"""Ask Jobsmith about your job hunt in plain words, with no AI.

    "in the past few hours, which companies did you apply to and what is waiting for me to send?"

Every answer is a lookup in Jobsmith's own records, so it's instant, offline, and never wrong about what happened.
A question is split into parts ("...and what is waiting for me..."), each part is matched to one or more topics
(applied, waiting on you, replies, interviews, matches...), and a time window ("past few hours", "this week") and
company ("at NVIDIA") found anywhere in the question apply to every part. Questions it can't read get examples of
ones it can, never a guess.

answer(text) yields blocks one at a time, so the terminal can show them as they come:
    {"t": "head", "text": "Applied in the past 6 hours"}
    {"t": "item", "text": "Acme Robotics", "meta": "Robotics Software Intern · 2:14 PM", "job_id": "..."}
    {"t": "note", "text": "Nothing yet. The last one was Globex, 3 days ago."}
    {"t": "hint", "text": "/review goes through them one by one"}
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
from typing import Iterator

from . import db, network

EXAMPLES = [
    "what did you apply to today?",
    "in the past few hours, which companies did you apply to and what is waiting for me to send?",
    "what needs me?",
    "any replies this week?",
    "do I have interviews?",
    "what are my best matches?",
    "how many applications this month?",
    "who do I know at Acme Robotics?",
    "what's running right now?",
    "which follow-ups are due?",
    "what did you answer for Globex?",
    "what failed?",
]

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10, "a": 1, "an": 1}
UNIT = {"min": 60, "minute": 60, "hour": 3600, "hr": 3600, "day": 86400, "week": 7 * 86400, "month": 30 * 86400}


# --------------------------------------------------------------------------- time windows
def window(text: str, now: float | None = None) -> tuple[float | None, float | None, str]:
    """(since, until, how to say it) for the time the question asks about, or (None, None, '') for all time."""
    now = now or db.now()
    t = text.lower()
    local = dt.datetime.fromtimestamp(now)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    m = re.search(r"\b(?:past|last|previous)\s+(few|couple(?: of)?|several|\d+|one|two|three|four|five|six|seven|ten|a|an)?\s*"
                  r"(min(?:ute)?|hours?|hrs?|days?|weeks?|months?)\b", t)
    if m:
        qty, unit = m.group(1) or "1", re.sub(r"s$", "", m.group(2))
        unit = "minute" if unit == "min" else unit
        if qty in ("few", "several"):
            n = {"few": 6 if unit == "hour" else 3, "several": 8 if unit == "hour" else 5}[qty]
        elif qty.startswith("couple"):
            n = 3 if unit == "hour" else 2
        elif qty.isdigit():
            n = int(qty)
        else:
            n = WORDS.get(qty, 1)
        word = {"minute": "minute", "hour": "hour", "hr": "hour", "day": "day", "week": "week", "month": "month"}[unit]
        if m.group(1) is None and word == "week" and re.search(r"\blast week\b", t):
            pass                                            # "last week" = the calendar week before this one
        else:
            return now - n * UNIT[word], None, f"in the past {n} {word}{'s' if n != 1 else ''}" if n != 1 else f"in the past {word}"
    if re.search(r"\btoday\b|\bthis morning\b|\btonight\b|\bso far\b", t):
        return midnight, None, "today"
    if re.search(r"\byesterday\b", t):
        return midnight - 86400, midnight, "yesterday"
    monday = midnight - local.weekday() * 86400
    if re.search(r"\bthis week\b", t):
        return monday, None, "this week"
    if re.search(r"\blast week\b", t):
        return monday - 7 * 86400, monday, "last week"
    if re.search(r"\bthis month\b", t):
        return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp(), None, "this month"
    if re.search(r"\b(recently|lately)\b", t):
        return now - 3 * 86400, None, "in the past 3 days"
    m = re.search(r"\bsince (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
    if m:
        wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(m.group(1))
        back = (local.weekday() - wd) % 7
        return midnight - back * 86400, None, f"since {m.group(1).title()}"
    return None, None, ""


# --------------------------------------------------------------------------- what the question is about
TOPICS: list[tuple[str, str]] = [
    ("help", r"^\s*(help|\?|what can (you|i) (ask|do|say)|how do i use)"),
    ("waiting", r"(waiting|left|need|have|got|ready)\b.{0,25}\b(me|i)\b.{0,20}\b(send|submit|approve|review|do|finish)|"
                r"\bto send\b|\bfor me to\b|ready to (send|submit)|unsent|haven'?t sent|not (been )?sent|my turn|on my plate|"
                r"\bneeds? (me|my|you)\b|waiting on me|attention|\bheld\b|on hold|\bpending\b|to[- ]?do"),
    ("codes", r"\bcodes?\b|verification|captcha|sign[- ]?ins?\b|log ?in"),
    ("answers", r"what did (you|it) (write|answer|say|put)|\banswers? (for|to|at|on)\b|cover letter|what('?s| is) in (my|the) application"),
    ("followups", r"follow[- ]?ups?|gone quiet|\bquiet\b|ghost|haven'?t heard|not heard|no (reply|response)"),
    ("replies", r"repl(y|ies|ied)|heard back|respon(se|ses|ded)|\bemails?\b|inbox|got back|news"),
    ("interviews", r"interview|assessment|\boa\b|online assessment|coding (test|challenge)|hackerrank|codesignal"),
    ("rejected", r"reject|declin|turned (me )?down|didn'?t (get|make)|\bno'?s\b"),
    ("offers", r"\boffers?\b"),
    ("people", r"who do i know|connections?|referr|\bpeople\b|contacts?|know anyone|anyone i know"),
    ("outreach", r"outreach|\bmessages?\b|\bdms?\b|drafted (notes|messages)"),
    ("failed", r"\bfail|errors?\b|broke|didn'?t work|\bstuck\b|problems?|went wrong"),
    ("running", r"right now|currently|in progress|working on|\bdoing\b|\brunning\b|\bstatus\b|autopilot|\bbusy\b"),
    ("matches", r"match|best (fit|roles?|jobs?|ones)|recommend|should i apply|new (jobs|roles|postings|openings)|"
                r"top (jobs|roles)|opportunit|\bopenings?\b|what('?s| is) out there"),
    ("stats", r"how many|\bcount\b|\btotal\b|numbers|\bstats?\b|funnel|response rate|how am i doing|how('?s| is) it going"),
    ("applied", r"\bappl(y|ied|ying|ications?)\b|\bsubmit(ted)?\b|sent (out|in|off)\b|\bwhere (did|have) (you|i)\b"),
    ("voice", r"\bvoice\b|my writing|stories|writing samples"),
    ("ai", r"\bai\b|quota|free limit|gemini|\bsmith\b|\bmodel\b"),
    ("summary", r"^\s*(what'?s (up|new|happening|going on)|summary|catch me up|recap|what did i miss|anything new|update me|brief me)"),
]


def topics(clause: str) -> list[str]:
    c = clause.lower()
    found = [name for name, rx in TOPICS if re.search(rx, c)]
    if "waiting" in found and "applied" in found and not re.search(r"\bappl(y|ied)\b|did you", c):
        found.remove("applied")                           # "waiting for me to submit" isn't asking what was sent
    if "people" in found and "outreach" in found:
        found.remove("outreach")
    if "failed" in found and "waiting" in found and "stuck" in c:
        found.remove("waiting")
    if "running" in found and len(found) > 1 and re.search(r"\bstatus\b", c) is None:
        found.remove("running")                           # "applications in progress" is about applications
    if "stats" in found and len(found) > 1 and not re.search(r"how many|\bcount\b|\btotal\b", c):
        found.remove("stats")
    if "applied" in found and "stats" in found:
        found.remove("applied")                           # "how many applications" is a count
    if "replies" in found and any(x in found for x in ("interviews", "rejected", "offers", "codes")):
        found.remove("replies")
    if "summary" in found:
        return ["summary"]
    return found


def clauses(text: str) -> list[str]:
    parts = re.split(r"\?|;|\n|\balso\b|,?\s*\band\s+(?=(?:what|which|who|how|is|are|did|do|does|any|show|list|tell|whats|what's)\b)",
                     text, flags=re.I)
    return [p.strip(" ,.") for p in parts if p and p.strip(" ,.")]


def company_in(text: str) -> str | None:
    """A company you've seen in Jobsmith, named anywhere in the question (longest name wins)."""
    t = " " + re.sub(r"[^a-z0-9&]+", " ", text.lower()) + " "
    best = None
    for r in db.q("SELECT DISTINCT company FROM jobs WHERE company != ''"):
        name = re.sub(r"[^a-z0-9&]+", " ", r["company"].lower()).strip()
        short = network.norm_company(r["company"])
        for cand in {name, short}:
            if len(cand) >= 3 and f" {cand} " in t and (not best or len(cand) > len(best[1])):
                best = (r["company"], cand)
    return best[0] if best else None


