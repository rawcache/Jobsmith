"""How much of your computer Jobsmith is using, and keeping that small.

Where the energy goes, biggest first:
  1. smith, the local AI. Writing with a model on your own GPU is the heaviest thing Jobsmith does; a laptop
     can drain while plugged in. So smith only stands in for a cloud AI when you're plugged in (by default),
     writes one answer at a time, and is unloaded from memory when you stop.
  2. Chrome. Each application is a tab rendering a real web page. Battery saver fills one at a time.
  3. The live previews in the dashboard. Battery saver refreshes them rarely.

Battery saver turns on by itself when you're on battery (Settings can make it always or never).
"""
from __future__ import annotations

import time

from . import db

_procs: dict[int, object] = {}
_battery_log: list[tuple[float, float]] = []      # (time, percent) while plugged in, to spot a net drain


def battery() -> dict | None:
    try:
        import psutil
        b = psutil.sensors_battery()
    except Exception:
        return None
    if b is None:
        return None
    now = time.time()
    if b.power_plugged:
        _battery_log.append((now, b.percent))
        del _battery_log[:-120]
    else:
        _battery_log.clear()
    # Plugged in but still going down over the last 10+ minutes: the charger can't keep up.
    old = next(((t, p) for t, p in _battery_log if now - t >= 600), None)
    draining = bool(b.power_plugged and old and b.percent < old[1] - 0.5)
    return {"percent": round(b.percent), "plugged": bool(b.power_plugged), "draining_plugged": draining,
            "minutes_left": None if b.secsleft in (-1, -2) or b.secsleft is None or b.secsleft < 0 else int(b.secsleft / 60)}


def saver() -> bool:
    """Battery saver: on when you ask for it, or (by default) whenever you're on battery or draining."""
    mode = db.get_setting("power_mode") or "auto"
    if mode == "saver":
        return True
    if mode == "full":
        return False
    b = battery()
    return bool(b and (not b["plugged"] or b["draining_plugged"]))


def paused() -> bool:
    """Autopilot waits while on battery, if you chose that."""
    if db.get_setting("on_battery") != "pause":
        return False
    b = battery()
    return bool(b and not b["plugged"])


def local_ai_allowed() -> bool:
    """May smith stand in when the cloud AI's free limit runs out?"""
    when = db.get_setting("smith_fallback") or "plugged"
    if when == "never":
        return False
    if when == "always":
        return True
    b = battery()
    return not saver() and (b is None or b["plugged"])


def _sample(p) -> tuple[float, float]:
    try:
        return p.cpu_percent(None), p.memory_info().rss / 2**20
    except Exception:
        return 0.0, 0.0


def usage() -> dict:
    """CPU and memory of Jobsmith's parts: its engine, the Chrome it drives, and smith (Ollama)."""
    try:
        import psutil
    except Exception:
        return {"parts": [], "cpu": 0, "level": "unknown"}
    me = psutil.Process()
    groups: dict[str, list] = {"Jobsmith": [me], "Chrome (applications)": [], "smith (local AI)": []}
    try:
        for c in me.children(recursive=True):
            name = (c.name() or "").lower()
            if "ollama" in name:
                groups["smith (local AI)"].append(c)
            elif any(k in name for k in ("chrome", "chromium", "msedge", "helper")):
                groups["Chrome (applications)"].append(c)
            else:
                groups["Jobsmith"].append(c)        # the browser driver and other helpers
    except Exception:
        pass
    if not groups["smith (local AI)"]:
        try:
            groups["smith (local AI)"] = [p for p in psutil.process_iter(["name"]) if "ollama" in (p.info["name"] or "").lower()]
        except Exception:
            pass
    cores = psutil.cpu_count() or 1
    parts = []
    total = 0.0
    for label, ps in groups.items():
        cpu = mem = 0.0
        for p in ps:
            cached = _procs.setdefault(p.pid, p)
            c, m = _sample(cached)
            cpu += c
            mem += m
        share = cpu / cores
        total += share
        parts.append({"name": label, "cpu": round(share, 1), "memory_mb": round(mem), "processes": len(ps)})
    level = "high" if total > 25 else "medium" if total > 8 else "low"
    return {"parts": parts, "cpu": round(total, 1), "level": level}


async def local_models_loaded() -> list[dict]:
    import httpx
    from . import llm
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get(f"{llm.OLLAMA_URL}/api/ps")
        return [{"name": m.get("name"), "vram_mb": round((m.get("size_vram") or 0) / 2**20)} for m in r.json().get("models", [])]
    except Exception:
        return []


async def unload_local() -> int:
    """Free the GPU memory smith is holding (it loads again on its next answer, in a few seconds)."""
    import httpx
    from . import llm
    n = 0
    for m in await local_models_loaded():
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(f"{llm.OLLAMA_URL}/api/generate", json={"model": m["name"], "keep_alive": 0})
            n += 1
        except Exception:
            pass
    return n


async def status() -> dict:
    from . import runner
    b = battery()
    return {"battery": b, "saver": saver(), "paused": paused(), "mode": db.get_setting("power_mode") or "auto",
            "local_ai_allowed": local_ai_allowed(), "usage": usage(), "local_models": await local_models_loaded(),
            "working": len(runner.active()), "tabs": len(runner.live_list())}
