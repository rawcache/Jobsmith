"""Plain-language requests: "apply to Apple roles", a GitHub list, or job links.

Every request becomes: find the jobs -> score them -> queue them. In Autonomous mode queued jobs are
drafted, filled and submitted when every answer is trusted; in Copilot mode they're drafted and wait
for your review.
"""
from __future__ import annotations

import json
import re

from . import boards, db, jobdetail, llm, match, profile, runner, sources
from .llm import LLMError, complete_json

URL_RE = re.compile(r"https?://[^\s<>\"')]+")


def _ensure_table() -> None:
    db.x("""CREATE TABLE IF NOT EXISTS commands (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
            result TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL)""")


def history(n: int = 10) -> list[dict]:
    _ensure_table()
    rows = db.q("SELECT * FROM commands ORDER BY id DESC LIMIT ?", (n,))
    return [dict(r, result=json.loads(r["result"])) for r in rows]


def _remaining_today() -> int:
    from . import guardrails
    return guardrails.remaining_today()


def queue(job_ids: list[str], force: bool = False, mode: str | None = None) -> list[str]:
    """Start work on jobs. Autonomous: draft+fill+submit-when-trusted. Copilot: draft for review."""
    autonomous = runner.applies_on_own() if mode is None else mode == "autopilot"
    started = []
    for j in job_ids:
        coro = runner.autopilot([j], force=force, submit=True) if autonomous else runner.prepare(j)
        if runner.spawn(j, "autopilot" if autonomous else "drafting", coro):
            started.append(j)
    return started


def _pick(job_ids: list[str], limit: int, keep_ineligible: bool = False) -> list[str]:
    """Best-fitting jobs first, ones Jobsmith can fill before ones it can't, skipping finished ones."""
    if not job_ids:
        return []
    marks = ",".join("?" * len(job_ids))
    rows = db.q(f"""SELECT id, ats, fit_score, status, eligibility FROM jobs WHERE id IN ({marks}) AND active=1
                    AND status NOT IN ('submitted','skipped')""", job_ids)
    if not keep_ineligible:   # jobs you clearly don't qualify for aren't worth an application
        rows = [r for r in rows if '"ok": false' not in (r["eligibility"] or "")]
    rows.sort(key=lambda r: (not runner.can_fill(r["ats"]), -(r["fit_score"] or 0)))
    return [r["id"] for r in rows[:limit]]


PARSE_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"},
                     "description": "role words like 'machine learning', 'hardware', 'new grad'"},
        "max_jobs": {"type": "integer"},
        "include_all_matches": {"type": "boolean"},
    },
    "required": ["companies", "keywords"],
}


async def _parse(text: str) -> dict:
    try:
        with llm.usage_for(None, "command"):
            return await complete_json(
                "Extract what job applications the user is asking for. companies: company names exactly as "
                "employers call themselves. keywords: role/title words they mentioned (not generic words like "
                "'roles' or 'jobs'). max_jobs only if they gave a number.", text, schema=PARSE_SCHEMA, role="write")
    except LLMError:
        m = re.search(r"(?:apply|applications?)?\s*(?:for|to|at)?\s*(.+?)\s*(?:roles?|jobs?|internships?|positions?|$)",
                      text, re.I)
        name = (m.group(1) if m else text).strip(" .!")
        return {"companies": [name] if name else [], "keywords": []}


DISCOVER_SCHEMA = {
    "type": "object",
    "properties": {"postings": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"}, "url": {"type": "string"}, "location": {"type": "string"},
        "why": {"type": "string"}}, "required": ["title", "url"]}}},
    "required": ["postings"],
}


async def discover(company: str, keywords: list[str]) -> list[dict]:
    """Use web search to find a company's open postings that fit the user's targets."""
    s = db.get_settings()
    ans = profile.answers()
    who = (f"{ans.get('degree', {}).get('value', '')} in {ans.get('major', {}).get('value', '')} student graduating "
           f"{ans.get('graduation_date', {}).get('value', '')}")
    prompt = (f"Company: {company}\nApplicant: {who}\nLooking for: {', '.join(s.get('target_terms') or [])} roles"
              f"{' about ' + ', '.join(keywords) if keywords else ''} in {', '.join(s.get('target_categories') or [])}.\n"
              "Find this company's currently open postings that match. Return the direct URL of each posting on the "
              "company's careers site or applicant tracking system (Greenhouse, Lever, Ashby, Workday, etc.), not job "
              "aggregators. Only include postings you actually found; at most 15.")
    with llm.usage_for(None, "command"):
        data = await complete_json("You find real, currently open job postings using web search. Never invent URLs.",
                                   prompt, schema=DISCOVER_SCHEMA, web=True)
    return [p for p in data.get("postings", []) if URL_RE.match(p.get("url", ""))]


