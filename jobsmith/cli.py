"""Command line.

    jobsmith                  the terminal app (see tui.py): prompt, live progress, review
    jobsmith serve            just the engine and the dashboard at http://127.0.0.1:8765
    jobsmith sync | ingest PATH | doctor
"""
from __future__ import annotations

import argparse
import asyncio
import webbrowser


ENGINE_CMDS = {"serve", "sync", "ingest", "doctor"}


def main() -> None:
    import sys
    argv = sys.argv[1:]
    if argv and argv[0] in ("mcp", "skills", "voice", "site"):
        from . import clicmds
        clicmds.main(argv)
        return
    if argv and argv[0] in ("demo", "demo-seed", "dev", "check", "shots"):
        from . import devtools
        devtools.main(argv)
        return
    if not argv or argv[0] not in ENGINE_CMDS:
        from . import tui
        tui.main(argv)
        return
    p = argparse.ArgumentParser(prog="jobsmith", description="Applies to jobs for you. Run `jobsmith` with no "
                                "arguments for the terminal app, or `jobsmith serve` for the dashboard.")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start the dashboard")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-open", action="store_true")
    sub.add_parser("sync", help="pull job sources and score them")
    i = sub.add_parser("ingest", help="add a resume / document to your profile")
    i.add_argument("path")
    sub.add_parser("doctor", help="check AI backend, browser, resume")
    args = p.parse_args()

    if args.cmd == "serve":
        import uvicorn
        port = getattr(args, "port", 8765)
        if not getattr(args, "no_open", False):
            import threading
            threading.Timer(1.5, webbrowser.open, args=(f"http://127.0.0.1:{port}",)).start()
        # If the engine ever dies from a crash in native code, leave the traceback in server.log.
        import faulthandler
        from .config import DATA_DIR
        faulthandler.enable(open(DATA_DIR / "crash.log", "a"), all_threads=True)
        # Plain asyncio rather than uvloop: a little slower, nothing native to crash on new Pythons.
        uvicorn.run("jobsmith.api:app", host="127.0.0.1", port=port, log_level="warning", loop="asyncio", http="h11")
    elif args.cmd == "sync":
        from . import db, match, sources
        db.conn()
        if not db.q("SELECT 1 FROM sources LIMIT 1"):
            sources.add_source("https://github.com/SimplifyJobs/Summer2027-Internships")
        for r in asyncio.run(sources.sync_all()):
            print(r)
        print("scored", match.rescore())
    elif args.cmd == "ingest":
        from pathlib import Path
        from . import match, profile
        print(asyncio.run(profile.ingest_document(Path(args.path))))
        match.rescore()
    elif args.cmd == "doctor":
        from . import llm, profile
        ok, msg = asyncio.run(llm.backend().available())
        print(f"AI: {llm.label(llm.backend())}: {'OK' if ok else 'NOT READY'} - {msg}")
        print(f"Browser: {browser_check()}")
        print(f"Resume PDF for attaching: {profile.primary_resume_pdf() or 'none uploaded'}")
        print(f"Facts: {len(profile.facts())}")


def browser_check() -> str:
    """Use the installed Chrome if there is one; otherwise make sure Playwright's Chromium is downloaded."""
    import subprocess
    import sys

    async def try_launch(channel):
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            b = await pw.chromium.launch(headless=True, **({"channel": channel} if channel else {}))
            await b.close()
    for ch in ("chrome", "msedge", None):
        try:
            asyncio.run(try_launch(ch))
            return f"OK ({ch or 'bundled Chromium'})"
        except Exception:
            continue
    r = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True, text=True)
    return "Downloaded Chromium" if r.returncode == 0 else f"NOT READY: {r.stderr[-200:]}"


if __name__ == "__main__":
    main()
