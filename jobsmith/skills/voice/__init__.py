"""The voice skill: how you write, learned from your own writing, on your computer.

Three jobs, none of which need an AI:
  1. Find your own passages that fit a question (BM25 over passages you added, plus answers you approved).
  2. Compose an answer from them when no AI is connected, the free limit ran out, or the AI's answer was weak.
     It uses your sentences as written; the only changes are the company and role names.
  3. Describe your style (sentence length, contractions, the stock phrases you never use) so any AI, even a
     small local one, gets steered toward it, and answers that drift get held for you instead of sent.

And it knows which common stories you have material for (why this company, a time you led, a conflict...).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from ... import db

STOP = set("""a an and are as at be been but by can could did do does for from had has have he her his how i if in
into is it its me my of on or our she so than that the their them then there these they this to too was we were
what when where which who why will with would you your about also just more most very really""".split())

# The questions applications ask again and again, and the words that mark a passage as material for one.
STORIES: dict[str, tuple[str, str, str]] = {
    "why_company": ("Why this company", r"why (do you want to|are you interested|this company|us\b|join|work (at|for|with))|what (excites|interests|draws) you about|why .{0,40}(company|team|us)\b",
                    r"\b(mission|product|team|culture|company|excited about|drawn to|admire)\b"),
    "why_role": ("Why this role", r"why (this|the) (role|position)|interest(ed)? in (this|the) (role|position)|what makes you a good fit",
                 r"\b(role|position|fit|interested in|want to work on)\b"),
    "leadership": ("A time you led", r"\blead(ership)?\b|\bled\b|took (the )?initiative|influence", r"\b(led|lead|leading|organized|mentored|managed|president|captain|founded|ran)\b"),
    "teamwork": ("Working on a team", r"\bteam(work)?\b|collaborat", r"\b(team|teammates|collaborat\w*|together|group)\b"),
    "conflict": ("A disagreement or conflict", r"conflict|disagree|difficult (person|teammate|coworker)", r"\b(disagree\w*|conflict|tension|compromise|pushed back)\b"),
    "failure": ("A failure or mistake", r"fail(ure|ed)|mistake|setback|went wrong", r"\b(failed|failure|mistake|wrong|learned from|setback)\b"),
    "challenge": ("A hard problem you solved", r"challeng|difficult (problem|project)|obstacle|overcame", r"\b(challeng\w*|hard|difficult|debug\w*|solved|figured out|overcame)\b"),
    "proud": ("A project you're proud of", r"proud|favorite project|project you|tell us about a project|technical project", r"\b(built|designed|project|shipped|implemented|developed)\b"),
    "impact": ("Measurable impact", r"impact|result|accomplish|achievement", r"\b(\d+%|\d[\d,]*\+?|reduced|increased|improved|saved|cut)\b"),
    "about": ("About you", r"tell us about yourself|introduce yourself|about you\b|describe yourself", r"\b(i am|i'm|my background|studying|student)\b"),
    "goals": ("Career goals", r"goal|five years|5 years|future|aspir|long[- ]term", r"\b(goals?|future|someday|career|want to become|hope to|after I graduate|grow into|in five years)\b"),
}
# Phrases that make an answer sound machine-written. If you never use one, Jobsmith won't let an AI either.
STOCK = ["passionate about", "i am excited to", "i'm excited to", "thrilled", "leverage", "delve", "synergy", "fast-paced",
         "cutting-edge", "align with", "aligns with", "furthermore", "moreover", "in today's", "ever-evolving", "tapestry",
         "i am writing to", "dynamic team", "unique blend", "testament to", "eager to contribute", "make a meaningful impact",
         "—", "invaluable", "honed", "spearheaded", "robust", "seamless", "pivotal"]


def _ensure() -> None:
    db.x("""CREATE TABLE IF NOT EXISTS voice_passages (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
            title TEXT, text TEXT NOT NULL, created_at REAL NOT NULL)""")


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9+#'.-]*", text.lower()) if w not in STOP and len(w) > 1]


def split_passages(text: str) -> list[str]:
    """Paragraphs of 30 to 220 words: short ones join the next, long ones split at sentences."""
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, buf = [], ""
    for p in paras:
        if re.match(r"^(dear|hi|hello|sincerely|best|thanks|regards)\b", p, re.I) and len(p.split()) < 12:
            continue
        buf = f"{buf} {p}".strip()
        if len(buf.split()) < 30:
            continue
        sents = re.split(r"(?<=[.!?])\s+", buf)
        cur = ""
        for s in sents:
            if len((cur + " " + s).split()) > 220 and cur:
                out.append(cur.strip())
                cur = s
            else:
                cur = f"{cur} {s}".strip()
        if cur:
            out.append(cur)
        buf = ""
    if buf and len(buf.split()) >= 12:
        out.append(buf)
    return out


def add(text: str, source: str = "pasted", title: str = "") -> int:
    _ensure()
    n = 0
    for p in split_passages(text):
        if not db.q1("SELECT 1 FROM voice_passages WHERE text=?", (p,)):
            db.x("INSERT INTO voice_passages(source, title, text, created_at) VALUES(?,?,?,?)", (source, title[:200], p, db.now()))
            n += 1
    return n


def add_file(path: Path) -> int:
    from ... import profile
    text = profile.read_text(path) if path.suffix.lower() in (".pdf", ".docx") else path.read_text(errors="replace")
    return add(text, source=path.name, title=path.stem)


def remove(pid: int) -> None:
    _ensure()
    db.x("DELETE FROM voice_passages WHERE id=?", (pid,))


def passages() -> list[dict]:
    """Your writing, plus every long answer you approved or wrote yourself in an application."""
    _ensure()
    rows = [dict(r, kind="sample") for r in db.q("SELECT id, source, title, text FROM voice_passages ORDER BY id")]
    for d in db.q("""SELECT d.id, d.label, COALESCE(d.final_answer, d.answer) text, j.company FROM drafts d JOIN jobs j ON j.id=d.job_id
                     WHERE (d.verdict='green' OR d.final_answer IS NOT NULL) AND d.qtype='textarea'
                       AND length(COALESCE(d.final_answer, d.answer)) > 120 ORDER BY d.id DESC LIMIT 200"""):
        rows.append({"id": -d["id"], "source": f"your answer to {d['company']}", "title": d["label"], "text": d["text"], "kind": "answer"})
    return rows


def story_of(question: str) -> str | None:
    for key, (_, q, _) in STORIES.items():
        if re.search(q, question, re.I):
            return key
    return None


def search(question: str, job: dict | None = None, k: int = 3) -> list[dict]:
    """Your passages that fit this question best (BM25, plus a boost for matching the question's story)."""
    docs = passages()
    if not docs:
        return []
    story = story_of(question)
    q = tokens(question) + (tokens(f"{job.get('title', '')} {(job.get('description') or '')[:1500]}")[:40] if job else [])
    toks = [tokens(d["text"]) for d in docs]
    N = len(docs)
    avg = sum(len(t) for t in toks) / N or 1
    df = Counter(w for t in toks for w in set(t))
    scored = []
    for d, t in zip(docs, toks):
        tf = Counter(t)
        s = sum(math.log(1 + (N - df[w] + .5) / (df[w] + .5)) * tf[w] * 2.2 / (tf[w] + 1.2 * (.25 + .75 * len(t) / avg))
                for w in set(q) if w in tf)
        if story and re.search(STORIES[story][2], d["text"], re.I):
            s += 2.5
        if d["kind"] == "answer" and story and story_of(d["title"] or "") == story:
            s += 3.0
        scored.append((s, d))
    scored.sort(key=lambda x: -x[0])
    return [dict(d, score=round(s, 2)) for s, d in scored[:k] if s > 0]


def _other_companies(text: str, job: dict) -> list[str]:
    """Company names in a passage that aren't this job's: an answer to Acme shouldn't say 'at Globex'."""
    from ... import network
    mine = network.norm_company(job.get("company", ""))
    names = set()
    for r in db.q("SELECT DISTINCT company FROM jobs WHERE company != '' LIMIT 3000"):
        c = r["company"]
        if len(c) > 2 and network.norm_company(c) != mine and re.search(rf"\b{re.escape(c)}\b", text):
            names.add(c)
    return sorted(names)


def _resume_text() -> str:
    """Your resume and profile facts, so names from your own history are never rewritten."""
    from ... import profile
    try:
        return profile.facts_prompt_block(20000)
    except Exception:
        return ""


def compose(job: dict, field: dict) -> dict | None:
    """An answer in your own words, with no AI: your best-fitting passages, trimmed to the limit, with the
    company and role names updated. None when you haven't written anything that fits."""
    hits = search(field["label"], job, k=4)
    if not hits:
        return None
    best = hits[0]
    text = best["text"]
    others = _other_companies(text, job)
    # Only a passage about wanting to join a company gets pointed at this one. A story that happened somewhere
    # (an internship, a hackathon) keeps its real names, and so does anywhere on your resume.
    story = story_of(field["label"])
    aimed = story in ("why_company", "why_role") and bool(
        re.search(STORIES["why_company"][2] + "|" + STORIES["why_role"][2], best["text"], re.I))
    yours = _resume_text().lower()
    swapped = [c for c in others if aimed and c.lower() not in yours]
    kept = [c for c in others if c not in swapped and c.lower() not in yours]
    for c in swapped:
        text = re.sub(rf"\b{re.escape(c)}\b", job.get("company", c), text)
    limit = _limit(field)
    if limit:
        unit, n = limit
        sents = re.split(r"(?<=[.!?])\s+", text)
        out = ""
        for s in sents:
            nxt = f"{out} {s}".strip()
            if (len(nxt.split()) if unit == "words" else len(nxt)) > n:
                break
            out = nxt
        text = out or text[: n if unit == "chars" else 10**9]
    fits_story = bool(story and re.search(STORIES[story][2], best["text"], re.I))
    conf = min(0.85, 0.35 + 0.05 * best["score"] + (0.2 if fits_story else 0) + (0.15 if best["kind"] == "answer" else 0))
    issues = [] if conf >= 0.6 else ["Built from your own writing, but it's only a loose fit. Check it."]
    if swapped:
        issues.append(f"Adapted from what you wrote for {', '.join(swapped)}. Check it reads right for {job.get('company')}.")
    if kept:
        conf = min(conf, 0.55)
        issues.append(f"Mentions {', '.join(kept)}, which isn't {job.get('company')}. Check it belongs in this answer.")
    return {"kind": "voice", "answer": text, "confidence": round(conf, 2), "fact_ids": [],
            "rationale": f"Your own words, from {best['source']}" + (f" ({best['title']})" if best.get("title") else ""),
            "issues": issues, "model": "your writing"}


def _limit(field: dict) -> tuple[str, int] | None:
    text = f"{field['label']} {field.get('description', '')}".lower()
    m = re.search(r"(\d[\d,]*)\s*(characters|chars|words)", text)
    return ("words" if m and "word" in m.group(2) else "chars", int(m.group(1).replace(",", ""))) if m else None


def style() -> dict:
    """How you write, measured from your samples: for prompts, and to catch answers that don't sound like you."""
    texts = [p["text"] for p in passages()]
    if not texts:
        return {"samples": 0}
    joined = " ".join(texts)
    sents = [s for s in re.split(r"(?<=[.!?])\s+", joined) if s.strip()]
    words = joined.split()
    contractions = len(re.findall(r"\b\w+'(s|re|ve|ll|d|m|t)\b", joined, re.I))
    used_stock = [p for p in STOCK if p in joined.lower()]
    return {"samples": len(texts), "words": len(words), "avg_sentence": round(len(words) / max(1, len(sents)), 1),
            "contractions_per_100": round(100 * contractions / max(1, len(words)), 1),
            "first_person_per_100": round(100 * len(re.findall(r"\b(i|my|me)\b", joined, re.I)) / max(1, len(words)), 1),
            "never_uses": [p for p in STOCK if p not in used_stock]}


def style_notes() -> str:
    s = style()
    if not s.get("samples"):
        return ""
    notes = [f"Sentences average {s['avg_sentence']} words."]
    notes.append("Uses contractions (I'm, don't)." if s["contractions_per_100"] >= 0.8 else "Rarely uses contractions.")
    if s["never_uses"]:
        notes.append("Never writes: " + ", ".join(f'"{p}"' for p in s["never_uses"][:14]) + ".")
    return " ".join(notes)


def style_issues(answer: str) -> list[str]:
    """Stock phrases you never use, in an answer an AI wrote for you."""
    s = style()
    banned = s.get("never_uses") if s.get("samples") else STOCK
    low = answer.lower()
    hits = [p for p in (banned or []) if p in low]
    return [f"Doesn't sound like you: \"{hits[0]}\"" + (f" and {len(hits) - 1} more" if len(hits) > 1 else "")] if hits else []


def coverage() -> list[dict]:
    """Which common stories you have material for, and which you should write a paragraph about."""
    texts = passages()
    out = []
    for key, (label, _, cue) in STORIES.items():
        n = sum(1 for p in texts if re.search(cue, p["text"], re.I) or story_of(p.get("title") or "") == key)
        out.append({"key": key, "label": label, "passages": n, "have": n > 0})
    return out


def summary() -> dict:
    _ensure()
    return {"style": style(), "coverage": coverage(),
            "samples": [dict(r) for r in db.q("SELECT id, source, title, substr(text,1,240) preview, length(text) chars FROM voice_passages ORDER BY id DESC")],
            "answers": sum(1 for p in passages() if p["kind"] == "answer")}
