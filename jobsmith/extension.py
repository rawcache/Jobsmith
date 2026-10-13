"""What the Chrome extension asks the local engine for.

The extension never holds your data. On any application page it scans the form, sends the fields here,
and fills in what comes back: answers from your profile first, answers you approved before, then AI for
the open questions (same rules as autopilot: nothing made up). It never clicks Submit.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from . import ats, db, draft, match, profile, sources

COMPANY_FROM_URL = [
    r"boards(?:\.eu)?\.greenhouse\.io/([^/?#]+)", r"job-boards(?:\.eu)?\.greenhouse\.io/([^/?#]+)",
    r"jobs\.lever\.co/([^/?#]+)", r"jobs\.ashbyhq\.com/([^/?#]+)", r"([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com",
    r"apply\.workable\.com/([^/?#]+)", r"jobs\.smartrecruiters\.com/([^/?#]+)",
]


def posting_url(url: str) -> str:
    """The posting a form belongs to: drop '/apply', '#app' and tracking bits so the same job matches."""
    u = ats.clean_url(url.split("#")[0])
    return re.sub(r"/(apply|application)/?$", "", u)


def company_guess(url: str, site_name: str = "") -> str:
    for pat in COMPANY_FROM_URL:
        m = re.search(pat, url, re.I)
        if m and m.group(1) not in ("embed", "jobs"):
            return m.group(1).replace("-", " ").title()
    if site_name:
        return site_name.strip()[:80]
    host = urlparse(url).netloc.split(":")[0]
    parts = [p for p in host.split(".") if p not in ("www", "jobs", "careers", "apply", "com", "io", "co", "org", "net")]
    return (parts[0] if parts else host).title()


def find_or_add(url: str, title: str = "", company: str = "") -> str:
    clean = posting_url(url)
    hit = db.q1("SELECT id FROM jobs WHERE url=? OR url=? ORDER BY created_at LIMIT 1", (clean, ats.clean_url(url)))
    if hit:
        return hit["id"]
    jid = sources.add_job_url(clean, company, title)
    match.rescore([jid])
    return jid


def _field(f: dict, i: int) -> dict:
    """The extension's field (id, label, type, options) in the engine's draft format."""
    qtype = {"textarea": "textarea", "select": "select", "radio": "radio", "checkbox": "checkbox",
             "multiselect": "multiselect", "file": "file", "combobox": "select"}.get(f.get("type", ""), "text")
    return {"field": str(f.get("id") or f"f{i}"), "label": (f.get("label") or "").strip()[:300], "qtype": qtype,
            "required": bool(f.get("required")), "options": [str(o)[:200] for o in (f.get("options") or [])][:200],
            "description": (f.get("description") or "")[:500], "section": "main"}


async def answers(url: str, fields: list[dict], title: str = "", company: str = "", site_name: str = "") -> dict:
    company = company or company_guess(url, site_name)
    jid = find_or_add(url, title, company)
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    wanted = [f for f in (_field(x, i) for i, x in enumerate(fields)) if f["label"]]
    if not job.get("questions"):
        db.x("UPDATE jobs SET questions=? WHERE id=?", (db.enc(wanted), jid))
        job["questions"] = wanted
    results, err = await draft.answer_fields(job, wanted, skip_locked=False)
    draft.save_results(jid, wanted, results, status="drafted" if job["status"] in ("new", "fetched") else None, error=err)
    out = []
    for f in wanted:
        r = results.get(f["field"]) or {}
        if f["qtype"] == "file":
            kind = "cover_letter" if "cover" in f["label"].lower() else "transcript" if "transcript" in f["label"].lower() else "resume"
            out.append({"id": f["field"], "file": kind, "kind": "file"})
            continue
        out.append({"id": f["field"], "value": r.get("answer", ""), "kind": r.get("kind", ""),
                    "confidence": r.get("confidence", 0), "issues": r.get("issues", [])})
    pdf = profile.attachment_file()
    return {"job_id": jid, "company": company, "answers": out, "error": err,
            "resume": pdf.name if pdf else None}


def file_for(kind: str, job_id: str = ""):
    """The resume (or transcript / cover letter) the extension attaches."""
    if kind == "transcript":
        return profile.transcript_file()
    if kind == "cover_letter" and job_id:
        d = db.q1("SELECT answer, final_answer FROM drafts WHERE job_id=? AND (field LIKE '%cover%' OR label LIKE '%over letter%')",
                  (job_id,))
        return (d or {}).get("final_answer") or (d or {}).get("answer") or None
    return profile.attachment_file()
