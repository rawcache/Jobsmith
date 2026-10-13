"""Background work: a small in-process queue that drafts and fills applications in parallel.

Browser: a persistent Chrome profile under data/browser-profile. It's a real (headed) Chrome, but by
default its window stays minimized: the dashboard shows a live picture of each tab ("peek"), and
"Show" brings the window up when you want to take over (CAPTCHA, final review, Submit)."""
from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
from pathlib import Path

from . import db, draft, jobdetail, profile
from .config import BROWSER_PROFILE, RUNS_DIR

MULTI_STEP = {"workday", "icims", "oracle", "taleo", "successfactors", "eightfold"}


def applies_on_own() -> bool:
    """Autopilot (and the older 'autonomous' name for it) submits without waiting for you."""
    return db.get_setting("autonomy") in ("autopilot", "autonomous")


def can_fill(ats_name: str) -> bool:
    """Single-page forms Jobsmith fills directly. Multi-step sites go through the beta multi-page engine."""
    return ats_name not in MULTI_STEP or bool(db.get_setting("multistep_beta"))


def is_multistep(ats_name: str) -> bool:
    return ats_name in MULTI_STEP


# --------------------------------------------------------------------------- run log
class Run:
    def __init__(self, job_id: str, kind: str):
        self.id = db.x("INSERT INTO runs(job_id, kind, status, started_at) VALUES(?,?,?,?)",
                       (job_id, kind, "running", db.now()))
        self.lines: list[str] = []

    def log(self, msg: str) -> None:
        self.lines.append(time.strftime("%H:%M:%S ") + msg)
        db.x("UPDATE runs SET log=? WHERE id=?", ("\n".join(self.lines), self.id))

    def done(self, status: str = "done", **extra) -> None:
        sets = {"status": status, "finished_at": db.now(), **extra}
        cols = ", ".join(f"{k}=?" for k in sets)
        db.x(f"UPDATE runs SET {cols} WHERE id=?", (*sets.values(), self.id))


# --------------------------------------------------------------------------- browser
class Browser:
    def __init__(self):
        self._pw = None
        self.ctx = None
        self._lock = asyncio.Lock()

    async def context(self):
        async with self._lock:
            if self.ctx is not None:
                return self.ctx
            from playwright.async_api import async_playwright
            s = db.get_settings()
            if self._pw is None:
                self._pw = await async_playwright().start()
            kw = dict(user_data_dir=str(BROWSER_PROFILE), headless=bool(s.get("headless")),
                      viewport={"width": 1280, "height": 900}, accept_downloads=True)
            if os.environ.get("JOBSMITH_CHROMIUM_PATH"):
                kw["executable_path"] = os.environ["JOBSMITH_CHROMIUM_PATH"]
            try:
                self.ctx = await self._pw.chromium.launch_persistent_context(
                    channel=s.get("browser_channel") or None, **kw)
            except Exception:
                self.ctx = await self._pw.chromium.launch_persistent_context(**kw)
            ctx = self.ctx
            # If you close the browser window, open a fresh one next time instead of failing.
            ctx.on("close", lambda _c: setattr(self, "ctx", None) if self.ctx is ctx else None)
            return self.ctx

    async def set_window(self, page, state: str) -> bool:
        """state: 'minimized' | 'normal'. Uses Chrome's DevTools window API."""
        try:
            s = await page.context.new_cdp_session(page)
            w = await s.send("Browser.getWindowForTarget")
            if state == "normal":
                await s.send("Browser.setWindowBounds", {"windowId": w["windowId"], "bounds": {"windowState": "normal"}})
                await page.bring_to_front()
            else:
                await s.send("Browser.setWindowBounds", {"windowId": w["windowId"], "bounds": {"windowState": state}})
            await s.detach()
            return True
        except Exception:
            return False

    async def new_page(self):
        """A new tab; in background mode the window goes back down unless you're looking at it."""
        ctx = await self.context()
        page = await ctx.new_page()
        if db.get_setting("browser_window") != "visible" and not self.shown and not db.get_setting("headless"):
            await self.set_window(page, "minimized")
        return page

    shown = False   # True after you click Show, until you click Hide

    async def close(self):
        # On Ctrl+C the terminal also stops Chrome, so it may already be gone.
        for step in (lambda: self.ctx and self.ctx.close(), lambda: self._pw and self._pw.stop()):
            try:
                aw = step()
                if aw:
                    await aw
            except Exception:
                pass
        self.ctx = self._pw = None


