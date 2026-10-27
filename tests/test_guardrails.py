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
    prepared = []

    async def fake_prepare(j, research=None):
        prepared.append(j)
    monkeypatch.setattr(runner, "prepare", fake_prepare)
    await runner.autopilot([jid])
    assert prepared == [] and db.q1("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "new"
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