async def run(text: str, mode: str | None = None) -> dict:
    """mode: None = your setting; "autopilot" = submit when confident; "copilot" = stop before submit."""
    from .config import DEMO
    _ensure_table()
    text = text.strip()
    if DEMO:
        return {"log": ["Demo mode: this is a practice copy, so nothing is searched or applied to. Try it in your real Jobsmith."],
                "started": [], "found": 0}
    log: list[str] = []
    found: list[str] = []
    explicit = False

    urls = URL_RE.findall(text)
    for u in urls:
        u = u.rstrip(".,")
        if "github.com" in u or boards.board_of(u):
            src = sources.add_source(u)
            res = await sources.sync_source(src)
            match.rescore()
            if res.get("error"):
                log.append(f"Couldn't read {u}: {res['error']}.")
                continue
            log.append(f"Added the list {u}: {res['listings']} postings ({res['added']} new)." if "left_out" not in res
                       else f"Added the job board {u}: {res['listings']} open roles, {res['added']} new"
                            + (f"; left out {res['left_out']} ({boards.left_out_words(res['why'])})." if res["left_out"]
                               else "."))
            rows = db.q("""SELECT id FROM jobs WHERE source_id=? AND active=1 AND status IN ('new','fetched')
                           AND COALESCE(fit_score,0) >= ?""", (src["id"], db.get_setting("min_fit_score") or 40))
            found += [r["id"] for r in rows]
        else:
            jid = sources.add_job_url(u)
            try:
                await jobdetail.fetch_job(jid)
            except Exception as e:
                log.append(f"Couldn't read {u} yet ({str(e)[:80]}); Jobsmith will open it in the browser.")
            match.rescore([jid])
            found.append(jid)
            explicit = True
    rest = URL_RE.sub("", text).strip()

    if rest and not urls:
        intent = await _parse(rest)
        kws = [k.lower() for k in intent.get("keywords") or []]
        for company in intent.get("companies") or []:
            rows = db.q("SELECT id, title FROM jobs WHERE active=1 AND company LIKE ? COLLATE NOCASE",
                        (f"%{company}%",))
            if kws:
                rows = [r for r in rows if any(k in r["title"].lower() for k in kws)] or rows
            if rows:
                log.append(f"{company}: {len(rows)} matching posting{'s' if len(rows) != 1 else ''} already in your lists.")
            else:
                log.append(f"{company}: not in your lists, searching the web with {llm.label(llm.backend('research'))}…")
                try:
                    posts = await discover(company, kws)
                except LLMError as e:
                    log.append(f"{company}: search failed ({e}).")
                    posts = []
                for p in posts:
                    jid = sources.add_job_url(p["url"], company, p.get("title", ""))
                    if p.get("location"):
                        db.x("UPDATE jobs SET locations=? WHERE id=?", (db.enc([p["location"]]), jid))
                    try:
                        await jobdetail.fetch_job(jid)
                    except Exception:
                        pass
                    rows.append({"id": jid, "title": p.get("title", "")})
                log.append(f"{company}: found {len(posts)} posting{'s' if len(posts) != 1 else ''} on the web.")
                match.rescore([r["id"] for r in rows])
            found += [r["id"] for r in rows]
            explicit = True
        limit = intent.get("max_jobs") or None
    else:
        limit = None

    room = _remaining_today()
    cap = min(limit or room, room)
    chosen = _pick(list(dict.fromkeys(found)), cap, keep_ineligible=explicit)
    if not explicit:   # from a big list: only good fits
        min_fit = db.get_setting("min_fit_score") or 40
        chosen = [j for j in chosen if (db.q1("SELECT fit_score FROM jobs WHERE id=?", (j,))["fit_score"] or 0) >= min_fit]
    started = queue(chosen, force=explicit, mode=mode)
    on = runner.applies_on_own() if mode is None else mode == "autopilot"
    mode = "applying on autopilot; anything uncertain waits in your review queue" if on \
        else "drafting for your review (Copilot mode)"
    if started:
        log.append(f"Started {len(started)} application{'s' if len(started) != 1 else ''}: {mode}.")
    elif found:
        log.append("Nothing new to start (already in progress, submitted, or today's limit is reached).")
    else:
        log.append("No matching postings found.")
    if len(set(found)) > len(chosen):
        log.append(f"{len(set(found)) - len(chosen)} more matched but weren't started (daily limit {room} left, "
                   "or below your fit threshold).")
    result = {"log": log, "started": started, "found": len(set(found))}
    db.x("INSERT INTO commands(text, result, created_at) VALUES(?,?,?)", (text, json.dumps(result), db.now()))
    return result
