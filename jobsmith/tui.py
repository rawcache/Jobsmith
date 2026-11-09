"""Jobsmith in the terminal.

    jobsmith                      open the prompt (sets you up the first time)
    jobsmith "apply to nvidia"    one request, then watch it work
    jobsmith --autopilot ...      submit whatever it's confident about without asking (this run only)
    jobsmith smith                set up smith, the free AI that runs on this computer
    jobsmith extension            add Jobsmith to Chrome
    jobsmith status | watch | review | init | web | serve

The terminal is a client of the same local engine the website uses, so both always show the same thing.
If the engine isn't running, this starts it in the background.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

from . import prompts as P
from .config import DATA_DIR

console = Console(highlight=False)
PORT = int(os.environ.get("JOBSMITH_PORT", "8765"))
BASE = os.environ.get("JOBSMITH_URL", f"http://127.0.0.1:{PORT}")
ACCENT = "#5b8def"
SPIN = "·✢✳✶✻✽✻✶✳✢"


class Engine:
    """Talks to the local Jobsmith engine over HTTP."""

    def __init__(self, base: str = BASE):
        self.base = base.rstrip("/")
        self.http = httpx.Client(base_url=self.base, timeout=httpx.Timeout(300, connect=2))

    def up(self) -> bool:
        try:
            return self.http.get("/api/status", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def ensure(self) -> None:
        if self.up():
            from .config import BUILD
            try:
                running = self.http.get("/api/status", timeout=5).json().get("build")
            except (httpx.HTTPError, ValueError):
                running = None
            if running == BUILD:
                return
            # An engine from before you updated Jobsmith is still running: swap it for this version.
            with console.status("Restarting Jobsmith's engine with the new version…", spinner="dots"):
                try:
                    self.http.post("/api/shutdown", timeout=5)
                except httpx.HTTPError:
                    pass
                for _ in range(40):
                    time.sleep(0.25)
                    if not self.up():
                        break
                else:
                    _stop_old_engine(PORT)     # too old to know /api/shutdown
                    for _ in range(40):
                        time.sleep(0.25)
                        if not self.up():
                            break
        log = open(DATA_DIR / "server.log", "a")
        args = [sys.executable, "-m", "jobsmith", "serve", "--no-open", "--port", str(PORT)]
        kw: dict = {"stdout": log, "stderr": log, "stdin": subprocess.DEVNULL}
        if os.name == "nt":
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008   # DETACHED_PROCESS
        else:
            kw["start_new_session"] = True
        subprocess.Popen(args, **kw)
        with console.status("Starting Jobsmith's engine…", spinner="dots"):
            for _ in range(60):
                time.sleep(0.5)
                if self.up():
                    return
        console.print(f"[red]The engine didn't start.[/] See {DATA_DIR / 'server.log'}")
        sys.exit(1)

    def _send(self, method: str, path: str, **kw) -> httpx.Response:
        """One request; if the engine went away, say why, start it again and retry once."""
        try:
            return self.http.request(method, path, **kw)
        except httpx.TransportError:
            time.sleep(1)
            if self.up():                      # a blip: the engine is fine
                return self.http.request(method, path, **kw)
            tail = _log_tail(DATA_DIR / "crash.log") or _log_tail(DATA_DIR / "server.log")
            console.print("[yellow]The engine stopped unexpectedly. Restarting it.[/]"
                          + (f"\n[dim]{tail}[/]" if tail else ""))
            self.ensure()
            return self.http.request(method, path, **kw)

    def get(self, path: str, **params):
        r = self._send("GET", path, params=params or None)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict | None = None, **kw):
        r = (self._send("POST", path, json=body if body is not None else {}, **kw) if "files" not in kw
             else self._send("POST", path, **kw))
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail") or r.text
            except ValueError:
                detail = r.text or f"HTTP {r.status_code}"
            raise RuntimeError(detail)
        return r.json()

    def put(self, path: str, body: dict):
        r = self._send("PUT", path, json=body)
        r.raise_for_status()
        return r.json()


def _stop_old_engine(port: int) -> None:
    """Stop whatever Jobsmith (or wyzard) engine is listening on our port. Never touches other programs."""
    import signal
    pids: list[int] = []
    try:
        if os.name == "nt":
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  f"(Get-NetTCPConnection -LocalPort {port} -State Listen).OwningProcess"],
                                 capture_output=True, text=True, timeout=10).stdout
        else:
            out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                                 capture_output=True, text=True, timeout=10).stdout
        pids = [int(x) for x in out.split() if x.strip().isdigit()]
    except (OSError, subprocess.SubprocessError):
        return
    for pid in pids:
        try:
            if os.name == "nt":
                cmd = subprocess.run(["powershell", "-NoProfile", "-Command",
                                      f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                                     capture_output=True, text=True, timeout=10).stdout
            else:
                cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
            if re.search(r"jobsmith|wyzard", cmd, re.I):
                os.kill(pid, signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass


# --------------------------------------------------------------------------- small helpers
def _log_tail(path: Path, lines: int = 6) -> str:
    """The end of the engine's log, minus noise: usually the error that stopped it."""
    try:
        text = path.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    keep = [l for l in text if l.strip() and "GET /api" not in l][-lines:]
    return "\n".join(keep).replace("[", "\\[")


class Keys:
    """Single keypresses without Enter, for the live view. Does nothing when stdin isn't a terminal."""

    def __enter__(self):
        self.ok = sys.stdin.isatty()
        self.old = None
        if self.ok and os.name != "nt":
            import termios
            import tty
            self.old = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, *a):
        if self.old is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old)

    def get(self, timeout: float) -> str | None:
        if not self.ok:
            time.sleep(timeout)
            return None
        if os.name == "nt":
            import msvcrt
            end = time.time() + timeout
            while time.time() < end:
                if msvcrt.kbhit():
                    return msvcrt.getwch()
                time.sleep(0.05)
            return None
        import select
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if r else None


