"""Limits autopilot works inside: how many applications it sends a day and to one company in a week.

Every submission counts toward the caps, yours included, so "12 of 20 today" means what it says. The caps only
stop autopilot: you can always submit an application yourself."""
from __future__ import annotations

import json
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
    return company_limit_reason(job)


# --------------------------------------------------------------------------- limits a company states
# Some employers cap how often you may apply ("Candidates may submit up to 5 applications during any rolling 30-day
# period") or when you may apply again ("may not reapply to the same role ... within 90 days of receiving a
# rejection"). Read from their postings, kept per company, and checked next to your own caps: whichever is
# stricter stops autopilot.
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "sixty": 60,
                "ninety": 90}
UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
_N = r"(\d{1,3}|" + "|".join(NUMBER_WORDS) + r")"
_SPAN = rf"(?:{_N}[- ]?(day|week|month|year)s?|(day|week|month|year))"
_CAP = r"(?:up to|no more than|a maximum of|maximum of|at most|limit(?:ed)? (?:of |to )?)"
PER_WINDOW = re.compile(
    rf"(?:{_CAP}\s*{_N}\s+(?:job\s+)?applications?|apply (?:to|for)\s+{_CAP}\s*{_N}\s+(?:roles|positions|jobs|openings))"
    rf"\b[^.;]{{0,40}}?\b(?:during|in|within|per|every|each|over|for)\s+"
    rf"(?:any|a|an|each|every|one|the)?\s*(?:rolling|calendar|consecutive)?\s*{_SPAN}", re.I)
REAPPLY = re.compile(
    rf"(?:\bnot\b|n't|\bcannot\b|\bunable to\b)[^.;]{{0,30}}?\bre-?apply\b[^.;]{{0,120}}?\b(?:within|for)\s+"
    rf"{_N}[- ]?(day|week|month)s?\b[^.;]{{0,40}}?\breject", re.I)
REAPPLY_WAIT = re.compile(
    rf"\bwait\s+(?:at least\s+)?{_N}[- ]?(day|week|month)s?\s+(?:after|following|from)\s+[^.;]{{0,30}}?reject", re.I)
WHILE_ACTIVE = re.compile(
    r"(?:\bnot\b|n't|\bcannot\b)[^.;]{0,30}?\bre-?apply\b[^.;]{0,60}?\bwhile\s+(?:an?|your|their)\s+"
    r"(?:application|candidacy)\s+(?:is|remains)\s+(?:active|open|under review|in process|being considered)", re.I)


# A limit is a rule for applicants: its sentence talks to or about them ("Candidates may…", "You can…").
FOR_APPLICANTS = re.compile(r"\b(candidates?|applicants?|you|your|per (?:candidate|person|applicant))\b", re.I)


def _num(s: str) -> int:
    return int(s) if s.isdigit() else NUMBER_WORDS[s.lower()]


def _sentence(text: str, m: re.Match) -> str:
    """The sentence (or list item) a match is in, as the posting wrote it."""
    start = max(text.rfind(c, 0, m.start()) for c in ".\n•;") + 1
    ends = [i for i in (text.find(c, m.end()) for c in ".\n") if i >= 0]
    return " ".join(text[start:(min(ends) + 1) if ends else len(text)].split())


def read_limits(text: str) -> dict:
    """The application limits a posting states, if any: {"windows": [[per, days], …], "reapply_days",
    "while_active", "lines"}. Every window is kept ("2 a day" and "5 a month" both hold)."""
    out: dict = {"lines": []}
    text = text or ""
    windows = []
    for m in PER_WINDOW.finditer(text):
        line = _sentence(text, m)
        if not FOR_APPLICANTS.search(line):
            continue
        n, k, unit, bare = m.group(1) or m.group(2), m.group(3), m.group(4), m.group(5)
        w = [_num(n), _num(k) * UNIT_DAYS[unit.lower()] if k else UNIT_DAYS[bare.lower()]]
        if w not in windows:
            windows.append(w)
        if line not in out["lines"]:
            out["lines"].append(line)
    if windows:
        out["windows"] = sorted(windows, key=lambda w: w[1])
    m = REAPPLY.search(text) or REAPPLY_WAIT.search(text)
    if m:
        out["reapply_days"] = _num(m.group(1)) * UNIT_DAYS[m.group(2).lower()]
        out["lines"].append(_sentence(text, m))
    m = WHILE_ACTIVE.search(text)
    if m:
        out["while_active"] = True
        if _sentence(text, m) not in out["lines"]:
            out["lines"].append(_sentence(text, m))
    return out if len(out) > 1 else {}


