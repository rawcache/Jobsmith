"""The feedback loop. Nothing is trained: green/red flags and your edits are stored and
retrieved as examples, rules, and trust levels for future applications."""
from __future__ import annotations

import math
import re
from collections import Counter

from . import db

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("a an the and or of to in for on at is are you your do does did have has with this that what "
            "please if any be will would which how".split())


def _toks(s: str) -> list[str]:
    return [w for w in _WORD.findall((s or "").lower()) if w not in _STOP]


def similarity(a: str, b: str) -> float:
    """Cosine similarity over word counts. Cheap and good enough for question matching."""
    ca, cb = Counter(_toks(a)), Counter(_toks(b))
    if not ca or not cb:
        return 0.0
    dot = sum(ca[w] * cb[w] for w in ca)
    return dot / (math.sqrt(sum(v * v for v in ca.values())) * math.sqrt(sum(v * v for v in cb.values())))


def approved_examples() -> list[dict]:
    """Every answer the user approved (green) or corrected (edited)."""
    rows = db.q("""SELECT d.*, j.company, j.title AS job_title FROM drafts d JOIN jobs j ON j.id=d.job_id
                   WHERE d.verdict='green' OR (d.final_answer IS NOT NULL AND d.final_answer != '')""")
    out = []
    for r in rows:
        r = db.decode(r)
        r["final"] = r["final_answer"] if r.get("final_answer") else r["answer"]
        r["edited"] = bool(r.get("final_answer")) and r["final_answer"] != r["answer"]
        out.append(r)
    return out


def similar_examples(label: str, qtype: str | None = None, k: int = 3, min_sim: float = 0.35) -> list[dict]:
    scored = []
    for ex in approved_examples():
        if qtype and ex["qtype"] != qtype and not {ex["qtype"], qtype} <= {"text", "textarea"}:
            continue
        s = similarity(label, ex["label"])
        if s >= min_sim:
            scored.append((s, ex))
    scored.sort(key=lambda t: (-t[0], -t[1]["updated_at"]))
    return [dict(ex, sim=round(s, 3)) for s, ex in scored[:k]]


def reusable_answer(label: str, qtype: str, options: list[str]) -> dict | None:
    """A past approved answer to essentially the same non-company-specific question."""
    from .classify import COMPANY_SPECIFIC, pick_option
    if COMPANY_SPECIFIC.search(label or "") or qtype in ("textarea", "file"):
        return None
    best = similar_examples(label, qtype, k=1, min_sim=0.8)
    if not best:
        return None
    ex = best[0]
    ans = ex["final"]
    if options:
        ans = pick_option(ans, options)
        if not ans:
            return None
    support = sum(1 for e in approved_examples() if similarity(label, e["label"]) >= 0.8 and not e["edited"])
    return {"answer": ans, "from": f"{ex['company']}: {ex['label']}", "support": support, "sim": ex["sim"]}


def guidance_rules(limit: int = 25) -> list[str]:
    """Your red-flag notes and job-level notes, newest first. Injected into every drafting prompt."""
    rules = [str(r) for r in (db.get_setting("writing_rules") or [])]
    for r in db.q("""SELECT note, label FROM drafts WHERE note IS NOT NULL AND note != ''
                     ORDER BY updated_at DESC LIMIT ?""", (limit,)):
        rules.append(f"(on \"{r['label'][:60]}\") {r['note']}")
    for r in db.q("""SELECT verdict_note, company FROM jobs WHERE verdict_note IS NOT NULL AND verdict_note != ''
                     ORDER BY updated_at DESC LIMIT ?""", (limit,)):
        rules.append(f"(job at {r['company']}) {r['verdict_note']}")
    return rules[:limit + len(db.get_setting("writing_rules") or [])]


def edit_examples(limit: int = 4) -> list[dict]:
    """Before/after pairs where the user rewrote a generated answer: the strongest style signal."""
    rows = db.q("""SELECT label, answer, final_answer FROM drafts WHERE kind='generated'
                   AND final_answer IS NOT NULL AND final_answer != '' AND final_answer != answer
                   ORDER BY updated_at DESC LIMIT ?""", (limit,))
    return rows


def trust_for(label: str) -> int:
    """How many times answers to similar questions were approved without edits."""
    return sum(1 for e in approved_examples() if not e["edited"] and similarity(label, e["label"]) >= 0.6)


def stats() -> dict:
    ex = approved_examples()
    red = db.q1("SELECT COUNT(*) n FROM drafts WHERE verdict='red'")["n"]
    return {
        "approved": sum(1 for e in ex if not e["edited"]),
        "edited": sum(1 for e in ex if e["edited"]),
        "rejected": red,
        "rules": guidance_rules(),
        "jobs_green": db.q1("SELECT COUNT(*) n FROM jobs WHERE verdict='green'")["n"],
        "jobs_red": db.q1("SELECT COUNT(*) n FROM jobs WHERE verdict='red'")["n"],
    }
