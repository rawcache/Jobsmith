"""Limits autopilot works inside: how many applications it sends a day and to one company in a week.

Every submission counts toward the caps, yours included, so "12 of 20 today" means what it says. The caps only
stop autopilot: you can always submit an application yourself."""
from __future__ import annotations

import time

from . import db

WEEK = 7 * 86400

# Applications autopilot has clicked Submit on but whose confirmation page hasn't shown yet. They count toward the
# caps, so several tabs submitting at once can't go past them.
_submitting: set[str] = set()


def _midnight(now: float | None = None) -> float:
    """Start of today, local time: "today" on the dashboard is the calendar day, not the last 24 hours."""
    t = time.localtime(now if now is not None else time.time())
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def _submitted_since(since: float, company: str | None = None) -> set[str]:
    sql = """SELECT DISTINCT r.job_id FROM runs r JOIN jobs j ON j.id=r.job_id
             WHERE r.kind='submit' AND r.status IN ('done','unconfirmed') AND r.finished_at>=?"""
    args: list = [since]
    if company is not None:
        sql += " AND lower(trim(j.company))=lower(trim(?))"
        args.append(company)
    return {r["job_id"] for r in db.q(sql, args)}


def _in_flight(company: str | None = None) -> set[str]:
    if company is None or not _submitting:
        return set(_submitting)
    marks = ",".join("?" * len(_submitting))
    rows = db.q(f"SELECT id FROM jobs WHERE id IN ({marks}) AND lower(trim(company))=lower(trim(?))",
                [*_submitting, company])
    return {r["id"] for r in rows}


def sent_today() -> int:
    return len(_submitted_since(_midnight()) | _in_flight())


def sent_to_company(company: str) -> int:
    """Applications to this company in the last 7 days."""
    return len(_submitted_since(time.time() - WEEK, company) | _in_flight(company))


def caps() -> tuple[int, int]:
    """(per day, per company per week); 0 means no limit."""
    s = db.get_settings()
    return int(s.get("max_applications_per_day") or 0), int(s.get("max_applications_per_company") or 0)


def remaining_today() -> int:
    day, _ = caps()
    return 10**6 if day <= 0 else max(0, day - sent_today())


def maybe_sent(job_id: str) -> bool:
    """Autopilot clicked Submit on this one once and never saw a confirmation page."""
    return bool(db.q1("SELECT 1 FROM runs WHERE job_id=? AND kind='submit' AND status='unconfirmed'", (job_id,)))


def cap_reason(job: dict) -> str | None:
    """Why autopilot can't submit this application now, or None. Doesn't count the application itself."""
    if job.get("id") and maybe_sent(job["id"]):
        return ("Autopilot may already have sent this one: it clicked Submit but never saw a confirmation page. "
                "It won't send it again; check your email or the site, and submit it yourself if it didn't go through.")
    day, company = caps()
    others = {job.get("id")}
    today = len((_submitted_since(_midnight()) | _in_flight()) - others)
    if day > 0 and today >= day:
        return f"Daily cap reached: {today} of {day} sent today. Autopilot starts again tomorrow."
    if company > 0 and job.get("company"):
        n = len((_submitted_since(time.time() - WEEK, job["company"]) | _in_flight(job["company"])) - others)
        if n >= company:
            return (f"Company cap reached: {n} of {company} sent to {job['company'].strip()} this week. "
                    "Autopilot waits a week before sending another.")
    return None


def claim(job_id: str) -> None:
    """Autopilot is about to click Submit: count it now, before the confirmation page shows."""
    _submitting.add(job_id)


def release(job_id: str) -> bool:
    """The confirmation page showed. True when autopilot was the one that submitted it."""
    was = job_id in _submitting
    _submitting.discard(job_id)
    return was


def abandon(job_id: str, why: str) -> bool:
    """Autopilot clicked Submit (a claim always comes right before the click) but never saw a confirmation page:
    the tab closed, the run stopped or failed. The site may have taken it, so it keeps counting toward the caps,
    on disk so a restart doesn't forget it; the application waits under Needs you saying so, and autopilot never
    sends it again. True when it recorded one."""
    if job_id not in _submitting:
        return False
    db.x("INSERT INTO runs(job_id, kind, status, log, started_at, finished_at) VALUES(?,?,?,?,?,?)",
         (job_id, "submit", "unconfirmed", why, db.now(), db.now()))
    db.x("UPDATE jobs SET status='filled', error=NULL, hold_reason=?, updated_at=? WHERE id=?",
         ("Autopilot clicked Submit but never saw a confirmation page. Check your email or the site to see if it "
          f"went through ({why}).", db.now(), job_id))
    _submitting.discard(job_id)
    return True


def summary() -> dict:
    """What the dashboard shows: "12 of 20 today"."""
    day, company = caps()
    return {"sent_today": sent_today(), "daily_cap": day, "company_cap": company,
            "remaining_today": remaining_today()}
