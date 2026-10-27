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
