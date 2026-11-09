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

# Where you want to work: each choice is the place names postings use (matched as whole words).
LOCATIONS = {
    "Remote": ["Remote"],
    "New York": ["New York", "NYC", "Brooklyn", "Jersey City"],
    "SF Bay Area": ["San Francisco", "SF", "Bay Area", "Mountain View", "Palo Alto", "San Jose", "Sunnyvale",
                    "Menlo Park", "Santa Clara", "Redwood City", "Oakland", "Cupertino", "San Mateo"],
    "Seattle": ["Seattle", "Redmond", "Bellevue", "Kirkland"],
    "Boston": ["Boston", "Cambridge", "Somerville"],
    "Austin": ["Austin"],
    "Atlanta": ["Atlanta", "Alpharetta"],
    "Chicago": ["Chicago"],
    "Los Angeles": ["Los Angeles", "Santa Monica", "Irvine", "El Segundo", "Culver City"],
    "Washington DC area": ["Washington", "Arlington", "McLean", "Reston", "Herndon", "Bethesda"],
    # outside the US
    "Canada": ["Canada", "Toronto", "Vancouver", "Montreal", "Montréal", "Waterloo", "Ottawa", "Calgary"],
    "London and the UK": ["London", "United Kingdom", "UK", "England", "Edinburgh", "Manchester"],
    "Europe": ["Berlin", "Munich", "Amsterdam", "Paris", "Zurich", "Zürich", "Dublin", "Ireland", "Stockholm",
               "Madrid", "Barcelona", "Copenhagen", "Warsaw", "Lisbon", "Germany", "Netherlands", "Switzerland", "France"],
    "India": ["India", "Bengaluru", "Bangalore", "Hyderabad", "Pune", "Mumbai", "Gurgaon", "Gurugram", "Delhi", "Noida", "Chennai"],
    "Singapore": ["Singapore"],
    "Asia-Pacific": ["Tokyo", "Japan", "Hong Kong", "Sydney", "Melbourne", "Australia", "Seoul", "Korea", "Taipei", "Taiwan", "Shanghai", "Beijing"],
    "Latin America": ["Mexico", "Mexico City", "São Paulo", "Sao Paulo", "Brazil", "Bogotá", "Bogota", "Buenos Aires", "Santiago"],
}
INTERNATIONAL = {"Canada", "London and the UK", "Europe", "India", "Singapore", "Asia-Pacific", "Latin America"}
PICKY = {"strong": 60, "good": 40, "any": 20}


def set_prefs(locations: list[str] | None = None, picky: str = "", concurrency: int = 0, browser_window: str = "",
              notifications: bool | None = None, values: list[str] | None = None) -> dict:
    """The extra choices setup asks about. Anything left out keeps its current value."""
    patch: dict = {}
    if locations is not None:
        names = [n for n in locations if n in LOCATIONS]
        patch["target_locations"] = [p for n in names for p in LOCATIONS[n]]
        patch["location_choices"] = names
    if picky in PICKY:
        patch["min_fit_score"] = PICKY[picky]
    if concurrency:
        patch["concurrency"] = max(1, min(8, int(concurrency)))
    if browser_window in ("background", "visible"):
        patch["browser_window"] = browser_window
    if notifications is not None:
        patch["notifications"] = bool(notifications)
    if values is not None:
        patch["values"] = [v for v in values if v in match.VALUES][:3]
    patch["prefs_saved"] = True
    db.set_settings(patch)
    match.rescore()
    return patch


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


# --------------------------------------------------------------------------- setup, in order
# 1 resume PDF, 2 check what was read, 3 one list of one-time questions, 4 what you're looking for (with a live
# count), 5 job lists from presets, 6 AI (optional), 7 the supervised first application.
SETUP_STEPS = ["resume", "confirm", "questions", "prefs", "sources", "ai", "start"]

# What the resume gives that forms ask for, shown back to you to check before anything uses it. Work authorization
# and the rest of the one-time questions are asked in step 3, never read from a resume.
READ_BACK = ["first_name", "last_name", "email", "phone", "location", "linkedin", "github", "website", "school",
             "degree", "major", "gpa", "graduation_date"]

