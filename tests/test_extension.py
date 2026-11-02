"""The Chrome extension's own scripts in a real (headless) browser, with chrome.* stubbed: where the folded tab
goes when another extension's tab is on the right edge, the popup opening the panel, and autofill with no PDF."""
import contextlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from jobsmith import db, devtools, extension, profile
from jobsmith.fill.base import browser_args
from conftest import FIXTURES

EXT = Path(__file__).resolve().parents[1] / "extension"
ESSAY = ("I want to work on hardware and software that has to be fast and has to be right. I like problems where a few "
         "milliseconds matter and where you can measure whether you got it. After I graduate I'd like to join a team "
         "building perception systems, and grow into someone who can own a system from the sensor to the model.")
FORM_ACTION = "/figma/jobs/5426468004"   # the saved Figma form posts back to its own posting
_SITE = {}


def _posting(fixture: str = "greenhouse_board_posting.html") -> str:
    """The saved Figma posting, served over local HTTP (not file://) so requests to its submit address are seen.
    greenhouse_figma_live.html is the same page with its dropdowns working (tests/fixtures/src/)."""
    if fixture not in _SITE:
        html = (FIXTURES / fixture).read_bytes()
        srv = _serve({FORM_ACTION: (200, "text/html", lambda body=None: html)})
        _SITE[fixture] = f"http://127.0.0.1:{srv.server_port}{FORM_ACTION}"
    return _SITE[fixture]


def _chromium() -> str:
    """The browser the tests launch, so the skip check and the launch agree."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        return os.environ.get("JOBSMITH_CHROMIUM_PATH") or pw.chromium.executable_path


CHROMIUM = _chromium()
browser = pytest.mark.skipif(not Path(CHROMIUM).exists(), reason="no browser available")

# The engine as the extension sees it through background.js: running, answers by label, and a resume PDF only
# when a test sets __opts.resume. __opts.noReceiver: the tab has no Jobsmith script until the popup injects one.
CHROME_STUB = """
window.__calls = []; window.__listeners = []; window.__store = Object.assign({}, window.__initialStore || {});
window.__opts = window.__opts || {}; let injected = false;
window.__tabAnswers = new Promise(r => { window.__letTabAnswer = r; });
const ANSWERS = {"First Name": "Alex", "Last Name": "Rivera", "Email": "alex.rivera@example.com", "Phone": "617-555-0123"};
const reply = msg => {
  if (msg.type === "ping") return { ok: true, data: { ai: "Gemini", ai_ok: true, resume: __opts.resume || null } };
  if (msg.type === "answers") return { ok: true, data: { job_id: "j1", resume: __opts.resume || null, error: null,
    answers: msg.body.fields.map((f, i, all) => f.type === "file" ? { id: f.id, file: "resume", kind: "file" }
                                                       : Object.assign({ id: f.id, value: ANSWERS[f.label] || "", kind: "standard" },
                                                                       (__opts.answers || {})[f.label] || {},
                                                                       (__opts.byName || {})[f.name] || {},
                                                                       // byNth: {label: [answer for the 1st box, the 2nd...]}
                                                                       ((__opts.byNth || {})[f.label] || [])[
                                                                         all.slice(0, i).filter(x => x.label === f.label).length] || {})) } };
  if (msg.type === "generate") return { ok: true, data: Object.assign({ text: "", based_on: [], error: null }, __opts.generate || {}) };
  if (msg.type === "fixes") return __opts.fixes ? { ok: true, data: __opts.fixes } : { ok: false, error: "not in this test" };
  if (msg.type === "fix") return __opts.fixAnswer ? { ok: true, data: __opts.fixAnswer } : { ok: false, error: "Type an answer first." };
  if (msg.type === "form-report") return { ok: true, data: { url: "https://github.com/rawcache/Jobsmith/issues/new?title=x" } };
  if (msg.type === "file") return __opts.resume ? { ok: true, name: __opts.resume, type: "application/pdf", b64: btoa("%PDF-1.4") }
                                                 : { ok: false, error: "No file for that yet." };
  return { ok: false, error: "not in this test" };
};
Object.defineProperty(window, "chrome", { configurable: true, value: {
  runtime: { lastError: undefined, onMessage: { addListener: f => __listeners.push(f) },
             sendMessage: (msg, cb) => { __calls.push(msg); setTimeout(() => cb && cb(reply(msg)), 0); } },
  storage: { local: { get: async k => ({ [k]: __store[k] }), set: async o => { Object.assign(__store, o); } } },
  tabs: { query: async () => [{ id: 1, url: "https://example.com", title: "Posting" }],
          sendMessage: async (id, msg) => { __calls.push({ tab: msg });
            if (__opts.holdTab) await window.__tabAnswers;    // a page that answers only when the test lets it
            if (__opts.noReceiver && !injected) throw new Error("Could not establish connection. Receiving end does not exist.");
            return { application: true, fields: 12 }; } },
  scripting: { executeScript: async t => { __calls.push({ inject: t.files, allFrames: !!t.target.allFrames }); injected = true; return []; } },
}});
"""


@pytest.fixture
async def page():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, executable_path=CHROMIUM, args=browser_args())
        p = await b.new_page(viewport={"width": 1280, "height": 900})
        yield p
        await b.close()
        # Reported even when a submit's navigation broke an earlier step of the test.
        assert not getattr(p, "_jobsmith_navigations", []), f"autofill navigated (submitted?): {p._jobsmith_navigations}"
        assert not getattr(p, "_jobsmith_sent", []), f"autofill sent the application: {p._jobsmith_sent}"


def _stub(store: dict, **opts) -> str:
    return f"window.__initialStore = {json.dumps(store)}; window.__opts = {json.dumps(opts)};" + CHROME_STUB


async def _load(page, store: dict, other_tab: bool = True, wait: bool = True, fixture: str = "greenhouse_board_posting.html",
                **opts):
    await page.add_init_script(_stub(store, **opts))
    await page.goto(_posting(fixture))
    await _watch_for_submits(page)
    if not other_tab:
        await page.evaluate("document.getElementById('other-extension-tab').remove()")
    await page.add_script_tag(path=str(EXT / "content.js"))
    if wait:
        await page.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.wrap')")


# Where job sites take a finished application, besides the form's own action: Greenhouse's /applications, Lever's
# /apply, Ashby's submit operation. Saving a draft, analytics and logging aren't sending it.
SUBMIT_URL = re.compile(r"/(applications?|apply|submit)(/|$|\?)|submit\w*application", re.I)
NOT_A_SUBMIT = re.compile(r"/(autosave|save_?drafts?|drafts?|analytics|collect|track(ing)?|telemetry|metrics|logs?)(/|$)", re.I)


def _is_submit(url: str, method: str, actions: list[str]) -> bool:
    """A request that sends an application: a POST/PUT/PATCH (sendBeacon is a POST) to the form's action or a
    job site's submit address, and not an autosave or analytics call."""
    if method.upper() not in ("POST", "PUT", "PATCH"):
        return False
    bare = lambda u: urlsplit(u)._replace(query="", fragment="").geturl()
    if bare(url) in {bare(a) for a in actions}:        # the form's own action always counts
        return True
    parts = urlsplit(url)
    noise = NOT_A_SUBMIT.search(parts.path) or parts.hostname.endswith(("sentry.io", "google-analytics.com"))
    return bool(SUBMIT_URL.search(url)) and not noise


async def _watch_for_submits(page, frame=None):
    """Autofill must never send an application. From here on, record every submit event in the form's frame, every
    navigation of any frame, and every request that sends the form quietly (fetch, XHR, sendBeacon);
    `_never_submitted` and the page fixture fail the test on any of them. It only listens: a real submit goes
    ahead, so it can't be hidden."""
    target = frame or page
    await target.evaluate("""window.__submits = 0;
      document.addEventListener("submit", () => { window.__submits++; }, true); 0""")   # 0: evaluate would call a function
    actions = await target.evaluate("[...document.forms].map(f => f.action)")
    page._jobsmith_navigations, page._jobsmith_sent = [], []
    page.on("framenavigated", lambda f: page._jobsmith_navigations.append(f.url))
    page.on("request", lambda r: _is_submit(r.url, r.method, actions) and page._jobsmith_sent.append(f"{r.method} {r.url}"))
    page._jobsmith_form_frame = target


async def _never_submitted(page):
    await page.wait_for_timeout(500)                     # a submit lands within this; the fixture checks again at the end
    assert page._jobsmith_navigations == [], f"autofill navigated: {page._jobsmith_navigations}"
    assert page._jobsmith_sent == [], f"autofill sent the application: {page._jobsmith_sent}"
    assert await page._jobsmith_form_frame.evaluate("window.__submits") == 0, "autofill submitted the form"


@pytest.mark.parametrize("method, url, sends", [
    ("POST", "https://boards.greenhouse.io/figma/jobs/5426468004", True),          # the form's action
    ("POST", "https://boards-api.greenhouse.io/v1/boards/figma/applications", True),
    ("POST", "https://jobs.lever.co/acme/1234/apply", True),
    ("POST", "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiSubmitSingleApplicationFormAction", True),
    ("GET", "https://boards.greenhouse.io/figma/jobs/5426468004", False),          # reading the posting
    ("POST", "https://jobs.ashbyhq.com/api/autosave", False),
    ("POST", "https://www.google-analytics.com/g/collect?v=2", False),
    ("POST", "https://boards.greenhouse.io/track/apply_click", False),
    ("POST", "https://jobs.example.com/tracksmith/jobs/123?utm=analytics", True),    # the action, whatever its name
    ("POST", "https://jobs.example.com/api/tracksmith/applications", True),          # "track" in a name isn't tracking
    ("POST", "https://o1.ingest.sentry.io/api/5/envelope/?apply=1", False),
])
def test_what_counts_as_sending_an_application(method, url, sends):
    actions = ["https://boards.greenhouse.io/figma/jobs/5426468004", "https://jobs.example.com/tracksmith/jobs/123"]
    assert _is_submit(url, method, actions) == sends


@browser
@pytest.mark.parametrize("send", ['fetch(f.action, {method: "POST", body: new FormData(f)})',
                                  '(() => { const x = new XMLHttpRequest(); x.open("POST", f.action); x.send(new FormData(f)); })()',
                                  'navigator.sendBeacon(f.action, new FormData(f))'])
async def test_the_submit_watcher_sees_a_quiet_submit(page, send):
    """The watcher itself, wired to a real page: a form sent in the background is caught."""
    await _load(page, {"panelOpen": False})
    await page.evaluate(f"(() => {{ const f = document.querySelector('form'); {send}; }})()")
    await page.wait_for_timeout(500)
    assert page._jobsmith_sent and page._jobsmith_sent[0].startswith("POST ") and FORM_ACTION in page._jobsmith_sent[0]
    page._jobsmith_sent.clear()                         # caught; don't fail the fixture for it


@browser
async def test_after_submit_the_thank_you_page_itself_is_sent_to_the_app_as_proof(page):
    await _load(page, {}, other_tab=False)
    posting = page.url
    await page.evaluate("""() => {
      sessionStorage.setItem("jobsmith-submit", JSON.stringify({ url: location.href, title: "Robotics Intern", at: Date.now() }));
      history.replaceState(null, "", "/confirmation");
      document.title = "Thank you | Acme";
      document.querySelector("main").innerHTML = "<h1>Thank you for applying!</h1>";   // the form gives way to thanks
    }""")
    await page.wait_for_function("__calls.some(c => c.type === 'submitted')", timeout=8000)
    body = await page.evaluate("__calls.find(c => c.type === 'submitted').body")
    assert body["url"] == posting and body["title"] == "Robotics Intern"            # the posting it was for
    c = body["confirmation"]                                                           # and the page that said thanks
    assert c["url"].endswith("/confirmation") and c["title"] == "Thank you | Acme" and "Thank you for applying!" in c["text"]
    page._jobsmith_navigations = [u for u in getattr(page, "_jobsmith_navigations", [])
                                  if not u.endswith("/confirmation")]      # this test's own stand-in for the site's


async def test_autofill_fills_one_step_of_a_job_site_form_in_a_frame_and_nothing_else(page):
    """Multi-step sites (iCIMS) show one step at a time in a frame: a page with just a phone number to give is still
    filled. A newsletter frame from another site asks for your email, but isn't an application: never typed into.
    Neither is a job-site frame that asks for nothing (a video's search box)."""
    pages = {"https://careers.acme.test/": b"<h1>Careers</h1>" + b"".join(
                 b"<iframe src='%s' style='width:600px;height:300px'></iframe>" % u.encode()
                 for u in ("https://careers-acme.icims.com/step", "https://news.acme.test/signup",
                           "https://careers-acme.icims.com/video")),
             "https://careers-acme.icims.com/step": b"<form><label for='phone'>Phone*</label><input id='phone' required></form>",
             "https://news.acme.test/signup": b"<form><label for='email'>Email*</label><input id='email' type='email' required>"
                                              b"<button>Sign up for news</button></form>",
             "https://careers-acme.icims.com/video": b"<p>A video</p><input id='q' aria-label='Phone'>"}
    await page.route("**/*", lambda r: r.fulfill(status=200, content_type="text/html", body=pages.get(r.request.url, b"")))
    await page.add_init_script(_stub({"panelOpen": False}))
    await page.goto("https://careers.acme.test/")
    frames = {f.url.rsplit("/", 1)[1]: f for f in page.frames if f != page.main_frame}
    await _watch_for_submits(page, frames["step"])
    for f in frames.values():
        await f.wait_for_selector("input")
        await f.add_script_tag(path=str(EXT / "content.js"))
        await f.evaluate("__listeners.forEach(l => l({type: 'fill'}, {}, () => {})); 0")
    await frames["step"].wait_for_function("document.getElementById('phone').value === '617-555-0123'")
    await page.wait_for_timeout(1000)
    assert await frames["signup"].input_value("#email") == ""
    assert await frames["video"].input_value("#q") == ""
    await _never_submitted(page)


def test_popup_and_page_script_share_one_list_of_job_sites():
    find = lambda f: re.search(r"const JOB_SITES = (/.+/i);", (EXT / f).read_text()).group(1)
    assert find("popup.js") == find("content.js")


# Opened as a page, the popup's "active tab" is itself: point it at the careers page, the oldest tab (a setup page
# that is still closing may be listed too).
ONLY_THE_CAREERS_TAB = """const q = chrome.tabs.query.bind(chrome.tabs);
    chrome.tabs.query = async () => { const me = await chrome.tabs.getCurrent();
                                      return (await q({})).filter(t => t.id !== me.id).sort((a, b) => a.id - b.id).slice(0, 1); };"""


