"""Fill local application forms in a real (headless) browser."""
import json
import os
import shutil
from pathlib import Path

import pytest

from jobsmith import db, draft, jobdetail, profile, runner, sources
from jobsmith.fill import base, generic, greenhouse
from jobsmith.fill.base import page_confirms_submission, scan_form
from conftest import FIXTURES

def _browser_available():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        executable = os.environ.get("JOBSMITH_CHROMIUM_PATH") or pw.chromium.executable_path
    return Path(executable).exists() or shutil.which("chromium") is not None or Path("/opt/pw-browsers").exists()


pytestmark = pytest.mark.skipif(not _browser_available(), reason="no browser available")


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
        b = await pw.chromium.launch(headless=True, args=base.browser_args(), **({"executable_path": exe} if exe else {}))
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


async def test_lever_generic_fill_stops_before_submit(tmp_path, page):
    await profile.ingest_document(FIXTURES / "sample_resume.tex")
    answers = {k: v["value"] for k, v in profile.answers().items()}
    values = {
        '[name="name"]': f"{answers['first_name']} {answers['last_name']}",
        '[name="email"]': answers["email"],
        '[name="phone"]': answers["phone"],
        "#location-input": answers["location"],
        '[name="org"]': "Northwind Labs",
        '[name="urls[LinkedIn]"]': answers["linkedin"],
        '[name="urls[GitHub]"]': answers["github"],
        '[name="urls[Other]"]': "https://example.com/alex-rivera",
        '[name="cards[demo-question-1][field0]"]': "5000 USD net per month",
        '[name="cards[demo-question-2][field0]"]': "C2: Proficiency / Native",
        '[name="cards[demo-question-3][field0]"]': "I enjoy building useful software and solving engineering problems.",
    }
    url = (FIXTURES / "lever_form.html").resolve().as_uri()
    fields = await generic.scan(page, url)
    assert {f["field"] for f in fields} == set(values) | {"#resume-upload-input"}
    assert {f["qtype"] for f in fields} == {"text", "textarea", "radio", "file"}
    assert all(not f["value"] for f in fields)
    drafts = [dict(f, value=values.get(f["field"], "")) for f in fields]
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n%%EOF\n")

    result = await generic.fill(page, drafts, {"resume": str(resume)})

    assert not result["failed"], result
    assert len(result["filled"]) == len(fields)
    for selector, expected in values.items():
        if "demo-question-2" in selector:
            assert await page.locator(selector + ":checked").input_value() == expected
        else:
            assert await page.input_value(selector) == expected
    assert await page.input_value('[name="name"]') == "Alex Rivera"
    assert await page.input_value('[name="email"]') == "alex.rivera@example.edu"
    assert await page.locator("#resume-upload-input").evaluate("el => [...el.files].map(f => f.name)") == ["resume.pdf"]
    assert await page.locator("#btn-submit").is_visible()
    assert await page.evaluate("[window.submitClicks, window.submitEvents]") == [0, 0]
    assert page.url == url
    assert not await page_confirms_submission(page)


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
    from jobsmith import guardrails
    assert not guardrails._submitting           # counted as sent now, not in flight
    assert [r["status"] for r in runs if r["kind"] == "submit"] == ["done"]     # confirmed, not "unconfirmed"


async def test_runner_holds_at_the_daily_cap(fake_llm, tmp_path, monkeypatch):
    async def no_watch(*a):         # a held tab is watched for 45 minutes while you finish it; not in a test
        return None
    monkeypatch.setattr(runner, "watch_tab", no_watch)
    jid, _ = await _job_with_drafts(fake_llm, tmp_path)
    db.set_settings({"browser_channel": "", "headless": True, "autonomy": "autonomous", "trust_threshold": 0,
                     "max_applications_per_day": 1})
    runner.mark_submitted(sources.add_job_url("https://job-boards.greenhouse.io/other/jobs/1", "Other", "Intern"))
    for d in draft.drafts_for(jid):
        db.x("UPDATE drafts SET verdict='green' WHERE id=?", (d["id"],))
    try:
        await runner.fill(jid, submit=True)
    finally:
        await runner.browser.close()
    job = db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (jid,))
    assert job["status"] == "filled"                  # filled, waiting for you, not sent
    assert job["hold_reason"].startswith("Daily cap reached: 1 of 1 sent today")


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


