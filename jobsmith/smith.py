"""smith: Jobsmith's own AI, running on this computer. Free and private.

smith is a small open model (Qwen3) served by Ollama. Nobody should have to set that up by hand, so
`setup()` does all of it, once, with your OK:

  1. find Ollama (or install it into your user folder: no admin, no sudo where avoidable)
  2. start it if it isn't running
  3. download the model that fits this computer's memory, with progress
  4. switch Jobsmith to smith

Progress lives in `STATE`, which the dashboard and the terminal both poll.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import db, llm
from .config import DATA_DIR

# Biggest model that runs comfortably in this much RAM (GB). Sizes are the download.
# The model has to share memory with Chrome and everything else you have open, so it gets about half.
MODELS = [  # (min RAM, model, download GB)
    (31.0, "qwen3:30b-a3b-instruct-2507-q4_K_M", 19.0),   # mixture-of-experts: big-model writing, small-model speed
    (20.0, "qwen3:14b", 9.3),
    (15.0, "qwen3:8b", 5.2),
    (7.0, "qwen3:4b-instruct-2507-q4_K_M", 2.5),
    (0.0, "qwen3:1.7b", 1.4),
]
ENGINE_GB = {"Darwin": 0.2, "Windows": 1.0, "Linux-x86_64": 1.5, "Linux-aarch64": 1.0}   # roughly; includes GPU support
DOWNLOADS = {
    "Darwin": "https://ollama.com/download/Ollama-darwin.zip",
    "Windows": "https://ollama.com/download/OllamaSetup.exe",
    "Linux-x86_64": "https://ollama.com/download/ollama-linux-amd64.tar.zst",
    "Linux-aarch64": "https://ollama.com/download/ollama-linux-arm64.tar.zst",
}
HOME = DATA_DIR / "tools"            # where smith installs Ollama when you don't have it

STATE: dict = {"phase": "idle", "message": "", "progress": None, "model": "", "error": ""}
_task: asyncio.Task | None = None


def _set(phase: str, message: str = "", progress: float | None = None, **kw) -> None:
    STATE.update({"phase": phase, "message": message, "progress": progress, "updated": time.time(), **kw})


# --------------------------------------------------------------------------- this computer
def ram_gb() -> float:
    try:
        if sys.platform == "darwin":
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=5)) / 2**30
        if os.name == "nt":
            import ctypes

            class MEM(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MEM()
            m.dwLength = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 2**30
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 2**20
    except Exception:
        pass
    return 8.0


def recommended(ram: float | None = None) -> dict:
    ram = ram_gb() if ram is None else ram
    for min_ram, model, gb in MODELS:
        if ram >= min_ram:
            return {"model": model, "download_gb": gb, "ram_gb": round(ram), "slow": ram < 12}
    return {"model": MODELS[-1][1], "download_gb": MODELS[-1][2], "ram_gb": round(ram), "slow": True}


def _platform_key() -> str:
    s = platform.system()
    return f"Linux-{'aarch64' if platform.machine().lower() in ('aarch64', 'arm64') else 'x86_64'}" if s == "Linux" else s


def find_ollama() -> str | None:
    """The ollama binary: on PATH, in the usual install spots, or the copy smith installed itself."""
    hit = shutil.which("ollama")
    if hit:
        return hit
    cands = [HOME / "Ollama.app/Contents/Resources/ollama", HOME / "bin/ollama", HOME / "ollama.exe",
             Path("/Applications/Ollama.app/Contents/Resources/ollama"),
             Path.home() / "Applications/Ollama.app/Contents/Resources/ollama",
             Path("/usr/local/bin/ollama"), Path("/opt/homebrew/bin/ollama"), Path("/usr/bin/ollama")]
    if os.environ.get("LOCALAPPDATA"):
        cands.append(Path(os.environ["LOCALAPPDATA"]) / "Programs/Ollama/ollama.exe")
    return next((str(p) for p in cands if p.exists()), None)


async def running() -> bool:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=1.5) as c:
            return (await c.get(f"{llm.OLLAMA_URL}/api/version")).status_code == 200
    except Exception:
        return False


def remote() -> bool:
    """OLLAMA_HOST points somewhere else (a Mac mini, say): use it, never install or start anything here."""
    host = llm.OLLAMA_URL.split("://", 1)[-1].split(":")[0]
    return host not in ("127.0.0.1", "localhost", "0.0.0.0", "::1")


async def status() -> dict:
    models = await llm.ollama_models()
    rec = recommended()
    s = db.get_settings()
    model = s.get("ollama_model") or rec["model"]
    return {"installed": bool(find_ollama()) or remote(), "running": await running(), "remote": remote(),
            "url": llm.OLLAMA_URL, "models": models, "model": model, "has_model": model in models,
            "recommended": rec, "active": s.get("llm_backend") == "ollama",
            "can_install": _platform_key() in DOWNLOADS, "engine_gb": ENGINE_GB.get(_platform_key(), 1.0),
            "state": dict(STATE)}


# --------------------------------------------------------------------------- install / start / pull
async def _download(url: str, dest: Path, label: str) -> None:
    import httpx
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=120), follow_redirects=True) as c:
        async with c.stream("GET", url) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            done = 0
            with open(tmp, "wb") as fh:
                async for chunk in r.aiter_bytes(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    _set("installing", f"{label} ({done / 2**20:.0f} MB)", done / total if total else None)
    tmp.replace(dest)


async def install() -> str:
    """Put Ollama in your user folder. Returns the binary path."""
    key = _platform_key()
    url = DOWNLOADS.get(key)
    if not url:
        raise RuntimeError("smith can't install itself on this system yet. Install Ollama from ollama.com.")
    HOME.mkdir(parents=True, exist_ok=True)
    name = url.rsplit("/", 1)[1]
    pkg = HOME / name
    await _download(url, pkg, "Downloading Ollama, the engine smith runs on")
    _set("installing", "Installing Ollama")
    if key == "Darwin":
        # ditto keeps the app bundle's symlinks and permissions, which zipfile doesn't.
        await _run(["ditto", "-x", "-k", str(pkg), str(HOME)])
    elif key == "Windows":
        # Per-user install, no admin. Ollama's installer starts the server when it's done.
        await _run([str(pkg), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"])
    else:
        if not shutil.which("zstd") and not _tar_has_zstd():
            raise RuntimeError("Unpacking Ollama needs zstd. Install it (apt install zstd), or run: "
                               "curl -fsSL https://ollama.com/install.sh | sh")
        await _run(["tar", "--zstd", "-xf", str(pkg), "-C", str(HOME)])
    pkg.unlink(missing_ok=True)
    exe = find_ollama()
    if not exe:
        raise RuntimeError("Ollama installed but its program wasn't found. Install it from ollama.com.")
    return exe


def _tar_has_zstd() -> bool:
    try:
        return "zstd" in subprocess.run(["tar", "--help"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return False


async def _run(cmd: list[str]) -> None:
    p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await p.communicate()
    if p.returncode:
        raise RuntimeError(f"{Path(cmd[0]).name} failed: {out.decode(errors='replace')[-300:]}")


async def start(exe: str | None = None) -> bool:
    """Start Ollama's server in the background (it keeps running after Jobsmith closes, like the app does)."""
    if await running():
        return True
    exe = exe or find_ollama()
    if not exe:
        return False
    log = open(DATA_DIR / "ollama.log", "ab")
    kw: dict = {"stdout": log, "stderr": log, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen([exe, "serve"], **kw)
    for _ in range(40):
        await asyncio.sleep(0.5)
        if await running():
            return True
    return False


async def pull(model: str) -> None:
    import httpx
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=600)) as c:
        async with c.stream("POST", f"{llm.OLLAMA_URL}/api/pull", json={"model": model, "stream": True}) as r:
            if r.status_code != 200:
                raise RuntimeError(f"Couldn't download {model}: {(await r.aread()).decode()[:200]}")
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                ev = json.loads(line)
                if ev.get("error"):
                    raise RuntimeError(ev["error"])
                total, done = ev.get("total"), ev.get("completed")
                if total and done is not None:
                    _set("downloading", f"Downloading smith's brain ({done / 2**30:.1f} of {total / 2**30:.1f} GB)",
                         done / total, model=model)
                else:
                    _set("downloading", ev.get("status", "Downloading").capitalize(), STATE.get("progress"), model=model)


