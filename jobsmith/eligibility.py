"""Can you actually get this job? Hard requirements, checked before Jobsmith spends an application on it.

Only clear, stated requirements count: a role that *prefers* a PhD isn't a blocker, one that *requires*
US citizenship is. Everything here is regex over the title, the job list's sponsorship note and the
posting, so it's free and explainable. Nothing is guessed: if the posting doesn't say, it passes.
"""
from __future__ import annotations

import re
import time

from . import profile

SENIOR = re.compile(r"\b(senior|sr\.?|staff|principal|lead|director|head of|manager|vp|architect)\b", re.I)
JUNIOR_OK = re.compile(r"\b(intern|internship|co-?op|new grad|graduate|entry|junior|apprentice|university|early career|student)\b", re.I)

CITIZEN_REQ = re.compile(
    r"(must be a|requires?|required:?|only)\s+(a\s+)?u\.?s\.?\s+(citizen|citizenship|person)|"
    r"u\.?s\.?\s+citizenship\s+(is\s+)?(required|mandatory)|"
    r"citizenship\s+is\s+required|us citizens only", re.I)
CLEARANCE_ACTIVE = re.compile(r"\b(active|current)\s+(dod\s+)?(secret|top secret|ts/sci|ts|security)\s+clearance", re.I)
CLEARANCE_OBTAIN = re.compile(r"(ability|able|eligible|eligibility)\s+to\s+(obtain|acquire|get|hold)\s+(and\s+maintain\s+)?(a\s+)?"
                              r"(u\.?s\.?\s+)?(government\s+)?(security\s+)?(secret|top secret|ts/sci|security)?\s*clearance", re.I)
NO_SPONSOR = re.compile(r"(will not|won'?t|cannot|can'?t|unable to|does not|do not|not able to)\s+(provide\s+|offer\s+)?"
                        r"(visa\s+)?sponsor|no\s+(visa\s+)?sponsorship|without\s+(the\s+)?(need\s+for\s+)?(visa\s+)?sponsorship|"
                        r"not\s+offer\s+sponsorship|sponsorship\s+(is\s+)?not\s+available", re.I)
PHD_REQ = re.compile(r"(currently\s+)?(pursuing|enrolled\s+in|working\s+towards?)\s+(a\s+)?(phd|ph\.d\.?|doctoral|doctorate)", re.I)
MASTERS_REQ = re.compile(r"(currently\s+)?(pursuing|enrolled\s+in)\s+(a\s+)?(master'?s|ms|m\.s\.)\s+(degree|program|in)", re.I)
UNDERGRAD_OK = re.compile(r"bachelor'?s|b\.s\.|bs/ms|undergrad|bs,|bs or|bs in", re.I)
YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:or more\s+|plus\s+)?years?['’]?\s+(?:of\s+)?(?:professional\s+|industry\s+|relevant\s+|"
                   r"full[- ]time\s+|hands[- ]on\s+|work\s+)*experience", re.I)
GRAD_WINDOW = re.compile(r"graduat\w*\s+(?:date\s+)?(?:between|from|in|by|during)?\s*"
                         r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?(20\d\d)"
                         r"(?:\s*(?:and|-|–|to|through)\s*(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?(20\d\d))?",
                         re.I)


def _yes(v: str) -> bool:
    return (v or "").strip().lower() in ("yes", "y", "true")


def _no(v: str) -> bool:
    return (v or "").strip().lower() in ("no", "n", "false", "none")


def check(job: dict, ans: dict | None = None) -> dict:
    """{'ok': bool, 'reasons': [...why you can't], 'notes': [...worth knowing]}"""
    ans = ans if ans is not None else profile.answers()
    v = lambda k: (ans.get(k) or {}).get("value", "")
    title = job.get("title") or ""
    text = f"{title}\n{job.get('sponsorship') or ''}\n{job.get('description') or ''}"
    reasons: list[str] = []
    notes: list[str] = []

    grad_year = None
    try:
        grad_year = int(re.search(r"20\d\d", v("graduation_year") or v("graduation_date") or "").group(0))
    except Exception:
        pass
    still_student = grad_year is not None and grad_year >= time.localtime().tm_year

    # seniority: a student shouldn't spend applications on senior or manager roles
    if still_student and SENIOR.search(title) and not JUNIOR_OK.search(title):
        reasons.append(f"Senior role ({SENIOR.search(title).group(0)}) and you're still a student")

    # citizenship and clearance
    if CITIZEN_REQ.search(text) and _no(v("us_citizen")):
        reasons.append("Requires US citizenship")
    if CLEARANCE_ACTIVE.search(text) and (_no(v("security_clearance")) or not v("security_clearance")):
        reasons.append("Requires an active security clearance")
    elif CLEARANCE_OBTAIN.search(text):
        if _no(v("us_citizen")):
            reasons.append("Requires being able to get a security clearance (usually US citizens only)")
        else:
            notes.append("You'd need to get a security clearance")

    # sponsorship
    if _yes(v("needs_sponsorship")) and NO_SPONSOR.search(text):
        reasons.append("Doesn't sponsor visas, and you need sponsorship")

    # degree level
    degree = (v("degree") or "").lower()
    has_grad_degree = any(w in degree for w in ("master", "ms", "m.s", "phd", "ph.d", "doctor"))
    if PHD_REQ.search(text) and "phd" not in degree.replace(".", "") and not UNDERGRAD_OK.search(text) \
            and not re.search(r"master'?s\s+or|or\s+(a\s+)?master", text, re.I):
        reasons.append("For PhD students")
    elif MASTERS_REQ.search(text) and not has_grad_degree and not UNDERGRAD_OK.search(text):
        reasons.append("For master's students")

    # graduation window (internships and new grad roles state these a lot)
    if grad_year:
        for m in GRAD_WINDOW.finditer(text):
            lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
            if lo > hi:
                lo, hi = hi, lo
            if hi - lo <= 4 and not (lo <= grad_year <= hi):
                reasons.append(f"Wants graduates from {lo}" + (f" to {hi}" if hi != lo else "") + f"; you graduate in {grad_year}")
                break

    # years of experience
    need = max((int(m.group(1)) for m in YEARS.finditer(text) if int(m.group(1)) < 30), default=0)
    if need and still_student:
        if need >= 3:
            reasons.append(f"Asks for {need}+ years of experience")
        elif need == 2:
            notes.append("Asks for 2 years of experience")
    return {"ok": not reasons, "reasons": reasons, "notes": notes}
