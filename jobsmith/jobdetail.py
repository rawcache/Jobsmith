"""Fetch a posting's description and (where the ATS exposes it) the application form's questions."""
from __future__ import annotations

import html
import re

import httpx
from bs4 import BeautifulSoup

from . import ats, db, traps

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"}

GH_TYPES = {
    "input_text": "text", "textarea": "textarea", "input_file": "file",
    "multi_value_single_select": "select", "multi_value_multi_select": "multiselect",
    "input_hidden": "hidden", "boolean": "select",
}


def html_to_text(s: str) -> str:
    """What a person reads: text hidden from view (often a line aimed at AI) is left out."""
    s = traps.visible_html(html.unescape(s or ""))
    soup = BeautifulSoup(s, "html.parser")
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
    text = soup.get_text("\n")
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def normalize_greenhouse(data: dict) -> list[dict]:
    """Greenhouse job-board API -> Jobsmith field list."""
    fields: list[dict] = []

    def add(q: dict, section: str):
        visible = [f for f in q.get("fields", []) if f.get("type") != "input_hidden"]
        if not visible:
            return
        primary = next((f for f in visible if f["type"] == "input_file"), visible[0])
        alt = next((f["name"] for f in visible if f is not primary), None)
        fields.append({
            "field": primary["name"],
            "label": html_to_text(q.get("label", "")).strip(),
            "description": html_to_text(q.get("description") or ""),
            "qtype": GH_TYPES.get(primary["type"], "text"),
            "required": bool(q.get("required")),
            "options": [v["label"] for v in primary.get("values", [])],
            "option_values": {v["label"]: v["value"] for v in primary.get("values", [])},
            "alt_field": alt,
            "section": section,
        })

    for q in data.get("questions") or []:
        add(q, "main")
    for q in data.get("location_questions") or []:
        add(q, "location")
    for block in data.get("compliance") or []:
        for q in block.get("questions") or []:
            add(q, "eeo")
    edu = data.get("education") or ""
    if edu in ("education_required", "education_optional"):
        req = edu == "education_required"
        for key, label, qt in (("school--0", "School", "select"), ("degree--0", "Degree", "select"),
                               ("discipline--0", "Discipline", "select"),
                               ("start-month--0", "Education start month", "select"),
                               ("start-year--0", "Education start year", "text"),
                               ("end-month--0", "Education end month", "select"),
                               ("end-year--0", "Education end year", "text")):
            fields.append({"field": key, "label": label, "description": "", "qtype": qt, "required": req,
                           "options": [], "option_values": {}, "alt_field": None, "section": "education"})
    demo = data.get("demographic_questions") or {}
    for q in (demo.get("questions") if isinstance(demo, dict) else None) or []:
        fields.append({
            "field": str(q.get("id")), "label": html_to_text(q.get("label", "")),
            "description": "", "qtype": "multiselect" if q.get("type") == "multi_value_multi_select" else "select",
            "required": bool(q.get("required")), "options": [o["label"] for o in q.get("answer_options", [])],
            "option_values": {o["label"]: o["id"] for o in q.get("answer_options", [])},
            "alt_field": None, "section": "eeo",
        })
    return fields


def _board_guesses(company: str) -> list[str]:
    base = re.sub(r"[^a-z0-9 ]", "", (company or "").lower()).strip()
    words = base.split()
    out = []
    for g in ("".join(words), "-".join(words), words[0] if words else "",
              "".join(w for w in words if w not in ("inc", "llc", "corp", "corporation", "the", "co", "company"))):
        if g and g not in out:
            out.append(g)
    return out


async def _resolve_board(url: str, job_id: str, company: str, region: str, client: httpx.AsyncClient) -> str | None:
    """Embed links (boards.greenhouse.io/embed/job_app?token=ID) don't name the board. Find it."""
    host = "boards-api.eu.greenhouse.io" if region == "eu" else "boards-api.greenhouse.io"
    # 1) the embed page usually references its board somewhere in the HTML
    try:
        r = await client.get(url)
        for pat in (r"greenhouse\.io/(?:embed/)?(?:v1/boards/)?([a-z0-9_-]+)/jobs/" + job_id,
                    r"[?&]for=([a-z0-9_-]+)", r'"board_token"\s*:\s*"([a-z0-9_-]+)"',
                    r"boards/([a-z0-9_-]+)/(?:jobs|embed)"):
            m = re.search(pat, r.text, re.I)
            if m and m.group(1).lower() not in ("embed", "v1"):
                return m.group(1)
    except httpx.HTTPError:
        pass
    # 2) guess from the company name and verify against the API
    for g in _board_guesses(company):
        try:
            rr = await client.get(f"https://{host}/v1/boards/{g}/jobs/{job_id}")
            if rr.status_code == 200:
                return g
        except httpx.HTTPError:
            continue
    return None