browser = Browser()


# --------------------------------------------------------------------------- live tabs ("peek")
LIVE: dict[str, dict] = {}   # job_id -> {page, phase, note, needs_code, since, shot, shot_at, run_dir}
PHASES = {"opening": "opening the form", "filling": "filling", "review": "ready for you",
          "code": "needs the emailed code", "submitting": "submitting", "submitted": "submitted",
          "error": "stopped"}


def live_set(job_id: str, page=None, **kw) -> None:
    cur = LIVE.setdefault(job_id, {"since": time.time(), "needs_code": False, "note": ""})
    if page is not None:
        cur["page"] = page
    cur.update(kw)


def live_drop(job_id: str) -> None:
    LIVE.pop(job_id, None)


def live_list() -> list[dict]:
    out = []
    for jid, v in list(LIVE.items()):
        page = v.get("page")
        if page is None or page.is_closed():
            if v.get("phase") not in ("submitted",) or time.time() - v.get("since", 0) > 600:
                LIVE.pop(jid, None)
                continue
        job = db.q1("SELECT company, title, status FROM jobs WHERE id=?", (jid,)) or {}
        out.append({"job_id": jid, "company": job.get("company", ""), "title": job.get("title", ""),
                    "phase": v.get("phase", ""), "phase_label": PHASES.get(v.get("phase", ""), v.get("phase", "")),
                    "note": v.get("note", ""), "needs_code": bool(v.get("needs_code")),
                    "url": page.url if page is not None and not page.is_closed() else "",
                    "since": v.get("since")})
    return sorted(out, key=lambda r: r["since"] or 0)


async def live_shot(job_id: str) -> bytes | None:
    """A small JPEG of what the tab shows right now (cached for a second)."""
    v = LIVE.get(job_id)
    if not v:
        return None
    if v.get("shot") and time.time() - v.get("shot_at", 0) < 1.0:
        return v["shot"]
    page = v.get("page")
    if page is None or page.is_closed():
        return v.get("shot")
    try:
        v["shot"] = await page.screenshot(type="jpeg", quality=55, timeout=4000)
        v["shot_at"] = time.time()
    except Exception:
        pass
    return v.get("shot")


async def live_show(job_id: str | None) -> bool:
    page = (LIVE.get(job_id) or {}).get("page") if job_id else None
    if page is None or page.is_closed():
        ctx = browser.ctx
        page = ctx.pages[0] if ctx and ctx.pages else None
    if page is None:
        return False
    browser.shown = True
    return await browser.set_window(page, "normal")


async def live_hide() -> bool:
    ctx = browser.ctx
    if not ctx or not ctx.pages:
        return False
    browser.shown = False
    return await browser.set_window(ctx.pages[0], "minimized")


async def live_submit(job_id: str) -> dict:
    """You clicked Submit in Jobsmith: click the form's submit button for you."""
    from .fill.base import SUBMIT_SELECTORS
    page = (LIVE.get(job_id) or {}).get("page")
    if page is None or page.is_closed():
        return {"ok": False, "message": "That tab is closed."}
    for sel in SUBMIT_SELECTORS:
        btn = page.locator(sel).first
        try:
            if await btn.count() and await btn.is_visible():
                await btn.click(timeout=5000)
                live_set(job_id, phase="submitting", note="Submit clicked")
                return {"ok": True}
        except Exception:
            continue
    return {"ok": False, "message": "Couldn't find a Submit button. Click Show and submit it yourself."}


async def live_code(job_id: str, code: str) -> dict:
    """Type the verification code you got by email into the form, then submit again."""
    from .fill.base import enter_security_code
    page = (LIVE.get(job_id) or {}).get("page")
    if page is None or page.is_closed():
        return {"ok": False, "message": "That tab is closed."}
    ok = await enter_security_code(page, code)
    if not ok:
        return {"ok": False, "message": "Couldn't find the code boxes. Click Show and type it in the browser."}
    live_set(job_id, needs_code=False, phase="submitting", note="Code entered")
    res = await live_submit(job_id)
    return {"ok": True, "submitted": res["ok"]}
_fill_sem: asyncio.Semaphore | None = None
_tasks: set[asyncio.Task] = set()
_active: dict[str, str] = {}   # job_id -> what's running


