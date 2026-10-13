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
            return
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
    v = ask(prompt + (" \\[Y/n]" if default else " \\[y/N]")).lower()
    return default if not v else v.startswith("y")


def _tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


Q_STYLE = None


def _qstyle():
    global Q_STYLE
    if Q_STYLE is None:
        import questionary
        Q_STYLE = questionary.Style([("qmark", f"fg:{ACCENT} bold"), ("pointer", f"fg:{ACCENT} bold"),
                                     ("highlighted", f"fg:{ACCENT} bold"), ("selected", "fg:#3fb950"),
                                     ("answer", f"fg:{ACCENT}"), ("instruction", "fg:#8b949e")])
    return Q_STYLE


def select(prompt: str, options: list[tuple[str, str]], default: str | None = None) -> str | None:
    """Arrow keys and Enter. options are (label, value). Falls back to numbers without a terminal."""
    if _tty():
        import questionary
        choices = [questionary.Choice(label, value=v) for label, v in options]
        r = questionary.select(prompt, choices=choices, default=next((c for c in choices if c.value == default), None),
                               style=_qstyle(), qmark="›", instruction="(↑↓ then Enter)").ask()
        if r is None:
            raise KeyboardInterrupt
        return r
    i = choose(prompt, [l for l, _ in options], next((n for n, (_, v) in enumerate(options, 1) if v == default), 1))
    return options[i][1]


def checkbox(prompt: str, options: list[tuple[str, str]], checked: list[str]) -> list[str]:
    """Space to tick, Enter to confirm. Falls back to comma-separated numbers without a terminal."""
    if _tty():
        import questionary
        r = questionary.checkbox(prompt, choices=[questionary.Choice(l, value=v, checked=v in checked) for l, v in options],
                                 style=_qstyle(), qmark="›", instruction="(↑↓ move, space to tick, Enter when done)",
                                 validate=lambda xs: bool(xs) or "Pick at least one.").ask()
        if r is None:
            raise KeyboardInterrupt
        return r
    for i, (l, _) in enumerate(options, 1):
        console.print(f"  [{ACCENT}]{i}[/] {l}")
    dflt = ",".join(str(i) for i, (_, v) in enumerate(options, 1) if v in checked) or "1"
    picked = ask(prompt + " (numbers, commas)", dflt)
    out = [options[int(x) - 1][1] for x in re.findall(r"\d+", picked) if 0 < int(x) <= len(options)]
    return out or [v for _, v in options if v in checked] or [options[0][1]]


def choose(prompt: str, options: list[str], default: int = 1) -> int:
    for i, o in enumerate(options, 1):
        console.print(f"  [{ACCENT}]{i}[/] {o}")
    while True:
        v = ask(prompt, str(default))
        if v.isdigit() and 1 <= int(v) <= len(options):
            return int(v) - 1
        console.print("[dim]Pick a number from the list.[/]")


def header(e: Engine) -> None:
    s = e.get("/api/status")
    h = e.get("/api/home")
    mode = "autopilot" if s["autonomy"] != "copilot" and s["auto"]["on"] else s["autonomy"]
    ai = s["llm"]["writing"]
    console.print(Text.assemble(("Jobsmith", f"bold {ACCENT}"), "  ",
                                (ai["label"] if ai["ok"] else "no AI connected", "green" if ai["ok"] else "yellow"), "  ",
                                (f"{mode}", "bold"), "  ",
                                (f"{h['applied_today']}{'/' + str(h['daily_cap']) if h['daily_cap'] else ''} sent today", ""), "  ",
                                (f"{s['needs_you']} need you" if s["needs_you"] else "", "yellow"), "  ",
                                (f"{tok(s.get('tokens_today'))} tokens today", "dim")))


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
            t.add_row(str(n), mark, f"[bold]{company}[/] {title}", label + (f". {tab['note']}" if tab and tab.get("note") else ""))
        if not rows:
            t.add_row("", "", "[dim]Nothing running right now.[/]", "")
        foot = Text.assemble((f"\n{h['applied_today']} sent today", "bold"), f", {h['applied_week']} this week",
                             (f", {len(h['review'])} need you" if h["review"] else "", "yellow"))
        keys = Text("1-9 watch it fill in the browser · h hide the browser · d dashboard · q back", style="dim")
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
                k = kb.get(1.0)
                if not k:
                    continue
                k = k.lower()
                if k in ("q", "\x1b"):
                    break
                if k.isdigit() and 0 < int(k) <= len(rows):
                    jid = rows[int(k) - 1]
                    r = e.post(f"/api/live/{jid}/show")
                    msg = ("Showing it in the browser window." if r.get("ok") and not r.get("pending")
                           else "It's still being researched; the browser window opens when its form does."
                           if r.get("pending") else "Couldn't bring the browser up.")
                elif k == "h":
                    e.post("/api/live/hide")
                    msg = "Browser back in the background."
                elif k == "d":
                    webbrowser.open(BASE + "/#/")
                    msg = "Opened the dashboard."
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


