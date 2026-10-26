"""The Chrome extension's own scripts in a real (headless) browser, with chrome.* stubbed: where the folded tab
goes when another extension's tab is on the right edge, the popup opening the panel, and autofill with no PDF."""
import json
import os
import re
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


def _posting() -> str:
    """The saved Figma posting, served over local HTTP (not file://) so requests to its submit address are seen."""
    if "url" not in _SITE:
        html = (FIXTURES / "greenhouse_board_posting.html").read_bytes()
        srv = _serve({FORM_ACTION: (200, "text/html", lambda body=None: html)})
        _SITE["url"] = f"http://127.0.0.1:{srv.server_port}{FORM_ACTION}"
    return _SITE["url"]


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
const ANSWERS = {"First Name": "Alex", "Last Name": "Rivera", "Email": "alex.rivera@example.com", "Phone": "555-010-2030"};
const reply = msg => {
  if (msg.type === "ping") return { ok: true, data: { ai: "Gemini", ai_ok: true, resume: __opts.resume || null } };
  if (msg.type === "answers") return { ok: true, data: { job_id: "j1", resume: __opts.resume || null, error: null,
    answers: msg.body.fields.map(f => f.type === "file" ? { id: f.id, file: "resume", kind: "file" }
                                                       : Object.assign({ id: f.id, value: ANSWERS[f.label] || "", kind: "standard" },
                                                                       (__opts.answers || {})[f.label] || {})) } };
  if (msg.type === "generate") return { ok: true, data: Object.assign({ text: "", based_on: [], error: null }, __opts.generate || {}) };
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


async def _load(page, store: dict, other_tab: bool = True, wait: bool = True, **opts):
    await page.add_init_script(_stub(store, **opts))
    await page.goto(_posting())
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
    await frames["step"].wait_for_function("document.getElementById('phone').value === '555-010-2030'")
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
    assert await page.input_value("#phone") == "555-010-2030"
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
    await _load(page, {"panelOpen": True}, answers={"Country": {"value": "555-010-2030", "qkind": "location"}})
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')")
    assert await page.input_value("#phone") == "555-010-2030"
    assert await page.input_value(COUNTRY_MIRROR) == ""
    assert await page.input_value("#country") == ""
    needs = (await page.evaluate(f"{note}.innerText")).split("Needs you:")[1]
    assert "Country" in needs and "isn't a place" in needs
    assert await page.evaluate("[...document.querySelectorAll('input')].filter(e => e.value === '555-010-2030').length") == 1
    await _never_submitted(page)


def test_a_phone_number_is_not_a_country():
    from jobsmith import classify, draft
    assert classify.question_kind("Country", "combobox") == "location"
    assert draft.shape_fits("location", "555-010-2030") and draft.shape_fits("location", "+1 (555) 010-2030")
    assert draft.shape_fits("location", "United States") is None and draft.shape_fits("location", "US") is None
    held = draft._checked({"label": "Country", "qtype": "combobox", "options": []},
                          {"answer": "555-010-2030", "confidence": 0.9, "kind": "standard"}, {"company": "Figma"})
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
                        "Two words", ESSAY, " ".join(["word"] * 41), "One. Two. Three.", "555-010-2030")]


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
async def test_popup_autopilot_box_starts_unchecked_and_remembers(page):
    async def popup(p, store):
        await p.add_init_script(_stub(store))
        await p.goto((EXT / "popup.html").resolve().as_uri())
        await p.wait_for_selector("#actions:not([hidden])")

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
    profile.set_answer("phone", "555-010-2030", True)
    r = await extension.answers("https://job-boards.greenhouse.io/acme/jobs/10", [
        {"id": "js1", "label": "Tell us your first name", "type": "text", "required": True},
        {"id": "js2", "label": "Please tell us your phone number so we can reach you", "type": "text", "required": True},
        {"id": "js3", "label": "Tell us your phone troubleshooting process", "type": "textarea", "required": True},
        {"id": "js4", "label": "Tell us your first name (as on your ID)", "type": "text", "required": True}],
        title="Intern")
    by = {a["id"]: a for a in r["answers"]}
    assert by["js1"]["value"] == "Alex" and by["js2"]["value"] == "555-010-2030" and by["js4"]["value"] == "Alex"
    assert by["js3"]["value"] != "555-010-2030" and by["js3"]["qkind"] == "essay"


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
    ("Tell us your phone troubleshooting process", "text", "555-010-2030", False),   # a story that names a fact
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


