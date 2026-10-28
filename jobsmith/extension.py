"""What the Chrome extension asks the local engine for.

The extension never holds your data. On any application page it scans the form, sends the fields here,
and fills in what comes back: answers from your profile first, answers you approved before, then AI for
the open questions (same rules as autopilot: nothing made up). It never clicks Submit.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from . import ats, classify, db, draft, match, profile, sources

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
        qkind = classify.question_kind(f["label"], f["qtype"], f["options"])
        out.append({"id": f["field"], "value": r.get("answer", ""), "kind": r.get("kind", ""),
                    "confidence": r.get("confidence", 0), "issues": r.get("issues", []),
                    # held: left blank because the answer didn't fit; check: filled, but you should read it.
                    # qkind: what the question asks for, so the extension checks the same thing (one set of rules).
                    "hold": r.get("held"), "check": r.get("check"), "qkind": qkind,
                    # pick: the option to look for in a place lookup ("Boston, Massachusetts, United States" for
                    # "Boston, MA"); the extension still types the city and picks only a matching option.
                    **({"pick": draft.location_full(r.get("answer", ""))}
                       if qkind == "location" and f["qtype"] == "select" and r.get("answer") else {})})
    pdf = profile.attachment_file()
    return {"job_id": jid, "company": company, "answers": out, "error": err,
            "resume": pdf.name if pdf else None}


def file_for(kind: str, job_id: str = ""):
    """The resume (or transcript / cover letter) the extension attaches."""
    if kind == "transcript":
        return profile.transcript_file()
    if kind == "cover_letter" and job_id:
        from . import letters
        return letters.cover_pdf(job_id)
    return profile.attachment_file()


# --------------------------------------------------------------------------- the side panel on a posting
def find(url: str) -> dict | None:
    """The job this page belongs to, if Jobsmith already knows it (no new rows: just looking)."""
    clean = posting_url(url)
    hit = db.q1("SELECT * FROM jobs WHERE url=? OR url=? OR url LIKE ? ORDER BY created_at LIMIT 1",
                (clean, ats.clean_url(url), clean.rstrip("/") + "%"))
    return db.decode(hit) if hit else None


def context(url: str, title: str = "", site_name: str = "", text: str = "") -> dict:
    """What the side panel shows: the role, pay, fit, how your resume matches, who you know, and the cover letter."""
    from . import insights, letters, network, outcomes
    outcomes._ensure()
    job = find(url)
    company = (job or {}).get("company") or company_guess(url, site_name)
    desc = (job or {}).get("description") or text
    km = insights.keyword_match({"title": (job or {}).get("title") or title, "company": company,
                                 "category": (job or {}).get("category"), "description": desc}, insights.resume_text())
    people = network.at_company(company, 5) if company else []
    letter = letters.cover_text(job["id"]) if job else ""
    return {"known": bool(job), "job_id": (job or {}).get("id"), "company": company, "title": (job or {}).get("title") or title,
            "pay": insights.pay_of(desc), "location": ", ".join(((job or {}).get("locations") or [])[:2]),
            "fit": (job or {}).get("fit_score"), "status": (job or {}).get("status"), "outcome": (job or {}).get("outcome"),
            "match": {"score": km["score"], "matched": km["matched"][:12], "missing": km["missing"][:12], "total": km["total"]},
            "people": [{"name": f"{p['first_name']} {p['last_name']}".strip(), "position": p["position"], "url": p["url"]} for p in people],
            "people_total": len(network.at_company(company, 200)) if company else 0, "cover_letter": bool(letter)}


async def generate(url: str, label: str, title: str = "", site_name: str = "", description: str = "", limit: int = 0) -> dict:
    """'Write with Jobsmith' beside one question: the same drafting autopilot uses, for just this field."""
    jid = find_or_add(url, title, company_guess(url, site_name))
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    f = {"field": "ext_" + re.sub(r"[^a-z0-9]+", "_", label.lower())[:60], "label": label[:300], "qtype": "textarea",
         "required": False, "options": [], "description": (description + (f" Limit: {limit} characters." if limit else ""))[:600],
         "section": "main"}
    results, err = await draft.answer_fields(job, [f], skip_locked=False)
    draft.save_results(jid, [f], results)
    r = results.get(f["field"]) or {}
    facts = profile.facts_by_id()
    used = [facts[i]["subject"] or facts[i]["category"] for i in r.get("fact_ids", []) if i in facts]
    text = r.get("answer", "")
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0]
    return {"job_id": jid, "text": text, "based_on": list(dict.fromkeys(u.split(" | ")[0] for u in used))[:5],
            "confidence": r.get("confidence", 0), "error": err if not text and not r.get("held") else None,
            "hold": r.get("held"), "check": r.get("check"), "issues": r.get("issues", []),
            "qkind": classify.question_kind(f["label"], f["qtype"])}


def submitted(url: str, title: str = "", site_name: str = "", confirmation: dict | None = None) -> dict:
    """You pressed Submit on a posting and it said thanks: log it to Applications, and suggest a few similar roles.
    `url` and `title` are the posting's; `confirmation` is the thank-you page itself, kept as proof it landed."""
    from . import audit, guardrails, runner
    jid = find_or_add(url, title, company_guess(url, site_name))
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    # Autopilot clicked Submit here without seeing a confirmation: this thank-you settles that submission rather than
    # making a second one.
    if job["status"] != "submitted" and not guardrails.maybe_sent(jid):
        runner.mark_submitted(jid)
    c = confirmation or {}
    # Also when it was already marked sent: the proof belongs to that submission.
    audit.log_confirmation(jid, "page", url=str(c.get("url") or ""), title=str(c.get("title") or ""),
                           text=str(c.get("text") or ""), seen_by="extension")
    similar = db.q("""SELECT id, company, title, locations FROM jobs WHERE active=1 AND status IN ('new','fetched','drafted')
                      AND id != ? AND company != ? AND (category = ? OR ? = '') ORDER BY COALESCE(fit_score,0) DESC LIMIT 3""",
                   (jid, job["company"], job.get("category") or "", job.get("category") or ""))
    return {"job_id": jid, "company": job["company"], "title": job["title"],
            "similar": [dict(db.decode(r)) for r in similar]}


def open_install() -> dict:
    """Make loading the extension one step: open chrome://extensions, show the folder, copy its path."""
    import platform
    import shutil
    import subprocess
    from .config import EXTENSION_DIR
    done = {"chrome": False, "folder": False}
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    try:
        if platform.system() == "Darwin":
            done["chrome"] = subprocess.run(["open", "-a", "Google Chrome", "chrome://extensions"], **quiet).returncode == 0
            done["folder"] = subprocess.run(["open", str(EXTENSION_DIR)], **quiet).returncode == 0
            subprocess.run(["pbcopy"], input=str(EXTENSION_DIR).encode(), stderr=subprocess.DEVNULL)
        elif platform.system() == "Windows":
            chrome = shutil.which("chrome") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
            done["chrome"] = subprocess.run([chrome, "chrome://extensions"], **quiet).returncode == 0
            done["folder"] = subprocess.run(["explorer", str(EXTENSION_DIR)], **quiet).returncode in (0, 1)
        else:
            for c in ("google-chrome", "chromium", "chromium-browser"):
                if shutil.which(c):
                    subprocess.Popen([c, "chrome://extensions"], **quiet)
                    done["chrome"] = True
                    break
            if shutil.which("xdg-open"):
                done["folder"] = subprocess.run(["xdg-open", str(EXTENSION_DIR)], **quiet).returncode == 0
    except Exception:
        pass
    return done