DECLINE = "Decline to self-identify"
VOLUNTARY_KEYS = ["gender", "race", "hispanic_latino", "veteran_status", "disability_status", "lgbtq"]

# The one list. No default for work authorization, sponsorship, or the employer-list claim: only you answer those
# (rule 2), and a default would be a guess. Each says in one line why forms ask.
QUESTIONS = [
    {"key": "work_authorized_us", "label": "Are you authorized to work in the US?", "choices": ["Yes", "No"],
     "required": True, "why": "Nearly every form asks. Only you answer it; Jobsmith never guesses."},
    {"key": "needs_sponsorship", "label": "Will you need visa sponsorship, now or later?", "choices": ["Yes", "No"],
     "required": True, "why": "Asked next to work authorization. Yes also hides roles that say they don't sponsor."},
    {"key": "resume_lists_all_employers", "label": "Does your resume list every employer and contract you've had?",
     "choices": ["Yes", "No"], "required": True,
     "why": "Then \"Have you worked for us before?\" is No for companies not on it. With No, each one asks you."},
    {"key": "willing_to_relocate", "label": "Work in person or relocate?", "choices": ["Only in my chosen locations",
     "Yes, anywhere", "No"], "default": "Only in my chosen locations",
     "why": "Forms ask about relocating and office days. Yes for a job in a place you pick next; others ask you."},
    {"key": "desired_pay", "label": "Pay expectation", "kind": "text", "default": "",
     "placeholder": "Leave blank, or e.g. $45/hour", "why": "Left empty when optional. When a form requires it, "
     "that job asks you."},
    {"key": "years_experience", "label": "Years of work experience", "kind": "text", "default": "",
     "placeholder": "e.g. 1", "why": "Some forms want a number. Blank: those jobs ask you."},
    {"key": "internships_count", "label": "Did you count internships in that number?", "choices": ["Yes", "No"],
     "default": "Yes", "why": "A form that counts them the other way asks you, so the number is never wrong."},
    {"key": "earliest_start", "label": "Earliest start date", "kind": "text", "default": "",
     "placeholder": "e.g. May 2027", "why": "Forms ask when you can start."},
    {"key": "voluntary", "label": "Voluntary questions (gender, race, veteran and disability status)",
     "choices": ["Decline to answer", "I'll answer them on my Profile"], "default": "Decline to answer",
     "why": "Optional on US forms, and declining never counts against you. Jobsmith never guesses these."},
]


def read_back() -> list[dict]:
    """The values your resume gave, for you to check: each with its label and whether you've confirmed it."""
    a = profile.answers()
    return [{"key": k, "label": a[k]["label"], "value": a[k]["value"], "confirmed": bool(a[k]["confirmed"]),
             "section": a[k]["section"]} for k in READ_BACK if k in a]


def confirm_values(values: dict[str, str]) -> None:
    """You checked these (and maybe corrected some): each is saved as yours. Only the keys shown, never the rest."""
    for k, v in values.items():
        if k in READ_BACK:
            profile.set_answer(k, (v or "").strip(), confirmed=bool((v or "").strip()))


def _start_default(s: dict, a: dict) -> str:
    grad = (a.get("graduation_date") or {}).get("value") or ""
    if goals_of(s) == ["newgrad"] and grad:
        return grad
    return "Summer 2027" if "internship" in goals_of(s) else ""


def questions() -> list[dict]:
    """The one list, with what you answered (or the default) and whether it's yours yet."""
    a = profile.answers()
    s = db.get_settings()
    out = []
    for q in QUESTIONS:
        row = dict(q, kind=q.get("kind") or "choice")
        if q["key"] == "voluntary":
            vals = [(a.get(k) or {}) for k in VOLUNTARY_KEYS]
            mine = [v for v in vals if v.get("confirmed") and v.get("value") and v["value"] != DECLINE]
            declined = all(v.get("confirmed") and v.get("value") == DECLINE for v in vals)
            row["value"] = "I'll answer them on my Profile" if mine else "Decline to answer" if declined else ""
            row["confirmed"] = bool(mine or declined)
        else:
            cur = a.get(q["key"]) or {}
            row["value"], row["confirmed"] = cur.get("value") or "", bool(cur.get("confirmed"))
            if q.get("required") and not row["confirmed"]:
                # read from your resume, never picked for you: shown beside the question, you choose
                row["hint"] = f"Your resume says: {row['value']}" if row["value"] else ""
                row["value"] = ""
        if q["key"] == "earliest_start":
            row["default"] = _start_default(s, a)
        out.append(row)
    return out


