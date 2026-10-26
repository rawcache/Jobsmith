"""The Chrome extension's own scripts in a real (headless) browser, with chrome.* stubbed: where the folded tab
goes when another extension's tab is on the right edge, the popup opening the panel, and autofill with no PDF."""
import json
import os
from pathlib import Path

import pytest

from jobsmith import devtools, extension, profile
from conftest import FIXTURES

EXT = Path(__file__).resolve().parents[1] / "extension"
POSTING = (FIXTURES / "greenhouse_board_posting.html").resolve().as_uri()


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
                                                       : { id: f.id, value: ANSWERS[f.label] || "", kind: "standard" }) } };
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
        b = await pw.chromium.launch(headless=True, executable_path=CHROMIUM)
        p = await b.new_page(viewport={"width": 1280, "height": 900})
        yield p
        await b.close()


def _stub(store: dict, **opts) -> str:
    return f"window.__initialStore = {json.dumps(store)}; window.__opts = {json.dumps(opts)};" + CHROME_STUB


async def _load(page, store: dict, other_tab: bool = True, wait: bool = True, **opts):
    await page.add_init_script(_stub(store, **opts))
    await page.goto(POSTING)
    # Count form submissions: autofill must never send the application.
    await page.evaluate("""window.__submits = 0; document.addEventListener("submit", e => { __submits++; e.preventDefault(); }, true);
      HTMLFormElement.prototype.submit = function () { __submits++; }; HTMLFormElement.prototype.requestSubmit = function () { __submits++; }; 0""")   # 0: evaluate calls a function it gets back
    if not other_tab:
        await page.evaluate("document.getElementById('other-extension-tab').remove()")
    await page.add_script_tag(path=str(EXT / "content.js"))
    if wait:
        await page.wait_for_function("document.querySelector('#jobsmith-panel')?.shadowRoot?.querySelector('.wrap')")


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
    await page.goto(POSTING)
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
    assert page.url == POSTING and await page.evaluate("__submits") == 0              # nothing submitted


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


@browser
async def test_autofill_attaches_the_resume_pdf_when_there_is_one(page):
    await _load(page, {"panelOpen": True}, resume="Alex_Rivera_resume.pdf")
    await page.evaluate("__listeners.forEach(f => f({type: 'fill'}, {}, () => {}))")
    note = "document.querySelector('#jobsmith-panel').shadowRoot.querySelector('.note')"
    await page.wait_for_function(f"{note}?.innerText.includes('Filled')")
    assert "Add your resume PDF" not in await page.evaluate(f"{note}.innerText")
    assert await page.evaluate("document.getElementById('resume').files[0].name") == "Alex_Rivera_resume.pdf"
    assert await page.evaluate("__submits") == 0


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
    assert await page.evaluate("__calls.find(c => c.inject)") == {"inject": ["content.js"], "allFrames": True}   # iframe forms too
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
