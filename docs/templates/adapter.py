"""<Site name> adapter: fills <site>'s application form from the user's drafted answers.

Copy to jobsmith/fill/<site>.py. Never press Submit here, type a password, or solve a CAPTCHA:
the runner decides when to submit, and sign-ins and CAPTCHAs are handed to the user.
"""
from __future__ import annotations

from playwright.async_api import Page

from .base import fill_field


async def open_form(page: Page, url: str) -> None:
    """Open the posting and get to the application form (click "Apply" if the form isn't on the page)."""
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    # e.g. await page.get_by_role("button", name="Apply").click()


async def fill(page: Page, drafts: list[dict], files: dict[str, str], extras: dict | None = None) -> dict:
    """Fill every field we have an answer for. Return {"filled": [...], "missed": [...]} so the runner
    can hold the application for the user when something required is missing."""
    filled, missed = [], []
    for d in drafts:
        value = d.get("final_answer") or d.get("answer") or ""
        if not value and d.get("qtype") != "file":
            missed.append(d["field"])
            continue
        # Find the field (by label, name or id) and fill it, e.g.:
        # ok = await fill_field(page, selector, d["qtype"], value, files)
        # (filled if ok else missed).append(d["field"])
    return {"filled": filled, "missed": missed}
