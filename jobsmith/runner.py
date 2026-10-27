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

from . import db, draft, guardrails, jobdetail, profile
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
    """Chrome, driven by Playwright.

    The main browser runs headless when the browser is set to work in the background (the default): it
    never opens a window, so it can't pull you away from what you're doing, and it doesn't draw anything to
    your screen, which saves a lot of energy. You watch any application live in the dashboard instead.
    'Take over' opens that application in a real window (the takeover browser, which shares your sign-ins)."""

    def __init__(self, kind: str = "main"):
        self.kind = kind
        self._pw = None
        self.ctx = None
        self.ctx_headless: bool | None = None
        self.ua: str | None = None
        self._lock = asyncio.Lock()

    def want_headless(self) -> bool:
        if self.kind == "takeover":
            return False
        s = db.get_settings()
        return bool(s.get("headless")) or (s.get("browser_window") or "background") != "visible"

    async def context(self):
        async with self._lock:
            want = self.want_headless()
            if self.ctx is not None and self.ctx_headless != want and not any(not p.is_closed() for p in self.ctx.pages[1:]):
                await self._close_ctx()          # the window setting changed and nothing is open: relaunch to match
            if self.ctx is not None:
                return self.ctx
            from playwright.async_api import async_playwright
            s = db.get_settings()
            if self._pw is None:
                self._pw = await async_playwright().start()
            profile = BROWSER_PROFILE if self.kind == "main" else BROWSER_PROFILE.parent / "browser-profile-window"
            args = ["--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                    "--disable-background-timer-throttling"] if not want else []
            from .fill.base import browser_args
            kw = dict(user_data_dir=str(profile), headless=want, viewport={"width": 1280, "height": 900},
                      accept_downloads=True, args=args + browser_args())
            if os.environ.get("JOBSMITH_CHROMIUM_PATH"):
                kw["executable_path"] = os.environ["JOBSMITH_CHROMIUM_PATH"]
            # "chromium" (or your Chrome) runs Chrome's new headless mode: the same browser, not a stripped-down one.
            channel = s.get("browser_channel") or ("chromium" if want else None)
            try:
                self.ctx = await self._pw.chromium.launch_persistent_context(channel=channel, **kw)
            except Exception:
                self.ctx = await self._pw.chromium.launch_persistent_context(**kw)
            self.ctx_headless = want
            ctx = self.ctx
            ctx.on("close", lambda _c: setattr(self, "ctx", None) if self.ctx is ctx else None)
            if self.kind == "takeover" and browser.ctx is not None:
                try:                              # your sign-ins from the background browser come along
                    await ctx.add_cookies(await browser.ctx.cookies())
                except Exception:
                    pass
            return self.ctx

    async def _user_agent(self, page) -> str | None:
        """Headless Chrome says 'HeadlessChrome' in its user agent; some sites treat that differently."""
        if self.ua is None:
            try:
                self.ua = (await page.evaluate("navigator.userAgent")).replace("HeadlessChrome", "Chrome")
            except Exception:
                return None
        return self.ua

    async def set_window(self, page, state: str) -> bool:
        """state: 'minimized' | 'normal'. Uses Chrome's DevTools window API (windows only exist when headed)."""
        if self.ctx_headless:
            return False
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
        ctx = await self.context()
        page = await ctx.new_page()
        if self.ctx_headless:
            ua = await self._user_agent(page)
            if ua:
                try:
                    cdp = await ctx.new_cdp_session(page)
                    await cdp.send("Network.setUserAgentOverride", {"userAgent": ua})
                except Exception:
                    pass
        elif self.kind == "main" and db.get_setting("browser_window") != "visible" and not self.shown:
            await self.set_window(page, "minimized")
        elif self.shown:
            # You're watching one application: a new tab opening for another one shouldn't steal the view.
            watched = (LIVE.get(self.focus_job) or {}).get("page") if self.focus_job else None
            if watched is not None and not watched.is_closed():
                try:
                    await watched.bring_to_front()
                except Exception:
                    pass
        return page

    shown = False            # True after you click Show, until you click Hide
    focus_job: str | None = None   # the application you asked to watch

    async def _close_ctx(self):
        try:
            if self.ctx:
                await self.ctx.close()
        except Exception:
            pass
        self.ctx = None
        self.ua = None

    async def close(self):
        # On Ctrl+C the terminal also stops Chrome, so it may already be gone.
        await self._close_ctx()
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self._pw = None


browser = Browser()
takeover = Browser("takeover")     # a real window, opened only when you ask to take over


# --------------------------------------------------------------------------- live tabs ("peek")
LIVE: dict[str, dict] = {}   # job_id -> {page, phase, note, needs_code, since, shot, shot_at, run_dir}
PHASES = {"opening": "opening the form", "filling": "filling", "review": "ready for you",
          "code": "needs the emailed code", "submitting": "submitting", "submitted": "submitted",
          "error": "stopped"}


WATCH: set[str] = set()   # applications you asked to see that hadn't opened a tab yet


def live_set(job_id: str, page=None, **kw) -> None:
    cur = LIVE.setdefault(job_id, {"since": time.time(), "needs_code": False, "note": ""})
    if page is not None:
        cur["page"] = page
        if job_id in WATCH:           # you asked to watch this one before its tab existed: show it now
            WATCH.discard(job_id)
            try:
                asyncio.get_running_loop().create_task(live_show(job_id))
            except RuntimeError:
                pass
    cur.update(kw)


def live_drop(job_id: str) -> None:
    LIVE.pop(job_id, None)


def live_list() -> list[dict]:
    out = []
    for jid, v in list(LIVE.items()):
        page = v.get("page")
        gone = page is None or page.is_closed()
        # showcase.py's practice entries never have a tab: list them while they play or wait for you, and let a
        # submitted one expire like any other
        if gone and (not v.get("practice") or v.get("phase") == "submitted"):
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


async def _shot(page, path, full: bool = True) -> bool:
    """A record of the page. Never worth failing an application over: a slow page just gets no picture."""
    try:
        await page.screenshot(path=str(path), full_page=full, timeout=10000)
        return True
    except Exception:
        try:
            await page.screenshot(path=str(path), timeout=5000)
            return True
        except Exception:
            return False


async def live_shot(job_id: str) -> bytes | None:
    """A small JPEG of what the tab shows right now (cached for a second)."""
    v = LIVE.get(job_id)
    if not v:
        return None
    # Pages waiting for you barely change: refresh those rarely, the ones being filled every couple of seconds.
    from . import power
    fresh_for = 15.0 if v.get("phase") in ("review", "code", "submitted", "error") else 2.0
    if power.saver():
        fresh_for *= 6                   # battery saver: previews refresh rarely
    if v.get("shot") and time.time() - v.get("shot_at", 0) < fresh_for:
        return v["shot"]
    page = v.get("page")
    if page is None or page.is_closed():
        return v.get("shot")
    try:
        # Some forms scroll sideways while fields are filled; the preview should show the page from its left edge.
        await page.evaluate("() => { if (window.scrollX) window.scrollTo(0, window.scrollY); }")
        v["shot"] = await page.screenshot(type="jpeg", quality=50, timeout=4000, scale="css")
        v["shot_at"] = time.time()
    except Exception:
        pass
    return v.get("shot")


async def screencast(job_id: str):
    """Smooth live video of a tab being filled (Chrome's screencast), as JPEG frames. Runs only while someone
    is watching, and works in the background (headless) browser too."""
    import base64
    page = (LIVE.get(job_id) or {}).get("page")
    if page is None or page.is_closed():
        return
    cdp = await page.context.new_cdp_session(page)
    q: asyncio.Queue = asyncio.Queue(maxsize=2)
    last = None

    def on_frame(params):
        asyncio.create_task(cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]}))
        if q.full():
            q.get_nowait()
        q.put_nowait(base64.b64decode(params["data"]))
    cdp.on("Page.screencastFrame", on_frame)
    await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 60, "maxWidth": 1280, "maxHeight": 900})
    try:
        while not page.is_closed():
            try:
                last = await asyncio.wait_for(q.get(), timeout=5)
            except asyncio.TimeoutError:
                if last is None:
                    last = await page.screenshot(type="jpeg", quality=60, timeout=4000)
            yield last                   # a still page sends no frames: repeat the last so the stream stays open
    finally:
        try:
            await cdp.send("Page.stopScreencast")
            await cdp.detach()
        except Exception:
            pass


