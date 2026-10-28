"""Phase 1 guardrails: caps, employer AI policies, the audit trail and the fit gate."""
import time

from jobsmith import config, db, guardrails, runner, scheduler, sources


def _job(company: str, n: int) -> str:
    return sources.add_job_url(f"https://job-boards.greenhouse.io/{company.lower()}/jobs/{n}", company, f"Role {n}")


def _sent(company: str, n: int, ago: float = 0) -> str:
    jid = _job(company, n)
    runner.mark_submitted(jid)
    if ago:
        db.x("UPDATE runs SET finished_at=? WHERE job_id=? AND kind='submit'", (time.time() - ago, jid))
    return jid


def test_default_caps_are_20_a_day_and_3_per_company_a_week():
    assert config.DEFAULT_SETTINGS["max_applications_per_day"] == 20
    assert config.DEFAULT_SETTINGS["max_applications_per_company"] == 3
    assert guardrails.summary() == {"sent_today": 0, "daily_cap": 20, "company_cap": 3, "remaining_today": 20}


def test_daily_cap_stops_autopilot_and_says_so():
    db.set_settings({"max_applications_per_day": 2, "max_applications_per_company": 0})
    _sent("Acme", 1)
    nxt = _job("Beta", 9)
    assert guardrails.cap_reason({"id": nxt, "company": "Beta"}) is None
    _sent("Beta", 2)
    why = guardrails.cap_reason({"id": nxt, "company": "Beta"})
    assert why.startswith("Daily cap reached: 2 of 2 sent today")
    assert guardrails.summary()["sent_today"] == 2 and guardrails.remaining_today() == 0


def test_yesterdays_submissions_dont_count_toward_today():
    db.set_settings({"max_applications_per_day": 1})
    _sent("Acme", 1, ago=time.time() - guardrails._midnight() + 60)     # a minute before midnight
    assert guardrails.sent_today() == 0
    assert guardrails.cap_reason({"id": "x", "company": "Beta"}) is None


def test_company_cap_is_per_week_and_ignores_case():
    db.set_settings({"max_applications_per_day": 0, "max_applications_per_company": 2})
    _sent("Acme", 1, ago=8 * 86400)                   # over a week ago: doesn't count
    _sent("Acme", 2)
    nxt = _job("ACME ", 3)
    assert guardrails.cap_reason({"id": nxt, "company": "ACME "}) is None
    _sent("acme", 4)
    why = guardrails.cap_reason({"id": nxt, "company": "ACME "})
    assert why.startswith("Company cap reached: 2 of 2 sent to ACME this week")
    assert guardrails.cap_reason({"id": "y", "company": "Other"}) is None


def test_submissions_in_flight_count_so_parallel_tabs_cant_pass_the_cap():
    db.set_settings({"max_applications_per_day": 2, "max_applications_per_company": 0})
    a, b, c = _job("A", 1), _job("B", 2), _job("C", 3)
    guardrails.claim(a)
    guardrails.claim(b)
    try:
        assert guardrails.cap_reason({"id": c, "company": "C"}).startswith("Daily cap reached: 2 of 2")
        assert guardrails.cap_reason({"id": a, "company": "A"}) is None      # its own claim isn't counted
        assert guardrails.release(a) is True and guardrails.release(a) is False
        assert guardrails.cap_reason({"id": c, "company": "C"}) is None
    finally:
        guardrails.release(b)


def test_caps_survive_a_restart(tmp_path):
    db.set_settings({"max_applications_per_day": 1})
    _sent("Acme", 1)
    db._conn = None                  # a new engine process reads the same database
    assert guardrails.cap_reason({"id": "x", "company": "Beta"}).startswith("Daily cap reached: 1 of 1")


def test_zero_means_no_limit():
    db.set_settings({"max_applications_per_day": 0, "max_applications_per_company": 0})
    for i in range(5):
        _sent("Acme", i)
    assert guardrails.cap_reason({"id": "x", "company": "Acme"}) is None
    assert guardrails.remaining_today() > 1000


def test_scheduler_skips_companies_at_their_weekly_cap():
    db.set_settings({"max_applications_per_company": 1, "max_applications_per_day": 0})
    _sent("Acme", 1)
    _sent("Beta", 2, ago=8 * 86400)
    ids = {}
    for co, n in (("Acme", 10), ("Beta", 11)):
        ids[co] = _job(co, n)
        db.x("UPDATE jobs SET fit_score=90 WHERE id=?", (ids[co],))
    assert scheduler.pick_new_jobs(5) == [ids["Beta"]]


