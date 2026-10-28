"""`jobsmith stats`: did the submissions land, and how much did autopilot do without you?

    Submitted      every submission in the period: autopilot's, confirmed or not, and the ones you sent
    Confirmed      submissions with proof they landed: the site's confirmation page, its confirmation email, or a
                   later reply from the company
    Good matches   jobs autopilot picked for itself at or above your fit bar. The share it sent without you is the
                   Phase 1 gate (80%); every one it held, hit a limit on, failed or skipped counts against it.

Everything is read from your own data folder. Nothing is sent anywhere."""
from __future__ import annotations

import time
from collections import Counter

from . import audit, db, outcomes

DAY = 86400


def _proof(sub: dict) -> set[str]:
    """How we know this submission landed: page, email, reply (none: no proof yet)."""
    kinds = {c["kind"] for c in db.q("SELECT kind FROM confirmations WHERE run_id=?", (sub["id"],))}
    # Any reply after you applied (received, assessment, interview, rejection, offer) means they have it.
    if db.q1("SELECT 1 FROM outcomes WHERE job_id=? AND received_at>=?", (sub["job_id"], sub["started_at"] - 3600)):
        kinds.add("reply")
    return kinds


def _first_sentence(s: str) -> str:
    s = " ".join((s or "").split())
    for end in (". ", ": "):
        if end in s:
            s = s.split(end, 1)[0]
    return s[:90]


def compute(days: int = 30, now: float | None = None) -> dict:
    audit._ensure()
    outcomes._ensure()
    now = now if now is not None else time.time()
    since = now - days * DAY
    subs = db.q("""SELECT r.id, r.job_id, r.status, r.started_at, COALESCE(s.sent_by, 'you') sent_by
                   FROM runs r LEFT JOIN audit_submissions s ON s.run_id=r.id
                   WHERE r.kind='submit' AND r.status IN ('done','unconfirmed') AND r.finished_at BETWEEN ? AND ?""",
                (since, now))
    proof = {s["id"]: _proof(s) for s in subs}
    confirmed = [s for s in subs if proof[s["id"]]]
    how = Counter(k for s in confirmed for k in proof[s["id"]])

    seen = db.q("""SELECT c.job_id, MIN(c.at) first, MAX(c.good) good, j.status, j.hold_reason
                   FROM considered c LEFT JOIN jobs j ON j.id=c.job_id
                   WHERE c.at BETWEEN ? AND ? GROUP BY c.job_id""", (since, now))
    good = [g for g in seen if g["good"]]
    by_job: dict[str, list[dict]] = {}
    for s in db.q("""SELECT r.job_id, r.status, r.finished_at, COALESCE(a.sent_by, 'you') sent_by FROM runs r
                     LEFT JOIN audit_submissions a ON a.run_id=r.id
                     WHERE r.kind='submit' AND r.status IN ('done','unconfirmed') AND r.finished_at<=?""", (now,)):
        by_job.setdefault(s["job_id"], []).append(s)
    buckets: Counter = Counter()
    held_why: Counter = Counter()
    for g in good:
        runs = [r for r in by_job.get(g["job_id"], []) if r["finished_at"] >= g["first"]]
        if any(r["status"] == "done" and r["sent_by"] == "autopilot" for r in runs):
            buckets["without_you"] += 1
        elif any(r["status"] == "unconfirmed" for r in runs):
            buckets["unconfirmed"] += 1
        elif runs:
            buckets["you_sent"] += 1
        elif g["status"] == "filled":
            buckets["held"] += 1
            held_why[_first_sentence(g["hold_reason"]) or "Waiting for you"] += 1
        elif g["status"] == "error":
            buckets["failed"] += 1
        elif g["status"] == "skipped":
            buckets["skipped"] += 1
        else:
            buckets["not_yet"] += 1             # still drafting, or waiting for room under a limit
    pct = lambda a, b: round(100 * a / b) if b else None
    return {
        "days": days, "since": since, "until": now,
        "submitted": len(subs),
        "by_autopilot": sum(1 for s in subs if s["sent_by"] == "autopilot"),
        "by_you": sum(1 for s in subs if s["sent_by"] != "autopilot"),
        "confirmed": len(confirmed), "confirmed_pct": pct(len(confirmed), len(subs)),
        "confirmed_by": {"page": how["page"], "email": how["email"], "reply": how["reply"]},
        "unconfirmed": [s["job_id"] for s in subs if not proof[s["id"]]],
        "considered": len(seen), "good": len(good),
        "good_without_you": buckets["without_you"], "good_without_you_pct": pct(buckets["without_you"], len(good)),
        "good_outcomes": {k: buckets[k] for k in ("without_you", "unconfirmed", "you_sent", "held", "failed",
                                                   "skipped", "not_yet")},
        "held_reasons": held_why.most_common(5),
    }


def render(d: dict) -> str:
    """Plain words for the terminal."""
    day = audit._day
    pct = lambda p: "n/a" if p is None else f"{p}%"
    o = d["good_outcomes"]
    lines = [f"Last {d['days']} days ({day(d['since'])} to {day(d['until'])})", ""]
    lines.append(f"Submitted          {d['submitted']:>4}   autopilot {d['by_autopilot']}, you {d['by_you']}")
    cb = d["confirmed_by"]
    lines.append(f"Confirmed          {d['confirmed']:>4}   {pct(d['confirmed_pct'])} of submitted "
                 f"(page {cb['page']}, email {cb['email']}, reply {cb['reply']})")
    if d["unconfirmed"]:
        lines.append(f"  no proof yet     {len(d['unconfirmed']):>4}   check the site or your email for these")
    lines += ["", f"Good matches       {d['good']:>4}   of {d['considered']} jobs autopilot picked for itself"]
    lines.append(f"  sent without you {o['without_you']:>4}   {pct(d['good_without_you_pct'])} (Phase 1 goal: 80%)")
    for key, label in (("unconfirmed", "clicked Submit, no confirmation"), ("you_sent", "you sent it"),
                       ("held", "held for you"), ("failed", "stopped with an error"),
                       ("skipped", "skipped, you may not qualify"), ("not_yet", "not done yet")):
        if o[key]:
            lines.append(f"  {label}: {o[key]}")
    if d["held_reasons"]:
        lines += ["", "Why autopilot held them:"]
        lines += [f"  {n} × {why}" for why, n in d["held_reasons"]]
    return "\n".join(lines)