def questions_done() -> bool:
    return all(q["confirmed"] and q["value"] for q in questions() if q.get("required"))


def save_questions(values: dict[str, str]) -> list[str]:
    """Your answers to the one list, saved as confirmed. Returns the required ones still missing."""
    known = {q["key"]: q for q in QUESTIONS}
    for k, v in values.items():
        q = known.get(k)
        v = (v or "").strip()
        if not q or (q.get("choices") and v and v not in q["choices"]):
            continue
        if k == "voluntary":
            if v == "Decline to answer":
                a = profile.answers()
                for key in VOLUNTARY_KEYS:     # an answer you gave yourself before stays
                    cur = a.get(key) or {}
                    if not (cur.get("confirmed") and cur.get("value") and cur["value"] != DECLINE):
                        profile.set_answer(key, DECLINE, confirmed=True)
            continue
        profile.set_answer(k, v, confirmed=bool(v) or not q.get("required"))
    match.rescore()                            # sponsorship changes which roles fit
    return [q["label"] for q in questions() if q.get("required") and not (q["confirmed"] and q["value"])]


# Job lists to start from, instead of typing a board's address. Each level picks its list by default.
PRESETS = {
    "simplify_internships": {"label": "SimplifyJobs: Summer 2027 internships", "level": "internship",
                             "url": "https://github.com/SimplifyJobs/Summer2027-Internships"},
    "simplify_newgrad": {"label": "SimplifyJobs: new grad roles", "level": "newgrad",
                         "url": "https://github.com/SimplifyJobs/New-Grad-Positions"},
}


def presets_state() -> list[dict]:
    active = {r["url"] for r in db.q("SELECT url FROM sources WHERE active=1")}
    return [dict(v, key=k, on=v["url"] in active) for k, v in PRESETS.items()]


def set_presets(keys: list[str]) -> list[dict]:
    """Turn the preset lists on or off. Lists you added yourself are left alone."""
    for k, v in PRESETS.items():
        if k in keys:
            sources.add_source(v["url"])
        else:
            db.x("UPDATE sources SET active=0 WHERE url=?", (v["url"],))
    return presets_state()


def prefs_patch(levels: list[str], seasons: list[str] | None, categories: list[str], locations: list[str],
                picky: str) -> dict:
    """The settings these choices mean, for previewing the count or saving."""
    levels = [x for x in levels if x in match.LEVELS] or ["internship"]
    terms = (["New Grad"] if "newgrad" in levels else []) + \
            ([t for t in (seasons or ["Summer 2027"]) if match.SEASON.match(t)] if "internship" in levels else [])
    names = [n for n in locations if n in LOCATIONS]
    return {"goals": levels, "goal": levels[0], "target_terms": terms, "target_categories": categories,
            "target_locations": [x for n in names for x in LOCATIONS[n]], "location_choices": names,
            "min_fit_score": PICKY.get(picky, 40)}


def preview(levels, seasons, categories, locations, picky) -> dict:
    r = match.preview(prefs_patch(levels, seasons, categories, locations, picky))
    n = r["matches"]
    r["advice"] = ("" if n == 0 and not r["open"] else
                   "No matches yet. Pick more places or role types." if n == 0 else
                   "That's a lot to check. Pick fewer places or role types, or a higher fit bar." if n > 300 else "")
    return r


