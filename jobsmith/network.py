"""Your LinkedIn connections, matched to companies, so each job and company page shows who you know there.

Import: LinkedIn > Settings > Data privacy > Get a copy of your data > Connections. The export is a
Connections.csv. Jobsmith only reads it to show people; it never contacts anyone.
"""
from __future__ import annotations

import csv
import io
import re

from . import db

SUFFIXES = {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "plc", "the",
            "gmbh", "ag", "sa", "lp", "llp", "group", "holdings", "technologies", "technology"}


def _ensure() -> None:
    db.x("""CREATE TABLE IF NOT EXISTS connections (
              id INTEGER PRIMARY KEY AUTOINCREMENT, first_name TEXT, last_name TEXT, url TEXT, email TEXT,
              company TEXT, company_norm TEXT, position TEXT, connected_on TEXT, source TEXT NOT NULL DEFAULT 'linkedin')""")
    db.x("CREATE INDEX IF NOT EXISTS connections_company ON connections(company_norm)")


def norm_company(name: str) -> str:
    words = re.sub(r"[^a-z0-9& ]+", " ", (name or "").lower().replace("&amp;", "&")).split()
    while words and words[-1] in SUFFIXES:
        words.pop()
    while words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


def import_csv(text: str) -> dict:
    """Replace your LinkedIn connections with the contents of a Connections.csv export."""
    _ensure()
    lines = text.lstrip("﻿").splitlines()
    start = next((i for i, l in enumerate(lines) if l.lower().startswith("first name")), None)
    if start is None:
        raise ValueError("That doesn't look like LinkedIn's Connections.csv (no 'First Name' header).")
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[start:]))))
    with db.tx() as c:
        c.execute("DELETE FROM connections WHERE source='linkedin'")
        n = 0
        for r in rows:
            first, last = (r.get("First Name") or "").strip(), (r.get("Last Name") or "").strip()
            if not (first or last):
                continue
            company = (r.get("Company") or "").strip()
            c.execute("""INSERT INTO connections(first_name, last_name, url, email, company, company_norm, position,
                         connected_on) VALUES(?,?,?,?,?,?,?,?)""",
                      (first, last, (r.get("URL") or "").strip(), (r.get("Email Address") or "").strip(), company,
                       norm_company(company), (r.get("Position") or "").strip(), (r.get("Connected On") or "").strip()))
            n += 1
    with_company = db.q1("SELECT COUNT(*) n FROM connections WHERE company_norm != ''")["n"]
    return {"imported": n, "with_company": with_company}


def at_company(company: str, limit: int = 50) -> list[dict]:
    """People you know at this company. 'Apple' matches 'Apple Inc.'; 'Amazon' matches 'Amazon Web Services'."""
    _ensure()
    key = norm_company(company)
    if not key:
        return []
    rows = db.q("""SELECT first_name, last_name, url, company, position, connected_on FROM connections
                   WHERE company_norm = ? OR company_norm LIKE ? ORDER BY company_norm = ? DESC, last_name LIMIT ?""",
                (key, key + " %", key, limit))
    return rows


def counts_for(companies: list[str]) -> dict[str, int]:
    _ensure()
    out = {}
    for c in set(companies):
        key = norm_company(c)
        if key:
            out[c] = db.q1("SELECT COUNT(*) n FROM connections WHERE company_norm = ? OR company_norm LIKE ?",
                           (key, key + " %"))["n"]
    return out


def summary() -> dict:
    _ensure()
    total = db.q1("SELECT COUNT(*) n FROM connections")["n"]
    top = db.q("""SELECT company, COUNT(*) n FROM connections WHERE company != '' GROUP BY company_norm
                  ORDER BY n DESC LIMIT 12""")
    return {"total": total, "top_companies": top}
