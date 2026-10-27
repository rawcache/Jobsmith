"""Local HTTP API + dashboard. Binds to 127.0.0.1 only."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (ats, audit, claude_login, commands, db, eligibility, guardrails, onboarding, outcomes, power, scheduler, smith, draft, insights, learn, llm, match, network,
               profile, runner, sources, traps)
from . import __version__
from .config import BUILD, DEMO, UPLOADS_DIR, WEB_DIST
from . import skills

app = FastAPI(title="Jobsmith", docs_url="/api/docs")

LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


@app.middleware("http")
async def only_local_callers(request, call_next):
    """The engine only talks to this computer: its own dashboard, the terminal, and the Chrome extension.
    A website you visit can't make it do anything (Origin check), and neither can a DNS-rebinding trick (Host check)."""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    origin = request.headers.get("origin") or ""
    o_host = origin.split("://", 1)[-1].rsplit(":", 1)[0] if origin else ""
    if host not in LOCAL_HOSTS and host != "testserver":
        return JSONResponse({"detail": "Jobsmith only answers on this computer."}, status_code=403)
    if origin and not origin.startswith("chrome-extension://") and o_host not in LOCAL_HOSTS:
        return JSONResponse({"detail": "Not allowed from a website."}, status_code=403)
    return await call_next(request)


@app.on_event("startup")
async def _startup():
    db.conn()
    profile.ensure_answer_bank()
    profile.migrate_documents()
    await profile.import_profile_json()
    # Repair: facts imported as raw LaTeX lines by an older version get re-parsed properly.
    if db.q1("SELECT 1 FROM facts WHERE active=1 AND (text LIKE '\\%' OR text LIKE '%\\textbf%')"):
        profile.rebuild_from_primary()
        match.rescore()
    if not db.q("SELECT 1 FROM sources LIMIT 1"):
        sources.add_source("https://github.com/SimplifyJobs/Summer2027-Internships")
    scheduler.start()
    import asyncio
    asyncio.create_task(smith.wake())


class ShowIn(BaseModel):
    speed: float = 1.0


@app.post("/api/demo/autopilot-show")
async def autopilot_show(s: ShowIn | None = None):
    """Practice copy only: play three made-up applications through autopilot (see showcase.py)."""
    from . import showcase
    try:
        started = showcase.start(max(0.0, min(5.0, (s or ShowIn()).speed)))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return {"started": started, "playing": showcase.running()}


@app.post("/api/shutdown")
async def shutdown():
    """The terminal restarts an engine left running by an older version of Jobsmith."""
    import asyncio
    import os

    async def bye():
        await asyncio.sleep(0.2)
        await runner.browser.close()
        os._exit(0)
    asyncio.create_task(bye())
    return {"ok": True}


@app.on_event("shutdown")
async def _shutdown():
    await runner.browser.close()


def job_or_404(job_id: str) -> dict:
    j = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    if not j:
        raise HTTPException(404, "job not found")
    return j


# --------------------------------------------------------------------------- status & settings
def attention() -> list[dict]:
    """Things only you can do, right now: emailed codes, CAPTCHAs, sign-ins. Shown as a bar on every page."""
    out = []
    for t in runner.live_list():
        note = (t.get("note") or "").lower()
        if t["needs_code"]:
            out.append({"job_id": t["job_id"], "company": t["company"], "kind": "code",
                        "message": f"{t['company']} emailed you a verification code."})
        elif "captcha" in note:
            out.append({"job_id": t["job_id"], "company": t["company"], "kind": "captcha",
                        "message": f"{t['company']} wants you to solve a CAPTCHA."})
        elif "sign in" in note or "sign-in" in note:
            out.append({"job_id": t["job_id"], "company": t["company"], "kind": "signin",
                        "message": f"{t['company']} wants you to sign in or create an account."})
    return out


@app.get("/api/notifications")
async def notifications():
    """Everything for the bell, newest first. Things only you can do come first; unread = newer than your last look."""
    from .config import DEMO
    seen = float(db.get_setting("notif_seen") or 0)
    now = db.now()
    items: list[dict] = []
    att = attention()
    if DEMO and not att:
        att = [{"job_id": "demo-wayne", "company": "Wayne Enterprises", "kind": "code",
                "message": "Wayne Enterprises emailed you a verification code."}]
    for a in att:
        items.append({"id": f"{a['kind']}:{a['job_id']}", "kind": a["kind"], "job_id": a["job_id"], "company": a["company"],
                      "title": a["message"], "detail": "" if a["kind"] == "code" else "Open it in a window to finish.",
                      "at": now, "urgent": True})
    held = db.q("""SELECT id, company, title, status, hold_reason, error, updated_at FROM jobs
                   WHERE status IN ('filled','error') ORDER BY updated_at DESC LIMIT 20""")
    if held:
        items.append({"id": "held", "kind": "held", "title": f"{len(held)} application{'s' if len(held) != 1 else ''} need you",
                      "detail": ", ".join(dict.fromkeys(h["company"] for h in held[:4])) + ("…" if len(held) > 4 else ""),
                      "at": max(h["updated_at"] for h in held), "href": "#/tracker"})
    outcomes._ensure()
    for r in db.q("""SELECT o.kind, o.subject, o.received_at, j.id job_id, j.company, j.title FROM outcomes o JOIN jobs j ON j.id=o.job_id
                     WHERE o.received_at > ? ORDER BY o.received_at DESC LIMIT 10""", (now - 14 * 86400,)):
        items.append({"id": f"reply:{r['job_id']}:{r['kind']}", "kind": "reply", "job_id": r["job_id"], "company": r["company"],
                      "title": f"{r['company']}: {OUTCOME_WORD.get(r['kind'], 'replied')}", "detail": r["subject"] or r["title"],
                      "at": r["received_at"] or now, "href": f"#/job/{r['job_id']}"})
    q = llm.quota_status()
    if q and q["limited"]:
        at = time.strftime("%I:%M %p", time.localtime(q["resets_at"])).lstrip("0")
        items.append({"id": "quota", "kind": "quota", "title": f"{q['name']}'s free limit is used up until {at}",
                      "detail": "smith is writing until then." if q.get("fallback") else "Answers wait until it resets.", "at": now})
    ok, msg = await llm.available_cached(role="write")
    if not ok:
        items.append({"id": "ai", "kind": "ai", "title": "No AI connected", "detail": msg, "at": now, "href": "#/settings"})
    for it in items:      # standing states (no AI, free limit) are listed but don't keep the count up
        it["unread"] = bool(it.get("urgent")) or (it["kind"] not in ("ai", "quota") and it["at"] > seen)
    return {"items": items, "unread": sum(1 for it in items if it["unread"])}