HELP = """[bold]Type what to apply to[/]: a company ("apply to AMD hardware internships"), job links, or a GitHub job list.

  /status          what's running, what needs you, what got sent
  /watch           live view of applications in progress
  /review          go through answers autopilot held for you
  /jobs [search]   your best matches; then /apply 1,3
  /autopilot on|off   apply on its own, or stop before every submit
  /sync            check your job lists for new roles now
  /smith           set up smith, the free AI that runs on this computer
  /extension       add Jobsmith to Chrome (fill any application, send jobs here)
  /web             open the dashboard in your browser
  /help  /quit"""


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
            elif cmd == "/help":
                console.print(HELP)
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
                    console.print("[dim]Run /jobs first, then /apply 1 or /apply 1,3.[/]")
                    continue
                r = e.post("/api/jobs/batch", {"action": "autopilot", "ids": ids})
                console.print(f"Applying to {r['started']}.")
                watch(e)
            elif cmd == "/autopilot":
                on = arg.strip().lower() not in ("off", "no", "false", "0")
                e.http.put("/api/settings", json={"autonomy": "autopilot" if on else "copilot", "auto_run": on})
                console.print("Autopilot is on: it applies on its own and holds anything it isn't sure about."
                              if on else "Autopilot is off: Jobsmith fills forms and stops before submitting.")
            elif cmd == "/sync":
                with console.status("Checking your job lists…"):
                    r = e.post("/api/sources/sync")
                for x in r["results"]:
                    console.print(f"  {x.get('source', '')}: " + (x["error"] if x.get("error") else f"{x.get('added', 0)} new"))
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


def extension_help() -> None:
    from .config import EXTENSION_DIR
    console.print(f"""[bold]Jobsmith for Chrome[/]: fill any application from your profile, and send postings to autopilot.

  1. Open [bold]chrome://extensions[/] and turn on [bold]Developer mode[/] (top right)
  2. Click [bold]Load unpacked[/] and choose this folder:
     [{ACCENT}]{EXTENSION_DIR}[/]
  3. Pin Jobsmith from the puzzle-piece menu. On an application, click Fill (or press Alt+J).

[dim]It works while Jobsmith is running, and never submits anything.[/]""")


# --------------------------------------------------------------------------- smith
def smith_start(e: Engine, ask_first: bool = True) -> bool:
    """Kick off smith's setup in the background. Asks before installing anything. False if declined."""
    st = e.get("/api/smith")
    rec = st["recommended"]
    better = rec["model"] if rec["model"] not in st["models"] and st["models"] else ""
    if st["has_model"] and st["running"] and not better:
        if not st["active"]:
            e.post("/api/onboarding/ai", {"kind": "ollama", "model": st["model"]})
        console.print(f"[green]✓[/] smith is ready ({st['model']}).")
        return True
    if better and ask_first:
        if yes(f"A stronger model fits your {rec['ram_gb']} GB of memory: {better} ({rec['download_gb']} GB). Download it?"):
            e.post("/api/smith/setup", {"model": better})
            return True
        if st["has_model"]:
            e.post("/api/onboarding/ai", {"kind": "ollama", "model": st["model"]})
            return True
    if st["remote"]:
        console.print(f"Using Ollama at {st['url']}.")
    elif ask_first:
        steps = [] if st["installed"] else [f"Ollama, the free engine smith runs on (about {st['engine_gb']:g} GB, no admin needed)"]
        if not st["has_model"]:
            steps.append(f"{st['model']}, a {rec['download_gb']} GB model picked for your {rec['ram_gb']} GB of memory")
        if steps:
            console.print("smith will download, once:\n" + "\n".join(f"  · {s}" for s in steps))
            if rec["slow"]:
                console.print("[dim]With this much memory smith is slow. An API key is faster if you have one.[/]")
            if not yes("Go ahead?"):
                return False
    e.post("/api/smith/setup", {})
    return True