@browser
async def test_popup_only_reaches_the_six_job_sites(page):
    await page.add_init_script(_stub({}))
    await page.goto((EXT / "popup.html").resolve().as_uri())
    hosts = {"boards.greenhouse.io": True, "job-boards.eu.greenhouse.io": True, "jobs.lever.co": True,
             "jobs.ashbyhq.com": True, "acme.wd5.myworkdayjobs.com": True, "careers-acme.icims.com": True,
             "jobs.smartrecruiters.com": True, "greenhouse.io.evil.test": False, "notgreenhouse.io": False,
             "lever.co.example.com": False, "example.com": False}
    seen = await page.evaluate("hs => hs.map(h => JOB_SITES.test(h))", list(hosts))
    assert dict(zip(hosts, seen)) == hosts
    manifest = json.loads((EXT / "manifest.json").read_text())
    sites = ["greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "icims.com", "smartrecruiters.com"]
    assert sorted(manifest["host_permissions"]) == sorted(["http://127.0.0.1/*", "http://localhost/*"] +
                                                         [f"https://*.{s}/*" for s in sites])   # nothing else
    assert "optional_host_permissions" not in manifest and sorted(manifest["permissions"]) == ["activeTab", "scripting", "storage"]


def _rect(js: str) -> str:
    return f"(() => {{ const r = {js}.getBoundingClientRect(); return {{l: r.left, t: r.top, r: r.right, b: r.bottom}}; }})()"


OURS = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.tab')"
THEIRS = "document.querySelector('#other-extension-tab').shadowRoot.querySelector('.t')"


@browser
async def test_folded_tab_stays_clear_of_another_extensions_tab_and_opens(page):
    await _load(page, {"panelOpen": False})
    ours, theirs = await page.evaluate(_rect(OURS)), await page.evaluate(_rect(THEIRS))
    overlap = ours["l"] < theirs["r"] and theirs["l"] < ours["r"] and ours["t"] < theirs["b"] and theirs["t"] < ours["b"]
    assert not overlap, (ours, theirs)
    x, y = (ours["l"] + ours["r"]) / 2, (ours["t"] + ours["b"]) / 2
    assert await page.evaluate(f"document.elementFromPoint({x}, {y}).id") == "jobsmith-panel"    # nothing covers it
    await page.mouse.click(x, y)
    await page.wait_for_function("document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.p')")


@browser
async def test_folded_tab_keeps_its_place_when_the_edge_is_free(page):
    await _load(page, {"panelOpen": False}, other_tab=False)
    ours = await page.evaluate(_rect(OURS))
    assert ours["r"] == 1280 and ours["t"] == 72


@browser
async def test_tab_sees_another_extensions_tab_under_a_page_layer(page):
    """A see-through page element over the other extension's tab mustn't hide it from Jobsmith."""
    await page.add_init_script(_stub({"panelOpen": False}))
    await page.goto(_posting())
    await page.evaluate("""const d = document.createElement('div');
      d.style.cssText = 'position:absolute;top:0;right:0;width:120px;height:400px;z-index:2147483647';
      document.body.appendChild(d)""")
    await page.add_script_tag(path=str(EXT / "content.js"))
    await page.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.tab')")
    ours, theirs = await page.evaluate(_rect(OURS)), await page.evaluate(_rect(THEIRS))
    assert ours["t"] >= theirs["b"] or ours["b"] <= theirs["t"] or ours["l"] >= theirs["r"], (ours, theirs)


@browser
async def test_toolbar_popup_opens_the_full_panel(page):
    await _load(page, {"panelOpen": False})
    await page.evaluate("__listeners.forEach(f => f({type: 'open'}, {}, () => {}))")
    panel = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.p')"
    await page.wait_for_function(f"{panel}?.querySelector('.fill')")
    assert (await page.evaluate(_rect(panel)))["t"] == 72                               # high enough to fit


@browser
async def test_toolbar_popup_opens_the_panel_before_the_page_script_has_started(page):
    """The popup can ask before the page's own start-up has drawn anything: one panel, open."""
    await _load(page, {"panelOpen": False}, wait=False)
    await page.evaluate("__listeners.forEach(f => f({type: 'open'}, {}, () => {}))")
    await page.wait_for_timeout(1500)                                                  # start() has run by now
    assert await page.evaluate("document.querySelectorAll('#jobsmith-panel').length") == 1
    assert await page.evaluate("!!document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.p .fill')")


@browser
async def test_autofill_without_a_resume_pdf_fills_the_rest(page):
    await _load(page, {"panelOpen": True})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')")
    text = await page.evaluate(f"{note}.innerText")
    assert "Add your resume PDF to attach it" in text
    assert await page.input_value("#first_name") == "Alex" and await page.input_value("#email") == "alex.rivera@example.com"
    assert await page.input_value("#phone") == "617-555-0123"
    assert await page.evaluate("document.getElementById('resume').files.length") == 0
    assert not await page.evaluate("__calls.some(c => c.type === 'file')")             # didn't even ask for one
    needs = text.split("Needs you:")[1] if "Needs you:" in text else ""
    assert "Attach" not in needs and "Resume" not in needs                            # said once, not as a blocker
    await _never_submitted(page)


WHERE = "#question_12497123004"     # "From where do you intend to work?" on the saved Figma form
WHY = "#question_12497120004"       # "Why do you want to join Figma?"


@browser
async def test_autofill_never_types_an_essay_where_the_figma_form_asks_where(page):
    """The engine's answer for "From where do you intend to work?" was the 'why Figma' paragraph. Even if that comes
    back again, the extension leaves the box empty and lists it under Needs you. A reused essay that never says
    Figma is filled but listed under Check these, and isn't counted as filled."""
    await _load(page, {"panelOpen": True}, answers={
        "From where do you intend to work?": {"value": ESSAY, "kind": "voice", "qkind": "location"},
        "Other Website": {"value": ESSAY, "kind": "voice", "qkind": "short"},
        "Preferred First Name": {"value": "", "hold": "asks for a name, but the answer isn't one", "qkind": "short"},
        "Why do you want to join Figma?": {"value": ESSAY, "kind": "voice", "qkind": "essay",
                                           "check": "generic, doesn't mention Figma: check this"}})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')")
    text = await page.evaluate(f"{note}.innerText")
    assert await page.input_value(WHERE) == "" and await page.input_value("#question_12497119004") == ""
    needs, check = text.split("Needs you:")[1].split("Check these:")
    assert "From where do you intend to work?" in needs and "isn't a place" in needs
    assert "Other Website" in needs and "Preferred First Name" in needs
    assert "Why do you want to join Figma?" in check and "generic" in check
    assert await page.input_value(WHY) == ESSAY                                       # there to edit, flagged
    filled = await page.evaluate("[...document.querySelectorAll('input,textarea')].filter(e => e.value).map(e => e.id)")
    assert WHY[1:] in filled and f"Filled {len(filled) - 1} of" in text, filled       # the flagged essay isn't counted
    assert await page.evaluate(f"document.querySelector('{WHERE}').style.outline") != ""
    await _never_submitted(page)


COUNTRY_MIRROR = ".phone-input__country input[aria-hidden='true']"   # react-select's hidden copy, for "required"


@browser
async def test_autofill_never_types_the_phone_number_into_the_phone_country_box(page):
    """The Figma form's phone has a Country select beside it, with a hidden required copy inside the Phone fieldset.
    That copy was read as a "Phone" field and got the number. It isn't a field; and a number offered for the
    Country box itself is held, not typed."""
    await _load(page, {"panelOpen": True}, answers={"Country": {"value": "617-555-0123", "qkind": "location"}})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')")
    assert await page.input_value("#phone") == "617-555-0123"
    assert await page.input_value(COUNTRY_MIRROR) == ""
    assert await page.input_value("#country") == ""
    needs = (await page.evaluate(f"{note}.innerText")).split("Needs you:")[1]
    assert "Country" in needs and "isn't a place" in needs
    assert await page.evaluate("[...document.querySelectorAll('input')].filter(e => e.value === '617-555-0123').length") == 1
    await _never_submitted(page)


AUTHORIZED = "#question_12497125004"   # "Are you authorized to work in the country for which you applied?"
WORKED_HERE = "#question_12497126004"  # "Have you ever worked for Figma before, ...?"


async def _shown(page, sel: str) -> str:
    """What a react-select box shows as picked."""
    return await page.evaluate(f"document.querySelector('{sel}').closest('.select__control')"
                               ".querySelector('.select__single-value')?.innerText || ''")


@browser
async def test_panel_shows_where_legal_answers_came_from_and_holds_worked_here_before(page):
    await _load(page, {"panelOpen": True}, fixture="greenhouse_figma_live.html", answers={
        "Are you authorized to work in the country for which you applied?": {
            "value": "Yes", "kind": "answer_bank", "source": "Profile: Authorized to work in the US? (you confirmed it)"},
        "Have you ever worked for Figma before, as an employee or a contractor/consultant?": {
            "value": "", "kind": "answer_bank", "hold": "nothing confirmed says, so answer it yourself"}})
    await page.wait_for_function("document.querySelectorAll('input[required][aria-hidden=true]').length === 4")
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    assert await _shown(page, AUTHORIZED) == "Yes"
    assert await _shown(page, WORKED_HERE) == ""
    text = await page.evaluate(f"{note}.innerText")
    needs, sources = text.split("Needs you:")[1].split("Where these answers came from:")
    assert "worked for Figma before" in needs and "nothing confirmed says" in needs
    assert "authorized to work in the country for which you applied?: Yes. Profile: Authorized to work in the US? " \
           "(you confirmed it)" in sources
    assert "worked for Figma" not in sources
    await _never_submitted(page)


@browser
async def test_report_this_form_sends_the_questions_and_never_what_you_typed(page):
    """The panel's "Report this form": the engine gets each question, its kind, whether it's required and its choices,
    from which it builds a GitHub issue link that background.js opens for you to read and post. Nothing typed."""
    await _load(page, {"panelOpen": True}, fixture="greenhouse_figma_live.html")
    await page.fill("#first_name", "Alex")
    panel = "document.querySelector('#jobsmith-panel').shadowRoot"
    await page.evaluate(f"{panel}.querySelector('.report').click()")
    await page.wait_for_function(f"{panel}.querySelector('.note')?.innerText.includes('Opened a GitHub issue')")
    [sent] = await page.evaluate("__calls.filter(c => c.type === 'form-report')")
    assert "/figma/jobs/" in sent["body"]["url"] and len(sent["body"]["fields"]) > 5
    assert all(set(f) == {"label", "qtype", "required", "options"} for f in sent["body"]["fields"])
    assert "Alex" not in json.dumps(sent) and any(f["label"].startswith("First Name") for f in sent["body"]["fields"])
    bg = (EXT / "background.js").read_text(encoding="utf-8")       # only ever opens a new issue on Jobsmith's repo
    assert 'REPORT_TO = "https://github.com/rawcache/Jobsmith/issues/new?"' in bg and ".startsWith(REPORT_TO)" in bg


@browser
async def test_report_this_form_includes_a_form_in_a_frame_two_deep(page):
    """A company page wrapping a job site's form, two frames down: the report holds the form's questions, told by
    Jobsmith's script in that frame, still without what's typed."""
    posting = b'<script type="application/ld+json">{"@type": "JobPosting", "title": "Intern"}</script><h1>Intern</h1>'
    pages = {"https://careers.acme.test/": posting + _framed("https://embed.acme.test/wrap"),
             "https://embed.acme.test/wrap": _framed("https://apply.unlisted-ats.test/form"),
             "https://apply.unlisted-ats.test/form": APPLY_FORM}
    await page.route("**/*", lambda r: r.fulfill(status=200, content_type="text/html", body=pages.get(r.request.url, b"")))
    await page.add_init_script(_stub({"panelOpen": True}))         # every frame gets the stand-in chrome
    await page.goto("https://careers.acme.test/")
    await page.wait_for_load_state("load")
    form = next(f for f in page.frames if f.url.endswith("/form"))
    await form.fill("#fn", "Alex")
    for f in page.frames:                                          # Jobsmith's script in every frame, as allFrames
        await f.add_script_tag(path=str(EXT / "content.js"))
    panel = "document.querySelector('#jobsmith-panel').shadowRoot"
    await page.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.report')")
    # the popup's own "who's there?" at the same moment: its answers carry no questions and mustn't wipe the report's
    await page.evaluate(f"{panel}.querySelector('.report').click(); __listeners.forEach(f => f({{type: 'info'}}, {{}}, () => {{}}))")
    await page.wait_for_function(f"{panel}.querySelector('.note')?.innerText.includes('Opened a GitHub issue')")
    [sent] = await page.evaluate("__calls.filter(c => c.type === 'form-report')")
    assert [f["label"] for f in sent["body"]["fields"]] == ["First Name", "Last Name", "Email", "Phone"], sent
    assert "Alex" not in json.dumps(sent)


RAMP_AUTH = "Are you currently based in the U.S., Canada, LATAM, and/or currently authorized to work in one of these locations?"
RAMP_REACT = ("Have you built and deployed production-level applications using React, TypeScript (or JavaScript), and other "
              "modern front-end technologies?")
RAMP_TAKE_HOME = "Are you comfortable completing a frontend take-home assessment?"


async def _pressed(page, question: str) -> str:
    """The pressed button under an Ashby Yes/No question, '' when neither is."""
    return await page.evaluate("""q => { const e = [...document.querySelectorAll('.ashby-application-form-field-entry')]
        .find(x => x.querySelector('label')?.innerText.startsWith(q));
        return [...e.querySelectorAll('button[aria-pressed=true]')].map(b => b.innerText.trim()).join(); }""", question)


@browser
async def test_autofill_presses_ashby_yes_no_buttons_on_the_saved_ramp_form(page):
    """The saved Ramp form (Ashby): its Yes/No questions are two buttons beside a hidden checkbox, so a scan that
    skips hidden inputs missed all four. Autofill presses the answer's button, leaves the ones it has no answer
    for under Needs you, and says where the work authorization answer came from. Ashby autosaves each answer with
    a POST; that isn't sending the application, and nothing here is."""
    saves = []
    page.on("request", lambda r: "op=ApiSetFormValue" in r.url and saves.append(r.method))
    await _load(page, {"panelOpen": True}, fixture="ashby_ramp_form.html", answers={
        "Legal Name": {"value": "Alex Rivera", "kind": "standard"},
        RAMP_AUTH: {"value": "Yes", "kind": "answer_bank", "source": "Profile: Authorized to work in the US? (you confirmed it)"},
        RAMP_REACT: {"value": "No", "kind": "generated"}})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    assert await page.input_value("#_systemfield_name") == "Alex Rivera"
    assert await _pressed(page, RAMP_AUTH) == "Yes"
    assert await page.is_checked('[name="9c5b0358-1bae-4437-b3e6-e3541fdcf473"]')       # the answer Ashby sends
    assert await _pressed(page, RAMP_REACT) == "No"
    assert await _pressed(page, RAMP_TAKE_HOME) == ""
    text = await page.evaluate(f"{note}.innerText")
    needs, sources = text.split("Needs you:")[1].split("Where these answers came from:")
    assert RAMP_TAKE_HOME in needs and RAMP_AUTH[:40] not in needs
    assert "Profile: Authorized to work in the US? (you confirmed it)" in sources
    assert saves and set(saves) == {"POST"}                     # autosaved, and the watcher let that be
    assert await page.evaluate("window.__submits") == 0
    await _never_submitted(page)


@browser
async def test_autofill_labels_a_lone_checkbox_by_its_own_label(page):
    """Skipping an option's own text when naming a radio question ("SMS") never applies to a lone checkbox."""
    html = (b"<form><label for='fn'>First Name</label><input id='fn'><label for='em'>Email</label><input id='em'>"
            b"<label for='ph'>Phone</label><input id='ph'>"
            b"<div><label><input type='checkbox' name='terms'> I agree to the privacy policy</label></div>"
            b"<div><p>Are you authorized to work in Canada?</p><label><input type='checkbox' name='ca'> Yes</label></div></form>")
    await page.route("**/*", lambda r: r.fulfill(status=200, content_type="text/html", body=html))
    await page.add_init_script(_stub({"panelOpen": False}))
    await page.goto("https://careers.acme.test/apply")
    await _watch_for_submits(page)
    await page.add_script_tag(path=str(EXT / "content.js"))
    await page.evaluate("__listeners.forEach(l => l({type: 'fill'}, {}, () => {})); 0")
    await page.wait_for_function("__calls.some(c => c.type === 'answers')")
    labels = await page.evaluate("__calls.find(c => c.type === 'answers').body.fields.map(f => f.label)")
    assert "I agree to the privacy policy" in labels
    assert "Are you authorized to work in Canada?" in labels and "Yes" not in labels      # "Yes" isn't the question
    await _never_submitted(page)


@browser
async def test_the_submit_watcher_sees_ashbys_submit_on_the_saved_ramp_form(page):
    """The other side of the watcher on Ashby: pressing Submit Application (which sends Ashby's submit operation,
    with no <form> on the page) is caught."""
    await _load(page, {"panelOpen": False}, fixture="ashby_ramp_form.html")
    await page.click(".ashby-application-form-submit-button")
    await page.wait_for_timeout(500)
    assert page._jobsmith_sent and "op=ApiSubmitSingleApplicationFormAction" in page._jobsmith_sent[0]
    page._jobsmith_sent.clear()                         # caught; don't fail the fixture for it


LEVER_LOCATION = "Current location"


@browser
async def test_autofill_on_the_saved_lever_form_picks_the_place_and_never_signs(page):
    """The saved Palantir form (Lever): each question is read by its own words (not its dropdown's options), the
    place is picked from Lever's lookup (typing alone is emptied when the box is left), and the disability question
    is left blank with its signature (Name, Date) never shown or filled. The engine is told each field's name on
    the page, so it knows Lever's eeo[…] fields. Nothing is sent."""
    await _load(page, {"panelOpen": True}, fixture="lever_palantir_form.html", answers={
        "Full name": {"value": "Alex Rivera", "kind": "standard"},
        LEVER_LOCATION: {"value": "Boston, MA", "pick": "Boston, Massachusetts, United States", "kind": "standard"},
        "Veteran status": {"value": "I am not a protected veteran", "kind": "answer_bank"},
        "Disability status": {"value": "", "kind": "answer_bank"}})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    sent = await page.evaluate("__calls.find(c => c.type === 'answers').body.fields")
    by_label = {f["label"]: f for f in sent}
    assert by_label["Disability status"]["name"] == "eeo[disability]"
    assert by_label["Resume/CV"]["required"] and not any("Select ..." in f["label"] for f in sent)
    assert await page.input_value('[name="name"]') == "Alex Rivera"
    assert await page.input_value("#location-input") == "Boston, MA, USA"
    assert '"Boston, MA, USA"' in await page.input_value("#selected-location")
    assert await page.eval_on_selector('[name="eeo[veteran]"]', "e => e.selectedOptions[0].text") == \
        "I am not a protected veteran"
    assert await page.input_value("#disabilitySelectElement") == ""
    assert not await page.is_visible('[name="eeo[disabilitySignature]"]')
    assert await page.input_value('[name="eeo[disabilitySignature]"]') == ""
    assert await page.evaluate("window.__submits") == 0
    await _never_submitted(page)


@browser
async def test_autofill_leaves_levers_place_for_you_when_its_not_exactly_one(page):
    """Plain "Boston" matches four of Lever's places: which one is yours isn't autofill's guess. The box is left
    empty (Lever empties it anyway when the list closes) and nothing is sent."""
    await _load(page, {"panelOpen": True}, fixture="lever_palantir_form.html", answers={
        LEVER_LOCATION: {"value": "Boston", "kind": "standard"}})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    assert await page.input_value("#location-input") == "" and await page.input_value("#selected-location") == ""
    await _never_submitted(page)


@browser
async def test_autofill_picks_levers_place_when_your_state_is_spelled_out(page):
    """Your profile says "Boston, Massachusetts" and Lever lists "Boston, MA, USA": the same place, picked."""
    await _load(page, {"panelOpen": True}, fixture="lever_palantir_form.html", answers={
        LEVER_LOCATION: {"value": "Boston, Massachusetts", "kind": "standard"}})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    assert await page.input_value("#location-input") == "Boston, MA, USA"
    await _never_submitted(page)


@browser
async def test_the_submit_watcher_sees_levers_submit_on_the_saved_palantir_form(page):
    """The other side of the watcher on Lever: Submit application (after Lever's captcha step) posts the form to
    its own address, and that is caught. Required fields are switched off here so the browser lets it through."""
    await _load(page, {"panelOpen": False}, fixture="lever_palantir_form.html")
    await page.eval_on_selector("#application-form", "f => { f.noValidate = true; }")
    await page.click("#btn-submit")
    await page.wait_for_timeout(500)
    assert page._jobsmith_sent and page._jobsmith_sent[0].startswith("POST ")
    page._jobsmith_sent.clear()                         # caught; don't fail the fixture for it


@browser
async def test_autofill_fills_nothing_on_workdays_create_account_page(page):
    """Workday's saved create-account page, served at NVIDIA's own Workday address so the panel opens as it would
    there. Pressing Fill does nothing: no email typed, "I agree" left unticked, nothing sent to the engine. Making
    the account is yours (rule 5)."""
    html = (FIXTURES / "workday_nvidia_create_account.html").read_text(encoding="utf-8")
    url = "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/x/apply/applyManually"

    async def serve(route):
        if route.request.url.split("?")[0] == url:
            await route.fulfill(status=200, content_type="text/html", body=html)
        else:
            await route.abort()
    await page.route("https://**/*", serve)
    await page.add_init_script(_stub({"panelOpen": True}))
    await page.goto(url)
    await page.add_script_tag(path=str(EXT / "content.js"))
    await page.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.wrap')")
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('yours to do')", timeout=10000)
    assert not await page.evaluate("__calls.some(c => c.type === 'answers')")
    assert await page.eval_on_selector_all("input", "els => els.filter(e => e.value && e.type !== 'hidden' && "
                                           "e.type !== 'checkbox').length") == 0
    assert not await page.eval_on_selector_all('input[type="checkbox"]', "els => els.some(e => e.checked)")
    assert await page.evaluate("window.__signInPresses") == 0
    await page.evaluate("document.querySelectorAll('input[type=password]').forEach(e => { e.type = 'text'; })")
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")   # "Show password", then Fill
    await page.wait_for_timeout(500)
    assert not await page.evaluate("__calls.some(c => c.type === 'answers')")
    await page.evaluate("document.querySelectorAll('input[name*=assword], input[id*=assword]').forEach(e => { "
                        "e.type = 'tel'; e.autocomplete = 'new-password'; })")       # drawn as a number pad
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    await page.wait_for_timeout(500)
    assert not await page.evaluate("__calls.some(c => c.type === 'answers')")


@browser
@pytest.mark.parametrize("fixture, url", [
    ("icims_idemia_email_frame.html",
     "https://uscareers-idemia.icims.com/jobs/8707/full-stack-software-engineering-internship/login?in_iframe=1"),
    ("icims_idemia_login.html", "https://login.icims.com/u/login/identifier"),
])
async def test_autofill_fills_nothing_on_icims_sign_in(page, fixture, url):
    """iCIMS's "Enter Your Information" (Email, then Next, which finds your account or starts one) and its login
    page, saved read-only from IDEMIA and served at their own addresses. Neither has a password box showing, and
    both are still a sign-in: Fill types no email and asks the engine nothing."""
    html = (FIXTURES / fixture).read_text(encoding="utf-8")

    async def serve(route):
        if route.request.url.split("?")[0] == url.split("?")[0]:
            await route.fulfill(status=200, content_type="text/html", body=html)
        else:
            await route.abort()
    await page.route("https://**/*", serve)
    await page.add_init_script(_stub({"panelOpen": True}))
    await page.goto(url)
    await page.add_script_tag(path=str(EXT / "content.js"))
    await page.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.wrap')")
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('yours to do')", timeout=10000)
    assert not await page.evaluate("__calls.some(c => c.type === 'answers')")
    assert await page.eval_on_selector_all("input", "els => els.filter(e => e.value && !['hidden', 'submit']"
                                           ".includes(e.type)).length") == 0
    assert await page.evaluate("window.__signInPresses") == 0


@browser
async def test_autofill_never_reads_a_honeypot(page):
    """Workday's hidden box, word for word, added to the saved Lever form: the engine is never asked about it, and
    it stays empty."""
    await page.add_init_script("""document.addEventListener('DOMContentLoaded', () => document.querySelector('form')
      .insertAdjacentHTML('beforeend', '<label for="hp">Enter website. This input is for robots only, do not enter if ' +
      "you're human.</label><input id=hp name=website type=text>"));""")
    await _load(page, {"panelOpen": True}, fixture="lever_palantir_form.html", answers={
        "Full name": {"value": "Alex Rivera", "kind": "standard"}})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    await page.wait_for_function("__calls.some(c => c.type === 'answers')", timeout=30000)
    labels = [f["label"] for f in await page.evaluate("__calls.find(c => c.type === 'answers').body.fields")]
    assert "Full name" in labels and not [l for l in labels if "robots" in l], labels
    assert await page.input_value("#hp") == ""
    await _never_submitted(page)


@browser
async def test_a_disability_box_named_pwd_is_a_question_not_a_password(page):
    """"PWD" also means a person with a disability. A checkbox named is_pwd (or pwd) is a question the engine is
    asked about, and it doesn't make the page look like a sign-in: Fill still fills."""
    await page.add_init_script("""document.addEventListener('DOMContentLoaded', () => document.querySelector('form')
      .insertAdjacentHTML('beforeend', '<label><input type=checkbox name=is_pwd id=is_pwd> I am a person with a ' +
      'disability (PWD)</label><label><input type=checkbox name=pwd> PWD card holder</label>'));""")
    await _load(page, {"panelOpen": True}, fixture="lever_palantir_form.html", answers={
        "Full name": {"value": "Alex Rivera", "kind": "standard"}})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    await page.wait_for_function("__calls.some(c => c.type === 'answers')", timeout=30000)
    labels = [f["label"] for f in await page.evaluate("__calls.find(c => c.type === 'answers').body.fields")]
    assert "I am a person with a disability (PWD)" in labels and "PWD card holder" in labels, labels
    assert not await page.is_checked("#is_pwd")
    await _never_submitted(page)


@browser
async def test_autofill_picks_greenhouse_dropdowns_and_the_city_from_its_lookup(page):
    """#19: on Greenhouse's form the dropdowns open on key-up, not key-down, so autofill left Country, Location
    (City) and every Yes/No box under Needs you. Now it opens them with a whole key press, picks the option that
    matches the answer, finds the city through the form's own lookup, and leaves a box with no matching option
    alone (never the first option)."""
    await _load(page, {"panelOpen": True}, fixture="greenhouse_figma_live.html", answers={
        "Country": {"value": "United States", "kind": "standard", "qkind": "location"},
        "Location (City)": {"value": "Boston, MA", "pick": "Boston, Massachusetts, United States", "kind": "standard",
                            "qkind": "location"},
        "Are you authorized to work in the country for which you applied?": {"value": "Yes", "kind": "standard"},
        "Have you ever worked for Figma before, as an employee or a contractor/consultant?": {"value": "Sometimes",
                                                                                               "kind": "standard"}})
    await page.wait_for_function("document.querySelectorAll('input[required][aria-hidden=true]').length === 4")
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    assert await _shown(page, "#country") == "United States +1"
    assert await _shown(page, "#candidate-location") == "Boston, Massachusetts, United States"   # not East Boston
    assert await _shown(page, AUTHORIZED) == "Yes"
    assert await _shown(page, WORKED_HERE) == ""                                        # no option says "Sometimes"
    assert await page.evaluate("window.__lookups") == ["Boston, MA"]                    # found through the lookup
    # react-select's hidden "required" copies: only the box left empty still has one
    assert await page.evaluate("document.querySelectorAll('input[required][aria-hidden=true]').length") == 1
    needs = (await page.evaluate(f"{note}.innerText")).split("Needs you:")[1]
    assert "worked for Figma before" in needs
    assert not any(x in needs for x in ("Country", "Location (City)", "authorized to work"))
    await _never_submitted(page)


@browser
async def test_autofill_leaves_a_city_the_lookup_doesnt_have_for_you(page):
    """A place with no matching option in the lookup isn't swapped for the nearest one."""
    await _load(page, {"panelOpen": True}, fixture="greenhouse_figma_live.html", answers={
        "Location (City)": {"value": "Springfield, IL", "pick": "Springfield, Illinois, United States",
                            "kind": "standard", "qkind": "location"}})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    assert await _shown(page, "#candidate-location") == ""
    assert "Location (City)" in (await page.evaluate(f"{note}.innerText")).split("Needs you:")[1]
    await _never_submitted(page)


@browser
async def test_autofill_picks_a_city_outside_the_us_as_you_wrote_it(page):
    """No US name to look for: the answer as written picks its own match from the lookup."""
    await _load(page, {"panelOpen": True}, fixture="greenhouse_figma_live.html", answers={
        "Location (City)": {"value": "Boston, England", "kind": "standard", "qkind": "location"}})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    assert await _shown(page, "#candidate-location") == "Boston, England, United Kingdom"
    await _never_submitted(page)


def test_a_us_city_is_named_the_way_place_lookups_name_it():
    from jobsmith import draft
    assert draft.location_full("Boston, MA") == "Boston, Massachusetts, United States"
    assert draft.location_full("Atlanta, Georgia") == ""     # could be the country; the answer as written still
                                                             # matches "Atlanta, Georgia, United States" in a lookup
    assert draft.location_full("Austin, Texas, USA") == "Austin, Texas, United States"
    assert draft.location_full("Atlanta, GA") == "Atlanta, Georgia, United States"
    assert draft.location_full("New York, NY") == "New York, New York, United States"
    assert draft.location_full("Washington, DC") == "Washington, District of Columbia, United States"
    for not_a_us_city in ("United States", "London, UK", "", "CA", "Tbilisi, Georgia", "Paris, Texas, France",
                          "Georgia, US", "Toronto, ON, Canada"):
        assert draft.location_full(not_a_us_city) == "", not_a_us_city


def test_a_phone_number_is_not_a_country():
    from jobsmith import classify, draft
    assert classify.question_kind("Country", "combobox") == "location"
    assert draft.shape_fits("location", "617-555-0123") and draft.shape_fits("location", "+1 (617) 555-0123")
    assert draft.shape_fits("location", "United States") is None and draft.shape_fits("location", "US") is None
    held = draft._checked({"label": "Country", "qtype": "combobox", "options": []},
                          {"answer": "617-555-0123", "confidence": 0.9, "kind": "standard"}, {"company": "Figma"})
    assert held["answer"] == "" and "isn't a place" in held["held"]


@browser
async def test_autofill_keeps_an_essay_asked_for_in_a_one_line_box(page):
    """The one-line-box check is about the question, not the box: 'Describe…' in an <input> takes sentences."""
    await page.add_init_script(_stub({"panelOpen": True}, answers={"Describe your most challenging project": {"value": ESSAY, "qkind": "essay"}}))
    await page.goto(_posting())
    await page.evaluate("""document.querySelector('#application-form').insertAdjacentHTML('afterbegin',
      '<label for="story">Describe your most challenging project</label><input id="story" type="text">'); 0""")
    await _watch_for_submits(page)
    await page.add_script_tag(path=str(EXT / "content.js"))
    await page.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.wrap')")
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    await page.wait_for_function("document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')?.innerText.includes('Filled')")
    assert await page.input_value("#story") == ESSAY
    await _never_submitted(page)


SHAPES = [(kind, value) for kind in ("location", "yes_no", "short", "essay", "open", "choice")
          for value in ("Boston, MA", "Yes", "No, but I could move within a month.", "I live in Boston.", "N/A", "NA",
                        "Two words", ESSAY, " ".join(["word"] * 41), "One. Two. Three.", "617-555-0123")]


@browser
async def test_extension_and_engine_agree_on_what_fits(page):
    """One set of rules: the engine says what each question asks for, and the extension's last check gives the
    same verdict as the engine's on every shape of answer."""
    from jobsmith import draft
    await _load(page, {"panelOpen": False})
    js = await page.evaluate("pairs => pairs.map(([k, v]) => __jobsmithFits(k, v))", SHAPES)
    assert js == [draft.shape_fits(k, v) or "" for k, v in SHAPES]


@browser
async def test_write_with_jobsmith_shows_held_and_generic_marks(page):
    """The button beside an open question: a held answer is never typed in and never says "Edit freely"; generic
    writing is typed in with "Check this"."""
    button = "document.getElementById('question_12497120004').nextElementSibling.shadowRoot"
    for gen, typed, says, never in (
            ({"text": "", "hold": "asks for a written answer, but the answer is a word or two", "qkind": "essay"},
             "", "Held for you", "Edit freely"),
            ({"text": "Yes", "qkind": "essay"}, "", "Held for you", "Edit freely"),          # the extension's own check
            ({"text": ESSAY, "qkind": "essay", "check": "generic, doesn't mention Figma: check this"},
             ESSAY, "Check this: generic, doesn't mention Figma", "Edit freely"),
            ({"text": ESSAY, "qkind": "essay", "issues": ["Number '600,000' not found in your facts"]},
             ESSAY, "Check this: Number '600,000' not found in your facts", "Edit freely"),
            ({"text": ESSAY, "qkind": "essay"}, ESSAY, "Edit freely", "Held")):
        await page.add_init_script(_stub({"panelOpen": False}, generate=gen))
        await page.goto(_posting())
        await _watch_for_submits(page)
        await page.add_script_tag(path=str(EXT / "content.js"))
        await page.wait_for_function(f"{button.replace('.shadowRoot', '')}?.shadowRoot")
        await page.evaluate(f"{button}.querySelector('button').click()")
        await page.wait_for_function(f"{button}.querySelector('span').innerText && !{button}.querySelector('button').disabled")
        note = await page.evaluate(f"{button}.querySelector('span').innerText")
        assert says in note and never not in note, (gen, note)
        assert await page.input_value(WHY) == typed
        await _never_submitted(page)


@browser
async def test_autofill_without_a_pdf_leaves_a_resume_you_attached_alone(page):
    await _load(page, {"panelOpen": True})
    await page.set_input_files("#resume", files=[{"name": "mine.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4"}])
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')")
    assert "Add your resume PDF" not in await page.evaluate(f"{note}.innerText")
    assert await page.evaluate("document.getElementById('resume').files[0].name") == "mine.pdf"
    assert await page.evaluate("document.getElementById('resume').style.outline") == ""
    await _never_submitted(page)


@browser
async def test_autofill_attaches_the_resume_pdf_when_there_is_one(page):
    await _load(page, {"panelOpen": True}, resume="Alex_Rivera_resume.pdf")
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')")
    assert "Add your resume PDF" not in await page.evaluate(f"{note}.innerText")
    assert await page.evaluate("document.getElementById('resume').files[0].name") == "Alex_Rivera_resume.pdf"
    await _never_submitted(page)


@browser
async def test_popup_marks_itself_ready_only_once_it_has_checked_the_page(page):
    """CI on macOS once read the popup's reload hint before the popup had finished reaching the page's frames (a fixed
    one-second wait). The popup now marks itself ready when it's done, and the tests wait for that: while the page
    hasn't answered, no mark; once it has, the mark comes after the panel was told to open."""
    await page.add_init_script(_stub({}, holdTab=True))
    await page.goto((EXT / "popup.html").resolve().as_uri())
    await page.wait_for_function("__calls.some(c => c.tab && c.tab.type === 'info')")   # asked; the page hasn't answered
    assert await page.evaluate("document.body.dataset.ready") is None
    await page.evaluate("__letTabAnswer()")
    await page.wait_for_selector("body[data-ready]", timeout=10000)
    assert await page.evaluate("__calls.filter(c => c.tab).map(c => c.tab.type)") == ["info", "open"]


def _fix(id, kind, title, unblocks, **kw):
    return {"id": id, "kind": kind, "title": title, "detail": "", "value": "", "unblocks": unblocks, "ready_after": 0,
            "jobs": [f"j{i}" for i in range(unblocks)], **kw}


FIXES = {"held": 56, "applications": [], "fixes": [
    _fix("resume_pdf", "resume_pdf", "Add your resume as a PDF", 56),
    _fix("profile:work_auth", "profile", "Confirm work authorization", 41, choices=["Yes", "No"]),
    _fix("essay:why_company", "essay", "Why do you want to join <img src=x onerror=window.__xss=1>?", 12),
    _fix("question:abc", "question", "Years with Kubernetes", 3)]}


async def _popup_fixes(page, **opts):
    await page.add_init_script(_stub({}, fixes=FIXES, **opts))
    await page.goto((EXT / "popup.html").resolve().as_uri())
    await page.wait_for_selector("#needs:not([hidden])")


@browser
async def test_popup_lists_what_held_applications_need_once_each(page):
    """The popup's Needs you: each fix once, with how many applications it unblocks, the resume PDF first; three at
    most, the rest counted. Titles from job sites are shown as text, never run as markup."""
    await _popup_fixes(page)
    rows = page.locator("#fixes .fix")
    assert await rows.count() == 3
    heads = [await rows.nth(i).locator(".fix-h").inner_text() for i in range(3)]
    assert heads[0].split("\n") == ["Add your resume as a PDF", "blocks every application"]
    assert heads[1].split("\n") == ["Confirm work authorization", "unblocks 41"]
    assert "<img src=x" in heads[2] and await page.evaluate("window.__xss") is None
    assert await page.inner_text("#needs-more") == "1 more in the dashboard."
    await rows.nth(0).locator("button").click()
    assert await page.evaluate("__calls.find(c => c.type === 'open')") == {"type": "open", "path": "/#/"}


@browser
async def test_popup_answer_goes_to_every_application_waiting_on_it(page):
    """Answering a fix in the popup sends just that answer (the engine re-checks every held application and starts
    the complete ones within your limits), says what happened, and shows what's left."""
    left = {**FIXES, "fixes": [FIXES["fixes"][0], FIXES["fixes"][3]]}
    await _popup_fixes(page, fixAnswer={**left, "freed": ["j1", "j2"], "started": ["j1"], "note": ""})
    await page.locator("#fixes .fix").nth(1).get_by_role("button", name="Yes").click()
    await page.wait_for_selector("#needs-said:not([hidden])")
    assert await page.evaluate("__calls.find(c => c.type === 'fix')") == {
        "type": "fix", "body": {"id": "profile:work_auth", "value": "Yes"}}
    assert await page.inner_text("#needs-said") == "Saved. 2 applications have nothing left: 1 going out now."
    assert await page.locator("#fixes .fix").count() == 2 and await page.is_hidden("#needs-more")


@browser
async def test_popup_keeps_what_you_typed_when_another_answer_redraws_the_list(page):
    """Half an essay typed, then a Yes/No answered: the list is drawn again, the essay text still there. Answering
    the last fix leaves what it did on show."""
    await _popup_fixes(page, fixAnswer={**FIXES, "freed": ["j1"], "started": [], "note": ""})
    await page.locator("#fixes .fix").nth(2).locator("textarea").fill("Half of my answer")
    await page.locator("#fixes .fix").nth(1).get_by_role("button", name="Yes").click()
    await page.wait_for_selector("#needs-said:not([hidden])")
    assert await page.locator("#fixes .fix").nth(2).locator("textarea").input_value() == "Half of my answer"
    await page.evaluate("__opts.fixAnswer = {held: 0, fixes: [], applications: [], freed: ['j2'], started: ['j2'], note: ''}")
    await page.locator("#fixes .fix").nth(1).get_by_role("button", name="No").click()
    await page.wait_for_function("document.querySelectorAll('#fixes .fix').length === 0")
    assert await page.is_visible("#needs-said")
    assert await page.inner_text("#needs-said") == "Saved. 1 application has nothing left: 1 going out now."


@browser
async def test_popup_saves_your_own_words_and_says_when_it_cant(page):
    """An essay is typed in your words and sent as typed; Save waits for an answer; an engine refusal is shown."""
    await _popup_fixes(page)
    essay = page.locator("#fixes .fix").nth(2)
    save = essay.get_by_role("button", name="Save your answer")
    assert await save.is_disabled()
    words = "I've used {company}'s tools for years.\n  Still do."
    await essay.locator("textarea").fill(words)
    await save.click()
    await page.wait_for_selector("#needs-said:not([hidden])")
    assert await page.evaluate("__calls.find(c => c.type === 'fix').body") == {"id": "essay:why_company", "value": words}
    assert await page.inner_text("#needs-said") == "Type an answer first."
    assert await page.locator("#fixes .fix").count() == 3          # nothing changed


@browser
async def test_popup_shows_no_needs_you_when_nothing_waits(page):
    await page.add_init_script(_stub({}, fixes={"held": 0, "fixes": [], "applications": []}))
    await page.goto((EXT / "popup.html").resolve().as_uri())
    await page.wait_for_selector("body[data-ready]")
    await page.wait_for_function("__calls.some(c => c.type === 'fixes')")
    assert await page.is_hidden("#needs")


@browser
async def test_popup_autopilot_box_starts_unchecked_and_remembers(page):
    async def popup(p, store):
        await p.add_init_script(_stub(store))
        await p.goto((EXT / "popup.html").resolve().as_uri())
        await p.wait_for_selector("body[data-ready]")

    await popup(page, {})
    assert not await page.is_checked("#apply")
    assert "Add your resume PDF to attach it" in await page.inner_text("#status")
    assert not await page.is_disabled("#fill")
    await page.check("#apply")
    assert await page.evaluate("__store.applyWithAutopilot") is True
    assert await page.evaluate("__calls.some(c => c.tab && c.tab.type === 'open')")   # opened the panel on the page
    saved = await page.evaluate("__store")
    assert saved == {"applyWithAutopilot": True}
    again = await (await page.context.browser.new_context()).new_page()      # the popup opens fresh each time
    await popup(again, saved)
    assert await again.is_checked("#apply")


@browser
async def test_popup_adds_the_page_script_to_a_tab_opened_before_the_extension(page):
    await page.add_init_script(_stub({}, noReceiver=True))
    await page.goto((EXT / "popup.html").resolve().as_uri())
    await page.wait_for_function("__calls.some(c => c.tab && c.tab.type === 'open')")
    injected = await page.evaluate("__calls.filter(c => c.inject)")
    assert injected == [{"inject": ["content.js"], "allFrames": False}]   # the top page; no job-site frames here
    assert not await page.is_disabled("#fill")


async def test_engine_answers_a_form_with_no_resume_pdf():
    """No PDF on file: every answer still comes back, and the file field is left for the extension to skip."""
    profile.set_answer("email", "alex@example.com", True)
    r = await extension.answers("https://job-boards.greenhouse.io/acme/jobs/9", [
        {"id": "js1", "label": "Email", "type": "text", "required": True},
        {"id": "js2", "label": "Resume/CV", "type": "file", "required": True}], title="Intern")
    assert r["resume"] is None
    by = {a["id"]: a for a in r["answers"]}
    assert by["js1"]["value"] == "alex@example.com" and by["js2"]["file"] == "resume"


async def test_engine_names_the_city_to_pick_from_a_place_lookup():
    """For Greenhouse's Location (City) the engine sends your city as you wrote it (typed to search) and the option
    to look for. Other dropdowns get no such hint."""
    profile.set_answer("location", "Boston, MA", True)
    r = await extension.answers("https://job-boards.greenhouse.io/acme/jobs/10", [
        {"id": "candidate-location", "label": "Location (City)", "type": "combobox", "required": True},
        {"id": "pronouns", "label": "Pronouns", "type": "combobox"}], title="Intern")
    by = {a["id"]: a for a in r["answers"]}
    assert by["candidate-location"]["value"] == "Boston, MA"
    assert by["candidate-location"]["pick"] == "Boston, Massachusetts, United States"
    assert "pick" not in by["pronouns"]


async def test_engine_holds_worked_here_before_and_says_where_legal_answers_came_from():
    """"Worked for <company> before?" with nothing confirmed is held (under Needs you), not a guessed "No"; a
    work-authorization answer carries its source for the panel."""
    profile.set_answer("work_authorized_us", "Yes", True)
    fields = [{"id": "auth", "label": "Are you authorized to work in the US?", "type": "combobox", "required": True},
              {"id": "worked", "label": "Have you ever worked for Figma before?", "type": "combobox", "required": True}]
    r = await extension.answers("https://job-boards.greenhouse.io/figma/jobs/11", fields, title="Intern", company="Figma")
    by = {a["id"]: a for a in r["answers"]}
    assert by["auth"]["value"] == "Yes"
    assert by["auth"]["source"] == "Profile: Authorized to work in the US? (you confirmed it)"
    assert by["worked"]["value"] == "" and by["worked"]["hold"] == "nothing confirmed says, so answer it yourself"
    assert "source" not in by["worked"]
    profile.set_answer("resume_lists_all_employers", "Yes", True)
    r = await extension.answers("https://job-boards.greenhouse.io/figma/jobs/11", fields, title="Intern", company="Figma")
    worked = next(a for a in r["answers"] if a["id"] == "worked")
    assert worked["value"] == "No" and not worked["hold"]
    assert worked["source"].startswith("You confirmed your resume lists every employer")


@pytest.mark.parametrize("fact", ["first name", "legal last name", "email address", "mobile phone number",
                                  "LinkedIn profile URL", "GitHub link", "personal website", "portfolio link", "city",
                                  "country", "current location", "city and state", "zip code", "salary expectations",
                                  "expected salary", "compensation expectations", "desired pay", "pay expectation",
                                  "hourly rate", "earliest start date", "desired compensation", "expected pay",
                                  "salary range", "desired salary", "expected compensation"])
def test_every_plain_fact_named_politely_maps_to_a_profile_answer(fact):
    from jobsmith import classify
    assert classify.plain_fact(f"Please tell us your {fact}") == fact
    assert classify.canon_for(f"Please tell us your {fact}") == classify.canon_for(fact) is not None


async def test_engine_answers_a_polite_question_for_a_fact_from_the_profile():
    """"Tell us your first name" is asking for your first name: the confirmed profile answer, no AI. "Tell us your
    phone troubleshooting process" isn't asking for your phone number."""
    profile.set_answer("first_name", "Alex", True)
    profile.set_answer("phone", "617-555-0123", True)
    r = await extension.answers("https://job-boards.greenhouse.io/acme/jobs/10", [
        {"id": "js1", "label": "Tell us your first name", "type": "text", "required": True},
        {"id": "js2", "label": "Please tell us your phone number so we can reach you", "type": "text", "required": True},
        {"id": "js3", "label": "Tell us your phone troubleshooting process", "type": "textarea", "required": True},
        {"id": "js4", "label": "Tell us your first name (as on your ID)", "type": "text", "required": True}],
        title="Intern")
    by = {a["id"]: a for a in r["answers"]}
    assert by["js1"]["value"] == "Alex" and by["js2"]["value"] == "617-555-0123" and by["js4"]["value"] == "Alex"
    assert by["js3"]["value"] != "617-555-0123" and by["js3"]["qkind"] == "essay"


def test_practice_copy_resume_pdf_matches_the_tex(tmp_path):
    pdf = devtools.resume_pdf(Path(devtools.__file__).parent / "demo_data" / "resume.tex", tmp_path / "Alex_Rivera_resume.pdf")
    from pypdf import PdfReader
    assert len(PdfReader(str(pdf)).pages) == 1
    text = " ".join(profile.pdf_text(pdf).split())
    parsed = profile.parse_latex((Path(devtools.__file__).parent / "demo_data" / "resume.tex").read_text())
    assert text.startswith("Alex Rivera")
    for k in ("email", "phone", "location"):
        assert parsed["identity"][k] in text
    for sec in parsed["sections"]:
        assert sec["title"].upper() in text
        for e in sec["entries"]:
            for b in e["bullets"]:
                assert " ".join(b.replace("\u2013", "-").split()) in text


# --------------------------------------------------------------------------- answers that don't fit their question

@pytest.mark.parametrize("label, qtype, answer, fits", [
    ("From where do you intend to work?", "text", ESSAY, False),          # the Figma bug
    ("From where do you intend to work?", "text", "Boston, MA", True),
    ("Location (City)", "text", "I live in Boston and would love to move.", False),
    ("Are you willing to relocate?", "text", ESSAY, False),
    ("Are you willing to relocate?", "text", "Yes", True),
    ("Other Website", "text", ESSAY, False),
    ("LinkedIn Profile", "text", "https://www.linkedin.com/in/alex-rivera-test/", True),
    ("Why do you want to join Figma?", "textarea", "Yes", False),
    ("Why do you want to join Figma?", "textarea", "Boston", False),
    ("Why do you want to join Figma?", "textarea", ESSAY, True),
    ("Additional Information", "textarea", "N/A", True),
    ("Additional Information", "textarea", "None", True),                   # a big box doesn't make it an essay
    ("How did you hear about us?", "textarea", "LinkedIn", True),
    ("How did you hear about us?", "textarea", ESSAY, False),               # a short question, even in a big box
    ("Are you willing to relocate? Explain.", "textarea", "Yes. I'd move to New York or Seattle, and could start in June.", True),
    ("Are you willing to relocate? Explain.", "textarea", ESSAY, True),
    ("How do you approach debugging?", "text", ESSAY, True),
    ("Please state your salary expectations", "text", "$45/hr. Open to discussing it.", True),   # 'state' the verb
    ("Why do you want to join Figma?", "text", "Yes", False),              # a one-line box doesn't make it short
    ("Describe your experience with Python.", "text", ESSAY, True),
    ("City and state", "text", ESSAY, False),
    ("Please tell us your LinkedIn profile URL", "text", "https://linkedin.com/in/alex-rivera", True),   # polite, a fact
    ("Please tell us your LinkedIn profile URL", "text", ESSAY, False),
    ("Tell us your city and state", "text", "Boston, MA", True),
    ("Tell us about yourself", "textarea", ESSAY, True),
    ("Tell us about yourself", "textarea", "Yes", False),
    ("Tell us your first name", "text", "Alex", True),
    ("Tell us your first name", "textarea", "Alex", True),
    ("Tell us your country", "text", "United States", True),
    ("Tell us your country", "textarea", "United States", True),
    ("Please tell us your LinkedIn profile URL so we can contact you", "textarea",
     "https://linkedin.com/in/alex-rivera", True),
    ("Please tell us your LinkedIn profile URL (so we can reach you)", "text", "https://linkedin.com/in/alex-rivera", True),
    ("Tell us your email address (required)", "text", "alex.rivera@example.com", True),
    ("Tell us your salary expectations", "text", "$45/hour", True),
    ("Tell us your expected pay", "text", "$45/hour", True),
    ("Please share your earliest start date", "text", "June 1, 2027", True),
    ("Tell us your salary expectations (explain how you arrived at this figure)", "text", "$45/hour", False),
    ("Tell us your phone troubleshooting process", "text", "617-555-0123", False),   # a story that names a fact
    ("Tell us your city and how you chose it", "text", "Boston, MA", False),
    ("Tell us your experience with Python", "text", "Yes", False),                  # narrative, not a fact
    ("Tell us your experience with Python", "textarea", ESSAY, True),
    ("Tell us the hardest bug you've fixed", "text", ESSAY, True),
    ("Tell us the hardest bug you've fixed", "textarea", "Yes", False),
])
def test_answer_must_fit_the_kind_of_question(label, qtype, answer, fits):
    from jobsmith import draft
    assert (draft.answer_fits({"label": label, "qtype": qtype, "options": []}, answer) is None) == fits


FIGMA_FIELDS = [   # the saved Figma form's questions, as the extension sends them
    {"id": "js1", "label": "First Name", "type": "text", "required": True},
    {"id": "js2", "label": "Location (City)", "type": "combobox", "required": True},
    {"id": "js3", "label": "Why do you want to join Figma?", "type": "textarea", "required": True},
    {"id": "js4", "label": "Additional Information", "type": "textarea"},
    {"id": "js5", "label": "From where do you intend to work?", "type": "text", "required": True},
    {"id": "js6", "label": "Preferred First Name", "type": "text"},
    {"id": "js7", "label": "Other Website", "type": "text"},
]


async def test_figma_form_never_puts_an_essay_where_it_asks_where():
    """With no AI, answers come from your own writing by word match. That once filled "From where do you intend to
    work?" with the 'why Figma' paragraph."""
    from jobsmith.skills import voice
    await profile.ingest_document(Path(devtools.__file__).parent / "demo_data" / "resume.tex")
    voice.add_file(Path(devtools.__file__).parent / "demo_data" / "writing.md")
    r = await extension.answers("https://job-boards.greenhouse.io/figma/jobs/5426468004", FIGMA_FIELDS,
                                title="Account Executive, Enterprise", company="Figma")
    by = {a["id"]: a for a in r["answers"]}
    where = by["js5"]
    assert where["value"] == "Boston, MA"                                         # a place, never the essay
    assert "where you'd work" in where["check"] and where["confidence"] <= 0.5    # where you live, for you to check
    for k in ("js6", "js7"):
        assert len(by[k]["value"].split()) <= 40, by[k]
    why = by["js3"]                                                               # reused writing that never says Figma
    assert why["kind"] == "voice" and "Figma" not in why["value"]
    assert "generic" in why["check"] and why["confidence"] <= 0.5 and "Generic" in why["issues"][0]


async def test_home_location_offered_for_where_youd_work_blocks_autopilot():
    """Where you live isn't necessarily where you'd work: filled for you to check, never sent unread."""
    from jobsmith import draft
    profile.set_answer("location", "Boston, MA", True)
    field = {"field": "where", "label": "From where do you intend to work?", "qtype": "text", "required": True}
    jid = extension.find_or_add("https://job-boards.greenhouse.io/figma/jobs/2", "Engineer", "Figma")
    results, _ = await draft.answer_fields(db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,))), [field])
    assert results["where"]["answer"] == "Boston, MA" and results["where"]["check"]
    draft.save_results(jid, [field], results)
    assert any("where you'd work" in b for b in draft.readiness(jid)["blockers"])


