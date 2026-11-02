"""`jobsmith report`: one screen to send the maintainer each day while the Phase 1 gate is measured.

What it shows: the gate numbers (`jobsmith stats`), the audit of every submitted application (`jobsmith audit`,
with no answer text, only whether each one traces), the five fixes waiting on you (Needs you), today's AI use
against your budget, and the job sites where applications stopped with an error.

Read-only: nothing is changed, sent or called. It prints counts, company names, question labels, error messages
and why applications are held (which can quote a few words of a draft), never a whole answer. Look it over before
you paste it anywhere."""
from __future__ import annotations

import time
from collections import Counter

from . import audit, db, fixes, llm, stats

TOP_FIXES = 5


def _short(s: str, n: int = 90) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 3] + "..."


def _site_errors(since: float) -> list[dict]:
    """Applications that stopped with an error since `since`, by job site, with the most common reason."""
    rows = db.q("""SELECT ats, COALESCE(NULLIF(error, ''), hold_reason, '') why FROM jobs
                   WHERE status='error' AND updated_at>=?""", (since,))
    by_site: dict[str, Counter] = {}
    for r in rows:
        by_site.setdefault(r["ats"] or "unknown", Counter())[stats._first_sentence(r["why"]) or "no message"] += 1
    out = [{"site": site, "count": sum(c.values()), "reasons": c.most_common(2)} for site, c in by_site.items()]
    return sorted(out, key=lambda s: (-s["count"], s["site"]))


def _audit() -> dict:
    """Every submitted application, checked: how many answers, and which don't trace to anything you gave."""
    audit._ensure()
    total = db.q1("SELECT COUNT(*) n FROM audit_submissions")["n"]
    subs = audit.sample(total) if total else []
    bad = [{"company": s["company"], "label": f["label"]} for s in subs for f in s["fields"] if not f["traces"]]
    return {"submissions": total, "answers": sum(len(s["fields"]) for s in subs), "untraced": bad}


def compute(days: int = 30, now: float | None = None) -> dict:
    now = now if now is not None else time.time()
    from . import __version__
    s = db.get_settings()
    fx = fixes.compute()
    try:
        backend = llm.label(llm.backend())
    except Exception as e:                                # no AI set up is something to report, not a crash
        backend = f"not set up ({e.__class__.__name__})"
    return {
        "version": __version__, "at": now, "autonomy": s.get("autonomy"), "ai_backend": backend,
        "stats": stats.compute(days=days, now=now),
        "today": stats.compute(days=1, now=now),
        "audit": _audit(),
        "held": fx["held"],
        "fixes": [{"title": f["title"], "unblocks": f["unblocks"], "ready_after": f["ready_after"]}
                  for f in fx["fixes"][:TOP_FIXES]],
        "more_fixes": max(0, len(fx["fixes"]) - TOP_FIXES),
        "own_problems": len(fx["applications"]),
        "own_reasons": Counter(_short(a["own"][0]) for a in fx["applications"] if a["own"])
                       .most_common(3),
        "ai_today": llm.ai_today(),
        "site_errors": _site_errors(now - days * stats.DAY),
    }


def render(d: dict) -> str:
    """Plain words, one screen."""
    st, today, a, ai = d["stats"], d["today"], d["audit"], d["ai_today"]
    pct = lambda p: "n/a" if p is None else f"{p}%"
    lines = [f"Jobsmith report · {time.strftime('%Y-%m-%d %H:%M', time.localtime(d['at']))} · v{d['version']} · "
             f"{d['autonomy']} · AI: {d['ai_backend']}", ""]

    lines.append(f"Gate, last {st['days']} days")
    lines.append(f"  good matches sent without you  {st['good_without_you']} of {st['good']}   "
                 f"{pct(st['good_without_you_pct'])} (goal 80%)")
    lines.append(f"  submitted {st['submitted']} (autopilot {st['by_autopilot']}, you {st['by_you']}), "
                 f"confirmed {st['confirmed']} ({pct(st['confirmed_pct'])})")
    lines.append(f"  today: submitted {today['submitted']}, confirmed {today['confirmed']}")

    lines += ["", f"Audit, every submitted application"]
    if not a["submissions"]:
        lines.append("  nothing submitted yet")
    else:
        ok = "all trace to what you gave Jobsmith" if not a["untraced"] else \
            f"{len(a['untraced'])} DON'T TRACE to anything you gave Jobsmith"
        lines.append(f"  {a['submissions']} applications, {a['answers']} answers: {ok}")
        lines += [f"    ✗ {b['company']}: {b['label']}" for b in a["untraced"][:3]]
        if len(a["untraced"]) > 3:
            lines.append(f"    and {len(a['untraced']) - 3} more (jobsmith audit)")

    lines += ["", f"Waiting on you: {d['held']} held"]
    if not d["fixes"]:
        lines.append("  no fixes waiting")
    for i, f in enumerate(d["fixes"], 1):
        go = f", {f['ready_after']} go out after it" if f["ready_after"] else ""
        lines.append(f"  {i}. {f['title']}: " + (f"unblocks {f['unblocks']}{go}" if f["unblocks"] else
                                                 "nothing held on it yet, but every application needs it"))
    tail = [f"{d['more_fixes']} more fixes"] * bool(d["more_fixes"]) + \
        [f"{d['own_problems']} with a problem of their own"] * bool(d["own_problems"])
    if tail:
        lines.append(f"  ({', '.join(tail)}: jobsmith review)")
    lines += [f"    {n} × {why}" for why, n in d["own_reasons"]]

    budget = f" of {ai['budget']}" if ai["budget"] is not None else ""
    lines += ["", f"AI used today: {ai['calls']}{budget} calls" + (f", {ai['smith_calls']} by smith" if ai["smith_calls"] else "")
              + f" · last {st['days']} days: {st['ai']['calls']} calls"
              + (f", {st['ai']['failed']} failed" if st["ai"]["failed"] else "")]
    if ai["out"]:
        lines.append(f"  {ai['out']}")

    lines += ["", f"Site errors, last {st['days']} days"]
    if not d["site_errors"]:
        lines.append("  none")
    for e in d["site_errors"]:
        reasons = "; ".join(f"{n} × {why}" for why, n in e["reasons"])
        lines.append(f"  {e['site']:<16} {e['count']:>3}   {reasons}")
    return "\n".join(lines)
