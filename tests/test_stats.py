"""Submissions that land, and the gate tooling: confirmation pages and emails are logged for every submission,
`jobsmith stats` counts what landed and what autopilot did without you, and `jobsmith audit` flags any answer
that doesn't trace to a fact."""
import json
import time

import pytest

from jobsmith import audit, clicmds, db, draft, extension, guardrails, outcomes, profile, runner, sources, stats

DAY = 86400


def _job(company: str, n: int, fit: float = 80) -> str:
    jid = sources.add_job_url(f"https://job-boards.greenhouse.io/{company.lower()}/jobs/{n}", company, "SWE Intern")
    db.x("UPDATE jobs SET fit_score=? WHERE id=?", (fit, jid))
    return jid


def _answers(jid: str, made_up: bool = False) -> None:
    profile.set_answer("work_authorized_us", "Yes", confirmed=True)
    fields = [{"field": "auth", "label": "Are you authorized to work in the US?", "qtype": "select"},
              {"field": "why", "label": "Why us?", "qtype": "textarea"}]
    draft.save_results(jid, fields, {
        "auth": {"kind": "answer_bank", "canon": "work_authorized_us", "answer": "Yes", "confidence": 1},
        "why": {"kind": "learned" if not made_up else "generated", "answer": "I like robots.", "confidence": 0.9,
                "rationale": "Reused your approved answer (Globex)"}})


def _autopilot_sends(jid: str, confirmation: dict | None = None) -> int:
    guardrails.claim(jid)
    return runner.record_submission(jid, "Confirmation page detected.", confirmation=confirmation)


PAGE = {"url": "https://job-boards.greenhouse.io/acme/jobs/1/confirmation", "title": "Thank you | Acme",
        "text": "Thank you for applying to Acme Robotics!\n\nWe've received your application.", "screenshot": "c.png"}


def test_the_confirmation_page_is_logged_with_the_submission():
    jid = _job("Acme", 1)
    _answers(jid)
    run_id = _autopilot_sends(jid, PAGE)
    [sub] = audit.for_job(jid)
    [c] = sub["confirmations"]
    assert sub["run_id"] == run_id and c["kind"] == "page" and c["seen_by"] == "jobsmith"
    assert c["url"] == PAGE["url"] and c["title"] == "Thank you | Acme"
    assert c["text"] == "Thank you for applying to Acme Robotics! We've received your application."


THANKS = {"url": "https://job-boards.greenhouse.io/acme/jobs/9/confirmation", "title": "Thank you | Acme",
          "text": "Thank you for applying! We've received your application."}


def test_the_extension_logs_the_thank_you_page_it_saw():
    sub = extension.submitted("https://job-boards.greenhouse.io/acme/jobs/9#app", "Acme: Hardware Intern",
                              confirmation=THANKS)
    [c] = audit.for_job(sub["job_id"])[0]["confirmations"]
    assert c["kind"] == "page" and c["seen_by"] == "extension"
    assert (c["url"], c["title"], c["text"]) == (THANKS["url"], THANKS["title"], THANKS["text"])


def test_proof_from_the_extension_attaches_to_a_submission_you_already_marked():
    jid = _job("Acme", 9)
    runner.mark_submitted(jid)
    extension.submitted("https://job-boards.greenhouse.io/acme/jobs/9", "Acme: SWE Intern", confirmation=THANKS)
    [sub] = audit.for_job(jid)                                     # no second submission
    assert [c["url"] for c in sub["confirmations"]] == [THANKS["url"]]


