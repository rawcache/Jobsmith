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

from jobsmith import ats, classify, jobdetail
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
KINDS = {"choice", "file", "location", "yes_no", "essay", "open", "short"}      # classify.question_kind
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
    """What's wrong with what was read from a form: too few fields, a field with no label or of an unknown kind, a
    question Jobsmith can't say what answer it wants, or a standard field (name, email, resume) not found or not
    classified as it should be (email a short answer, resume a file)."""
    problems = []
    shown = [f for f in fields if f.get("qtype") != "hidden"]
    if len(shown) < MIN_FIELDS:
        problems.append(f"found {len(shown)} fields, expected at least {MIN_FIELDS}")
    for f in shown:
        # with no words of its own, a box is read by its name or id ("q_123"): as good as no label (the scan
        # says so: `unworded`)
        if not (f.get("label") or "").strip() or f.get("unworded"):
            problems.append(f"a {f.get('qtype')} field ({f.get('field', '')[:60]}) has no label")
        if f.get("qtype") not in QTYPES:
            problems.append(f"\"{f.get('label', '')[:60]}\" is of a kind Jobsmith doesn't know: {f.get('qtype')}")
    for f in shown:
        kind = classify.question_kind(f.get("label") or "", f.get("qtype") or "", f.get("options"))
        if kind not in KINDS:
            problems.append(f"\"{f.get('label', '')[:60]}\": no answer kind ({kind})")
        canon = classify.canon_for(f.get("label") or "")
        if canon == "email" and kind != "short":
            problems.append(f"\"{f.get('label', '')[:60]}\" asks for your email but reads as {kind}")
        if f.get("qtype") == "file" and kind != "file":
            problems.append(f"\"{f.get('label', '')[:60]}\" is an upload but reads as {kind}")
    canons = {classify.canon_for(f.get("label") or "") for f in shown} | \
        {"resume" for f in shown if f.get("qtype") == "file" and "resume" in (f.get("label", "") + f.get("field", "")).lower()}
    for what, keys in STANDARD.items():
        if not canons & set(keys):
            problems.append(f"no {what} field found")
    return problems


def check_greenhouse_api(data: dict) -> list[str]:
    """Greenhouse's job API, where autopilot reads a Greenhouse form's questions: every question's kind is one
    Jobsmith knows (an unknown one would be read as a text box), and the questions it gives pass check_fields."""
    problems = []
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        return ["Greenhouse's job API gave no questions list"]
    # every section normalize_greenhouse reads: an unknown kind in any of them would quietly become a text box
    asked = list(data["questions"]) + list(data.get("location_questions") or []) + \
        [q for block in data.get("compliance") or [] for q in (block.get("questions") or [])]
    for q in asked:
        for f in (q.get("fields") or []) if isinstance(q, dict) else []:
            if f.get("type") not in jobdetail.GH_TYPES:
                problems.append(f"Greenhouse question \"{str(q.get('label'))[:60]}\" is of a new kind: {f.get('type')}")
    demo = data.get("demographic_questions") or {}
    for q in (demo.get("questions") if isinstance(demo, dict) else None) or []:
        if q.get("type") not in ("multi_value_single_select", "multi_value_multi_select"):
            problems.append(f"Greenhouse question \"{str(q.get('label'))[:60]}\" is of a new kind: {q.get('type')}")
    return problems + [f"in Greenhouse's job API: {p}" for p in check_fields(jobdetail.normalize_greenhouse(data))]


def greenhouse_api(posting: str) -> dict:
    board, job_id, region = ats.greenhouse_ids(posting)
    host = "boards-api.eu.greenhouse.io" if region == "eu" else "boards-api.greenhouse.io"
    req = urllib.request.Request(f"https://{host}/v1/boards/{board}/jobs/{job_id}?questions=true",
                                 headers={"Accept": "application/json", "User-Agent": "jobsmith-canary"})
    with urllib.request.urlopen(req, timeout=30) as r:          # a GET
        return json.loads(r.read())


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
        # what the page holds before any field without a label is dropped (scan_form drops them; here they count)
        seen, fields = set(), []
        for f in await page.evaluate(base.SCAN_JS):
            if f["field"] not in seen and not base.HONEYPOT.search(f["label"] or ""):
                seen.add(f["field"])
                fields.append(f)
        res.fields = len(fields)
        res.problems += check_fields(fields)
        if site == "greenhouse" and res.posting.startswith("http"):
            res.problems += check_greenhouse_api(greenhouse_api(res.posting))
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
