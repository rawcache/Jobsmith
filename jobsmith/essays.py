"""Your own answers to the essay questions most forms ask, saved once and used as you wrote them.

"Why do you want to join <company>?", "Why this role?", "Additional information" and a cover letter come up on
form after form. Save yours once (Needs you or Profile) and every form that asks one gets it: your words, never
changed by Jobsmith or an AI, marked "your saved answer", and counted as filled. Two slots are filled in for you:
{company} becomes the company's name and {role} the job's title. Nothing else in the text is touched.

An optional essay box you have no saved answer for is left blank: it never holds an application, and no AI is
spent writing it."""
from __future__ import annotations

import re

from . import classify, db

KINDS: dict[str, str] = {
    "why_company": "Why do you want to join {company}?",
    "why_role": "Why this role?",
    "additional_info": "Additional information",
    "cover_letter": "Cover letter",
}
SAVED = "your saved answer"

_COVER = re.compile(r"\bcover ?letter\b", re.I)
_ADDITIONAL = re.compile(r"^\s*(additional|other) (information|info|comments?|details|notes)\b|anything else (you('d| would)"
                         r" like|we should|to (share|add|tell))|is there anything (else )?(you('d| would) like|we should)",
                         re.I)
_ROLE = re.compile(r"why (this|the) (role|position|job|internship|opportunity|team)|why (are you|do you want)( \w+){0,3} "
                   r"(apply(ing)?|interested)( \w+){0,3} (this|the) (role|position|job|internship|opportunity)|"
                   r"interest(ed)? in (this|the) (role|position|job|internship|opportunity)", re.I)
_COMPANY = re.compile(r"why (do you want to|would you like to) (join|work (at|for|with))|why (us|join)\b|"
                      r"why (are you|do you want)( \w+){0,3} (interested in|to work (at|for)|applying to) "
                      r"(us|our (company|team|organi[sz]ation)|this (company|organi[sz]ation))|"
                      r"interest(ed)? in (joining|working (at|for|with)|our (company|team|mission))|"
                      r"what (excites|interests|draws|attracts) you (about|to) (us|our|working|joining|this company)", re.I)


def kind_of(label: str, company: str = "", qtype: str = "textarea") -> str | None:
    """Which saved answer a question asks for, or None. A question naming the company ("Why Acme?", "Why are you
    interested in Acme and this role?") is the company one; one only about the job is the role one."""
    text = " ".join((label or "").split())
    if not text:
        return None
    if _COVER.search(text):
        return "cover_letter"
    if qtype == "file":
        return None
    names_company = bool(company.strip()) and re.search(rf"\b{re.escape(company.strip())}\b", text, re.I)
    if _COMPANY.search(text) or (names_company and re.search(r"\bwhy\b|interest", text, re.I)):
        return "why_company"
    if _ROLE.search(text):
        return "why_role"
    if _ADDITIONAL.search(text):
        return "additional_info"
    if classify.WHY_COMPANY.search(text):
        return "why_company"
    return None


def saved() -> dict[str, str]:
    """Your saved answers, by kind (only the ones you've written)."""
    raw = db.get_setting("saved_answers") or {}
    return {k: v for k, v in raw.items() if k in KINDS and isinstance(v, str) and v.strip()}


def save(kind: str, text: str) -> dict[str, str]:
    """Save (or, with empty text, forget) your answer for one kind of question. Kept exactly as you wrote it."""
    if kind not in KINDS:
        raise ValueError(f"Unknown kind of question: {kind}")
    all_ = dict(db.get_setting("saved_answers") or {})
    if text.strip():
        all_[kind] = text
    else:
        all_.pop(kind, None)
    db.set_settings({"saved_answers": all_})
    return saved()


def fill_slots(text: str, job: dict) -> str:
    """{company} and {role} filled in; nothing else in your text changes."""
    return text.replace("{company}", (job.get("company") or "").strip()).replace("{role}", (job.get("title") or "").strip())


def answer_for(field: dict, job: dict) -> dict | None:
    """Your saved answer for this question (a draft result), or None when you have none for its kind."""
    kind = kind_of(field.get("label", ""), job.get("company") or "", field.get("qtype") or "textarea")
    if not kind and field.get("qtype") == "file" and "cover" in (field.get("field") or "").lower():
        kind = "cover_letter"
    text = saved().get(kind) if kind else None
    if not text:
        return None
    return {"kind": "saved", "canon": None, "answer": fill_slots(text, job), "confidence": 1.0, "issues": [],
            "fact_ids": [], "rationale": f"{SAVED.capitalize()} for “{KINDS[kind]}”, used as you wrote it",
            "check": SAVED}


def is_essay(field: dict) -> bool:
    """A box that wants sentences: a big text box, a question worded as one, or a cover letter upload."""
    if field.get("qtype") == "file":
        return bool(_COVER.search(f"{field.get('label', '')} {field.get('field', '')}"))
    if field.get("options"):
        return False
    kind = classify.question_kind(field.get("label", ""), field.get("qtype", "text"), field.get("options"))
    return kind == "essay" or (kind == "open" and field.get("qtype") == "textarea")


def left_blank(field: dict) -> dict:
    """An optional essay box with no saved answer: left empty, never held, no AI spent."""
    return {"kind": "left_blank", "canon": None, "answer": "", "confidence": 1.0, "issues": [], "fact_ids": [],
            "rationale": "Optional, and you have no saved answer for it, so it's left blank"}
