"""Fill a local mock of Greenhouse's form in a real (headless) browser."""
import json
import shutil

import pytest

from jobsmith import db, draft, jobdetail, profile, runner, sources
from jobsmith.fill import greenhouse
from jobsmith.fill.base import page_confirms_submission, scan_form
from conftest import FIXTURES

pytestmark = pytest.mark.skipif(shutil.which("chromium") is None and not __import__("os").path.exists("/opt/pw-browsers"),
                                reason="no browser available")


async def _job_with_drafts(fake_llm, tmp_path):
    await profile.ingest_document(FIXTURES / "sample_resume.tex")
    for k, v in {"enrollment_start": "Aug 2023", "race": "Asian (Indian)", "hispanic_latino": "No", "country": "United States"}.items():
        profile.set_answer(k, v)
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    db.x("INSERT INTO documents(kind, filename, path, text, is_primary, created_at) VALUES('resume','resume.pdf',?, '',0,?)",
         (str(pdf), db.now()))
    data = json.loads((FIXTURES / "greenhouse_job.json").read_text())
    url = (FIXTURES / "mock_greenhouse.html").resolve().as_uri()
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/123", "Acme Robotics", "SWE Intern")
    db.x("UPDATE jobs SET url=?, description='Jetson', questions=? WHERE id=?",
         (url, db.enc(jobdetail.normalize_greenhouse(data)), jid))
    jetson = [f["id"] for f in profile.facts() if "Jetson" in f["text"]]
    fake_llm(lambda s, p: {"answers": [
        {"field": "question_1004", "answer": "I deployed a fire/smoke detection model on NVIDIA Jetson Nano.",
         "fact_ids": jetson, "confidence": 0.9},
        {"field": "question_1005", "answer": "No", "fact_ids": [], "confidence": 0.3},
        {"field": "cover_letter", "answer": "I built perception systems on Jetson.", "fact_ids": jetson, "confidence": 0.8}]})
    await draft.draft_job(jid, research=False)
    return jid, url


async def _shown(page, sel):
    from jobsmith.fill.base import combobox_text
    return await combobox_text(page, sel)


@pytest.fixture
async def page():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        exe = __import__("os").environ.get("JOBSMITH_CHROMIUM_PATH")
        b = await pw.chromium.launch(headless=True, **({"executable_path": exe} if exe else {}))
        p = await b.new_page()
        yield p
        await b.close()


async def test_greenhouse_fill_stops_before_submit(fake_llm, tmp_path, page):
    jid, url = await _job_with_drafts(fake_llm, tmp_path)
    drafts = runner._drafts_for_fill(jid)
    cover = tmp_path / "cl.txt"
    cover.write_text("letter")
    await greenhouse.open_form(page, url)
    extras = {"country": "United States", "hispanic_latino": "No", "location_full": "Boston, Massachusetts, United States"}
    res = await greenhouse.fill(page, drafts, {"resume": str(tmp_path / "resume.pdf"), "cover_letter": str(cover)}, extras)
    failed = dict(res["failed"])
    assert await page.input_value("#first_name") == "Alex"
    assert await page.input_value("#email") == "alex.rivera@example.edu"
    assert await _shown(page, "#question_1002") == "3.5 - 3.79"        # combobox
    assert await page.input_value("#question_1003") == "No"                # native select
    assert await _shown(page, "#question_1005") == "No"
    assert "Jetson" in await page.input_value("#question_1004")
    assert await _shown(page, "#country") == "United States +1"
    assert await _shown(page, "#candidate-location") == "Boston, Massachusetts, United States"
    assert await _shown(page, "#school--0") == "Example Institute of Technology"
    assert await _shown(page, "#degree--0") == "Bachelor's Degree"
    assert await _shown(page, "#discipline--0") == "Computer Engineering"
    assert await _shown(page, "#start-month--0") == "August" and await page.input_value("#start-year--0") == "2023"
    assert await _shown(page, "#end-month--0") == "May" and await page.input_value("#end-year--0") == "2027"
    assert await _shown(page, '[id="4028769003"]') == "South Asian"
    assert await _shown(page, "#hispanic_ethnicity") == "No"
    assert await page.evaluate("document.querySelector('#resume').files.length") == 1
    assert await page.evaluate("document.querySelector('#cover_letter').files.length") == 1
    assert "Gender" in failed or await _shown(page, "#gender") == ""    # EEO left for the user
    assert not await page_confirms_submission(page)                         # nothing submitted