def tok(n) -> str:
    n = n or 0
    return str(n) if n < 1000 else f"{n / 1000:.1f}k" if n < 10_000 else f"{n // 1000}k"


def ask(prompt: str, default: str = "") -> str:
    try:
        v = console.input(f"[bold]{prompt}[/] " + (f"[dim]({default})[/] " if default else ""))
    except EOFError:
        return default
    return v.strip() or default


def yes(prompt: str, default: bool = True) -> bool:
    if P.interactive():
        return P.confirm(prompt, default)
    v = ask(prompt + (" \\[Y/n]" if default else " \\[y/N]")).lower()
    return default if not v else v.startswith("y")


def select(prompt: str, options: list[tuple], default=None):
    return P.select(prompt, options, default)


def checkbox(prompt: str, options: list[tuple], checked: list) -> list:
    return P.multiselect(prompt, options, checked)


def choose(prompt: str, options: list[str], default: int = 1) -> int:
    for i, o in enumerate(options, 1):
        console.print(f"  [{ACCENT}]{i}[/] {o}")
    while True:
        v = ask(prompt, str(default))
        if v.isdigit() and 1 <= int(v) <= len(options):
            return int(v) - 1
        console.print("[dim]Pick a number from the list.[/]")


def header(e: Engine) -> None:
    """A small card at the top: what's writing, whether autopilot is on, today's numbers, anything urgent."""
    from rich import box
    from rich.panel import Panel
    s = e.get("/api/status")
    h = e.get("/api/home")
    on = s["autonomy"] != "copilot" and s["auto"]["on"]
    ai = s["llm"]["writing"]
    q = s.get("quota")
    line1 = Text.assemble(("● " if ai["ok"] else "○ ", "green" if ai["ok"] else "yellow"),
                          (ai["label"] if ai["ok"] else "No AI connected (/smith, or add a key with /web)", ""),
                          ("   autopilot " + ("on" if on else "off"), f"bold {'green' if on else 'yellow'}"),
                          ("   battery saver" if (s.get("power") or {}).get("saver") else "", "green"))
    bits = [f"{h['applied_today']} sent today", f"{h['applied_week']} this week", f"{h['queued']} good matches waiting"]
    if q:
        bits.append(f"{q['name']} {q['used']}{'/' + str(q['limit']) if q['limit'] else ''} today")
    line2 = Text("  ·  ".join(bits), style="dim")
    lines = [line1, line2]
    if s["needs_you"]:
        lines.append(Text(f"{s['needs_you']} need you: /review", style="yellow"))
    for a in s.get("attention") or []:
        lines.append(Text(f"! {a['message']} (/watch)", style="bold yellow"))
    console.print(Panel(Text("\n").join(lines), title=f"[bold {ACCENT}]Jobsmith[/]", title_align="left",
                        box=box.ROUNDED, border_style="grey37", padding=(0, 1), expand=False))


# --------------------------------------------------------------------------- views
def status(e: Engine) -> None:
    header(e)
    h = e.get("/api/home")
    s = e.get("/api/status")
    tabs = e.get("/api/live")["tabs"]
    if s["active"] or tabs:
        console.print("\n[bold]In progress[/]  [dim]/watch to follow along[/]")
        shown = set()
        for t in tabs:
            shown.add(t["job_id"])
            console.print(f"  [{ACCENT}]●[/] {t['company']}, {t['title']}  [dim]{t['phase_label']}[/]")
        for jid, what in s["active"].items():
            if jid not in shown:
                j = e.get(f"/api/jobs/{jid}")["job"]
                console.print(f"  [{ACCENT}]●[/] {j['company']}, {j['title']}  [dim]{what}[/]")
    if h["review"]:
        console.print(f"\n[bold yellow]Needs you ({len(h['review'])})[/]  [dim]run /review[/]")
        for j in h["review"][:8]:
            why = j["error"] if j["status"] == "error" else (j["hold_reason"] or "filled in, ready to submit")
            console.print(f"  [yellow]●[/] {j['company']}, {j['title']}\n    [dim]{why}[/]")
    if h["recent"]:
        console.print("\n[bold]Recently applied[/]")
        for r in h["recent"][:5]:
            console.print(f"  [green]✓[/] {r['company']}, {r['title']}" + (f"  [green]{r['outcome']}[/]" if r["outcome"] else ""))
    console.print(f"\n[dim]{h['queued']} good matches waiting. {h['last_summary'] or ''}[/]")


