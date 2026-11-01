"""Weekly canary: does Jobsmith still read each supported job site's live form?

    uv run python scripts/canary/canary.py [--out report.json] [--site greenhouse|lever|ashby]

For each site in ats.SUPPORTED it finds one current public posting through the site's own public job list (a GET),
opens its application form headless the way autopilot would, behind jobsmith/readonly.py (only GETs, plus the named
read queries there, leave the browser; every other request is blocked and listed), and checks that Jobsmith still
finds every field, gives each one a label and a kind, and finds the standard ones (name, email, resume). Nothing is
typed and nothing is pressed but Apply and a cookie banner's reject button. No sign-in, no credentials, no AI.

Exit status 0 when every site passes, 1 otherwise; the report says what broke. The scheduled workflow
(.github/workflows/canary.yml) opens an issue labelled `canary` on a failure."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request
from dataclasses import asdict, dataclass, field

from jobsmith import ats, classify
from jobsmith.fill import base, generic, greenhouse
from jobsmith.readonly import guard

# One company per site, the same ones the saved fixtures come from: big boards that always have postings.
BOARDS = {
    "greenhouse": ("figma", "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"),
    "lever": ("palantir", "https://api.lever.co/v0/postings/{board}?mode=json&limit=5"),
    "ashby": ("ramp", "https://api.ashbyhq.com/posting-api/job-board/{board}"),
}
QTYPES = {"text", "textarea", "select", "multiselect", "radio", "checkbox", "file", "listbox"}   # what scan_form gives
STANDARD = {"name": ("first_name", "full_name"), "email": ("email",), "resume": ("resume",)}
MIN_FIELDS = 5


@dataclass
class Result:
    site: str
    posting: str = ""
    fields: int = 0
    problems: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)      # requests the page tried to send (blocked, not a failure)

    @property
    def ok(self) -> bool:
        return not self.problems


def posting_url(site: str, listing: object) -> str:
    """The first posting's address from a site's public job list (its JSON, already fetched)."""
    if site == "greenhouse":
        return listing["jobs"][0]["absolute_url"]
    if site == "lever":
        return listing[0]["applyUrl"]
    if site == "ashby":
        return next(j for j in listing["jobs"] if j.get("isListed", True))["applyUrl"]
    raise ValueError(site)


def find_posting(site: str) -> str:
    board, api = BOARDS[site]
    req = urllib.request.Request(api.format(board=board), headers={"Accept": "application/json",
                                                                   "User-Agent": "jobsmith-canary"})
    with urllib.request.urlopen(req, timeout=30) as r:          # a GET
        return posting_url(site, json.loads(r.read()))


def check_fields(fields: list[dict]) -> list[str]:
    """What's wrong with what was read from a form: too few fields, a field with no label or an unknown kind, or a
    standard field (name, email, resume) not found."""
    problems = []
    shown = [f for f in fields if f.get("qtype") != "hidden"]
    if len(shown) < MIN_FIELDS:
        problems.append(f"found {len(shown)} fields, expected at least {MIN_FIELDS}")
    for f in shown:
        if not (f.get("label") or "").strip():
            problems.append(f"a {f.get('qtype')} field ({f.get('field', '')[:60]}) has no label")
        if f.get("qtype") not in QTYPES:
            problems.append(f"\"{f.get('label', '')[:60]}\" is of a kind Jobsmith doesn't know: {f.get('qtype')}")
    canons = {classify.canon_for(f.get("label") or "") for f in shown} | \
        {"resume" for f in shown if f.get("qtype") == "file" and "resume" in (f.get("label", "") + f.get("field", "")).lower()}
    for what, keys in STANDARD.items():
        if not canons & set(keys):
            problems.append(f"no {what} field found")
    return problems


async def run_site(site: str, browser) -> Result:
    res = Result(site)
    try:
        res.posting = find_posting(site)
    except Exception as e:                                       # the list itself changed or is down
        res.problems.append(f"couldn't find a posting in {site}'s public job list: {e.__class__.__name__}: {e}")
        return res
    context = await browser.new_context(viewport={"width": 1280, "height": 900})
    blocked = await guard(context)
    try:
        page = await context.new_page()
        adapter = greenhouse if site == "greenhouse" else generic
        await adapter.open_form(page, res.posting)
        await page.wait_for_timeout(2000)
        if wall := await base.bot_wall(page):
            res.problems.append(f"the site showed a bot check: {wall}")
            return res
        fields = await base.scan_form(page)
        res.fields = len(fields)
        res.problems += check_fields(fields)
    except Exception as e:
        res.problems.append(f"{e.__class__.__name__}: {str(e)[:300]}")
    finally:
        res.blocked = sorted({f"{m} {u}" for m, u in blocked})[:40]
        await context.close()
    return res


async def main(sites: list[str]) -> list[Result]:
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=base.browser_args())
        try:
            return [await run_site(s, browser) for s in sites]
        finally:
            await browser.close()


def summary(results: list[Result]) -> str:
    """Markdown for the issue a failure opens (and the job's summary)."""
    lines = ["| Site | Posting | Fields | Result |", "| --- | --- | --- | --- |"]
    for r in results:
        lines.append(f"| {r.site} | {r.posting or '–'} | {r.fields} | {'ok' if r.ok else '; '.join(r.problems)} |")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="write the report as JSON here")
    ap.add_argument("--site", action="append", choices=sorted(ats.SUPPORTED))
    a = ap.parse_args()
    results = asyncio.run(main(a.site or sorted(ats.SUPPORTED)))
    print(summary(results))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump([{**asdict(r), "ok": r.ok} for r in results], f, indent=2)
    sys.exit(0 if all(r.ok for r in results) else 1)