async def take_over(job_id: str) -> bool:
    """Open this application in a real window so you can finish it yourself. In the background (headless)
    browser there's no window to show, so Jobsmith fills it again in the takeover window, stopping before Submit."""
    v = LIVE.get(job_id) or {}
    task = _by_job.get(job_id)
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    page = v.get("page")
    if page is not None and not page.is_closed():
        try:
            await page.close()
        except Exception:
            pass
    live_drop(job_id)
    _active.pop(job_id, None)
    return spawn(job_id, "filling", fill(job_id, submit=False, visible=True))


async def live_show(job_id: str | None) -> bool | str:
    """Bring the browser window up on this application. If it's still being researched (no tab yet),
    remember it and show it the moment its form opens. Returns 'pending' in that case.
    When the browser works in the background (headless), this opens the application in a window instead."""
    page = (LIVE.get(job_id) or {}).get("page") if job_id else None
    if job_id and browser.ctx_headless and page is not None and not page.is_closed():
        return "takeover" if await take_over(job_id) else False
    if (page is None or page.is_closed()) and job_id:
        WATCH.add(job_id)
        browser.focus_job = job_id
        return "pending"
    if page is None or page.is_closed():
        ctx = browser.ctx
        page = ctx.pages[0] if ctx and ctx.pages else None
    if page is None:
        return False
    browser.shown = True
    browser.focus_job = job_id
    return await browser.set_window(page, "normal")


