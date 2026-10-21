"""Your LinkedIn data export, read into your profile.

LinkedIn doesn't let apps read profiles, but it gives you all your data as a file: Settings, Data privacy,
Get a copy of your data. The archive (a .zip of CSVs) has your name and headline, every position, school,
certification, language, skill, project and honor, and your connections. Jobsmith reads whichever of those
it finds. Your name, headline and credentials follow LinkedIn; work history and education entries are
added when they're new, never deleted; everything becomes facts the AI can cite.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile

from . import network, profile


def _rows(text: str) -> list[dict]:
    """LinkedIn CSVs sometimes start with notes before the header row: skip to the real header."""
    lines = text.lstrip("﻿").splitlines()
    start = next((i for i, ln in enumerate(lines[:12]) if ln.count(",") >= 1 and not ln.lower().startswith("notes")), 0)
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO("\n".join(lines[start:])))]


def _files(data: bytes, name: str) -> dict[str, str]:
    """{lowercased base name: text} from a zip archive or a single CSV."""
    out: dict[str, str] = {}
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.filename.lower().endswith(".csv") and info.file_size < 50_000_000:
                    out[info.filename.rsplit("/", 1)[-1].lower()] = z.read(info).decode("utf-8", "replace")
    else:
        out[name.rsplit("/", 1)[-1].lower()] = data.decode("utf-8", "replace")
    return out


def _find(files: dict[str, str], *names: str) -> list[dict]:
    for n in names:
        if n in files:
            return _rows(files[n])
    return []


def _when(s: str) -> str:
    """'Jun 2025' / '2025-06' / '6/2025' -> 'Jun 2025' style, as LinkedIn shows it."""
    return (s or "").strip()


def import_archive(data: bytes, name: str = "linkedin.zip") -> dict:
    files = _files(data, name)
    if not files:
        return {"ok": False, "message": "That file has no LinkedIn CSVs in it."}
    done: dict[str, int | str] = {}
    a = {k: v for k, v in profile.answers().items()}

    def setv(key: str, value: str, overwrite: bool = True) -> None:
        if not value:
            return
        cur = (a.get(key) or {}).get("value", "")
        if cur and (not overwrite or cur == value):
            return
        profile.set_answer(key, value, True)
        done.setdefault("updated", 0)
        done["updated"] = int(done["updated"]) + 1

    # who you are: LinkedIn wins for name and headline
    p = (_find(files, "profile.csv") or [{}])[0]
    setv("first_name", p.get("First Name", ""))
    setv("last_name", p.get("Last Name", ""))
    setv("headline", p.get("Headline", ""))
    if p.get("Geo Location"):
        setv("location", p["Geo Location"], overwrite=False)
    if p.get("Summary"):
        profile.add_fact("identity", p["Summary"][:1500], "LinkedIn summary", "linkedin")
    sites = re.findall(r"https?://[^\s,\]]+", p.get("Websites", ""))
    for u in sites:
        key = "github" if "github.com" in u else "devpost" if "devpost.com" in u else "website"
        setv(key, u, overwrite=False)
    emails = _find(files, "email addresses.csv")
    prim = next((e["Email Address"] for e in emails if e.get("Primary", "").lower() == "yes"), "")
    setv("email", prim, overwrite=False)
    phones = _find(files, "phonenumbers.csv", "phone numbers.csv")
    if phones:
        setv("phone", phones[0].get("Number", ""), overwrite=False)

    # work history and education: add what's new
    have = {(e.get("company", "").lower(), e.get("title", "").lower()) for e in profile.entries("experience")}
    n_pos = 0
    for r in _find(files, "positions.csv"):
        key = (r.get("Company Name", "").lower(), r.get("Title", "").lower())
        if not key[0] or key in have:
            continue
        profile.save_entry("experience", {"title": r.get("Title", ""), "company": r.get("Company Name", ""),
                                          "location": r.get("Location", ""), "start": _when(r.get("Started On", "")),
                                          "end": _when(r.get("Finished On", "")) or "present",
                                          "description": r.get("Description", "")})
        subject = f"{r.get('Company Name', '')} - {r.get('Title', '')}"
        profile.add_fact("experience", f"{r.get('Title', '')} at {r.get('Company Name', '')}"
                         + (f" ({_when(r.get('Started On', ''))} to {_when(r.get('Finished On', '')) or 'present'})" if r.get("Started On") else "")
                         + (f": {r['Description'][:600]}" if r.get("Description") else ""), subject, "linkedin")
        have.add(key)
        n_pos += 1
    done["positions"] = n_pos
    have_edu = {e.get("school", "").lower() for e in profile.entries("education")}
    n_edu = 0
    for r in _find(files, "education.csv"):
        school = r.get("School Name", "")
        if not school or school.lower() in have_edu:
            continue
        profile.save_entry("education", {"school": school, "degree": r.get("Degree Name", ""),
                                         "start": _when(r.get("Start Date", "")), "end": _when(r.get("End Date", "")),
                                         "notes": r.get("Notes", "") or r.get("Activities", "")})
        have_edu.add(school.lower())
        n_edu += 1
    done["education"] = n_edu

    # credentials
    certs = _find(files, "certifications.csv")
    if certs:
        items = [c.get("Name", "") + (f" ({c['Authority']}" + (f", {c['Started On'][-4:]}" if c.get("Started On") else "") + ")"
                                      if c.get("Authority") else "") for c in certs if c.get("Name")]
        setv("certifications", "; ".join(items))
        for it in items:
            profile.add_fact("award", f"Certification: {it}", "Certifications", "linkedin")
        done["certifications"] = len(items)
    langs = _find(files, "languages.csv")
    if langs:
        setv("languages", ", ".join(l.get("Name", "") + (f" ({l['Proficiency']})" if l.get("Proficiency") else "")
                                    for l in langs if l.get("Name")))
    skills = [s.get("Name", "") for s in _find(files, "skills.csv") if s.get("Name")]
    if skills:
        profile.add_fact("skill", "Skills (LinkedIn): " + ", ".join(skills[:80]), "Skills", "linkedin")
        done["skills"] = len(skills)
    for r in _find(files, "projects.csv"):
        if r.get("Title"):
            profile.add_fact("project", r["Title"] + (f": {r['Description'][:600]}" if r.get("Description") else "")
                             + (f" ({r['Url']})" if r.get("Url") else ""), r["Title"], "linkedin")
    for r in _find(files, "honors.csv"):
        if r.get("Title"):
            profile.add_fact("award", r["Title"] + (f" ({r['Issued On']})" if r.get("Issued On") else "")
                             + (f": {r['Description'][:300]}" if r.get("Description") else ""), "Honors", "linkedin")

    # who you know
    conn = files.get("connections.csv")
    if conn:
        done["connections"] = network.import_csv(conn).get("imported", 0)

    found = [k for k in ("profile.csv", "positions.csv", "education.csv", "certifications.csv", "languages.csv",
                         "skills.csv", "projects.csv", "honors.csv", "connections.csv") if k in files]
    parts = [f"{v} {k}" for k, v in done.items() if isinstance(v, int) and v]
    return {"ok": True, "found": found, **done,
            "message": ("Read " + ", ".join(parts) + ".") if parts else "Read it; your profile was already up to date."}
