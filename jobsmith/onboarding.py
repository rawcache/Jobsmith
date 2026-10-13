"""First run: one question about your goal, then everything else fills itself in.

Shared by the website's walkthrough and `jobsmith init` in the terminal.
"""
from __future__ import annotations

from . import db, llm, match, profile, runner, smith, sources

GOALS = {
    "internship": {"label": "Summer 2027 internships", "terms": ["Summer 2027"],
                   "sources": ["https://github.com/SimplifyJobs/Summer2027-Internships"]},
    "newgrad": {"label": "Full-time new grad roles", "terms": ["New Grad"],
                "sources": ["https://github.com/SimplifyJobs/New-Grad-Positions"]},
    "targeted": {"label": "Specific companies I name", "terms": [], "sources": []},
}
# Before goals were multi-select, "both" was its own choice.
LEGACY = {"both": ["internship", "newgrad"]}
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


# What autopilot needs before it can apply on its own. (key, label, required)
CHECKLIST = [
    ("resume", "Resume", True), ("pdf", "PDF resume to attach", True), ("name", "Name", True),
    ("email", "Email", True), ("phone", "Phone", False), ("links", "LinkedIn, GitHub or website", False),
    ("work_authorized_us", "Authorized to work in the US", True), ("needs_sponsorship", "Needs visa sponsorship", True),
    ("graduation_date", "Graduation date", False),
]


def checklist() -> list[dict]:
    a = {k: (v.get("value") or "") for k, v in profile.answers().items()}
    rs = profile.resume_status()
    n = len(profile.facts())
    found = {"resume": f"{n} fact{'s' if n != 1 else ''} about you" if rs["resume"] else "",
             "pdf": rs["attached"] or "",
             "name": " ".join(x for x in (a.get("first_name"), a.get("last_name")) if x),
             "email": a.get("email", ""), "phone": a.get("phone", ""),
             "links": ", ".join(k for k in ("linkedin", "github", "devpost", "website") if a.get(k)),
             "work_authorized_us": a.get("work_authorized_us", ""), "needs_sponsorship": a.get("needs_sponsorship", ""),
             "graduation_date": a.get("graduation_date") or a.get("graduation_year", "")}
    return [{"key": k, "label": label, "required": req, "value": found[k], "done": bool(found[k])}
            for k, label, req in CHECKLIST]


def profile_ready() -> bool:
    return all(c["done"] for c in checklist() if c["required"])


def goals_of(s: dict) -> list[str]:
    g = s.get("goals") or ([s["goal"]] if s.get("goal") else [])
    return [x for k in g for x in LEGACY.get(k, [k]) if x in GOALS]


async def state() -> dict:
    s = db.get_settings()
    models = await llm.ollama_models()
    ok, msg = await llm.available_cached(ttl=30)
    return {"onboarded": bool(s.get("onboarded")), "goal": s.get("goal") or "", "goals_set": goals_of(s),
            "companies": s.get("target_companies") or [], "checklist": checklist(), "profile_ready": profile_ready(),
            "setup_step": s.get("setup_step") or "", "goals": GOALS, "fields": FIELDS,
            "categories": s.get("target_categories") or [], "ai": {"detected": llm.detected(s, models), "ok": ok,
            "message": msg, "using": llm.label(llm.backend("write")), "backend": s.get("llm_backend")},
            "resume": resume_summary(), "sources": db.q("SELECT id, url, last_synced, last_count FROM sources WHERE active=1"),
            "autonomy": s.get("autonomy"), "smith": await smith.status()}


def set_goal(goal: str | list[str], categories: list[str] | None = None, companies: list[str] | None = None) -> dict:
    """One or more of GOALS. Internships and new grad roles each add a job list; 'targeted' applies to
    the companies you name, a bit more selectively."""
    picked = [x for k in ([goal] if isinstance(goal, str) else goal) for x in LEGACY.get(k, [k]) if x in GOALS]
    picked = picked or ["internship"]
    terms = sorted({t for k in picked for t in GOALS[k]["terms"]}) or ["Summer 2027", "New Grad"]
    patch: dict = {"goal": picked[0], "goals": picked, "target_terms": terms}
    if categories:
        patch["target_categories"] = categories
    if "targeted" in picked:
        patch["target_companies"] = [c.strip() for c in (companies or []) if c.strip()]
        if picked == ["targeted"]:
            patch["min_fit_score"] = 55
    db.set_settings(patch)
    for k in picked:
        for url in GOALS[k]["sources"]:
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


FIRST_AUTOPILOT_DELAY = 20 * 60   # the supervised first run gets the browser to itself


def finish(autonomy: str = "autopilot", start_now: bool = False) -> None:
    """Setup is done. Autopilot (the default) starts after the first supervised application, or right
    away with start_now (for example when you skip watching the first one)."""
    import time
    s = db.get_settings()
    interval = max(1.0, float(s.get("auto_interval_hours") or 6)) * 3600
    patch = {"onboarded": True, "autonomy": autonomy, "auto_run": autonomy != "copilot"}
    if start_now:
        patch["auto_last_run"] = 0
    elif not s.get("onboarded"):
        # The scheduler runs when auto_last_run + interval has passed: start autopilot in 20 minutes, not now.
        patch["auto_last_run"] = time.time() - interval + FIRST_AUTOPILOT_DELAY
    patch["setup_step"] = "done"
    db.set_settings(patch)


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
