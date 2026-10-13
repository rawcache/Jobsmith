"""Jobsmith in the terminal.

    jobsmith                      open the prompt (sets you up the first time)
    jobsmith "apply to nvidia"    one request, then watch it work
    jobsmith --autopilot ...      submit whatever it's confident about without asking (this run only)
    jobsmith smith                set up smith, the free AI that runs on this computer
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

    def get(self, path: str, **params):
        r = self.http.get(path, params=params or None)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict | None = None, **kw):
        r = self.http.post(path, json=body if body is not None else {}, **kw) if "files" not in kw else self.http.post(path, **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail") or r.text
            except ValueError:
                detail = r.text or f"HTTP {r.status_code}"
            raise RuntimeError(detail)
        return r.json()

    def put(self, path: str, body: dict):
        r = self.http.put(path, json=body)
        r.raise_for_status()
        return r.json()


# --------------------------------------------------------------------------- small helpers
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
                                (f"{h['applied_today']}/{h['daily_cap']} sent today", ""), "  ",
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
    """Live view of everything Jobsmith is doing. Ctrl+C goes back to the prompt."""
    seen_busy = False
    idle_since = None
    frame = 0

    def render():
        nonlocal frame
        frame += 1
        s = e.get("/api/status")
        tabs = {t["job_id"]: t for t in e.get("/api/live")["tabs"]}
        h = e.get("/api/home")
        t = Table.grid(padding=(0, 2))
        t.add_column(width=2)
        t.add_column()
        t.add_column(style="dim")
        ids = list(dict.fromkeys(list(s["active"]) + list(tabs)))
        for jid in ids:
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
            t.add_row(mark, f"[bold]{company}[/] {title}", label + (f". {tab['note']}" if tab and tab.get("note") else ""))
        if not ids:
            t.add_row("", "[dim]Nothing running right now.[/]", "")
        foot = Text.assemble((f"\n{h['applied_today']} sent today", "bold"), f", {h['applied_week']} this week",
                             (f", {len(h['review'])} need you" if h["review"] else "", "yellow"),
                             ("   Ctrl+C to go back", "dim"))
        group = Table.grid()
        group.add_row(t)
        group.add_row(foot)
        working = bool(s["active"]) or any(tb["phase"] in ("opening", "filling", "submitting") for tb in tabs.values())
        return group, working

    try:
        with Live(console=console, refresh_per_second=4, transient=False) as live:
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
                time.sleep(1)
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
            elif cmd == "/web":
                webbrowser.open(BASE)
            elif cmd.startswith("/"):
                console.print("[dim]Unknown command. /help lists them.[/]")
            else:
                run_request(e, line, mode)
        except (httpx.HTTPError, RuntimeError) as ex:
            console.print(f"[red]{ex}[/]")


# --------------------------------------------------------------------------- smith
def smith_start(e: Engine, ask_first: bool = True) -> bool:
    """Kick off smith's setup in the background. Asks before installing anything. False if declined."""
    st = e.get("/api/smith")
    rec = st["recommended"]
    if st["active"] and st["has_model"] and st["running"]:
        console.print(f"[green]✓[/] smith is ready ({st['model']}).")
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
    if smith_start(e):
        smith_wait(e)


# --------------------------------------------------------------------------- first run
def _clean_path(p: str) -> Path:
    p = p.strip().strip("'\"")
    p = re.sub(r"\\(.)", r"\1", p) if os.name != "nt" else p   # drag-and-drop escapes spaces
    return Path(os.path.expanduser(p))


