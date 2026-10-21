"""Skills: Jobsmith is a set of parts for the whole job hunt, and each part is a folder here.

    jobsmith/skills/<name>/SKILL.md     what the skill does, for people and for AI agents (Claude Code, Codex,
                                        Gemini CLI, Cursor). The frontmatter is also the skill's manifest.
    jobsmith/skills/<name>/__init__.py  its code, when it has any (planned skills are just a SKILL.md)

Frontmatter keys: name, description (agents read these two), and Jobsmith's own: title, status (ready | planned),
core (can't be switched off), page (its dashboard page), command (its terminal command).

Add a skill: make a folder with a SKILL.md, write the code beside it, and it shows up in `jobsmith skills`,
the dashboard's Skills page and the README's table. See CONTRIBUTING in the README.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import db

HERE = Path(__file__).parent


def _frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            v = v.strip().strip('"')
            meta[k.strip()] = {"true": True, "false": False}.get(v, v)
    return meta, m.group(2)


def _load() -> list[dict]:
    out = []
    for d in sorted(HERE.iterdir()):
        f = d / "SKILL.md"
        if not f.exists():
            continue
        meta, body = _frontmatter(f.read_text())
        key = d.name
        out.append({"key": key, "name": meta.get("title") or key.replace("-", " ").title(), "agent_name": meta.get("name", f"jobsmith-{key}"),
                    "what": meta.get("description", ""), "status": meta.get("status", "ready"), "core": bool(meta.get("core")),
                    "page": meta.get("page", ""), "command": meta.get("command", ""), "path": str(f), "soon": meta.get("status") == "planned",
                    "order": int(meta.get("order", 50))})
    return sorted(out, key=lambda s: (s["order"], s["key"]))


SKILLS = _load()


def enabled() -> set[str]:
    off = set(db.get_setting("skills_off") or [])
    return {s["key"] for s in SKILLS if not s["soon"] and (s["core"] or s["key"] not in off)}


def listing() -> list[dict]:
    on = enabled()
    return [dict(s, enabled=s["key"] in on) for s in SKILLS]


def set_enabled(key: str, on: bool) -> list[dict]:
    s = next((x for x in SKILLS if x["key"] == key), None)
    if s is None or s["core"] or s["soon"]:
        raise KeyError(key)
    off = set(db.get_setting("skills_off") or [])
    (off.discard if on else off.add)(key)
    db.set_settings({"skills_off": sorted(off)})
    return listing()


def skill_dirs(ready_only: bool = True) -> list[Path]:
    return [Path(s["path"]).parent for s in SKILLS if not (ready_only and s["soon"])]
