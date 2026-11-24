"""The front door: `jobsmith` (or `jobsmith open`, or the Jobsmith app in ~/Applications) opens the dashboard.

Someone who has never used a terminal shouldn't need to know a command, a port or an address. So the one thing
they run starts the engine if it isn't running, waits until it answers, opens the dashboard in their browser, and
says so in one line. If the engine can't start, they get one plain sentence saying why and what to do, never a
traceback.

The dashboard only ever listens on this computer (127.0.0.1); the address carries no token or secret, because the
engine's Host and Origin checks (api.only_local_callers) are what keep other websites and other machines out.
"""
from __future__ import annotations

import os
import shlex
import socket
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_PORT = 8765
START_TIMEOUT = 30.0


def base_url() -> str:
    """The dashboard's address on this computer. JOBSMITH_URL / JOBSMITH_PORT move it (the practice copy, tests),
    but never off this computer: an address pointing anywhere else is ignored."""
    port = os.environ.get("JOBSMITH_PORT", str(DEFAULT_PORT))
    url = os.environ.get("JOBSMITH_URL", "").strip().rstrip("/")
    if url:
        parts = urlsplit(url)
        if parts.scheme == "http" and parts.hostname in LOCAL_HOSTS:
            return url
    return f"http://127.0.0.1:{port}"


def _port(base: str) -> int:
    return urlsplit(base).port or DEFAULT_PORT


def link(href: str = "", base: str | None = None) -> str:
    """A full dashboard address for a page: link("#/profile/desired_pay") -> http://127.0.0.1:8765/#/profile/desired_pay"""
    base = base or base_url()
    href = (href or "").lstrip("/")
    return f"{base}/{href}" if href else base