async def test_autopilot_leaves_capped_jobs_for_later_but_your_pick_still_fills(monkeypatch):
    db.set_settings({"max_applications_per_day": 1, "autonomy": "autopilot"})
    _sent("Acme", 1)
    jid = _job("Beta", 2)
    db.x("UPDATE jobs SET fit_score=90 WHERE id=?", (jid,))   # clears the fit gate: only the cap stops it
    prepared = []

    async def fake_prepare(j, research=None):
        prepared.append(j)
    monkeypatch.setattr(runner, "prepare", fake_prepare)
    await runner.autopilot([jid])
    row = db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (jid,))
    assert prepared == [] and row["status"] == "new" and "bar" not in (row["hold_reason"] or "")
    await runner.autopilot([jid], force=True)       # you picked it: filled, then held at Submit with the reason
    assert prepared == [jid]


def test_scheduler_counts_a_submission_in_flight_once_and_ignores_held_ones(monkeypatch):
    db.set_settings({"max_applications_per_company": 2, "max_applications_per_day": 0})
    sending, held, nxt = _job("Acme", 1), _job("Acme", 2), _job("Acme", 3)
    db.x("UPDATE jobs SET status='filling' WHERE id=?", (sending,))
    db.x("UPDATE jobs SET status='filled' WHERE id=?", (held,))       # waiting for you, its tab long closed
    db.x("UPDATE jobs SET fit_score=90 WHERE id=?", (nxt,))
    monkeypatch.setattr(runner, "active", lambda: {sending: "filling"})
    guardrails.claim(sending)
    try:
        assert scheduler.pick_new_jobs(5) == [nxt]                    # 1 in flight of 2: room for one more
    finally:
        guardrails.release(sending)



def test_a_job_already_being_worked_on_isnt_picked_or_counted_twice(monkeypatch):
    db.set_settings({"max_applications_per_company": 2, "max_applications_per_day": 0})
    drafting, other = _job("Acme", 1), _job("Acme", 2)
    db.x("UPDATE jobs SET fit_score=90 WHERE id IN (?,?)", (drafting, other))
    monkeypatch.setattr(runner, "active", lambda: {drafting: "drafting"})
    assert scheduler.pick_new_jobs(5) == [other]


def test_an_unconfirmed_submit_counts_but_a_confirmed_one_counts_once():
    db.set_settings({"max_applications_per_day": 5})
    a, b = _job("A", 1), _job("B", 2)
    guardrails.claim(a)
    runner.mark_submitted(a)                     # confirmed: released, counted once
    guardrails.claim(b)
    guardrails.abandon(b, "the tab closed")
    assert not guardrails._submitting
    assert guardrails.sent_today() == 2
    guardrails.abandon(a, "late")                # not claimed any more: nothing recorded
    assert db.q1("SELECT COUNT(*) n FROM runs WHERE kind='submit'")["n"] == 2


async def test_a_maybe_sent_application_is_never_sent_again(monkeypatch):
    import asyncio
    jid = _job("Acme", 1)
    db.x("UPDATE jobs SET status='filling', fit_score=90 WHERE id=?", (jid,))
    guardrails.claim(jid)
    assert guardrails.abandon(jid, "stopped while submitting") is True
    assert db.q1("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "filled"     # waits under Needs you
    assert guardrails.cap_reason({"id": jid, "company": "Acme"}).startswith("Autopilot may already have sent this")
    # Even if something resets it to drafted, the scheduler won't pick it again...
    db.x("UPDATE jobs SET status='drafted' WHERE id=?", (jid,))
    assert jid not in scheduler.pick_new_jobs(5)
    # ...and the off switch doesn't wipe the warning.
    db.x("UPDATE jobs SET status='filling', hold_reason='kept' WHERE id=?", (jid,))
    runner.spawn(jid, "autopilot", asyncio.sleep(30))
    await asyncio.sleep(0)
    await runner.stop()
    assert db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (jid,)) == {"status": "filling", "hold_reason": "kept"}