def _sem() -> asyncio.Semaphore:
    global _fill_sem
    if _fill_sem is None:
        _fill_sem = asyncio.Semaphore(int(db.get_setting("concurrency") or 2))
    return _fill_sem


def spawn(job_id: str, label: str, coro) -> bool:
    if job_id in _active:
        coro.close()
        return False
    _active[job_id] = label

    async def wrapper():
        try:
            await coro
        finally:
            _active.pop(job_id, None)
    t = asyncio.create_task(wrapper())
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return True


def active() -> dict[str, str]:
    return dict(_active)


def _set_status(job_id: str, status: str, error: str | None = None) -> None:
    if status == "submitted":
        db.x("UPDATE jobs SET hold_reason=NULL WHERE id=?", (job_id,))
    db.x("UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?", (status, error, db.now(), job_id))


# --------------------------------------------------------------------------- limits
def limit_check(job: dict) -> str | None:
    s = db.get_settings()
    day_ago = time.time() - 86400
    today = db.q1("SELECT COUNT(*) n FROM runs WHERE kind='submit' AND status='done' AND finished_at>?", (day_ago,))["n"]
    if today >= int(s["max_applications_per_day"]):
        return f"Daily limit reached ({today}/{s['max_applications_per_day']})"
    same = db.q1("SELECT COUNT(*) n FROM jobs WHERE company=? AND status='submitted' AND id!=?",
                 (job["company"], job["id"]))["n"]
    if same >= int(s["max_applications_per_company"]):
        return f"Already applied to {same} roles at {job['company']} (limit {s['max_applications_per_company']})"
    return None


# --------------------------------------------------------------------------- steps
async def do_scan(job: dict, run: Run) -> list[dict]:
    """Discover the form's fields by opening it in the browser (non-Greenhouse ATSes)."""
    from .fill import generic
    page = await browser.new_page()
    try:
        fields = await generic.scan(page, job["url"])
        fields = [f for f in fields if f["qtype"] != "hidden"]
        db.x("UPDATE jobs SET questions=?, updated_at=? WHERE id=?", (db.enc(fields), db.now(), job["id"]))
        if not job.get("description"):
            body = await page.locator("body").inner_text()
            db.x("UPDATE jobs SET description=? WHERE id=?", (body[:20000], job["id"]))
        run.log(f"Scanned form: {len(fields)} fields")
        return fields
    finally:
        await page.close()


async def prepare(job_id: str, research: bool | None = None) -> None:
    """fetch -> (scan) -> research -> draft"""
    run = Run(job_id, "draft")
    try:
        job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
        scan_needed = job["ats"] != "greenhouse"
        if not job["description"] and not job["questions"]:
            run.log("Fetching posting…")
            try:
                job = await jobdetail.fetch_job(job_id)
            except jobdetail.BoardNotFound as e:
                run.log(f"{e}; reading the form in the browser instead")
                scan_needed = True
        if scan_needed and not job["questions"] and not is_multistep(job["ats"]):
            run.log("Opening the application form to read its questions…")
            async with _sem():
                try:
                    await do_scan(job, run)
                except Exception as e:
                    run.log(f"Scan failed ({e}); drafting common questions instead")
        from . import llm
        run.log(f"Researching with {llm.label(llm.backend('research'))}; writing with {llm.label(llm.backend('write'))}…")
        res = await draft.draft_job(job_id, research=research, log=run.log)
        run.log(f"Drafted {res['drafted']} fields" + (f" (AI error: {res['error']})" if res["error"] else ""))
        run.done()
    except Exception as e:
        run.log("ERROR " + "".join(traceback.format_exception_only(type(e), e)).strip())
        run.done("error")
        _set_status(job_id, "error", str(e)[:500])


def _drafts_for_fill(job_id: str) -> list[dict]:
    job = db.decode(db.q1("SELECT questions FROM jobs WHERE id=?", (job_id,)))
    meta = {q["field"]: q for q in job["questions"] or []}
    out = []
    for d in draft.drafts_for(job_id):
        if d["verdict"] == "red" and not d.get("final_answer"):
            continue
        m = meta.get(d["field"], {})
        out.append({"field": d["field"], "label": d["label"], "qtype": m.get("qtype", d["qtype"]),
                    "required": bool(d["required"]), "value": draft.final_value(d),
                    "alt_field": m.get("alt_field")})
    return out