def smith_wait(e: Engine) -> bool:
    """Progress bar until smith is ready. Ctrl+C leaves it downloading in the background."""
    from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
    with Progress(TextColumn("{task.description}"), BarColumn(), TextColumn("{task.percentage:>3.0f}%"),
                  TimeRemainingColumn(), console=console, transient=True) as bar:
        task = bar.add_task("Getting smith ready", total=1.0)
        try:
            while True:
                s = e.get("/api/smith")["state"]
                bar.update(task, description=s.get("message") or "Getting smith ready",
                           completed=s.get("progress") or 0)
                if s["phase"] in ("ready", "error", "idle"):
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            console.print("[dim]smith keeps downloading in the background. /smith shows progress.[/]")
            return False
    if s["phase"] == "error":
        console.print(f"[yellow]! smith: {s['message']}[/]")
        return False
    console.print(f"[green]✓[/] {s.get('message') or 'smith is ready'}")
    return True


def smith_setup(e: Engine) -> None:
    if smith_start(e) and smith_wait(e):
        smith_test(e)


def smith_test(e: Engine) -> None:
    """Write one sample application answer so you can judge smith's quality and speed on this computer."""
    with console.status("Writing a sample answer to see how smith does on this computer…", spinner="dots"):
        r = e.post("/api/smith/test")
    if not r.get("ok"):
        console.print(f"[yellow]! smith couldn't write a sample answer: {r.get('error', 'no answer')}[/]")
        return
    console.print(f"\n[dim]Sample answer from {r['model']} in {r['seconds']:g}s ({r['words']} words):[/]")
    console.print(f"  {r['answer']}\n")
    if r["grade"] != "good":
        console.print("[yellow]That's slow or off-length for this computer. A Gemini key (free) writes better and faster.[/]")


# --------------------------------------------------------------------------- first run
def _clean_path(p: str) -> Path:
    p = p.strip().strip("'\"")
    p = re.sub(r"\\(.)", r"\1", p) if os.name != "nt" else p   # drag-and-drop escapes spaces
    return Path(os.path.expanduser(p))


GEMINI_KEY_URL = "https://aistudio.google.com/apikey"


def _pick_ai(e: Engine, st: dict) -> None:
    """Which AI writes answers. Gemini's free tier is the recommended start: best free writing, and it can search."""
    sm = st["smith"]
    rec = sm["recommended"]
    found = {d["kind"]: d for d in st["ai"]["detected"]}
    opts: list[tuple[str, str]] = []
    if "gemini_api" in found:
        opts.append(("Gemini: your key is already set up (recommended)", "gemini_api"))
    else:
        opts.append(("Gemini: free, writes well, can research companies. Needs a free key, 1 minute (recommended)", "gemini_api"))
    for kind in ("anthropic_api", "openai_api", "claude_cli"):
        if kind in found:
            opts.append((f"{found[kind]['label']}: found on this computer", kind))
    smith_note = (f"already set up ({sm['model']})" if sm["has_model"] else
                  f"free and fully private, runs on this computer ({rec['download_gb']:g} GB download)")
    opts.append((f"smith: {smith_note}", "smith"))
    for kind, label in (("anthropic_api", "Claude, with an Anthropic API key"), ("openai_api", "ChatGPT, with an OpenAI API key")):
        if kind not in found:
            opts.append((label, kind))
    opts.append(("Skip for now (answers from your profile still fill in)", "skip"))
    while True:
        kind = select("Which AI should write your answers?", opts, opts[0][1])
        if kind == "skip":
            return
        if kind == "smith":
            if smith_start(e):
                console.print("[green]✓[/] smith is getting ready in the background. Keep going.")
                return
            continue
        key = ""
        if kind not in found:
            if kind == "gemini_api":
                console.print(f"Opening {GEMINI_KEY_URL}. Sign in with Google, click [bold]Create API key[/], and copy it.")
                webbrowser.open(GEMINI_KEY_URL)
            import getpass
            key = getpass.getpass("Paste the key here (hidden), or press Enter to go back: ").strip()
            if not key:
                continue
        with console.status("Checking it…", spinner="dots"):
            res = e.post("/api/onboarding/ai", {"kind": kind, "key": key})
        console.print(("[green]✓[/] " if res["ok"] else "[yellow]! [/]") + f"{res['using']}: {res['message']}")
        if res["ok"]:
            return