def test_only_why_us_answers_are_called_generic():
    from jobsmith import draft
    job = {"company": "Figma"}
    story = {"kind": "voice", "answer": ESSAY, "confidence": 0.8, "issues": []}
    assert "check" not in draft._checked({"label": "Describe your most challenging project", "qtype": "textarea"}, story, job)
    assert draft._checked({"label": "Why do you want to join Figma?", "qtype": "textarea"}, story, job)["check"]
    assert draft._checked({"label": "What excites you about this role?", "qtype": "textarea"}, story, job)["check"]
    aimed = dict(story, answer="Figma's multiplayer editor is the kind of system I want to build.")
    assert "check" not in draft._checked({"label": "Why do you want to join Figma?", "qtype": "textarea"}, aimed, job)


async def test_write_with_jobsmith_returns_held_and_generic_marks():
    """The engine side of the button beside one question: the same checks as autofill, sent along with the text."""
    from jobsmith.skills import voice
    voice.add_file(Path(devtools.__file__).parent / "demo_data" / "writing.md")
    url = "https://job-boards.greenhouse.io/figma/jobs/3"
    why = await extension.generate(url, "Why do you want to join Figma?", title="Engineer", site_name="Figma")
    assert why["text"] and "generic" in why["check"] and why["qkind"] == "essay" and not why["hold"]
    office = await extension.generate(url, "Which office would you like to work from?", title="Engineer", site_name="Figma")
    assert office["text"] == "" and office["hold"] and office["error"] is None      # held, not "no AI"


