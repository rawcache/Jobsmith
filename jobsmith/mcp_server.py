"""Jobsmith as an MCP server: let the AI agent you already use (Claude Code, Codex, Gemini CLI, Cursor) be the
brain, and Jobsmith the hands.

    jobsmith mcp                  run it (agents start this themselves once it's registered)
    jobsmith skills install       register it with the agents on this computer, and copy the skills' SKILL.md files

Jobsmith keeps doing what it does without any AI: reading postings and forms, your profile answers, checking you
qualify, filling the browser, tracking replies. The agent does the writing: for every open question Jobsmith
couldn't answer on its own, it gets the posting, your facts and examples of your own writing, and sends its answer
back. Jobsmith checks that answer like any other (numbers and claims must come from your facts; phrases you never
use get flagged) before anything is submitted.
"""
from __future__ import annotations

import json

try:                                    # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:                     # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from . import db, draft, eligibility, insights, network, outcomes, profile
from .skills import voice

mcp = FastMCP("jobsmith", instructions=(
    "Jobsmith applies to internships and jobs for the user from their real resume. Start with jobsmith_status. "
    "Write answers only from the facts Jobsmith gives you, in the user's own voice. Never invent experience or numbers, "
    "never answer demographic or work-authorization questions, never send messages, type passwords or solve CAPTCHAs."))