def save_prefs(levels, seasons, categories, locations, picky) -> dict:
    patch = prefs_patch(levels, seasons, categories, locations, picky) | {"prefs_saved": True}
    db.set_settings(patch)
    for k, v in PRESETS.items():               # the level you picked brings its list along
        if v["level"] in patch["goals"]:
            sources.add_source(v["url"])
    match.rescore()
    return patch


def seasons_seen() -> list[str]:
    """Internship seasons in your lists, most roles first, for the level picker."""
    import json as _j
    n: dict[str, int] = {}
    for r in db.q("SELECT terms FROM jobs WHERE active=1 AND terms LIKE '%20%'"):
        for t in _j.loads(r["terms"] or "[]"):
            if match.SEASON.match(t or ""):
                n[t] = n.get(t, 0) + 1
    return sorted(n, key=lambda t: -n[t])[:6] or ["Summer 2027"]


def step_done() -> dict[str, bool]:
    s = db.get_settings()
    rs = profile.resume_status()
    rb = read_back()
    return {"resume": bool(rs["attached"]),
            "confirm": bool(rs["attached"]) and all(r["confirmed"] for r in rb if r["value"]),
            "questions": questions_done(), "prefs": bool(s.get("prefs_saved")),
            "sources": bool(s.get("prefs_saved")) and bool(db.q1("SELECT 1 FROM sources WHERE active=1")),
            "ai": bool(s.get("llm_backend") not in (None, "", "auto")) or bool(s.get("ai_step_seen")),
            "start": setup_done(s)}


# What autopilot needs before it can apply on its own. (key, label, required)
CHECKLIST = [
    ("resume", "Resume", True), ("pdf", "PDF resume to attach", True), ("name", "Name", True),
    ("email", "Email", True), ("phone", "Phone", False), ("links", "LinkedIn, GitHub or website", False),
    ("work_authorized_us", "Authorized to work in the US", True), ("needs_sponsorship", "Needs visa sponsorship", True),
    ("graduation_date", "Graduation date", False),
    ("acknowledge_notices", "Agree to privacy notices and terms on forms", False),
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
             "graduation_date": a.get("graduation_date") or a.get("graduation_year", ""),
             "acknowledge_notices": a.get("acknowledge_notices", "")}
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
            "locations": list(LOCATIONS), "location_choices": s.get("location_choices") or [],
            "values_all": match.VALUES, "values": s.get("values") or [],
            "international": sorted(INTERNATIONAL),
            "picky": next((k for k, v in PICKY.items() if v == s.get("min_fit_score")), "good"),
            "concurrency": s.get("concurrency") or 3, "browser_window": s.get("browser_window") or "background",
            "categories": s.get("target_categories") or [], "ai": {"detected": llm.detected(s, models), "ok": ok,
            "message": msg, "using": llm.label(llm.backend("write")), "backend": s.get("llm_backend")},
            "resume": resume_summary(), "sources": db.q("SELECT id, url, last_synced, last_count FROM sources WHERE active=1"),
            "autonomy": s.get("autonomy"), "smith": await smith.status(),
            "steps": SETUP_STEPS, "step_done": step_done(), "read_back": read_back(), "questions": questions(),
            "presets": presets_state(), "seasons": seasons_seen(), "seasons_set": [x for x in s.get("target_terms") or []
                                                                                  if match.SEASON.match(x)],
            "prefs_saved": bool(s.get("prefs_saved"))}


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
    llm.forget_checks()
    llm._auto_cache = None


FIRST_AUTOPILOT_DELAY = 20 * 60   # the supervised first run gets the browser to itself


DONE_STEPS = ("done", "first", "started")


def setup_done(s: dict | None = None) -> bool:
    """Setup reached its end. Until then nothing is drafted on its own and autopilot stays off; skipping setup
    doesn't count."""
    s = s or db.get_settings()
    return bool(s.get("onboarded")) and (s.get("setup_step") or "") in DONE_STEPS


def skip() -> None:
    """You left setup before the end: the dashboard opens, but autopilot stays off until you finish it."""
    db.set_settings({"onboarded": True, "setup_step": "skipped", "auto_run": False})


def finish(autonomy: str = "autopilot", start_now: bool = False, final: bool = True) -> None:
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
    if final:          # the website saves the mode one step before its last page; that isn't the end yet
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


