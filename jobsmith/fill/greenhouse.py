"""Greenhouse adapter. Questions come from the public job-board API, so drafting needs no
browser; filling maps each API field name onto the form."""
from __future__ import annotations

import re

from playwright.async_api import Page, TimeoutError as PWTimeout

from .. import ats
from .base import combobox_text, css_for, fill_combobox, fill_field

# The new job-boards UI renames a few API fields.
FIELD_ALIASES = {
    "location": ['#candidate-location', '[id="location"]', '[name="location"]'],
    "gender": ['#gender', '[id="job_application_gender"]'],
    "race": ['#race', '[id="job_application_race"]'],
    "hispanic_ethnicity": ['#hispanic_ethnicity', '[id="job_application_hispanic_ethnicity"]'],
    "veteran_status": ['#veteran_status', '[id="job_application_veteran_status"]'],
    "disability_status": ['#disability_status', '[id="job_application_disability_status"]'],
}


async def open_form(page: Page, url: str) -> None:
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    try:
        await page.locator("#first_name").first.wait_for(timeout=15000)
        return
    except PWTimeout:
        pass
    # Company-hosted page or legacy board: fall back to the embeddable form.
    board, job_id, region = ats.greenhouse_ids(url)
    host = "boards.eu.greenhouse.io" if region == "eu" else "boards.greenhouse.io"
    await page.goto(f"https://{host}/embed/job_app?for={board}&token={job_id}", wait_until="domcontentloaded")
    await page.locator("#first_name").first.wait_for(timeout=20000)


async def selector_for(page: Page, field: str) -> str | None:
    extra = [f'[id="{field.split("_", 1)[1]}"]'] if field.startswith("demographic_") else []
    cands = FIELD_ALIASES.get(field, []) + extra + [css_for(field), f'[name="{field}"]', f'[name="{field}[]"]',
                                             f'[name="job_application[{field}]"]']
    for c in cands:
        try:
            if await page.locator(c).count():
                return c
        except Exception:
            continue
    return None


def _file_key(d: dict) -> str:
    t = (d["label"] + " " + d["field"]).lower()
    return "transcript" if "transcript" in t else "cover_letter" if "cover" in t else "resume"


async def fill_implicit(page: Page, extras: dict) -> list[tuple[str, str]]:
    """Fields the live form has but the job-board API doesn't list (phone country, Hispanic/Latino)."""
    done = []
    if extras.get("country") and await page.locator('#country').count():
        cur = await combobox_text(page, '#country')
        if not cur or cur.lower().startswith("select"):
            if await fill_combobox(page, '#country', extras["country"]):
                done.append(("Phone country", "ok"))
    if extras.get("hispanic_latino") and await page.locator('#hispanic_ethnicity').count():
        if await fill_combobox(page, '#hispanic_ethnicity', extras["hispanic_latino"]):
            done.append(("Hispanic/Latino", "ok"))
    return done


async def fill(page: Page, drafts: list[dict], files: dict[str, str], extras: dict | None = None) -> dict:
    """files: {'resume': path, 'cover_letter': path}. Returns per-field results."""
    filled, failed, sent = [], [], []    # sent: the field ids actually set, for the audit trail
    done = await fill_implicit(page, extras or {})
    filled += done
    implicit = [{"field": control, "label": label, "canon": canon, "profile": (extras or {}).get(canon, "")}
                for label, canon, control in (("Phone country", "country", "country"),
                                              ("Hispanic/Latino", "hispanic_latino", "hispanic_ethnicity"))
                if (label, "ok") in done]
    for d in drafts:
        value = d["value"]
        if d["qtype"] == "file":
            fp = files.get(_file_key(d))
            if not fp:
                if d["required"]:
                    failed.append((d["label"], "no file available"))
                continue
        elif not value:
            if d["required"]:
                failed.append((d["label"], "no answer"))
            continue
        else:
            fp = None
        sel = await selector_for(page, d["field"])
        if not sel and d["qtype"] == "file" and "cover" in d["field"] and d.get("alt_field"):
            sel = await selector_for(page, d["alt_field"])
            d = dict(d, qtype="textarea")
        if not sel:
            # Greenhouse's API lists education fields some live forms don't show: not a problem then.
            if d["required"] and not re.match(r"(school|degree|discipline|start-month|start-year|end-month|end-year)--\d", d["field"]):
                failed.append((d["label"], "field not found on page"))
            continue
        try:
            if d["field"] == "location" and await page.locator(sel).first.get_attribute("role") == "combobox":
                city = value.split(",")[0].strip()
                ok = await fill_combobox(page, sel, (extras or {}).get("location_full") or value, query=city,
                                         wait_ms=10000)
                (filled if ok else failed).append((d["label"], "ok") if ok else (d["label"], "pick your city"))
                sent += [d["field"]] if ok else []
                continue
            ok = await fill_field(page, sel, d["qtype"], value, fp)
            (filled if ok else failed).append((d["label"], "ok") if ok else (d["label"], f"no option matched \"{value[:40]}\""))
            sent += [d["field"]] if ok else []
        except Exception as e:
            failed.append((d["label"], f"{e.__class__.__name__}: {str(e)[:120]}"))
    # Filled from your profile without a draft, so the audit trail records them too, with what the box shows
    # (the option picked, like "United States +1"). One a draft later filled again is that draft's.
    implicit = [i for i in implicit if i["field"] not in sent]
    for i in implicit:
        i["answer"] = await combobox_text(page, f'#{i["field"]}') or i["profile"]
    return {"filled": filled, "failed": failed, "sent": sent, "implicit": implicit}