def _post(path: str, body: dict) -> dict:
    """Ask the local engine to act (it owns the browser). Starts it if needed, quietly: on an MCP stdio server,
    anything printed to stdout would corrupt the conversation with the agent."""
    import os
    import subprocess
    import sys
    import time
    import httpx
    from .config import DATA_DIR
    base = os.environ.get("JOBSMITH_URL", f"http://127.0.0.1:{os.environ.get('JOBSMITH_PORT', '8765')}")

    def up() -> bool:
        try:
            return httpx.get(base + "/api/status", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False
    if not up():
        log = open(DATA_DIR / "server.log", "a")
        subprocess.Popen([sys.executable, "-m", "jobsmith", "serve", "--no-open"], stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, start_new_session=os.name != "nt")
        for _ in range(60):
            time.sleep(0.5)
            if up():
                break
        else:
            return {"error": f"Jobsmith's engine didn't start. See {DATA_DIR / 'server.log'}"}
    r = httpx.post(base + path, json=body, timeout=120)
    try:
        return r.json()
    except ValueError:
        return {"error": r.text[:300]}


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


@mcp.tool()
def jobsmith_status() -> str:
    """What Jobsmith is doing: applications running, held for the user, submitted today, and anything only the user can do."""
    counts = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM jobs WHERE active=1 GROUP BY status")}
    held = db.q("SELECT id, company, title, status, hold_reason, error FROM jobs WHERE status IN ('filled','error') ORDER BY updated_at DESC LIMIT 15")
    pending = len(_pending(50))
    return _j({"counts": counts, "held_for_user": held, "open_questions_for_you_to_write": pending,
               "autopilot_on": bool(db.get_setting("auto_run")), "email_connected": outcomes.email_ready()})


@mcp.tool()
def jobsmith_profile() -> str:
    """The user's facts (cite them by id), profile answers, and how they write. Read this before writing anything."""
    ans = {k: v["value"] for k, v in profile.answers().items() if v.get("value") and k not in profile.SENSITIVE_KEYS}
    return _j({"facts": profile.facts_prompt_block(12000), "answers": ans, "voice": voice.style(), "voice_notes": voice.style_notes()})


@mcp.tool()
def jobsmith_find_jobs(query: str = "", limit: int = 20, only_new: bool = True) -> str:
    """Best-fit roles from the user's job lists. query filters by company or title."""
    where, params = ["active=1"], []
    if only_new:
        where.append("status IN ('new','fetched','drafted')")
    if query:
        where.append("(company LIKE ? OR title LIKE ?)")
        params += [f"%{query}%", f"%{query}%"]
    rows = db.q(f"""SELECT id, company, title, locations, terms, fit_score, status, url FROM jobs WHERE {' AND '.join(where)}
                    ORDER BY COALESCE(fit_score,0) DESC LIMIT ?""", params + [max(1, min(limit, 100))])
    return _j([db.decode(r) for r in rows])


@mcp.tool()
def jobsmith_job(job_id: str) -> str:
    """One job: the posting, pay and level, how the user's resume matches, eligibility, and every drafted answer."""
    j = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    if not j:
        return _j({"error": "No such job"})
    return _j({"job": {k: j.get(k) for k in ("id", "company", "title", "url", "locations", "terms", "status", "fit_score", "hold_reason")},
               "posting": (j.get("description") or "")[:6000], "facts_row": insights.job_facts(j), "match": insights.keyword_match(j),
               "eligibility": eligibility.check(j),
               "answers": [{"field": d["field"], "question": d["label"], "answer": draft.final_value(d), "kind": d["kind"],
                            "confidence": d["confidence"], "issues": d["issues"]} for d in draft.drafts_for(job_id)]})


def _pending(limit: int) -> list[dict]:
    min_conf = float(db.get_setting("autopilot_min_confidence") or 0.7)
    out = []
    for d in db.q("""SELECT d.*, j.company, j.title, j.description FROM drafts d JOIN jobs j ON j.id=d.job_id
                     WHERE j.status IN ('drafted','filled') AND d.verdict IS NULL AND d.final_answer IS NULL
                       AND d.qtype IN ('textarea','text') AND d.kind IN ('generated','voice')
                     ORDER BY j.fit_score DESC, d.id LIMIT 400"""):
        d = db.decode(d)
        if (d["answer"] or "").strip() and (d["confidence"] or 0) >= min_conf and not d["issues"]:
            continue
        out.append(d)
        if len(out) >= limit:
            break
    return out


@mcp.tool()
def jobsmith_pending_questions(limit: int = 10) -> str:
    """Written questions Jobsmith couldn't answer confidently on its own, with what you need to answer them:
    the posting, the user's closest passages of their own writing, and any current draft. Answer them with
    jobsmith_save_answers, using only facts from jobsmith_profile."""
    rows = []
    for d in _pending(max(1, min(limit, 30))):
        job = {"company": d["company"], "title": d["title"], "description": d["description"]}
        rows.append({"job_id": d["job_id"], "company": d["company"], "role": d["title"], "field": d["field"], "question": d["label"],
                     "required": bool(d["required"]), "current_draft": d["answer"], "why_held": d["issues"],
                     "posting_excerpt": (d["description"] or "")[:1500],
                     "users_own_writing": [p["text"][:900] for p in voice.search(d["label"], job, k=2)]})
    return _j({"questions": rows, "voice_notes": voice.style_notes()})


@mcp.tool()
def jobsmith_save_answers(job_id: str, answers: list[dict]) -> str:
    """Save answers you wrote: [{"field": ..., "text": ..., "fact_ids": [...]}]. Jobsmith checks each one
    (claims and numbers must come from the cited facts; stock phrases the user never uses are flagged) and
    returns whether the application is now ready to submit."""
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    if not job:
        return _j({"error": "No such job"})
    facts = profile.facts_by_id()
    existing = {d["field"]: d for d in draft.drafts_for(job_id)}
    report = []
    for a in answers or []:
        d = existing.get(a.get("field"))
        if not d:
            report.append({"field": a.get("field"), "error": "No such question on this job"})
            continue
        text = (a.get("text") or "").strip()
        f = {"field": d["field"], "label": d["label"], "qtype": d["qtype"], "required": d["required"], "options": d["options"], "description": ""}
        issues, valid = draft.validate(f, text, a.get("fact_ids") or [], facts,
                                       f"{job.get('company', '')} {job.get('title', '')} {job.get('description', '')}")
        issues += voice.style_issues(text)
        draft.save_results(job_id, [f], {d["field"]: {"kind": "agent", "answer": text, "fact_ids": valid, "issues": issues,
                                                     "confidence": 0.88 if not issues else 0.5, "model": "your agent",
                                                     "rationale": "Written by your AI agent from your facts"}})
        report.append({"field": d["field"], "saved": True, "issues": issues})
    return _j({"saved": report, "readiness": draft.readiness(job_id)})


@mcp.tool()
def jobsmith_apply(job_ids: list[str], submit: bool | None = None) -> str:
    """Start applying to these jobs (autopilot fills them in the browser on the user's computer, and submits only
    when every answer is trusted, unless the user's settings say otherwise). submit=False fills and stops."""
    return _j(_post("/api/jobs/batch", {"action": "autopilot" if submit is not False else "fill", "ids": job_ids}))


@mcp.tool()
def jobsmith_add_jobs(text: str) -> str:
    """Point Jobsmith at jobs in plain words: a company ('NVIDIA hardware internships'), a job link, or a GitHub job list."""
    return _j(_post("/api/command", {"text": text}))


@mcp.tool()
def jobsmith_tracker() -> str:
    """Every application and its stage (applied, assessment, interview, offer, rejected), with replies so far."""
    outcomes._ensure()
    rows = db.q("""SELECT id, company, title, status, outcome, updated_at FROM jobs WHERE status IN ('submitted','filled','error','drafted')
                   ORDER BY updated_at DESC LIMIT 200""")
    return _j({"applications": rows, "funnel": outcomes.funnel()})


@mcp.tool()
def jobsmith_people_at(company: str) -> str:
    """The user's LinkedIn connections at a company (from their own export)."""
    return _j(network.at_company(company, 20))


@mcp.tool()
async def jobsmith_draft_outreach(job_id: str, first_name: str, last_name: str = "", kind: str = "referral") -> str:
    """Draft a referral ask (kind=referral), recruiter note (recruiter) or thank-you (thanks) to someone the user knows.
    Show it to the user; never send it."""
    from .skills import outreach
    person = next((p for p in network.at_company(db.q1("SELECT company FROM jobs WHERE id=?", (job_id,))["company"], 50)
                   if p["first_name"].lower() == first_name.lower() and (not last_name or p["last_name"].lower() == last_name.lower())),
                  {"first_name": first_name, "last_name": last_name})
    return _j(await outreach.draft(job_id, person, kind))


@mcp.tool()
def jobsmith_voice_examples(question: str, job_id: str = "") -> str:
    """The user's own passages that best fit a question, for writing in their voice."""
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,))) if job_id else None
    return _j({"passages": voice.search(question, job, k=4), "voice_notes": voice.style_notes()})


@mcp.tool()
def jobsmith_voice_add(text: str, title: str = "") -> str:
    """Save writing the user gave you (an essay, a cover letter, an answer they wrote) so Jobsmith learns their voice."""
    return _j({"added_passages": voice.add(text, "from your agent", title)})


def main() -> None:
    db.conn()
    mcp.run()