OUTCOME_WORD = {"received": "got your application", "assessment": "sent an assessment", "interview": "wants to interview",
                "offer": "made an offer", "rejected": "isn't moving forward"}


class AskBody(BaseModel):
    text: str


@app.post("/api/ask")
def ask_endpoint(b: AskBody):
    """Answer a question about your job hunt from Jobsmith's own records (no AI), one block per line as it's found."""
    from . import ask
    att, act = attention(), runner.active()

    def gen():
        try:
            for block in ask.answer(b.text, att, act):
                yield json.dumps(block, default=str) + "\n"
        except Exception as e:                       # say so in the answer rather than cutting the stream
            yield json.dumps({"t": "note", "text": f"Something went wrong reading that: {e.__class__.__name__}: {e}"}) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/notifications/seen")
def notifications_seen():
    db.set_settings({"notif_seen": db.now()})
    return {"ok": True}


def _names(job_ids: list[str]) -> dict[str, dict]:
    if not job_ids:
        return {}
    rows = db.q(f"SELECT id, company, title FROM jobs WHERE id IN ({','.join('?' * len(job_ids))})", tuple(job_ids))
    return {r["id"]: {"company": r["company"], "title": r["title"]} for r in rows}


@app.get("/api/status")
async def status():
    ok, msg = await llm.available_cached(role="write")
    s_ = db.get_settings()
    split = s_.get("research_backend") not in (None, "", "same", s_.get("llm_backend"))
    r_ok, r_msg = (await llm.available_cached(role="research")) if split else (ok, msg)
    counts = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM jobs WHERE active=1 GROUP BY status")}
    working = list(dict.fromkeys(list(runner._active) + [t["job_id"] for t in runner.live_list()]))
    ans = profile.answers()
    unconfirmed = sum(1 for a in ans.values() if a["value"] and not a["confirmed"])
    missing = [a["label"] for k, a in ans.items()
               if not a["value"] and k in ("first_name", "last_name", "email", "phone", "work_authorized_us",
                                           "needs_sponsorship", "school", "graduation_year")]
    rs = profile.resume_status()
    synced = bool(db.q1("SELECT 1 FROM sources WHERE last_synced IS NOT NULL"))
    setup = [
        {"key": "claude", "label": "Connect your AI (Claude or ChatGPT)", "done": ok, "detail": msg},
        {"key": "resume", "label": "Add your resume", "done": bool(rs["resume"]),
         "detail": rs["resume"]["filename"] if rs["resume"] else "A .tex is read exactly; a PDF works too"},
        {"key": "pdf", "label": "Choose the PDF employers get", "done": bool(rs["attached"]),
         "detail": rs["attached"] or "Upload your resume as a PDF"},
        {"key": "answers", "label": "Check your answers", "done": not unconfirmed and not missing,
         "detail": (f"{unconfirmed} to confirm" if unconfirmed else "") +
                   (f"{', ' if unconfirmed else ''}missing: {', '.join(missing)}" if missing else "") or "All set"},
        {"key": "jobs", "label": "Pull in jobs", "done": synced, "detail": "Sync the job lists"},
    ]
    return {"llm": {"backend": db.get_setting("llm_backend"), "ok": ok and r_ok,
                    "message": msg if not ok else r_msg,
                    "writing": {"label": llm.label(llm.backend("write")), "ok": ok, "message": msg},
                    "research": {"label": llm.label(llm.backend("research")), "ok": r_ok, "message": r_msg}},
            "counts": counts, "active": runner.active(), "setup": setup, "quota": llm.quota_status(),
            "power": {"saver": power.saver(), "battery": power.battery(), "paused": power.paused()},
            "attention": attention(),
            "progress": {jid: runner.progress(jid) for jid in working},
            # company and title from the job record, so the terminal names a job before its browser tab exists
            "names": _names(working),
            "has_resume": rs["attached"] is not None,
            "facts": len(profile.facts()), "autonomy": db.get_setting("autonomy"),
            "auto": {"on": bool(db.get_setting("auto_run")), "next_run": scheduler.state["next_run"],
                     "last_summary": scheduler.state["last_summary"]},
            "needs_you": db.q1("SELECT COUNT(*) n FROM jobs WHERE status IN ('filled','error')")["n"],
            "tokens_today": _usage_rows("at > ?", (db.now() - 86400,))["tokens"],
            "onboarded": bool(s_.get("onboarded")) or bool(db.q1("SELECT 1 FROM runs WHERE kind='submit' LIMIT 1")),
            "setup_step": s_.get("setup_step") or "", "build": BUILD, "version": __version__, "demo": DEMO,
            "skills": [{"key": k["key"], "name": k["name"], "enabled": k["enabled"]} for k in skills.listing()],
            "me": {"first_name": (ans.get("first_name") or {}).get("value") or "",
                   "last_name": (ans.get("last_name") or {}).get("value") or ""},
            "email": {"ready": outcomes.email_ready(), "address": s_.get("gmail_address") or "",
                      "codes": s_.get("gmail_codes") is not False},
            "live": len(runner.live_list())}


# --------------------------------------------------------------------------- Claude sign-in
@app.post("/api/claude/connect")
async def claude_connect():
    return await claude_login.flow.start(db.get_setting("claude_path") or "claude")


@app.get("/api/claude/connect")
async def claude_connect_state():
    return claude_login.flow.snapshot()


class CodeIn(BaseModel):
    code: str


@app.post("/api/claude/code")
async def claude_code(c: CodeIn):
    return await claude_login.flow.send_code(c.code)


@app.post("/api/claude/cancel")
async def claude_cancel():
    return await claude_login.flow.cancel()


@app.post("/api/claude/disconnect")
async def claude_disconnect():
    claude_login.disconnect()
    return {"ok": True}


# --------------------------------------------------------------------------- first run
@app.get("/api/onboarding")
async def onboarding_state():
    return await onboarding.state()


class GoalIn(BaseModel):
    goal: str = ""
    goals: list[str] = []
    categories: list[str] = []
    companies: list[str] = []


@app.post("/api/onboarding/goal")
async def onboarding_goal(g: GoalIn):
    patch = onboarding.set_goal(g.goals or g.goal or "internship", g.categories, g.companies)
    spawn_sync()
    return patch