# --------------------------------------------------------------------------- formatting
def ago(ts: float | None, now: float | None = None) -> str:
    if not ts:
        return ""
    s = (now or db.now()) - ts
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86400:
        return f"{int(s // 3600)}h ago"
    if s < 7 * 86400:
        return f"{int(s // 86400)}d ago"
    d = dt.datetime.fromtimestamp(ts)
    return f"{d:%b} {d.day}"


def clock(ts: float | None) -> str:
    if not ts:
        return ""
    d = dt.datetime.fromtimestamp(ts)
    today = dt.datetime.now().date()
    hm = d.strftime("%I:%M %p").lstrip("0")         # no %-I: Windows strftime rejects it
    return hm if d.date() == today else f"{d:%a} {hm}" if (today - d.date()).days < 7 else f"{d:%b} {d.day}"


def _in(col: str, since: float | None, until: float | None, company: str | None) -> tuple[str, list]:
    where, params = [], []
    if since:
        where.append(f"{col} >= ?")
        params.append(since)
    if until:
        where.append(f"{col} < ?")
        params.append(until)
    if company:
        where.append("j.company = ?")
        params.append(company)
    return (" AND " + " AND ".join(where)) if where else "", params


def _scope(label: str, company: str | None) -> str:
    return " ".join(x for x in (f"at {company}" if company else "", label) if x)