def merge_limits(a: dict, b: dict) -> dict:
    """Two statements of a company's limits together: every window and line, the longer reapply wait. Limits only
    add up, so no posting (or the order they're read in) can loosen what another said."""
    if not a or not b:
        return a or b
    windows = sorted({tuple(w) for w in a.get("windows", []) + b.get("windows", [])}, key=lambda w: w[1])
    out = {"lines": a["lines"] + [x for x in b["lines"] if x not in a["lines"]]}
    if windows:
        out["windows"] = [list(w) for w in windows]
    if a.get("reapply_days") or b.get("reapply_days"):
        out["reapply_days"] = max(a.get("reapply_days") or 0, b.get("reapply_days") or 0)
    if a.get("while_active") or b.get("while_active"):
        out["while_active"] = True
    return out


def note_limits(company: str, text: str, job_id: str | None = None, found: dict | None = None) -> dict:
    """Keep what this posting (or `found`, already read) says about the company's limits, added to what its other
    postings said. A posting that says nothing changes nothing."""
    found = found if found is not None else read_limits(text)
    key = (company or "").strip().lower()
    if not found or not key or key.startswith("("):
        return found
    old = db.q1("SELECT * FROM company_limits WHERE company=?", (key,))
    kept = {}
    if old:
        kept = {"lines": json.loads(old["lines"]), "windows": json.loads(old["windows"])}
        if old["reapply_days"]:
            kept["reapply_days"] = old["reapply_days"]
        if old["while_active"]:
            kept["while_active"] = True
    both = merge_limits(kept, found)
    db.x("""INSERT INTO company_limits(company, name, windows, reapply_days, while_active, lines, job_id, updated_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(company) DO UPDATE SET name=excluded.name, windows=excluded.windows,
            reapply_days=excluded.reapply_days, while_active=excluded.while_active, lines=excluded.lines,
            job_id=excluded.job_id, updated_at=excluded.updated_at""",
         (key, company.strip(), db.enc(both.get("windows", [])), both.get("reapply_days"),
          int(bool(both.get("while_active"))), db.enc(both["lines"]), job_id, db.now()))
    return found


_scanned = False


def _scan_saved_postings() -> None:
    """Once per run: read the limits in postings saved before Jobsmith looked for them."""
    global _scanned
    if _scanned:
        return
    _scanned = True
    for r in db.q("""SELECT id, company, description FROM jobs WHERE description LIKE '%appl%'
                     AND (description LIKE '%applications%' OR description LIKE '%reapply%'
                          OR description LIKE '%re-apply%' OR description LIKE '%apply to%')
                     ORDER BY updated_at"""):
        note_limits(r["company"], r["description"], r["id"])


def company_limits(company: str) -> dict | None:
    """What this company has said about how often you may apply, or None."""
    _scan_saved_postings()
    row = db.q1("SELECT * FROM company_limits WHERE company=?", ((company or "").strip().lower(),))
    return dict(row, lines=json.loads(row["lines"]), windows=json.loads(row["windows"])) if row else None


def company_used(company: str, days: int) -> int:
    """Applications to this company in the last `days` days, yours included."""
    return len(_submitted_since(time.time() - days * 86400, company) | _in_flight(company))


def company_room(company: str) -> int | None:
    """How many more applications the company's own limits allow right now; None when it states none."""
    lim = company_limits(company)
    if not lim or not lim["windows"]:
        return None
    return min(per - company_used(company, days) for per, days in lim["windows"])


def _per(days: int) -> str:
    return "per day" if days == 1 else f"per {days} days"


def limit_note(company: str) -> str | None:
    """"Figma allows 5 per 30 days — 2 used", for the match. A company that only limits reapplying says that."""
    lim = company_limits(company)
    if not lim:
        return None
    if lim["windows"]:
        return f"{lim['name']} allows " + ", ".join(
            f"{per} {_per(days)} — {company_used(company, days)} used" for per, days in lim["windows"])
    if lim.get("reapply_days"):
        return f"{lim['name']}: no reapplying to a role within {lim['reapply_days']} days of a rejection"
    if lim.get("while_active"):
        return f"{lim['name']}: no reapplying to a role while an application to it is open"
    return None


def _day(t: float) -> str:
    lt = time.localtime(t)
    return f"{time.strftime('%b', lt)} {lt.tm_mday}"