async def live_hide() -> bool:
    ctx = browser.ctx
    if not ctx or not ctx.pages:
        return False
    browser.shown = False
    browser.focus_job = None
    WATCH.clear()
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
    from .config import DEMO
    if DEMO:
        return {"ok": False, "message": "Demo mode: in your real Jobsmith this types the code into the form and submits it."}
    page = (LIVE.get(job_id) or {}).get("page")
    if page is None or page.is_closed():
        return {"ok": False, "message": "That tab is closed."}
    ok = await enter_security_code(page, code)
    if not ok:
        return {"ok": False, "message": "Couldn't find the code boxes. Click Show and type it in the browser."}
    live_set(job_id, needs_code=False, phase="submitting", note="Code entered")
    res = await live_submit(job_id)
    return {"ok": True, "submitted": res["ok"]}
_tasks: set[asyncio.Task] = set()
_active: dict[str, str] = {}   # job_id -> what's running


class _Slots:
    """How many forms fill at once. Reads the setting each time, so changing it applies right away."""

    def __init__(self):
        self.busy = 0
        self.cond: asyncio.Condition | None = None

    def limit(self) -> int:
        from . import power
        if power.saver():
            return 1                      # battery saver: one application at a time
        return max(1, min(8, int(db.get_setting("concurrency") or 3)))

    async def __aenter__(self):
        if self.cond is None:
            self.cond = asyncio.Condition()
        async with self.cond:
            await self.cond.wait_for(lambda: self.busy < self.limit())
            self.busy += 1

    async def __aexit__(self, *a):
        async with self.cond:
            self.busy -= 1
            self.cond.notify_all()


_slots = _Slots()


def _sem() -> _Slots:
    return _slots


def spawn(job_id: str, label: str, coro) -> bool:
    from .config import DEMO
    if DEMO:                      # demo data: never open a real site
        coro.close()
        db.x("UPDATE jobs SET status='filled', hold_reason=?, updated_at=? WHERE id=?",
             ("Demo mode: no real site was opened", db.now(), job_id))
        return False
    if job_id in _active:
        coro.close()
        return False
    _active[job_id] = label

    async def wrapper():
        try:
            await coro
        finally:
            _active.pop(job_id, None)
            _by_job.pop(job_id, None)
    t = asyncio.create_task(wrapper())
    _tasks.add(t)
    _by_job[job_id] = t
    t.add_done_callback(_tasks.discard)
    return True


_by_job: dict[str, asyncio.Task] = {}