def _wait_for_profile(e: Engine) -> dict:
    """The website takes your resume and details; this mirrors what arrives, live.
    Enter continues here (or lets you drag a file in), o reopens the page."""
    url = BASE + "/#/setup"
    e.put("/api/settings", {"setup_step": "profile"})
    console.print(f"\n[bold]Next, your resume and details.[/] Opening {url} in your browser.")
    console.print("[dim]Add them there; they show up here as they arrive. Enter: continue here instead · o: open the page again[/]\n")
    webbrowser.open(url)
    shown: dict[str, str] = {}

    def view(st: dict):
        g = Table.grid(padding=(0, 2))
        g.add_column(width=2)
        g.add_column()
        g.add_column(style="dim")
        for c in st["checklist"]:
            mark = "[green]✓[/]" if c["done"] else ("[yellow]·[/]" if c["required"] else "[dim]·[/]")
            g.add_row(mark, c["label"] + ("" if c["required"] or c["done"] else " [dim](optional)[/]"),
                      (c["value"] or "")[:60])
        tail = ("[green]Everything autopilot needs is here.[/] Finish on the website, or press Enter to continue here."
                if st["profile_ready"] else "Waiting for the website…")
        g.add_row("", Text.from_markup(f"\n{tail}"), "")
        return g

    st = e.get("/api/onboarding")
    try:
        with Keys() as kb, Live(view(st), console=console, refresh_per_second=4, transient=True) as live:
            while st.get("setup_step") == "profile":
                k = kb.get(1.0)
                st = e.get("/api/onboarding")
                live.update(view(st))
                if k in ("\r", "\n"):
                    break
                if k and k.lower() == "o":
                    webbrowser.open(url)
    except KeyboardInterrupt:
        pass
    for c in st["checklist"]:
        if c["done"] and c["key"] not in shown:
            console.print(f"[green]✓[/] {c['label']}: {c['value'][:70]}")
    return st


def _resume_here(e: Engine, st: dict) -> dict:
    """Finishing in the terminal: drag a resume in, answer what's still missing."""
    if not st["checklist"][0]["done"] or not st["checklist"][1]["done"]:
        while True:
            p = ask("Drag your resume here (.tex, .pdf or .docx) and press Enter, or leave blank to skip:")
            if not p:
                break
            path = _clean_path(p)
            if not path.exists():
                console.print(f"[yellow]Can't find {path}.[/]")
                continue
            with console.status("Reading it…"):
                slots = ["resume", "resume_pdf"] if path.suffix.lower() == ".pdf" else ["resume"]
                for slot in slots:
                    with open(path, "rb") as fh:
                        e.post("/api/profile/upload", files={"file": (path.name, fh)}, data={"slot": slot})
            st = e.get("/api/onboarding")
            if st["checklist"][1]["done"] or not yes("Add the PDF version too (that's what employers get)?"):
                break
    for key, label in (("work_authorized_us", "Authorized to work in the US?"), ("needs_sponsorship", "Need visa sponsorship now or later?")):
        item = next(c for c in st["checklist"] if c["key"] == key)
        if not item["done"]:
            v = select(label, [("Yes", "Yes"), ("No", "No"), ("Skip", "")])
            if v:
                e.put(f"/api/answers/{key}", {"value": v, "confirmed": True})
    if any(c["value"] for c in st["checklist"]) and yes("Confirm the details read from your resume?"):
        e.post("/api/answers/confirm-all")
    return e.get("/api/onboarding")


