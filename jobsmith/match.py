"""Fit scoring. Deterministic and free, so it can score thousands of listings instantly.
Signals: category/season/location targets, sponsorship compatibility, skill overlap,
whether Jobsmith can auto-fill the ATS, recency, and what you've green/red-flagged before."""
from __future__ import annotations

import json
import math
import re
import time

from . import ats, db, eligibility, profile

STOP = set("""a an and are as at be by for from has have in is it of on or that the to with we you your our
will this their they who what intern internship summer 2026 2027 fall spring winter engineer engineering
software team role work using build new""".split())

SKILL_ALIASES = {
    "ml": ["machine learning", "ml"], "cv": ["computer vision", "opencv", "yolo"],
    "fpga": ["fpga", "verilog", "vhdl", "systemverilog", "rtl"],
    "cloud": ["aws", "gcp", "azure", "cloud", "lambda", "dynamodb"],
    "data": ["sql", "spark", "databricks", "etl", "pipeline", "data"],
    "embedded": ["embedded", "firmware", "arduino", "microcontroller", "jetson"],
}


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.\-/]{1,}", (text or "").lower())
    return {w.strip(".-/") for w in words if w not in STOP and len(w) > 1}


def profile_vocab() -> set[str]:
    vocab: set[str] = set()
    for f in profile.facts():
        if f["category"] in ("skill", "experience", "project", "education"):
            vocab |= tokens(f["text"])
    return vocab


def _learned_company_bias() -> dict[str, float]:
    bias: dict[str, float] = {}
    try:   # replies from employers: interviews/assessments nudge similar roles up, rejections slightly down
        for r in db.q("SELECT category, outcome FROM jobs WHERE outcome IS NOT NULL"):
            d = {"offer": 4, "interview": 3, "assessment": 2, "rejected": -1}.get(r["outcome"], 0)
            bias[r["category"] or ""] = bias.get(r["category"] or "", 0) + d
    except Exception:
        pass
    for r in db.q("SELECT company, category, verdict FROM jobs WHERE verdict IS NOT NULL"):
        delta = 6 if r["verdict"] == "green" else -10
        bias[r["category"] or ""] = bias.get(r["category"] or "", 0) + delta / 3
        bias["co:" + r["company"].lower()] = bias.get("co:" + r["company"].lower(), 0) + delta
    return bias


_US = re.compile(r",\s*(A[LKZR]|C[AOT]|D[EC]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|"
                 r"T[NX]|UT|V[AT]|W[AIVY])\b|\b(USA|United States|US|Remote in USA|Remote)\b|^(NYC|SF|Remote)$", re.I)


def _in_us(loc: str) -> bool:
    from .draft import US_STATES
    l = loc.strip()
    if l.upper() in US_STATES or l in ("LA", "SF", "South SF", "NYC", "DC") or \
            any(l.lower() == n.lower() or l.lower().endswith(", " + n.lower()) for n in US_STATES.values()):
        return True
    if re.search(r"\b(UK|Canada|India|Germany|London|Toronto|Singapore|Ireland|Japan|China|Israel|Mexico|Europe|"
                 r"Netherlands|France|Poland|Australia|Taiwan|Korea|Switzerland|Spain|Brazil|Italy|United Kingdom)\b",
                 l, re.I):
        return False
    return bool(_US.search(l))


# --------------------------------------------------------------------------- what you're looking for
# Level, role type, place and how fresh a posting is are filters, not nudges: a role outside them isn't a match at
# any fit, so it scores at most OUT_OF_SCOPE (under every fit bar setup offers) and says why. Before these were
# filters, a role in the right season and category started at 60+ with no skill overlap at all, so a fit bar of 40
# let thousands through.
OUT_OF_SCOPE = 10.0
SEASON = re.compile(r"^(Summer|Fall|Winter|Spring) \d{4}$")
INTERN_TITLE = re.compile(r"\bintern(ship)?s?\b|\bco-?op\b|\bapprentice(ship)?\b|\bsummer (analyst|associate)\b", re.I)
NEWGRAD_TITLE = re.compile(r"new ?grad|university grad|recent grad|college grad|early[- ]career|entry[- ]level|"
                           r"graduate (engineer|program|software|developer|analyst)|\bjunior\b|\b(engineer|developer) i\b",
                           re.I)
LEVELS = ("internship", "newgrad")


def level_of(job: dict) -> str:
    """'internship', 'newgrad', or '' when neither the list's season nor the title says."""
    terms = [t for t in job.get("terms") or [] if t and t != "N/A"]
    if "New Grad" in terms:
        return "newgrad"
    if any(SEASON.match(t) for t in terms):
        return "internship"
    title = job.get("title") or ""
    if INTERN_TITLE.search(title):
        return "internship"
    if NEWGRAD_TITLE.search(title):
        return "newgrad"
    return ""


def place_matches(job: dict, wanted: list[str]) -> bool:
    locs = " ".join(job.get("locations") or [])
    return any(re.search(r"(?<![A-Za-z])" + re.escape(t) + r"(?![A-Za-z])", locs, re.I) for t in wanted)


