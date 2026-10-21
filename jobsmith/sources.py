"""Job sources. First-class: SimplifyJobs-style GitHub repos (they publish listings.json).
Fallback for other GitHub lists: parse links out of the README tables."""
from __future__ import annotations

import hashlib
import re

import httpx

from . import ats, db

UA = {"User-Agent": "jobsmith/0.1 (+https://github.com/)"}


def _repo(url: str) -> tuple[str, str] | None:
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)", url)
    return (m.group(1), m.group(2).removesuffix(".git")) if m else None


def job_id_for(url: str, company: str, title: str) -> str:
    return "j_" + hashlib.sha1(f"{ats.clean_url(url)}|{company}|{title}".lower().encode()).hexdigest()[:12]


def add_source(url: str) -> dict:
    kind = "simplify_github" if "github.com" in url else "url"
    db.x("INSERT OR IGNORE INTO sources(kind, url, active) VALUES(?,?,1)", (kind, url.strip()))
    return db.q1("SELECT * FROM sources WHERE url=?", (url.strip(),))


async def _fetch_listings_json(owner: str, repo: str, client: httpx.AsyncClient) -> list[dict] | None:
    for branch in ("dev", "main", "master"):
        r = await client.get(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/.github/scripts/listings.json")
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                return None
    return None


async def _fetch_readme_rows(owner: str, repo: str, client: httpx.AsyncClient) -> list[dict]:
    """Generic fallback: any README table row with a company + an apply link."""
    for branch in ("dev", "main", "master"):
        r = await client.get(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md")
        if r.status_code == 200:
            break
    else:
        return []
    from bs4 import BeautifulSoup
    rows = []
    text = r.text
    # HTML tables
    soup = BeautifulSoup(text, "html.parser")
    last_company = ""
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        company = tds[0].get_text(" ", strip=True)
        if company in ("↳", ""):
            company = last_company
        last_company = company
        link = next((a["href"] for a in tr.find_all("a", href=True)
                     if "simplify.jobs" not in a["href"]), None)
        if not link:
            continue
        rows.append({"company_name": company, "title": tds[1].get_text(" ", strip=True),
                     "locations": [tds[2].get_text(" ", strip=True)], "url": link, "active": True,
                     "terms": [], "category": "", "sponsorship": "", "date_posted": None, "degrees": []})
    # Markdown tables
    for line in text.splitlines():
        if not line.startswith("|") or "](" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        links = re.findall(r"\]\((https?://[^)]+)\)", line)
        links = [l for l in links if "simplify.jobs" not in l and "shields.io" not in l and "imgur" not in l]
        if len(cells) >= 3 and links:
            company = re.sub(r"\*|\[|\]\(.*?\)|\]", "", cells[0]).strip()
            if company in ("↳", ""):
                company = last_company
            last_company = company
            rows.append({"company_name": company, "title": re.sub(r"\[|\]\(.*?\)|\]", "", cells[1]).strip(),
                         "locations": [cells[2]], "url": links[-1], "active": "🔒" not in line,
                         "terms": [], "category": "", "sponsorship": "", "date_posted": None, "degrees": []})
    return rows


async def sync_source(source: dict) -> dict:
    owner_repo = _repo(source["url"])
    async with httpx.AsyncClient(headers=UA, timeout=60, follow_redirects=True) as client:
        if owner_repo:
            listings = await _fetch_listings_json(*owner_repo, client)
            if listings is None:
                listings = await _fetch_readme_rows(*owner_repo, client)
        else:
            listings = []
    added = updated = 0
    with db.tx() as c:
        for it in listings:
            if it.get("is_visible") is False:
                continue
            url = it.get("url") or ""
            if not url:
                continue
            jid = job_id_for(url, it.get("company_name", ""), it.get("title", ""))
            if not it.get("terms") and "new-grad" in source["url"].lower():
                it = dict(it, terms=["New Grad"])
            exists = c.execute("SELECT 1 FROM jobs WHERE id=?", (jid,)).fetchone()
            row = (
                source["id"], it.get("id"), it.get("company_name", "").strip(), it.get("title", "").strip(),
                ats.clean_url(url), ats.detect(url), db.enc(it.get("locations") or []),
                db.enc(it.get("terms") or []), it.get("category") or "", it.get("sponsorship") or "",
                db.enc(it.get("degrees") or []), it.get("date_posted"), int(bool(it.get("active", True))),
            )
            if exists:
                c.execute("""UPDATE jobs SET source_id=?, external_id=?, company=?, title=?, url=?, ats=?,
                             locations=?, terms=?, category=?, sponsorship=?, degrees=?, date_posted=?, active=?,
                             updated_at=? WHERE id=?""", row + (db.now(), jid))
                updated += 1
            else:
                c.execute("""INSERT INTO jobs(source_id, external_id, company, title, url, ats, locations, terms,
                             category, sponsorship, degrees, date_posted, active, id, created_at, updated_at)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row + (jid, db.now(), db.now()))
                added += 1
        c.execute("UPDATE sources SET last_synced=?, last_count=? WHERE id=?",
                  (db.now(), len(listings), source["id"]))
    return {"source": source["url"], "listings": len(listings), "added": added, "updated": updated}


async def sync_all() -> list[dict]:
    from .config import DEMO
    if DEMO:
        return []
    out = []
    for s in db.q("SELECT * FROM sources WHERE active=1"):
        try:
            out.append(await sync_source(s))
        except Exception as e:  # keep going on other sources
            out.append({"source": s["url"], "error": str(e)})
    return out


def add_job_url(url: str, company: str = "", title: str = "") -> str:
    """Manually add a single posting by URL."""
    from .match import guess_category
    jid = job_id_for(url, company, title or url)
    terms = db.get_setting("target_terms") or []
    guessed_terms = [t for t in terms if t.split()[0].lower() in (title or "").lower()] or \
        (["New Grad"] if re.search(r"new grad|graduate|entry level|early career", title or "", re.I) else
         (["Summer 2027"] if re.search(r"intern", title or "", re.I) and "Summer 2027" in terms else []))
    db.x("""INSERT OR IGNORE INTO jobs(id, company, title, url, ats, created_at, updated_at, category, terms)
            VALUES(?,?,?,?,?,?,?,?,?)""",
         (jid, company or "(unknown)", title or "(fetching…)", ats.clean_url(url), ats.detect(url),
          db.now(), db.now(), guess_category(title), db.enc(guessed_terms)))
    return jid
