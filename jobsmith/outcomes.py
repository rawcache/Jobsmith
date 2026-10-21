"""Track what happened after you applied, from your Gmail (read-only, IMAP with an app password).

Each message from the last few weeks is matched to a job you applied to (by company name) and
labelled: received, assessment, interview, rejected or offer. Outcomes feed the fit scores."""
from __future__ import annotations

import asyncio
import email
import imaplib
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from . import db

RANK = {"received": 1, "rejected": 2, "assessment": 3, "interview": 4, "offer": 5}
PATTERNS = [
    ("offer", re.compile(r"\boffer letter\b|pleased to (extend|offer)|we('d| would) like to offer|congratulations.{0,60}offer", re.I)),
    ("rejected", re.compile(r"unfortunately|not (be )?moving forward|decided to (move|proceed|pursue) .{0,40}other|"
                            r"no longer (being )?consider|regret to inform|not selected|position has been filled|"
                            r"will not be (moving|proceeding)", re.I)),
    ("interview", re.compile(r"\binterview\b|phone screen|schedule (a|some) time|availability for a (call|chat)|"
                             r"next round|meet with the team|recruiter (call|screen)", re.I)),
    ("assessment", re.compile(r"assessment|hackerrank|codesignal|codility|hirevue|online (test|challenge)|"
                              r"coding (challenge|exercise)|take-home", re.I)),
    ("received", re.compile(r"thank you for (applying|your application|your interest)|application (was )?received|"
                            r"we('ve| have) received your application", re.I)),
]


def _ensure() -> None:
    db.x("""CREATE TABLE IF NOT EXISTS outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
            kind TEXT NOT NULL, subject TEXT, sender TEXT, received_at REAL, message_id TEXT UNIQUE)""")
    cols = {r["name"] for r in db.q("PRAGMA table_info(jobs)")}
    if "outcome" not in cols:
        db.x("ALTER TABLE jobs ADD COLUMN outcome TEXT")


def classify(subject: str, body: str) -> str | None:
    text = f"{subject}\n{body[:4000]}"
    # rejections often start with "thank you for applying", so check the decisive outcomes first
    for kind, pat in PATTERNS:
        if pat.search(text):
            return kind
    return None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def match_job(sender: str, subject: str, body: str, jobs: list[dict]) -> dict | None:
    hay = _norm(f"{sender} {subject} {body[:2000]}")
    best = None
    for j in jobs:
        key = _norm(j["company"])
        if len(key) >= 3 and key in hay:
            if best is None or len(key) > len(_norm(best["company"])):
                best = j
    return best


def record(job: dict, kind: str, subject: str, sender: str, when: float, message_id: str) -> bool:
    _ensure()
    try:
        db.x("INSERT INTO outcomes(job_id, kind, subject, sender, received_at, message_id) VALUES(?,?,?,?,?,?)",
             (job["id"], kind, subject[:300], sender[:200], when, message_id))
    except Exception:
        return False   # already seen
    cur = db.q1("SELECT outcome FROM jobs WHERE id=?", (job["id"],))["outcome"]
    if RANK.get(kind, 0) >= RANK.get(cur or "", 0):
        db.x("UPDATE jobs SET outcome=?, updated_at=? WHERE id=?", (kind, db.now(), job["id"]))
    return True


def _text_of(msg: email.message.Message) -> str:
    parts = []
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        if part.get_content_type() in ("text/plain", "text/html") and not part.get_filename():
            try:
                t = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
            except Exception:
                continue
            parts.append(re.sub(r"<[^>]+>", " ", t) if part.get_content_type() == "text/html" else t)
    return " ".join(" ".join(parts).split())


def _fetch(days: int) -> list[dict]:
    from . import mail
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    address = db.get_setting("gmail_address") or ""
    out = []
    with mail.connect() as m:
        _, data = m.search(None, "SINCE", since)
        ids = data[0].split()[-400:]
        for i in ids:
            _, msg_data = m.fetch(i, "(BODY.PEEK[])")
            msg = email.message_from_bytes(msg_data[0][1])
            try:
                when = parsedate_to_datetime(msg.get("Date")).timestamp()
            except Exception:
                when = 0
            out.append({"id": msg.get("Message-ID") or f"{address}-{i.decode()}",
                        "from": str(make_header(decode_header(msg.get("From", "")))),
                        "subject": str(make_header(decode_header(msg.get("Subject", "")))),
                        "when": when, "body": _text_of(msg)})
    return out