POLICY = [
    "Please do not use AI tools such as ChatGPT to write your answers.",
    "We kindly ask that you refrain from using generative AI when completing this application.",
    "The use of AI or automated tools in this application is strictly prohibited.",
    "AI-generated responses will be rejected.",
    "Applications submitted by bots or automated tools will not be considered.",
    "Answers must not be generated by AI.",
    "I confirm that I did not use AI to write my answers.",
    "Candidates may not use artificial intelligence during the assessment.",
    "No AI-generated applications, please.",
    "Please complete this application without the assistance of AI.",
    "Do not use auto-apply tools.",
]
NOT_POLICY = [
    "Experience with generative AI tools such as ChatGPT or Claude is a plus.",
    "You will build AI systems that do not hallucinate.",
    "We use AI to help our recruiters, but every application is read by a person.",
    "Do not worry if you do not meet every requirement.",
    "Our automation platform helps teams ship faster; you must not be afraid of ambiguity.",
    "Familiarity with LLMs, prompt engineering, and AI safety.",
    "Build automated testing systems and CI pipelines.",
    "Do not apply if you need sponsorship.",
    "We do not use AI to evaluate applications.",
    "Our recruiters never use AI to screen resumes.",
    "Our employees do not use AI to screen applications.",
]


def test_ai_policy_sentences_are_found_and_ai_jobs_are_not_mistaken_for_them():
    for s in POLICY:
        assert guardrails.ai_policy(f"About the role. {s} We look forward to hearing from you.") == s, s
    for s in NOT_POLICY:
        assert guardrails.ai_policy(s) is None, s


def test_ai_policy_reads_html_and_saved_real_postings_dont_trip_it():
    from conftest import FIXTURES
    assert guardrails.ai_policy("<p>Thanks!</p><p><strong>Please don&rsquo;t use AI</strong> to answer.</p>") == \
        "Please don’t use AI to answer."
    for f in FIXTURES.iterdir():
        if f.suffix in (".html", ".json"):
            assert guardrails.ai_policy(f.read_text(errors="ignore")) is None, f.name


def test_policy_reason_reads_the_posting_the_questions_and_the_page():
    job = {"company": "Acme ", "description": "<p>Build robots.</p>", "questions": []}
    assert guardrails.policy_reason(job) is None
    job["questions"] = [{"label": "Certification", "description": "I did not use AI to write my answers."}]
    why = guardrails.policy_reason(job)
    assert why.startswith('Acme asks applicants not to use AI or automated tools: "I did not use AI to write my '
                          'answers." Autopilot won\'t send it.')
    assert guardrails.policy_reason({"company": "Beta", "questions": "[]"},
                                    page_text="Submit\nAI-generated responses will be rejected.\nApply")
    # A <br> inside a sentence on the page shows up as a line break in the page's text.
    assert 'Please do not use AI tools to write your answers."' in guardrails.policy_reason(
        {"company": "Beta"}, page_text="Questions\nPlease do not use\nAI tools to write your answers.\nSubmit")


def test_wrapped_lines_and_html_blocks_dont_hide_a_policy():
    assert guardrails.ai_policy("Please do not use\nAI tools to write your answers.") == \
        "Please do not use AI tools to write your answers."
    assert guardrails.ai_policy("AI-generated responses\nwill be rejected.") == "AI-generated responses will be rejected."
    assert guardrails.ai_policy("<p>Note</p><p>Please do not use AI.</p>") == "Please do not use AI."
    for br in ("<br>", "<br/>", "<br />"):
        assert guardrails.ai_policy(f"Please do not use{br}AI tools to write your answers.") == \
            "Please do not use AI tools to write your answers."


def test_rules_for_applicants_count_even_when_they_start_with_our():
    for s in ("Our applicants must not use AI to write their answers.",
              "Our candidates should not use ChatGPT.", "They must not use AI tools.",
              "Candidates must not use AI to write answers; we do not use AI to screen applications.",
              "You must not use AI to review applications.",
              "To review applications fairly, candidates must not use AI to write their answers.",
              "Our recruiters read every application, and candidates must not use AI to write answers.",
              "We must not receive AI-generated answers, so do not use AI."):
        assert guardrails.ai_policy(s) == s, s