async def fetch_greenhouse(url: str, client: httpx.AsyncClient, company: str = "") -> dict:
    board, job_id, region = ats.greenhouse_ids(url)
    if not job_id:
        raise ValueError("Could not find a Greenhouse job id in the URL")
    if not board:
        board = await _resolve_board(url, job_id, company, region, client)
        if not board:
            raise BoardNotFound("Couldn't identify the Greenhouse board for this embed link")
    host = "boards-api.eu.greenhouse.io" if region == "eu" else "boards-api.greenhouse.io"
    r = await client.get(f"https://{host}/v1/boards/{board}/jobs/{job_id}", params={"questions": "true"})
    if r.status_code == 404:
        raise ValueError("This posting is no longer on Greenhouse (it may have closed)")
    r.raise_for_status()
    data = r.json()
    domain = "job-boards.eu.greenhouse.io" if region == "eu" else "job-boards.greenhouse.io"
    return {
        "title": data.get("title"),
        "company": data.get("company_name"),
        "description": html_to_text(data.get("content", "")),
        "html": "\n".join([html.unescape(data.get("content", "") or ""), *(
            f"<p>{q.get('label') or ''}</p><div>{html.unescape(q.get('description') or '')}</div>"
            for q in data.get("questions") or [] if isinstance(q, dict))]),
        "questions": normalize_greenhouse(data),
        "apply_url": f"https://{domain}/{board}/jobs/{job_id}",
        "location": (data.get("location") or {}).get("name"),
    }


class BoardNotFound(ValueError):
    pass


async def fetch_lever(url: str, client: httpx.AsyncClient) -> dict:
    company, pid = ats.lever_ids(url)
    r = await client.get(f"https://api.lever.co/v0/postings/{company}/{pid}")
    r.raise_for_status()
    d = r.json()
    # From the HTML, not Lever's plain-text copies, so text hidden from a person is left out.
    parts = [html_to_text(d["description"]) if d.get("description") else d.get("descriptionPlain", "")]
    for lst in d.get("lists", []):
        parts.append(lst.get("text", "") + "\n" + html_to_text(lst.get("content", "")))
    parts.append(html_to_text(d["additional"]) if d.get("additional") else d.get("additionalPlain", ""))
    raw = "\n".join([d.get("description") or "", *(lst.get("content", "") for lst in d.get("lists", [])),
                     d.get("additional") or ""])
    return {"title": d.get("text"), "description": "\n\n".join(p for p in parts if p), "questions": [], "html": raw}


async def fetch_ashby(url: str, client: httpx.AsyncClient) -> dict:
    org, pid = ats.ashby_ids(url)
    r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}", params={"includeCompensation": "true"})
    r.raise_for_status()
    for j in r.json().get("jobs", []):
        if j.get("id") == pid:
            raw = j.get("descriptionHtml") or ""
            return {"title": j.get("title"), "description": html_to_text(raw) if raw else j.get("descriptionPlain") or "",
                    "questions": [], "html": raw or j.get("descriptionPlain") or ""}
    raise ValueError("Posting not found on Ashby board (may be closed)")


async def fetch_generic(url: str, client: httpx.AsyncClient) -> dict:
    r = await client.get(url)
    r.raise_for_status()
    soup = BeautifulSoup(traps.visible_html(r.text), "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        t.decompose()
    text = re.sub(r"\n\s*\n+", "\n\n", soup.get_text("\n")).strip()
    return {"title": None, "description": text[:20000], "questions": [], "html": r.text}


async def fetch_job(job_id: str) -> dict:
    from .config import DEMO
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    if not job:
        raise KeyError(job_id)
    if DEMO:
        return job
    async with httpx.AsyncClient(headers=UA, timeout=40, follow_redirects=True) as client:
        kind = job["ats"]
        if kind == "greenhouse":
            info = await fetch_greenhouse(job["url"], client, job["company"])
        elif kind == "lever":
            info = await fetch_lever(job["url"], client)
        elif kind == "ashby":
            info = await fetch_ashby(job["url"], client)
        else:
            info = await fetch_generic(job["url"], client)
    sets = {"description": info.get("description") or "", "questions": db.enc(info.get("questions") or []),
            # before any AI sees it: lines aimed at AI, hidden or not, from the posting as served
            "traps": db.enc(traps.unique(traps.scan_html(info.get("html") or "") +
                                         traps.scan_text(info.get("description") or "")))}
    if info.get("apply_url"):
        sets["url"] = info["apply_url"]
    if job["title"].startswith("(") and info.get("title"):
        sets["title"] = info["title"]
    if job["company"].startswith("(") and info.get("company"):
        sets["company"] = info["company"]
    if job["status"] == "new":
        sets["status"] = "fetched"
    cols = ", ".join(f"{k}=?" for k in sets)
    db.x(f"UPDATE jobs SET {cols}, error=NULL, updated_at=? WHERE id=?", (*sets.values(), db.now(), job_id))
    return db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
