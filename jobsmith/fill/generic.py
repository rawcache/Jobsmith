"""Generic adapter for single-page forms (Lever, Ashby, many company sites).
Fields were discovered by scan_form, so each field key is already a CSS selector."""
from __future__ import annotations

from playwright.async_api import Page

from .base import css_for, fill_field, scan_form

APPLY_BUTTONS = ['a:has-text("Apply for this job")', 'a:has-text("Apply now")', 'button:has-text("Apply now")',
                 'a:has-text("Apply")', 'button:has-text("Apply")']


async def open_form(page: Page, url: str) -> None:
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(1500)
    # Lever/Ashby job pages have a separate application page
    if "lever.co" in url and not url.rstrip("/").endswith("/apply"):
        await page.goto(url.rstrip("/") + "/apply", wait_until="domcontentloaded")
        return
    if "ashbyhq.com" in url and "/application" not in url:
        await page.goto(url.split("?")[0].rstrip("/") + "/application", wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        return
    if await page.locator("form input, form textarea").count() < 3:
        for sel in APPLY_BUTTONS:
            btn = page.locator(sel).first
            if await btn.count() and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(2500)
                break


async def scan(page: Page, url: str) -> list[dict]:
    await open_form(page, url)
    return await scan_form(page)


def _file_key(d: dict) -> str:
    t = (d["label"] + " " + d["field"]).lower()
    return "transcript" if "transcript" in t else "cover_letter" if "cover" in t else "resume"


async def fill(page: Page, drafts: list[dict], files: dict[str, str]) -> dict:
    filled, failed, sent = [], [], []    # sent: the field ids actually set, for the audit trail
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
    return {"filled": filled, "failed": failed, "sent": sent}