async def test_generic_fills_ashby_style_form_stops_before_submit(page, tmp_path):
    """The generic filler (fill/generic.py) handles a hand-written Ashby-style form: scan the fields,
    fill them from the made-up demo profile, and stop before Submit. Sponsorship is left for the
    user (confirmed profile only), so the filler is never handed an answer for it."""
    from jobsmith.fill import generic
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n%%EOF\n")
    await page.goto((FIXTURES / "ashby_style_form.html").resolve().as_uri())

    fields = {f["label"]: f for f in await scan_form(page)}
    # the demo profile's answers, keyed by the label the form shows
    answers = {
        "Name": "Alex Rivera",
        "Email": "alex.rivera@example.edu",
        "LinkedIn Profile": "https://www.linkedin.com/in/alexrivera",
        "GitHub Profile": "https://github.com/alexrivera",
        "Why do you want to work here?": "I built perception systems on NVIDIA Jetson and want to keep shipping them.",
        "How did you hear about us?": "LinkedIn",
    }
    drafts = []
    for label, value in answers.items():
        f = fields[label]
        drafts.append({**f, "value": value})
    drafts.append({**fields["Resume"], "value": ""})            # file comes from the files map

    res = await generic.fill(page, drafts, {"resume": str(resume)})
    assert not res["failed"], res

    assert await page.input_value("#_systemfield_name") == "Alex Rivera"
    assert await page.input_value("#_systemfield_email") == "alex.rivera@example.edu"
    assert await page.input_value("#field-linkedin") == "https://www.linkedin.com/in/alexrivera"
    assert "Jetson" in await page.input_value("#field-why")
    assert await page.input_value("#field-heard") == "LinkedIn"
    assert await page.evaluate("document.querySelector('#_systemfield_resume').files.length") == 1
    assert await page.input_value("#field-sponsorship") == ""      # left for the user
    # counted directly: the blank required sponsorship field alone would block a submit
    assert await page.evaluate("[window.submitClicks, window.submitEvents]") == [0, 0]
    assert not await page_confirms_submission(page)                # nothing submitted


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


async def test_a_fill_stopped_while_submitting_still_counts(fake_llm, tmp_path, monkeypatch):
    import asyncio
    from jobsmith import guardrails
    jid, _ = await _job_with_drafts(fake_llm, tmp_path)
    db.set_settings({"browser_channel": "", "headless": True, "autonomy": "autonomous", "trust_threshold": 0})
    for d in draft.drafts_for(jid):
        db.x("UPDATE drafts SET verdict='green' WHERE id=?", (d["id"],))
    real_claim = guardrails.claim

    def claim_then_stop(j):          # autopilot is switched off the moment it claims the slot
        real_claim(j)
        raise asyncio.CancelledError
    monkeypatch.setattr(guardrails, "claim", claim_then_stop)
    try:
        with pytest.raises(asyncio.CancelledError):
            await runner.fill(jid, submit=True)
    finally:
        await runner.browser.close()
    assert jid not in guardrails._submitting
    # It may have gone through, so it still counts, on disk, and says so.
    assert db.q1("SELECT status FROM runs WHERE job_id=? AND kind='submit'", (jid,))["status"] == "unconfirmed"
    assert guardrails.sent_today() == 1
    assert "never saw a confirmation page" in db.q1("SELECT hold_reason FROM jobs WHERE id=?", (jid,))["hold_reason"]


