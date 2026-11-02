"""`jobsmith report`: one screen to send the maintainer each day while the Phase 1 gate is measured.

What it shows: the gate numbers (`jobsmith stats`), the audit of every submitted application (`jobsmith audit`,
with no answer text, only whether each one traces), the five fixes waiting on you (Needs you), today's AI use
against your budget, and the job sites where applications stopped with an error.

Read-only: nothing is changed or sent, and no AI or other address is asked anything. It prints counts, company
names, question labels, error messages and why applications are held, with anything quoted and any of your
profile's answers taken out ("…"). Look it over before you paste it anywhere."""
from __future__ import annotations

import re
import time
from collections import Counter

from . import audit, db, fixes, llm, profile, stats

TOP_FIXES = 5


_QUOTES = "'\"\u2018\u2019\u201c\u201d`"
_BACKENDS = {"gemini_api": "Gemini (API)", "anthropic_api": "Claude (API)", "openai_api": "ChatGPT (API)",
             "ollama": "smith on this computer", "claude_cli": "Claude (subscription)",
             "auto": "auto (the first one that answers)"}


def _private() -> list[str]:
    """Your profile's answers, longest first: taken out of anything the report quotes."""
    vals = {(r.get("value") or "").strip() for r in profile.answers().values()}
    return sorted((v for v in vals if len(v) >= 3 and v.lower() not in ("yes", "no")), key=len, reverse=True)


def _clean(s: str, private: list[str], n: int = 90, quotes: bool = True) -> str:
    """A reason or label safe to paste: everything from the first quote mark to the last (a draft's words or an
    answer, whatever is inside) and any of your profile's answers become "…", and only then is it cut to one
    line, so a cut never leaves half a quote or half an answer behind. quotes=False for a form's own words (a
    question's label, "What's your…"), where only your answers are taken out."""
    s = " ".join((s or "").split())
    # an apostrophe between two letters (can't, Alex's) is a word's, not a quote's
    word = lambda i: s[i] in "'\u2019" and 0 < i < len(s) - 1 and s[i - 1].isalpha() and s[i + 1].isalpha()
    marks = [i for i, c in enumerate(s) if c in _QUOTES and not word(i)] if quotes else []
    if marks:                     # an odd count: the last quote never closes, so all of it from the first goes
        s = s[:marks[0]] + "…" + (s[marks[-1] + 1:] if len(marks) % 2 == 0 else "")
    for v in private:
        s = re.sub(rf"(?<!\w){re.escape(v)}(?!\w)", "…", s, flags=re.I)
    return s if len(s) <= n else s[:n - 3] + "..."


def _midnight(now: float) -> float:
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def _site_errors(since: float, private: list[str]) -> list[dict]:
    """Applications that stopped with an error since `since`, by job site, with the most common reason."""
    rows = db.q("""SELECT ats, COALESCE(NULLIF(error, ''), hold_reason, '') why FROM jobs
                   WHERE status='error' AND updated_at>=?""", (since,))
    by_site: dict[str, Counter] = {}
    for r in rows:
        why = stats._first_sentence(_clean(r["why"], private, 10**6)) or "no message"
        by_site.setdefault(r["ats"] or "unknown", Counter())[why] += 1
    out = [{"site": site, "count": sum(c.values()), "reasons": c.most_common(2)} for site, c in by_site.items()]
    return sorted(out, key=lambda s: (-s["count"], s["site"]))


def _audit(private: list[str]) -> dict:
    """Every submitted application, checked: how many answers, which don't trace to anything you gave, and how
    sure the check is (none recorded proves nothing; drafts may differ from what the form got)."""
    audit._ensure()
    total = db.q1("SELECT COUNT(*) n FROM audit_submissions")["n"]
    subs = audit.sample(total) if total else []
    bad = [{"company": s["company"], "label": _clean(f["label"], private, quotes=False)}
           for s in subs for f in s["fields"] if not f["traces"]]
    return {"submissions": total, "answers": sum(len(s["fields"]) for s in subs), "untraced": bad,
            "no_answers": sum(1 for s in subs if not s["fields"]),
            "from_drafts": sum(1 for s in subs if s["fields"] and s.get("basis") == "drafted")}


