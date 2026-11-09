"""Generic adapter for single-page forms (Lever, Ashby, many company sites).
Fields were discovered by scan_form, so each field key is already a CSS selector."""
from __future__ import annotations

import re

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from .base import NeedsYou, css_for, dismiss_banners, fill_field, scan_form

APPLY_BUTTONS = ['a:has-text("Apply for this job")', 'a:has-text("Apply now")', 'button:has-text("Apply now")',
                 'a:has-text("Apply")', 'button:has-text("Apply")']


APPLY_EXACT = re.compile(r"^\s*apply(\s+now|\s+(for|to)\s+(this|the)\s+(job|role|position))?\s*$", re.I)


async def open_form(page: Page, url: str) -> list[str]:
    """Open the application form. Returns the words of any cookie-banner button pressed on the way."""
    early = await _open(page, url)
    return early + await dismiss_banners(page)      # before anything is read or clicked: a banner covers fields


async def _open(page: Page, url: str) -> list[str]:
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(1500)
    # Lever/Ashby job pages have a separate application page
    if "lever.co" in url and not url.rstrip("/").endswith("/apply"):
        await page.goto(url.rstrip("/") + "/apply", wait_until="domcontentloaded")
        return []
    if "ashbyhq.com" in url and "/application" not in url:
        await page.goto(url.split("?")[0].rstrip("/") + "/application", wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        return []
    if await page.locator("form input, form textarea").count() < 3:
        early = await dismiss_banners(page)      # it can cover the Apply button too
        await _press_apply(page)
        return early
    return []


async def _press_apply(page: Page) -> None:
    """Press the posting's Apply button, if it has one: first a button or link that says just that ("Apply", "Apply
    to this job"), then one that merely has the word (a menu called "How to Apply" comes last). A press that
    something on the page swallows moves on to the next after a few seconds; when none works, or the site then asks
    for a sign-in, that's yours (NeedsYou) and says so, instead of a browser's timeout."""
    from .multistep import needs_sign_in
    exact = [el for role in ("button", "link") for el in await page.get_by_role(role, name=APPLY_EXACT).all()]
    loose = [el for sel in APPLY_BUTTONS for el in await page.locator(sel).all()]
    # the menu is tried only when nothing says just "Apply": pressing it past a covered Apply button opens no form
    shown = [el for el in (exact or loose) if await el.is_visible()]
    for btn in shown:
        try:
            await btn.click(timeout=4000)
        except PlaywrightTimeout:
            continue
        await page.wait_for_timeout(2500)
        if await needs_sign_in(page):
            raise NeedsYou("asks you to sign in before it shows its application form")
        return
    if shown:
        raise NeedsYou("has an Apply button Jobsmith couldn't press (something on the page covers it)")


async def scan(page: Page, url: str) -> list[dict]:
    await open_form(page, url)
    return await scan_form(page)


def _file_key(d: dict) -> str:
    t = (d["label"] + " " + d["field"]).lower()
    return "transcript" if "transcript" in t else "cover_letter" if "cover" in t else "resume"


async def fill(page: Page, drafts: list[dict], files: dict[str, str]) -> dict:
    filled, failed, sent = [], [], []    # sent: the field ids actually set, for the audit trail
    banners = await dismiss_banners(page)      # one that showed up after the page opened
    for d in drafts:
        value = d["value"]
        fp = None
        if d["qtype"] == "file":
            fp = files.get(_file_key(d))
            if not fp:
                continue
        elif not value:
            if d["required"]:
                failed.append((d["label"], "no answer"))
            continue
        sel = css_for(d["field"])
        try:
            if not await page.locator(sel).count():
                if d["required"]:
                    failed.append((d["label"], "field not found on page"))
                continue
            ok = await fill_field(page, sel, d["qtype"], value, fp)
            (filled if ok else failed).append((d["label"], "ok" if ok else "could not set value"))
            sent += [d["field"]] if ok else []
        except Exception as e:
            failed.append((d["label"], f"{e.__class__.__name__}: {str(e)[:120]}"))
    return {"filled": filled, "failed": failed, "sent": sent, "banners": banners}