async def _green_job(fake_llm, tmp_path, monkeypatch):
    async def no_watch(*a):
        return None
    monkeypatch.setattr(runner, "watch_tab", no_watch)
    jid, _ = await _job_with_drafts(fake_llm, tmp_path)
    db.set_settings({"browser_channel": "", "headless": True, "autonomy": "autonomous", "trust_threshold": 0})
    for d in draft.drafts_for(jid):
        db.x("UPDATE drafts SET verdict='green' WHERE id=?", (d["id"],))
    return jid


async def test_an_error_after_clicking_submit_says_it_may_have_been_sent(fake_llm, tmp_path, monkeypatch):
    jid = await _green_job(fake_llm, tmp_path, monkeypatch)

    async def broken(page):
        raise RuntimeError("page went away")
    monkeypatch.setattr(base, "captcha_visible", broken)
    try:
        await runner.fill(jid, submit=True)
    finally:
        await runner.browser.close()
    job = db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (jid,))
    assert job["status"] == "filled"                                # Needs you, not "error, try again"
    assert "never saw a confirmation page" in job["hold_reason"]


async def test_no_submit_button_means_no_submission_counted(fake_llm, tmp_path, monkeypatch):
    from jobsmith import guardrails
    jid = await _green_job(fake_llm, tmp_path, monkeypatch)
    monkeypatch.setattr(base, "SUBMIT_SELECTORS", ["#no-such-button"])
    try:
        await runner.fill(jid, submit=True)
    finally:
        await runner.browser.close()
    assert db.q1("SELECT hold_reason FROM jobs WHERE id=?", (jid,))["hold_reason"] == "couldn't find the Submit button"
    assert guardrails.sent_today() == 0 and not guardrails._submitting
    assert runner.LIVE[jid]["phase"] == "review"       # waiting for you, so the off switch leaves its tab open


async def test_runner_holds_when_the_employer_asks_for_no_ai(fake_llm, tmp_path, monkeypatch):
    jid = await _green_job(fake_llm, tmp_path, monkeypatch)
    db.x("UPDATE jobs SET description=? WHERE id=?",
         ("<p>Jetson work.</p><p>Please do not use AI tools to write your answers.</p>", jid))
    try:
        await runner.fill(jid, submit=True)
    finally:
        await runner.browser.close()
    job = db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (jid,))
    assert job["status"] == "filled"
    assert job["hold_reason"].startswith('Acme Robotics asks applicants not to use AI or automated tools: '
                                         '"Please do not use AI tools to write your answers."')
    assert not db.q("SELECT 1 FROM runs WHERE job_id=? AND kind='submit'", (jid,))


async def test_multistep_shows_every_page_to_the_policy_check_before_submit(fake_llm, tmp_path, page):
    from jobsmith.fill import multistep
    await profile.ingest_document(FIXTURES / "sample_resume.tex")
    profile.set_answer("how_heard", "LinkedIn")
    jid = sources.add_job_url("https://acme.wd1.myworkdayjobs.com/x/job/2", "Acme", "Hardware Intern")
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    jetson = [f["id"] for f in profile.facts() if "Jetson" in f["text"]]
    fake_llm(lambda s, p: {"answers": [{"field": "#why", "answer": "I deployed a detection model on NVIDIA Jetson Nano.",
                                        "fact_ids": jetson, "confidence": 0.9}] if "#why" in p.split("QUESTIONS TO ANSWER:")[1] else []})

    async def answer(fields):
        results, _ = await draft.answer_fields(job, fields)
        return {k: v.get("answer", "") for k, v in results.items()}

    async def wait_for_user(msg, check, negate=False):
        await page.fill("#em", "alex@example.edu")
        await page.click("#signin")
        return not await check() if negate else await check()

    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    seen, asked_with = [], []
    url = (FIXTURES / "mock_multistep.html").resolve().as_uri()
    res = await multistep.run(page, url, answer=answer, files={"resume": str(pdf)}, log=lambda m: None,
                              wait_for_user=wait_for_user, on_page=seen.append,
                              allow_submit=lambda: asked_with.append("\n".join(seen)) or False)
    assert res["status"] == "review", res
    assert asked_with and "My Information" in asked_with[-1] and "Review" in asked_with[-1]
