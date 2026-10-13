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


def _fetch(address: str, password: str, days: int) -> list[dict]:
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    out = []
    with imaplib.IMAP4_SSL("imap.gmail.com") as m:
        m.login(address, password.replace(" ", ""))
        m.select("INBOX", readonly=True)
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
    _ensure()
    s = db.get_settings()
    if not (s.get("gmail_address") and s.get("gmail_app_password")):
        return {"error": "Add your Gmail address and an app password in Settings."}
    try:
        messages = await asyncio.to_thread(_fetch, s["gmail_address"], s["gmail_app_password"], days)
    except Exception as e:
        return {"error": f"Couldn't read Gmail: {e}"}
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