async def stop(everything: bool = False) -> dict:
    """The off switch. Stops every application Jobsmith is working on, right now: AI calls are cancelled
    (a local model stops generating when its request goes away) and their tabs close. Applications already
    filled in and waiting for you stay open, unless `everything`, which also closes the browser."""
    stopped = []
    for jid, task in list(_by_job.items()):
        waiting = (LIVE.get(jid) or {}).get("phase") in WAITING
        if waiting and not everything:
            continue
        task.cancel()
        stopped.append(jid)
    if stopped:
        await asyncio.gather(*(_by_job.get(j) or asyncio.sleep(0) for j in stopped), return_exceptions=True)
    for jid in stopped:
        _active.pop(jid, None)
        _by_job.pop(jid, None)
        WATCH.discard(jid)
        v = LIVE.get(jid) or {}
        page = v.get("page")
        if page is not None and not page.is_closed() and (everything or v.get("phase") not in WAITING):
            try:
                await page.close()
            except Exception:
                pass
            live_drop(jid)
        st = (db.q1("SELECT status FROM jobs WHERE id=?", (jid,)) or {}).get("status")
        if st in ("filling", "fetched", "new", "drafted") and not guardrails.maybe_sent(jid):
            db.x("UPDATE jobs SET status=?, hold_reason=?, updated_at=? WHERE id=?",
                 ("drafted" if st in ("filling", "drafted") else st, "Stopped by you", db.now(), jid))
    db.x("UPDATE runs SET status='error', log=log || ?, finished_at=? WHERE status='running'",
         ("\nStopped by you.", db.now()))
    if everything:
        for t in list(_tasks):
            t.cancel()
        await browser.close()
        await takeover.close()
        LIVE.clear()
    return {"stopped": len(stopped)}


WAITING = ("review", "code", "submitted", "error")
STEPS = ["Reading the posting", "Writing answers", "Filling the form", "Ready for you", "Submitted"]


def progress(job_id: str) -> dict:
    """Where one application is, as step n of 5, for progress bars in the dashboard and the terminal."""
    phase = (LIVE.get(job_id) or {}).get("phase")
    j = db.q1("SELECT status, research, description FROM jobs WHERE id=?", (job_id,)) or {}
    st = j.get("status")
    if st == "submitted" or phase == "submitted":
        n = 4
    elif phase in ("review", "code") or st == "filled":
        n = 3
    elif phase in ("opening", "filling", "submitting") or st == "filling":
        n = 2
    elif st == "drafted":
        n = 2 if job_id in _active else 3
    elif j.get("research") not in (None, "", "{}") or j.get("description"):
        n = 1
    else:
        n = 0
    label = STEPS[n]
    if n == 2 and phase not in ("opening", "filling", "submitting") and st == "drafted":
        label = "Waiting for a free browser slot"
    return {"step": n, "total": len(STEPS) - 1, "label": label}


def active() -> dict[str, str]:
    """Applications Jobsmith is working on right now. One that's filled in and waiting for you (or done)
    isn't 'working' anymore, even though its tab is still being watched for the confirmation page."""
    out = {}
    for jid, label in _active.items():
        if (LIVE.get(jid) or {}).get("phase") in WAITING:
            continue
        st = (db.q1("SELECT status FROM jobs WHERE id=?", (jid,)) or {}).get("status")
        if st in ("filled", "submitted", "skipped", "error"):
            continue
        out[jid] = "filling" if st == "filling" else ("drafting" if label in ("drafting", "autopilot") and st != "filling" else label)
    return out


def _set_status(job_id: str, status: str, error: str | None = None) -> None:
    if status == "submitted":
        db.x("UPDATE jobs SET hold_reason=NULL WHERE id=?", (job_id,))
    db.x("UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?", (status, error, db.now(), job_id))


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


