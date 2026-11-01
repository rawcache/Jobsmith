"""'Report this form': a pre-filled GitHub issue about a form Jobsmith didn't handle well, for the user to review and
post. Nothing is sent: this only builds the address of GitHub's new-issue page, which the user's browser opens.

What goes in is the form's structure as the site wrote it (each question's words, its kind, whether it's required,
its choices), the site and the page's path. Never a value from a field, never the page's query string (it can hold
tracking or account ids), and never an email address, phone number or long number, even inside a question's words."""
from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

REPO = "https://github.com/rawcache/Jobsmith"
MAX_URL = 7500                  # GitHub refuses longer new-issue links; the field list is cut to fit
MAX_FIELDS = 80

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PHONE = re.compile(r"\+?\(?\d[\d\s().-]{7,}\d")
LONG_NUMBER = re.compile(r"\b\d{6,}\b")


def scrub(text: str, limit: int = 160) -> str:
    """A question's words, without anything that could be someone's (a form can greet you by email)."""
    t = " ".join(str(text or "").split())
    t = EMAIL.sub("[email]", t)
    t = PHONE.sub("[number]", t)
    t = LONG_NUMBER.sub("[number]", t)
    t = t.replace("|", "/")         # keeps the Markdown table intact
    return t[:limit] + ("…" if len(t) > limit else "")


def page_of(url: str) -> tuple[str, str]:
    """The site and the page's path, no query string or fragment."""
    u = urlsplit(url or "")
    return (u.hostname or "", scrub(u.path, 200))


def body(url: str, fields: list[dict], site: str = "", note: str = "", total: int | None = None) -> str:
    """The issue's text. `total`: how many fields the form has, when only the first few fit."""
    host, path = page_of(url)
    total = len(fields) if total is None else total
    rows = ["| # | Question | Kind | Required | Choices |", "| --- | --- | --- | --- | --- |"]
    for i, f in enumerate(fields[:MAX_FIELDS], 1):
        choices = [scrub(o, 40) for o in (f.get("options") or [])]
        shown = ", ".join(choices[:8]) + (f" and {len(choices) - 8} more" if len(choices) > 8 else "")
        rows.append(f"| {i} | {scrub(f.get('label'))} | {scrub(f.get('qtype') or f.get('type'), 20)} | "
                    f"{'yes' if f.get('required') else ''} | {shown} |")
    if total > min(len(fields), MAX_FIELDS):
        rows.append(f"| | and {total - min(len(fields), MAX_FIELDS)} more | | | |")
    return "\n".join([
        f"**Site:** {host}{f' ({scrub(site, 60)})' if site else ''}",
        f"**Page:** `{path or '/'}`",
        "",
        "**What went wrong:** " + (scrub(note, 500) if note else "_(say what Jobsmith did, and what it should have done)_"),
        "",
        f"**The form, as Jobsmith read it ({total} field{'' if total == 1 else 's'}; questions and choices only, nothing you "
        "typed):**",
        "",
        *rows,
        "",
        "_Made with Jobsmith's \"Report this form\". Check it before posting: it's public._",
    ])


def issue_url(url: str, fields: list[dict], site: str = "", note: str = "") -> str:
    """The new-issue address for this form, its field list cut to a length GitHub takes."""
    host, _ = page_of(url)
    title = quote(f"Form report: {host or 'a job site'}")
    shown = list(fields)
    while True:
        link = f"{REPO}/issues/new?labels=form-report&title={title}&body={quote(body(url, shown, site, note, len(fields)))}"
        if len(link) <= MAX_URL or not shown:
            return link
        shown = shown[: len(shown) - max(1, len(shown) // 5)]


def from_questions(questions: list[dict]) -> list[dict]:
    """A saved application's questions (jobs.questions) in the report's shape: no values, no answers."""
    return [{"label": q.get("label"), "qtype": q.get("qtype"), "required": bool(q.get("required")),
             "options": list(q.get("options") or [])} for q in questions or [] if q.get("qtype") != "hidden"]