async def test_a_where_question_with_no_profile_answer_is_held_not_filled_with_writing():
    from jobsmith import draft
    from jobsmith.skills import voice
    voice.add_file(Path(devtools.__file__).parent / "demo_data" / "writing.md")
    field = {"field": "office", "label": "Which office would you like to work from?", "qtype": "text", "required": True}
    jid = extension.find_or_add("https://job-boards.greenhouse.io/figma/jobs/1", "Engineer", "Figma")
    db.x("UPDATE jobs SET description='We want people who want to work on hard problems.' WHERE id=?", (jid,))
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    results, _ = await draft.answer_fields(job, [field])
    r = results["office"]
    assert r["answer"] == "" and r["held"] and r["issues"][0].startswith("Held for you")
    draft.save_results(job["id"], [field], results)
    assert not draft.readiness(job["id"])["ready"]                 # autopilot won't submit a held answer


# --------------------------------------------------------------------------- the real extension, loaded into Chromium
def _serve(routes, tls: tuple[str, str] | None = None):
    """A local HTTP server answering from `routes` (path -> (status, content type, body or callable(body))).
    tls: (certificate file, key file) to serve HTTPS instead."""
    import ssl
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def _answer(self, body=None):
            status, ctype, out = routes.get(self.path.split("?")[0], (404, "application/json", b'{"detail": "not here"}'))
            out = out(body) if callable(out) else out
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(out)

        def do_GET(self):
            self._answer()

        def do_POST(self):
            self._answer(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"))

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(*tls)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _engine_answers(body):
    by_label = {"First Name": "Alex", "Last Name": "Rivera", "Email": "alex.rivera@example.com"}
    return json.dumps({"job_id": "j1", "resume": None, "error": None, "answers": [
        {"id": f["id"], "file": "resume", "kind": "file"} if f["type"] == "file" else
        {"id": f["id"], "value": by_label.get(f["label"], ""), "kind": "answer_bank"} for f in body["fields"]]}).encode()


def _self_signed(hosts: list[str], folder: Path) -> tuple[str, str]:
    """A throwaway certificate for made-up job-site hostnames (Chrome is told to accept it)."""
    import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(h) for h in hosts]), critical=False)
            .sign(key, hashes.SHA256()))
    (folder / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (folder / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                       serialization.NoEncryption()))
    return str(folder / "cert.pem"), str(folder / "key.pem")


