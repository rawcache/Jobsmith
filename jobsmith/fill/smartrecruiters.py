"""SmartRecruiters adapter: fills the first page of SmartRecruiters' application ("Easy apply") from your answers.

SmartRecruiters draws its form from web components whose insides are shadow roots; the shared reader and fillers in
base.py walk those. What's SmartRecruiters' own:

- the "autocomplete your application" upload (it reads a resume to fill the form for you) and Apply With LinkedIn,
  Indeed or SEEK are never used: Jobsmith fills the form itself, from your answers, and signs in nowhere;
- a file box's question is its section's title ("Resume *"), not the dropzone's "Choose a file or drop it here";
- the form asks more after its Next button (shown on the saved Bosch form, tests/fixtures/smartrecruiters_bosch_form.html),
  and those pages haven't been seen yet. So Jobsmith fills the first page and stops there for you: it never presses
  Next or Submit (`HOLD`).

Never press Submit here, type a password, or solve a CAPTCHA: the runner decides, and hands those to you.
"""
from __future__ import annotations

import re

from playwright.async_api import Page

from . import generic
from .base import css_for, dismiss_banners, scan_form

HOLD = ("SmartRecruiters asks more after its Next button, and Jobsmith fills only its first page so far: "
        "check it, then press Next and finish it yourself")

# The posting's button to the form (docs/guides/save-smartrecruiters-form.md). Never "Apply with LinkedIn" and so on.
INTERESTED = re.compile(r"^\s*I['’]m interested\s*$", re.I)

# Where a file box sits: the autocomplete upload is skipped; any other takes its section's title and required mark.
_FILE_JS = r"""
e => {
  const up = n => n.parentNode instanceof ShadowRoot ? n.parentNode.host : n.parentElement;
  for (let n = e; n; n = up(n)) {
    if (n.dataset && n.dataset.test === 'apply-with-resume-container') return { skip: true };
    if (n.classList && n.classList.contains('form-section')) {
      const t = n.querySelector('[data-test="section-title"]');
      if (!t) break;
      const mark = t.querySelector('[data-test="section-required-mark"]');
      const words = t.textContent.replace(mark ? mark.textContent : '', ' ').replace(/\s+/g, ' ').trim();
      return { skip: false, label: words, required: !!mark };
    }
  }
  return { skip: false };
}
"""


async def open_form(page: Page, url: str) -> list[str]:
    """Open the form: a posting's page shows "I'm interested", which leads to it. Returns the cookie-banner buttons
    pressed on the way (the most private choice)."""
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(1500)
    pressed = await dismiss_banners(page)
    if not await page.locator('input[id="first-name-input"]').count():
        btn = page.locator("a, button").filter(has_text=INTERESTED).first
        if await btn.count() and await btn.is_visible():
            await btn.click()
            await page.wait_for_timeout(2500)
            pressed += await dismiss_banners(page)
    return pressed


async def read(page: Page) -> list[dict]:
    """The form's questions, each by its own words."""
    out = []
    for f in await scan_form(page):
        if f["qtype"] == "file":
            where = await page.locator(css_for(f["field"])).first.evaluate(_FILE_JS)
            if where["skip"]:
                continue
            if where.get("label"):
                f = {**f, "label": where["label"], "required": f["required"] or where["required"]}
        out.append(f)
    return out


async def scan(page: Page, url: str) -> list[dict]:
    await open_form(page, url)
    return await read(page)


async def fill(page: Page, drafts: list[dict], files: dict[str, str]) -> dict:
    """Fill the first page and stop there (`HOLD`): the runner never submits a SmartRecruiters form."""
    result = await generic.fill(page, drafts, files)
    return {**result, "hold": HOLD}