class PrefsIn(BaseModel):
    locations: list[str] | None = None
    picky: str = ""
    concurrency: int = 0
    browser_window: str = ""
    notifications: bool | None = None
    values: list[str] | None = None


@app.post("/api/onboarding/prefs")
def onboarding_prefs(p: PrefsIn):
    return onboarding.set_prefs(p.locations, p.picky, p.concurrency, p.browser_window, p.notifications, p.values)


class AiIn(BaseModel):
    kind: str
    key: str = ""
    model: str = ""


@app.post("/api/onboarding/ai")
async def onboarding_ai(a: AiIn):
    onboarding.set_ai(a.kind, a.key, a.model)
    ok, msg = await llm.available_cached(ttl=0)
    return {"ok": ok, "message": msg, "using": llm.label(llm.backend("write"))}


class FinishIn(BaseModel):
    autonomy: str = "autopilot"
    start_now: bool = False
    final: bool = True


@app.post("/api/onboarding/finish")
def onboarding_finish(f: FinishIn):
    onboarding.finish(f.autonomy, f.start_now, f.final)
    return {"ok": True}


@app.post("/api/onboarding/restart")
def onboarding_restart():
    """Setup from step 1 again. Everything you already filled in stays; each step shows it."""
    db.set_settings({"setup_step": "restart"})
    return {"ok": True}


_start_task = None


@app.post("/api/onboarding/start")
async def onboarding_start():
    """Setup's last step: go. Applies to the companies you named and starts autopilot's first run now."""
    import asyncio
    global _start_task
    s_ = db.get_settings()
    if not s_.get("onboarded"):
        onboarding.finish(s_.get("autonomy") or "autopilot", start_now=True)
    companies = s_.get("target_companies") or []

    async def go():
        for c in companies:
            try:
                await commands.run(f"apply to {c}")
            except Exception:   # one company failing shouldn't stop the rest
                pass
        if scheduler.enabled(db.get_settings()):
            db.set_settings({"auto_last_run": time.time()})
            await scheduler.run_once("first")
    if _start_task is None or _start_task.done():
        _start_task = asyncio.create_task(go())
    db.set_settings({"setup_step": "started"})
    return {"ok": True, "companies": companies, "autopilot": scheduler.enabled(db.get_settings())}


@app.post("/api/onboarding/first-run")
async def onboarding_first_run():
    r = onboarding.first_run()
    if r.get("ok"):
        if not db.get_setting("onboarded"):
            onboarding.finish(db.get_setting("autonomy") or "autopilot")
        db.set_settings({"setup_step": "first"})
    return r


_sync_task = None


def spawn_sync() -> None:
    """Pull job lists in the background so the walkthrough never waits on GitHub."""
    import asyncio
    global _sync_task

    async def go():
        await sources.sync_all()
        match.rescore()
    if _sync_task is None or _sync_task.done():
        _sync_task = asyncio.create_task(go())


class AutopilotIn(BaseModel):
    on: bool


@app.post("/api/quota/recheck")
async def quota_recheck():
    return await llm.recheck_gemini()


@app.get("/api/skills")
def skills_list():
    return skills.listing()


class SkillIn(BaseModel):
    enabled: bool


@app.post("/api/skills/{key}")
def skills_set(key: str, b: SkillIn):
    try:
        return skills.set_enabled(key, b.enabled)
    except KeyError:
        raise HTTPException(404, "No such skill, or it can't be switched off.")


@app.get("/api/voice")
def voice_summary():
    from .skills import voice
    return voice.summary()


class VoiceIn(BaseModel):
    text: str
    title: str = ""


@app.post("/api/voice")
def voice_add(b: VoiceIn):
    from .skills import voice
    return {"added": voice.add(b.text, "pasted", b.title), **voice.summary()}


@app.post("/api/voice/upload")
async def voice_upload(file: UploadFile = File(...)):
    from .skills import voice
    dest = UPLOADS_DIR / f"voice-{int(time.time())}-{Path(file.filename or 'writing.txt').name}"
    dest.write_bytes(await file.read())
    try:
        n = voice.add_file(dest)
    except Exception as e:
        raise HTTPException(400, f"Couldn't read that file: {e}")
    return {"added": n, **voice.summary()}


@app.delete("/api/voice/{pid}")
def voice_remove(pid: int):
    from .skills import voice
    voice.remove(pid)
    return voice.summary()


class VoiceTry(BaseModel):
    question: str
    job_id: str = ""


@app.post("/api/voice/try")
def voice_try(b: VoiceTry):
    """What Jobsmith would answer from your own writing alone, with no AI."""
    from .skills import voice
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (b.job_id,))) if b.job_id else None
    job = job or {"company": "the company", "title": "", "description": ""}
    field = {"field": "try", "label": b.question, "qtype": "textarea", "options": [], "description": ""}
    return {"answer": voice.compose(job, field), "matches": voice.search(b.question, job, k=3)}


@app.get("/api/outreach")
def outreach_list():
    from .skills import outreach
    return {"companies": outreach.overview(), "kinds": outreach.KINDS, "network": network.summary()["total"]}


class DraftIn(BaseModel):
    job_id: str
    person: dict
    kind: str = "referral"


@app.post("/api/outreach/draft")
async def outreach_draft(d: DraftIn):
    from .skills import outreach
    try:
        return await outreach.draft(d.job_id, d.person, d.kind)
    except KeyError:
        raise HTTPException(404, "Job not found")


class SentIn(BaseModel):
    sent: bool = True


@app.post("/api/outreach/{draft_id}/sent")
def outreach_sent(draft_id: int, b: SentIn):
    from .skills import outreach
    outreach.mark_sent(draft_id, b.sent)
    return {"ok": True}


@app.get("/api/followups")
def followups_board():
    from .skills import followups
    return followups.board()


class FollowIn(BaseModel):
    action: str   # done | snooze | undo


@app.post("/api/followups/{job_id}")
def followups_mark(job_id: str, b: FollowIn):
    from .skills import followups
    followups.mark(job_id, b.action)
    return followups.board()


@app.post("/api/autopilot")
async def autopilot_switch(a: AutopilotIn):
    """The switch in the top right. Off stops everything in progress right away, not just new starts;
    applications already filled in and waiting for you stay open."""
    db.set_settings({"autonomy": "autopilot", "auto_run": True} if a.on else {"autonomy": "copilot", "auto_run": False})
    stopped = {"stopped": 0}
    if not a.on:
        stopped = await runner.stop()
        await power.unload_local()
    return {"on": a.on, **stopped}


