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


def review(e: Engine) -> None:
    """Go through everything autopilot held for you, one answer at a time."""
    jobs = e.get("/api/jobs", status="filled,error", limit=50)["jobs"]
    if not jobs:
        console.print("[green]Nothing needs you.[/]")
        return
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


def _checklist_lines(st: dict, footer: str) -> list[str]:
    lines = [f"{P.cyan(P.ACTIVE)}  {P.bold('Your resume and details')}  {P.dim('(on the website)')}"]
    for c in st["checklist"]:
        if c["done"]:
            mark, label = P.green(P.BOX_ON), c["label"]
        else:
            mark, label = (P.yellow(P.BOX_OFF) if c["required"] else P.dim(P.BOX_OFF)), P.dim(c["label"] + ("" if c["required"] else " (optional)"))
        val = P.dim("  " + c["value"][:48]) if c["value"] else ""
        lines.append(f"{P.cyan(P.BAR)}  {mark} {label}{val}")
    lines.append(f"{P.cyan(P.END)}  {footer}")
    return lines


def _wait_for_profile(e: Engine) -> dict:
    """The website takes your resume and details; this ticks each one off as it arrives.
    Enter continues here instead, o opens the page again."""
    url = BASE + "/#/setup"
    e.put("/api/settings", {"setup_step": "profile"})
    P.note(f"Opening {url}\nAdd your resume and details there. They tick off here as they arrive.", "Next: your resume")
    webbrowser.open(url)
    st = e.get("/api/onboarding")
    if not P.interactive():
        return st
    f = P.Frame()
    tick = 0
    try:
        with P._Raw() as kb:
            while st.get("setup_step") == "profile":
                tick += 1
                foot = (P.green("Everything autopilot needs is here.") + P.dim("  Finish on the website, or press Enter to continue here")
                        if st["profile_ready"] else
                        P.dim(f"{SPIN_FRAMES[tick % 4]} waiting for the website · Enter to continue here instead · o to open it again"))
                f.draw(_checklist_lines(st, foot))
                k = kb.key(1.0)
                if k == "enter":
                    break
                if k == "o":
                    webbrowser.open(url)
                st = e.get("/api/onboarding")
    except KeyboardInterrupt:
        f.clear()
        raise
    f.clear()
    done = [c for c in st["checklist"] if c["done"]]
    print(f"{P.green(P.DONE)}  Your resume and details")
    for c in done:
        print(f"{P.gray(P.BAR)}  {P.green(P.BOX_ON)} {c['label']}  {P.dim(c['value'][:60])}")
    print(P.gray(P.BAR))
    return st


def _resume_here(e: Engine, st: dict) -> dict:
    """Finishing in the terminal: drag a resume in, answer what's still missing."""
    if not st["checklist"][0]["done"] or not st["checklist"][1]["done"]:
        while True:
            p = P.text("Drag your resume here (.tex, .pdf or .docx) and press Enter, or leave blank to skip")
            if not p:
                break
            path = _clean_path(p)
            if not path.exists():
                P.warn(f"Can't find {path}")
                continue
            slots = ["resume", "resume_pdf"] if path.suffix.lower() == ".pdf" else ["resume"]
            for slot in slots:
                with open(path, "rb") as fh:
                    e.post("/api/profile/upload", files={"file": (path.name, fh)}, data={"slot": slot})
            st = e.get("/api/onboarding")
            P.success(f"Read {path.name}: {st['checklist'][0]['value']}")
            if st["checklist"][1]["done"] or not P.confirm("Add the PDF version too? That's what employers get."):
                break
    for key, label in (("work_authorized_us", "Authorized to work in the US?"), ("needs_sponsorship", "Need visa sponsorship now or later?")):
        item = next(c for c in st["checklist"] if c["key"] == key)
        if not item["done"]:
            v = P.select(label, [("Yes", "Yes"), ("No", "No"), ("Skip", "")])
            if v:
                e.put(f"/api/answers/{key}", {"value": v, "confirmed": True})
    if any(c["value"] for c in st["checklist"]) and P.confirm("Confirm the details read from your resume?"):
        e.post("/api/answers/confirm-all")
    return e.get("/api/onboarding")


