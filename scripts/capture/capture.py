"""Save a live job site's application form for a test fixture, read-only.

    uv run python scripts/capture/capture.py URL OUT.html

Headless, through jobsmith.readonly: only GETs and the named read queries there leave the browser. Every blocked
request is printed. The saved page is the rendered form with scripts removed; sanitize it
(Alex Rivera only, no real names or contact details) before it goes in tests/fixtures/.

Never sign in, create an account or solve a CAPTCHA with this; never point it at a form you've filled."""
from __future__ import annotations

import asyncio
import sys

from jobsmith.fill.base import browser_args
from jobsmith.readonly import allowed, guard  # noqa: F401  (allowed: what may leave the browser)


async def capture(url: str, out: str, wait_ms: int = 5000) -> list[tuple[str, str]]:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=browser_args())
        context = await browser.new_context()
        blocked = await guard(context)
        page = await context.new_page()
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