def _same_role(job: dict) -> list[dict]:
    """Your other applications to this role (same company, same title): sent, or being submitted in another tab
    right now (sent_at None)."""
    from . import outcomes
    if not (job.get("company") or "").strip() or not (job.get("title") or "").strip():
        return []
    outcomes._ensure()
    args = (job.get("company") or "", job.get("title") or "")
    same = "lower(trim(j.company))=lower(trim(?)) AND lower(trim(j.title))=lower(trim(?))"
    # rejected_at: when the latest word on it was a rejection (a later interview means it's open again; a "we got
    # your application" email says nothing either way)
    rows = db.q(f"""SELECT j.id, j.title, j.outcome, MAX(r.finished_at) sent_at,
                          (SELECT CASE WHEN o.kind='rejected' THEN o.received_at END FROM outcomes o
                           WHERE o.job_id=j.id AND o.kind!='received' ORDER BY o.received_at DESC LIMIT 1) rejected_at,
                          (SELECT COUNT(*) FROM outcomes o WHERE o.job_id=j.id AND o.kind!='received') heard
                   FROM jobs j JOIN runs r ON r.job_id=j.id AND r.kind='submit' AND r.status IN ('done','unconfirmed')
                   WHERE {same} GROUP BY j.id""", args)
    sent = {r["id"] for r in rows}
    flying = [i for i in _submitting if i not in sent]
    if flying:
        marks = ",".join("?" * len(flying))
        rows += [dict(r, outcome=None, sent_at=None, rejected_at=None, heard=0) for r in db.q(
            f"SELECT j.id, j.title FROM jobs j WHERE j.id IN ({marks}) AND {same}", (*flying, *args))]
    return [r for r in rows if r["id"] != job.get("id")]


def company_limit_reason(job: dict) -> str | None:
    """Why the company's own stated limits stop autopilot on this application now, or None."""
    lim = company_limits(job.get("company") or "")
    if not lim:
        return None
    name, others = lim["name"], {job.get("id")}
    for per, days in lim["windows"]:
        n = len((_submitted_since(time.time() - days * 86400, job["company"]) | _in_flight(job["company"])) - others)
        if n >= per:
            return (f"{name} allows {per} applications {_per(days)}, and {n} have gone to {name} in the last "
                    f"{'day' if days == 1 else f'{days} days'}. Autopilot waits until there's room again.")
    for prev in _same_role(job):
        # From the emails: the latest one decides (the job's outcome keeps the furthest stage, so a rejection after
        # an interview doesn't show there). With none, a rejection you marked yourself.
        rejected = prev["rejected_at"] if prev["heard"] else (prev["sent_at"] if prev["outcome"] == "rejected" else None)
        if rejected and lim.get("reapply_days"):
            when = rejected
            if when >= time.time() - lim["reapply_days"] * 86400:
                return (f"{name} doesn't take a new application to the same role within {lim['reapply_days']} days "
                        f"of a rejection, and your application to {prev['title']} was turned down "
                        f"{_day(when)}.")
        elif not rejected and lim.get("while_active") and prev["outcome"] != "offer":
            when = f"on {_day(prev['sent_at'])}" if prev["sent_at"] else "and it's being sent right now"
            return (f"{name} doesn't take a new application to a role while one to it is open, and you applied to "
                    f"{prev['title']} {when}.")
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
    run_id = db.x("INSERT INTO runs(job_id, kind, status, log, started_at, finished_at) VALUES(?,?,?,?,?,?)",
                  (job_id, "submit", "unconfirmed", why, db.now(), db.now()))
    from . import audit
    audit.record(job_id, run_id, "autopilot")             # what it may have sent, in case it did
    db.x("UPDATE jobs SET status='filled', error=NULL, hold_reason=?, updated_at=? WHERE id=?",
         ("Autopilot clicked Submit but never saw a confirmation page. Check your email or the site to see if it "
          f"went through ({why}).", db.now(), job_id))
    _submitting.discard(job_id)
    return True


# --------------------------------------------------------------------------- supervised first runs
# Autopilot's first real submission, and its first on each job site, stops at the filled form: you see every answer
# and where it came from, and it's sent only when you approve it. After that, autopilot submits on that site on its
# own within the caps. (The practice copy keeps its own data folder, so approvals there never carry over.)
SITE_NAMES = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workday": "Workday",
              "icims": "iCIMS", "smartrecruiters": "SmartRecruiters", "oracle": "Oracle", "workable": "Workable",
              "eightfold": "Eightfold", "rippling": "Rippling", "jobvite": "Jobvite", "taleo": "Taleo",
              "successfactors": "SuccessFactors"}


def site_of(job: dict) -> str:
    """The job site an application goes through: the tracking system's name, or the host for any other site."""
    from urllib.parse import urlparse
    from . import ats
    url = job.get("referral_url") or job.get("url") or ""
    name = ats.detect(url) if url else "other"
    if name == "other" and job.get("ats") and job["ats"] != "other":
        name = job["ats"]                     # what it was added as (a saved copy of the form has a file:// url)
    if name != "other":
        return name
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.") or "other"


def site_name(site: str) -> str:
    return SITE_NAMES.get(site, site)


