"""Retry held applications whose hold no longer applies.

An application stays held until something runs it again. Two kinds of hold can go stale without you doing anything:
your AI wasn't connected (or out of quota) when it was drafted and is now, or it was held by an earlier version of
Jobsmith, whose bug may since be fixed. "Retry held applications" under Needs you runs those again, and only those.

Never the ones that wait on you: a question only you can answer, a sign-in, a bot check, one you stopped, one
waiting for you to approve a first send, one autopilot may already have sent. The retry is a fill, never a send:
it goes through autopilot with every check (fit, your daily and per-company limits, your resume) and submit off,
the same path your own AI agent's applications take. What it fills waits for you as usual.
"""
from __future__ import annotations

import json
import re

from . import __version__, db, draft, fixes, guardrails, profile

# Held for something only you can do: a retry would only hold it again, or worse, try what it must not
YOURS = re.compile(r"Stopped by you|never signs in|never tries to get past|take over|sign[ -]?in|log[ -]?in|password|"
                   r"captcha|bot check|verification code|may already have sent|you may not qualify|Demo mode", re.I)
SEEN = "version_seen"       # settings row: {"version": ..., "since": time this version first ran}


def version_since() -> float:
    """When this version of Jobsmith first ran on your data. A hold older than that came from an earlier version.
    Recorded the first time it's asked (the engine asks at start-up)."""
    row = db.q1("SELECT value FROM settings WHERE key=?", (SEEN,))
    try:
        seen = json.loads(row["value"]) if row else None
    except json.JSONDecodeError:
        seen = None
    if isinstance(seen, dict) and seen.get("version") == __version__:
        return float(seen["since"])
    since = db.now()
    db.x("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
         (SEEN, db.enc({"version": __version__, "since": since})))
    return since


def _only_ai(job_id: str) -> bool:
    """Everything holding it is an answer for AI to write, or one AI couldn't write then."""
    items = draft.readiness(job_id)["items"]
    return bool(items) and all(b.get("pending") or (b.get("issue") or "").startswith(draft.NO_AI_ISSUES)
                               for b in items)


def stale(ai_connected: bool) -> list[dict]:
    """Held applications whose hold no longer applies, each with why: [{id, company, title, why}]. Read-only.
    ai_connected: whether your AI answers now (the engine's last check)."""
    from . import runner
    since = version_since()
    approving = {a["job_id"] for a in guardrails.awaiting_approval()} | set(runner.active())
    yours: set[str] = set()                      # applications waiting on a question only you can answer
    for f in fixes.compute()["fixes"]:
        if f["kind"] in ("profile", "essay", "question"):
            yours.update(f["jobs"])
    out = []
    for j in db.q("""SELECT id, company, title, ats, status, hold_reason, error, updated_at FROM jobs
                     WHERE active=1 AND status IN ('filled','error') ORDER BY updated_at"""):
        said = f"{j['hold_reason'] or ''} {j['error'] or ''}"
        if j["id"] in approving or YOURS.search(said) or guardrails.maybe_sent(j["id"]) or not runner.can_fill(j["ats"]):
            continue
        # only answers AI couldn't write then (some listed under Needs you for you to write instead, too)
        if ai_connected and j["status"] == "filled" and _only_ai(j["id"]):
            out.append(dict(j, why="Your AI is connected now"))
        elif j["updated_at"] < since and j["id"] not in yours:
            out.append(dict(j, why=f"Held by an earlier version of Jobsmith than {__version__}"))
    return [{k: r[k] for k in ("id", "company", "title", "why")} for r in out]


def plan(ai_connected: bool) -> dict:
    """What "Retry held applications" would do now, shown before it runs: how many it retries, and how many wait
    because of your limits. Read-only."""
    rows = stale(ai_connected)
    if not rows:
        return {"count": 0, "stale": 0, "jobs": [], "waiting": 0, "note": ""}
    if profile.attachment_file() is None:
        return {"count": 0, "stale": len(rows), "jobs": [], "waiting": len(rows),
                "note": "Add your resume as a PDF first: every application attaches it."}
    room = max(0, guardrails.remaining_today())
    go, capped = [], 0
    for r in rows:
        full = db.decode(db.q1("SELECT id, company, title, fit_score, fit_reasons FROM jobs WHERE id=?", (r["id"],)))
        if guardrails.cap_reason(full) or not guardrails.fit_gate(full)["passed"] or len(go) >= room:
            capped += 1
            continue
        go.append(r)
    note = f"{capped} wait for room under your limits." if capped else ""
    return {"count": len(go), "stale": len(rows), "jobs": go, "waiting": capped, "note": note}


def run(ai_connected: bool) -> dict:
    """Retry them: each is drafted and filled again with every check on and submit off, and waits for you after.
    Within your daily and per-company limits; the rest stay held. Never sends anything."""
    from . import runner
    p = plan(ai_connected)
    started = []
    for r in p["jobs"]:
        db.x("UPDATE jobs SET status='drafted', hold_reason=NULL, error=NULL, updated_at=? WHERE id=?",
             (db.now(), r["id"]))
        if runner.spawn(r["id"], "retrying", runner.autopilot([r["id"]], submit=False, every_check=True)):
            started.append(r["id"])
    return dict(p, started=started)
