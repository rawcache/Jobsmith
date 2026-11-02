"""`jobsmith report`: the one screen sent to the maintainer each day while the gate is measured. Made-up data only
(Acme, Globex); nothing is sent or called."""
import json

from jobsmith import audit, clicmds, db, draft, guardrails, profile, report, runner, sources

SECRET = "I like robots and nobody else should read this."


def _job(company: str, n: int, ats_url: str = "https://job-boards.greenhouse.io/{c}/jobs/{n}") -> str:
    jid = sources.add_job_url(ats_url.format(c=company.lower(), n=n), company, "SWE Intern")
    db.x("UPDATE jobs SET fit_score=80 WHERE id=?", (jid,))
    return jid


def _sent(company: str, n: int, made_up: bool = False) -> str:
    jid = _job(company, n)
    profile.set_answer("work_authorized_us", "Yes", confirmed=True)
    fields = [{"field": "auth", "label": "Are you authorized to work in the US?", "qtype": "select"},
              {"field": "why", "label": "Why us?", "qtype": "textarea"}]
    draft.save_results(jid, fields, {
        "auth": {"kind": "answer_bank", "canon": "work_authorized_us", "answer": "Yes", "confidence": 1},
        "why": {"kind": "generated" if made_up else "learned", "answer": SECRET, "confidence": 0.9,
                "rationale": "Reused your approved answer (Globex)"}})
    audit.log_considered(jid, True, 80)
    guardrails.claim(jid)
    runner.record_submission(jid, "Confirmation page detected.")
    return jid


def test_with_nothing_yet_every_section_says_so():
    out = report.render(report.compute())
    for line in ("Gate, last 30 days", "nothing submitted yet", "Waiting on you: 0 held",
                 "1. Add your resume as a PDF: nothing held on it yet, but every application needs it",
                 "AI used today: 0", "Site errors, last 30 days", "  none"):
        assert line in out, line


def test_the_report_has_the_gate_the_audit_the_top_fixes_ai_and_site_errors_but_never_an_answer():
    _sent("Acme", 1)
    _sent("Globex", 2, made_up=True)                   # an AI answer citing no fact: doesn't trace
    held = _job("Initech", 3)
    db.x("UPDATE jobs SET status='filled', hold_reason='Add your resume PDF' WHERE id=?", (held,))
    broken = _job("Hooli", 4, "https://jobs.lever.co/{c}/{n}")
    db.x("UPDATE jobs SET status='error', error='Page timed out. Tried twice.', updated_at=? WHERE id=?",
         (db.now(), broken))
    d = report.compute()
    out = report.render(d)
    assert "submitted 2 (autopilot 2, you 0)" in out
    assert "2 applications, 4 answers: 1 DON'T TRACE" in out and "✗ Globex: Why us?" in out
    assert "Waiting on you: 2 held" in out
    assert "1. Add your resume as a PDF: unblocks 2" in out            # missing PDF: always the first fix
    assert "lever" in out and "1 × Page timed out" in out
    assert SECRET not in out and SECRET not in json.dumps(d)            # safe to paste: no answer you gave
    assert len(out.splitlines()) <= 40                                  # one screen


def test_with_your_pdf_and_nothing_held_no_fixes_are_waiting(monkeypatch, tmp_path):
    from jobsmith import profile as prof
    monkeypatch.setattr(prof, "attachment_file", lambda: tmp_path / "resume.pdf")
    assert "  no fixes waiting" in report.render(report.compute())


def test_the_command_prints_it_and_json_on_request(capsys):
    _sent("Acme", 1)
    clicmds.report_cmd([])
    assert "Jobsmith report" in capsys.readouterr().out
    clicmds.report_cmd(["--json"])
    d = json.loads(capsys.readouterr().out)
    assert d["stats"]["submitted"] == 1 and d["audit"]["submissions"] == 1 and "fixes" in d


def test_nothing_from_your_profile_or_a_quoted_draft_reaches_the_report(monkeypatch):
    """A held reason can quote a draft or name an answer from your profile (a city picked from a dropdown): both
    come out as "…", in the text and the JSON."""
    profile.set_answer("location", "Privateville, MA", confirmed=True)
    jid = _job("Initech", 3)
    db.x("UPDATE jobs SET status='error', error=?, updated_at=? WHERE id=?",
         ("Couldn't pick Privateville, MA from the Location list", db.now(), jid))
    other = _job("Hooli", 5)
    db.x("UPDATE jobs SET status='filled', hold_reason=? WHERE id=?",
         ("Stopped by you: draft said 'I led 400 robots at Northwind'", other))
    d = report.compute()
    out = report.render(d) + json.dumps(d)
    assert "Privateville" not in out and "Northwind" not in out and "400 robots" not in out
    assert "Couldn't pick … from the Location list" in out


def test_today_starts_at_midnight_not_24_hours_ago(monkeypatch):
    import time as t
    jid = _sent("Acme", 1)
    now = t.mktime((2026, 11, 3, 10, 0, 0, 0, 0, -1))                  # 10:00; it was sent at 23:00 the day before
    db.x("UPDATE runs SET started_at=?, finished_at=? WHERE job_id=?", (now - 11 * 3600, now - 11 * 3600, jid))
    d = report.compute(now=now)
    assert d["stats"]["submitted"] == 1 and d["today"]["submitted"] == 0


def test_submissions_with_no_answers_or_checked_from_drafts_are_said_so_not_called_proof():
    jid = _job("Acme", 1)
    audit.log_considered(jid, True, 80)
    guardrails.claim(jid)
    runner.record_submission(jid, "Confirmation page detected.")       # nothing drafted: no answers recorded
    out = report.render(report.compute())
    assert "1 applications, 0 answers: none recorded, so nothing is proven" in out
    assert "all trace" not in out
    _sent("Globex", 2)                                                  # drafts only: Jobsmith didn't fill it
    out = report.render(report.compute())
    assert "1 with no answers recorded: not checked" in out and "1 checked from drafts" in out


def test_naming_your_ai_asks_it_nothing(monkeypatch):
    from jobsmith import llm
    monkeypatch.setattr(llm, "backend", lambda *a, **k: (_ for _ in ()).throw(AssertionError("probed the AI")))
    import socket

    def no_network(*a, **k):
        raise AssertionError("the report opened a connection")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    db.set_settings({"llm_backend": "auto"})
    _sent("Acme", 1)
    assert "AI: auto" in report.render(report.compute())