async def fill(job_id: str, submit: bool = False, visible: bool = False) -> None:
    """Fill the form in a visible browser tab. Submits only if `submit` and the job is ready."""
    from .fill import greenhouse, generic
    from .fill.base import SUBMIT_SELECTORS, captcha_visible, page_confirms_submission
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    run = Run(job_id, "fill")
    if not can_fill(job["ats"]):
        run.log(f"{job['ats']} uses a multi-page flow. Turn on 'Multi-page sites (beta)' in Settings, "
                "or fill it yourself. Opening it for you.")
        page = await (takeover if visible or browser.want_headless() else browser).new_page()
        live_set(job_id, page, phase="review", note="multi-page site: fill it yourself")
        await page.goto(job["url"])
        run.done("waiting_user")
        return
    if is_multistep(job["ats"]):
        run.done("done")
        await fill_multistep(job_id, submit)
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
    from . import letters
    cl = letters.cover_pdf(job_id, run_dir)      # a formatted PDF of the letter (yours, if you edited it)
    if cl:
        files["cover_letter"] = str(cl)
        run.log(f"Attaching your cover letter ({cl.name}).")
    (run_dir / "answers.json").write_text(json.dumps(drafts_, indent=2))

    _set_status(job_id, "filling")
    watch = False
    async with _sem():
        page = await (takeover if visible else browser).new_page()
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
                # Country (from citizenship) and Hispanic/Latino come only from answers you confirmed (rule 2).
                ok = lambda k: v(k) if (ans.get(k) or {}).get("confirmed") else ""
                extras = {"country": ok("country") or ("United States" if ok("us_citizen").lower() == "yes" else ""),
                          "hispanic_latino": ok("hispanic_latino"),
                          "location_full": f"{loc.split(',')[0].strip()}, {st}, United States" if st else loc}
                result = await adapter.fill(page, drafts_, files, extras)
                live_set(job_id, phase="filling", note="checking the page for anything else")
                from .fill.sweep import sweep
                try:
                    more = await asyncio.wait_for(sweep(page, job, run.log), timeout=150)
                except Exception as e:  # a second pass is a bonus, never a reason to fail
                    run.log(f"Second pass skipped ({e.__class__.__name__})")
                    more = {"filled": [], "failed": [], "sent": []}
                result["filled"] += more["filled"]
                result["sent"] = result.get("sent", []) + more.get("sent", [])
                # a field the main pass missed but the sweep filled isn't a failure anymore
                done = {l for l, _ in more["filled"]}
                result["failed"] = [x for x in result["failed"] if x[0] not in done] + more["failed"]
            else:
                result = await adapter.fill(page, drafts_, files)
            for label, why in result["failed"]:
                run.log(f"  ✗ {label}: {why}")
            run.log(f"Filled {len(result['filled'])} fields, {len(result['failed'])} need you")
            from . import audit
            audit.capture(job_id, set(result.get("sent", [])), result.get("implicit"))   # what this fill set
            live_set(job_id, phase="review",
                     note=(f"{len(result['failed'])} field(s) need you: " + ", ".join(f[0] for f in result["failed"][:3]))
                     if result["failed"] else "all fields filled")
            if visible:
                await takeover.set_window(page, "normal")      # you asked for it: bring the window up
            shot = run_dir / "filled.png"
            await _shot(page, shot)
            ready = draft.readiness(job_id)
            capped = None
            if submit:
                try:
                    page_text = await page.locator("body").inner_text(timeout=5000)
                except Exception:
                    page_text = ""
                capped = guardrails.policy_reason(job, page_text) or guardrails.cap_reason(job)
            auto = submit and ready["ready"] and not result["failed"] and not capped
            if submit and not auto:
                why = ([capped] if capped else []) + (ready["blockers"] or [])[:3] + \
                    [f"{f[0]}: couldn't fill it" for f in result["failed"]][:3]
                run.log("Held for your review: " + "; ".join(why))
                db.x("UPDATE jobs SET hold_reason=? WHERE id=?", ("; ".join(why)[:500], job_id))
            if auto:
                run.log("All answers trusted; submitting…")
                live_set(job_id, phase="submitting")
                btn = None
                for sel in SUBMIT_SELECTORS:
                    b = page.locator(sel).first
                    if await b.count() and await b.is_visible():
                        btn = b
                        break
                # Checked again with nothing awaited before the claim, so tabs finishing together can't pass a cap.
                late = guardrails.cap_reason(job) if btn else "couldn't find the Submit button"
                if late:
                    run.log("Held for your review: " + late)
                    db.x("UPDATE jobs SET hold_reason=? WHERE id=?", (late, job_id))
                    live_set(job_id, phase="review", note=late[:120])
                    auto = False
                else:
                    guardrails.claim(job_id)   # counted toward the caps from the click on
                    await btn.click()
                    await page.wait_for_timeout(4000)
            if auto:
                if await captcha_visible(page):
                    run.log("CAPTCHA shown: solve it in the browser window; Jobsmith is waiting.")
                    live_set(job_id, phase="review", note="CAPTCHA to solve: take over to finish it")
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
        except asyncio.CancelledError:
            guardrails.abandon(job_id, "stopped while submitting")
            raise
        except Exception as e:
            run.log("ERROR " + "".join(traceback.format_exception_only(type(e), e)).strip())
            run.done("error")
            if not guardrails.abandon(job_id, f"stopped by an error: {e.__class__.__name__}"):
                _set_status(job_id, "error", str(e)[:500])   # (if it may have been sent, it waits for you instead)
            live_set(job_id, phase="error", note=str(e)[:120])
            try:
                await _shot(page, run_dir / "error.png", full=False)
            except Exception:
                pass

    if watch:
        await watch_tab(job_id, page, run_dir, run)


