"""Read-only visits to live job sites: what may leave the browser, and a guard that blocks everything else.

Saving a form for a test fixture (scripts/capture/capture.py) and the weekly canary both open real postings. On
those visits only a GET leaves the browser, plus the reads named in ALLOWED_READS: a site that loads its form
through a POST query (Ashby) can't render it otherwise. Those are let through only when the body is a GraphQL
`query` with that exact operation name, so a submit, autosave, upload or CAPTCHA call never leaves. Never sign in,
create an account or solve a CAPTCHA on such a visit; never point it at a form you've filled."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

# host -> path -> GraphQL operations that only read. Each entry is a reason the Phase 1 read-only rule bends, and
# is recorded in docs/PHASE1.md.
ALLOWED_READS = {
    "jobs.ashbyhq.com": {"/api/non-user-graphql": {"ApiJobPosting", "ApiOrganizationFromHostedJobsPageName"}},
}


def allowed(method: str, url: str, body: str | None) -> bool:
    """True for a GET, or for one of ALLOWED_READS sent as a GraphQL query (never a mutation)."""
    if method == "GET":
        return True
    if method != "POST":
        return False
    u = urlsplit(url)
    ops = ALLOWED_READS.get(u.hostname or "", {}).get(u.path)
    op = (parse_qs(u.query).get("op") or [""])[0]
    if not ops or op not in ops:
        return False
    try:
        payload = json.loads(body or "")
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict) or payload.get("operationName") != op:
        return False
    # One named query, nothing else in the document: "query ApiJobPosting(…) { … }"
    query = payload.get("query") or ""
    return bool(re.match(rf"\s*query\s+{op}\b", query)) and not re.search(r"\b(mutation|subscription)\b", query)


async def guard(context) -> list[tuple[str, str]]:
    """Block every request from a Playwright browser context that `allowed` refuses. Returns the list the blocked
    requests are added to (method, URL without its query), so a caller can show what the page tried to send.
    Guard the context, not a page, so pop-ups are covered too. Playwright asks the newest route first, so call
    this after any other routes: an allowed request falls back to them, then the network."""
    blocked: list[tuple[str, str]] = []

    async def route(r):
        req = r.request
        if allowed(req.method, req.url, req.post_data):
            await r.fallback()
        else:
            blocked.append((req.method, req.url.split("?")[0]))
            await r.abort()
    await context.route("**/*", route)
    return blocked
