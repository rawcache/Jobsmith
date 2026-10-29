"""Save a live job site's application form for a test fixture, read-only.

    uv run python scripts/capture/capture.py URL OUT.html

Headless. Every request that isn't a GET is blocked, except the reads listed in ALLOWED_READS: a site that loads
its form through a POST query (Ashby) can't render it otherwise. Those are let through only when the body is a
GraphQL `query` with that exact operation name, so a submit, autosave, upload or reCAPTCHA call never leaves the
browser. Every blocked request is printed. The saved page is the rendered form with scripts removed; sanitize it
(Alex Rivera only, no real names or contact details) before it goes in tests/fixtures/.

Never sign in, create an account or solve a CAPTCHA with this; never point it at a form you've filled."""
from __future__ import annotations

import asyncio
import json
import re
import sys
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


async def capture(url: str, out: str, wait_ms: int = 5000) -> list[tuple[str, str]]:
    from playwright.async_api import async_playwright
    blocked: list[tuple[str, str]] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        async def route(r):
            req = r.request
            if allowed(req.method, req.url, req.post_data):
                await r.continue_()
            else:
                blocked.append((req.method, req.url.split("?")[0]))
                await r.abort()
        await page.route("**/*", route)
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(wait_ms)
        html = await page.evaluate("""() => {
            const doc = document.documentElement.cloneNode(true);
            doc.querySelectorAll('script, noscript, iframe[src*="recaptcha"]').forEach(e => e.remove());
            return '<!doctype html>\\n' + doc.outerHTML;
        }""")
        await browser.close()
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return blocked


if __name__ == "__main__":
    for method, where in asyncio.run(capture(sys.argv[1], sys.argv[2])):
        print(f"blocked {method} {where}")