async def watch_tab(job_id: str, page, run_dir: Path, run: Run) -> None:
    """Outside the concurrency slot: watch the tab until you (or Jobsmith) submit. Spots the
    'we emailed you a code' step and asks you for the code instead of leaving you guessing."""
    job = db.q1("SELECT company, title FROM jobs WHERE id=?", (job_id,)) or {}
    deadline = time.time() + 45 * 60
    try:
        await _watch(job_id, page, run_dir, run, job, deadline)
    finally:
        guardrails.abandon(job_id, "no confirmation page before the tab closed")   # no-op unless autopilot clicked Submit and nothing confirmed


async def _watch(job_id: str, page, run_dir: Path, run: Run, job: dict, deadline: float) -> None:
    from .fill.base import page_confirms_submission, security_code_prompt
    from .scheduler import notify
    from . import outcomes
    asked = notified = False
    asked_at = last_mail = 0.0
    tried: set[str] = set()
    while time.time() < deadline:
        try:
            if page.is_closed():
                break
            if await page_confirms_submission(page):
                await _shot(page, run_dir / "confirmation.png")
                record_submission(job_id, "Confirmation page detected.", screenshot=str(run_dir / "confirmation.png"),
                                  snapshot=str(run_dir / "answers.json"))
                live_set(job_id, phase="submitted", needs_code=False, note="")
                run.log("Submitted ✓")
                await live_shot(job_id)
                await asyncio.sleep(3)
                await page.close()
                break
            prompt = await security_code_prompt(page)
            if prompt and not asked:
                asked = True
                asked_at = time.time()
                tried: set[str] = set()
                live_set(job_id, phase="code", needs_code=True, note=prompt)
                if outcomes.email_ready():
                    run.log(f"Verification step: {prompt}. Looking for the code in your email.")
                else:
                    run.log(f"Verification step: {prompt}. Paste the code into Jobsmith (or the browser).")
                    notify("Jobsmith needs a code", f"{job.get('company', '')}: check your email for the verification code.")
            if prompt and asked and outcomes.email_ready() and time.time() - asked_at < 10 * 60 \
                    and time.time() - last_mail >= 12:
                last_mail = time.time()
                code = await outcomes.find_code(job.get("company", ""), asked_at)
                if code and code not in tried:
                    tried.add(code)
                    run.log("Found the code in your email and entered it.")
                    await live_code(job_id, code)
                    continue
                if time.time() - asked_at > 4 * 60 and not notified:
                    notified = True
                    notify("Jobsmith needs a code", f"{job.get('company', '')}: no code in your inbox yet. Paste it in Jobsmith when it arrives.")
            elif not prompt and asked and LIVE.get(job_id, {}).get("needs_code"):
                asked = False
                live_set(job_id, needs_code=False, phase="submitting")
        except Exception:
            break
        await asyncio.sleep(2)