def watch(e: Engine, until_idle: bool = True) -> None:
    """Live view of everything Jobsmith is doing. Press a row's number to watch that form being filled
    in a real browser window; h hides it again, d opens the dashboard, q goes back."""
    seen_busy = False
    idle_since = None
    frame = 0
    rows: list[str] = []
    msg = ""
    taking = False

    def render():
        nonlocal frame, rows
        frame += 1
        s = e.get("/api/status")
        tabs = {t["job_id"]: t for t in e.get("/api/live")["tabs"]}
        h = e.get("/api/home")
        t = Table.grid(padding=(0, 2))
        t.add_column(width=2, style="dim")
        t.add_column(width=2)
        t.add_column()
        t.add_column(style="dim")
        rows = list(dict.fromkeys(list(s["active"]) + list(tabs)))[:9]
        for n, jid in enumerate(rows, 1):
            tab = tabs.get(jid)
            company = tab["company"] if tab else jid
            title = tab["title"] if tab else ""
            if not tab:
                try:
                    j = e.get(f"/api/jobs/{jid}")["job"]
                    company, title = j["company"], j["title"]
                except Exception:
                    pass
            phase = tab["phase"] if tab else s["active"].get(jid, "")
            label = tab["phase_label"] if tab else {"drafting": "researching and drafting", "autopilot": "researching and drafting",
                                                     "filling": "filling the form"}.get(phase, phase)
            mark = ("[green]✓[/]" if phase == "submitted" else "[yellow]![/]" if phase in ("code", "review", "error")
                    else f"[{ACCENT}]{SPIN[frame % len(SPIN)]}[/]")
            pr = (s.get("progress") or {}).get(jid)
            if pr:
                bar = "".join(f"[{ACCENT}]▰[/]" if i < pr["step"] or pr["step"] == pr["total"] else
                              ("[yellow]▰[/]" if i == pr["step"] else "[dim]▱[/]") for i in range(pr["total"] + 1))
                label = f"{bar} {pr['label']}"
            t.add_row(str(n), mark, f"[bold]{company}[/] {title}", label + (f". {tab['note']}" if tab and tab.get("note") else ""))
        if not rows:
            t.add_row("", "", "[dim]Nothing running right now.[/]", "")
        foot = Text.assemble((f"\n{h['applied_today']} sent today", "bold"), f", {h['applied_week']} this week",
                             (f", {len(h['review'])} need you" if h["review"] else "", "yellow"))
        keys = Text("1-9 watch it live · t take over · d dashboard · x stop everything · q back", style="dim")
        group = Table.grid()
        group.add_row(t)
        group.add_row(foot)
        if msg:
            group.add_row(Text(msg, style=ACCENT))
        group.add_row(keys)
        working = bool(s["active"]) or any(tb["phase"] in ("opening", "filling", "submitting") for tb in tabs.values())
        return group, working

    try:
        with Keys() as kb, Live(console=console, refresh_per_second=4, transient=False) as live:
            while True:
                view, busy = render()
                live.update(view)
                seen_busy |= busy
                if until_idle and seen_busy and not busy:
                    idle_since = idle_since or time.time()
                    if time.time() - idle_since > 4:
                        break
                else:
                    idle_since = None
                k = kb.get(2.0)
                if not k:
                    continue
                k = k.lower()
                if k in ("q", "\x1b"):
                    break
                if k.isdigit() and 0 < int(k) <= len(rows):
                    jid = rows[int(k) - 1]
                    if taking:
                        r = e.post(f"/api/live/{jid}/show")
                        msg = ("Opening it in a window for you to finish." if r.get("ok") else
                               "Its form isn't open yet; try again once it's filling.")
                        taking = False
                    else:
                        # Watching happens in your own browser, in a tab you choose to look at:
                        # nothing jumps in front of what you're doing.
                        webbrowser.open(f"{BASE}/#/watch/{jid}")
                        msg = "Watching it live in your browser."
                elif k == "t":
                    taking = True
                    msg = "Take over which one? Press its number."
                elif k == "h":
                    e.post("/api/live/hide")
                    msg = "Browser back in the background."
                elif k == "d":
                    webbrowser.open(BASE + "/#/")
                    msg = "Opened the dashboard."
                elif k == "x":
                    r = e.post("/api/stop", {"everything": True})
                    msg = f"Stopped everything ({r['stopped']} cancelled). Autopilot is off."
    except KeyboardInterrupt:
        pass
    console.print()


def _needs(d: dict) -> bool:
    val = (d.get("final_answer") if d.get("final_answer") is not None else d.get("answer")) or ""
    return d["verdict"] == "red" or (d["required"] and not val and d["qtype"] != "file") or \
        (bool(d["issues"]) and d["verdict"] != "green" and not d.get("final_answer"))


def _answer_fix(e: Engine, f: dict, skip_job: str = "") -> str:
    """Ask one fix. Returns "" to carry on, "quit", or "skip_job" (only offered under one application)."""
    extra = (["Skip this job"] if skip_job else []) + ["Skip", "Quit"]
    if f.get("choices"):
        # Enter skips: an answer like work authorization is only ever one you picked (rule 2)
        k = choose("Your answer:", f["choices"] + extra, default=len(f["choices"]) + len(extra) - 1)
        picked = (f["choices"] + extra)[k]
        if picked in ("Quit", "Skip this job") and k >= len(f["choices"]):
            return "quit" if picked == "Quit" else "skip_job"
        value = picked if k < len(f["choices"]) else ""
    else:
        value = ask("Your answer (blank skips" + (", 'skip job' drops this application" if skip_job else "") + "):"
                    + ("  {company} and {role} are filled in" if f["kind"] == "essay" else ""))
        if skip_job and value.strip().lower() == "skip job":
            return "skip_job"
    if value:
        try:
            r = e.post("/api/fixes/answer", {"id": f["id"], "value": value})
        except RuntimeError as err:
            console.print(f"  [yellow]{err}[/]")
            return ""
        n, sent = len(r.get("freed", [])), len(r.get("started", []))
        console.print("  [green]Saved.[/] " + (r.get("note") or (f"{n} application(s) have nothing left"
                      + (f"; {sent} going out now." if sent else ".") if n else "")))
    return ""


def review_fixes(e: Engine) -> bool:
    """Needs you, in two parts: about you (asked once, with how many applications each unblocks), then about one job
    (under its company and role, with "Skip this job"). False: quit."""
    data = e.get("/api/fixes")
    fixes = data.get("fixes", [])
    you = [f for f in fixes if f.get("part") != "job"]
    if you:
        console.print("\n[bold]About you[/] [dim]· answer once, used on every form[/]")
    for f in you:
        count = "blocks every application" if f["id"] == "resume_pdf" else f"unblocks {f['unblocks']}"
        console.print(f"\n[bold]{f['title']}[/]  [yellow]{count}[/]\n  [dim]{f['detail']}[/]")
        if f["kind"] == "resume_pdf":
            console.print("  Upload it on the dashboard's Profile page; the applications waiting on it go out after.")
            continue
        if _answer_fix(e, f) == "quit":
            return False
    by = {f["id"]: f for f in fixes}
    jobs = data.get("applications", [])
    if jobs:
        console.print("\n[bold]About one job[/] [dim]· that application's own; an answer is never reused[/]")
    for a in jobs:
        console.print(f"\n[bold]{a['company']}[/] · {a['title']}")
        for line in a.get("own", [])[:2]:
            console.print(f"  [yellow]{line[:200]}[/]")
        if not a.get("questions"):          # only its own problem: carry on to it below, or drop the job here
            k = choose("This application:", ["Keep it", "Skip this job", "Quit"], default=1)
            if k == 2:
                return False
            if k == 1:
                try:
                    e.post("/api/fixes/skip", {"job_id": a["id"]})
                    console.print(f"  [green]Skipped[/] {a['company']} · {a['title']}. Nothing was sent.")
                except RuntimeError as err:
                    console.print(f"  [yellow]{err}[/]")
            continue
        for q in a["questions"]:
            f = by.get(q)
            if not f:
                continue
            console.print(f"  [bold]{f['title']}[/]")
            did = _answer_fix(e, f, skip_job=a["id"])
            if did == "quit":
                return False
            if did == "skip_job":
                try:
                    e.post("/api/fixes/skip", {"job_id": a["id"]})
                    console.print(f"  [green]Skipped[/] {a['company']} · {a['title']}. Nothing was sent.")
                except RuntimeError as err:
                    console.print(f"  [yellow]{err}[/]")
                break
    return True


