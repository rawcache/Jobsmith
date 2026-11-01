"""Multi-page application flows (Workday, iCIMS, Oracle, SuccessFactors, ...). Beta.

Page by page: read the visible fields, answer the empty ones (your profile first, AI for the rest),
fill them, then click Next/Continue. Stops at the review page unless submitting is allowed.

Jobsmith never types passwords or creates accounts: when a sign-in page appears it waits for you to
sign in (or create the account) in its browser window, then carries on. The browser profile keeps
you signed in for next time.
"""
from __future__ import annotations

import re
from typing import Callable

from playwright.async_api import Page

from .base import CONFIRM_RE, BotWall, bot_wall, css_for, dismiss_banners, fill_field, form_view, scan_form

# iCIMS: "Apply for this job online" (its "Log back in!" link is a sign-in, never the start)
START_BUTTONS = ['[data-automation-id="adventureButton"]', 'a.iCIMS_ApplyOnlineButton', 'a:has-text("Apply Now")', 'button:has-text("Apply Now")',
                 'a:has-text("Apply")', 'button:has-text("Apply")']
AUTOFILL_BUTTONS = ['[data-automation-id="autofillWithResume"]', 'a:has-text("Autofill with Resume")',
                    'button:has-text("Autofill with Resume")', 'button:has-text("Upload Resume")']
# Workday's "Start Your Application" box without a resume to autofill from: fill it in by hand
MANUAL_BUTTONS = ['[data-automation-id="applyManually"]', 'a:has-text("Apply Manually")', 'button:has-text("Apply Manually")']
NEXT_BUTTONS = ['[data-automation-id="bottom-navigation-next-button"]', '[data-automation-id="pageFooterNextButton"]',
                'button:has-text("Save and Continue")', 'button:has-text("Continue")', 'button:has-text("Next")',
                'input[type="submit"][value*="Next" i]']
SUBMIT_TEXT = re.compile(r"^\s*submit( application)?\s*$", re.I)


async def _first_visible(page: Page, selectors: list[str]):
    for sel in selectors:
        loc = page.locator(sel)
        try:
            n = await loc.count()
        except Exception:
            continue
        for i in range(min(n, 5)):
            el = loc.nth(i)
            try:
                if await el.is_visible():
                    return el
            except Exception:
                continue
    return None


# A sign-in that offers ways in before any password box shows (Workday: Google, LinkedIn, or email; iCIMS: your
# email, then Next, which finds your account or starts a new one)
SIGN_IN_CHOICES = ['[data-automation-id="SignInWithEmailButton"]', '[data-automation-id="GoogleSignInButton"]',
                   'button:has-text("Sign in with email")', 'a:has-text("Sign in with email")',
                   '#enterEmailSubmitButton', 'form._form-login-id button._button-login-id']
# iCIMS's own login (login.icims.com, Auth0's "Username or email address" with "Continue with Google"...; the
# _form-login-id form above is Auth0's): a sign-in page wherever it's served
SIGN_IN_ADDRESSES = re.compile(r"^https://login\.icims\.com/", re.I)


async def needs_sign_in(page: Page) -> bool:
    page = form_view(page) if isinstance(page, Page) else page
    try:
        if SIGN_IN_ADDRESSES.search(page.url):
            return True
        if await page.locator('input[type="password"]:visible').count():
            return True
        if await _first_visible(page, SIGN_IN_CHOICES):
            return True
        body = (await page.locator("body").inner_text(timeout=3000))[:3000].lower()
        return ("sign in" in body or "create account" in body) and "password" in body
    except Exception:
        return False


async def submit_button(page: Page):
    for el in await page.locator('button, input[type="submit"]').all():
        try:
            if await el.is_visible():
                txt = (await el.inner_text()) if await el.evaluate("e => e.tagName") == "BUTTON" else \
                    (await el.get_attribute("value") or "")
                if SUBMIT_TEXT.match(txt or ""):
                    return el
        except Exception:
            continue
    return None


async def is_submit(el) -> bool:
    """Whether a button reads Submit (or Submit Application), whatever its id says."""
    try:
        tag = await el.evaluate("e => e.tagName")
        txt = await el.inner_text() if tag == "BUTTON" else (await el.get_attribute("value") or "")
        return bool(SUBMIT_TEXT.match(txt or ""))
    except Exception:
        return False


async def page_errors(page: Page) -> list[str]:
    errs = []
    for sel in ('[role="alert"]', '[data-automation-id="errorMessage"]', '.error', '[class*="error"]'):
        for el in (await page.locator(sel).all())[:6]:
            try:
                if await el.is_visible():
                    t = " ".join((await el.inner_text()).split())
                    if t and t not in errs and len(t) < 200:
                        errs.append(t)
            except Exception:
                continue
    return errs[:6]