LISTED, UNLISTED = "job-boards.greenhouse.io", "apply.unlisted-ats.test"


WRAPPER = "embed.careers-cdn.test"          # a company's own embed host, not a job site: its frame wraps the form


@contextlib.asynccontextmanager
async def _extension_after_tab(tmp_path, careers_html, form_routes: dict, settle, engine_routes: dict | None = None):
    """A careers page open in Chromium before the extension is loaded, so no frame has Jobsmith's script; then the
    real extension, pointed at a stand-in engine. form_routes are served on the job-site, unlisted and wrapper hosts
    (one server, so careers_html(port) builds its frame addresses); settle(tab) waits for the page's frames to load.
    Yields the context, the tab, and popup(), which opens the real popup on that tab once it has reached every frame.

    The careers page is served from 127.0.0.1, which the extension may reach (the engine's address): that stands in
    for the access a click on the toolbar button grants to the top page, which a test can't click."""
    import asyncio
    import socket
    import subprocess
    import tempfile
    from types import SimpleNamespace
    from playwright.async_api import async_playwright
    tls = _self_signed([LISTED, UNLISTED, WRAPPER], tmp_path)
    form = _serve(form_routes, tls=tls)
    engine = _serve({"/api/ext/ping": (200, "application/json", b'{"ok": true, "ai": "none", "ai_ok": false, "resume": null}'),
                     "/api/ext/answers": (200, "application/json", _engine_answers), **(engine_routes or {})})
    careers = _serve({"/careers": (200, "text/html", careers_html(form.server_port).encode())})
    careers_url = f"http://127.0.0.1:{careers.server_port}/careers"
    # Chromium with an ordinary profile (Playwright's own contexts are incognito-like, where extensions don't run),
    # driven over the DevTools protocol so the extension can be loaded after the tab is open.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    profile_dir = tempfile.mkdtemp(prefix="jobsmith-chrome-")
    chrome = subprocess.Popen([CHROMIUM, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}",
                               "--enable-unsafe-extension-debugging", "--no-first-run", "--no-default-browser-check",
                               f"--host-resolver-rules=MAP {LISTED} 127.0.0.1, MAP {UNLISTED} 127.0.0.1, "
                               f"MAP {WRAPPER} 127.0.0.1",
                               "--ignore-certificate-errors", *browser_args(),
                               # Ubuntu 24.04 (CI) blocks Chrome's sandbox for ordinary users; Playwright's own
                               # launches turn it off the same way
                               *(["--no-sandbox"] if sys.platform.startswith("linux") else []), "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=open(tmp_path / "chrome.log", "w"))
    try:
        import urllib.request
        for _ in range(300):                     # Chrome's DevTools endpoint answers once it's ready to be driven
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).read()
                break
            except OSError:
                if chrome.poll() is not None:
                    break
                await asyncio.sleep(0.1)
        else:
            pytest.fail("Chrome didn't start:\n" + (tmp_path / "chrome.log").read_text()[-3000:])
        if chrome.poll() is not None:
            pytest.fail(f"Chrome exited ({chrome.returncode}):\n" + (tmp_path / "chrome.log").read_text()[-3000:])
        async with async_playwright() as pw:
            b = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = b.contexts[0]
            tab = await ctx.new_page()
            for p in ctx.pages:
                if p is not tab:
                    await p.close()                                      # Chrome's blank start tab
            for attempt in range(3):             # a just-started Chrome can cut off its first load (seen on Windows)
                try:
                    await tab.goto(careers_url)
                    break
                except Exception as e:
                    if "ERR_ABORTED" not in str(e) or attempt == 2:
                        raise
                    await asyncio.sleep(0.5)
            await settle(tab)
            ext_id = (await (await b.new_browser_cdp_session()).send(
                "Extensions.loadUnpacked", {"path": str(EXT)}))["id"]               # loaded after the tab opened
            # Point the extension at this test's engine from its service worker: a page (the popup) would ping
            # the default engine, the real one on 8765, before the address was saved.
            worker = next((w for w in ctx.service_workers if ext_id in w.url), None) or \
                await ctx.wait_for_event("serviceworker", predicate=lambda w: ext_id in w.url, timeout=15000)
            await worker.evaluate(f"chrome.storage.local.set({{engine: 'http://127.0.0.1:{engine.server_port}'}})")

            async def popup():
                # Opened as a page, the popup's "active tab" is itself: point it at the only other tab, the careers
                # page (tab URLs are hidden without the "tabs" permission). Everything else is the real extension.
                pop = await ctx.new_page()
                await pop.add_init_script(ONLY_THE_CAREERS_TAB)
                await pop.goto(f"chrome-extension://{ext_id}/popup.html")
                await pop.wait_for_selector("body[data-ready]", timeout=20000)           # done reaching every frame
                return pop

            async def hint(pop):
                return None if await pop.is_hidden("#result") else await pop.inner_text("#result")
            yield SimpleNamespace(ctx=ctx, tab=tab, popup=popup, hint=hint, port=form.server_port)
            await b.close()
    finally:
        chrome.kill()
        for s in (form, engine, careers):
            s.shutdown()
        __import__("shutil").rmtree(profile_dir, ignore_errors=True)