def review(e: Engine) -> None:
    """Go through everything autopilot held for you: each fix once first, then one answer at a time."""
    jobs = e.get("/api/jobs", status="filled,error", limit=50)["jobs"]
    if not jobs and not e.get("/api/fixes").get("fixes"):     # a missing resume PDF holds drafted ones too
        console.print("[green]Nothing needs you.[/]")
        return
    if not review_fixes(e):
        return
    jobs = e.get("/api/jobs", status="filled,error", limit=50)["jobs"]
    for j in jobs:
        r = e.get(f"/api/jobs/{j['id']}")
        job = r["job"]
        console.rule(f"[bold]{job['company']}[/], {job['title']}", align="left", style="dim")
        if job.get("hold_reason"):
            console.print(f"[yellow]Held because:[/] {job['hold_reason']}")
        if job.get("error") and job["status"] == "error":
            console.print(f"[red]Problem:[/] {job['error']}")
        quit_all = False
        for d in [d for d in r["drafts"] if _needs(d)]:
            val = d["final_answer"] if d["final_answer"] is not None else d["answer"]
            console.print(f"\n[bold]{d['label']}[/]" + (" [dim](required)[/]" if d["required"] else ""))
            console.print(f"  {val or '[dim]empty[/]'}")
            for i in d["issues"]:
                console.print(f"  [yellow]{i}[/]")
            c = ask("\\[a]pprove  \\[e]dit  \\[s]kip  \\[q]uit", "s" if not val else "a").lower()[:1]
            if c == "q":
                quit_all = True
                break
            if c == "a" and val:
                e.put(f"/api/drafts/{d['id']}", {"verdict": "green"})
            elif c == "e":
                if d["options"]:
                    k = choose("Pick:", d["options"])
                    new = d["options"][k]
                else:
                    new = ask("New answer:")
                if new:
                    e.put(f"/api/drafts/{d['id']}", {"final_answer": new, "verdict": "green"})
        if quit_all:
            return
        tabs = {t["job_id"]: t for t in e.get("/api/live")["tabs"]}
        c = ask("\n\\[s]ubmit now  \\[w]atch it in the browser  \\[n]ext", "n").lower()[:1]
        if c == "s":
            if j["id"] in tabs and tabs[j["id"]]["phase"] == "review":
                res = e.post(f"/api/live/{j['id']}/submit")
                console.print("[green]Submit clicked.[/]" if res.get("ok") else f"[yellow]{res.get('message')}[/]")
            else:
                e.post(f"/api/jobs/{j['id']}/fill", {"submit": True})
                console.print("Filling it again with your answers and submitting.")
        elif c == "w":
            e.post(f"/api/live/{j['id']}/show")


def pick_jobs(e: Engine, q: str = "") -> list[str]:
    """Tick several of your best matches and apply to them all at once."""
    rows = e.get("/api/jobs", status="new,fetched,drafted", limit=20, q=q)["jobs"]
    if not rows:
        console.print("[dim]No matches waiting. Try /sync, or type a company to apply to.[/]")
        return []
    opts = []
    for j in rows:
        hint = ", ".join(x for x in ((j.get("locations") or [""])[0], f"fit {round(j['fit_score'] or 0)}") if x)
        opts.append((f"{j['company']}: {j['title']}", j["id"], hint))
    return P.multiselect("Which ones? They fill in parallel", opts, [o[1] for o in opts[:5]])


def run_request(e: Engine, text: str, mode: str | None = None, follow: bool = True) -> None:
    with console.status("Finding postings. A web search for a company can take a minute.", spinner="dots"):
        try:
            r = e.post("/api/command", {"text": text, "mode": mode})
        except RuntimeError as ex:
            console.print(f"[red]{ex}[/]")
            return
    for line in r["log"]:
        console.print(f"  {line}")
    if r["started"] and follow:
        watch(e)


def jobs(e: Engine, q: str = "") -> list[dict]:
    rows = e.get("/api/jobs", status="new,fetched,drafted", limit=15, q=q)["jobs"]
    for i, j in enumerate(rows, 1):
        extra = []
        if j.get("match") is not None:
            extra.append(f"{j['match_hits']} of {j['match_total']} skills")
        if j.get("connections"):
            extra.append(f"{j['connections']} you know")
        el = j.get("eligibility") or {}
        if el.get("ok") is False:
            extra.append("[yellow]may not qualify: " + "; ".join(el["reasons"]) + "[/]")
        console.print(f"  [{ACCENT}]{i:>2}[/] [bold]{j['company']}[/], {j['title']}  [dim]fit {round(j['fit_score'] or 0)}"
                      + (", " + ", ".join(extra) if extra else "") + "[/]")
    if rows:
        console.print("[dim]  /apply 3 (or 1,4,7) to apply to those.[/]")
    return rows


