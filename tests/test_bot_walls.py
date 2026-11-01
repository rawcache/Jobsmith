"""Bot checks: a page a site shows instead of the form when it takes the browser for a bot. Jobsmith never tries to
get past one (rule 5: it's a CAPTCHA by another name); it stops and hands the application to the user.

tests/fixtures/bot_walls/ holds what SmartRecruiters showed for Bosch's internship form on 2026-10-31 (DataDome's
"Access is temporarily restricted", drawn in a frame from geo.captcha-delivery.com). The frame is served here at
DataDome's own address from the saved copy, so nothing leaves the machine."""
import pytest

from jobsmith import db, runner, scheduler, sources
from jobsmith.fill import base
from conftest import FIXTURES

WALLS = FIXTURES / "bot_walls"
BOSCH = "https://jobs.smartrecruiters.com/BoschGroup/744000158818709-quality-engineering-intern-co-op-spring-2027"


async def _serve_datadome(target, body: str | None = None) -> None:
    """Answer DataDome's frame address (on a page or a browser context) with the saved frame."""
    html = body if body is not None else (WALLS / "datadome_frame.html").read_text(encoding="utf-8")

    async def fulfill(route):
        await route.fulfill(status=403, content_type="text/html", body=html)
    await target.route("https://geo.captcha-delivery.com/**", fulfill)


@pytest.fixture
async def page():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        exe = __import__("os").environ.get("JOBSMITH_CHROMIUM_PATH")
        b = await pw.chromium.launch(headless=True, args=base.browser_args(), **({"executable_path": exe} if exe else {}))
        p = await b.new_page()
        await p.route("http*://**", lambda r: r.abort() if "captcha-delivery" not in r.request.url else r.fallback())
        yield p
        await b.close()


async def test_smartrecruiters_datadome_page_is_seen_as_a_bot_check(page):
    await _serve_datadome(page)
    await page.goto((WALLS / "smartrecruiters_datadome.html").resolve().as_uri())
    await page.frame_locator("iframe").locator("h1").wait_for()
    assert await base.bot_wall(page) == "Access is temporarily restricted"


async def test_a_datadome_frame_is_a_bot_check_even_before_its_words_load(page):
    await _serve_datadome(page, body="<html><body></body></html>")
    await page.goto((WALLS / "smartrecruiters_datadome.html").resolve().as_uri())
    await page.wait_for_timeout(300)
    assert await base.bot_wall(page) == "a bot check from geo.captcha-delivery.com"


async def test_a_chat_widgets_box_in_another_frame_doesnt_hide_a_bot_check(page):
    """Only the page and the frame an application lives in (iCIMS's) count as a form: a recruiter-chat widget's
    name box in a frame of its own is no reason to think the bot check is a form."""
    await _serve_datadome(page)
    await page.goto((WALLS / "smartrecruiters_datadome.html").resolve().as_uri())
    await page.frame_locator("iframe").locator("h1").wait_for()
    await page.evaluate("""document.body.insertAdjacentHTML('beforeend', '<iframe name="te__acsWidgetMenu" srcdoc="' +
      '<label>First name <input name=firstName></label>"></iframe>')""")
    await page.wait_for_function("frames.length >= 2")
    assert await base.bot_wall(page) == "Access is temporarily restricted"


async def test_a_form_in_icims_frame_is_never_a_bot_check(page):
    await page.goto((FIXTURES / "icims_idemia_posting.html").resolve().as_uri())
    await page.frame(name="icims_content_iframe").locator("a.iCIMS_ApplyOnlineButton").click()
    await page.frame(name="icims_content_iframe").wait_for_url("**/icims_idemia_email_frame.html")
    assert await base.bot_wall(page) == ""


@pytest.mark.parametrize("form", ["lever_palantir_form.html", "ashby_ramp_form.html", "greenhouse_figma_live.html"])
async def test_an_application_form_is_never_a_bot_check(page, form):
    """Real forms carry hCaptcha or reCAPTCHA under their fields; that's a CAPTCHA at Submit, not a wall."""
    await page.goto((FIXTURES / form).resolve().as_uri())
    assert await base.bot_wall(page) == ""


@pytest.mark.parametrize("fields", [
    "<label>Email <input type=email name=e></label>",                                # one field is enough
    "<label>Name <input name=n></label><label>Why? <textarea name=w></textarea></label>",
    "<p>Are you 18 or older?</p><label><input type=radio name=a value=y> Yes</label><label><input type=radio "
    "name=a value=n> No</label>",                                                   # a page of choices
])
async def test_a_form_that_mentions_robots_is_still_a_form(page, fields):
    await page.set_content(f"<form>{fields}<p>Please verify you are human below.</p></form>")
    assert await base.bot_wall(page) == ""


async def _bosch_job() -> str:
    jid = sources.add_job_url(BOSCH, "Bosch", "Quality Engineering Intern / Co-op - Spring 2027")
    db.x("UPDATE jobs SET url=?, ats='smartrecruiters', description='Quality engineering at Bosch.' WHERE id=?",
         ((WALLS / "smartrecruiters_datadome.html").resolve().as_uri(), jid))
    db.set_settings({"browser_channel": "", "headless": True, "autonomy": "autonomous", "trust_threshold": 0})
    await _serve_datadome(await runner.browser.context())
    return jid


