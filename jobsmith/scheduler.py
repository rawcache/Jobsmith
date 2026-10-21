"""Unattended mode: every few hours, pull the job lists, score them, and start the best new matches.
Runs inside the Jobsmith process, so it works while Jobsmith is open (laptop awake)."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time

from . import commands, db, match, power, runner, sources

_task: asyncio.Task | None = None
state = {"last_run": None, "next_run": None, "last_summary": ""}


def notify(title: str, message: str) -> None:
    """A desktop notification on macOS, Windows or Linux. Silently does nothing if the system has no way to show one."""
    if not db.get_setting("notifications"):
        return
    safe = lambda t: t.replace("\\", "").replace('"', "'").replace("`", "'")[:200]
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    try:
        if shutil.which("osascript"):
            subprocess.Popen(["osascript", "-e", f'display notification "{safe(message)}" with title "{safe(title)}"'], **quiet)
        elif os.name == "nt" and shutil.which("powershell"):
            ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
                  "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
                  "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                  f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode(\"{safe(title)}\")) > $null;"
                  f"$t.GetElementsByTagName('text')[1].AppendChild($t.CreateTextNode(\"{safe(message)}\")) > $null;"
                  "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
                  "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe')"
                  ".Show([Windows.UI.Notifications.ToastNotification]::new($t))")
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps], **quiet)
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", safe(title), safe(message)], **quiet)
    except OSError:
        pass


def pick_new_jobs(limit: int) -> list[str]:
    s = db.get_settings()
    rows = db.q("""SELECT id, company, ats, fit_score FROM jobs WHERE active=1 AND status IN ('new','fetched','drafted')
                   AND verdict IS NULL AND COALESCE(fit_score,0) >= ? AND eligibility NOT LIKE '%"ok": false%'
                   ORDER BY status='drafted' DESC, fit_score DESC, date_posted DESC LIMIT 400""", (s.get("min_fit_score") or 40,))
    # Network hiccups ("too slow", "couldn't reach") get two more tries, an hour apart.
    rows += db.q("""SELECT j.id, j.company, j.ats, j.fit_score FROM jobs j WHERE j.active=1 AND j.status='error'
                    AND j.updated_at < ? AND (j.error LIKE '%imeout%' OR j.error LIKE '%nodename%' OR j.error LIKE '%ERR_%'
                         OR j.error LIKE '%onnect%' OR j.error LIKE '%name or service%')
                    AND (SELECT COUNT(*) FROM runs r WHERE r.job_id=j.id AND r.status='error') < 3""",
                 (time.time() - 3600,))
    per_company: dict[str, int] = {}
    for r in db.q("SELECT company, COUNT(*) n FROM jobs WHERE status IN ('submitted','filling','filled','drafted') "
                  "GROUP BY company"):
        per_company[r["company"]] = r["n"]
    out = []
    # fillable sites first; multi-step sites only get drafted
    rows.sort(key=lambda r: (not runner.can_fill(r["ats"]), -(r["fit_score"] or 0)))
    for r in rows:
        cap = int(s.get("max_applications_per_company") or 0)
        if cap > 0 and per_company.get(r["company"], 0) >= cap:
            continue
        out.append(r["id"])
        per_company[r["company"]] = per_company.get(r["company"], 0) + 1
        if len(out) >= limit:
            break
    return out


async def run_once(reason: str = "scheduled") -> dict:
    from .config import DEMO
    if DEMO:
        state.update(last_run=time.time(), last_summary="Demo mode: nothing is checked or sent.")
        return {"summary": state["last_summary"], "started": []}
    s = db.get_settings()
    results = await sources.sync_all()
    match.rescore()
    new = sum(r.get("added", 0) for r in results)
    room = min(int(s.get("auto_max_per_run") or 10), commands._remaining_today())
    picked = pick_new_jobs(room)
    # Autopilot may have been switched off while the lists were syncing: then only look, don't start.
    from . import llm
    waiting_ai = llm.gemini_limited() and not llm._local_ok() and db.get_setting("llm_backend") in ("gemini_api", "auto")
    go = (reason == "manual" or enabled(db.get_settings())) and not power.paused() and not waiting_ai
    started = commands.queue(picked) if go else []
    from . import outcomes
    if outcomes.email_ready():
        o = await outcomes.check_inbox()
        if o.get("new_outcomes"):
            notify("Jobsmith: replies", f"{o['new_outcomes']} new replies from companies (see Jobs).")
    summary = (f"Synced {len(results)} list{'s' if len(results) != 1 else ''} ({new} new postings). "
               + (f"Started {len(started)} application{'s' if len(started) != 1 else ''}." if go else
                  "Waiting for Gemini's free limit to reset before applying." if waiting_ai else
                  "Paused: on battery." if power.paused() else "Autopilot is off, so nothing was started."))
    state.update(last_run=time.time(), last_summary=summary)
    commands._ensure_table()
    db.x("INSERT INTO commands(text, result, created_at) VALUES(?,?,?)",
         (f"[{reason} run]", json.dumps({"log": [summary], "started": started, "found": len(picked)}), db.now()))
    if started:
        notify("Jobsmith", summary)
    return {"summary": summary, "started": started}


def enabled(s: dict) -> bool:
    """Runs on its own only when you turned it on and finished setting up (never on a fresh install)."""
    return bool(s.get("auto_run") and s.get("onboarded"))


async def _loop() -> None:
    while True:
        try:
            s = db.get_settings()
            if enabled(s):
                interval = max(1.0, float(s.get("auto_interval_hours") or 6)) * 3600
                last = state["last_run"] or float(s.get("auto_last_run") or 0)
                state["next_run"] = last + interval
                if time.time() >= last + interval:
                    await run_once()
                    db.set_settings({"auto_last_run": time.time()})
                    state["next_run"] = (state["last_run"] or time.time()) + interval
            else:
                state["next_run"] = None
        except Exception as e:  # never let the loop die
            state["last_summary"] = f"Last scheduled run failed: {e}"
        await asyncio.sleep(60)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
