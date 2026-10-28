"""Shell commands that don't need the engine running.

    jobsmith skills                       every skill, and whether it's on
    jobsmith skills install [--agent X]   register Jobsmith's MCP server with your AI agents and add the skills
                                          (X: claude, codex, gemini, cursor; default: the ones on this computer)
    jobsmith voice                        what Jobsmith knows about how you write, and which stories are missing
    jobsmith voice add FILE...            add your writing (.md .txt .docx .pdf)
    jobsmith mcp                          the MCP server itself (your agent starts this; you don't need to)
    jobsmith site                         open the project page (site/index.html) in your browser
    jobsmith stats [--days N] [--json]    submissions, how many were confirmed, and the share of good matches
                                          autopilot sent without you
    jobsmith audit [-n N] [--seed S] [--json]
                                          N submitted applications (default 50), every answer with what it traces
                                          to; exits 1 if any answer doesn't trace to a fact
    Add --practice to either to read the practice copy (`jobsmith demo`) instead of your own data.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()
HOME = Path.home()
SERVER = {"command": sys.executable, "args": ["-m", "jobsmith", "mcp"]}


def _backup(p: Path) -> None:
    if p.exists():
        shutil.copy(p, p.with_name(p.name + f".bak-jobsmith-{int(time.time())}"))


def _json_server(p: Path) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(p.read_text() or "{}") if p.exists() else {}
    if data.get("mcpServers", {}).get("jobsmith") == SERVER:
        return "already set up"
    _backup(p)
    data.setdefault("mcpServers", {})["jobsmith"] = SERVER
    p.write_text(json.dumps(data, indent=2))
    return f"added to {p}"


def _codex() -> str:
    p = HOME / ".codex" / "config.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    text = p.read_text() if p.exists() else ""
    if "[mcp_servers.jobsmith]" in text:
        return "already set up"
    _backup(p)
    args = ", ".join(json.dumps(a) for a in SERVER["args"])
    p.write_text(text.rstrip() + f'\n\n[mcp_servers.jobsmith]\ncommand = {json.dumps(SERVER["command"])}\nargs = [{args}]\n')
    return f"added to {p}"


def _claude() -> str:
    if shutil.which("claude"):
        r = subprocess.run(["claude", "mcp", "add", "--scope", "user", "jobsmith", "--", SERVER["command"], *SERVER["args"]],
                           capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip()
        if r.returncode == 0 or "already exists" in out:
            return "registered with `claude mcp add`" if r.returncode == 0 else "already set up"
        return f"`claude mcp add` said: {out[:200]}"
    return _json_server(HOME / ".claude.json")


AGENTS = {
    "claude": ("Claude Code", HOME / ".claude", _claude, [HOME / ".claude" / "skills"]),
    "codex": ("Codex", HOME / ".codex", _codex, [HOME / ".codex" / "skills"]),
    "gemini": ("Gemini CLI", HOME / ".gemini", lambda: _json_server(HOME / ".gemini" / "settings.json"), []),
    "cursor": ("Cursor", HOME / ".cursor", lambda: _json_server(HOME / ".cursor" / "mcp.json"), []),
}


def install(only: list[str]) -> None:
    from . import skills
    picked = only or [k for k, (_, d, _, _) in AGENTS.items() if d.exists()]
    if not picked:
        console.print("No AI agents found on this computer (Claude Code, Codex, Gemini CLI or Cursor). "
                      "Install one, or name it: [bold]jobsmith skills install --agent claude[/]")
    for k in picked:
        if k not in AGENTS:
            console.print(f"[yellow]Unknown agent {k}[/]; choose from {', '.join(AGENTS)}")
            continue
        name, _, register, skill_roots = AGENTS[k]
        try:
            msg = register()
        except Exception as e:  # never leave someone's config half-written without saying so
            msg = f"couldn't update its settings ({e}); add the MCP server by hand: {SERVER['command']} -m jobsmith mcp"
        console.print(f"[bold]{name}[/]: MCP server {msg}")
        for root in skill_roots + [HOME / ".agents" / "skills"]:
            for d in skills.skill_dirs():
                dest = root / f"jobsmith-{d.name}"
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy(d / "SKILL.md", dest / "SKILL.md")
        console.print(f"  skills copied ({', '.join(d.name for d in skills.skill_dirs())})")
    console.print("\nIn your agent, try: [bold]\"What does Jobsmith have waiting for me? Write the open questions in my voice.\"[/]")


def list_skills() -> None:
    from . import db, skills
    db.conn()
    t = Table(show_header=True, header_style="bold", box=None, padding=(0, 2), expand=False)
    for c in ("Skill", "Status", "Command", "What it does"):
        t.add_column(c)
    for s in skills.listing():
        what = s["what"].replace("Planned. ", "").split(" Use when")[0].split(". ")[0]
        t.add_row(s["name"], "planned" if s["soon"] else "on" if s["enabled"] else "off", s["command"] or "", what[:70] + ("…" if len(what) > 70 else ""))
    console.print(t)
    console.print("\n[dim]Switch skills on or off on the dashboard's Skills page. Use them from your own AI agent: jobsmith skills install[/]")


def voice_cmd(args: list[str]) -> None:
    from . import db
    from .skills import voice
    db.conn()
    if args[:1] == ["add"]:
        total = 0
        for a in args[1:]:
            p = Path(a).expanduser()
            if not p.exists():
                console.print(f"[yellow]Not found:[/] {p}")
                continue
            n = voice.add_file(p)
            total += n
            console.print(f"Added {n} passage{'s' if n != 1 else ''} from {p.name}")
        if not args[1:]:
            console.print("Paste your writing, then press Ctrl+D:")
            total = voice.add(sys.stdin.read(), "pasted")
            console.print(f"Added {total} passages")
        return
    s = voice.summary()
    st = s["style"]
    console.print(f"[bold]Your voice[/]: {st.get('samples', 0)} passages of your writing, {s['answers']} answers you approved.")
    if st.get("samples"):
        console.print(f"  {st['avg_sentence']} words per sentence, {st['contractions_per_100']} contractions per 100 words. "
                      f"It won't use {len(st['never_uses'])} stock phrases you never write.")
    console.print("\n[bold]Stories applications ask for[/]")
    for c in s["coverage"]:
        console.print(f"  {'[green]✓[/]' if c['have'] else '[dim]·[/]'} {c['label']}" + ("" if c["have"] else "  [dim]add a paragraph about this[/]"))
    console.print("\n[dim]Add writing: jobsmith voice add essay.md cover-letter.docx[/]")


def site() -> None:
    import webbrowser
    from .config import ROOT
    p = ROOT / "site" / "index.html"
    if p.exists():
        webbrowser.open(p.as_uri())
        console.print(f"Opened {p}")
    else:
        webbrowser.open("https://github.com/rawcache/Jobsmith")


def main(argv: list[str]) -> None:
    cmd, rest = argv[0], argv[1:]
    if cmd == "mcp":
        from . import mcp_server
        mcp_server.main()
    elif cmd == "skills":
        if rest[:1] == ["install"]:
            agents = [a for i, a in enumerate(rest) if i and rest[i - 1] == "--agent"]
            install(sum((a.split(",") for a in agents), []))
        else:
            list_skills()
    elif cmd == "voice":
        voice_cmd(rest)
    elif cmd == "site":
        site()
    elif cmd in ("stats", "audit"):
        if "--practice" in rest:
            _use_practice_copy()
        (stats_cmd if cmd == "stats" else audit_cmd)([a for a in rest if a != "--practice"])


def _use_practice_copy() -> None:
    """Point this command at the practice copy. Must happen before anything reads the data folder."""
    import os
    from .devtools import DEMO_DIR
    if "jobsmith.config" in sys.modules:
        raise SystemExit("--practice has to be set before Jobsmith opens its data; run it as its own command.")
    if not (DEMO_DIR / "jobsmith.db").exists():
        raise SystemExit("There's no practice copy yet. Start one with: jobsmith demo")
    os.environ.update(JOBSMITH_DATA=str(DEMO_DIR), JOBSMITH_DEMO="1")


def _opt(rest: list[str], name: str, default: int | None) -> int | None:
    i = rest.index(name) + 1 if name in rest else 0
    return int(rest[i]) if 0 < i < len(rest) else default


def stats_cmd(rest: list[str]) -> None:
    from . import db, stats
    db.conn()
    d = stats.compute(days=_opt(rest, "--days", 30))
    print(json.dumps(d, indent=2) if "--json" in rest else stats.render(d))


def audit_cmd(rest: list[str]) -> None:
    from . import audit, db
    db.conn()
    audit._ensure()
    total = db.q1("SELECT COUNT(*) n FROM audit_submissions")["n"]
    subs = audit.sample(_opt(rest, "-n", 50), _opt(rest, "--seed", None))
    if "--json" in rest:
        print(json.dumps({"total": total, "submissions": subs}, indent=2, ensure_ascii=False))
    else:
        print(audit.render_sample(subs, total) if subs else "No submitted applications to check yet.")
    if any(not f["traces"] for s in subs for f in s["fields"]):
        raise SystemExit(1)
