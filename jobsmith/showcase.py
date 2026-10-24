"""Show me autopilot: a scripted run of three made-up applications, for the practice copy only.

It moves the same state the real runner keeps (what's running, each job's status, the live phase), so the real
terminal app and dashboard draw it with their own spinners, progress bars and messages. Nothing else happens:
no browser, no AI, no network, no email. Two applications are submitted and one is held for you to review.

    POST /api/demo/autopilot-show     (refused unless this engine is the practice copy)
    jobsmith demo show                starts a fresh practice copy and the terminal app, then plays it
"""
from __future__ import annotations

import asyncio
import json

from . import db, draft, runner

# Made-up companies and roles. Answers reuse the made-up Alex Rivera's resume facts, nothing new.
APPS = [
    {"id": "show-lumen", "company": "Lumen Robotics", "title": "Robotics Software Intern", "end": "submitted",
     "location": "Boston, MA"},
    {"id": "show-quarry", "company": "Quarry Labs", "title": "Machine Learning Intern", "end": "review",
     "location": "Remote in USA"},
    {"id": "show-kestrel", "company": "Kestrel AI", "title": "Software Engineering Intern", "end": "submitted",
     "location": "New York, NY"},
]
HELD_REASON = "AI wasn't sure (55% confident): Why Quarry Labs?"
# Seconds spent on each step at speed 1, and how far apart the three start: about 20 s in all, for a short video.
STEP_SECONDS = {"reading": 2.5, "writing": 4.0, "filling": 4.5, "submitting": 2.0}
STAGGER = 2.0

_playing: list[asyncio.Task] = []


def _require_practice_copy() -> None:
    from . import config
    if not config.DEMO:
        raise PermissionError("Show me autopilot only runs in the practice copy (jobsmith demo show).")


def running() -> bool:
    return any(not t.done() for t in _playing)


def start(speed: float = 1.0) -> bool:
    """Start the run in the background. False if one is already playing.
    Each application is registered with the runner like a real one, so /stop and autopilot off stop it too."""
    _require_practice_copy()
    if running():
        return False
    _reset()
    _playing.clear()
    loop = asyncio.get_running_loop()
    for i, a in enumerate(APPS):
        t = loop.create_task(_one(a, i * STAGGER, speed))
        runner._by_job[a["id"]] = t
        runner._tasks.add(t)
        t.add_done_callback(lambda t, jid=a["id"]: (runner._tasks.discard(t),
                                                     runner._by_job.pop(jid, None) if runner._by_job.get(jid) is t else None))
        _playing.append(t)
    return True


def _reset() -> None:
    """Clear an earlier run so the show can play again from the start."""
    for a in APPS:
        runner._active.pop(a["id"], None)
        runner.live_drop(a["id"])
        db.x("DELETE FROM drafts WHERE job_id=?", (a["id"],))
        db.x("DELETE FROM runs WHERE job_id=?", (a["id"],))
        db.x("DELETE FROM jobs WHERE id=?", (a["id"],))


def _add(a: dict) -> None:
    now = db.now()
    db.x("""INSERT INTO jobs(id, company, title, url, ats, locations, terms, category, date_posted, description, status,
            created_at, updated_at, fit_score) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
         (a["id"], a["company"], a["title"], f"https://boards.greenhouse.io/example/jobs/{a['id']}", "greenhouse",
          json.dumps([a["location"]]), json.dumps(["Summer 2027"]), "Software", now, "", "new", now, now, 88))


def _phase(jid: str, phase: str, status: str | None = None) -> None:
    # practice=True keeps the entry listed without a browser tab (see runner.live_list)
    runner.live_set(jid, phase=phase, practice=True)
    if status:
        db.x("UPDATE jobs SET status=?, updated_at=? WHERE id=?", (status, db.now(), jid))


def _hold(a: dict) -> None:
    """Filled and waiting for you, with one low-confidence answer to look at in /review."""
    fields = [{"field": "first_name", "label": "First Name", "qtype": "text", "required": True},
              {"field": "email", "label": "Email", "qtype": "text", "required": True},
              {"field": "resume", "label": "Resume/CV", "qtype": "file", "required": True},
              {"field": "why", "label": f"Why {a['company']}?", "qtype": "textarea", "required": True}]
    draft.save_results(a["id"], fields, {
        "first_name": {"kind": "standard", "answer": "Alex", "confidence": 1, "rationale": "From your profile"},
        "email": {"kind": "standard", "answer": "alex.rivera@example.edu", "confidence": 1, "rationale": "From your profile"},
        "resume": {"kind": "file", "answer": "Alex_Rivera_resume.pdf", "confidence": 1, "rationale": "Your resume"},
        "why": {"kind": "generated", "answer": "At Northwind I built an image pipeline that handled 600,000+ images with 94% "
                "duplicate-detection precision, and I'd like to keep working on ML that runs on real data at that scale.",
                "confidence": 0.55, "issues": ["The posting doesn't say what scale Quarry Labs works at. Check it fits."],
                "rationale": "From your Northwind internship", "model": "practice copy"},
    })
    db.x("UPDATE jobs SET hold_reason=? WHERE id=?", (HELD_REASON, a["id"]))


async def _one(a: dict, delay: float, speed: float) -> None:
    jid = a["id"]
    try:
        await _steps(a, delay, speed)
    except asyncio.CancelledError:                          # stopped: no spinner left turning on screen
        runner._active.pop(jid, None)
        runner.live_drop(jid)
        raise


async def _steps(a: dict, delay: float, speed: float) -> None:
    pause = lambda s: asyncio.sleep(s * speed)
    jid = a["id"]
    await pause(delay)
    _add(a)
    runner._active[jid] = "autopilot"                       # step 1 of 5: reading the posting
    await pause(STEP_SECONDS["reading"])
    db.x("UPDATE jobs SET description=? WHERE id=?",        # step 2: writing answers
         (f"{a['company']} is hiring a {a['title']}. (A made-up posting in the practice copy.)", jid))
    await pause(STEP_SECONDS["writing"])
    _phase(jid, "filling", "filling")                       # step 3: filling the form
    await pause(STEP_SECONDS["filling"])
    if a["end"] == "review":
        _hold(a)
        _phase(jid, "review", "filled")                     # step 4: ready for you
    else:
        _phase(jid, "submitting")
        await pause(STEP_SECONDS["submitting"])
        run = runner.Run(jid, "submit")
        run.log("Submitted in the practice copy. Nothing was sent anywhere.")
        run.done("done")
        runner._set_status(jid, "submitted")
        _phase(jid, "submitted")                            # step 5: submitted
    runner._active.pop(jid, None)


async def play(speed: float = 1.0) -> dict:
    """Play the whole run; returns how each application ended. speed 0 skips the pauses (tests)."""
    _require_practice_copy()
    _reset()
    await asyncio.gather(*(_one(a, i * STAGGER, speed) for i, a in enumerate(APPS)))
    return {a["id"]: db.q1("SELECT status FROM jobs WHERE id=?", (a["id"],))["status"] for a in APPS}