def category_of(job: dict) -> str:
    return job.get("category") or guess_category(job.get("title") or "")


def category_wanted(cat: str, targets: list[str]) -> bool:
    return not targets or not cat or any(t.lower() in cat.lower() or cat.lower() in t.lower() for t in targets)


def scope(job: dict, s: dict) -> list[str]:
    """Why a role is outside what you're looking for (empty: it's inside). Companies you named keep any level."""
    out: list[str] = []
    levels = [g for g in (s.get("goals") or []) if g in LEVELS]
    named = (job.get("company") or "").strip().lower() in {c.strip().lower() for c in s.get("target_companies") or []}
    lvl = level_of(job)
    if levels and not named:
        if lvl and lvl not in levels:
            out.append("not your level (" + ("an internship" if lvl == "internship" else "a new grad role") + ")")
        elif not lvl and levels == ["internship"]:
            out.append("not an internship")
        elif lvl == "internship":
            seasons = [t for t in job.get("terms") or [] if SEASON.match(t or "")]
            wanted = [t for t in s.get("target_terms") or [] if SEASON.match(t)]
            if seasons and wanted and not set(seasons) & set(wanted):
                out.append(f"not your season ({', '.join(seasons)})")
    cat = category_of(job)
    if not category_wanted(cat, s.get("target_categories") or []):
        out.append(f"not a role type you picked ({cat})")
    if job.get("locations"):
        tl = s.get("target_locations") or []
        if tl and not place_matches(job, tl):
            out.append("not in your places")
        elif not tl and not any(_in_us(l) for l in job["locations"]):
            out.append("outside the US")
    days = int(s.get("max_posting_age_days") or 0)
    posted = job.get("date_posted")
    if days and posted and (time.time() - float(posted)) / 86400 > days:
        out.append(f"posted over {days} days ago")
    return out


def score_job(job: dict, s: dict, vocab: set[str], bias: dict[str, float]) -> tuple[float, list[str]]:
    sc, reasons = _score(job, s, vocab, bias)
    outside = scope(job, s)
    if outside and sc > OUT_OF_SCOPE:
        sc = OUT_OF_SCOPE
        reasons.insert(0, "- outside what you're looking for: " + "; ".join(outside))
    return sc, reasons