class StopIn(BaseModel):
    everything: bool = True


@app.post("/api/stop")
async def stop_all(s: StopIn):
    """Stop everything: every application, the browser, and smith's hold on your GPU. Autopilot goes off."""
    db.set_settings({"autonomy": "copilot", "auto_run": False})
    r = await runner.stop(everything=s.everything)
    r["unloaded"] = await power.unload_local()
    return r


@app.get("/api/power")
async def power_status():
    return await power.status()


@app.post("/api/power/unload")
async def power_unload():
    return {"unloaded": await power.unload_local()}


@app.get("/api/smith")
async def smith_status():
    """smith, Jobsmith's own AI: what's installed, what fits this computer, and setup progress."""
    return await smith.status()


class SmithIn(BaseModel):
    model: str = ""
    allow_install: bool = True


@app.post("/api/smith/setup")
async def smith_setup(b: SmithIn):
    return smith.spawn_setup(b.model, b.allow_install)


@app.post("/api/smith/test")
async def smith_test():
    return await smith.selftest()


@app.get("/api/ai")
async def ai_options():
    """What AI Jobsmith can use on this computer right now, without being told."""
    models = await llm.ollama_models()
    s_ = db.get_settings()
    return {"detected": llm.detected(s_, models), "ollama_models": models, "ollama_url": llm.OLLAMA_URL,
            "current": s_.get("llm_backend"), "using": llm.label(llm.backend("write"))}


@app.get("/api/settings")
def get_settings():
    s = db.get_settings()
    for k in ("anthropic_api_key", "openai_api_key", "gemini_api_key", "gmail_app_password", "imap_password"):
        if s.get(k):
            s[k] = "•••• set"
    s["ms_signed_in"] = bool(s.pop("ms_refresh_token", ""))
    s["claude_connected_in_app"] = bool(s.pop("claude_oauth_token", ""))
    return s


@app.put("/api/settings")
def put_settings(body: dict):
    for k in ("anthropic_api_key", "openai_api_key", "gemini_api_key", "gmail_app_password", "imap_password"):
        if str(body.get(k, "")).startswith("••••"):
            body.pop(k)
    body.pop("claude_oauth_token", None)
    body.pop("ms_refresh_token", None)
    body.pop("ms_signed_in", None)
    db.set_settings(body)
    match.rescore()
    return get_settings()


# --------------------------------------------------------------------------- profile
@app.post("/api/profile/upload")
async def upload(file: UploadFile = File(...), slot: str = Form("resume")):
    name = Path(file.filename or "upload").name
    dest = UPLOADS_DIR / name
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    if slot == "resume_pdf" and dest.suffix.lower() != ".pdf":
        raise HTTPException(400, "The attached resume must be a PDF.")
    res = await profile.ingest_document(dest, slot)
    match.rescore()
    return res


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int):
    profile.delete_document(doc_id)
    match.rescore()
    return {"ok": True}


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: int):
    d = db.q1("SELECT filename, path FROM documents WHERE id=?", (doc_id,))
    if not d or not Path(d["path"]).exists():
        raise HTTPException(404, "file not found")
    ext = Path(d["path"]).suffix.lower()
    media = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
        ext, "text/plain; charset=utf-8")
    # inline so the dashboard can show it; text types (.tex, .txt, .md, .json) render as plain text
    return FileResponse(d["path"], media_type=media, headers={"Content-Disposition": f'inline; filename="{d["filename"]}"'})


@app.get("/api/profile")
async def get_profile():
    imported = await profile.import_profile_json()   # pick up edits made to data/profile.json
    if imported:
        match.rescore()
    return {
        "entries": profile.entries(),
        "facts": profile.facts(),
        "answers": list(profile.answers().values()),
        "documents": profile.documents(),
        "resume": profile.resume_status(),
    }


@app.put("/api/entries/{entry_id}")
def put_entry(entry_id: int, body: dict):
    profile.save_entry(body.get("kind", "experience"), body, entry_id)
    return {"ok": True}


@app.post("/api/entries")
def add_entry(body: dict):
    profile.save_entry(body.get("kind", "experience"), body)
    return {"ok": True}


@app.delete("/api/entries/{entry_id}")
def del_entry(entry_id: int):
    profile.delete_entry(entry_id)
    return {"ok": True}


class FactIn(BaseModel):
    category: str = "other"
    subject: str = ""
    text: str


@app.post("/api/facts")
def add_fact(f: FactIn):
    fid = profile.add_fact(f.category, f.text, f.subject, "user")
    return db.q1("SELECT * FROM facts WHERE id=?", (fid,))


@app.put("/api/facts/{fid}")
def edit_fact(fid: str, f: FactIn):
    db.x("UPDATE facts SET category=?, subject=?, text=?, source=CASE WHEN source='' THEN 'user' ELSE source END "
         "WHERE id=?", (f.category, f.subject, " ".join(f.text.split()), fid))
    return db.q1("SELECT * FROM facts WHERE id=?", (fid,))


@app.delete("/api/facts/{fid}")
def delete_fact(fid: str):
    db.x("UPDATE facts SET active=0 WHERE id=?", (fid,))
    return {"ok": True}


class AnswerIn(BaseModel):
    value: str
    confirmed: bool = True


def clear_confirm_issues(canon: str | None = None) -> None:
    """Once you confirm an answer, drafts that used it stop asking you to check it."""
    db.x("""UPDATE drafts SET issues='[]' WHERE kind='answer_bank' AND issues LIKE '%confirm it on the Profile page%'
            AND (? IS NULL OR canon=?)""", (canon, canon))


@app.post("/api/answers/confirm-all")
def confirm_all():
    db.x("UPDATE answers SET confirmed=1, updated_at=? WHERE value != '' AND confirmed=0", (db.now(),))
    clear_confirm_issues()
    return {"ok": True}


@app.put("/api/answers/{key}")
def put_answer(key: str, a: AnswerIn):
    profile.set_answer(key, a.value, a.confirmed)
    if a.confirmed:
        clear_confirm_issues(key)
    return profile.answers().get(key)


# --------------------------------------------------------------------------- sources
@app.get("/api/sources")
def list_sources():
    return db.q("SELECT * FROM sources ORDER BY id")


class SourceIn(BaseModel):
    url: str