# --------------------------------------------------------------------------- the dashboard's checklists
def strength() -> dict:
    """How complete your profile is, weighted the way it matters for filling forms."""
    a = {k: (v.get("value") or "") for k, v in profile.answers().items()}
    cats = {f["category"] for f in profile.facts()}
    s = db.get_settings()
    rs = profile.resume_status()
    items = [
        ("contact", "Add your contact info", 10, all(a.get(k) for k in ("first_name", "last_name", "email", "phone")), "#/profile"),
        ("education", "Add your education", 10, bool(a.get("school") and (a.get("graduation_date") or a.get("graduation_year"))
                                                    or profile.entries("education")), "#/profile"),
        ("experience", "Add your work experience", 20, bool(profile.entries("experience") or "experience" in cats), "#/profile"),
        ("resume", "Add your resume", 10, bool(rs["attached"]), "#/profile"),
        ("links", "Add your links", 10, any(a.get(k) for k in ("linkedin", "github", "website", "devpost")), "#/profile"),
        ("skills", "Add your skills", 10, "skill" in cats, "#/profile"),
        ("prefs", "Fill out your job preferences", 20, prefs_done(s), "#/preferences"),
        ("employment", "Fill out your work authorization", 10,
         bool(a.get("work_authorized_us") and a.get("needs_sponsorship")), "#/profile"),
    ]
    out = [{"key": k, "label": l, "points": p, "done": bool(d), "href": h} for k, l, p, d, h in items]
    return {"percent": sum(i["points"] for i in out if i["done"]), "items": out}


def prefs_done(s: dict | None = None) -> bool:
    s = s or db.get_settings()
    return bool(s.get("prefs_saved") or s.get("goals"))


def get_started(ai_ok: bool) -> list[dict]:
    """Simplify-style 'Get started': the six things that make autopilot work well."""
    from . import outcomes
    s = db.get_settings()
    st = strength()
    sent = (db.q1("SELECT COUNT(*) n FROM jobs WHERE status='submitted'") or {"n": 0})["n"]
    return [
        {"key": "prefs", "label": "Fill out your job preferences", "detail": "What, where, and how picky autopilot should be",
         "done": prefs_done(s), "href": "#/preferences"},
        {"key": "profile", "label": "Complete your profile", "detail": f"Profile strength {st['percent']}%. More details, fewer held applications",
         "done": st["percent"] >= 80, "href": "#/profile"},
        {"key": "ai", "label": "Connect your AI", "detail": "Gemini's free tier writes your answers and cover letters",
         "done": ai_ok, "href": "#/settings"},
        {"key": "email", "label": "Connect your email", "detail": "Enters emailed codes for you and tracks replies",
         "done": outcomes.email_ready(), "href": "#/settings/email"},
        {"key": "extension", "label": "Add the Chrome extension", "detail": "Autofill any application you open yourself",
         "done": bool(s.get("ext_seen")), "href": "#/settings/extension"},
        {"key": "first", "label": "Send your first application", "detail": "Turn on autopilot, or pick roles from your matches",
         "done": sent > 0, "href": "#/matches"},
    ]


def stages(active: set[str]) -> dict:
    """Counts for 'My applications', grouped like the tracker's columns."""
    from . import outcomes
    outcomes._ensure()
    rows = db.q("SELECT id, status, outcome FROM jobs WHERE status IN ('drafted','filling','filled','error','submitted')")
    out = dict.fromkeys(("working", "paused", "needs", "applied", "interviewing", "offer", "rejected"), 0)
    for r in rows:
        st, oc = r["status"], r.get("outcome")
        if r["id"] in active:
            out["working"] += 1
        elif st in ("drafted", "filling"):
            out["paused"] += 1
        elif st in ("filled", "error"):
            out["needs"] += 1
        elif oc == "offer":
            out["offer"] += 1
        elif oc == "rejected":
            out["rejected"] += 1
        elif oc in ("assessment", "interview"):
            out["interviewing"] += 1
        else:
            out["applied"] += 1
    return out
