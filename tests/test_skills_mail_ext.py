"""Skills (outreach, follow-ups), email providers, the bell, the extension's panel, and the practice copy."""
import json
import subprocess
import sys
import time

import pytest

from jobsmith import config, db, extension, mail, outcomes, profile, runner, skills
from jobsmith.skills import followups, outreach
from conftest import FIXTURES


def _job(jid="j1", company="Acme Robotics", title="Software Engineering Intern", status="new", url="https://boards.greenhouse.io/acme/jobs/1",
         description="Python, C++, ROS. Pay: $45 - $55 per hour."):
    now = db.now()
    db.x("""INSERT INTO jobs(id, company, title, url, ats, locations, terms, category, description, status, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (jid, company, title, url, "greenhouse", '["Boston, MA"]', '["Summer 2027"]', "Software",
                                                description, status, now, now))
    return jid


def test_skills_can_be_switched_off_but_apply_cannot():
    assert {"apply", "outreach", "followups"} <= skills.enabled()
    skills.set_enabled("outreach", False)
    assert "outreach" not in skills.enabled()
    with pytest.raises(KeyError):
        skills.set_enabled("apply", False)
    with pytest.raises(KeyError):
        skills.set_enabled("interview-notes", True)      # not built yet


async def test_outreach_drafts_without_ai_and_never_sends():
    from jobsmith import network
    await profile.ingest_document(FIXTURES / "sample_resume.tex")
    jid = _job()
    network.import_csv("First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                       "Priya,Natarajan,https://linkedin.com/in/x,,Acme Robotics,Senior Engineer,01 Mar 2025\n")
    cos = outreach.overview()
    assert cos and cos[0]["company"] == "Acme Robotics" and cos[0]["people"][0]["first_name"] == "Priya"
    d = await outreach.draft(jid, cos[0]["people"][0], "referral")
    assert d["text"].startswith("Hi Priya") and "Software Engineering Intern" in d["text"]
    row = db.q1("SELECT * FROM outreach")
    assert row["sent_at"] is None                    # only you mark it sent
    outreach.mark_sent(row["id"])
    assert db.q1("SELECT sent_at FROM outreach")["sent_at"]


def test_followups_find_quiet_applications():
    jid = _job(status="submitted")
    old = db.now() - 9 * 86400
    db.x("INSERT INTO runs(job_id, kind, status, started_at, finished_at) VALUES(?,?,?,?,?)", (jid, "submit", "done", old, old))
    b = followups.board()
    assert [q["id"] for q in b["quiet"]] == [jid] and "Software Engineering Intern" in b["quiet"][0]["draft"]
    followups.mark(jid, "snooze")
    assert followups.board()["quiet"] == []
    followups.mark(jid, "undo")
    outcomes.record({"id": jid}, "interview", "Next steps", "r@acme.com", db.now(), "m1")
    assert followups.board()["quiet"] == []          # they replied: nothing to follow up on
    assert followups.board()["counts"]["interview"] == 1


def test_email_providers():
    assert mail.xoauth2("a@b.edu", "TOK") == b"user=a@b.edu\x01auth=Bearer TOK\x01\x01"
    db.set_settings({"gmail_address": "me@school.edu"})
    assert mail.provider() == "outlook" and not mail.ready()
    db.set_settings({"ms_client_id": "cid", "ms_refresh_token": "rt"})
    assert mail.ready()
    db.set_settings({"email_provider": "gmail", "gmail_address": "me@gmail.com", "ms_refresh_token": ""})
    assert mail.provider() == "gmail" and not mail.ready()
    db.set_settings({"gmail_app_password": "abcd efgh ijkl mnop"})
    assert mail.ready()
    assert "administrator" in mail._ms_error({"error_description": "AADSTS65001: The user or administrator has not consented"})
    assert "client ID" in mail._ms_error({"error_description": "AADSTS700016: Application not found"})
    db.set_settings({"ms_client_id": ""})
    assert not mail.ms_start()["ok"]


def test_microsoft_device_sign_in(monkeypatch):
    calls = []

    class R:
        def __init__(self, code, body): self.status_code, self._b = code, body
        def json(self): return self._b

    replies = iter([R(200, {"device_code": "dc", "user_code": "ABCD-1234", "verification_uri": "https://microsoft.com/devicelogin", "interval": 5, "expires_in": 900}),
                    R(400, {"error": "authorization_pending"}),
                    R(200, {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600})])
    monkeypatch.setattr(mail.httpx, "post", lambda url, data, timeout: calls.append((url, data)) or next(replies))
    db.set_settings({"ms_client_id": "cid", "gmail_address": "me@school.edu"})
    s = mail.ms_start()
    assert s["ok"] and s["code"] == "ABCD-1234" and "IMAP.AccessAsUser.All" in calls[0][1]["scope"]
    assert mail.ms_poll() == {"ok": True, "done": False, "message": "Waiting for you to finish signing in…"}
    assert mail.ms_poll()["done"] and db.get_setting("ms_refresh_token") == "RT" and db.get_setting("email_provider") == "outlook"


async def test_bell_lists_held_applications_and_replies():
    from jobsmith import api
    jid = _job(status="filled")
    outcomes.record({"id": jid}, "interview", "Let's talk", "r@acme.com", db.now(), "m2")
    n = await api.notifications()
    kinds = [i["kind"] for i in n["items"]]
    assert "held" in kinds and "reply" in kinds and n["unread"] >= 2
    api.notifications_seen()
    n2 = await api.notifications()
    assert all(not i["unread"] for i in n2["items"] if not i.get("urgent"))


async def test_extension_panel_context_and_submission():
    await profile.ingest_document(FIXTURES / "sample_resume.tex")
    jid = _job()
    _job("j2", company="Globex", title="Software Engineering Intern", url="https://boards.greenhouse.io/globex/jobs/2")
    c = extension.context("https://boards.greenhouse.io/acme/jobs/1", "")
    assert c["known"] and c["job_id"] == jid and c["pay"] == "$45 - $55/hr" and "Python" in c["match"]["matched"]
    unknown = extension.context("https://jobs.ashbyhq.com/newco/123", "Data Intern", text="We use SQL and Python.")
    assert not unknown["known"] and unknown["company"] == "Newco"
    r = extension.submitted("https://boards.greenhouse.io/acme/jobs/1/apply", "Software Engineering Intern")
    assert r["job_id"] == jid and db.q1("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "submitted"
    assert [s["company"] for s in r["similar"]] == ["Globex"]
    g = await extension.generate("https://boards.greenhouse.io/acme/jobs/1", "Why do you want to work at Acme Robotics?")
    assert g["job_id"] == jid and g["text"] == "" and g["error"]     # no AI connected: says so instead of inventing


def test_demo_mode_never_opens_a_site(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    jid = _job()

    async def never():
        raise AssertionError("should not run")
    coro = never()
    assert runner.spawn(jid, "autopilot", coro) is False
    j = db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (jid,))
    assert j["status"] == "filled" and "Demo mode" in j["hold_reason"]
    assert not outcomes.email_ready()


def test_practice_copy_seeds_in_its_own_folder(tmp_path):
    env = {"JOBSMITH_DATA": str(tmp_path / "demo"), "JOBSMITH_DEMO": "1", "JOBSMITH_DEMO_DATA": str(tmp_path / "demo"), "PATH": "/usr/bin:/bin"}
    (tmp_path / "demo").mkdir()
    r = subprocess.run([sys.executable, "-m", "jobsmith", "demo-seed"], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    import sqlite3
    con = sqlite3.connect(tmp_path / "demo" / "jobsmith.db")
    assert con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] > 40
    assert con.execute("SELECT COUNT(*) FROM jobs WHERE status='submitted'").fetchone()[0] >= 4
    assert (tmp_path / "demo" / "Alex_Rivera_resume.tex").exists()