@app.post("/api/sources")
async def add_source(s: SourceIn):
    src = sources.add_source(s.url)
    res = await sources.sync_source(src)
    match.rescore()
    if runner.applies_on_own() and db.get_setting("onboarded"):   # a new list on autopilot: start on its best matches
        room = min(int(db.get_setting("auto_max_per_run") or 10), commands._remaining_today())
        res["started"] = commands.queue(scheduler.pick_new_jobs(room))
    return res


@app.delete("/api/sources/{sid}")
def del_source(sid: int):
    db.x("UPDATE sources SET active=0 WHERE id=?", (sid,))
    return {"ok": True}


@app.post("/api/sources/sync")
async def sync():
    res = await sources.sync_all()
    n = match.rescore()
    return {"results": res, "scored": n}


# --------------------------------------------------------------------------- jobs
@app.get("/api/jobs")
def list_jobs(status: str = "", category: str = "", ats_name: str = "", min_score: float = 0, q: str = "",
              term: str = "", include_closed: bool = False, sort: str = "score", limit: int = 200, offset: int = 0,
              location: str = ""):
    where, params = ["1=1"], []
    if not include_closed:
        where.append("active=1")
    if status:
        where.append("status IN (%s)" % ",".join("?" * len(status.split(","))))
        params += status.split(",")
    if category:
        where.append("category LIKE ?")
        params.append(f"%{category}%")
    if ats_name:
        where.append("ats=?")
        params.append(ats_name)
    if min_score:
        where.append("COALESCE(fit_score,0)>=?")
        params.append(min_score)
    if term:
        where.append("terms LIKE ?")
        params.append(f"%{term}%")
    if location:
        where.append("locations LIKE ?")
        params.append(f"%{location}%")
    if q:
        where.append("(company LIKE ? OR title LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    order = {"score": "fit_score DESC, date_posted DESC", "posted": "date_posted DESC",
             "company": "company COLLATE NOCASE, title"}.get(sort, "fit_score DESC")
    w = " AND ".join(where)
    total = db.q1(f"SELECT COUNT(*) n FROM jobs WHERE {w}", params)["n"]
    outcomes._ensure()
    rows = db.q(f"""SELECT id, company, title, url, ats, locations, terms, category, sponsorship, date_posted,
                    fit_score, fit_reasons, status, verdict, error, outcome, hold_reason, eligibility, updated_at FROM jobs WHERE {w}
                    ORDER BY {order} LIMIT ? OFFSET ?""", params + [limit, offset])
    facets = {
        "ats": db.q(f"SELECT ats, COUNT(*) n FROM jobs WHERE {w} GROUP BY ats ORDER BY n DESC", params),
        "category": db.q(f"SELECT category, COUNT(*) n FROM jobs WHERE {w} GROUP BY category ORDER BY n DESC", params),
    }
    ids = [r["id"] for r in rows]
    tok = {r["job_id"]: r["t"] for r in db.q(
        f"SELECT job_id, SUM(input_tokens + output_tokens) t FROM usage WHERE job_id IN ({','.join('?' * len(ids))}) "
        "GROUP BY job_id", ids)} if ids else {}
    resume = insights.resume_text()
    descs = {r["id"]: r["description"] for r in db.q(
        f"SELECT id, title, description FROM jobs WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
    conns = network.counts_for([r["company"] for r in rows])
    ai_blocked = {r["job_id"] for r in db.q(
        f"SELECT DISTINCT job_id FROM drafts WHERE issues LIKE '%Needs your AI%' AND job_id IN ({','.join('?' * len(ids))})",
        ids)} if ids else set()
    bar = float(db.get_setting("min_fit_score") or 40)
    for r in rows:
        r["gate"] = guardrails.fit_gate(r, bar)
        r["ai_blocked"] = r["id"] in ai_blocked
        r["tokens"] = tok.get(r["id"], 0)
        km = insights.keyword_match({"title": r["title"], "description": descs.get(r["id"], "")}, resume)
        r["match"], r["match_hits"], r["match_total"] = km["score"], len(km["matched"]), km["total"]
        r["connections"] = conns.get(r["company"], 0)
        r["pay"] = insights.pay_of(descs.get(r["id"], ""))
    return {"total": total, "jobs": [db.decode(r) for r in rows], "facets": facets,
            "fillable": sorted(set(ats.SUPPORTED) | {"lever", "ashby", "other", "smartrecruiters", "workable"})}


class UrlIn(BaseModel):
    url: str
    company: str = ""
    title: str = ""


@app.post("/api/jobs/add-url")
async def add_url(u: UrlIn):
    jid = sources.add_job_url(u.url, u.company, u.title)
    try:
        from . import jobdetail
        await jobdetail.fetch_job(jid)
    except Exception as e:
        db.x("UPDATE jobs SET error=? WHERE id=?", (str(e)[:300], jid))
    match.rescore([jid])
    return job_or_404(jid)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    j = job_or_404(job_id)
    facts = profile.facts_by_id()
    drafts = draft.drafts_for(job_id)
    for d in drafts:
        d["facts"] = [facts[f] for f in d["fact_ids"] if f in facts]
    return {"job": j, "drafts": drafts, "runs": runner.latest_runs(job_id), "usage": job_usage(job_id),
            "match": insights.keyword_match(j), "connections": network.at_company(j["company"], 8),
            "sections": insights.posting_sections(j.get("description") or ""), "facts": insights.job_facts(j),
            "eligibility": eligibility.check(j), "ai_policy": guardrails.policy_reason(j),
            "trap": traps.trap_reason(j),
            "gate": guardrails.fit_gate(j),
            "readiness": draft.readiness(job_id) if drafts else None,
            "busy": runner.active().get(job_id), "can_fill": runner.can_fill(j["ats"])}


@app.get("/api/jobs/{job_id}/audit")
def job_audit(job_id: str):
    """What was sent in each submission of this application, field by field, and where each answer came from."""
    job_or_404(job_id)
    return {"submissions": audit.for_job(job_id)}


@app.get("/api/jobs/{job_id}/audit.json")
def job_audit_json(job_id: str):
    import re as _re
    j = job_or_404(job_id)
    name = _re.sub(r"[^A-Za-z0-9]+", "-", f"{j['company']}-{j['title']}").strip("-")[:60] or job_id
    return JSONResponse(audit.export(job_id),
                        headers={"Content-Disposition": f'attachment; filename="jobsmith-audit-{name}.json"'})


@app.post("/api/jobs/{job_id}/prepare")
async def prepare(job_id: str, research: bool | None = None):
    job_or_404(job_id)
    started = runner.spawn(job_id, "drafting", runner.prepare(job_id, research))
    return {"started": started}


class FillIn(BaseModel):
    submit: bool = False


@app.post("/api/jobs/{job_id}/fill")
async def fill(job_id: str, body: FillIn):
    job_or_404(job_id)
    started = runner.spawn(job_id, "filling", runner.fill(job_id, submit=body.submit))
    return {"started": started}


@app.post("/api/jobs/{job_id}/approve-standard")
def approve_standard(job_id: str):
    db.x("""UPDATE drafts SET verdict='green', updated_at=? WHERE job_id=? AND kind IN ('answer_bank','file')
            AND verdict IS NULL AND (answer != '' OR final_answer IS NOT NULL OR qtype='file')""", (db.now(), job_id))
    return {"ok": True}


class ReferralIn(BaseModel):
    name: str = ""
    url: str = ""


@app.post("/api/jobs/{job_id}/referral")
def set_referral(job_id: str, r: ReferralIn):
    db.x("UPDATE jobs SET referral_name=?, referral_url=?, updated_at=? WHERE id=?",
         (r.name.strip() or None, r.url.strip() or None, db.now(), job_id))
    # answers that depend on the referral must be recomputed
    db.x("DELETE FROM drafts WHERE job_id=? AND canon IN ('how_heard','referral_name') AND verdict IS NULL "
         "AND final_answer IS NULL", (job_id,))
    return job_or_404(job_id)


@app.post("/api/jobs/{job_id}/submitted")
def submitted(job_id: str):
    runner.mark_submitted(job_id)
    return {"ok": True}


class VerdictIn(BaseModel):
    verdict: str | None = None  # green | red | None
    note: str | None = None


@app.post("/api/jobs/{job_id}/verdict")
def job_verdict(job_id: str, v: VerdictIn):
    db.x("UPDATE jobs SET verdict=?, verdict_note=?, updated_at=? WHERE id=?", (v.verdict, v.note, db.now(), job_id))
    if v.verdict == "red":
        db.x("UPDATE jobs SET status='skipped' WHERE id=? AND status IN ('new','fetched','drafted')", (job_id,))
    match.rescore()
    return job_or_404(job_id)


@app.post("/api/jobs/{job_id}/status")
def set_status(job_id: str, body: dict):
    db.x("UPDATE jobs SET status=?, updated_at=? WHERE id=?", (body.get("status", "new"), db.now(), job_id))
    return job_or_404(job_id)


class DraftIn(BaseModel):
    final_answer: str | None = None
    verdict: str | None = None
    note: str | None = None
    clear_verdict: bool = False


@app.put("/api/drafts/{draft_id}")
def put_draft(draft_id: int, d: DraftIn):
    row = db.q1("SELECT * FROM drafts WHERE id=?", (draft_id,))
    if not row:
        raise HTTPException(404)
    final = row["final_answer"]
    if d.final_answer is not None:
        final = d.final_answer if d.final_answer.strip() != (row["answer"] or "").strip() else None
    verdict = None if d.clear_verdict else (d.verdict if d.verdict is not None else row["verdict"])
    if verdict == "green" and row["required"] and row["qtype"] != "file" and not (final or row["answer"] or "").strip():
        raise HTTPException(400, "This answer is empty. Write one (or click Redraft) before approving it.")
    note = d.note if d.note is not None else row["note"]
    db.x("UPDATE drafts SET final_answer=?, verdict=?, note=?, updated_at=? WHERE id=?",
         (final, verdict, note, db.now(), draft_id))
    # Answering a standard question by hand teaches the answer bank too.
    if row["canon"] and final and row["kind"] == "answer_bank" and row["canon"] not in profile.EEO_KEYS:
        if not profile.answers().get(row["canon"], {}).get("value"):
            profile.set_answer(row["canon"], final, True)
    return db.decode(db.q1("SELECT * FROM drafts WHERE id=?", (draft_id,)))


class BatchIn(BaseModel):
    action: str        # prepare | autopilot | skip | fill
    ids: list[str]


@app.post("/api/jobs/batch")
async def batch(b: BatchIn):
    started = 0
    if b.action == "skip":
        for j in b.ids:
            db.x("UPDATE jobs SET status='skipped' WHERE id=?", (j,))
        return {"started": 0, "skipped": len(b.ids)}
    for j in b.ids:
        if b.action == "prepare":
            started += runner.spawn(j, "drafting", runner.prepare(j))
        elif b.action == "fill":
            started += runner.spawn(j, "filling", runner.fill(j, submit=False))
        elif b.action == "autopilot":   # you picked these yourself, so apply even if a requirement looks off
            started += runner.spawn(j, "autopilot", runner.autopilot([j], force=True))
    return {"started": started}


@app.get("/api/jobs/{job_id}/cover-letter.pdf")
def cover_letter_pdf(job_id: str):
    from . import letters
    p = letters.cover_pdf(job_id)
    if not p:
        raise HTTPException(404, "No cover letter for this job yet.")
    return FileResponse(p, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{p.name}"'})


@app.post("/api/jobs/{job_id}/cover-letter")
async def cover_letter_write(job_id: str):
    from . import letters
    job_or_404(job_id)
    try:
        with llm.usage_for(job_id, "answers"):
            text = await letters.write_cover(job_id)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"text": text}


@app.get("/api/runs/{run_id}/screenshot")
def screenshot(run_id: int):
    p = runner.run_file(run_id, "screenshot")
    if not p:
        raise HTTPException(404)
    return FileResponse(p)


class CommandIn(BaseModel):
    text: str
    mode: str | None = None    # "autopilot" | "copilot" for this request only (the terminal's --autopilot)


@app.post("/api/command")
async def command(c: CommandIn):
    if not c.text.strip():
        raise HTTPException(400, "Tell Jobsmith what to apply to.")
    return await commands.run(c.text, c.mode)


@app.post("/api/auto/run-now")
async def auto_run_now():
    return await scheduler.run_once("manual")


@app.get("/api/commands")
def command_history():
    return commands.history()


@app.get("/api/learning")
def learning():
    return dict(learn.stats(), funnel=outcomes.funnel())


@app.post("/api/email/ms/start")
async def email_ms_start():
    from . import mail
    import asyncio as _a
    return await _a.to_thread(mail.ms_start)


@app.post("/api/email/ms/poll")
async def email_ms_poll():
    from . import mail
    import asyncio as _a
    return await _a.to_thread(mail.ms_poll)


@app.post("/api/email/ms/signout")
def email_ms_signout():
    db.set_settings({"ms_refresh_token": ""})
    return {"ok": True}


@app.post("/api/email/test")
async def email_test():
    return await outcomes.test_connection()


@app.post("/api/outcomes/check")
async def outcomes_check():
    res = await outcomes.check_inbox()
    match.rescore()
    return res


# --------------------------------------------------------------------------- home, network, companies, links, documents
@app.get("/api/home")
async def home():
    week = db.now() - 7 * 86400
    day = db.now() - 86400
    sub_q = "SELECT COUNT(*) n FROM runs WHERE kind='submit' AND status='done' AND finished_at>?"
    review = [db.decode(r) for r in db.q("""SELECT id, company, title, ats, status, hold_reason, error, fit_score, updated_at
                                             FROM jobs WHERE status IN ('filled','error') ORDER BY updated_at DESC LIMIT 30""")]
    recent = db.q("""SELECT j.id, j.company, j.title, j.outcome, r.finished_at FROM runs r JOIN jobs j ON j.id=r.job_id
                     WHERE r.kind='submit' AND r.status='done' ORDER BY r.finished_at DESC LIMIT 8""")
    srcs = db.q("SELECT id, url, kind, last_synced, last_count FROM sources WHERE active=1 ORDER BY id")
    s = db.get_settings()
    return {"applied_today": db.q1(sub_q, (day,))["n"], "applied_week": db.q1(sub_q, (week,))["n"],
            "applied_total": db.q1("SELECT COUNT(*) n FROM jobs WHERE status='submitted'")["n"],
            "in_progress": len(runner.active()), "review": review, "recent": recent, "sources": srcs,
            "queued": db.q1("""SELECT COUNT(*) n FROM jobs WHERE active=1 AND status IN ('new','fetched') AND verdict IS NULL
                               AND COALESCE(fit_score,0) >= ?""", (s.get("min_fit_score") or 40,))["n"],
            **guardrails.summary(),
            "autonomy": s.get("autonomy"), "auto_run": bool(s.get("auto_run")), "next_run": scheduler.state["next_run"],
            "last_summary": scheduler.state["last_summary"], "min_fit": s.get("min_fit_score") or 40,
            "network": network.summary()["total"],
            "first_name": (profile.answers().get("first_name") or {}).get("value") or "",
            "strength": onboarding.strength(), "started": onboarding.get_started((await llm.available_cached(role="write"))[0]),
            "stages": onboarding.stages(set(runner.active())), "email": outcomes.email_ready(),
            "gmail": s.get("gmail_address") or ""}


@app.post("/api/connections")
async def upload_connections(file: UploadFile = File(...)):
    try:
        return network.import_csv((await file.read()).decode("utf-8", errors="replace"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/linkedin")
async def upload_linkedin(file: UploadFile = File(...)):
    """LinkedIn's data export (the whole .zip, or any of its CSVs): profile, history, credentials, connections."""
    from . import linkedin
    data = await file.read()
    try:
        r = linkedin.import_archive(data, file.filename or "linkedin.zip")
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    if not r.get("ok"):
        raise HTTPException(400, r.get("message"))
    match.rescore()
    return r


@app.get("/api/connections")
def connections(company: str = ""):
    return {"summary": network.summary(), "people": network.at_company(company) if company else []}


@app.get("/api/companies")
def companies(q: str = ""):
    from . import clout
    rows = db.q("""SELECT company, COUNT(*) jobs, SUM(status='submitted') applied, MAX(fit_score) best
                   FROM jobs WHERE active=1 AND (? = '' OR company LIKE ?) GROUP BY company COLLATE NOCASE
                   LIMIT 5000""", (q, f"%{q}%"))
    # Best-known names first, then everyone else by how many roles they have open.
    for r in rows:
        r["rank"] = clout.rank(r["company"])
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, -(r["jobs"] or 0), r["company"].lower()))
    rows = rows[:200]
    conns = network.counts_for([r["company"] for r in rows])
    for r in rows:
        r["connections"] = conns.get(r["company"], 0)
        r["domain"] = insights.domain_guess(r["company"])
    return rows


@app.get("/api/companies/{name}")
def company_page(name: str):
    c = insights.company(name)
    if not c["jobs"] and not c["connections"]:
        raise HTTPException(404, "No jobs or connections at that company yet.")
    return c


@app.get("/api/links")
async def my_links(refresh: bool = False):
    return await insights.links(refresh)


@app.post("/api/links/facts")
async def link_facts():
    added = insights.add_link_facts(await insights.links())
    match.rescore()
    return {"added": added}


@app.get("/api/library")
def library():
    return insights.documents()


@app.get("/api/files/{rel:path}")
def data_file(rel: str):
    p = insights.safe_data_file(rel)
    if not p:
        raise HTTPException(404)
    media = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg"}.get(p.suffix.lower(),
                                                                                       "text/plain; charset=utf-8")
    return FileResponse(p, media_type=media, headers={"Content-Disposition": f'inline; filename="{p.name}"'})


# --------------------------------------------------------------------------- AI usage
def _usage_rows(where: str = "1=1", params: tuple = ()) -> dict:
    r = db.q1(f"""SELECT COUNT(*) calls, COALESCE(SUM(input_tokens),0) input, COALESCE(SUM(output_tokens),0) output,
                  COALESCE(SUM(cached_tokens),0) cached, COALESCE(SUM(web_searches),0) searches,
                  SUM(cost_usd) cost FROM usage WHERE {where}""", params)
    r["tokens"] = r["input"] + r["output"]
    return r


@app.get("/api/usage")
def usage():
    day = db.now() - 86400
    per_app = db.q("""SELECT job_id, SUM(input_tokens + output_tokens) tokens FROM usage
                      WHERE job_id IS NOT NULL GROUP BY job_id""")
    avg = round(sum(r["tokens"] for r in per_app) / len(per_app)) if per_app else 0
    by_purpose = db.q("""SELECT purpose, COUNT(*) calls, SUM(input_tokens + output_tokens) tokens,
                         SUM(cached_tokens) cached FROM usage GROUP BY purpose ORDER BY tokens DESC""")
    by_model = db.q("""SELECT backend, model, COUNT(*) calls, SUM(input_tokens + output_tokens) tokens, SUM(cost_usd) cost
                       FROM usage GROUP BY backend, model ORDER BY tokens DESC""")
    top = db.q("""SELECT u.job_id, j.company, j.title, SUM(u.input_tokens + u.output_tokens) tokens, SUM(u.cost_usd) cost
                  FROM usage u JOIN jobs j ON j.id = u.job_id GROUP BY u.job_id ORDER BY MAX(u.at) DESC LIMIT 30""")
    return {"today": _usage_rows("at > ?", (day,)), "all": _usage_rows(), "avg_per_app": avg,
            "apps": len(per_app), "by_purpose": by_purpose, "by_model": by_model, "recent": top}


def job_usage(job_id: str) -> dict:
    out = _usage_rows("job_id=?", (job_id,))
    out["by_purpose"] = db.q("""SELECT purpose, SUM(input_tokens + output_tokens) tokens, SUM(cached_tokens) cached,
                                SUM(web_searches) searches, SUM(cost_usd) cost FROM usage WHERE job_id=?
                                GROUP BY purpose""", (job_id,))
    return out


# --------------------------------------------------------------------------- live browser tabs
@app.get("/api/live")
def live():
    return {"tabs": runner.live_list(), "window": "visible" if runner.browser.shown else
            db.get_setting("browser_window") or "background"}


@app.get("/api/live/{job_id}/shot")
async def live_shot(job_id: str):
    b = await runner.live_shot(job_id)
    if not b:
        raise HTTPException(404)
    return Response(b, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/live/{job_id}/show")
async def live_show(job_id: str):
    r = await runner.live_show(job_id)
    return {"ok": bool(r), "pending": r == "pending", "takeover": r == "takeover"}


@app.get("/api/live/{job_id}/stream")
async def live_stream(job_id: str):
    """Live video of the form being filled: an MJPEG stream an <img> tag can show."""
    from fastapi.responses import StreamingResponse

    async def frames():
        async for jpg in runner.screencast(job_id):
            yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})