async def test_multipage_autopilot_holds_for_a_policy_seen_on_a_middle_page(monkeypatch):
    from jobsmith.fill import multistep
    jid = sources.add_job_url("https://acme.wd1.myworkdayjobs.com/x/job/1", "Acme", "Hardware Intern")

    class Page:
        async def screenshot(self, **kw):
            raise RuntimeError("no screen in tests")

        def is_closed(self):
            return False

    class Browser:
        def want_headless(self):
            return True

        async def new_page(self):
            return Page()

    async def fake_run(page, url, *, answer, files, log, wait_for_user, allow_submit, on_page=None, **kw):
        on_page("My Information\nFirst name")
        on_page("Questions\nPlease do not use AI tools to write your answers.\nWhy Acme?")
        on_page("Review\nSubmit")
        return {"status": "submitted_clicked" if allow_submit() else "review", "filled": 3, "issues": []}

    async def no_watch(*a):
        return None
    monkeypatch.setattr(multistep, "run", fake_run)
    monkeypatch.setattr(runner, "browser", Browser())
    monkeypatch.setattr(runner, "takeover", Browser())
    monkeypatch.setattr(runner, "watch_tab", no_watch)
    try:
        await runner.fill_multistep(jid, submit=True)
    finally:
        runner.live_drop(jid)          # the fake tab mustn't linger for other tests
    job = db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (jid,))
    assert job["status"] == "filled"
    assert job["hold_reason"].startswith('Acme asks applicants not to use AI or automated tools: "Please do not use '
                                         'AI tools to write your answers."')
    assert not db.q("SELECT 1 FROM runs WHERE job_id=? AND kind='submit'", (jid,))
    assert not guardrails._submitting


def test_an_unclear_they_holds():
    for s in ("Applicants must certify that they did not use AI to write their answers.",
              "Candidates are eligible only if they do not use AI to complete this application.",
              "They do not use AI to evaluate applications."):      # unclear who: held, one click for you
        assert guardrails.ai_policy(s) == s, s


def test_fit_gate_says_why_a_match_passes_or_not():
    db.set_settings({"min_fit_score": 40})
    ok = guardrails.fit_gate({"fit_score": 62, "fit_reasons": '["+ season match", "+ skills: python", "- location"]'})
    assert ok["passed"] and ok["summary"] == "Fit 62 clears your bar of 40: autopilot applies."
    assert ok["for"] == ["season match", "skills: python"] and ok["against"] == ["location"]
    edge = guardrails.fit_gate({"fit_score": 40, "fit_reasons": []})
    assert edge["passed"]                                            # at the bar counts
    low = guardrails.fit_gate({"fit_score": 39.6, "fit_reasons": ["- older than 60 days"]})
    assert not low["passed"] and low["summary"].startswith("Fit 39 is under your bar of 40")
    assert not guardrails.fit_gate({"fit_score": None})["passed"]


async def test_autopilot_only_applies_at_or_above_the_bar_unless_you_picked_it(monkeypatch):
    db.set_settings({"min_fit_score": 50, "max_applications_per_day": 0})
    low, high = _job("Low", 1), _job("High", 2)
    db.x("UPDATE jobs SET fit_score=30 WHERE id=?", (low,))
    db.x("UPDATE jobs SET fit_score=70 WHERE id=?", (high,))
    prepared = []

    async def fake_prepare(j, research=None):
        prepared.append(j)
    monkeypatch.setattr(runner, "prepare", fake_prepare)
    await runner.autopilot([low, high])
    assert prepared == [high]
    assert db.q1("SELECT hold_reason FROM jobs WHERE id=?", (low,))["hold_reason"].startswith("Fit 30 is under your bar of 50")
    await runner.autopilot([low], force=True)
    assert prepared == [high, low]


def test_every_match_carries_its_gate():
    from fastapi.testclient import TestClient
    from jobsmith.api import app
    db.set_settings({"min_fit_score": 50})
    jid = _job("Acme", 1)
    db.x("UPDATE jobs SET fit_score=30, fit_reasons='[\"- location\"]' WHERE id=?", (jid,))
    c = TestClient(app)
    [row] = c.get("/api/jobs?min_score=0").json()["jobs"]
    assert row["gate"]["passed"] is False and row["gate"]["against"] == ["location"]
    assert c.get(f"/api/jobs/{jid}").json()["gate"]["summary"].startswith("Fit 30 is under your bar of 50")