def init(e: Engine) -> None:
    st = e.get("/api/onboarding")
    console.print(f"\n[bold {ACCENT}]Jobsmith[/] applies to jobs for you, from your real resume, and never makes anything up.\n"
                  "Four quick questions, then it gets to work.\n")

    # 1. goal
    goals = list(st["goals"].items())
    console.print("[bold]1. What's your goal with Jobsmith?[/]")
    gi = choose("Goal:", [g["label"] for _, g in goals])
    fields = st["fields"]
    console.print("\n[bold]Which fields?[/] [dim]Numbers separated by commas.[/]")
    for i, f in enumerate(fields, 1):
        console.print(f"  [{ACCENT}]{i}[/] {f}")
    picked = ask("Fields:", "1,2,3")
    cats = [fields[int(x) - 1] for x in re.findall(r"\d+", picked) if 0 < int(x) <= len(fields)] or fields[:3]
    e.post("/api/onboarding/goal", {"goal": goals[gi][0], "categories": cats})
    console.print(f"[green]✓[/] Looking for {', '.join(cats)} roles. Your job lists are syncing in the background.\n")

    # 2. AI
    console.print("[bold]2. Which AI should write your answers?[/]")
    det = [d for d in st["ai"]["detected"] if d["kind"] != "ollama"]   # keys you already have
    sm = st["smith"]
    rec = sm["recommended"]
    smith_bg = False
    done = False
    if det and yes(f"Found {det[0]['label']}. Use it?"):
        res = e.post("/api/onboarding/ai", {"kind": det[0]["kind"]})
        done = res["ok"]
        console.print(("[green]✓[/] " if res["ok"] else "[yellow]! [/]") + res["message"])
    while not done:
        size = "" if sm["has_model"] else f", {rec['download_gb']} GB download"
        k = choose("AI:", [f"smith: free and private, runs on this computer{size} (recommended)",
                           "Claude, with an Anthropic API key", "ChatGPT, with an OpenAI API key",
                           "Gemini, with a Google AI Studio key (has a free tier)", "Skip for now"])
        kind = [None, "anthropic_api", "openai_api", "gemini_api", "skip"][k]
        if kind == "skip":
            console.print("[dim]Without AI, Jobsmith still fills everything from your profile; written answers wait for you.[/]")
            break
        if kind is None:
            if smith_start(e):
                smith_bg = True
                console.print("[green]✓[/] smith is getting ready in the background. Keep going.")
                break
            continue
        import getpass
        key = getpass.getpass("Paste the key (hidden): ").strip()
        res = e.post("/api/onboarding/ai", {"kind": kind, "key": key})
        console.print(("[green]✓[/] " if res["ok"] else "[yellow]! [/]") + res["message"])
        done = res["ok"] or not yes("Try another?", False)

    # 3. resume
    console.print("\n[bold]3. Your resume[/]")
    r = st["resume"]
    if r["has_resume"]:
        console.print(f"[green]✓[/] Already have it ({r['name'] or 'your resume'}).")
    while not r["has_resume"]:
        p = ask("Drag your resume here (.tex, .pdf or .docx) and press Enter:")
        if not p:
            break
        path = _clean_path(p)
        if not path.exists():
            console.print(f"[yellow]Can't find {path}.[/]")
            continue
        with console.status("Reading it…"):
            with open(path, "rb") as fh:
                e.post("/api/profile/upload", files={"file": (path.name, fh)}, data={"slot": "resume"})
            if path.suffix.lower() == ".pdf":
                with open(path, "rb") as fh:
                    e.post("/api/profile/upload", files={"file": (path.name, fh)}, data={"slot": "resume_pdf"})
        r = e.get("/api/onboarding")["resume"]
    if r["has_resume"]:
        console.print(f"  {r['name']}, {r['email']}")
        console.print(f"  {r['degree']} {r['major']}, {r['school']}" + (f", {r['graduation']}" if r["graduation"] else ""))
        for k, v in r["links"].items():
            console.print(f"  {k}: {v}")
        console.print(f"  {r['facts']} facts about your experience, projects and skills")
        if r["to_confirm"] and yes(f"\nThat's {r['to_confirm']} answers read from your resume. Look right?"):
            e.post("/api/answers/confirm-all")
        if not r["pdf"]:
            console.print("[yellow]Employers get a PDF. Add one with: jobsmith init, or in the dashboard's Profile.[/]")

    # 4. mode
    console.print("\n[bold]4. How should it apply?[/]")
    m = choose("Mode:", ["Autopilot: applies on its own, holds anything it isn't sure about for you (recommended)",
                         "Copilot: fills every form, you press submit"])
    e.post("/api/onboarding/finish", {"autonomy": ["autopilot", "copilot"][m]})
    console.print("[green]✓[/] All set.\n")

    if smith_bg and e.get("/api/smith")["state"]["phase"] not in ("ready", "error"):
        console.print("Waiting for smith to finish downloading (Ctrl+C to do this later).")
        smith_wait(e)
    if yes("Watch it fill your first application now? It won't submit this one."):
        res = e.post("/api/onboarding/first-run")
        if res.get("ok"):
            console.print(f"Filling {res['company']}, {res['title']} in a browser window you can watch.")
            watch(e)
        else:
            console.print(f"[yellow]{res.get('message', 'Nothing to try yet.')}[/]")


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