FORM_ROUTES = {"/apply": (200, "text/html", (FIXTURES / "greenhouse_board_posting.html").read_bytes()),
               "/video": (200, "text/html", b"<p>A video</p><input id='q' aria-label='Search videos'>")}
RELOAD = "Reload this page to fill the form inside it."


@browser
@pytest.mark.parametrize("form_host, beside, wrapped", [
    (LISTED, None, False), (UNLISTED, None, False), (LISTED, UNLISTED, False), (UNLISTED, LISTED, False),
    (LISTED, None, True), (UNLISTED, None, True)])            # #15: page -> wrapper frame -> the form's frame
async def test_popup_reaches_a_job_site_form_in_a_frame_opened_before_the_extension(form_host, beside, wrapped,
                                                                                       tmp_path):
    """A company's careers page embeds an application form in a frame from another site, and the tab was open before
    the extension was loaded, so no frame has Jobsmith's script. The real popup adds it to the top page and to a frame
    from a listed job site (manifest host_permissions; see SECURITY.md), and autofill fills that form. A frame from
    any other site gets "Reload this page" and is left alone; beside a job-site form (a video, say), it's just skipped.
    A job-site frame with no form in it (a video) doesn't hide the reload another site's form needs. A form inside a
    wrapper frame (the company's own embed, from a site Jobsmith may not reach) is found the same way, three deep at
    most, and the wrapper never gets the script."""
    form_url = lambda port: f"https://{form_host}:{port}/apply"
    routes = dict(FORM_ROUTES)

    def careers(port):
        inner = (f'<iframe id="gh" src="{form_url(port)}" style="width:1000px;height:2400px"></iframe>')
        if wrapped:
            routes["/wrap"] = (200, "text/html", f"<p>Embedded careers</p>{inner}".encode())
            inner = f'<iframe id="wrap" src="https://{WRAPPER}:{port}/wrap" style="width:1040px;height:2500px"></iframe>'
        return ('<h1>Careers</h1>' + inner +
                (f'<iframe id="other" src="https://{beside}:{port}/video" style="width:640px;height:360px"></iframe>'
                 if beside else ""))

    async def settle(tab):
        await tab.wait_for_load_state("load")
        frame = next(f for f in tab.frames if f.url.endswith("/apply"))
        await frame.wait_for_selector("#first_name")
    async with _extension_after_tab(tmp_path, careers, routes, settle) as x:
        tab = x.tab
        frame = next(f for f in tab.frames if f.url.endswith("/apply"))
        assert await frame.evaluate("document.querySelector('[data-jobsmith-id]') === null")   # no script in it yet
        popup = await x.popup()
        await tab.wait_for_selector("#jobsmith-panel", state="attached", timeout=10000)   # the popup opened the panel
        await _watch_for_submits(tab, frame)
        hint = await x.hint(popup)
        await popup.click("#fill")                                                     # (closes the popup)
        if form_host == LISTED:
            assert hint is None                                                         # no reload needed
            await frame.wait_for_function("document.getElementById('first_name').value === 'Alex'", timeout=15000)
            assert await frame.input_value("#email") == "alex.rivera@example.com"
            await frame.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.note')"
                                          "?.innerText.includes('Filled')")       # autofill finished in the frame
        else:
            assert hint == RELOAD
            await tab.wait_for_timeout(2000)
            assert await frame.input_value("#first_name") == ""                         # not reached: reload it
            assert await frame.evaluate("document.querySelector('[data-jobsmith-id]') === null")
        # Open the popup again: the frame's state is read afresh, not remembered from the first time.
        if not popup.is_closed():
            await popup.close()
        again = await x.popup()
        assert await again.inner_text("#fill") != "Can't fill this page"                 # it reached the tab
        if form_host == LISTED:
            assert await again.is_hidden("#result")                                     # the frame has it now
            assert await frame.evaluate("document.querySelectorAll('#jobsmith-panel').length") == 1   # not injected twice
            await frame.fill("#first_name", "")
            await again.click("#fill")                                                  # and it still fills
            await frame.wait_for_function("document.getElementById('first_name').value === 'Alex'", timeout=15000)
        else:
            assert await again.inner_text("#result") == RELOAD
        if beside:                                                       # nothing typed or shown there
            other = tab.frame(url=lambda u: u.endswith("/video"))
            assert await other.evaluate("document.querySelector('#jobsmith-panel') === null")
            assert await other.input_value("#q") == ""
        await _never_submitted(tab)


TALENT_NETWORK = ("<h1>Careers at Acme</h1><form><h2>Join our talent network</h2>"
                  "<label for=fn>First Name</label><input id=fn><label for=ln>Last Name</label><input id=ln>"
                  "<label for=em>Email</label><input id=em type=email><label for=ph>Phone</label><input id=ph></form>")


@browser
@pytest.mark.parametrize("path, reload", [("/apply", True), ("/video", False)])
async def test_popup_says_reload_when_the_real_application_is_in_another_sites_frame(path, reload, tmp_path):
    """#17: the careers page has its own short form (a talent network), so it looks like an application itself, and
    the real one is in a frame from a site Jobsmith may not reach, opened before the extension. The popup says
    "Reload this page" for that frame, and not for a video's frame on the same page."""
    def careers(port):
        return TALENT_NETWORK + (f'<iframe src="https://{UNLISTED}:{port}{path}" title="Embedded content" '
                                 f'style="width:900px;height:{700 if path == "/apply" else 360}px"></iframe>')

    async def settle(tab):
        await tab.wait_for_load_state("load")
        await next(f for f in tab.frames if f.url.endswith(path)).wait_for_selector("input")
    async with _extension_after_tab(tmp_path, careers, FORM_ROUTES, settle) as x:
        await _watch_for_submits(x.tab)
        popup = await x.popup()
        assert await popup.inner_text("#fill") == "Fill this application"
        assert await x.hint(popup) == (RELOAD if reload else None)
        await _never_submitted(x.tab)


@browser
async def test_write_with_jobsmith_works_beside_a_question_in_a_job_sites_frame(tmp_path):
    """#16: a company page embeds Greenhouse's form in a frame. The real popup reaches the frame; the Write button
    then shows beside its open question (the panel stays on the top page, one per tab). Pressed three times: a held
    answer is never typed in, a flagged one is typed in with "Check this", and a clean one says "Edit freely". The
    submit watcher is on in the frame throughout."""
    replies = iter([{"text": "", "hold": "asks for a written answer, but the answer is a word or two", "qkind": "essay"},
                    {"text": ESSAY, "qkind": "essay", "check": "generic, doesn't mention Figma: check this"},
                    {"text": ESSAY, "qkind": "essay"}])

    def generate(body):
        assert body["label"] == "Why do you want to join Figma?"
        return json.dumps({"based_on": [], "error": None, **next(replies)}).encode()

    def careers(port):
        return (f'<h1>Careers at Figma</h1><iframe src="https://{LISTED}:{port}/apply" '
                f'style="width:1000px;height:2400px"></iframe>')

    async def settle(tab):
        await tab.wait_for_load_state("load")
        await next(f for f in tab.frames if f.url.endswith("/apply")).wait_for_selector("#first_name")
    async with _extension_after_tab(tmp_path, careers, FORM_ROUTES, settle,
                                    {"/api/ext/generate": (200, "application/json", generate)}) as x:
        frame = next(f for f in x.tab.frames if f.url.endswith("/apply"))
        await _watch_for_submits(x.tab, frame)
        await (await x.popup()).close()
        write = "document.getElementById('question_12497120004').nextElementSibling?.shadowRoot"
        await frame.wait_for_function(f"{write}?.querySelector('button')", timeout=15000)
        assert await x.tab.evaluate("document.querySelectorAll('#jobsmith-panel').length") == 1
        assert await frame.evaluate("document.querySelector('#jobsmith-panel') === null")      # no second panel

        async def press(times=1):
            for _ in range(times):
                await frame.evaluate(f"{write}.querySelector('button').click()")
            await frame.wait_for_function(f"!{write}.querySelector('button').disabled && "
                                          f"!/Writing|replaces/.test({write}.querySelector('span').innerText)")
            return await frame.evaluate(f"{write}.querySelector('span').innerText")
        note = await press()
        assert "Held for you" in note and await frame.input_value("#question_12497120004") == ""
        note = await press()
        assert note.startswith("Check this: generic, doesn't mention Figma") and "Edit freely" not in note
        assert await frame.input_value("#question_12497120004") == ESSAY
        await frame.evaluate(f"{write}.querySelector('button').click()")       # it has text: the first press asks
        await frame.wait_for_function(f"{write}.querySelector('span').innerText.includes('replaces')")
        note = await press()
        assert note == "Edit freely." and await frame.input_value("#question_12497120004") == ESSAY
        await _never_submitted(x.tab)


def _framed(src: str, h: int = 700, title: str = "") -> bytes:
    return f'<iframe src="{src}" title="{title}" style="width:900px;height:{h}px"></iframe>'.encode()


APPLY_FORM = (b"<form><label for=fn>First Name</label><input id=fn><label for=ln>Last Name</label><input id=ln>"
              b"<label for=em>Email</label><input id=em><label for=ph>Phone</label><input id=ph></form>")