async def setup(model: str = "", allow_install: bool = True) -> dict:
    """Everything, in order. Safe to call again: each step is skipped when already done."""
    try:
        model = model or db.get_settings().get("ollama_model") or recommended()["model"]
        STATE.update(model=model, error="")
        if not await running():
            exe = find_ollama()
            if not exe and remote():
                raise RuntimeError(f"Can't reach Ollama at {llm.OLLAMA_URL}. Is that computer on?")
            if not exe:
                if not allow_install:
                    raise RuntimeError("Ollama isn't installed.")
                exe = await install()
            _set("starting", "Starting smith")
            if not await start(exe):
                raise RuntimeError("Ollama didn't start. See ollama.log in your Jobsmith data folder.")
        if model not in await llm.ollama_models():
            _set("downloading", f"Downloading {model}", 0.0, model=model)
            await pull(model)
        db.set_settings({"llm_backend": "ollama", "ollama_model": model, "research_backend": "same"})
        llm.forget_checks()
        llm._auto_cache = None
        _set("ready", f"smith is ready ({model})", 1.0, model=model)
    except Exception as e:  # noqa: BLE001 - shown to the user
        msg = str(e)
        if e.__class__.__module__.startswith("httpx"):
            msg = (f"Couldn't download Ollama ({msg[:80]}). Check your internet connection and try again, "
                   "or install Ollama yourself from ollama.com.")
        _set("error", msg, None, error=msg)
    return dict(STATE)