# --------------------------------------------------------------------------- each topic
def _applied(since, until, label, company):
    w, p = _in("r.finished_at", since, until, company)
    rows = db.q(f"""SELECT j.id, j.company, j.title, j.outcome, MAX(r.finished_at) at FROM runs r JOIN jobs j ON j.id=r.job_id
                    WHERE r.kind='submit' AND r.status='done'{w} GROUP BY j.id ORDER BY at DESC LIMIT 60""", p)
    cos = list(dict.fromkeys(r["company"] for r in rows))
    yield {"t": "head", "text": f"Applied {_scope(label, company)}".strip() + (f"  {len(rows)} application{'s' if len(rows) != 1 else ''}"
                                                                                    + (f" at {len(cos)} companies" if len(cos) > 1 else "") if rows else "")}
    if not rows:
        last = db.q1("""SELECT j.company, MAX(r.finished_at) at FROM runs r JOIN jobs j ON j.id=r.job_id
                        WHERE r.kind='submit' AND r.status='done'""" + (" AND j.company=?" if company else ""), (company,) if company else ())
        yield {"t": "note", "text": "Nothing sent " + (label or "yet") + "." +
               (f" The last one was {last['company']}, {ago(last['at'])}." if last and last["at"] else "")}
        return
    for r in rows:
        yield {"t": "item", "text": r["company"], "meta": f"{r['title']} · {clock(r['at'])}" + (f" · {r['outcome']}" if r["outcome"] else ""),
               "job_id": r["id"]}


CODE_HOLD = re.compile(r"\b(emailed|verification|security) code\b", re.I)


def _only_you(attention, company) -> list[dict]:
    """Codes, CAPTCHAs and sign-ins. A filled application whose hold reason is an emailed code counts too: the tab
    asking for it may be gone (or, in the practice copy, never existed), but it still can't go on without you."""
    items = [a for a in attention if not company or a["company"] == company]
    seen = {a["job_id"] for a in items}
    for r in db.q("SELECT id, company, hold_reason FROM jobs WHERE status='filled'" + (" AND company=?" if company else "")
                  + " ORDER BY updated_at DESC", (company,) if company else ()):
        if r["id"] not in seen and CODE_HOLD.search(r["hold_reason"] or ""):
            items.append({"job_id": r["id"], "company": r["company"], "kind": "code",
                          "message": r["hold_reason"]})          # as recorded: it may not say how the code came
    return items