def _score(job: dict, s: dict, vocab: set[str], bias: dict[str, float]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 35.0
    cat = job.get("category") or ""
    targets = s.get("target_categories") or []
    if not targets or any(t.lower() in cat.lower() or cat.lower() in t.lower() for t in targets if cat):
        score += 15
        reasons.append(f"+ category {cat or 'n/a'}")
    elif cat:
        score -= 20
        reasons.append(f"- category {cat} not targeted")

    terms = job.get("terms") or []
    tt = s.get("target_terms") or []
    if tt and terms and not set(terms) & set(tt):
        score -= 30
        reasons.append(f"- season {', '.join(terms)}")
    elif tt and set(terms) & set(tt):
        score += 10
        reasons.append("+ season match")

    locs = " ".join(job.get("locations") or [])
    tl = s.get("target_locations") or []
    wanted_place = False
    if tl:
        if any(re.search(r"(?<![A-Za-z])" + re.escape(t) + r"(?![A-Za-z])", locs, re.I) for t in tl):
            score += 8
            wanted_place = True
            reasons.append("+ location")
        else:
            score -= 10
            reasons.append("- location")

    if job.get("locations") and not wanted_place and not any(_in_us(l) for l in job["locations"]):
        score -= 25
        reasons.append("- outside the US")

    spons = (job.get("sponsorship") or "").lower()
    needs = s.get("_needs_sponsorship", False)
    citizen = s.get("_citizen", False)
    if needs and ("does not" in spons or "citizenship" in spons):
        score -= 40
        reasons.append("- no sponsorship")
    if "citizenship is required" in spons and citizen:
        score += 4
        reasons.append("+ citizenship-required (you qualify)")

    text = f"{job.get('title', '')} {job.get('description', '')}"
    jt = tokens(text)
    overlap = jt & vocab
    if jt:
        k = min(20.0, 4 * math.log1p(len(overlap)) * (2 if job.get("description") else 1.3))
        score += k
        if overlap:
            reasons.append("+ skills: " + ", ".join(sorted(overlap, key=len, reverse=True)[:6]))

    if job.get("ats") in ats.SUPPORTED:
        score += 6
        reasons.append(f"+ auto-fill supported ({job['ats']})")

    posted = job.get("date_posted")
    if posted:
        days = (time.time() - float(posted)) / 86400
        if days < 7:
            score += 6
            reasons.append("+ posted this week")
        elif days > 60:
            score -= 6
            reasons.append("- older than 60 days")

    co = (job.get("company") or "").lower()
    if co in [c.lower() for c in s.get("exclude_companies") or []]:
        score = 0
        reasons.append("- excluded company")
    b = bias.get("co:" + co, 0) + bias.get(cat, 0)
    if b:
        score += max(-25, min(15, b))
        reasons.append(f"{'+' if b > 0 else '-'} your past flags")
    for why, pts in value_bonus(job, s.get("values") or []):
        score += pts
        reasons.append(f"+ you value {why}")
    if not job.get("active"):
        score -= 50
        reasons.append("- closed")
    return max(0.0, min(100.0, round(score, 1))), reasons


# What you said you value in a role (up to 3, from setup or Job preferences): small nudges toward roles that
# show it. Only things a posting can actually show; the rest still shapes cover letters and "why us" answers.
VALUES = ["Learning and mentorship", "Hard technical problems", "Impact on real users", "Pay", "Well-known company",
          "Small team, big ownership", "Path to a full-time offer", "Work-life balance", "A mission I care about",
          "Remote or flexible"]


def value_bonus(job: dict, values: list[str]) -> list[tuple[str, float]]:
    from . import clout, insights
    if not values:
        return []
    text = f"{job.get('title', '')} {job.get('description', '')}"
    out: list[tuple[str, float]] = []
    known = clout.rank(job.get("company") or "")
    for v in values[:3]:
        if v == "Well-known company" and known is not None:
            out.append(("well-known companies", 6 if known < 60 else 3))
        elif v == "Small team, big ownership" and (known is None and re.search(
                r"\b(startup|seed|series [a-c]|early[- ]stage|founding|small team)\b", text, re.I)):
            out.append(("small teams", 5))
        elif v == "Pay" and insights.pay_of(job.get("description") or ""):
            out.append(("pay (listed)", 3))
        elif v == "Path to a full-time offer" and re.search(r"return offer|full[- ]time (conversion|offer)|convert to full", text, re.I):
            out.append(("a full-time path", 5))
        elif v == "Learning and mentorship" and re.search(r"\bmentor(ship|s|ing)?\b|learning|grow(th)?", text, re.I):
            out.append(("mentorship", 3))
        elif v == "Remote or flexible" and re.search(r"\b(remote|hybrid|flexible)\b", " ".join(job.get("locations") or []) + " " + text[:3000], re.I):
            out.append(("flexibility", 4))
    return out


def _scoring_settings(patch: dict | None = None) -> dict:
    s = db.get_settings() | (patch or {})
    ans = profile.answers()
    s["_needs_sponsorship"] = (ans.get("needs_sponsorship", {}).get("value") or "").lower() == "yes"
    s["_citizen"] = (ans.get("us_citizen", {}).get("value") or "").lower() == "yes"
    return s


def preview(patch: dict) -> dict:
    """How many matches these choices would give, without saving them: setup's live "N matches". Counts open roles
    not yet applied to, skipped or left out, at or above the fit bar."""
    s = _scoring_settings(patch)
    vocab, bias = profile_vocab(), _learned_company_bias()
    bar = float(s.get("min_fit_score") or 40)
    rows = db.q("""SELECT * FROM jobs WHERE active=1 AND status NOT IN ('submitted','skipped','left_out')
                   AND verdict IS NULL""")
    n, outside = 0, {"level": 0, "role": 0, "place": 0, "age": 0}
    for r in rows:
        j = db.decode(r)
        why = scope(j, s)
        for w in why:
            key = ("level" if w.startswith("not your level") or w.startswith("not an intern") or w.startswith("not your season")
                   else "role" if w.startswith("not a role") else "age" if w.startswith("posted") else "place")
            outside[key] += 1
        if not why and score_job(j, s, vocab, bias)[0] >= bar:
            n += 1
    return {"matches": n, "open": len(rows), "outside": outside, "bar": bar}


def rescore(job_ids: list[str] | None = None) -> int:
    s = _scoring_settings()
    ans = profile.answers()
    vocab = profile_vocab()
    bias = _learned_company_bias()
    if job_ids:
        rows = [db.q1("SELECT * FROM jobs WHERE id=?", (j,)) for j in job_ids]
    else:
        rows = db.q("SELECT * FROM jobs WHERE active=1")
    n = 0
    with db.tx() as c:
        for r in rows:
            if not r:
                continue
            j = db.decode(r)
            sc, why = score_job(j, s, vocab, bias)
            el = eligibility.check(j, ans)
            if not el["ok"]:
                sc = max(0.0, sc - 40)
                why.append("- you may not qualify: " + "; ".join(el["reasons"]))
            c.execute("UPDATE jobs SET fit_score=?, fit_reasons=?, eligibility=? WHERE id=?",
                      (sc, json.dumps(why), json.dumps(el), j["id"]))
            n += 1
    return n


CATEGORY_WORDS = [
    ("Hardware", r"hardware|rtl|asic|fpga|verification|\bdv\b|firmware|embedded|silicon|circuit|electrical|si/pi|"
                 r"physical design|analog|pcb|chip"),
    ("AI/ML/Data", r"machine learning|\bml\b|\bai\b|data|inference|research scientist|deep learning|vision|nlp"),
    ("Quant", r"quant|trading|trader"),
    ("Product", r"product manag|\bpm\b|product design"),
    ("Software", r"software|engineer|developer|infrastructure|backend|frontend|full.?stack|platform|devops|sre"),
]


def guess_category(title: str) -> str:
    t = (title or "").lower()
    for cat, pat in CATEGORY_WORDS:
        if re.search(pat, t):
            return cat
    return ""
