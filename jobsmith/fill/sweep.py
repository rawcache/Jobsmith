"""A last pass over the live form: anything required and still empty gets answered and filled.

Job-board APIs don't list every field a live form shows (Greenhouse's newer forms add an Employment section,
for one). So after the main fill, Jobsmith reads the page itself, answers what's left the same way it
answers everything (your profile, then your approved answers, then AI with citations), and fills it."""
from __future__ import annotations

import re

from .. import draft, profile
from .base import fill_field, scan_form

EMPLOY = re.compile(r"employ|experience|work history|professional history|positions?", re.I)


def _recent_job() -> dict | None:
    xs = profile.entries("experience")
    return xs[0] if xs else None


def employment_value(f: dict) -> str | None:
    """Fields in an Employment section, from your most recent role. None when it isn't one of those."""
    if not EMPLOY.search(f.get("group") or ""):
        return None
    e = _recent_job()
    if not e:
        return None
    label = (f.get("label") or "").lower()
    current = str(e.get("end", "")).lower() in ("", "present", "current", "now")
    if re.search(r"company|employer|organi[sz]ation", label):
        return e.get("company", "")
    if re.search(r"^title|job title|position|role$", label):
        return e.get("title", "")
    m = re.search(r"(start|end)\w*\s*(date)?\s*(month|year)", label)
    if m:
        which = e.get("start", "") if m.group(1) == "start" else ("" if current else e.get("end", ""))
        month, year = draft._month_year(which)
        return month if m.group(3) == "month" else year
    if re.search(r"current(ly)? (role|position|job|work)|i currently work", label):
        return "Yes" if current else ""
    if re.search(r"location|city", label):
        return e.get("location", "")
    return None


async def sweep(page, job: dict, log=None) -> dict:
    fields = [f for f in await scan_form(page)
              if f["required"] and not f.get("value") and f["qtype"] not in ("file", "hidden")]
    if not fields:
        return {"filled": [], "failed": [], "sent": []}
    for f in fields:
        f.setdefault("options", [])
    results: dict[str, dict] = {}
    rest = []
    for f in fields:
        v = employment_value(f)
        if v is not None:
            results[f["field"]] = {"kind": "answer_bank", "canon": "employment", "answer": v,
                                   "confidence": 1.0 if v else 0, "issues": [] if v else ["Add your work history on the Profile page"]}
        else:
            rest.append(f)
    if rest:
        more, _err = await draft.answer_fields(job, rest, skip_locked=False)
        results.update(more)
    filled, failed, sent = [], [], []
    for f in fields:
        val = (results.get(f["field"]) or {}).get("answer", "")
        if not val:
            failed.append((f["label"], "no answer"))
            continue
        try:
            ok = await fill_field(page, f["field"], f["qtype"], val)
        except Exception as e:  # noqa: BLE001
            ok = False
            if log:
                log(f"  {f['label']}: {e.__class__.__name__}")
        (filled if ok else failed).append((f["label"], "ok") if ok else (f["label"], f"couldn't set \"{val[:40]}\""))
        sent += [f["field"]] if ok else []
    draft.save_results(job["id"], [f for f in fields if f["field"] in results],
                       {k: v for k, v in results.items()})
    if log and fields:
        log(f"Second pass over the page: filled {len(filled)} more field{'s' if len(filled) != 1 else ''}"
            + (f", {len(failed)} still need you" if failed else ""))
    return {"filled": filled, "failed": failed, "sent": sent}