async def test_scan_generic_form(page):
    await page.goto((FIXTURES / "mock_greenhouse.html").resolve().as_uri())
    fields = {f["label"]: f for f in await scan_form(page)}
    assert fields["First Name"]["field"] == "#first_name"
    assert fields["Will you now or in the future require visa sponsorship?"]["options"] == ["Yes", "No"]
    assert fields["What is your cumulative GPA?"]["qtype"] == "select"
    assert fields["Resume/CV"]["qtype"] == "file"


async def test_runner_fill_and_detect_submission(fake_llm, tmp_path):
    jid, _ = await _job_with_drafts(fake_llm, tmp_path)
    db.set_settings({"browser_channel": "", "headless": True, "autonomy": "autonomous", "trust_threshold": 0})
    # user approves every remaining field, sets EEO answers
    for d in draft.drafts_for(jid):
        db.x("UPDATE drafts SET verdict='green' WHERE id=?", (d["id"],))
    try:
        await runner.fill(jid, submit=True)
    finally:
        await runner.browser.close()
    job = db.q1("SELECT status FROM jobs WHERE id=?", (jid,))
    runs = db.q("SELECT kind, status, log FROM runs WHERE job_id=? ORDER BY id", (jid,))
    assert job["status"] == "submitted", runs
    assert any(r["kind"] == "submit" and r["status"] == "done" for r in runs)


async def test_multistep_signin_handoff_and_review(fake_llm, tmp_path, page):
    from jobsmith.fill import multistep
    await profile.ingest_document(FIXTURES / "sample_resume.tex")
    profile.set_answer("how_heard", "LinkedIn")
    jid = sources.add_job_url("https://acme.wd1.myworkdayjobs.com/x/job/1", "Acme", "Hardware Intern")
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    jetson = [f["id"] for f in profile.facts() if "Jetson" in f["text"]]

    def responder(system, prompt):
        qs = prompt.split("QUESTIONS TO ANSWER:")[1]
        return {"answers": [{"field": "#why", "answer": "I deployed a detection model on NVIDIA Jetson Nano.",
                             "fact_ids": jetson, "confidence": 0.9}] if "#why" in qs else []}
    fake_llm(responder)
    asked = []

    async def answer(fields):
        results, _ = await draft.answer_fields(job, fields)
        draft.save_results(jid, fields, results)
        return {k: v.get("answer", "") for k, v in results.items()}

    async def wait_for_user(msg, check, negate=False):
        asked.append(msg)          # the "user" signs in
        await page.fill("#em", "alex@example.edu")
        await page.fill("#pw", "not-typed-by-jobsmith")
        await page.click("#signin")
        return not await check() if negate else await check()

    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    url = (FIXTURES / "mock_multistep.html").resolve().as_uri()
    logs = []
    res = await multistep.run(page, url, answer=answer, files={"resume": str(pdf)}, log=logs.append,
                              wait_for_user=wait_for_user, allow_submit=lambda: False)
    assert asked and res["status"] == "review", (res, logs)
    summary = await page.inner_text("#summary")
    import json as j
    st = j.loads(summary)
    assert st == {"first": "Alex", "email": "alex.rivera@example.edu", "heard": "LinkedIn", "resume": 1,
                  "why": "I deployed a detection model on NVIDIA Jetson Nano.", "spons": "No"}
    assert not await page.locator("text=Thank you for applying").count()       # stopped before Submit
    saved = {d["field"]: d for d in draft.drafts_for(jid)}
    assert saved["#why"]["kind"] == "generated" and saved["#first"]["kind"] == "answer_bank"