# --------------------------------------------------------------------------- supervised first runs
def test_first_submission_and_first_on_each_site_need_your_approval():
    gh, lever = _job("Acme", 1), sources.add_job_url("https://jobs.lever.co/beta/1", "Beta", "Role")
    other = sources.add_job_url("https://careers.example.com/jobs/7", "Gamma", "Role")
    row = lambda j: db.q1("SELECT * FROM jobs WHERE id=?", (j,))
    assert [guardrails.site_of(row(j)) for j in (gh, lever, other)] == ["greenhouse", "lever", "careers.example.com"]
    assert guardrails.first_run_reason(row(gh)).startswith("This is autopilot's first submission: check every answer")
    guardrails.ask_approval(gh, "greenhouse")
    db.x("UPDATE jobs SET status='filled' WHERE id=?", (gh,))
    assert [a["job_id"] for a in guardrails.awaiting_approval()] == [gh]
    assert guardrails.first_run_reason(row(gh)) is not None          # asking isn't approving
    assert guardrails.approve(gh) == "greenhouse" and guardrails.approve(gh) is None
    assert guardrails.awaiting_approval() == []
    assert guardrails.first_run_reason(row(_job("Delta", 2))) is None   # any Greenhouse job now
    assert guardrails.first_run_reason(row(lever)) == (
        "This is autopilot's first submission on Lever: check every answer and where it came from, then approve it "
        "to send it. After that, autopilot submits on Lever on its own within your limits.")
    assert "on careers.example.com" in guardrails.first_run_reason(row(other))


def test_your_own_submission_doesnt_count_as_approving_autopilot():
    _sent("Acme", 1)                                   # you sent one yourself: autopilot still asks the first time
    assert guardrails.first_run_reason({"url": "https://job-boards.greenhouse.io/acme/jobs/2"}) is not None


def test_approve_endpoint_only_acts_on_an_application_waiting_for_it():
    from fastapi.testclient import TestClient
    from jobsmith.api import app
    c = TestClient(app)
    jid = _job("Acme", 1)
    assert c.post(f"/api/jobs/{jid}/approve").json() == {"ok": False, "message": "Nothing here is waiting for your approval."}
    assert c.get(f"/api/jobs/{jid}").json()["approval"] is None
    guardrails.ask_approval(jid, "greenhouse")
    db.x("UPDATE jobs SET status='filled' WHERE id=?", (jid,))
    got = c.get(f"/api/jobs/{jid}").json()["approval"]
    assert got["site_name"] == "Greenhouse" and got["answers"] is None      # nothing was filled in this test
    assert [r["approve"] for r in c.get("/api/home").json()["review"] if r["id"] == jid] == [True]


async def test_multipage_autopilot_waits_for_approval_at_the_review_page(monkeypatch):
    from jobsmith.fill import multistep
    jid = sources.add_job_url("https://acme.wd1.myworkdayjobs.com/x/job/1", "Acme", "Hardware Intern")

    class Page:
        async def screenshot(self, **kw):
            raise RuntimeError("no screen in tests")

        def is_closed(self):
            return False

    class Browser:
        def want_headless(self):
            return True

        async def new_page(self):
            return Page()
    allowed = []

    async def fake_run(page, url, *, answer, files, log, wait_for_user, allow_submit, on_page=None, **kw):
        on_page("Review\nSubmit")
        allowed.append(allow_submit())
        return {"status": "review", "filled": 3, "issues": []}

    async def no_watch(*a):
        return None
    monkeypatch.setattr(multistep, "run", fake_run)
    monkeypatch.setattr(runner, "browser", Browser())
    monkeypatch.setattr(runner, "takeover", Browser())
    monkeypatch.setattr(runner, "watch_tab", no_watch)
    try:
        await runner.fill_multistep(jid, submit=True)
        assert allowed == [False]
        job = db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (jid,))
        assert job["status"] == "filled" and job["hold_reason"].startswith("This is autopilot's first submission")
        assert [a["site"] for a in guardrails.awaiting_approval(jid)] == ["workday"]
        assert not guardrails._submitting
        guardrails.approve(jid)                           # approved once: the next one goes through on its own
        await runner.fill_multistep(jid, submit=True)
        assert allowed == [False, True] and jid in guardrails._submitting
    finally:
        guardrails._submitting.discard(jid)
        runner.live_drop(jid)