def record_submission(job_id: str, note: str, **files) -> None:
    """Every submission goes through here: counted toward the caps, logged, and its audit trail written from the
    answers as they stood when it was sent."""
    from . import audit
    by = "autopilot" if guardrails.release(job_id) else "you"
    sub = Run(job_id, "submit")
    sub.log(note)
    sub.done("done", **files)
    audit.record(job_id, sub.id, by)
    _set_status(job_id, "submitted")


def mark_submitted(job_id: str) -> None:
    record_submission(job_id, "Marked submitted by you.")


async def autopilot(job_ids: list[str], force: bool = False, submit: bool | None = None) -> None:
    """End to end for a batch: prepare each job, then fill (and submit when trusted + autonomous).
    Jobs you don't qualify for are skipped with the reason, unless you picked them yourself (force)."""
    from . import eligibility
    autonomous = applies_on_own() if submit is None else submit

    async def one(jid):
        if not force:            # the fit gate: autopilot's own picks only, never one you chose
            gate = guardrails.fit_gate(db.q1("SELECT fit_score, fit_reasons FROM jobs WHERE id=?", (jid,)) or {})
            if not gate["passed"]:
                db.x("UPDATE jobs SET hold_reason=?, updated_at=? WHERE id=?", (gate["summary"], db.now(), jid))
                return
        if autonomous and not force:
            capped = guardrails.cap_reason(db.q1("SELECT id, company FROM jobs WHERE id=?", (jid,)) or {"id": jid})
            if capped:          # left as it is: autopilot picks it up again once there's room
                return
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
    resume = profile.attachment_file()
    files = {"resume": str(resume)} if resume else {}
    tr = profile.transcript_file()
    if tr:
        files["transcript"] = str(tr)
    trust = {"ok": True}
    held: list[str] = []
    seen: list[str] = []            # every page's text, for the employer's AI policy
    sent: set[str] = set()          # every field actually set, for the audit trail

    def may_submit() -> bool:
        """Checked at the review page, right before the Submit click."""
        if not (submit and trust["ok"]):
            return False
        capped = guardrails.policy_reason(job, "\n".join(seen)) or guardrails.cap_reason(job)
        if capped:
            held.append(capped)
            run.log("Held for your review: " + capped)
            db.x("UPDATE jobs SET hold_reason=? WHERE id=?", (capped, job_id))
            return False
        guardrails.claim(job_id)
        from . import audit
        audit.capture(job_id, sent)      # exactly the fields it set, on every page
        return True
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
        page = await (takeover if browser.want_headless() else browser).new_page()   # you may need to sign in
        live_set(job_id, page, phase="filling", note="multi-page", needs_code=False, run_dir=str(run_dir))
        try:
            run.log(f"Opening {job.get('referral_url') or job['url']} (multi-page beta)")
            res = await multistep.run(page, job.get("referral_url") or job["url"], answer=answer, files=files,
                                      log=run.log, wait_for_user=wait_for_user,
                                      allow_submit=may_submit, on_page=seen.append, on_filled=sent.add)
            shot = run_dir / "filled.png"
            await _shot(page, shot)
            db.x("UPDATE runs SET screenshot=? WHERE id=?", (str(shot), run.id))
            if res["status"] == "review":         # every page answered: keep what was put in, for when you submit
                from . import audit
                audit.capture(job_id, sent)
            for i in res["issues"][:6]:
                run.log(f"  ✗ {i}")
            if res["status"] in ("submitted", "submitted_clicked"):
                from .fill.base import page_confirms_submission
                if res["status"] == "submitted" or await page_confirms_submission(page):
                    record_submission(job_id, "Submitted through the multi-page flow.", screenshot=str(shot))
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
        except asyncio.CancelledError:
            guardrails.abandon(job_id, "stopped while submitting")
            raise
        except Exception as e:
            run.log("ERROR " + "".join(traceback.format_exception_only(type(e), e)).strip())
            run.done("error")
            if not guardrails.abandon(job_id, f"stopped by an error: {e.__class__.__name__}"):
                _set_status(job_id, "error", str(e)[:500])   # (if it may have been sent, it waits for you instead)