def _ai_today(now: float) -> dict:
    """llm.ai_today() without asking which AI is live (with "auto" that can call smith on this computer): today's
    calls against your budget, and the calls a free limit refused, from the usage log alone."""
    start = _midnight(now)
    n = lambda where: db.q1(f"SELECT COUNT(*) n FROM usage WHERE at BETWEEN ? AND ? AND {where}", (start, now))["n"]
    budget = llm.ai_budget()
    used = n("backend NOT IN ('ollama') AND (ok=1 OR COALESCE(error, '') NOT LIKE 'quota:%')")   # as ai_used_today
    out = f"Today's AI budget is used ({budget} calls)." if budget is not None and used >= budget else None
    return {"calls": used, "budget": budget, "smith_calls": n("backend='ollama' AND ok=1"),
            "refused": n("ok=0 AND COALESCE(error, '') LIKE 'quota:%'"), "out": out}


def _stats(days: float, now: float, private: list[str]) -> dict:
    """`jobsmith stats`, with its held reasons cleaned like every other reason here."""
    return stats.compute(days=days, now=now, clean=lambda why: _clean(why, private, 10**6))


def compute(days: int = 30, now: float | None = None) -> dict:
    now = now if now is not None else time.time()
    from . import __version__
    s = db.get_settings()
    fx = fixes.compute()
    private = _private()
    kind = s.get("llm_backend") or ""
    backend = _BACKENDS.get(kind, kind or "not set")     # from Settings: naming it never asks the AI anything
    return {
        "version": __version__, "at": now, "autonomy": s.get("autonomy"), "ai_backend": backend,
        "stats": _stats(days, now, private),
        "today": _stats((now - _midnight(now)) / stats.DAY, now, private),
        "audit": _audit(private),
        "held": fx["held"],
        "fixes": [{"title": _clean(f["title"], private, quotes=False), "unblocks": f["unblocks"], "ready_after": f["ready_after"]}
                  for f in fx["fixes"][:TOP_FIXES]],
        "more_fixes": max(0, len(fx["fixes"]) - TOP_FIXES),
        "own_problems": len(fx["applications"]),
        "own_reasons": Counter(_clean(a["own"][0], private) for a in fx["applications"] if a["own"])
                       .most_common(3),
        "ai_today": _ai_today(now),
        "site_errors": _site_errors(now - days * stats.DAY, private),
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
    lines.append(f"  today since midnight: submitted {today['submitted']}, confirmed {today['confirmed']}")

    lines += ["", f"Audit, every submitted application"]
    if not a["submissions"]:
        lines.append("  nothing submitted yet")
    else:
        ok = f"{len(a['untraced'])} DON'T TRACE to anything you gave Jobsmith" if a["untraced"] else \
            "none recorded, so nothing is proven" if not a["answers"] else "all trace to what you gave Jobsmith"
        lines.append(f"  {a['submissions']} applications, {a['answers']} answers: {ok}")
        if a["answers"] and a["no_answers"]:
            lines.append(f"    {a['no_answers']} with no answers recorded: not checked")
        if a["from_drafts"]:
            lines.append(f"    {a['from_drafts']} checked from drafts: Jobsmith didn't fill those forms, so what "
                         "was sent may differ")
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
    if ai["refused"]:
        lines.append(f"  {ai['refused']} refused today by a free limit")

    lines += ["", f"Site errors, last {st['days']} days"]
    if not d["site_errors"]:
        lines.append("  none")
    for e in d["site_errors"]:
        reasons = "; ".join(f"{n} × {why}" for why, n in e["reasons"])
        lines.append(f"  {e['site']:<16} {e['count']:>3}   {reasons}")
    return "\n".join(lines)