async def test_real_react_select_ignores_other_option_lists(page):
    """Built from the real react-select library, plus a hidden phone-country list with
    [role=option] items like Greenhouse has. Options must come from each field's own menu."""
    from jobsmith.fill.base import combobox_text, fill_combobox
    await page.goto((FIXTURES / "react_select_real.html").resolve().as_uri())
    cases = [("#candidate-location", "Atlanta, Georgia, United States", "Atlanta", "Atlanta, Georgia, United States"),
             ("#question_1", "He/him/his", None, "He/him/his"),
             ("#question_2", "No", None, "No"),
             ("#question_4", "Georgia", None, "Georgia"),
             ("#degree--0", "Bachelor's", None, "Bachelor's Degree"),
             ('[id="4028769003"]', "South Asian", None, "South Asian"),
             ("#veteran_status", "I am not a protected veteran", None, "I am not a protected veteran")]
    for sel, value, query, shown in cases:
        assert await fill_combobox(page, sel, value, query=query), sel
        assert await combobox_text(page, sel) == shown
    # no match: leaves it alone instead of guessing
    assert not await fill_combobox(page, "#question_5", "Carrier pigeon", wait_ms=1500)
    assert (await combobox_text(page, "#question_5")).startswith("Select")


async def test_verification_code_step(page):
    """After Submit, some forms email a code. Jobsmith spots the prompt and types the code you give it."""
    from jobsmith.fill.base import enter_security_code, page_confirms_submission, security_code_prompt
    await page.goto((FIXTURES / "mock_code.html").resolve().as_uri())
    assert await security_code_prompt(page) == ""          # nothing asked yet
    await page.click("#submit")
    msg = await security_code_prompt(page)
    assert "verification code was sent" in msg
    assert await enter_security_code(page, "AB12 CD34")
    await page.click("#submit")
    assert await page_confirms_submission(page)


async def test_live_tab_code_flow(page):
    runner.live_set("j1", page, phase="review")
    await page.goto((FIXTURES / "mock_code.html").resolve().as_uri())
    assert (await runner.live_submit("j1"))["ok"]
    from jobsmith.fill.base import security_code_prompt
    assert await security_code_prompt(page)
    res = await runner.live_code("j1", "AB12CD34")
    assert res["ok"] and res["submitted"]
    from jobsmith.fill.base import page_confirms_submission
    assert await page_confirms_submission(page)
    assert await runner.live_shot("j1")                     # peek works
    runner.live_drop("j1")


async def test_second_pass_fills_employment_section_the_api_missed(page):
    """Greenhouse's newer forms add an Employment section the job-board API doesn't list."""
    from jobsmith.fill.sweep import sweep
    profile.save_entry("experience", {"title": "Data Engineer Intern", "company": "Rooms To Go", "start": "2025-05",
                                      "end": "Aug 2025", "location": "Atlanta, GA"})
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/777", "Acme", "Intern")
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    await page.set_content("""<form><h3>Employment</h3>
      <label for="co">Company name*</label><input id="co">
      <label for="ti">Title*</label><input id="ti">
      <label for="sm">Start date month*</label><select id="sm"><option></option><option>April</option><option>May</option></select>
      <label for="sy">Start date year*</label><input id="sy">
      <h3>Education</h3><label for="ey">End date year*</label><input id="ey"></form>""")
    profile.set_answer("graduation_date", "May 2027", True)
    r = await sweep(page, job)
    vals = await page.evaluate("() => Object.fromEntries([...document.querySelectorAll('input,select')].map(e => [e.id, e.value]))")
    assert vals["co"] == "Rooms To Go" and vals["ti"] == "Data Engineer Intern"
    assert vals["sm"] == "May" and vals["sy"] == "2025"
    assert vals["ey"] == "2027"                     # same label, Education section: your graduation
    assert not r["failed"]