@browser
@pytest.mark.parametrize("pages, scripted, bare, apps", [
    # a wrapper whose own script answers (it holds no form) around another site's application it can't reach
    ({"https://careers.acme.test/": _framed("https://embed.acme.test/wrap"),
      "https://embed.acme.test/wrap": _framed("https://apply.unlisted-ats.test/apply")},
     ["/wrap"], ["embed.acme.test"], []),
    # the same wrapper around a form whose script answered: reached
    ({"https://careers.acme.test/": _framed("https://embed.acme.test/wrap"),
      "https://embed.acme.test/wrap": _framed("https://apply.unlisted-ats.test/apply")},
     ["/wrap", "/apply"], [], []),
    # three deep is reached; four deep is past the limit, so the wrapper stays unreached
    ({"https://careers.acme.test/": _framed("https://embed.acme.test/w1"),
      "https://embed.acme.test/w1": _framed("https://embed.acme.test/w2"),
      "https://embed.acme.test/w2": _framed("https://apply.unlisted-ats.test/apply")},
     ["/apply"], [], []),
    ({"https://careers.acme.test/": _framed("https://embed.acme.test/w1"),
      "https://embed.acme.test/w1": _framed("https://embed.acme.test/w2"),
      "https://embed.acme.test/w2": _framed("https://embed.acme.test/w3"),
      "https://embed.acme.test/w3": _framed("https://apply.unlisted-ats.test/apply")},
     ["/apply"], ["embed.acme.test"], []),
    # every wrapper three deep answers "no form", but the application is a fourth level down: not reached
    ({"https://careers.acme.test/": _framed("https://embed.acme.test/w1"),
      "https://embed.acme.test/w1": _framed("https://embed.acme.test/w2"),
      "https://embed.acme.test/w2": _framed("https://embed.acme.test/w3"),
      "https://embed.acme.test/w3": _framed("https://apply.unlisted-ats.test/apply")},
     ["/w1", "/w2", "/w3"], ["embed.acme.test"], []),
    # a wrapper and the video inside it both answer, and neither holds a form: nothing left unseen
    ({"https://careers.acme.test/": _framed("https://embed.acme.test/wrap"),
      "https://embed.acme.test/wrap": _framed("https://embed.acme.test/video", 360)},
     ["/wrap", "/video"], [], []),
    # Google Forms titled as an application is one; a YouTube video and Google Maps aren't
    ({"https://careers.acme.test/": _framed("https://docs.google.com/forms/d/e/x/viewform", title="Job application") +
      _framed("https://www.youtube.com/embed/x", 360) + _framed("https://www.google.com/maps/embed?pb=x", 360)},
     [], ["docs.google.com", "www.youtube.com", "www.google.com"], ["docs.google.com"]),
])
async def test_the_page_tells_the_popup_which_frames_it_couldnt_reach(page, pages, scripted, bare, apps):
    """What the top page reports about its frames (#15, #17): frames are asked three deep; a frame counts as reached
    when it or a frame inside it holds an application and answered, or when it and everything inside it answered.
    Of the ones not reached, those that look like an application (address, title or size) are named apart."""
    pages = {**pages, "https://apply.unlisted-ats.test/apply": APPLY_FORM,
             "https://docs.google.com/forms/d/e/x/viewform": APPLY_FORM}
    await page.route("**/*", lambda r: r.fulfill(status=200, content_type="text/html",
                                                 body=pages.get(r.request.url, b"<p>media</p>")))
    await page.add_init_script(_stub({"panelOpen": False}))
    await page.goto("https://careers.acme.test/")
    await page.wait_for_load_state("load")
    for f in page.frames:
        if f != page.main_frame and any(f.url.endswith(p) for p in scripted):
            await f.add_script_tag(path=str(EXT / "content.js"))
    await page.add_script_tag(path=str(EXT / "content.js"))
    info = await page.evaluate("new Promise(res => __listeners.forEach(f => f({type: 'info'}, {}, res)))")
    assert (sorted(info["bare"]), sorted(info["bareApps"])) == (sorted(bare), sorted(apps)), info


SLOW_FRAME = (b"<p>Application</p><script>addEventListener('message', e => { if (e.data && e.data.jobsmith === 'who') "
              b"setTimeout(() => e.source.postMessage({jobsmith: 'here', application: true}, '*'), 400); });</script>")


@browser
async def test_the_page_waits_for_a_slow_frame_and_not_forever_for_a_silent_one(page):
    """#25: a frame that takes 400 ms to say it holds a form still counts as reached (a fixed quarter second missed
    it on a slow machine), the answer comes as soon as every frame has spoken, and a frame that never answers is
    reported unreached after about a second, once."""
    import asyncio
    pages = {"https://careers.acme.test/": _framed("https://apply.unlisted-ats.test/slow"),
             "https://careers.acme.test/both": _framed("https://apply.unlisted-ats.test/slow") +
             _framed("https://apply.unlisted-ats.test/silent"),
             "https://apply.unlisted-ats.test/slow": SLOW_FRAME, "https://apply.unlisted-ats.test/silent": b"<p>x</p>"}
    await page.route("**/*", lambda r: r.fulfill(status=200, content_type="text/html", body=pages.get(r.request.url, b"")))
    await page.add_init_script(_stub({"panelOpen": False}))
    # timed inside the page, from the request to its reply (#27: a busy CI machine's wall clock counted its own
    # slowness); held 1300 ms more to count any second reply past the deadline
    ask = "new Promise(res => { let n = 0, ms; const t0 = performance.now(); __listeners.forEach(f => " \
          "f({type: 'info'}, {}, r => { n++; ms = ms ?? performance.now() - t0; " \
          "setTimeout(() => res({...r, replies: n, ms}), 1300); })); })"
    for url, bare, forms, within in (("https://careers.acme.test/", [], 1, (400, 1000)),
                                     ("https://careers.acme.test/both", ["apply.unlisted-ats.test"], 1, (1000, 1600))):
        await page.goto(url)
        await page.wait_for_load_state("load")
        await page.add_script_tag(path=str(EXT / "content.js"))
        info = await asyncio.wait_for(page.evaluate(ask), 10)            # never answering at all fails, not hangs
        assert info["bare"] == bare and info["forms"] == forms and info["replies"] == 1, info
        assert within[0] <= info["ms"] < within[1], (url, info["ms"])


@browser
async def test_autofill_never_puts_anything_but_digits_in_a_phone_extension_box(page):
    """Workday's phone extension box, word for word, and two others added to the saved Lever form: "+1" (or a whole
    number) offered for an extension is held under Needs you and never typed; digits are typed."""
    await page.add_init_script("""document.addEventListener('DOMContentLoaded', () => document.querySelector('form')
      .insertAdjacentHTML('beforeend', '<label for="phoneNumber--extension">Phone Extension</label>' +
      '<input id="phoneNumber--extension" type="text"><label for="o2">Office Ext</label><input id="o2" type="text">' +
      '<label for="o3">Desk extension</label><input id="o3" type="text" autocomplete="tel-extension">'));""")
    await _load(page, {"panelOpen": True}, fixture="lever_palantir_form.html", answers={
        "Full name": {"value": "Alex Rivera", "kind": "standard"},
        "Phone": {"value": "617-555-0123", "kind": "standard"},
        "Phone Extension": {"value": "+1", "kind": "standard"},
        "Office Ext": {"value": "617-555-0123", "kind": "standard"},
        "Desk extension": {"value": "23", "kind": "standard"}})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    assert await page.input_value('[id="phoneNumber--extension"]') == ""
    assert await page.input_value("#o2") == ""
    assert await page.input_value("#o3") == "23"
    outlined = "s => document.querySelector(s).style.outline.includes('solid')"    # marked under Needs you
    assert await page.evaluate(outlined, '[id="phoneNumber--extension"]') and await page.evaluate(outlined, "#o2")
    assert not await page.evaluate(outlined, "#o3")
    assert await page.evaluate("[...document.querySelectorAll('input')].filter(e => e.value === '+1').length") == 0
    await _never_submitted(page)


async def _on_workday(page, name: str, **opts):
    """A saved Workday application page served at NVIDIA's own Workday address, with Jobsmith's panel on it and
    every submit watched."""
    html = (FIXTURES / f"workday_nvidia_{name}.html").read_text(encoding="utf-8")
    url = "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/x/apply/applyManually"

    async def serve(route):
        if route.request.url.split("?")[0] == url:
            await route.fulfill(status=200, content_type="text/html", body=html)
        else:
            await route.abort()
    await page.route("https://**/*", serve)
    await page.add_init_script(_stub({"panelOpen": True}, **opts))
    await page.goto(url)
    await page.add_script_tag(path=str(EXT / "content.js"))
    await page.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.wrap')")
    await _watch_for_submits(page)


@browser
async def test_autofill_fills_workdays_my_information_page_and_never_moves_on(page):
    """NVIDIA's My Information page, saved signed in and emptied. Fill picks the dropdowns (Country, State, Phone
    Device Type) and the search boxes (How Did You Hear About Us?, Country Phone Code) from their lists, types the
    rest, never puts "+1" in the phone extension, and never presses Save and Continue."""
    std = lambda v: {"value": v, "kind": "standard"}
    await _on_workday(page, "my_information", answers={
        "How Did You Hear About Us?": std("LinkedIn"), "Country": std("United States of America"),
        "First Name": std("Alex"), "Last Name": std("Rivera"), "City": std("Boston"), "State": std("Massachusetts"),
        "Phone Device Type": std("Mobile"), "Country Phone Code": std("United States of America (+1)"),
        "Phone Number": std("617-555-0123"), "Phone Extension": std("+1"),
        "Have you previously worked for NVIDIA as an employee or contractor?": std("No")})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    shown = lambda i: page.evaluate(f"document.getElementById('{i}').innerText.trim()")
    assert await shown("country--country") == "United States of America"
    assert await shown("address--countryRegion") == "Massachusetts"
    assert await shown("phoneNumber--phoneType") == "Mobile"
    pills = lambda i: page.evaluate(f"""[...document.getElementById('{i}').closest('[data-automation-id="multiSelectContainer"]')
        .querySelectorAll('[data-automation-id="selectedItem"]')].map(p => p.innerText.trim())""")
    assert await pills("source--source") == ["LinkedIn"]
    assert await pills("phoneNumber--countryPhoneCode") == ["United States of America (+1)"]
    assert await page.input_value('[id="name--legalName--firstName"]') == "Alex"
    assert await page.input_value('[id="phoneNumber--phoneNumber"]') == "617-555-0123"
    assert await page.input_value('[id="phoneNumber--extension"]') == ""
    assert await page.is_checked("#sijp3") and not await page.is_checked("#sijp2")       # No
    labels = [f["label"] for f in await page.evaluate("__calls.find(c => c.type === 'answers').body.fields")]
    assert "Settings" not in labels and not [l for l in labels if "Select One" in l], labels
    assert page.url.endswith("/applyManually")                                      # still on My Information
    await _never_submitted(page)


@browser
async def test_autofill_reads_workdays_application_questions_by_their_words(page):
    """On the Application Questions page each dropdown's question is beside it, not in its ARIA name (" Select One
    Required"): the engine is asked the question itself, and both are required."""
    await _on_workday(page, "application_questions")
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    await page.wait_for_function("__calls.some(c => c.type === 'answers')", timeout=30000)
    fields = await page.evaluate("__calls.find(c => c.type === 'answers').body.fields")
    asked = {f["label"]: f["required"] for f in fields}
    assert asked == {
        "Are you legally authorized to work in the country where this position is located?": True,
        "Will you require employer support to obtain or maintain authorization to work in that country? e.g. (work permit)": True}, asked
    await _never_submitted(page)


@browser
async def test_the_submit_watcher_sees_your_submit_on_workdays_review_page(page):
    """Autofill never presses Workday's Submit (it sits in the footer's Next slot). When you press it, the watcher
    notes it, so the thank-you page that follows is logged as your application."""
    await _on_workday(page, "review")
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    await page.wait_for_timeout(1500)
    assert await page.evaluate("window.__submitPresses") == 0
    assert await page.evaluate("sessionStorage.getItem('jobsmith-submit')") is None
    await page.click('[data-automation-id="pageFooterNextButton"]')                      # you press Submit
    assert await page.evaluate("window.__submitPresses") == 1
    noted = json.loads(await page.evaluate("sessionStorage.getItem('jobsmith-submit')"))
    assert noted["url"].endswith("/applyManually")


@browser
async def test_autofill_answers_workdays_voluntary_questions_from_your_decline_and_never_a_wrong_code(page):
    """Your confirmed "Decline to self-identify" picks Workday's own wording for it ("I do not wish to answer.",
    "I do not wish to self-identify"); and on My Information a phone code is only ever your number's own."""
    std = lambda v: {"value": v, "kind": "standard"}
    await _on_workday(page, "voluntary_disclosures", answers={
        "What is your ethnicity?": std("Decline to self-identify"), "What is your gender?": std("Decline to self-identify"),
        "Do you identify as one of the following protected veterans (Disabled Veteran, Recently Separated Veteran, "
        "Active Duty Wartime or Campaign Badge Veteran, Armed Forces Service Medal Veteran)?": std("Decline to self-identify")})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    shown = lambda i: page.evaluate(f"document.getElementById('{i}').innerText.trim()")
    assert await shown("personalInfoUS--ethnicity") == "I do not wish to answer. (United States of America)"
    assert await shown("personalInfoUS--gender") == "I do not wish to answer."
    assert await shown("personalInfoUS--veteranStatus") == "I do not wish to self-identify"
    await _never_submitted(page)


@browser
async def test_autofill_never_picks_a_phone_code_that_isnt_your_numbers(page):
    std = lambda v: {"value": v, "kind": "standard"}
    await _on_workday(page, "my_information", answers={"Country Phone Code": std("United Kingdom (+1)")})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    pills = await page.evaluate("""[...document.getElementById('phoneNumber--countryPhoneCode').closest(
        '[data-automation-id="multiSelectContainer"]').querySelectorAll('[data-automation-id="selectedItem"]')].length""")
    assert pills == 0                                     # "United Kingdom (+44)" is never taken for +1
    await _never_submitted(page)


SR_URL = "https://jobs.smartrecruiters.com/oneclick-ui/company/BoschGroup/publication/00000000-0000-4000-8000-000000000000"


async def _on_smartrecruiters(page, **opts):
    """The saved Bosch form served at a SmartRecruiters address, with Jobsmith's panel on it and every submit
    watched."""
    html = (FIXTURES / "smartrecruiters_bosch_form.html").read_text(encoding="utf-8")

    async def serve(route):
        if route.request.url.split("?")[0] == SR_URL:
            await route.fulfill(status=200, content_type="text/html", body=html)
        else:
            await route.abort()
    await page.route("https://**/*", serve)
    await page.add_init_script(_stub({"panelOpen": True}, **opts))
    await page.goto(SR_URL)
    await page.add_script_tag(path=str(EXT / "content.js"))
    await page.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.wrap')")
    await _watch_for_submits(page)


@browser
async def test_autofill_fills_smartrecruiters_form_inside_its_components_and_never_moves_on(page):
    """Bosch's form on SmartRecruiters keeps every box inside web components' shadow roots. Fill reads each by its
    own words, puts the resume in the Resume box (never the "autocomplete your application" upload), picks City
    from its list, and never presses Next, Apply With Indeed or SEEK."""
    std = lambda v: {"value": v, "kind": "standard"}
    await _on_smartrecruiters(page, resume="resume.pdf", answers={
        "First name": std("Alex"), "Last name": std("Rivera"), "Email": std("alex.rivera@example.edu"),
        "Confirm your email": std("alex.rivera@example.edu"), "City": std("Boston, MA, USA"),
        "Phone number": std("617-555-0123")})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    fields = {f["label"]: f for f in await page.evaluate("__calls.find(c => c.type === 'answers').body.fields")}
    assert {"First name", "Last name", "Email", "Confirm your email", "LinkedIn", "Website", "City", "Phone number",
            "Resume"} <= set(fields), sorted(fields)
    assert fields["Resume"]["type"] == "file" and fields["Resume"]["required"]
    assert "Choose a file or drop it here" not in fields
    assert await page.input_value('input[id="first-name-input"]') == "Alex"
    assert await page.input_value('input[id="confirm-email-input"]') == "alex.rivera@example.edu"
    assert await page.input_value('input[id="spl-form-element_3"]') == "617-555-0123"
    assert await page.input_value('input[id="spl-form-element_8"]') == "Boston, MA, USA"
    files = lambda box: page.evaluate(f"""document.querySelector('[data-test="{box}"]').shadowRoot
        .querySelector('input[type=file]').files.length""")
    assert await files("resume-upload") == 1 and await files("apply-with-resume-container") == 0
    assert await page.evaluate("window.__nextPresses") == 0
    assert page.url == SR_URL
    await _never_submitted(page)