def spawn_setup(model: str = "", allow_install: bool = True) -> dict:
    """Start setup in the background (the dashboard and terminal poll STATE)."""
    global _task
    if _task is None or _task.done():
        _set("starting", "Getting smith ready", None)
        _task = asyncio.create_task(setup(model, allow_install))
    return dict(STATE)


async def wake() -> None:
    """On Jobsmith start: if you use smith and Ollama is installed here but not running, start it."""
    s = db.get_settings()
    if s.get("llm_backend") in ("ollama", "auto") and not remote() and find_ollama() and not await running():
        await start()


SAMPLE = {
    "system": "You write answers for a job application. Use only the facts given. Be specific and concise. Reply with JSON.",
    "prompt": ("Facts about the applicant:\n"
               "- Built a RISC-V pipeline simulator in TypeScript used by 300 students in a computer architecture course\n"
               "- Data engineering internship: moved nightly batch jobs to Spark Structured Streaming, cutting latency from 6 hours to 4 minutes\n"
               "- Hackathon winner: wildfire smoke detection on a Jetson Nano with a LoRa mesh\n\n"
               "Company: a payments company building real-time fraud detection.\n"
               "Question: Why are you interested in this role? (80 to 120 words)\n"
               'Reply as {"answer": "...", "facts_used": [numbers of the facts you used]}'),
}


async def selftest(model: str = "") -> dict:
    """One realistic application answer, timed, so you can judge smith's writing on your own machine."""
    b = llm.OllamaLocal(model or db.get_settings().get("ollama_model") or "")
    t0 = time.time()
    try:
        out = await b.complete_json(SAMPLE["system"], SAMPLE["prompt"], timeout=300)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    secs = time.time() - t0
    answer = (out or {}).get("answer", "") if isinstance(out, dict) else ""
    words = len(answer.split())
    return {"ok": bool(answer), "model": b.model, "seconds": round(secs, 1), "answer": answer, "words": words,
            "tokens": b.last_usage, "grade": "good" if answer and 60 <= words <= 160 and secs < 90 else "check"}