def _filled(answer: str) -> str:
    """What Jobsmith filled in a form, as the audit trail keeps it."""
    import json
    return json.dumps([{"field": "first_name", "label": "First Name", "qtype": "text", "answer": answer,
                        "source": "profile", "detail": [{"ref": "Profile: First name", "text": answer}],
                        "traces": True, "approved": True, "kind_check": "ok", "issues": []}])


def _waiting_for_approval(answer: str = "Alex") -> str:
    from jobsmith import audit
    jid = _job("Acme", 1)
    audit._ensure()
    db.x("INSERT OR REPLACE INTO audit_pending(job_id, fields, at) VALUES(?,?,?)", (jid, _filled(answer), db.now()))
    guardrails.ask_approval(jid, "greenhouse")
    db.x("UPDATE jobs SET status='filled' WHERE id=?", (jid,))
    return jid


async def test_approving_after_the_tab_closed_sends_only_the_answers_you_checked(monkeypatch):
    spawned = []

    def fake_spawn(jid, label, coro):
        coro.close()
        spawned.append(jid)
        return True
    monkeypatch.setattr(runner, "spawn", fake_spawn)
    jid = _waiting_for_approval("Alex")
    r = await runner.approve(jid)
    assert r["ok"] and spawned == [jid] and "if the answers come out the same" in r["message"]
    job = db.q1("SELECT * FROM jobs WHERE id=?", (jid,))
    assert guardrails.first_run_reason(job) is not None                 # not trusted until it's actually sent
    run = runner.Run(jid, "fill")
    assert runner._first_run_hold(job, run) is None                     # the refill matches: it may go
    assert runner._approved.pop(jid) == "greenhouse"
    assert guardrails.first_run_reason(job) is not None                 # trusted only once Submit is clicked

    other = _job("Beta", 2)                                              # same, but the refill comes out different
    db.x("UPDATE first_runs SET approved_at=NULL")
    db.x("INSERT OR REPLACE INTO audit_pending(job_id, fields, at) VALUES(?,?,?)", (other, _filled("Alex"), db.now()))
    guardrails.ask_approval(other, "greenhouse")
    db.x("UPDATE jobs SET status='filled' WHERE id=?", (other,))
    await runner.approve(other)
    db.x("UPDATE audit_pending SET fields=? WHERE job_id=?", (_filled("Alexander"), other))
    why = runner._first_run_hold(db.q1("SELECT * FROM jobs WHERE id=?", (other,)), runner.Run(other, "fill"))
    assert why.startswith("The form changed after you approved it, so check the answers again. This is autopilot's")
    assert guardrails.awaiting_approval(other) and guardrails.approved_answers(other) is None


async def test_two_approvals_at_once_click_submit_once_and_an_unconfirmed_one_is_kept(monkeypatch):
    import asyncio
    jid = _waiting_for_approval()
    clicks = []

    class Tab:
        def is_closed(self):
            return False

    async def slow_submit(j):
        clicks.append(j)
        await asyncio.sleep(0.2)
        return {"ok": True}
    monkeypatch.setattr(runner, "live_submit", slow_submit)
    monkeypatch.setitem(runner.LIVE, jid, {"page": Tab()})
    try:
        a, b = await asyncio.gather(runner.approve(jid), runner.approve(jid))
        assert clicks == [jid] and sorted([a["ok"], b["ok"]]) == [False, True]
        assert "Already sending it." in (a.get("message"), b.get("message"))
        assert jid in guardrails._submitting                   # counted from the click, like autopilot's own
        # No confirmation page and the tab closes: recorded as possibly sent, never sent again on its own.
        assert guardrails.abandon(jid, "no confirmation page before the tab closed")
        assert guardrails.maybe_sent(jid) and guardrails.sent_today() == 1
    finally:
        guardrails._submitting.discard(jid)
        runner._approved.pop(jid, None)


async def test_an_approval_whose_click_fails_isnt_counted_or_approved(monkeypatch):
    jid = _waiting_for_approval()

    class Tab:
        def is_closed(self):
            return False

    async def no_button(j):
        return {"ok": False, "message": "Couldn't find a Submit button."}
    monkeypatch.setattr(runner, "live_submit", no_button)
    monkeypatch.setitem(runner.LIVE, jid, {"page": Tab()})
    assert (await runner.approve(jid))["ok"] is False
    assert jid not in guardrails._submitting and guardrails.awaiting_approval(jid)