def _waiting(since, until, label, company, attention):
    any_ = False
    cw = " AND company=?" if company else ""
    cp = (company,) if company else ()
    codes = _only_you(attention, company)
    if codes:
        any_ = True
        yield {"t": "head", "text": f"Only you can do  {len(codes)}"}
        for a in codes:
            yield {"t": "item", "text": a["company"], "meta": a["message"], "job_id": a["job_id"], "urgent": True}
    mine = {a["job_id"] for a in codes}            # listed once, under what only you can do
    ready = [r for r in db.q(f"SELECT id, company, title, hold_reason, updated_at FROM jobs WHERE status='filled'{cw} "
                             "ORDER BY updated_at DESC", cp) if r["id"] not in mine][:40]
    if ready:
        any_ = True
        yield {"t": "head", "text": f"Filled, waiting for you to submit  {len(ready)}"}
        for r in ready:
            yield {"t": "item", "text": r["company"], "meta": f"{r['title']} · {r['hold_reason'] or 'ready to submit'}", "job_id": r["id"]}
    err = db.q(f"SELECT id, company, title, error FROM jobs WHERE status='error'{cw} ORDER BY updated_at DESC LIMIT 20", cp)
    if err:
        any_ = True
        yield {"t": "head", "text": f"Couldn't finish  {len(err)}"}
        for r in err:
            yield {"t": "item", "text": r["company"], "meta": f"{r['title']} · {(r['error'] or 'stopped')[:80]}", "job_id": r["id"]}
    from .skills import followups, outreach
    outreach._ensure()
    drafts = db.q(f"""SELECT o.id, o.person, o.kind, o.created_at, j.company, j.id job_id FROM outreach o LEFT JOIN jobs j ON j.id=o.job_id
                      WHERE o.sent_at IS NULL{' AND j.company=?' if company else ''} ORDER BY o.created_at DESC LIMIT 20""", cp)
    if drafts:
        any_ = True
        yield {"t": "head", "text": f"Messages drafted, not sent  {len(drafts)}"}
        for d in drafts:
            yield {"t": "item", "text": d["person"], "meta": f"{d['kind']} · {d['company'] or ''} · drafted {ago(d['created_at'])}", "job_id": d["job_id"]}
    quiet = [q for q in followups.board()["quiet"] if not company or q["company"] == company]
    if quiet:
        any_ = True
        yield {"t": "head", "text": f"Follow-ups to send  {len(quiet)}"}
        for q in quiet[:15]:
            yield {"t": "item", "text": q["company"], "meta": f"{q['title']} · quiet for {q['days']} days", "job_id": q["id"]}
    if not any_:
        yield {"t": "head", "text": "Waiting on you"}
        yield {"t": "note", "text": "Nothing. Every application is either sent or still being worked on."}
    else:
        yield {"t": "hint", "text": "/review goes through the applications one by one · /outreach and /followups for messages"}


def _codes(since, until, label, company, attention):
    items = _only_you(attention, company)
    yield {"t": "head", "text": f"Codes, CAPTCHAs and sign-ins  {len(items)}" if items else "Codes, CAPTCHAs and sign-ins"}
    if not items:
        yield {"t": "note", "text": "Nothing waiting. Jobsmith asks here and under the bell when a site needs you."}
    for a in items:
        yield {"t": "item", "text": a["company"], "meta": a["message"], "job_id": a["job_id"], "urgent": True}
    if items:
        yield {"t": "hint", "text": "/code to paste a code · /takeover opens the page in a window"}


def _outcomes(kinds, title, since, until, label, company):
    from . import outcomes
    outcomes._ensure()
    w, p = _in("o.received_at", since, until, company)
    ph = ",".join("?" * len(kinds))
    rows = db.q(f"""SELECT o.kind, o.subject, o.received_at, j.id job_id, j.company, j.title FROM outcomes o JOIN jobs j ON j.id=o.job_id
                    WHERE o.kind IN ({ph}){w} ORDER BY o.received_at DESC LIMIT 40""", list(kinds) + p)
    yield {"t": "head", "text": f"{title} {_scope(label, company)}".strip() + (f"  {len(rows)}" if rows else "")}
    if not rows:
        last = db.q1(f"""SELECT j.company, o.kind, o.received_at FROM outcomes o JOIN jobs j ON j.id=o.job_id WHERE o.kind IN ({ph})"""
                     + (" AND j.company=?" if company else "") + " ORDER BY o.received_at DESC LIMIT 1", list(kinds) + ([company] if company else []))
        yield {"t": "note", "text": "None " + (label or "yet") + "." +
               (f" The last was {last['company']} ({last['kind']}), {ago(last['received_at'])}." if last and since else "") +
               ("" if outcomes.email_ready() or last else " Connect your email (/email) so Jobsmith sees replies.")}
        return
    word = {"received": "got your application", "assessment": "assessment", "interview": "interview", "offer": "offer", "rejected": "not moving forward"}
    for r in rows:
        yield {"t": "item", "text": r["company"], "meta": f"{word.get(r['kind'], r['kind'])} · {r['title']} · {ago(r['received_at'])}", "job_id": r["job_id"]}


