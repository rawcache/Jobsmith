"""Inbox and follow-ups: what companies said back (from your email, read-only), and which applications have gone
quiet long enough that a short, polite follow-up makes sense. Jobsmith drafts the follow-up; you send it."""
from __future__ import annotations

from ... import db, outcomes

QUIET_DAYS = 7


def _ensure() -> None:
    outcomes._ensure()
    db.x("CREATE TABLE IF NOT EXISTS followups (job_id TEXT PRIMARY KEY, done_at REAL, snooze_until REAL)")


def board() -> dict:
    _ensure()
    now = db.now()
    replies = db.q("""SELECT o.id, o.kind, o.subject, o.sender, o.received_at, j.id job_id, j.company, j.title
                      FROM outcomes o JOIN jobs j ON j.id = o.job_id ORDER BY o.received_at DESC LIMIT 60""")
    sent = db.q("""SELECT j.id, j.company, j.title, j.outcome, MAX(r.finished_at) sent_at, f.done_at, f.snooze_until
                   FROM jobs j JOIN runs r ON r.job_id = j.id AND r.kind='submit' AND r.status='done'
                   LEFT JOIN followups f ON f.job_id = j.id
                   WHERE j.status='submitted' GROUP BY j.id ORDER BY sent_at""")
    quiet = []
    for j in sent:
        days = (now - (j["sent_at"] or now)) / 86400
        if j["outcome"] in ("rejected", "offer", "interview", "assessment") or j["done_at"] or (j["snooze_until"] or 0) > now:
            continue
        if days >= QUIET_DAYS:
            quiet.append(dict(j, days=int(days), draft=draft_text(j)))
    waiting = [dict(j, days=int((now - (j["sent_at"] or now)) / 86400)) for j in sent
               if not j["outcome"] or j["outcome"] == "received"]
    return {"replies": replies, "quiet": quiet, "waiting": len(waiting), "email": outcomes.email_ready(),
            "counts": {k: sum(1 for r in replies if r["kind"] == k) for k in outcomes.RANK}}


def draft_text(job: dict) -> str:
    from ... import profile
    me = {k: v["value"] for k, v in profile.answers().items() if v.get("value")}
    name = " ".join(x for x in (me.get("first_name"), me.get("last_name")) if x)
    return (f"Hi {job['company']} recruiting team,\n\nI applied for the {job['title']} role a little over a week ago and wanted "
            "to follow up. I'm still very interested and would be glad to share anything else that would help with my application.\n\n"
            f"Thank you for your time,\n{name}").strip()


def mark(job_id: str, action: str) -> None:
    _ensure()
    if action == "done":
        db.x("INSERT INTO followups(job_id, done_at) VALUES(?,?) ON CONFLICT(job_id) DO UPDATE SET done_at=excluded.done_at",
             (job_id, db.now()))
    elif action == "snooze":
        db.x("INSERT INTO followups(job_id, snooze_until) VALUES(?,?) ON CONFLICT(job_id) DO UPDATE SET snooze_until=excluded.snooze_until",
             (job_id, db.now() + 7 * 86400))
    elif action == "undo":
        db.x("DELETE FROM followups WHERE job_id=?", (job_id,))