async def fill(job_id: str, submit: bool = False) -> None:
    """Fill the form in a visible browser tab. Submits only if `submit` and the job is ready."""
    from .fill import greenhouse, generic
    from .fill.base import SUBMIT_SELECTORS, captcha_visible, page_confirms_submission
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    run = Run(job_id, "fill")
    if not can_fill(job["ats"]):
        run.log(f"{job['ats']} uses a multi-page flow. Turn on 'Multi-page sites (beta)' in Settings, "
                "or fill it yourself. Opening it for you.")
        page = await browser.new_page()
        live_set(job_id, page, phase="review", note="multi-page site: fill it yourself")
        await page.goto(job["url"])
        run.done("waiting_user")
        return
    if is_multistep(job["ats"]):
        run.done("done")
        await fill_multistep(job_id, submit)
        return
    blocked = limit_check(job)
    if blocked:
        run.log(blocked)
        run.done("error")
        _set_status(job_id, job["status"], blocked)
        return
    resume = profile.attachment_file()
    if not resume:
        run.log("Upload a PDF resume in Profile first (it's what gets attached).")
        run.done("error")
        return
    run_dir = RUNS_DIR / f"{job_id}-{int(time.time())}"
    run_dir.mkdir(parents=True, exist_ok=True)
    from . import tailor
    tailored = tailor.tailored_pdf(job, run_dir, resume.name)
    if tailored:
        run.log("Using a tailored copy of your resume (same content, most relevant bullets first).")
        resume = tailored
    if draft.questions_stale(job):
        job = await draft.refresh_questions(job_id, run.log)
    files = {"resume": str(resume)}
    tr = profile.transcript_file()
    if tr and any("transcript" in (d["label"] + d["field"]).lower() and d["required"] for d in _drafts_for_fill(job_id)):
        files["transcript"] = str(tr)
    drafts_ = _drafts_for_fill(job_id)
    cover = next((d for d in drafts_ if "cover" in (d["field"] + d["label"]).lower() and d["value"]), None)
    if cover:
        cl = run_dir / "cover_letter.txt"
        cl.write_text(cover["value"])
        files["cover_letter"] = str(cl)
    (run_dir / "answers.json").write_text(json.dumps(drafts_, indent=2))

    _set_status(job_id, "filling")
    watch = False
    async with _sem():
        page = await browser.new_page()
        live_set(job_id, page, phase="opening", note="", needs_code=False, run_dir=str(run_dir))
        try:
            adapter = greenhouse if job["ats"] == "greenhouse" else generic
            url = job.get("referral_url") or job["url"]
            run.log(f"Opening {url}" + (" (your referral link)" if job.get("referral_url") else ""))
            await adapter.open_form(page, url)
            live_set(job_id, phase="filling")
            if adapter is greenhouse:
                ans = profile.answers()
                v = lambda k: (ans.get(k) or {}).get("value", "")
                from .draft import state_from_location
                loc = v("location")
                st = state_from_location(loc)
                extras = {"country": v("country") or ("United States" if v("us_citizen").lower() == "yes" else ""),
                          "hispanic_latino": v("hispanic_latino"),
                          "location_full": f"{loc.split(',')[0].strip()}, {st}, United States" if st else loc}
                result = await adapter.fill(page, drafts_, files, extras)
            else:
                result = await adapter.fill(page, drafts_, files)
            for label, why in result["failed"]:
                run.log(f"  ✗ {label}: {why}")
            run.log(f"Filled {len(result['filled'])} fields, {len(result['failed'])} need you")
            live_set(job_id, phase="review",
                     note=(f"{len(result['failed'])} field(s) need you: " + ", ".join(f[0] for f in result["failed"][:3]))
                     if result["failed"] else "all fields filled")
            shot = run_dir / "filled.png"
            await page.screenshot(path=str(shot), full_page=True)
            ready = draft.readiness(job_id)
            auto = submit and ready["ready"] and not result["failed"]
            if submit and not auto:
                why = (ready["blockers"] or [])[:3] + [f"{f[0]}: couldn't fill it" for f in result["failed"]][:3]
                run.log("Held for your review: " + "; ".join(why))
                db.x("UPDATE jobs SET hold_reason=? WHERE id=?", ("; ".join(why)[:500], job_id))
            if auto:
                run.log("All answers trusted; submitting…")
                live_set(job_id, phase="submitting")
                for sel in SUBMIT_SELECTORS:
                    btn = page.locator(sel).first
                    if await btn.count() and await btn.is_visible():
                        await btn.click()
                        break
                await page.wait_for_timeout(4000)
                if await captcha_visible(page):
                    run.log("CAPTCHA shown: solve it in the browser window; Jobsmith is waiting.")
                    from .scheduler import notify
                    notify("Jobsmith needs you", f"Solve the CAPTCHA for {job['company']} in the Jobsmith browser window.")
            else:
                run.log("Stopped before submit. Review the tab, then click Submit yourself.")
                from .scheduler import notify
                notify("Jobsmith: ready for you", f"{job['company']}: {job['title']} is filled in. Review it and click Submit.")
            db.x("UPDATE runs SET screenshot=?, snapshot=? WHERE id=?",
                 (str(shot), str(run_dir / "answers.json"), run.id))
            _set_status(job_id, "filled")
            run.done("waiting_user")
            watch = True
        except Exception as e:
            run.log("ERROR " + "".join(traceback.format_exception_only(type(e), e)).strip())
            run.done("error")
            _set_status(job_id, "error", str(e)[:500])
            live_set(job_id, phase="error", note=str(e)[:120])
            try:
                await page.screenshot(path=str(run_dir / "error.png"))
            except Exception:
                pass

    if watch:
        await watch_tab(job_id, page, run_dir, run)