def _followups(since, until, label, company):
    from .skills import followups
    b = followups.board()
    quiet = [q for q in b["quiet"] if not company or q["company"] == company]
    yield {"t": "head", "text": f"Gone quiet  {len(quiet)}" if quiet else "Gone quiet"}
    if not quiet:
        yield {"t": "note", "text": f"No follow-ups due. {b['waiting']} application{'s are' if b['waiting'] != 1 else ' is'} still waiting on a reply."}
        return
    for q in quiet:
        yield {"t": "item", "text": q["company"], "meta": f"{q['title']} · {q['days']} days without a reply", "job_id": q["id"]}
    yield {"t": "hint", "text": "/followups shows a draft for each"}


def _people(since, until, label, company):
    if not company:
        n = network.summary()["total"]
        yield {"t": "head", "text": "People you know"}
        if not n:
            yield {"t": "note", "text": "No LinkedIn connections yet. Add your export on the dashboard's Profile page or with /web."}
            return
        rows = db.q("""SELECT company, COUNT(*) n FROM jobs WHERE active=1 AND status NOT IN ('skipped','left_out') GROUP BY company
                       ORDER BY MAX(COALESCE(fit_score,0)) DESC LIMIT 300""")
        shown = 0
        for r in rows:
            k = len(network.at_company(r["company"], 9))
            if k:
                shown += 1
                yield {"t": "item", "text": r["company"], "meta": f"{k} connection{'s' if k != 1 else ''}"}
            if shown >= 12:
                break
        yield {"t": "hint", "text": "ask: who do I know at <company>?"}
        return
    ppl = network.at_company(company, 20)
    yield {"t": "head", "text": f"People you know at {company}" + (f"  {len(ppl)}" if ppl else "")}
    if not ppl:
        yield {"t": "note", "text": "No one in your LinkedIn connections."}
    for x in ppl:
        yield {"t": "item", "text": f"{x['first_name']} {x['last_name']}".strip(), "meta": x.get("position") or ""}
    if ppl:
        yield {"t": "hint", "text": f"/outreach {company} drafts a referral ask"}


def _outreach(since, until, label, company):
    from .skills import outreach
    outreach._ensure()
    w, p = _in("o.created_at", since, until, company)
    rows = db.q(f"""SELECT o.person, o.kind, o.sent_at, o.created_at, j.company FROM outreach o LEFT JOIN jobs j ON j.id=o.job_id
                    WHERE 1=1{w} ORDER BY o.created_at DESC LIMIT 30""", p)
    yield {"t": "head", "text": f"Messages {_scope(label, company)}".strip() + (f"  {len(rows)}" if rows else "")}
    if not rows:
        yield {"t": "note", "text": "No drafts yet. /outreach shows who you could ask for a referral."}
    for r in rows:
        yield {"t": "item", "text": r["person"], "meta": f"{r['kind']} · {r['company'] or ''} · " + (f"sent {ago(r['sent_at'])}" if r["sent_at"] else "not sent")}


def _failed(since, until, label, company):
    w, p = _in("j.updated_at", since, until, company)
    rows = db.q(f"SELECT j.id, j.company, j.title, j.error, j.updated_at FROM jobs j WHERE j.status='error'{w} ORDER BY j.updated_at DESC LIMIT 30", p)
    yield {"t": "head", "text": f"Couldn't finish {_scope(label, company)}".strip() + (f"  {len(rows)}" if rows else "")}
    if not rows:
        yield {"t": "note", "text": "Nothing failed" + (f" {label}" if label else "") + "."}
    for r in rows:
        yield {"t": "item", "text": r["company"], "meta": f"{r['title']} · {(r['error'] or 'stopped')[:90]}", "job_id": r["id"]}