@app.post("/api/live/hide")
async def live_hide():
    return {"ok": await runner.live_hide()}


@app.post("/api/live/{job_id}/submit")
async def live_submit(job_id: str):
    return await runner.live_submit(job_id)


@app.post("/api/live/{job_id}/code")
async def live_code(job_id: str, c: CodeIn):
    return await runner.live_code(job_id, c.code)


@app.post("/api/live/{job_id}/close")
async def live_close(job_id: str):
    page = (runner.LIVE.get(job_id) or {}).get("page")
    if page is not None and not page.is_closed():
        await page.close()
    runner.live_drop(job_id)
    return {"ok": True}


# --------------------------------------------------------------------------- Chrome extension
class ExtFill(BaseModel):
    url: str
    title: str = ""
    company: str = ""
    site_name: str = ""
    fields: list[dict] = []


class ExtSave(BaseModel):
    url: str
    title: str = ""
    company: str = ""
    site_name: str = ""
    apply: bool = False


@app.get("/api/ext/install")
def ext_install():
    from .config import EXTENSION_DIR
    seen = float(db.get_setting("ext_seen") or 0)
    return {"path": str(EXTENSION_DIR), "exists": (EXTENSION_DIR / "manifest.json").exists(), "seen": seen or None}


@app.post("/api/ext/open-install")
def ext_open_install():
    from . import extension
    return extension.open_install()