def init(e: Engine) -> None:
    st = e.get("/api/onboarding")
    print()
    P.intro("Jobsmith setup")
    P.note("Applies to jobs for you, from your real resume, and never makes anything up.\n"
           "A few questions and your resume, here in the terminal. Then it gets to work.", "Welcome")

    # 1. what you're applying for (several allowed)
    goal_opts = [(g["label"], k) for k, g in st["goals"].items()]
    goals = P.multiselect("What are you applying for?", goal_opts, st.get("goals_set") or ["internship"])
    companies: list[str] = []
    if "targeted" in goals:
        companies = [c.strip() for c in P.text("Which companies? Separate them with commas",
                                               ", ".join(st.get("companies") or [])).split(",") if c.strip()]

    # 2. fields (several allowed)
    fields = st["fields"]
    cats = P.multiselect("Which fields?", [(f, f) for f in fields], st.get("categories") or fields[:3])
    e.post("/api/onboarding/goal", {"goals": goals, "goal": goals[0], "categories": cats, "companies": companies})

    # 3. preferences
    places = P.multiselect("Where do you want to work?", [("Anywhere in the US", "any")] +
                           [(n, n, "remote roles" if n == "Remote" else "outside the US" if n in st.get("international", []) else "")
                            for n in st["locations"]],
                           st.get("location_choices") or ["any"], exclusive="any")
    picky = P.select("How picky should autopilot be?", [
        ("Good fits (recommended)", "good", "roles that match your fields and resume"),
        ("Strong fits only", "strong", "fewer applications, closer matches"),
        ("Anything I qualify for", "any", "the most applications")], st.get("picky") or "good")
    at_once = P.select("How many applications at once?", [
        ("3 (recommended)", 3, "fast, and easy to keep an eye on"), ("1", 1, "one at a time, easiest to watch"),
        ("5", 5, "fastest; uses more memory")], st.get("concurrency") or 3)
    window = P.select("While it applies, the browser window should be", [
        ("In the background (recommended)", "background", "watch any application when you want to"),
        ("On screen", "visible", "see every form as it's filled")], st.get("browser_window") or "background")
    values = P.multiselect("What do you value most in a role? Pick up to 3", [(v, v) for v in st.get("values_all") or []],
                           st.get("values") or [], required=False, limit=3) if st.get("values_all") else []
    e.post("/api/onboarding/prefs", {"locations": [] if "any" in places else places, "picky": picky,
                                     "concurrency": at_once, "browser_window": window, "values": values})
    ack = P.select("Forms often ask you to confirm privacy notices, terms, or AI-use policies. Answer those for you?", [
        ("Yes, agree for me (recommended)", "Yes", "otherwise each one waits for you"),
        ("No, ask me each time", "No")], "Yes")
    for key in ("acknowledge_notices", "ai_tools_consent"):
        e.put(f"/api/answers/{key}", {"value": ack, "confirmed": True})
    P.info("Job lists are syncing in the background.")

    # 4. AI
    _pick_ai(e, st)

    # 4. resume and details: right here by default (drag the file in), or on the website if you'd rather
    where = P.select("Your resume", [("Add it here (recommended)", "here", "drag the file into this window"),
                                     ("On the website", "web", "upload it and check what was read, in your browser")], "here") \
        if P.interactive() else "web"
    if where == "here":
        e.put("/api/settings", {"setup_step": "profile"})
        st = e.get("/api/onboarding")
    else:
        st = _wait_for_profile(e)
    if st.get("setup_step") == "profile":       # you continued here instead of on the website
        if not st["profile_ready"]:
            st = _resume_here(e, st)
        # 5. how it applies: autopilot first, since that's what Jobsmith is for
        mode = P.select("How should it apply?", [
            ("Autopilot (recommended)", "autopilot", "applies on its own, holds anything it isn't sure about for you"),
            ("Copilot", "copilot", "fills every form and stops before Submit")], "autopilot")
        e.post("/api/onboarding/finish", {"autonomy": mode})
        st = e.get("/api/onboarding")
    elif st.get("setup_step") in ("started", "first"):
        P.success("Finished on the website. " + ("Autopilot is running." if st["setup_step"] == "started"
                                                 else "Filling your first application."))
        P.outro("Here's what it's doing.")
        _handoff(e, until_idle=st["setup_step"] == "first")
        return
    else:
        P.success("Finished on the website.")
    missing = [c["label"] for c in st["checklist"] if c["required"] and not c["done"]]
    if missing:
        P.warn(f"Still missing: {', '.join(missing)}. Applications that need these wait for you.")

    # 6. go
    if st.get("autonomy") == "copilot":
        go = P.select("Ready", [("Fill my best match now", "first", "you press Submit"), ("Not now", "later")], "first")
    else:
        go = P.select("Ready", [("Start autopilot now (recommended)", "start", "and watch it work"),
                                ("Watch one application first", "first", "fills it without submitting"),
                                ("Not now", "later")], "start")
    if smith_busy(e):
        P.info("Waiting for smith to finish downloading (Ctrl+C to do this later).")
        smith_wait(e)
    if go == "start":
        r = e.post("/api/onboarding/start")
        P.success("Autopilot is on." + (f" Also applying to {', '.join(r['companies'])}." if r.get("companies") else ""))
        P.outro("Opening Jobsmith. Ask it anything, or type /help. `jobsmith extension` adds Chrome.")
        _handoff(e)
    elif go == "first":
        res = e.post("/api/onboarding/first-run")
        if res.get("ok"):
            P.outro(f"Filling {res['company']}, {res['title']}. Shift+Tab turns autopilot on when you're ready.")
            _handoff(e)
        else:
            P.outro(res.get("message", "Nothing to try yet. Your job lists may still be syncing."))
    else:
        P.outro("Autopilot is on: it checks your job lists every few hours. Type /autopilot off to stop it."
                if st.get("autonomy") != "copilot" else "All set. Type what to apply to, or /help.")


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