async def watch_tab(job_id: str, page, run_dir: Path, run: Run) -> None:
    """Outside the concurrency slot: watch the tab until you (or Jobsmith) submit. Spots the
    'we emailed you a code' step and asks you for the code instead of leaving you guessing."""
    from .fill.base import page_confirms_submission, security_code_prompt
    from .scheduler import notify
    job = db.q1("SELECT company, title FROM jobs WHERE id=?", (job_id,)) or {}
    asked = False
    deadline = time.time() + 45 * 60
    while time.time() < deadline:
        try:
            if page.is_closed():
                break
            if await page_confirms_submission(page):
                await page.screenshot(path=str(run_dir / "confirmation.png"), full_page=True)
                sub = Run(job_id, "submit")
                sub.log("Confirmation page detected.")
                sub.done("done", screenshot=str(run_dir / "confirmation.png"),
                         snapshot=str(run_dir / "answers.json"))
                _set_status(job_id, "submitted")
                live_set(job_id, phase="submitted", needs_code=False, note="")
                run.log("Submitted ✓")
                await live_shot(job_id)
                await asyncio.sleep(3)
                await page.close()
                break
            prompt = await security_code_prompt(page)
            if prompt and not asked:
                asked = True
                live_set(job_id, phase="code", needs_code=True, note=prompt)
                run.log(f"Verification step: {prompt}. Paste the code into Jobsmith (or the browser).")
                notify("Jobsmith needs a code", f"{job.get('company', '')}: check your email for the verification code.")
            elif not prompt and asked and LIVE.get(job_id, {}).get("needs_code"):
                asked = False
                live_set(job_id, needs_code=False, phase="submitting")
        except Exception:
            break
        await asyncio.sleep(2)


def mark_submitted(job_id: str) -> None:
    sub = Run(job_id, "submit")
    sub.log("Marked submitted by you.")
    sub.done("done")
    _set_status(job_id, "submitted")


async def autopilot(job_ids: list[str], force: bool = False, submit: bool | None = None) -> None:
    """End to end for a batch: prepare each job, then fill (and submit when trusted + autonomous).
    Jobs you don't qualify for are skipped with the reason, unless you picked them yourself (force)."""
    from . import eligibility
    autonomous = applies_on_own() if submit is None else submit

    async def one(jid):
        await prepare(jid)
        full = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
        el = eligibility.check(full)
        db.x("UPDATE jobs SET eligibility=? WHERE id=?", (db.enc(el), jid))
        if not el["ok"] and not force:
            db.x("UPDATE jobs SET status='skipped', hold_reason=?, updated_at=? WHERE id=?",
                 ("Skipped, you may not qualify: " + "; ".join(el["reasons"]), db.now(), jid))
            return
        job = db.q1("SELECT status, ats FROM jobs WHERE id=?", (jid,))
        if job["status"] == "drafted" and can_fill(job["ats"]):
            await fill(jid, submit=autonomous)
    await asyncio.gather(*(one(j) for j in job_ids))