@app.get("/api/ext/ping")
async def ext_ping():
    s_ = db.get_settings()
    if db.now() - float(s_.get("ext_seen") or 0) > 3600:
        db.set_settings({"ext_seen": db.now()})
    ok, msg = await llm.available_cached(role="write")
    pdf = profile.attachment_file()
    return {"ok": True, "name": "Jobsmith", "onboarded": bool(s_.get("onboarded")), "ai": llm.label(llm.backend("write")),
            "ai_ok": ok, "resume": pdf.name if pdf else None, "autonomy": s_.get("autonomy")}


@app.post("/api/ext/answers")
async def ext_answers(b: ExtFill):
    from . import extension
    with llm.usage_for(None, "answers"):
        return await extension.answers(b.url, b.fields, b.title, b.company, b.site_name)


@app.get("/api/ext/file/{kind}")
def ext_file(kind: str, job_id: str = ""):
    from . import extension
    f = extension.file_for(kind, job_id)
    if f is None:
        raise HTTPException(404, "No file for that yet. Add your resume PDF in Profile.")
    if isinstance(f, str):     # a cover letter's text
        return Response(f.encode(), media_type="text/plain", headers={"X-Filename": "Cover letter.txt"})
    return FileResponse(f, media_type="application/pdf", headers={"X-Filename": f.name})