def engine_up(base: str | None = None) -> bool:
    try:
        return httpx.get((base or base_url()) + "/api/status", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


def _port_taken(base: str) -> bool:
    """Something accepts connections on the dashboard's port (checked only when it isn't Jobsmith answering)."""
    parts = urlsplit(base)
    try:
        with socket.create_connection((parts.hostname or "127.0.0.1", _port(base)), timeout=0.5):
            return True
    except OSError:
        return False


def _log_path() -> Path:
    from .config import DATA_DIR
    return DATA_DIR / "server.log"


def start_engine(base: str) -> subprocess.Popen:
    """The engine in the background, on this computer only (`serve` binds 127.0.0.1), logging to server.log.
    Detached, so closing the window or the launcher doesn't stop applications in progress."""
    log = open(_log_path(), "a")
    args = [sys.executable, "-m", "jobsmith", "serve", "--no-open", "--port", str(_port(base))]
    kw: dict = {"stdout": log, "stderr": log, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008   # DETACHED_PROCESS
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(args, **kw)


def _why_it_stopped(log: Path) -> str:
    try:
        tail = log.read_text(errors="replace")[-4000:]
    except OSError:
        return ""
    return "port" if "address already in use" in tail.lower() or "errno 48" in tail.lower() else ""


def ensure_engine(base: str | None = None, timeout: float = START_TIMEOUT,
                  start=None, sleep=None) -> tuple[bool, bool, str]:
    """Make sure the engine answers. Returns (ok, started, problem): `started` is whether this call started it,
    `problem` one plain sentence for the user when it couldn't. Prints nothing (the MCP server calls this too,
    where anything on stdout would break the conversation with the agent)."""
    base, sleep = base or base_url(), sleep or time.sleep
    if engine_up(base):
        return True, False, ""
    port, log = _port(base), _log_path()
    if _port_taken(base):
        return False, False, (f"Jobsmith couldn't start: another program is using port {port}. Quit that program "
                              "(or restart your computer) and open Jobsmith again.")
    try:
        proc = (start or start_engine)(base)
    except OSError as e:
        return False, False, (f"Jobsmith couldn't start its engine ({e.strerror or e}). "
                              "Reinstall Jobsmith, then open it again.")
    waited = 0.0
    while waited < timeout:
        sleep(0.25)
        waited += 0.25
        if engine_up(base):
            return True, True, ""
        if proc is not None and proc.poll() is not None:
            if _why_it_stopped(log) == "port":
                return False, True, (f"Jobsmith couldn't start: another program is using port {port}. Quit that "
                                     "program (or restart your computer) and open Jobsmith again.")
            return False, True, ("Jobsmith couldn't start: its engine stopped while starting up. Run `jobsmith doctor` "
                                 f"to see what's wrong (details are in {log}).")
    return False, True, (f"Jobsmith couldn't start: its engine didn't answer within {int(timeout)} seconds. Open it "
                         f"again; if this keeps happening, the details are in {log}.")


def quiet_open(url: str) -> bool:
    """Open an address in the default browser without writing anything to this process's stdout or stderr
    (the MCP server's stdout is its conversation with the agent)."""
    try:
        if sys.platform == "darwin":
            return subprocess.run(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=15).returncode == 0
        if os.name == "nt":
            os.startfile(url)                      # type: ignore[attr-defined]
            return True
        return subprocess.run(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@dataclass
class Opened:
    ok: bool               # the engine answers
    url: str
    started: bool = False  # this call started the engine
    opened: bool = False   # the browser was asked to show it
    problem: str = ""      # one plain sentence when the engine couldn't start


def open_dashboard(href: str = "", opener=None, **kw) -> Opened:
    """Start the engine if needed, then show the dashboard (or one page of it) in the default browser."""
    opener = opener or webbrowser.open
    base = base_url()
    ok, started, problem = ensure_engine(base, **kw)
    url = link(href, base)
    if not ok:
        return Opened(False, url, started, False, problem)
    try:
        opened = opener(url) is not False
    except Exception:                              # no browser, a broken handler: the address still works
        opened = False
    return Opened(True, url, started, opened)


def main() -> int:
    """`jobsmith` and `jobsmith open`: one line out, whatever happens."""
    try:
        r = open_dashboard()
    except KeyboardInterrupt:
        return 130
    except Exception as e:                         # never a traceback at the front door
        print(f"Jobsmith couldn't open ({type(e).__name__}). Run `jobsmith doctor` to see what's wrong.")
        return 1
    if not r.ok:
        print(r.problem)
        return 1
    if r.opened:
        print(f"Jobsmith is open at {r.url}")
    else:
        print(f"Jobsmith is open at {r.url} (your browser didn't open by itself: copy that address into it)")
    return 0


# --------------------------------------------------------------------------- macOS launcher
APP_NAME = "Jobsmith.app"
APP_ID = "org.jobsmith.launcher"


def launcher_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Applications" / APP_NAME


def _is_ours(app: Path) -> bool:
    import plistlib
    try:
        with open(app / "Contents" / "Info.plist", "rb") as f:
            return plistlib.load(f).get("CFBundleIdentifier") == APP_ID
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False


def _launcher_script(python: str, path_env: str) -> str:
    """The app's program: the same front door as `jobsmith`, with any problem shown in a dialog (an app has no
    terminal to print to). The message goes to osascript as an argument, never pasted into the script."""
    return f"""#!/bin/sh
# Made by `jobsmith install-launcher`. Opens the Jobsmith dashboard, starting Jobsmith first if it isn't running.
# Remove it with `jobsmith install-launcher --remove`.
export PATH={shlex.quote(path_env)}
out=$({shlex.quote(python)} -m jobsmith open 2>&1)
code=$?
if [ $code -ne 0 ]; then
  /usr/bin/osascript - "$out" <<'EOF'
on run argv
  display alert "Jobsmith couldn't open" message (item 1 of argv)
end run
EOF
fi
exit $code
"""


def install_launcher(remove: bool = False, home: Path | None = None, platform: str | None = None,
                     python: str | None = None, say=print) -> int:
    """Put a small Jobsmith.app in ~/Applications so Spotlight (Cmd+Space, "Jobsmith") opens the dashboard.
    Only ever writes or deletes that one folder, and only deletes it if Jobsmith made it."""
    import plistlib
    import shutil
    from . import __version__
    if (platform or sys.platform) != "darwin":
        say("The Jobsmith app launcher is for macOS. On this computer, run `jobsmith` to open the dashboard.")
        return 1
    app = launcher_path(home)
    if remove:
        if not app.exists():
            say(f"There's no Jobsmith launcher in {app.parent}, so nothing was removed.")
            return 0
        if not _is_ours(app):
            say(f"{app} wasn't made by Jobsmith, so it was left alone.")
            return 1
        shutil.rmtree(app)
        say(f"Removed {app}.")
        return 0
    if app.exists() and not _is_ours(app):
        say(f"{app} already exists and wasn't made by Jobsmith, so it was left alone.")
        return 1
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Resources").mkdir(exist_ok=True)
    with open(contents / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleName": "Jobsmith", "CFBundleDisplayName": "Jobsmith", "CFBundleIdentifier": APP_ID,
                       "CFBundleExecutable": "Jobsmith", "CFBundlePackageType": "APPL",
                       "CFBundleVersion": __version__, "CFBundleShortVersionString": __version__,
                       "LSUIElement": True, "NSHighResolutionCapable": True}, f)
    exe = contents / "MacOS" / "Jobsmith"
    exe.write_text(_launcher_script(python or sys.executable,
                                    os.environ.get("PATH") or "/usr/bin:/bin:/usr/sbin:/sbin"))
    exe.chmod(0o755)
    say(f"Created {app}. Press Cmd+Space and type Jobsmith to open the dashboard. "
        "(Remove it with `jobsmith install-launcher --remove`.)")
    return 0
