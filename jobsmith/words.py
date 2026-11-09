"""The words for an application that's waiting on you or didn't finish: one wording for the terminal's log, its
Review list and the dashboard, so they can't disagree, and a plain reason every time.

`event_lines` turns what changed since the last look into log lines: each names the company and the role, and
several of one company's roles in the same state become one line ("TikTok · 3 roles couldn't finish: …")."""
from __future__ import annotations

import re

READY, FAILED = "ready for you", "couldn't finish"


def status_word(status: str) -> str:
    """How a held application is described everywhere: by its saved status, never by what its tab last showed."""
    return FAILED if status == "error" else READY


# A browser's or the network's own error, in plain words. The first that matches wins.
_PLAIN = [
    (r"bot check", ""),                                                  # already in plain words: kept as written
    (r"Timeout \d+ms exceeded|timed? ?out|ReadTimeout|ConnectTimeout", "the site didn't answer in time"),
    (r"nodename nor servname|name or service not known|ERR_NAME_NOT_RESOLVED|getaddrinfo", "the site's address couldn't be found"),
    (r"ERR_INTERNET_DISCONNECTED|ERR_NETWORK|ConnectError|Connection refused|ERR_CONNECTION", "the site couldn't be reached"),
    (r"404 Not Found|no longer on|posting (is|was) (closed|removed)|may have closed", "the posting is gone"),
    (r"Could not (resolve|identify) the Greenhouse board|Couldn't identify the Greenhouse board", "its form couldn't be found from this link"),
    (r"Target (page|closed)|browser has been closed|Browser closed", "its browser tab was closed"),
]


def why(job: dict) -> str:
    """One plain line saying why this application waits or failed. Never empty: if nothing was recorded, it says so."""
    held = " ".join((job.get("hold_reason") or "").split())
    text = held or " ".join((job.get("error") or "").split())
    if not text:
        return "Jobsmith didn't record why; open it to see" if job.get("status") == "error" else "filled and waiting for you"
    for pat, plain in _PLAIN:
        if re.search(pat, text, re.I):
            if plain:
                return plain
            break
    text = re.split(r"\s*(?:Call log:|For more information check|=====)", text)[0].strip(" :;")
    return text if len(text) <= 140 else text[:137].rsplit(" ", 1)[0] + "…"


def summary(ready: int, failed: int) -> str:
    """The one line for start-up and the Review heading: "12 ready for you, 3 couldn't finish"."""
    bits = [f"{ready} {READY}"] if ready else []
    bits += [f"{failed} {FAILED}"] if failed else []
    return ", ".join(bits)


_VERB = {"submitted": "[green]submitted ✓[/]", "code": "[yellow]emailed you a code[/] · /code",
         "review": f"[yellow]is {READY}[/] · /review", "error": f"[yellow]{FAILED}[/]"}
_MANY = {"submitted": "[green]submitted ✓[/]", "code": "[yellow]emailed you codes[/] · /code",
         "review": f"[yellow]are {READY}[/] · /review", "error": f"[yellow]{FAILED}[/]"}


def event_lines(events: list[dict]) -> list[str]:
    """Log lines (Rich markup) for what just changed. Each event: phase ('submitted', 'code', 'review', 'error'),
    company, title, and why (for 'error'). One line per company and phase: a single role is named; several become
    "Company · N roles …", with the reason when they share one."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for e in events:
        if e.get("phase") in _VERB:
            groups.setdefault((e.get("company") or "An application", e["phase"]), []).append(e)
    from rich.markup import escape          # a title like "Engineer [Remote]" is text, never markup
    out = []
    for (company, phase), es in groups.items():
        company = escape(company)
        reasons = list(dict.fromkeys(escape(e.get("why") or "") for e in es))
        tail = ""
        if phase == "error":
            tail = (f": {reasons[0]}" if len(reasons) == 1 and reasons[0] else ": for different reasons") + " · /review"
        if len(es) == 1:
            role = f" · {escape(es[0]['title'])}" if es[0].get("title") else ""
            out.append(f"[b]{company}[/]{role} {_VERB[phase]}{tail}")
        else:
            out.append(f"[b]{company}[/] · {len(es)} roles {_MANY[phase]}{tail}")
    return out
