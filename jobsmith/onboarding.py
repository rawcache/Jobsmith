"""First run: one question about your goal, then everything else fills itself in.

Shared by the website's walkthrough and `jobsmith init` in the terminal.
"""
from __future__ import annotations

from . import db, llm, match, profile, runner, smith, sources

GOALS = {
    "internship": {"label": "Land a Summer 2027 internship", "terms": ["Summer 2027"],
                   "sources": ["https://github.com/SimplifyJobs/Summer2027-Internships"]},
    "newgrad": {"label": "Land a full-time new grad role", "terms": ["New Grad"],
                "sources": ["https://github.com/SimplifyJobs/New-Grad-Positions"]},
    "both": {"label": "Both: internships and new grad roles", "terms": ["Summer 2027", "New Grad"],
             "sources": ["https://github.com/SimplifyJobs/Summer2027-Internships",
                         "https://github.com/SimplifyJobs/New-Grad-Positions"]},
    "targeted": {"label": "A few specific companies, done really well", "terms": ["Summer 2027", "New Grad"],
                 "sources": [], "limits": {"max_applications_per_day": 8, "min_fit_score": 55}},
}
FIELDS = ["Software", "AI/ML/Data", "Hardware", "Product", "Quant"]


def resume_summary() -> dict:
    a = {k: v["value"] for k, v in profile.answers().items() if v.get("value")}
    rs = profile.resume_status()
    return {"has_resume": bool(rs["resume"]), "pdf": rs["attached"],
            "name": " ".join(x for x in (a.get("first_name"), a.get("last_name")) if x),
            "email": a.get("email", ""), "school": a.get("school", ""), "degree": a.get("degree", ""),
            "major": a.get("major", ""), "graduation": a.get("graduation_date") or a.get("graduation_year", ""),
            "links": {k: a[k] for k in ("linkedin", "github", "devpost", "website") if a.get(k)},
            "facts": len(profile.facts()),
            "to_confirm": sum(1 for v in profile.answers().values() if v.get("value") and not v.get("confirmed"))}


async def state() -> dict:
    s = db.get_settings()
    models = await llm.ollama_models()
    ok, msg = await llm.available_cached(ttl=30)
    return {"onboarded": bool(s.get("onboarded")), "goal": s.get("goal") or "", "goals": GOALS, "fields": FIELDS,
            "categories": s.get("target_categories") or [], "ai": {"detected": llm.detected(s, models), "ok": ok,
            "message": msg, "using": llm.label(llm.backend("write")), "backend": s.get("llm_backend")},
            "resume": resume_summary(), "sources": db.q("SELECT id, url, last_synced, last_count FROM sources WHERE active=1"),
            "autonomy": s.get("autonomy"), "smith": await smith.status()}


def set_goal(goal: str, categories: list[str] | None = None) -> dict:
    g = GOALS.get(goal) or GOALS["internship"]
    patch = {"goal": goal, "target_terms": g["terms"]}
    if categories:
        patch["target_categories"] = categories
    patch.update(g.get("limits", {}))
    db.set_settings(patch)
    for url in g["sources"]:
        sources.add_source(url)
    match.rescore()
    return patch


def set_ai(kind: str, key: str = "", model: str = "") -> None:
    patch: dict = {"llm_backend": kind, "research_backend": "same"}
    field = {"anthropic_api": "anthropic_api_key", "openai_api": "openai_api_key", "gemini_api": "gemini_api_key"}.get(kind)
    if field and key.strip():
        patch[field] = key.strip()
    if kind == "ollama" and model:
        patch["ollama_model"] = model
    db.set_settings(patch)
    llm._avail_cache.clear()
    llm._auto_cache = None


def finish(autonomy: str = "autopilot") -> None:
    db.set_settings({"onboarded": True, "autonomy": autonomy, "auto_run": autonomy != "copilot"})


def best_first_job() -> str | None:
    """The best fitting job Jobsmith can fill on one page: a good first, supervised run."""
    rows = db.q("""SELECT id, ats FROM jobs WHERE active=1 AND status IN ('new','fetched','drafted')
                   AND eligibility NOT LIKE '%"ok": false%' ORDER BY fit_score DESC LIMIT 50""")
    return next((r["id"] for r in rows if r["ats"] in ("greenhouse", "lever", "ashby")), rows[0]["id"] if rows else None)


def first_run() -> dict:
    """Fill one application in front of you (no submit), so you see exactly what Jobsmith does."""
    jid = best_first_job()
    if not jid:
        return {"ok": False, "message": "No matches yet. Sync your job lists first."}
    runner.browser.shown = True     # keep the window up for this one
    started = runner.spawn(jid, "autopilot", _prepare_then_fill(jid))
    job = db.q1("SELECT company, title FROM jobs WHERE id=?", (jid,))
    return {"ok": started, "job_id": jid, "company": job["company"], "title": job["title"]}


async def _prepare_then_fill(jid: str) -> None:
    await runner.prepare(jid)
    if (db.q1("SELECT status FROM jobs WHERE id=?", (jid,)) or {}).get("status") == "drafted":
        await runner.fill(jid, submit=False)