async def check_inbox(days: int = 45) -> dict:
    from .config import DEMO
    if DEMO:
        return {"checked": 0, "new_outcomes": 0}
    _ensure()
    if not email_ready():
        return {"error": "Connect your email in Settings first."}
    try:
        messages = await asyncio.to_thread(_fetch, days)
    except Exception as e:
        return {"error": f"Couldn't read your email: {e}"}
    jobs = db.q("SELECT id, company, updated_at FROM jobs WHERE status='submitted'")
    found = 0
    for msg in messages:
        kind = classify(msg["subject"], msg["body"])
        if not kind:
            continue
        job = match_job(msg["from"], msg["subject"], msg["body"], jobs)
        if job and record(job, kind, msg["subject"], msg["from"], msg["when"], msg["id"]):
            found += 1
    return {"checked": len(messages), "new_outcomes": found}


def funnel() -> dict:
    _ensure()
    rows = db.q("SELECT outcome, COUNT(*) n FROM jobs WHERE status='submitted' GROUP BY outcome")
    out = {"submitted": sum(r["n"] for r in rows)}
    for r in rows:
        out[r["outcome"] or "no_reply"] = r["n"]
    return out


# --------------------------------------------------------------------------- emailed verification codes
# Some application forms (Greenhouse, most often) email a code after you press Submit. With Gmail connected,
# Jobsmith reads only the last few minutes of your inbox, read-only, for that code and types it in for you.
CODE_NEAR = re.compile(r"(security|verification|confirmation|one[- ]time|access)?\s*(code|passcode|pin)\b", re.I)
TOKEN = re.compile(r"\b([A-Za-z0-9]{4,10})\b")
NOT_CODES = {"security", "verification", "application", "applying", "password", "passcode", "greenhouse"}


def _looks_like_code(t: str) -> bool:
    if t.lower() in NOT_CODES:
        return False
    if t.isdigit():
        return 4 <= len(t) <= 8
    has_digit = any(c.isdigit() for c in t)
    mixed = any(c.isupper() for c in t[1:]) and any(c.islower() for c in t)
    return len(t) >= 6 and (has_digit or mixed or t.isupper())


def extract_code(subject: str, body: str) -> str | None:
    """The code in a verification email: the first code-shaped token after the word 'code'."""
    text = f"{subject}\n{body[:5000]}"
    for m in CODE_NEAR.finditer(text):
        for t in TOKEN.finditer(text[m.end():m.end() + 220]):
            if _looks_like_code(t.group(1)):
                return t.group(1)
    return None


def _recent(since: float) -> list[dict]:
    from . import mail
    day = datetime.fromtimestamp(since - 86400).strftime("%d-%b-%Y")
    out = []
    with mail.connect() as m:
        _, data = m.search(None, "SINCE", day)
        for i in reversed(data[0].split()[-25:]):
            _, msg_data = m.fetch(i, "(BODY.PEEK[])")
            msg = email.message_from_bytes(msg_data[0][1])
            try:
                when = parsedate_to_datetime(msg.get("Date")).timestamp()
            except Exception:
                continue
            if when < since - 120:
                continue
            out.append({"from": str(make_header(decode_header(msg.get("From", "")))),
                        "subject": str(make_header(decode_header(msg.get("Subject", "")))),
                        "when": when, "body": _text_of(msg)})
    return out


def pick_code(messages: list[dict], company: str) -> str | None:
    key = _norm(company)
    for msg in sorted(messages, key=lambda m: -m["when"]):
        hay = _norm(f"{msg['from']} {msg['subject']} {msg['body'][:1500]}")
        if (len(key) >= 3 and key in hay) or "greenhouse" in hay:
            code = extract_code(msg["subject"], msg["body"])
            if code:
                return code
    return None


def email_ready() -> bool:
    from . import mail
    from .config import DEMO
    return False if DEMO else mail.ready()


async def find_code(company: str, since: float) -> str | None:
    """A verification code emailed by this company since `since`, or None. Never raises."""
    s = db.get_settings()
    if not email_ready() or s.get("gmail_codes") is False:
        return None
    try:
        msgs = await asyncio.to_thread(_recent, since)
    except Exception:
        return None
    return pick_code(msgs, company)


async def test_connection() -> dict:
    from . import mail
    s = db.get_settings()
    if not email_ready():
        return {"ok": False, "message": "Finish connecting your email first."}

    def _try():
        with mail.connect(s):
            pass
    try:
        await asyncio.to_thread(_try)
        return {"ok": True, "message": f"Connected to {s['gmail_address']} (read-only)."}
    except imaplib.IMAP4.error as e:
        p = mail.provider(s)
        if p == "gmail":
            return {"ok": False, "message": "Gmail didn't accept that. Use an app password (not your normal password), and check IMAP is on."}
        return {"ok": False, "message": str(e)[:300] or "The mail server didn't accept the sign-in."}
    except Exception as e:
        return {"ok": False, "message": f"Couldn't reach your mail server: {e.__class__.__name__}"}
