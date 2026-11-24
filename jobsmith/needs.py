"""Needs you, with a link to where each one is fixed.

The same list feeds the dashboard's banner (`/api/needs`) and the agent's `jobsmith_status`, so an agent can hand the
user the exact page instead of describing menus. Each item says in plain words what's missing, which page fixes it
(`page`), and links straight there (`href` inside the dashboard, `link` as a full address).

Read-only, and never carries a profile value: it says "Say whether you're a US citizen", never the answer.
"""
from __future__ import annotations

from . import db, fixes, guardrails, profile
from .frontdoor import link

# Plain words for the profile facts that most often hold applications.
ASK = {
    "desired_pay": "Add your salary range",
    "languages": "Add the languages you speak",
    "us_citizen": "Say whether you're a US citizen",
    "security_clearance": "Say whether you have a security clearance",
    "citizenships": "Add your citizenship",
    "work_authorized_us": "Say whether you're authorized to work in the US",
    "needs_sponsorship": "Say whether you need visa sponsorship",
}
LABELS = {k: label for k, label, _ in profile.ANSWER_BANK}


def _item(key: str, kind: str, text: str, href: str, page: str, about: str, waiting: int = 0, base: str | None = None) -> dict:
    return {"key": key, "kind": kind, "text": text, "page": page, "href": href, "link": link(href, base),
            "about": about, "waiting": waiting}


def _from_fix(f: dict, names: dict[str, dict], base: str | None) -> dict:
    n = f.get("unblocks") or 0
    if f["kind"] == "resume_pdf":
        return _item(f["id"], "resume_pdf", "Add your resume as a PDF", "#/profile/resume",
                     "Profile page, under Resume", "you", n, base)
    if f["kind"] == "profile":
        key = f["key"]
        label = LABELS.get(key, key.replace("_", " "))
        text = f["title"] if f["title"].startswith("Confirm") else ASK.get(key, f"Add: {label}")
        return _item(f["id"], "profile", text, f"#/profile/{key}", f"Profile page, “{label}”", "you", n, base)
    if f["kind"] == "essay":
        return _item(f["id"], "essay", f["title"], "#/settings/saved-answers",
                     "Settings page, under Your saved answers", "you", n, base)
    # a written question: one several forms ask is answered once under Needs you on Home; one only a single
    # application asks is answered on that application's page
    if f.get("part") == "job" and f.get("jobs"):
        jid = f["jobs"][0]
        j = names.get(jid) or {}
        return _item(f["id"], "question", f["title"], f"#/job/{jid}",
                     f"the {j.get('company') or 'application'}'s application page", "job", n, base)
    return _item(f["id"], "question", f["title"], "#/", "Home page, under Needs you", "you", n, base)


def items(ai: tuple[bool, str] | None = None, base: str | None = None) -> list[dict]:
    """Everything held applications wait on, most-blocking first, each with its link. `ai` is (connected, message)
    from the engine's last check; None when unknown (then nothing is claimed about it)."""
    out: list[dict] = []
    if ai is not None and not ai[0]:
        out.append(_item("ai", "ai", "Connect your AI, so Jobsmith can write answers", "#/settings/ai",
                         "Settings page, under Your AI", "you", 0, base))
    fx = fixes.compute()
    names = {r["id"]: r for r in db.q("SELECT id, company, title FROM jobs WHERE status IN ('filled','error')")}
    out += [_from_fix(f, names, base) for f in fx["fixes"]]
    waiting = guardrails.awaiting_approval()
    for a in waiting:
        out.append(_item(f"approve:{a['job_id']}", "approval",
                         f"Approve the first application on {a['site_name']}: {a['company']}, {a['title']}",
                         f"#/job/{a['job_id']}", f"the {a['company']} application's review page", "job", 1, base))
    approving = {a["job_id"] for a in waiting}
    for app in fx["applications"]:
        if app["id"] in approving or not app["own"]:
            continue
        out.append(_item(f"job:{app['id']}", "application", f"{app['company']}, {app['title']}: {app['own'][0]}",
                         f"#/job/{app['id']}", f"the {app['company']} application's page", "job", 1, base))
    return out


def blocking(rows: list[dict]) -> list[dict]:
    """The ones about you (your AI, your resume, a profile answer, a saved answer, a question several forms ask):
    what the dashboard's banner lists. One application's own problems stay under Needs you on Home."""
    return [r for r in rows if r["about"] == "you"]