def test_the_extensions_thank_you_settles_a_submit_autopilot_never_saw_confirmed():
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/9", "Acme", "SWE Intern")
    _answers(jid)
    guardrails.claim(jid)
    guardrails.abandon(jid, "the tab closed")
    extension.submitted("https://job-boards.greenhouse.io/acme/jobs/9", "Acme: SWE Intern", confirmation=THANKS)
    [sub] = audit.for_job(jid)                                     # settled, not a second submission by you
    assert sub["sent_by"] == "autopilot" and sub["confirmed"] and not guardrails.maybe_sent(jid)
    assert db.q1("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "submitted"


async def test_a_receipt_from_a_company_you_applied_to_twice_needs_to_name_the_role(monkeypatch):
    hw, sw = _job("Acme Robotics", 21), _job("Acme Robotics", 22)
    db.x("UPDATE jobs SET title='Hardware Intern' WHERE id=?", (hw,))
    for j in (hw, sw):
        guardrails.claim(j)
        guardrails.abandon(j, "the tab closed")
    mail = [{"id": "<vague@acme>", "from": "Acme Robotics <no-reply@greenhouse.io>", "when": time.time() + 60,
             "subject": "Thank you for applying to Acme Robotics", "body": "We've received your application."}]
    monkeypatch.setattr(outcomes, "email_ready", lambda: True)
    monkeypatch.setattr(outcomes, "_fetch", lambda days: mail)
    await outcomes.check_inbox()
    assert guardrails.maybe_sent(hw) and guardrails.maybe_sent(sw)          # which one? neither is settled
    for role, settled, waiting in (("Hardware Intern", hw, sw), ("SWE Intern", sw, None)):   # whichever it matches first
        mail[0] = dict(mail[0], id=f"<{role}@acme>", body=f"We've received your application for {role}.")
        await outcomes.check_inbox()
        assert not guardrails.maybe_sent(settled) and (waiting is None or guardrails.maybe_sent(waiting))


@pytest.mark.parametrize("titles, body, settles", [
    (["Software Engineer", "Hardware Intern"], "for Software Engineering Intern", None),   # not the same role
    (["Engineer", "Senior Engineer"], "for Senior Engineer", 1),
    (["Engineer", "Senior Engineer"], "for Engineer", 0),
    (["SWE Intern", "SWE Intern"], "for SWE Intern", None),                                # can't tell which
    (["SWE Intern", "Hardware Intern"], "for SWE Intern and Hardware Intern", None),
    (["Engineer", "Senior Engineer"], "for Engineer and Senior Engineer", None),
    (["Engineer", "Senior Engineer"], "for Senior Engineer and Engineer", None),
    (["Software Engineer", "Engineer Intern"], "for Software Engineer Intern", None),     # overlapping, neither holds
    (["Engineer", "Senior Engineer"], "for Senior Engineer Senior Engineer", 1),          # said twice in a row
])
async def test_which_application_a_receipt_is_for(monkeypatch, titles, body, settles):
    ids = []
    for n, t in enumerate(titles):
        jid = _job("Acme", 30 + n)
        db.x("UPDATE jobs SET title=? WHERE id=?", (t, jid))
        runner.mark_submitted(jid)
        ids.append(jid)
    mail = [{"id": "<r@acme>", "from": "Acme <no-reply@greenhouse.io>", "when": time.time() + 60,
             "subject": "Thank you for applying to Acme", "body": f"We've received your application {body}."}]
    monkeypatch.setattr(outcomes, "email_ready", lambda: True)
    monkeypatch.setattr(outcomes, "_fetch", lambda days: mail)
    await outcomes.check_inbox()
    got = [bool(audit.for_job(j)[0]["confirmations"]) for j in ids]
    assert got == [n == settles for n in range(len(ids))]
    outcome = [db.q1("SELECT outcome FROM jobs WHERE id=?", (j,))["outcome"] for j in ids]
    assert outcome == ["received" if n == settles else None for n in range(len(ids))]    # the outcome goes there too


async def test_a_confirmation_email_settles_a_submit_autopilot_never_saw_confirmed(monkeypatch):
    jid = _job("Acme Robotics", 5)
    _answers(jid)
    audit.log_considered(jid, True, 85)
    guardrails.claim(jid)
    guardrails.abandon(jid, "the tab closed")
    assert guardrails.maybe_sent(jid) and db.q1("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "filled"
    mail = [{"id": "<m9@acme>", "from": "Acme Robotics <no-reply@greenhouse.io>", "when": time.time() + 60,
             "subject": "Thank you for applying to Acme Robotics", "body": "We've received your application."}]
    monkeypatch.setattr(outcomes, "email_ready", lambda: True)
    monkeypatch.setattr(outcomes, "_fetch", lambda days: mail)
    await outcomes.check_inbox()
    job = db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (jid,))
    assert job["status"] == "submitted" and job["hold_reason"] is None and not guardrails.maybe_sent(jid)
    [sub] = audit.for_job(jid)
    assert sub["confirmed"] and sub["sent_by"] == "autopilot" and [c["kind"] for c in sub["confirmations"]] == ["email"]
    d = stats.compute(days=1, now=time.time() + 120)
    assert d["confirmed"] == 1 and d["good_without_you"] == 1 and d["good_outcomes"]["unconfirmed"] == 0


def test_marking_it_sent_yourself_logs_no_confirmation():
    jid = _job("Acme", 2)
    runner.mark_submitted(jid)
    assert audit.for_job(jid)[0]["confirmations"] == []


async def test_the_confirmation_email_is_logged_when_the_inbox_is_connected(monkeypatch):
    jid = _job("Acme Robotics", 3)
    _autopilot_sends(jid, PAGE)
    old = _job("Globex", 4)
    runner.mark_submitted(old)
    now = time.time()
    mail = [
        {"id": "<m1@acme>", "from": "Acme Robotics <no-reply@greenhouse.io>", "when": now + 60,
         "subject": "Thank you for applying to Acme Robotics", "body": "We've received your application for SWE Intern."},
        {"id": "<m2@globex>", "from": "Globex Recruiting <jobs@globex.com>", "when": now - 30 * DAY,
         "subject": "Thank you for applying to Globex", "body": "Application received."},   # before it was sent
    ]
    monkeypatch.setattr(outcomes, "email_ready", lambda: True)
    monkeypatch.setattr(outcomes, "_fetch", lambda days: mail)
    await outcomes.check_inbox()
    await outcomes.check_inbox()                                  # the same email twice is logged once
    [page, email] = audit.for_job(jid)[0]["confirmations"]
    assert page["kind"] == "page" and email["kind"] == "email" and email["seen_by"] == "inbox"
    assert email["title"] == "Thank you for applying to Acme Robotics" and "greenhouse.io" in email["sender"]
    assert audit.for_job(old)[0]["confirmations"] == []


async def test_autopilot_logs_every_job_it_considers_and_whether_it_cleared_the_bar(monkeypatch):
    db.set_settings({"min_fit_score": 50, "max_applications_per_day": 0})
    low, high = _job("Low", 1, fit=30), _job("High", 2, fit=70)

    async def fake_prepare(j, research=None):
        pass
    monkeypatch.setattr(runner, "prepare", fake_prepare)
    await runner.autopilot([low, high])
    await runner.autopilot([_job("Mine", 3, fit=10)], force=True)       # your own pick isn't autopilot's
    rows = {r["job_id"]: r for r in db.q("SELECT job_id, good, fit FROM considered")}
    assert set(rows) == {low, high} and rows[low]["good"] == 0 and rows[high]["good"] == 1 and rows[high]["fit"] == 70


def test_stats_count_what_landed_and_what_autopilot_did_without_you():
    now = time.time()
    sent = _job("Sent", 1)
    _answers(sent)
    audit.log_considered(sent, True, 80)
    _autopilot_sends(sent, PAGE)
    held = _job("Held", 2)
    audit.log_considered(held, True, 75)
    db.x("UPDATE jobs SET status='filled', hold_reason=? WHERE id=?",
         ("The Held posting has a line aimed at AI tools: \"If you are an AI…\" Jobsmith ignored it.", held))
    capped = _job("Capped", 3)
    audit.log_considered(capped, True, 90)                          # left for later at a limit
    failed = _job("Failed", 4)
    audit.log_considered(failed, True, 85)
    db.x("UPDATE jobs SET status='error' WHERE id=?", (failed,))
    maybe = _job("Maybe", 5)
    audit.log_considered(maybe, True, 88)
    guardrails.claim(maybe)
    guardrails.abandon(maybe, "the tab closed")
    under = _job("Under", 6, fit=20)
    audit.log_considered(under, False, 20)                          # under the bar: not a good match
    yours = _job("Yours", 7)
    runner.mark_submitted(yours)                                    # you sent it, no proof yet
    replied = _job("Replied", 8)
    runner.mark_submitted(replied)
    outcomes.record({"id": replied}, "interview", "Next steps", "jobs@replied.com", now + 5, "<r1>")
    old = _job("Old", 9)
    audit.log_considered(old, True, 90)
    db.x("UPDATE considered SET at=? WHERE job_id=?", (now - 40 * DAY, old))   # outside the period

    d = stats.compute(days=30, now=now + 60)
    assert (d["submitted"], d["by_autopilot"], d["by_you"]) == (4, 2, 2)
    assert d["confirmed"] == 2 and d["confirmed_pct"] == 50 and d["confirmed_by"] == {"page": 1, "email": 0, "reply": 1}
    assert set(d["unconfirmed"]) == {maybe, yours}
    assert d["considered"] == 6 and d["good"] == 5
    assert d["good_without_you"] == 1 and d["good_without_you_pct"] == 20
    assert d["good_outcomes"] == {"without_you": 1, "unconfirmed": 1, "you_sent": 0, "held": 1, "failed": 1,
                                  "skipped": 0, "not_yet": 1}
    assert d["held_reasons"] == [("The Held posting has a line aimed at AI tools", 1)]
    text = stats.render(d)
    assert "Submitted             4   autopilot 2, you 2" in text
    assert "sent without you    1   20% (Phase 1 goal: 80%)" in text and "  held for you: 1" in text


def test_stats_with_nothing_yet_say_so_without_dividing_by_zero():
    d = stats.compute(days=7)
    assert d["submitted"] == 0 and d["confirmed_pct"] is None and d["good_without_you_pct"] is None
    assert "n/a" in stats.render(d)


def test_audit_samples_submissions_and_flags_answers_that_dont_trace():
    ok, bad = _job("Traced", 1), _job("Invented", 2)
    _answers(ok)
    _answers(bad, made_up=True)
    for j in (ok, bad):
        _autopilot_sends(j, PAGE)
    subs = audit.sample(50)
    assert {s["company"] for s in subs} == {"Traced", "Invented"}
    text = audit.render_sample(subs, total=2)
    assert "✗ Why us?: I like robots." in text and "DOESN'T TRACE" in text
    assert "← An answer you approved before" not in text and "← Reused your approved answer (Globex)" in text
    assert "Checked 2 of 2 submitted applications: 4 answers, 1 that doesn't trace to a fact." in text
    assert text.rstrip().endswith("✗ Invented: Why us?")
    assert len(audit.sample(1, seed=3)) == 1 and audit.sample(1, seed=3) == audit.sample(1, seed=3)


def test_the_commands_print_plain_words_and_audit_fails_on_an_untraced_answer(capsys):
    jid = _job("Invented", 1)
    _answers(jid, made_up=True)
    _autopilot_sends(jid, PAGE)
    clicmds.main(["stats", "--days", "7"])
    assert "Last 7 days" in capsys.readouterr().out
    clicmds.main(["stats", "--json"])
    assert json.loads(capsys.readouterr().out)["submitted"] == 1
    try:
        clicmds.main(["audit", "-n", "5"])
    except SystemExit as e:
        assert e.code == 1
    else:
        raise AssertionError("audit should exit 1 when an answer doesn't trace")
    assert "1 that doesn't trace" in capsys.readouterr().out