COMMANDS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Apply", [
        ("apply to <company or role>", "find matching roles and apply, e.g. apply to NVIDIA hardware internships"),
        ("<job link or GitHub list>", "paste it to apply, or to add the list to what autopilot checks"),
        ("/apply", "tick several of your best matches and apply to them in parallel"),
        ("/jobs [search]", "your best matches; then /apply 1,3"),
    ]),
    ("Watch and review", [
        ("/watch", "live view; press a number to watch that form fill in your browser"),
        ("/review", "go through the answers autopilot held for you"),
        ("/status", "what's running, what needs you, what got sent"),
        ("/web", "open the dashboard"),
    ]),
    ("Control", [
        ("/autopilot on|off", "apply on its own, or stop (off also stops anything in progress)"),
        ("/stop", "stop everything now: applications, the browser and smith"),
        ("/activity", "what Jobsmith is using on this computer: processor, memory, battery"),
        ("/sync", "check your job lists for new roles now"),
    ]),
    ("Set up", [
        ("/smith", "set up smith, the free AI that runs on this computer"),
        ("/extension", "add Jobsmith to Chrome"),
        ("jobsmith setup", "run setup again from step 1 (add --web for the website)"),
    ]),
    ("Try changes safely", [
        ("jobsmith demo", "a practice copy with a made-up person and jobs; nothing real is opened or sent"),
        ("jobsmith demo --setup", "the practice copy, starting the website setup from step 1"),
        ("jobsmith demo show", "watch autopilot apply to 3 made-up applications in the practice copy"),
        ("jobsmith dev", "practice copy with live reload while you edit (source checkout)"),
        ("jobsmith check", "tests, dashboard build, and screenshots of every page (source checkout)"),
        ("/help  /commands  /quit", ""),
    ]),
]


def show_help() -> None:
    console.print(f"\n[bold]Type what you want[/], or a command. [dim]In your shell, the same commands work as `jobsmith <command>`.[/]")
    for section, rows in COMMANDS:
        t = Table.grid(padding=(0, 3))
        t.add_column(style=ACCENT, no_wrap=True, min_width=26)
        t.add_column(style="dim")
        from rich.markup import escape
        for c, d in rows:
            t.add_row(escape(c), escape(d))
        console.print(f"\n[bold]{section}[/]")
        console.print(t)
    console.print()