def first_run_reason(job: dict) -> str | None:
    """Why autopilot needs your approval before sending this one, or None once you've approved one on its site."""
    site = site_of(job)
    approved = {r["site"] for r in db.q("SELECT DISTINCT site FROM first_runs WHERE approved_at IS NOT NULL")}
    if site in approved:
        return None
    first = "This is autopilot's first submission" if not approved else \
        f"This is autopilot's first submission on {site_name(site)}"
    return (f"{first}: check every answer and where it came from, then approve it to send it. After that, "
            f"autopilot submits on {site_name(site)} on its own within your limits.")


def ask_approval(job_id: str, site: str, files: list[str] | None = None) -> bool:
    """Hold it for you, noting the files the fill attached (`files`, from when it started; default: as they are
    now). True when you'd approved different answers for it before (the form changed since)."""
    import json
    before = db.q1("SELECT answers FROM first_runs WHERE job_id=? AND approved_at IS NULL", (job_id,))
    db.x("""INSERT OR REPLACE INTO first_runs(job_id, site, asked_at, approved_at, answers, files)
            VALUES(?,?,?,NULL,NULL,?)""", (job_id, site, db.now(), json.dumps(files if files is not None else _files())))
    return bool(before and before["answers"])


def _files() -> list[str]:
    """The resume and transcript as they are now, by content: replacing one means checking it again."""
    import hashlib
    from . import profile
    out = []
    for f in (profile.attachment_file(), profile.transcript_file()):
        try:
            out.append(hashlib.sha256(f.read_bytes()).hexdigest() if f else "")
        except OSError:
            out.append("unreadable")
    return out


def answers_key(fields: list[dict], files: list[str] | None = None) -> str:
    """What you approved, to compare with a later fill: each field and the answer put in it, and the files (as they
    were when it was filled, or as they are now)."""
    import json
    return json.dumps({"fields": sorted((f["field"], f.get("answer") or "") for f in fields),
                       "files": files if files is not None else _files()})


def approve_answers(job_id: str, fields: list[dict]) -> None:
    """You approved these answers but the tab had closed: a refill that puts in exactly these, with the same files
    it was filled with, may be sent."""
    import json
    row = db.q1("SELECT files FROM first_runs WHERE job_id=? AND approved_at IS NULL", (job_id,))
    files = json.loads(row["files"]) if row and row["files"] else ["unknown"]
    db.x("UPDATE first_runs SET answers=? WHERE job_id=? AND approved_at IS NULL",
         (answers_key(fields, files), job_id))


def approved_answers(job_id: str) -> str | None:
    row = db.q1("SELECT answers FROM first_runs WHERE job_id=? AND approved_at IS NULL", (job_id,))
    return row and row["answers"]


def awaiting_approval(job_id: str | None = None) -> list[dict]:
    """Applications filled and waiting for you to approve autopilot's first submission (on their site)."""
    sql = """SELECT f.job_id, f.site, f.asked_at, j.company, j.title FROM first_runs f JOIN jobs j ON j.id=f.job_id
             WHERE f.approved_at IS NULL AND j.status='filled'"""
    rows = db.q(sql + (" AND f.job_id=?" if job_id else "") + " ORDER BY f.asked_at", (job_id,) if job_id else ())
    return [dict(r, site_name=site_name(r["site"])) for r in rows]


def approve(job_id: str) -> str | None:
    """You approved it: its site is trusted from now on. Returns the site, or None if nothing was waiting."""
    row = db.q1("SELECT site FROM first_runs WHERE job_id=? AND approved_at IS NULL", (job_id,))
    if not row:
        return None
    db.x("UPDATE first_runs SET approved_at=? WHERE job_id=?", (db.now(), job_id))
    return row["site"]


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


# --------------------------------------------------------------------------- the fit gate
def fit_gate(job: dict, threshold: float | None = None) -> dict:
    """Whether autopilot would apply to this match on fit alone, and why, in words for the match's page."""
    if threshold is None:
        threshold = float(db.get_setting("min_fit_score") or 40)
    score = job.get("fit_score")
    reasons = job.get("fit_reasons") or []
    if isinstance(reasons, str):
        import json
        reasons = json.loads(reasons or "[]")
    plus = [r[2:] for r in reasons if r.startswith("+ ")]
    minus = [r[2:] for r in reasons if r.startswith("- ")]
    passed = score is not None and score >= threshold
    import math
    s, t = (round if passed else math.floor)(score or 0), round(threshold)   # never "40 is under your bar of 40"
    summary = (f"Fit {s} clears your bar of {t}: autopilot applies." if passed else
               "Not scored yet: autopilot waits until it is." if score is None else
               f"Fit {s} is under your bar of {t}: autopilot skips it. Apply yourself if you want it.")
    return {"passed": passed, "score": score, "threshold": threshold, "summary": summary,
            "for": plus, "against": minus}