def init(e: Engine) -> None:
    st = e.get("/api/onboarding")
    console.print(f"\n[bold {ACCENT}]Jobsmith[/] applies to jobs for you, from your real resume, and never makes anything up.\n"
                  "A few questions here, then your resume on the website, then it gets to work.\n")

    # 1. what you're applying for (several allowed)
    goal_opts = [(g["label"], k) for k, g in st["goals"].items()]
    goals = checkbox("What are you applying for?", goal_opts, st.get("goals_set") or ["internship"])
    companies: list[str] = []
    if "targeted" in goals:
        companies = [c.strip() for c in ask("Which companies? Separate them with commas:", ", ".join(st.get("companies") or [])).split(",") if c.strip()]

    # 2. fields (several allowed)
    fields = st["fields"]
    cats = checkbox("Which fields?", [(f, f) for f in fields], st.get("categories") or fields[:3])
    e.post("/api/onboarding/goal", {"goals": goals, "categories": cats, "companies": companies})
    kinds = [st["goals"][k]["label"] for k in goals if k != "targeted"] + ([", ".join(companies)] if companies else [])
    console.print(f"[green]✓[/] Looking for {', '.join(cats)} roles: {'; '.join(kinds) or 'the companies you name'}. "
                  "Job lists are syncing in the background.\n")

    # 3. AI
    _pick_ai(e, st)

    # 4. resume and details, on the website (mirrored here)
    st = _wait_for_profile(e)
    if st.get("setup_step") == "profile":       # you continued here instead of on the website
        if not st["profile_ready"]:
            st = _resume_here(e, st)
        # 5. how it applies: autopilot first, since that's what Jobsmith is for
        mode = select("How should it apply?", [
            ("Autopilot: applies on its own, holds anything it isn't sure about for you (recommended)", "autopilot"),
            ("Copilot: fills every form and stops before Submit", "copilot")], "autopilot")
        e.post("/api/onboarding/finish", {"autonomy": mode})
        st = e.get("/api/onboarding")
    else:
        console.print("[green]✓[/] Finished on the website.")
        if st.get("setup_step") == "started":
            console.print("[green]✓[/] Autopilot started from the website. Here's what it's doing:")
            watch(e, until_idle=False)
            return
    missing = [c["label"] for c in st["checklist"] if c["required"] and not c["done"]]
    if missing:
        console.print(f"[yellow]Still missing: {', '.join(missing)}.[/] Applications that need these wait for you.")

    # 6. go
    if st.get("autonomy") == "copilot":
        go = select("Ready.", [("Fill my best match now (you press Submit)", "first"), ("Not now", "later")], "first")
    else:
        go = select("Ready.", [("Start autopilot now and watch it work (recommended)", "start"),
                               ("Watch it fill one application first, without submitting", "first"),
                               ("Not now", "later")], "start")
    if smith_busy(e):
        console.print("Waiting for smith to finish downloading (Ctrl+C to do this later).")
        smith_wait(e)
    if go == "start":
        r = e.post("/api/onboarding/start")
        console.print("[green]✓[/] Autopilot is on." + (f" Also applying to {', '.join(r['companies'])}." if r.get("companies") else ""))
        console.print("[dim]Tip: `jobsmith extension` adds Jobsmith to Chrome, to fill any application you're looking at.[/]")
        watch(e, until_idle=False)
    elif go == "first":
        res = e.post("/api/onboarding/first-run")
        if res.get("ok"):
            console.print(f"Filling {res['company']}, {res['title']}. Press 1 to watch it in the browser.")
            watch(e)
            if st.get("autonomy") != "copilot" and yes("Start autopilot now?"):
                e.post("/api/onboarding/start")
                watch(e, until_idle=False)
        else:
            console.print(f"[yellow]{res.get('message', 'Nothing to try yet.')}[/]")
    else:
        console.print("[dim]Autopilot is on: it checks your job lists every few hours. Type /autopilot off to stop it.[/]"
                      if st.get("autonomy") != "copilot" else "")


def smith_busy(e: Engine) -> bool:
    return e.get("/api/smith")["state"]["phase"] in ("starting", "installing", "downloading")


def main(argv: list[str]) -> None:
    """Entry for everything that isn't `serve`."""
    mode = None
    if "--autopilot" in argv:
        argv.remove("--autopilot")
        mode = "autopilot"
    if "--copilot" in argv:
        argv.remove("--copilot")
        mode = "copilot"
    e = Engine()
    e.ensure()
    cmd = argv[0] if argv else ""
    if cmd == "status":
        status(e)
    elif cmd == "watch":
        watch(e, until_idle=False)
    elif cmd == "review":
        review(e)
    elif cmd == "init":
        init(e)
    elif cmd == "web":
        webbrowser.open(BASE)
    elif cmd == "smith":
        smith_setup(e)
    elif cmd == "extension":
        extension_help()
    elif cmd == "jobs":
        jobs(e, " ".join(argv[1:]))
    elif argv:
        run_request(e, " ".join(argv), mode)
    else:
        if not e.get("/api/onboarding")["onboarded"]:
            init(e)
        if mode:
            console.print(f"[bold]{mode.capitalize()} for this session.[/]")
        repl(e, mode)
