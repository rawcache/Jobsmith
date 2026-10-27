"""Limits autopilot works inside: how many applications it sends a day and to one company in a week.

Every submission counts toward the caps, yours included, so "12 of 20 today" means what it says. The caps only
stop autopilot: you can always submit an application yourself."""
from __future__ import annotations

import re
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


# --------------------------------------------------------------------------- employer AI policies
# Some employers ask applicants not to use AI or automated tools. Autopilot never sends those on its own: they wait
# under Needs you with the employer's own words. A sentence must say *don't* (or "will be rejected") and name AI or
# automation, so a posting for an AI job ("experience with generative AI tools") doesn't trip it.
_AI = (r"(?:(?-i:AI|A\.I\.|GenAI|LLMs?)|artificial intelligence|chat ?gpt|gpt-?\d*|large language models?|"
       r"generative(?: ai)?(?: tools?)?|gen ?ai|claude|gemini|copilot|bots?|auto-?appl(?:y|ies|ying)\w*|"
       r"auto-?fill\w*|automat(?:ed|ion)(?: \w+)?(?: tools?| software| means| systems?| services?| scripts?| "
       r"programs?| applications?| submissions?| responses?)?)")
_W = r"(?:[\w'’,-]+ ){0,4}?"
AI_POLICY = [re.compile(p, re.I) for p in (
    # "Please do not use AI tools to …", "without the help of ChatGPT", "refrain from using generative AI"
    rf"\b(?:do not|don['’]t|must not|may not|should not|shall not|cannot|can not|never|refrain from|avoid|"
    rf"(?:are|is) not (?:permitted|allowed) to|prohibited from|without)\s+{_W}(?:use|using|rely(?:ing)? on|"
    rf"submit(?:ting)?|the (?:use|help|aid|assistance) of|help of|assistance (?:of|from))\s+{_W}{_AI}\b",
    # "The use of AI … is prohibited / not permitted / grounds for disqualification"
    rf"\b(?:use|usage) of {_W}{_AI}\b.{{0,80}}?\b(?:is|are|will be)\s+(?:strictly )?(?:not (?:permitted|allowed|"
    rf"accepted)|prohibited|forbidden|banned|grounds for|disqualif\w*)",
    # "AI-generated responses will be rejected", "Applications written with AI will not be considered"
    rf"\b{_AI}[- ](?:generated|written|assisted|created|produced)\b.{{0,80}}?\b(?:will|may|are|is)\s+(?:not be "
    rf"(?:considered|accepted|reviewed)|be (?:rejected|disqualified|removed|discarded|flagged)|not (?:accepted|"
    rf"permitted|allowed)|prohibited)",
    rf"\b(?:submitted|completed|filled out|written|generated|created) (?:by|with|using|through) {_W}{_AI}\b.{{0,80}}?"
    rf"\b(?:will|may)\s+(?:not be (?:considered|accepted|reviewed)|be (?:rejected|disqualified|removed|discarded))",
    # "Answers must not be generated by AI", certification boxes: "I did not use AI to write my answers"
    rf"\b(?:not|never) (?:be )?(?:generated|written|created|produced|completed) {_W}(?:by|with|using) {_W}{_AI}\b",
    rf"\b(?:did not|didn['’]t|have not|haven['’]t|will not|won['’]t) {_W}(?:use|used) {_W}{_AI}\b",
    rf"\bno {_AI}(?:[- ](?:generated|written|assisted))? (?:applications?|responses?|answers?|submissions?|"
    rf"content|tools?|assistance|help)\b",
)]
# Sentences end at . ! ? or a blank line; a single line break is just a wrapped line.
_SENT = re.compile(r"(?<=[.!?])\s+|\n\s*\n")
_BLOCK = re.compile(r"<(?:/p|/li|/h\d|/div|/tr|/td)\s*>", re.I)      # <br> is only a wrapped line
# The employer describing what it does ("We do not use AI to screen applications", "Our recruiters never use AI")
# isn't a rule for you: its own side is the subject and the verb describes rather than instructs. "Must not",
# "may not" and "should not" are rules whoever the subject is. When it's unclear, it holds: a needless hold costs
# you one click, a missed rule sends an application the employer asked not to get. So "they" never excuses one:
# it's as often the applicants ("certify that they did not use AI") as the employer.
_THEM = re.compile(r"\b(?:we|our (?:company|team|recruiters?|recruiting team|hiring team|talent team|"
                   r"interviewers|hiring managers|reviewers|employees|staff|people|process|systems?|tools)|"
                   r"the company|recruiters)\s*$", re.I)
_DESCRIBES = re.compile(r"(?:do not|don['’]t|does not|doesn['’]t|never|will not|won['’]t|did not|didn['’]t)\b", re.I)


def _plain(text: str) -> str:
    import html
    text = _BLOCK.sub("\n\n", text or "")
    return html.unescape(re.sub(r"<[^>]+>", " ", text)).replace("\xa0", " ")


def _applies_to_you(s: str) -> bool:
    for p in AI_POLICY:
        for m in p.finditer(s):
            if _THEM.search(s[:m.start()]) and _DESCRIBES.match(m.group(0)):
                continue
            return True
    return False


def ai_policy(text: str) -> str | None:
    """The employer's sentence asking applicants not to use AI or automated tools, or None."""
    for sent in _SENT.split(_plain(text)):
        s = " ".join(sent.split())
        if s and _applies_to_you(s):
            return s if len(s) <= 300 else s[:297].rsplit(" ", 1)[0] + "…"
    return None


def policy_reason(job: dict, page_text: str = "") -> str | None:
    """Why autopilot won't send this one on its own because of the employer's AI policy, or None. Reads the
    posting, the form's questions and (when filling) the page itself."""
    qs = job.get("questions") or []
    if isinstance(qs, str):
        import json
        qs = json.loads(qs or "[]")
    form = "\n\n".join(f"{q.get('label', '')}\n\n{q.get('description', '')}" for q in qs if isinstance(q, dict))
    # A page's text (the browser's innerText) breaks lines only between blocks, so each line stands alone there.
    # (tried first for a clean quote); a <br> inside a sentence shows as a line break too, so then joined.
    for text in (job.get("description") or "", form, re.sub(r"\n", "\n\n", page_text or ""), page_text or ""):
        line = ai_policy(text)
        if line:
            return (f"{(job.get('company') or 'This employer').strip()} asks applicants not to use AI or automated "
                    f"tools: \"{line}\" Autopilot won't send it. Review it and submit it yourself if you're "
                    "comfortable.")
    return None