def test_a_resume_replaced_after_the_fill_means_checking_again(tmp_path):
    """Approved after the tab closed: the refill is sent only with the files the held form was filled with."""
    import json
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 first\n%%EOF\n")
    db.x("INSERT INTO documents(kind, filename, path, text, is_primary, created_at) VALUES('resume','resume.pdf',?, '',1,?)",
         (str(pdf), db.now()))
    fields = json.loads(_filled("Alex"))
    same, swapped = _job("Acme", 1), _job("Beta", 2)
    for jid in (same, swapped):
        guardrails.ask_approval(jid, "greenhouse")            # held right after the fill: files fingerprinted then
    guardrails.approve_answers(same, fields)
    assert guardrails.approved_answers(same) == guardrails.answers_key(fields)        # a refill now matches
    pdf.write_bytes(b"%PDF-1.4 a different resume, same name\n%%EOF\n")              # replaced before you approve
    guardrails.approve_answers(swapped, fields)
    assert guardrails.approved_answers(swapped) != guardrails.answers_key(fields)     # the refill would carry B
    assert guardrails.approved_answers(same) != guardrails.answers_key(fields)        # and after approving, too


async def test_a_confirmation_seen_during_the_approved_click_is_yours(monkeypatch):
    from jobsmith import audit
    jid = _waiting_for_approval()

    class Tab:
        def is_closed(self):
            return False

    async def confirms_at_once(j):            # the watcher sees the thank-you page before the click returns
        runner.record_submission(j, "Confirmation page detected.")
        return {"ok": True}
    monkeypatch.setattr(runner, "live_submit", confirms_at_once)
    monkeypatch.setitem(runner.LIVE, jid, {"page": Tab()})
    assert (await runner.approve(jid))["ok"]
    [sub] = audit.for_job(jid)
    assert sub["sent_by"] == "you" and sub["note"].startswith("You approved autopilot's first submission on Greenhouse")
    assert jid not in runner._approved and jid not in guardrails._submitting
    assert guardrails.first_run_reason({"url": "https://job-boards.greenhouse.io/acme/jobs/9"}) is None


def test_a_resume_swapped_while_it_was_filling_means_checking_again():
    """The fingerprint is of the files the fill started with, not whatever the profile holds when it's held."""
    import json
    fields = json.loads(_filled("Alex"))
    jid = _job("Acme", 1)
    guardrails.ask_approval(jid, "greenhouse", ["sha-of-resume-A", ""])   # what the fill attached
    guardrails.approve_answers(jid, fields)
    assert guardrails.approved_answers(jid) == guardrails.answers_key(fields, ["sha-of-resume-A", ""])
    assert guardrails.approved_answers(jid) != guardrails.answers_key(fields, ["sha-of-resume-B", ""])


def test_a_held_approval_with_no_file_record_is_checked_again():
    import json
    fields = json.loads(_filled("Alex"))
    jid = _job("Acme", 1)
    db.x("INSERT INTO first_runs(job_id, site, asked_at) VALUES(?,?,?)", (jid, "greenhouse", db.now()))
    guardrails.approve_answers(jid, fields)
    assert guardrails.approved_answers(jid) != guardrails.answers_key(fields)


def test_after_a_refill_the_site_is_trusted_only_once_it_lands():
    jid, other = _job("Acme", 1), _job("Beta", 2)
    for j in (jid, other):
        guardrails.ask_approval(j, "greenhouse")
        runner._approved[j] = "greenhouse"            # a refill matched the answers you approved
        guardrails.claim(j)
    assert runner._abandon(other, "no confirmation page")          # clicked, never confirmed: not trusted
    assert other not in runner._approved
    assert guardrails.first_run_reason({"url": "https://job-boards.greenhouse.io/x/jobs/3"}) is not None
    runner.record_submission(jid, "Confirmation page detected.")   # confirmed: trusted from now on
    assert guardrails.first_run_reason({"url": "https://job-boards.greenhouse.io/x/jobs/3"}) is None
    assert db.q1("SELECT sent_by FROM audit_submissions WHERE job_id=?", (jid,))["sent_by"] == "you"