def _running(since, until, label, company, active):
    s = db.get_settings()
    on = bool(s.get("auto_run")) and s.get("autonomy") != "copilot"
    yield {"t": "head", "text": f"Right now  autopilot {'on' if on else 'off'}"}
    rows = db.q("SELECT id, company, title FROM jobs WHERE id IN (%s)" % ",".join("?" * len(active)), list(active)) if active else []
    if not rows:
        yield {"t": "note", "text": "Nothing is applying." + ("" if on else " Shift+Tab turns autopilot on.")}
    for r in rows:
        yield {"t": "item", "text": r["company"], "meta": f"{r['title']} · {active.get(r['id'], '')}", "job_id": r["id"], "live": True}


def _matches(since, until, label, company):
    w, p = _in("j.created_at", since, until, company)
    rows = db.q(f"""SELECT j.id, j.company, j.title, j.locations, j.fit_score FROM jobs j WHERE j.active=1 AND j.status IN ('new','fetched','drafted')
                    AND j.verdict IS NULL{w} ORDER BY COALESCE(j.fit_score,0) DESC LIMIT 10""", p)
    yield {"t": "head", "text": f"Best matches {_scope(label, company)}".strip()}
    if not rows:
        yield {"t": "note", "text": "No open matches. /sync checks your job lists for new ones."}
    for r in rows:
        loc = (db.decode(r).get("locations") or [""])[0]
        yield {"t": "item", "text": r["company"], "meta": f"{r['title']} · {loc} · fit {round(r['fit_score'] or 0)}", "job_id": r["id"], "fit": r["fit_score"]}
    if rows:
        yield {"t": "hint", "text": "/apply <company> applies · /matches to browse"}


def _stats(since, until, label, company):
    from . import outcomes
    outcomes._ensure()
    w, p = _in("r.finished_at", since, until, company)
    sent = db.q1(f"""SELECT COUNT(DISTINCT r.job_id) n FROM runs r JOIN jobs j ON j.id=r.job_id WHERE r.kind='submit' AND r.status='done'{w}""", p)["n"]
    w2, p2 = _in("o.received_at", since, until, company)
    got = {r["kind"]: r["n"] for r in db.q(f"""SELECT o.kind, COUNT(DISTINCT o.job_id) n FROM outcomes o JOIN jobs j ON j.id=o.job_id
                                               WHERE 1=1{w2} GROUP BY o.kind""", p2)}
    held = db.q1("SELECT COUNT(*) n FROM jobs WHERE status IN ('filled','error')" + (" AND company=?" if company else ""), (company,) if company else ())["n"]
    yield {"t": "head", "text": f"Your numbers {_scope(label, company)}".strip()}
    yield {"t": "stat", "text": str(sent), "meta": "applications sent"}
    for k, word in (("assessment", "assessments"), ("interview", "interviews"), ("offer", "offers"), ("rejected", "not moving forward")):
        if got.get(k):
            yield {"t": "stat", "text": str(got[k]), "meta": word}
    replied = sum(got.get(k, 0) for k in ("assessment", "interview", "offer", "rejected"))
    if sent:
        yield {"t": "stat", "text": f"{round(100 * replied / sent)}%", "meta": "heard back beyond a receipt"}
    yield {"t": "stat", "text": str(held), "meta": "waiting on you"}


def _answers(since, until, label, company):
    if not company:
        yield {"t": "head", "text": "Answers"}
        yield {"t": "note", "text": "Name the company: what did you answer for <company>?"}
        return
    job = db.q1("""SELECT id, title, status FROM jobs WHERE company=? ORDER BY (status='submitted') DESC, (status='filled') DESC, updated_at DESC LIMIT 1""", (company,))
    from . import draft
    ds = [d for d in draft.drafts_for(job["id"]) if d["qtype"] in ("text", "textarea") and (draft.final_value(d) or "").strip()] if job else []
    yield {"t": "head", "text": f"Your application to {company}" + (f"  {job['title']} · {job['status']}" if job else "")}
    if not ds:
        yield {"t": "note", "text": "No written answers yet."}
    for d in ds[:8]:
        ans = draft.final_value(d)
        yield {"t": "qa", "text": d["label"], "meta": ans[:600] + ("…" if len(ans) > 600 else ""), "job_id": job["id"]}