def repl(e: Engine, mode: str | None = None) -> None:
    header(e)
    console.print("[dim]Type a company, paste job links or a GitHub list. /help for more.[/]\n")
    last: list[dict] = []
    while True:
        try:
            line = console.input(f"[bold {ACCENT}]›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return
        if not line:
            continue
        cmd, _, arg = line.partition(" ")
        try:
            if cmd in ("/quit", "/exit", "q", "exit"):
                return
            elif cmd in ("/help", "/commands", "/?", "help"):
                show_help()
            elif cmd == "/status":
                status(e)
            elif cmd == "/watch":
                watch(e, until_idle=False)
            elif cmd == "/review":
                review(e)
            elif cmd == "/jobs":
                last = jobs(e, arg)
            elif cmd == "/apply":
                ids = [last[int(x) - 1]["id"] for x in re.findall(r"\d+", arg) if 0 < int(x) <= len(last)]
                if not ids:
                    ids = pick_jobs(e, arg)
                if not ids:
                    continue
                r = e.post("/api/jobs/batch", {"action": "autopilot", "ids": ids})
                console.print(f"Applying to {r['started']}.")
                watch(e)
            elif cmd == "/autopilot":
                on = arg.strip().lower() not in ("off", "no", "false", "0")
                r = e.post("/api/autopilot", {"on": on})
                if r.get("stopped"):
                    console.print(f"Stopped {r['stopped']} application{'s' if r['stopped'] != 1 else ''} in progress.")
                console.print("Autopilot is on: it applies on its own and holds anything it isn't sure about."
                              if on else "Autopilot is off: Jobsmith fills forms and stops before submitting.")
            elif cmd == "/sync":
                with console.status("Checking your job lists…"):
                    r = e.post("/api/sources/sync")
                for x in r["results"]:
                    console.print(f"  {x.get('source', '')}: " + (x["error"] if x.get("error") else f"{x.get('added', 0)} new"))
            elif cmd == "/stop":
                stop_everything(e)
            elif cmd == "/activity":
                activity(e)
            elif cmd == "/smith":
                smith_setup(e)
            elif cmd == "/extension":
                extension_help()
            elif cmd == "/web":
                webbrowser.open(BASE)
            elif cmd.startswith("/"):
                console.print("[dim]Unknown command. /help lists them.[/]")
            else:
                run_request(e, line, mode)
        except (httpx.HTTPError, RuntimeError) as ex:
            console.print(f"[red]{ex}[/]")


def stop_everything(e: Engine) -> None:
    r = e.post("/api/stop", {"everything": True})
    console.print(f"[bold]Stopped.[/] {r['stopped']} application{'s' if r['stopped'] != 1 else ''} cancelled, browser closed"
                  + (", smith unloaded" if r.get("unloaded") else "") + ". Autopilot is off; /autopilot on starts it again.")


def activity(e: Engine) -> None:
    p = e.get("/api/power")
    b = p.get("battery")
    console.print(f"[bold]{ {'low': 'Light', 'medium': 'Moderate', 'high': 'Heavy'}.get(p['usage']['level'], '?') }[/] "
                  f"[dim]{p['usage']['cpu']}% of your processor, {p['working']} in progress, {p['tabs']} tabs[/]")
    for part in p["usage"]["parts"]:
        console.print(f"  {part['name']:<24} {part['cpu']:>5}%  {part['memory_mb']:>6} MB")
    if b:
        console.print(f"  Battery {b['percent']}%" + (", plugged in" if b["plugged"] else ", on battery")
                      + (" [yellow](draining while plugged in)[/]" if b["draining_plugged"] else ""))
    if p["saver"]:
        console.print("  [green]Battery saver is on:[/] one application at a time, smith stays off.")
    for m in p["local_models"]:
        console.print(f"  smith is holding {m['name']} ({m['vram_mb']} MB). /stop unloads it.")


def extension_help() -> None:
    from .config import EXTENSION_DIR
    from . import extension as ext
    opened = ext.open_install()
    console.print(f"""[bold]Jobsmith for Chrome[/]: a panel on job postings (autofill, resume match, who you know, cover letter).

  1. In [bold]chrome://extensions[/], turn on [bold]Developer mode[/] (top right).{"  [dim](opened it for you)[/]" if opened.get("chrome") else ""}
  2. Click [bold]Load unpacked[/] and choose this folder{" (it's open in Finder, and the path is copied)" if opened.get("folder") else ""}:
     [{ACCENT}]{EXTENSION_DIR}[/]
  3. Pin Jobsmith from the puzzle-piece menu, then open any job posting.

[dim]After you update Jobsmith, click the reload arrow on Jobsmith's card in chrome://extensions.
It works while Jobsmith is running, and never submits anything.[/]""")


# --------------------------------------------------------------------------- smith
def smith_start(e: Engine, ask_first: bool = True) -> bool:
    """Kick off smith's setup in the background. Asks before downloading anything. False if declined."""
    st = e.get("/api/smith")
    rec = st["recommended"]
    better = rec["model"] if rec["model"] not in st["models"] and st["models"] else ""
    if st["has_model"] and st["running"] and not better:
        if not st["active"]:
            e.post("/api/onboarding/ai", {"kind": "ollama", "model": st["model"]})
        P.success(f"smith is ready ({st['model']})")
        return True
    if better and ask_first:
        if P.confirm(f"A stronger model fits your {rec['ram_gb']} GB of memory: {better} ({rec['download_gb']:g} GB). Download it?"):
            e.post("/api/smith/setup", {"model": better})
            return True
        if st["has_model"]:
            e.post("/api/onboarding/ai", {"kind": "ollama", "model": st["model"]})
            return True
    if st["remote"]:
        P.info(f"Using Ollama at {st['url']}")
    elif ask_first:
        steps = [] if st["installed"] else [f"Ollama, the free engine smith runs on (about {st['engine_gb']:g} GB, no admin needed)"]
        if not st["has_model"]:
            steps.append(f"{st['model']}, a {rec['download_gb']:g} GB model picked for your {rec['ram_gb']} GB of memory")
        if steps:
            P.note("\n".join(f"· {s}" for s in steps) + ("\n\nWith this much memory smith is slow; Gemini is faster." if rec["slow"] else ""),
                   "smith downloads, once")
            if not P.confirm("Download now? It keeps going in the background while you finish setup."):
                return False
    e.post("/api/smith/setup", {})
    return True


SPIN_FRAMES = "◒◐◓◑"


def smith_wait(e: Engine) -> bool:
    """A progress line until smith is ready. Ctrl+C leaves it downloading in the background."""
    f = P.Frame()
    n = 0
    s: dict = {}
    try:
        while True:
            s = e.get("/api/smith")["state"]
            if s["phase"] in ("ready", "error", "idle"):
                break
            pct = s.get("progress")
            bar = ""
            if pct is not None:
                w = 24
                full = int(pct * w)
                bar = "  " + P.cyan("━" * full) + P.gray("━" * (w - full)) + f" {pct * 100:.0f}%"
            f.draw([f"{P.cyan(SPIN_FRAMES[n % 4])}  {s.get('message') or 'Getting smith ready'}{bar}"])
            n += 1
            time.sleep(0.25)
    except KeyboardInterrupt:
        f.clear()
        P.info("smith keeps downloading in the background. `jobsmith smith` shows progress.")
        return False
    f.clear()
    if s.get("phase") == "error":
        P.warn(f"smith: {s['message']}")
        return False
    P.success(s.get("message") or "smith is ready")
    return True


def smith_setup(e: Engine) -> None:
    if smith_start(e) and smith_wait(e):
        smith_test(e)


def smith_test(e: Engine) -> None:
    """Write one sample application answer so you can judge smith's quality and speed on this computer."""
    f = P.Frame()
    f.draw([f"{P.cyan('◒')}  Writing a sample application answer to see how smith does here…"])
    r = e.post("/api/smith/test")
    f.clear()
    if not r.get("ok"):
        P.warn(f"smith couldn't write a sample answer: {r.get('error', 'no answer')}")
        return
    import textwrap
    P.note("\n".join(textwrap.wrap(r["answer"], 72)), f"Sample from {r['model']}, {r['seconds']:g}s, {r['words']} words")
    if r["grade"] != "good":
        P.warn("That's slow or off-length on this computer. Gemini (free) writes better and faster.")


# --------------------------------------------------------------------------- first run
def _clean_path(p: str) -> Path:
    p = p.strip().strip("'\"")
    p = re.sub(r"\\(.)", r"\1", p) if os.name != "nt" else p   # drag-and-drop escapes spaces
    return Path(os.path.expanduser(p))


GEMINI_KEY_URL = "https://aistudio.google.com/apikey"


def _pick_ai(e: Engine, st: dict) -> None:
    """Which AI writes answers. Gemini's free tier is recommended: best free writing, and it can search."""
    sm = st["smith"]
    rec = sm["recommended"]
    found = {d["kind"]: d for d in st["ai"]["detected"]}
    opts: list[tuple] = []
    opts.append(("Gemini (recommended)", "gemini_api",
                 "your key is set up" if "gemini_api" in found else "free, writes well, researches companies; 1-minute key"))
    for kind in ("anthropic_api", "openai_api", "claude_cli"):
        if kind in found:
            opts.append((found[kind]["label"], kind, "found on this computer"))
    opts.append(("smith", "smith", f"already set up, {sm['model']}" if sm["has_model"] else
                 f"free and fully private, runs on this computer; {rec['download_gb']:g} GB download"))
    for kind, label, hint in (("anthropic_api", "Claude", "Anthropic API key, pay per use"),
                              ("openai_api", "ChatGPT", "OpenAI API key, pay per use")):
        if kind not in found:
            opts.append((label, kind, hint))
    opts.append(("Skip for now", "skip", "answers from your profile still fill in"))
    while True:
        kind = P.select("Which AI should write your answers?", opts, opts[0][1])
        if kind == "skip":
            return
        if kind == "smith":
            if smith_start(e):
                P.info("smith is getting ready in the background. Keep going.")
                return
            continue
        key = ""
        if kind not in found:
            if kind == "gemini_api":
                P.note(f"Opening {GEMINI_KEY_URL}\nSign in with Google, click Create API key, and copy it.", "Gemini key")
                webbrowser.open(GEMINI_KEY_URL)
            key = P.text("Paste the key (hidden), or press Enter to go back", secret=True)
            if not key:
                continue
        f = P.Frame()
        f.draw([f"{P.cyan('◒')}  Checking it…"])
        res = e.post("/api/onboarding/ai", {"kind": kind, "key": key})
        f.clear()
        if res["ok"]:
            P.success(f"{res['using']}: {res['message']}")
            return
        P.warn(f"{res['using']}: {res['message']}")


LEVEL_OPTS = [("Internship", "internship"), ("New grad", "newgrad")]
PICKY_OPTS = [("Good fits (recommended)", "good", "roles that match your level, role types and places"),
              ("Strong fits only", "strong", "fewer, closer matches"), ("Anything I qualify for", "any", "the most")]


def _why(text: str) -> None:
    print(f"{P.gray(P.BAR)}  {P.dim(text)}")


def _setup_resume(e: Engine, st: dict) -> dict:
    """Step 1: the resume PDF first. A .tex or .docx alongside it is read more exactly."""
    while not st["step_done"]["resume"]:
        p = P.text("Drag your resume PDF here and press Enter")
        if not p:
            if not P.interactive():
                break
            P.warn("Setup starts from your resume: everything Jobsmith writes comes from it.")
            continue
        path = _clean_path(p)
        if not path.exists():
            P.warn(f"Can't find {path}")
            continue
        slots = ["resume", "resume_pdf"] if path.suffix.lower() == ".pdf" else ["resume"]
        for slot in slots:
            with open(path, "rb") as fh:
                e.post("/api/profile/upload", files={"file": (path.name, fh)}, data={"slot": slot})
        st = e.get("/api/onboarding")
        P.success(f"Read {path.name}: {st['resume']['facts']} facts")
        if not st["step_done"]["resume"]:
            P.info("Employers get a PDF. Drag the PDF version in too.")
    return st


def _setup_confirm(e: Engine, st: dict) -> dict:
    """Step 2: every value read from the resume, shown back; fix any before they go into a form."""
    vals = {r["key"]: r["value"] for r in st["read_back"]}
    labels = {r["key"]: r["label"] for r in st["read_back"]}
    while True:
        lines = [f"{labels[k]}: {v or P.dim('(not on your resume)')}" for k, v in vals.items()]
        P.note("\n".join(lines), "Check what we read")
        fix = P.select("These go into forms exactly as shown. Are they right?",
                       [("Yes, these are right", "")] + [(f"Fix {labels[k]}", k) for k in vals], "")
        if not fix:
            break
        vals[fix] = P.text(labels[fix], vals[fix])
    e.post("/api/onboarding/confirm", {"values": vals})
    return e.get("/api/onboarding")


def _setup_questions(e: Engine, st: dict) -> dict:
    """Step 3: the one list of questions forms ask once. Work authorization, sponsorship and the employer list have
    no default: only you answer them."""
    P.info("Questions forms ask. Answer once; every application uses them.")
    out: dict[str, str] = {}
    for q in st["questions"]:
        _why(q["why"])
        cur = q["value"] or q.get("default") or ""
        if q["kind"] == "choice":
            opts = [(c, c) for c in q["choices"]]
            if q.get("required") and not cur:
                opts = [("Choose one", "")] + opts
            while True:
                v = P.select(q["label"], opts, cur or "")
                if v or not q.get("required"):
                    break
                P.warn("Only you can answer this one.")
        else:
            v = P.text(q["label"] + (f" ({q['placeholder']})" if q.get("placeholder") and not cur else ""), cur)
        out[q["key"]] = v
    r = e.post("/api/onboarding/questions", {"values": out})
    if r["missing"]:
        P.warn("Still to answer: " + ", ".join(r["missing"]))
    if P.interactive() and P.confirm("Add saved answers now? Your own words for questions many forms ask (optional)",
                                     False):
        for kind, label in (("additional_info", "Additional information"), ("why_role", "Why this role?")):
            text_ = P.text(f"{label} (Enter to skip)")
            if text_:
                e.put(f"/api/essays/{kind}", {"text": text_})
    return e.get("/api/onboarding")


def _setup_looking(e: Engine, st: dict) -> dict:
    """Step 4: level, role types, places and fit bar, with the count of matches they give."""
    levels = [g for g in st.get("goals_set") or [] if g != "targeted"] or ["internship"]
    seasons = st.get("seasons_set") or ["Summer 2027"]
    cats = st["categories"] if st.get("prefs_saved") and st.get("categories") else ["Software", "AI/ML/Data"]
    places = st.get("location_choices") or []
    picky = st.get("picky") or "good"
    while True:
        levels = P.multiselect("Level", LEVEL_OPTS, levels)
        if "internship" in levels and len(st.get("seasons") or []) > 1:
            seasons = P.multiselect("Internship seasons", [(x, x) for x in st["seasons"]], seasons)
        cats = P.multiselect("Role types", [(f, f) for f in st["fields"]], cats)
        picked = P.multiselect("Places", [("Anywhere in the US", "any")] +
                               [(n, n, "outside the US" if n in st.get("international", []) else "") for n in st["locations"]],
                               places or ["any"], exclusive="any")
        places = [] if "any" in picked else picked
        picky = P.select("How good a fit", PICKY_OPTS, picky)
        body = {"levels": levels, "seasons": seasons, "categories": cats, "locations": places, "picky": picky}
        pv = e.post("/api/onboarding/preview", body)
        P.success(f"{pv['matches']:,} match{'es' if pv['matches'] != 1 else ''}"
                  + (f" of {pv['open']:,} open roles in your lists" if pv["open"] else
                     " so far: your job lists are still syncing"))
        if pv.get("advice"):
            P.info(pv["advice"])
        if not P.interactive() or P.select("Keep these?", [("Yes", True), ("Change them", False)], True):
            break
    e.post("/api/onboarding/looking", body)
    return e.get("/api/onboarding")


def _setup_sources(e: Engine, st: dict) -> dict:
    """Step 5: job lists from presets, not board addresses. The list for your level is on already."""
    levels = st.get("goals_set") or []
    on = [p["key"] for p in st["presets"] if p["level"] in levels]
    keys = P.multiselect("Where to look", [(p["label"], p["key"]) for p in st["presets"]], on)
    e.post("/api/onboarding/sources", {"presets": keys})
    P.info("Want one company's own job board too? Paste its address here any time later.")
    return e.get("/api/onboarding")


def _setup_start(e: Engine, st: dict) -> None:
    """Step 7: the supervised first application. Nothing is sent until you approve it."""
    mode = P.select("After your first application", [
        ("Autopilot (recommended)", "autopilot", "applies on its own within your limits; holds anything unsure"),
        ("Copilot", "copilot", "fills every form and stops before Submit")], st.get("autonomy") or "autopilot")
    P.info("Jobsmith fills your best match, then stops and shows every answer and where it came from.\n"
           "Nothing is sent until you approve it (/review, then s).")
    go = P.select("Ready", [("Fill my first application now", "go"), ("Not now", "later", "autopilot stays off")], "go")
    if go != "go":
        e.post("/api/onboarding/skip")
        P.outro("Setup is saved. Run `jobsmith setup` to finish; autopilot stays off until then.")
        return
    if smith_busy(e):
        P.info("Waiting for smith to finish downloading (Ctrl+C to do this later).")
        smith_wait(e)
    e.post("/api/onboarding/finish", {"autonomy": mode, "final": False})
    res = e.post("/api/onboarding/first-run" if mode == "copilot" else "/api/onboarding/start")
    if res.get("ok") is False:
        P.outro(res.get("message", "Nothing to fill yet. Your job lists may still be syncing; try /autopilot in a minute."))
        return
    P.outro("Filling your first application. It waits for you under /review." + (
        f" Also applying to {', '.join(res['companies'])}." if res.get("companies") else ""))
    _handoff(e)


def init(e: Engine) -> None:
    """First-run setup in the terminal, the same steps and order as the website's."""
    st = e.get("/api/onboarding")
    print()
    P.intro("Jobsmith setup")
    P.note("Applies to jobs for you, from your real resume, and never makes anything up.\n"
           "About ten minutes. Nothing is drafted or sent until you finish,\n"
           "and the first application waits for you to approve it.", "Welcome")
    if P.interactive() and P.select("Set up here or in your browser?", [
            ("Here (recommended)", "here", "drag your resume into this window"),
            ("In the browser", "web", f"{BASE}/#/setup")], "here") == "web":
        webbrowser.open(f"{BASE}/#/setup")
        P.outro(f"Setup is open at {BASE}/#/setup. Come back here when it's done.")
        return
    st = _setup_resume(e, st)
    st = _setup_confirm(e, st)
    st = _setup_questions(e, st)
    st = _setup_looking(e, st)
    st = _setup_sources(e, st)
    _pick_ai(e, st)
    if not e.get("/api/onboarding")["step_done"]["ai"]:      # skipped: answers from your profile still go in
        e.post("/api/onboarding/ai", {"kind": "skip"})
    _setup_start(e, e.get("/api/onboarding"))


def _handoff(e: Engine, until_idle: bool = False) -> None:
    """After setup: the full-screen app when there's a terminal to draw it in, the plain watch view otherwise."""
    if sys.stdout.isatty() and P.interactive():
        from . import tuiapp
        tuiapp.run(BASE, splash=False)
        raise SystemExit(0)
    watch(e, until_idle=until_idle)


def smith_busy(e: Engine) -> bool:
    return e.get("/api/smith")["state"]["phase"] in ("starting", "installing", "downloading")


def main(argv: list[str]) -> None:
    """Entry for everything that isn't `serve`."""
    mode = None
    plain = "--plain" in argv
    if plain:
        argv.remove("--plain")
    if "--autopilot" in argv:
        argv.remove("--autopilot")
        mode = "autopilot"
    if "--copilot" in argv:
        argv.remove("--copilot")
        mode = "copilot"
    if argv and argv[0] in ("help", "commands", "--help", "-h"):
        show_help()                     # no engine needed to read the menu
        return
    e = Engine()
    e.ensure()
    cmd = argv[0] if argv else ""
    if cmd == "status":
        status(e)
    elif cmd == "watch":
        watch(e, until_idle=False)
    elif cmd == "review":
        if plain or not sys.stdout.isatty():
            review(e)
        else:
            from . import tuiapp
            tuiapp.run(BASE, splash=False, start="review")
    elif cmd in ("init", "setup"):
        if "--web" in argv:
            e.post("/api/onboarding/restart", {})
            webbrowser.open(f"{BASE}/#/setup/1")
            console.print(f"Setup is open on the website from step 1: {BASE}/#/setup/1")
        else:
            init(e)
    elif cmd == "web":
        webbrowser.open(BASE)
    elif cmd == "smith":
        smith_setup(e)
    elif cmd == "stop":
        stop_everything(e)
    elif cmd == "activity":
        activity(e)
    elif cmd == "extension":
        extension_help()
    elif cmd in ("help", "commands", "--help", "-h"):
        show_help()
    elif cmd == "jobs":
        jobs(e, " ".join(argv[1:]))
    elif argv:
        run_request(e, " ".join(argv), mode)
    else:
        if not e.get("/api/onboarding")["onboarded"]:
            init(e)
        if mode:
            console.print(f"[bold]{mode.capitalize()} for this session.[/]")
        if plain or not sys.stdout.isatty():
            repl(e, mode)
        else:
            from . import tuiapp
            tuiapp.run(BASE, splash=os.environ.get("JOBSMITH_NO_SPLASH") != "1")