@browser
async def test_the_submit_watcher_sees_a_submit_inside_a_web_component_but_not_next(page):
    """SmartRecruiters' buttons sit inside shadow roots, so the watcher reads the button pressed, not the component
    around it. Next isn't sending it; a Submit drawn the same way is, so the thank-you page after it is logged."""
    await _on_smartrecruiters(page)
    await page.click('[data-test="footer-next"]')
    assert await page.evaluate("window.__nextPresses") == 1
    assert await page.evaluate("sessionStorage.getItem('jobsmith-submit')") is None
    await page.evaluate("""() => {
      const host = document.createElement('oc-button'); host.id = 'written-submit';
      host.attachShadow({ mode: 'open' }).innerHTML = '<button type="button">Submit</button>';
      document.body.appendChild(host); }""")
    await page.click("#written-submit button")
    noted = json.loads(await page.evaluate("sessionStorage.getItem('jobsmith-submit')"))
    assert noted["url"] == SR_URL


@browser
async def test_autofill_answers_each_copy_of_a_component_on_its_own(page):
    """Two copies of one component with the same ids and radio name inside: each box and each Yes/No is its own
    question and gets its own answer."""
    from conftest import TWIN_COMPONENTS
    html = f"<!doctype html><html><body><h1>Apply</h1>{TWIN_COMPONENTS}</body></html>"
    await page.route("https://**/*", lambda r: r.fulfill(status=200, content_type="text/html", body=html)
                     if r.request.url.split("?")[0] == SR_URL else r.abort())
    std = lambda v: {"value": v, "kind": "standard"}
    await page.add_init_script(_stub({"panelOpen": True}, answers={
        "First name": std("Alex"), "Last name": std("Rivera"), "City": std("Boston"),
        "Over 18?": std("Yes"), "Willing to relocate?": std("No"), "Open to nights?": std("Yes"),
        "Preferred name": std("Alex")}))
    await page.goto(SR_URL)
    await page.add_script_tag(path=str(EXT / "content.js"))
    await page.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.wrap')")
    await _watch_for_submits(page)
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    labels = [f["label"] for f in await page.evaluate("__calls.find(c => c.type === 'answers').body.fields")]
    assert sorted(labels) == ["City", "First name", "Last name", "Open to nights?", "Over 18?", "Preferred name",
                              "Willing to relocate?"], labels
    inside = lambda host, sel, js: page.evaluate(
        f"document.querySelector('{host}').shadowRoot.querySelector('{sel}').{js}")
    assert await inside("#first", "#box", "value") == "Alex" and await inside("#last", "#box", "value") == "Rivera"
    assert await inside("#first", "[value=Y]", "checked") and await inside("#last", "[value=N]", "checked")
    assert not await inside("#last", "[value=Y]", "checked")
    assert await inside("#third", "[value=Y]", "checked") and not await inside("#third", "[value=N]", "checked")
    await _never_submitted(page)


@browser
@pytest.mark.parametrize("inside, slotted, sends", [
    ("<slot></slot>", "<span>Submit</span>", True),
    ('<span aria-hidden="true">✓</span> <slot></slot>', "<span>Submit</span>", True),
    ('<span class="material-icons">send</span><slot></slot>', "<span>Submit</span>", True),   # an icon font's word
    ('<slot name="icon"></slot>Submit', '<span slot="icon">check</span>', True),            # a slotted icon
    ('<slot name="icon"></slot>Next', '<span slot="icon">check</span>', False),
], ids=["slotted words", "beside an icon", "beside an icon font's word", "own words, slotted icon", "next"])
async def test_the_submit_watcher_sees_a_submit_whose_words_are_slotted_in(page, inside, slotted, sends):
    """A component's own <button> with the page's words slotted into it, or its own words beside a slotted icon:
    whichever of the words it shows says Submit, pressing it is noticed; a Next beside an icon isn't."""
    await _on_smartrecruiters(page)
    await page.evaluate("""([inside, slotted]) => {
      const host = document.createElement('x-button'); host.id = 'slotted-submit';
      host.attachShadow({ mode: 'open' }).innerHTML = `<button type="button">${inside}</button>`;
      host.innerHTML = slotted;
      document.body.appendChild(host); }""", [inside, slotted])
    await page.click("#slotted-submit")
    noted = json.loads(await page.evaluate("sessionStorage.getItem('jobsmith-submit')") or "null")
    assert (noted and noted["url"] == SR_URL) if sends else noted is None


@browser
async def test_the_submit_watcher_goes_by_the_words_shown_not_a_buttons_value(page):
    """<button value="submit">Next</button> says Next: pressing it isn't sending the application."""
    await _on_smartrecruiters(page)
    await page.evaluate("""() => { const b = document.createElement('button'); b.type = 'button'; b.id = 'next-btn';
      b.value = 'submit'; b.textContent = 'Next'; document.body.appendChild(b); }""")
    await page.click("#next-btn")
    assert await page.evaluate("sessionStorage.getItem('jobsmith-submit')") is None
    await page.evaluate("""() => { const i = document.createElement('input'); i.type = 'submit'; i.id = 'send-it';
      i.value = 'Submit'; i.addEventListener('click', e => e.preventDefault()); document.body.appendChild(i); }""")
    await page.click("#send-it")                                       # a Submit whose words are its value
    assert json.loads(await page.evaluate("sessionStorage.getItem('jobsmith-submit')"))["url"] == SR_URL


ICIMS_PROFILE_URL = "https://uscareers-idemia.icims.com/jobs/8707/full-stack-software-engineering-internship/candidate"


@browser
async def test_autofill_fills_icims_profile_and_leaves_the_login_to_you(page):
    """IDEMIA's iCIMS Candidate Profile makes your account on the same page. Fill attaches the resume first and
    waits while iCIMS reads it (what it reads replaces the form), fills the profile, picks from iCIMS's search
    dropdowns, never touches Login, Password or Password (Re-enter), never presses Submit Profile, and says the
    login is yours."""
    html = (FIXTURES / "icims_idemia_profile_frame.html").read_text(encoding="utf-8")
    await page.route("https://**/*", lambda r: r.fulfill(status=200, content_type="text/html", body=html)
                     if r.request.url.split("?")[0] == ICIMS_PROFILE_URL else r.abort())
    std = lambda v: {"value": v, "kind": "standard"}
    await page.add_init_script(_stub({"panelOpen": True}, resume="resume.pdf", answers={
        "First Name": std("Alex"), "Last Name": std("Rivera"), "Email": std("alex.rivera@example.edu"),
        "Phones Type": std("Mobile"), "Phones Number": std("617-555-0123"), "Country": std("United States"),
        "Login": std("alex.rivera"), "Password": std("hunter2")}))
    await page.goto(ICIMS_PROFILE_URL)
    await page.add_script_tag(path=str(EXT / "content.js"))
    await page.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.wrap')")
    await _watch_for_submits(page)
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=30000)
    assert "create your login and press Submit Profile yourself" in await page.evaluate(f"{note}.innerText")
    labels = [f["label"] for f in await page.evaluate("__calls.find(c => c.type === 'answers').body.fields")]
    assert not [l for l in labels if l in ("Login", "Password", "Password (Re-enter)")], labels
    box = lambda i: page.input_value(f'[id="{i}"]')
    for account in ("PersonProfileFields.Login", "PersonProfileFields.Password", "PersonProfileFields.Password_Confirm"):
        assert await box(account) == "", account
    assert await page.evaluate("window.__resumeRead") == 1
    assert await box("PersonProfileFields.FirstName") == "Alex" and await box("PersonProfileFields.LastName") == "Rivera"
    assert await box("-1_PersonProfileFields.PhoneNumber") == "617-555-0123"
    assert await page.eval_on_selector('[id="-1_PersonProfileFields.PhoneType"]', "e => e.selectedOptions[0].text.trim()") == "Mobile"
    assert await box("-1_PersonProfileFields.AddressCountry") == "United States"
    assert await page.evaluate("window.__signInPresses") == 0
    await _never_submitted(page)


REDRAWN_URL = "https://careers.example.com/apply/redrawn"
REDRAWN = """<form><label for="em">Email</label><input id="em" name="email">
<label for="r">Resume</label><input type="file" id="r" name="resume">
<p id="busy" hidden>Parsing resume, please wait...</p>
<div id="boxes"><label>City <input name="home_city" id="home_city"></label>
<label>City <input name="work_city" id="work_city"></label>
<label>Notes <input name="notes" id="notes"></label></div></form><script>
window.__changes = 0;
document.getElementById("r").addEventListener("change", () => { window.__changes++; setTimeout(() => {
  const busy = document.getElementById("busy"); busy.hidden = false;
  setTimeout(() => {          // the read draws the boxes again: new elements, the two Cities in the other order,
    const box = (n, l) => `<label>${l} <input name="${n}" id="${n}"></label>`;   // and Notes gone
    if (window.__redraw) window.__redraw();
    else document.getElementById("boxes").innerHTML = (window.__dropHome ? "" : box("work_city", "City") + box("home_city", "City"))
      + (window.__dropHome ? box("work_city", "City") : "");
    busy.hidden = true; }, 400); }, 500); });
</script>"""


REDRAWN_BOXES = REDRAWN[REDRAWN.index('<div id="boxes">'):REDRAWN.index('</div></form>')]


async def _redrawn(page, before: str = "", boxes: str = "", **opts):
    """Load the form (its boxes swapped for `boxes` if given), press Fill, wait till it's done. Every test here also
    checks the form was never sent."""
    html = REDRAWN.replace(REDRAWN_BOXES, f'<div id="boxes">{boxes}') if boxes else REDRAWN
    await page.route("https://**/*", lambda r: r.fulfill(status=200, content_type="text/html", body=html)
                     if r.request.url == REDRAWN_URL else r.abort())
    opts = opts or {"byName": {"home_city": {"value": "Boston"}, "work_city": {"value": "Denver"},
                               "notes": {"value": "Hi"}, "email": {"value": "alex.rivera@example.com"}}}
    await page.add_init_script(before + _stub({"panelOpen": True}, resume="resume.pdf", **opts))
    await page.goto(REDRAWN_URL)
    await _watch_for_submits(page)
    await page.add_script_tag(path=str(EXT / "content.js"))
    await page.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.wrap')")
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=15000)


@browser
async def test_boxes_a_resume_read_draws_again_get_their_own_answers(page):
    """A site that reads your resume can draw its boxes again (new elements, maybe in another order). Each answer
    goes back into its own box, found by the box's name: two "City" boxes swapped by the redraw keep their own
    answers, and an answer whose box is gone is typed nowhere."""
    await _redrawn(page)
    assert await page.input_value("#home_city") == "Boston" and await page.input_value("#work_city") == "Denver"
    assert await page.evaluate("window.__changes") == 1
    await _never_submitted(page)


@browser
async def test_an_answer_whose_box_a_resume_read_removed_goes_nowhere_else(page):
    """Two boxes with the same question, and the read keeps only one: the one it kept gets its own answer, never
    the other box's."""
    await _redrawn(page, "window.__dropHome = true;")
    assert await page.input_value("#work_city") == "Denver"
    assert await page.locator("#home_city").count() == 0
    await _never_submitted(page)


@browser
async def test_a_removed_box_never_passes_its_answer_to_a_box_still_there(page):
    """City and Country share the name "value" (some forms name every box that), and the read takes City away
    and leaves Country as it was. City's answer goes nowhere: Country is its own question."""
    await _redrawn(page, "window.__redraw = () => document.getElementById('city').closest('label').remove();",
                   boxes='<label>City <input name="value" id="city"></label>'
                         '<label>Country <input name="value" id="country"></label>',
                   answers={"City": {"value": "Boston"}})
    assert await page.locator("#city").count() == 0
    assert await page.input_value("#country") == ""
    await _never_submitted(page)


PHONE = '<label>Phone <input {}></label>'
A1, A2 = "617-555-0101", "617-555-0102"      # the 1st and 2nd Phone box's answers, told apart


@browser
@pytest.mark.parametrize("before, after, typed", [
    # the same question drawn again as often as before: each answer goes back to its own place
    ([""] * 2, [""] * 2, [A1, A2]),
    (['name="phone"'] * 2, ['name="phone"'] * 2, [A1, A2]),
    # one of two replaced, and the one kept moved first: it keeps its own answer, the new box takes the other's
    (['name="phone"', 'name="phone" id="kept"'], ['name="phone"'] * 2, [A2, A1]),
    # fewer or more boxes for a question than before: which is which can't be told, so none is typed in
    ([""] * 2, [""], [""]),
    (['name="phone"'] * 2, ['name="phone"'], [""]),
    (['name="phone"'], ['name="phone"'] * 2, ["", ""]),
], ids=["unnamed", "named", "one-replaced", "unnamed-fewer", "named-fewer", "named-more"])
async def test_boxes_drawn_again_are_matched_only_when_sure(page, before, after, typed):
    """The read draws a question's boxes again with no telling them apart but their order. Answers go back only
    when there are as many as before; otherwise the boxes are left for you."""
    new = "".join(PHONE.format(a + ' class="new"') for a in after)
    redraw = f"""window.__redraw = () => {{ const kept = document.getElementById('kept');
      document.getElementById('boxes').innerHTML = {json.dumps(new)};
      if (kept) document.querySelector('#boxes .new').replaceWith(kept); }};"""
    await _redrawn(page, redraw, boxes="".join(PHONE.format(b) for b in before),
                   byNth={"Phone": [{"value": A1}, {"value": A2}]})
    boxes = page.locator("#boxes input")
    assert [await boxes.nth(i).input_value() for i in range(await boxes.count())] == typed
    await _never_submitted(page)


@browser
async def test_fill_again_doesnt_upload_a_resume_that_is_already_attached(page):
    """Pressing Fill again on a form whose resume is already attached doesn't send it to be read a second time."""
    await _redrawn(page)
    await page.evaluate("""() => { const b = document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note');
                                   b.innerText = ''; }""")
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')", timeout=15000)
    assert await page.evaluate("window.__changes") == 1
    assert await page.evaluate("__calls.filter(c => c.type === 'file').length") == 1