async def run(page: Page, url: str, *, answer: Callable, files: dict, log: Callable, wait_for_user: Callable,
              allow_submit: Callable, max_pages: int = 15, on_page: Callable | None = None,
              on_filled: Callable | None = None, on_nodes: Callable | None = None) -> dict:
    """answer(fields) -> {field: value}; wait_for_user(message, check) waits until check() is true.
    on_page(text) gets each page's text once it's filled, before allow_submit() is asked on that page;
    on_nodes(nodes) the same page's text with what's hidden (traps.PAGE_JS), for lines aimed at AI;
    on_filled(field) each field it actually set (the audit trail records only those).
    Raises BotWall when a page is a bot check instead of the form."""
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(2500)
    filled_total, issues = 0, []

    await dismiss_banners(page, log)
    view = form_view(page)                       # iCIMS: the application is in a frame of the page
    start = await _first_visible(view, START_BUTTONS)
    if start and not await view.locator("form input:visible, form textarea:visible").count():
        await start.click()
        await page.wait_for_timeout(2500)
        view = form_view(page)
        # Workday's "Start Your Application": from your resume when there is one, else by hand. Either way the
        # next page (often a sign-in) is checked like any other
        how = (files.get("resume") and await _first_visible(view, AUTOFILL_BUTTONS)) or \
            await _first_visible(view, MANUAL_BUTTONS)
        if how:
            await how.click()
            await page.wait_for_timeout(2500)

    for page_no in range(1, max_pages + 1):
        if wall := await bot_wall(page):        # never got past: the runner hands it to you
            raise BotWall(wall)
        if await needs_sign_in(page):
            log("This site needs you to sign in or create an account. Do it in the Jobsmith browser window; "
                "Jobsmith continues automatically (it never types passwords).")
            ok = await wait_for_user("Sign in to continue the application", lambda: needs_sign_in(page), negate=True)
            if not ok:
                return {"status": "waiting_user", "filled": filled_total, "issues": ["Sign-in not completed"]}
            await page.wait_for_timeout(2000)

        await dismiss_banners(page, log)           # each page can bring its own
        view = form_view(page)
        auto = await _first_visible(view, AUTOFILL_BUTTONS)
        if auto and files.get("resume"):
            await auto.click()
            await page.wait_for_timeout(1500)
            view = form_view(page)                 # the click can bring a new page, or a new frame

        fields = [f for f in await scan_form(view) if f["qtype"] != "hidden"]
        todo = [f for f in fields if not f.get("value")]
        log(f"Page {page_no}: {len(fields)} fields, {len(todo)} empty")
        answers = await answer(todo) if todo else {}
        for f in todo:
            val = answers.get(f["field"], "")
            fp = None
            if f["qtype"] == "file":
                t = (f["label"] + f["field"]).lower()
                fp = files.get("transcript" if "transcript" in t else "cover_letter" if "cover" in t else "resume")
                if not fp or ("transcript" in t and not f["required"]):
                    continue
            elif not val:
                if f["required"]:
                    issues.append(f"{f['label']}: no answer")
                continue
            try:
                ok = await fill_field(view, css_for(f["field"]), f["qtype"], val, fp)
                filled_total += int(bool(ok))
                if ok and on_filled:
                    on_filled(f["field"])
                if not ok and f["required"]:
                    issues.append(f"{f['label']}: couldn't set '{val[:40]}'")
            except Exception as e:
                if f["required"]:
                    issues.append(f"{f['label']}: {e.__class__.__name__}")

        try:
            body = await view.locator("body").inner_text(timeout=3000)
            if on_page:
                on_page(body)
            if CONFIRM_RE.search(body):
                return {"status": "submitted", "filled": filled_total, "issues": issues}
        except Exception:
            pass

        if on_nodes:
            from ..traps import PAGE_JS
            try:
                on_nodes(await view.evaluate(PAGE_JS))
            except Exception:
                pass

        nxt = await _first_visible(view, NEXT_BUTTONS)
        sub = await submit_button(view)
        if nxt and await is_submit(nxt):
            # Workday's Review page: its footer "Next" button (pageFooterNextButton) reads Submit, and pressing it
            # sends the application. It is the Submit, asked for like any other
            sub, nxt = sub or nxt, None
        if sub and not nxt:
            if not issues and allow_submit():      # asked last: it counts the submission toward the caps
                log("Review page reached and everything is trusted: submitting.")
                await sub.click()
                await page.wait_for_timeout(4000)
                return {"status": "submitted_clicked", "filled": filled_total, "issues": issues}
            log("Review page reached. Stopped before Submit.")
            return {"status": "review", "filled": filled_total, "issues": issues}
        if not nxt:
            log("No Next button found on this page.")
            return {"status": "stuck", "filled": filled_total, "issues": issues + ["No Next button"]}
        before = view.url + str(len(fields))
        await nxt.click()
        await page.wait_for_timeout(2500)
        view = form_view(page)
        after_fields = await scan_form(view)
        if view.url + str(len(after_fields)) == before:
            errs = await page_errors(view)
            if errs:
                log("The site didn't accept this page: " + "; ".join(errs))
                return {"status": "stuck", "filled": filled_total, "issues": issues + errs}
    return {"status": "stuck", "filled": filled_total, "issues": issues + ["Too many pages"]}