def latest_runs(job_id: str, n: int = 10) -> list[dict]:
    return db.q("SELECT * FROM runs WHERE job_id=? ORDER BY id DESC LIMIT ?", (job_id, n))


def run_file(run_id: int, which: str) -> Path | None:
    r = db.q1("SELECT * FROM runs WHERE id=?", (run_id,))
    p = r and r.get(which)
    return Path(p) if p and Path(p).exists() else None


async def fill_multistep(job_id: str, submit: bool = False) -> None:
    """Workday-style flows: answer each page as it appears, stop at review (or submit when trusted)."""
    from . import draft, learn
    from .fill import multistep
    from .scheduler import notify
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    run = Run(job_id, "fill")
    blocked = limit_check(job)
    if blocked:
        run.log(blocked)
        run.done("error")
        return
    resume = profile.attachment_file()
    files = {"resume": str(resume)} if resume else {}
    tr = profile.transcript_file()
    if tr:
        files["transcript"] = str(tr)
    trust = {"ok": True}
    threshold = int(db.get_setting("trust_threshold") or 3)

    async def answer(fields: list[dict]) -> dict:
        for f in fields:
            f.setdefault("description", "")
        locked = {d["field"]: draft.final_value(d) for d in draft.drafts_for(job_id) if draft.is_locked(d)}
        results, err = await draft.answer_fields(job, [f for f in fields if f["field"] not in locked])
        draft.save_results(job_id, [f for f in fields if f["field"] not in locked], results)
        out = dict(locked)
        for fid, r in results.items():
            out[fid] = r.get("answer", "")
            if r.get("issues") or (r["kind"] == "generated" and learn.trust_for(
                    next((f["label"] for f in fields if f["field"] == fid), "")) < threshold):
                trust["ok"] = False
        if err:
            run.log(f"AI unavailable: {err}")
        return out

    async def wait_for_user(message: str, check, negate: bool = False) -> bool:
        notify("Jobsmith needs you", f"{job['company']}: {message}")
        deadline = time.time() + 15 * 60
        while time.time() < deadline:
            r = await check()
            if (not r) if negate else r:
                return True
            await asyncio.sleep(3)
        return False

    _set_status(job_id, "filling")
    run_dir = RUNS_DIR / f"{job_id}-{int(time.time())}"
    run_dir.mkdir(parents=True, exist_ok=True)
    async with _sem():
        page = await browser.new_page()
        live_set(job_id, page, phase="filling", note="multi-page", needs_code=False, run_dir=str(run_dir))
        try:
            run.log(f"Opening {job.get('referral_url') or job['url']} (multi-page beta)")
            res = await multistep.run(page, job.get("referral_url") or job["url"], answer=answer, files=files,
                                      log=run.log, wait_for_user=wait_for_user,
                                      allow_submit=lambda: submit and trust["ok"])
            shot = run_dir / "filled.png"
            await page.screenshot(path=str(shot), full_page=True)
            db.x("UPDATE runs SET screenshot=? WHERE id=?", (str(shot), run.id))
            for i in res["issues"][:6]:
                run.log(f"  ✗ {i}")
            if res["status"] in ("submitted", "submitted_clicked"):
                from .fill.base import page_confirms_submission
                if res["status"] == "submitted" or await page_confirms_submission(page):
                    sub = Run(job_id, "submit")
                    sub.log("Submitted through the multi-page flow.")
                    sub.done("done", screenshot=str(shot))
                    _set_status(job_id, "submitted")
                    notify("Jobsmith: submitted", f"{job['company']}: {job['title']}")
                    live_set(job_id, phase="submitted", note="")
                    run.done("done")
                    return
            _set_status(job_id, "filled")
            run.log("Stopped for you: review the browser tab and click Submit when ready."
                    if res["status"] == "review" else "Stopped: this page needs you.")
            notify("Jobsmith: ready for you", f"{job['company']}: {job['title']} needs a look.")
            live_set(job_id, phase="review", note="review the last page" if res["status"] == "review"
                     else "; ".join(res["issues"][:2]) or "this page needs you")
            run.done("waiting_user")
            t = asyncio.create_task(watch_tab(job_id, page, run_dir, run))
            _tasks.add(t)
            t.add_done_callback(_tasks.discard)
        except Exception as e:
            run.log("ERROR " + "".join(traceback.format_exception_only(type(e), e)).strip())
            run.done("error")
            _set_status(job_id, "error", str(e)[:500])