async def test_autopilot_hands_a_bot_check_to_you_and_never_retries_it(fake_llm):
    """Reading the form meets the bot check: nothing is drafted or filled, the job waits for you with the line the
    site showed, you're told, and autopilot doesn't pick it again on its own."""
    fake_llm(lambda s, p: {"answers": []})
    jid = await _bosch_job()
    try:
        await runner.prepare(jid, research=False)
    finally:
        await runner.browser.close()
    job = db.q1("SELECT status, error, hold_reason FROM jobs WHERE id=?", (jid,))
    assert job["status"] == "error" and "Access is temporarily restricted" in job["hold_reason"]
    assert "never tries to get past" in job["error"] and "SmartRecruiters" in job["error"]
    assert [r["status"] for r in db.q("SELECT status FROM runs WHERE job_id=?", (jid,))] == ["waiting_user"]
    assert not db.q("SELECT 1 FROM drafts WHERE job_id=?", (jid,))
    assert jid not in scheduler.pick_new_jobs(50)


async def test_a_held_bot_check_is_never_retried_even_when_its_words_look_like_a_network_hiccup():
    """Cloudflare's "Checking if the site connection is secure" has "connect" in it, which the scheduler's retry for
    network errors looks for. A bot check is never retried, an hour later or ever."""
    jid = sources.add_job_url(BOSCH, "Bosch", "Quality Engineering Intern / Co-op - Spring 2027")
    db.x("UPDATE jobs SET fit_score=90 WHERE id=?", (jid,))
    runner._held_by_bot_wall(db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,))), runner.Run(jid, "fill"),
                             "Checking if the site connection is secure")
    db.x("UPDATE jobs SET updated_at=? WHERE id=?", (db.now() - 7200, jid))
    assert "onnect" in db.q1("SELECT error FROM jobs WHERE id=?", (jid,))["error"]
    assert jid not in scheduler.pick_new_jobs(50)


async def test_a_bot_check_when_filling_stops_before_anything_is_typed(fake_llm, tmp_path, monkeypatch):
    """The form was read earlier (or by the extension), but this time the site shows its bot check: autopilot
    stops at once, presses nothing, and hands it over. The tab is still watched, so if you finish the application
    in the Jobsmith window its confirmation is recorded."""
    watched = []

    async def watch(job_id, *a):
        watched.append(job_id)
    monkeypatch.setattr(runner, "watch_tab", watch)
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    db.x("INSERT INTO documents(kind, filename, path, text, is_primary, created_at) VALUES('resume','resume.pdf',?,'',1,?)",
         (str(pdf), db.now()))
    jid = await _bosch_job()
    db.x("UPDATE jobs SET questions=? WHERE id=?", (db.enc([{"field": "#first", "label": "First name", "qtype": "text",
                                                             "required": True}]), jid))
    try:
        await runner.fill(jid, submit=True)
    finally:
        await runner.browser.close()
    job = db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (jid,))
    assert job["status"] == "error" and "bot check" in job["hold_reason"], db.q("SELECT kind, status, log FROM runs WHERE job_id=?", (jid,))
    assert not db.q("SELECT 1 FROM runs WHERE job_id=? AND kind='submit'", (jid,))
    assert watched == [jid]


async def test_a_multi_page_form_that_turns_into_a_bot_check_is_handed_to_you(page):
    """Workday and iCIMS go page by page: a bot check on any page stops there (multistep raises BotWall; the runner
    holds the job as above), before any field is read or typed into."""
    from jobsmith.fill import base as fb, multistep
    await _serve_datadome(page)
    asked = []

    async def answer(fields):
        asked.append(fields)
        return {}
    with pytest.raises(fb.BotWall, match="Access is temporarily restricted"):
        await multistep.run(page, (WALLS / "smartrecruiters_datadome.html").resolve().as_uri(), answer=answer,
                            files={}, log=lambda m: None, wait_for_user=None, allow_submit=lambda: False)
    assert asked == []


async def test_a_bot_check_in_a_multi_page_application_is_held_through_the_runner(page, tmp_path, monkeypatch):
    """The runner's side for Workday and iCIMS: held with the site's line, nothing submitted, the tab still watched.
    The runner gets this test's page (DataDome served locally, everything else refused), never a window of its own."""
    watched = []

    async def watch(job_id, *a):
        watched.append(job_id)

    class Given:
        async def new_page(self):
            return page

        def want_headless(self):
            return True
    monkeypatch.setattr(runner, "watch_tab", watch)
    monkeypatch.setattr(runner, "browser", Given())
    monkeypatch.setattr(runner, "takeover", Given())
    await _serve_datadome(page)
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    db.x("INSERT INTO documents(kind, filename, path, text, is_primary, created_at) VALUES('resume','resume.pdf',?,'',1,?)",
         (str(pdf), db.now()))
    jid = sources.add_job_url("https://acme.wd1.myworkdayjobs.com/x/job/1", "Acme", "Hardware Intern")
    db.x("UPDATE jobs SET url=?, ats='workday' WHERE id=?", ((WALLS / "smartrecruiters_datadome.html").resolve().as_uri(), jid))
    db.set_settings({"autonomy": "autonomous", "trust_threshold": 0})
    try:
        await runner.fill_multistep(jid, submit=True)
        import asyncio
        await asyncio.sleep(0.1)                         # the watcher is started as a task
    finally:
        runner.live_drop(jid)
    job = db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (jid,))
    assert job["status"] == "error" and "Access is temporarily restricted" in job["hold_reason"], \
        db.q("SELECT log FROM runs WHERE job_id=?", (jid,))
    assert not db.q("SELECT 1 FROM runs WHERE job_id=? AND kind='submit'", (jid,))
    assert watched == [jid]