@browser
@pytest.mark.parametrize("form_host, beside", [(LISTED, None), (UNLISTED, None), (LISTED, UNLISTED), (UNLISTED, LISTED)])
async def test_popup_reaches_a_job_site_form_in_a_frame_opened_before_the_extension(form_host, beside, tmp_path):
    """A company's careers page embeds an application form in a frame from another site, and the tab was open before
    the extension was loaded, so no frame has Jobsmith's script. The real popup adds it to the top page and to a frame
    from a listed job site (manifest host_permissions; see SECURITY.md), and autofill fills that form. A frame from
    any other site gets "Reload this page" and is left alone; beside a job-site form (a video, say), it's just skipped.
    A job-site frame with no form in it (a video) doesn't hide the reload another site's form needs.

    The careers page is served from 127.0.0.1, which the extension may reach (the engine's address): that stands in
    for the access a click on the toolbar button grants to the top page, which a test can't click."""
    import asyncio
    import socket
    import subprocess
    import tempfile
    from playwright.async_api import async_playwright
    tls = _self_signed([LISTED, UNLISTED], tmp_path)
    form = _serve({"/apply": (200, "text/html", (FIXTURES / "greenhouse_board_posting.html").read_bytes()),
                   "/video": (200, "text/html", b"<p>A video</p><input id='q' aria-label='Search videos'>")}, tls=tls)
    engine = _serve({"/api/ext/ping": (200, "application/json", b'{"ok": true, "ai": "none", "ai_ok": false, "resume": null}'),
                     "/api/ext/answers": (200, "application/json", _engine_answers)})
    form_url = f"https://{form_host}:{form.server_port}/apply"
    page_html = (f'<h1>Careers</h1><iframe id="gh" src="{form_url}" style="width:1000px;height:2400px"></iframe>' +
                 (f'<iframe id="other" src="https://{beside}:{form.server_port}/video" '
                  f'style="width:640px;height:360px"></iframe>' if beside else ""))
    careers = _serve({"/careers": (200, "text/html", page_html.encode())})
    careers_url = f"http://127.0.0.1:{careers.server_port}/careers"
    # Chromium with an ordinary profile (Playwright's own contexts are incognito-like, where extensions don't run),
    # driven over the DevTools protocol so the extension can be loaded after the tab is open.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    profile_dir = tempfile.mkdtemp(prefix="jobsmith-chrome-")
    chrome = subprocess.Popen([CHROMIUM, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}",
                               "--enable-unsafe-extension-debugging", "--no-first-run", "--no-default-browser-check",
                               f"--host-resolver-rules=MAP {LISTED} 127.0.0.1, MAP {UNLISTED} 127.0.0.1",
                               "--ignore-certificate-errors", *browser_args(), "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import urllib.request
        for _ in range(200):                     # Chrome's DevTools endpoint answers once it's ready to be driven
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).read()
                break
            except OSError:
                await asyncio.sleep(0.1)
        async with async_playwright() as pw:
            b = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = b.contexts[0]
            tab = await ctx.new_page()
            for p in ctx.pages:
                if p is not tab:
                    await p.close()                                      # Chrome's blank start tab
            await tab.goto(careers_url)
            frame = tab.frame(url=form_url)
            await frame.wait_for_selector("#first_name")
            ext_id = (await (await b.new_browser_cdp_session()).send(
                "Extensions.loadUnpacked", {"path": str(EXT)}))["id"]               # loaded after the tab opened
            assert await frame.evaluate("document.querySelector('[data-jobsmith-id]') === null")   # no script in it yet

            setup = await ctx.new_page()
            await setup.goto(f"chrome-extension://{ext_id}/popup.html")
            await setup.evaluate(f"chrome.storage.local.set({{engine: 'http://127.0.0.1:{engine.server_port}'}})")
            await setup.close()
            popup = await ctx.new_page()
            # Opened as a page, the popup's "active tab" is itself: point it at the only other tab, the careers page
            # (tab URLs are hidden without the "tabs" permission). Everything else is the real extension.
            await popup.add_init_script(ONLY_THE_CAREERS_TAB)
            await popup.goto(f"chrome-extension://{ext_id}/popup.html")
            await popup.wait_for_selector("#actions:not([hidden])")
            await tab.wait_for_selector("#jobsmith-panel", state="attached", timeout=10000)   # the popup opened the panel
            await _watch_for_submits(tab, frame)
            await popup.wait_for_timeout(500)
            hint = None if await popup.is_hidden("#result") else await popup.inner_text("#result")
            await popup.click("#fill")                                                     # (closes the popup)
            if form_host == LISTED:
                assert hint is None                                                         # no reload needed
                await frame.wait_for_function("document.getElementById('first_name').value === 'Alex'", timeout=15000)
                assert await frame.input_value("#email") == "alex.rivera@example.com"
                await frame.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.note')"
                                              "?.innerText.includes('Filled')")       # autofill finished in the frame
            else:
                assert hint == "Reload this page to fill the form inside it."
                await tab.wait_for_timeout(2000)
                assert await frame.input_value("#first_name") == ""                         # not reached: reload it
                assert await frame.evaluate("document.querySelector('[data-jobsmith-id]') === null")
            # Open the popup again: the frame's state is read afresh, not remembered from the first time.
            if not popup.is_closed():
                await popup.close()
            again = await ctx.new_page()
            await again.add_init_script(ONLY_THE_CAREERS_TAB)
            await again.goto(f"chrome-extension://{ext_id}/popup.html")
            await again.wait_for_selector("#actions:not([hidden])")
            await again.wait_for_timeout(1000)
            assert await again.inner_text("#fill") != "Can't fill this page"                 # it reached the tab
            if form_host == LISTED:
                assert await again.is_hidden("#result")                                     # the frame has it now
                assert await frame.evaluate("document.querySelectorAll('#jobsmith-panel').length") == 1   # not injected twice
                await frame.fill("#first_name", "")
                await again.click("#fill")                                                  # and it still fills
                await frame.wait_for_function("document.getElementById('first_name').value === 'Alex'", timeout=15000)
            else:
                assert await again.inner_text("#result") == "Reload this page to fill the form inside it."
            if beside:                                                       # nothing typed or shown there
                other = tab.frame(url=lambda u: u.endswith("/video"))
                assert await other.evaluate("document.querySelector('#jobsmith-panel') === null")
                assert await other.input_value("#q") == ""
            await _never_submitted(tab)
            await b.close()
    finally:
        chrome.kill()
        for s in (form, engine, careers):
            s.shutdown()
        __import__("shutil").rmtree(profile_dir, ignore_errors=True)