@app.post("/api/ext/save")
async def ext_save(b: ExtSave):
    """'Send to Jobsmith' from a posting: add it, read it, score it, and (if asked) apply with autopilot."""
    from . import extension, jobdetail
    jid = extension.find_or_add(b.url, b.title, b.company or extension.company_guess(b.url, b.site_name))
    try:
        await jobdetail.fetch_job(jid)
    except Exception as e:
        db.x("UPDATE jobs SET error=? WHERE id=?", (str(e)[:300], jid))
    match.rescore([jid])
    started = runner.spawn(jid, "autopilot", runner.autopilot([jid], force=True)) if b.apply else False
    j = job_or_404(jid)
    return {"job_id": jid, "company": j["company"], "title": j["title"], "fit": j.get("fit_score"),
            "eligibility": eligibility.check(j), "started": bool(started)}


class ExtContext(BaseModel):
    url: str
    title: str = ""
    site_name: str = ""
    text: str = ""


@app.post("/api/ext/context")
def ext_context(b: ExtContext):
    from . import extension
    return extension.context(b.url, b.title, b.site_name, b.text[:20000])


class ExtGenerate(BaseModel):
    url: str
    label: str
    title: str = ""
    site_name: str = ""
    description: str = ""
    limit: int = 0


@app.post("/api/ext/generate")
async def ext_generate(b: ExtGenerate):
    from . import extension
    with llm.usage_for(None, "answers"):
        return await extension.generate(b.url, b.label, b.title, b.site_name, b.description, b.limit)


@app.post("/api/ext/submitted")
def ext_submitted(b: ExtSave):
    from . import extension
    return extension.submitted(b.url, b.title, b.site_name)


# --------------------------------------------------------------------------- dashboard
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


@app.get("/{path:path}")
def spa(path: str):
    index = WEB_DIST / "index.html"
    if path.startswith("api/"):
        return JSONResponse({"detail": "not found"}, status_code=404)
    if index.exists():
        f = WEB_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(index)
    return JSONResponse({"detail": "Dashboard not built. Run: cd web && npm install && npm run build"})