def _voice(*_):
    from .skills import voice
    s = voice.summary()
    miss = [c["label"] for c in s["coverage"] if not c["have"]]
    yield {"t": "head", "text": "Your voice"}
    yield {"t": "stat", "text": str(s["style"].get("samples", 0)), "meta": "passages of your writing"}
    yield {"t": "stat", "text": str(s["answers"]), "meta": "answers you approved"}
    yield {"t": "note", "text": ("Missing stories: " + ", ".join(miss) + ".") if miss else "Every common story is covered."}
    yield {"t": "hint", "text": "/voice add <file> adds your writing"}


def _ai(*_):
    from . import llm
    s = db.get_settings()
    q = llm.quota_status() or {}
    yield {"t": "head", "text": "AI"}
    yield {"t": "item", "text": "Writing with", "meta": s.get("llm_backend") or "auto"}
    if q.get("limited"):
        yield {"t": "item", "text": "Free limit", "meta": f"{q['name']} is used up until {clock(q['resets_at'])}"}
    yield {"t": "note", "text": "Without an AI, answers come from your profile, your approved answers and your own writing."}


def _summary(since, until, label, company, attention, active):
    since = since or db.now() - 86400
    label = label or "in the past day"
    yield from _running(since, until, label, company, active)
    yield from _applied(since, until, label, company)
    yield from _outcomes(("assessment", "interview", "offer", "rejected", "received"), "Replies", since, until, label, company)
    yield from _waiting(since, until, label, company, attention)


def _help(*_):
    yield {"t": "head", "text": "Ask about your job hunt"}
    yield {"t": "note", "text": "Answers come from Jobsmith's own records, instantly, with no AI. Try:"}
    for e in EXAMPLES[:8]:
        yield {"t": "example", "text": e}


# --------------------------------------------------------------------------- entry point
def answer(text: str, attention: list[dict] | None = None, active: dict | None = None) -> Iterator[dict]:
    attention, active = attention or [], active or {}
    since, until, label = window(text)
    company = company_in(text)
    seen: set[str] = set()
    plan: list[str] = []
    for c in clauses(text):
        for tpc in topics(c):
            if tpc not in seen:
                seen.add(tpc)
                plan.append(tpc)
    if not plan and company:
        plan = ["applied", "waiting", "people"]                # just a company name: everything about it
    if not plan:
        yield {"t": "head", "text": "I can't answer that one yet"}
        close = difflib.get_close_matches(text.lower(), EXAMPLES, n=2, cutoff=0.3)
        close = list(dict.fromkeys(close + EXAMPLES[:4]))[:4]
        yield {"t": "note", "text": "I answer from Jobsmith's records only (no AI), about applications, replies, matches and what needs you. Try:"}
        for e in close:
            yield {"t": "example", "text": e}
        yield {"t": "hint", "text": "To apply somewhere, start with apply: apply to nvidia hardware internships"}
        return
    for tpc in plan:
        args = (since, until, label, company)
        if tpc == "applied":
            yield from _applied(*args)
        elif tpc == "waiting":
            yield from _waiting(*args, attention)
        elif tpc == "codes":
            yield from _codes(*args, attention)
        elif tpc == "replies":
            yield from _outcomes(("received", "assessment", "interview", "offer", "rejected"), "Replies", *args)
        elif tpc == "interviews":
            yield from _outcomes(("assessment", "interview"), "Interviews and assessments", *args)
        elif tpc == "rejected":
            yield from _outcomes(("rejected",), "Not moving forward", *args)
        elif tpc == "offers":
            yield from _outcomes(("offer",), "Offers", *args)
        elif tpc == "followups":
            yield from _followups(*args)
        elif tpc == "people":
            yield from _people(*args)
        elif tpc == "outreach":
            yield from _outreach(*args)
        elif tpc == "failed":
            yield from _failed(*args)
        elif tpc == "running":
            yield from _running(*args, active)
        elif tpc == "matches":
            yield from _matches(*args)
        elif tpc == "stats":
            yield from _stats(*args)
        elif tpc == "answers":
            yield from _answers(*args)
        elif tpc == "voice":
            yield from _voice()
        elif tpc == "ai":
            yield from _ai()
        elif tpc == "summary":
            yield from _summary(*args, attention, active)
        elif tpc == "help":
            yield from _help()


def is_question(text: str) -> bool:
    """A request to act ('apply to...', a link) goes to the command runner; anything else is a question."""
    t = text.strip().lower()
    if re.match(r"https?://", t) or re.match(r"(apply|add|track|find|search|sync|watch|skip|stop|start|pause|resume)\b", t):
        return False
    return True
