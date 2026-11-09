"""Needs you, by fix: each thing held applications wait on, listed once with how many it unblocks.

A held application can wait on several things. The ones that are the same for every application are asked once:
your resume as a PDF (every application attaches it), a fact from your profile ("Authorized to work in the US?"),
your saved answer to a common essay question, or one question several forms ask in the same words. Whatever is
this application's own (a site's error, an answer to check) stays with it, listed after the fixes.

Answering a fix re-checks every held application at once (`recheck`), without AI: answers come only from your
profile, your saved answers and what you just typed. The ones with nothing left go out, within your limits.
Work authorization, sponsorship and demographic answers are only ever what you entered (rule 2)."""
from __future__ import annotations

import hashlib
import re

from . import classify, db, draft, essays, profile

LABELS = {k: label for k, label, _ in profile.ANSWER_BANK}
YES_NO = {"work_authorized_us", "needs_sponsorship", "us_citizen", "willing_to_relocate", "relatives_at_company",
          "over_18", "acknowledge_notices", "ai_tools_consent", "background_check_ok", "non_compete",
          "hispanic_latino", "first_gen", "resume_lists_all_employers"}
DECLINE = "Decline to self-identify"
# A profile item says so in its issue: "Add this to your answers on the Profile page", "Read from your resume;
# confirm it on the Profile page", "your profile doesn't give this answer now"
PROFILE_FIX = re.compile(r"on (the|your) Profile page|your profile doesn't give this answer now", re.I)
# "Have you worked for <company>?" that your confirming "My resume lists every employer…" would answer
ALL_EMPLOYERS = re.compile(r"your resume lists every employer", re.I)
# What AI would have written, or nobody did: answerable once for every form that asks it the same way
UNANSWERED = re.compile(r"required and empty|Needs your AI connected|Your AI couldn.t write this|Model skipped this question|needs your answer", re.I)
STOPPED = re.compile(r"^Stopped by you", re.I)
HELD = ("filled", "error")


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (s or "").lower()).split())


def question_id(label: str, options: list[str]) -> str:
    return "question:" + hashlib.sha1(f"{_norm(label)}|{'|'.join(options or [])}".encode()).hexdigest()[:12]


_twin = draft.twin_key


def _one_per_question(items: list[dict]) -> list[dict]:
    """Each question once: of twins, the one with the choices."""
    best: dict[str, dict] = {}
    for it in items:
        k = _twin(it.get("field") or it.get("label") or "")
        if k not in best or len(it.get("options") or []) > len(best[k].get("options") or []):
            best[k] = it
    return list(best.values())


def _fix_for(item: dict, job: dict, answers: dict) -> dict | None:
    """The shared fix one blocker waits on, or None when it's this application's own."""
    canon, issue, label = item.get("canon"), item.get("issue") or "", item.get("label") or ""
    if canon == "previously_employed" and ALL_EMPLOYERS.search(issue):
        canon = "resume_lists_all_employers"
    if canon in LABELS and PROFILE_FIX.search(issue):
        have = (answers.get(canon) or {}).get("value") or ""
        choices = ["Yes", "No"] if canon in YES_NO else []
        if canon in profile.EEO_KEYS:
            choices = list(dict.fromkeys([*(item.get("options") or []), DECLINE]))
        return {"id": f"profile:{canon}", "kind": "profile", "key": canon,
                "title": f"{'Confirm' if have else 'Add'}: {LABELS[canon]}", "choices": choices, "value": have,
                "detail": "Saved to your profile and used on every form that asks."}
    asks = dict(item, qtype=item.get("qtype") or "textarea")
    kind = essays.kind_of(label, job.get("company") or "", asks["qtype"]) if essays.is_essay(asks) else None
    if kind:
        return {"id": f"essay:{kind}", "kind": "essay", "key": kind,
                "title": f"Save your answer to “{essays.KINDS[kind]}”", "value": essays.saved().get(kind, ""),
                "detail": "Used as you write it on every form that asks. {company} and {role} are filled in for you."}
    if UNANSWERED.search(issue) and item.get("qtype") != "file":
        opts = item.get("options") or []
        return {"id": question_id(label, opts), "kind": "question", "key": label, "title": f"Answer “{label}”",
                "choices": opts, "value": "", "detail": "Your answer goes on every held form that asks this."}
    return None


def compute() -> dict:
    """Every fix, most-blocking first (the resume PDF always first), and the applications with something of their
    own to look at. Read-only: nothing is changed or sent."""
    jobs = [db.decode(r) for r in db.q("""SELECT id, company, title, status, hold_reason, error, ats FROM jobs
                                         WHERE status IN ('filled','error') ORDER BY updated_at DESC""")]
    answers = profile.answers()
    no_pdf = profile.attachment_file() is None
    fixes: dict[str, dict] = {}
    rows = []
    for j in jobs:
        need: set[str] = set()
        own: list[str] = []
        if j["status"] == "error":
            own.append(j.get("hold_reason") or j.get("error") or "Something went wrong on the site")
        elif STOPPED.match(j.get("hold_reason") or ""):
            own.append(j["hold_reason"])
        else:
            r = draft.readiness(j["id"])
            for it in _one_per_question(r["items"]):
                if it.get("pending"):
                    continue                                      # written by AI once the rest is answered
                fx = _fix_for(it, j, answers)
                if fx:
                    fixes.setdefault(fx["id"], dict(fx, jobs=[]))
                    need.add(fx["id"])
                else:
                    own.append(it["text"])
            if not r["items"] and j.get("hold_reason"):
                own.append(j["hold_reason"])                       # held on the form itself (a login, a page it can't fill)
        if no_pdf:
            need.add("resume_pdf")
        for k in need - {"resume_pdf"}:
            fixes[k]["jobs"].append(j["id"])
        rows.append({"job": j, "need": need, "own": own})
    if no_pdf:
        waiting = db.q1("""SELECT COUNT(*) n FROM jobs WHERE active=1 AND status IN ('drafted','fetched')
                           AND verdict IS NULL""")["n"]
        fixes["resume_pdf"] = {"id": "resume_pdf", "kind": "resume_pdf", "key": "resume",
                               "title": "Add your resume as a PDF", "value": "",
                               "detail": "It's attached to every application, so every one waits for it."
                                         + (f" {waiting} more are drafted and waiting to start." if waiting else ""),
                               "jobs": [r["job"]["id"] for r in rows]}
    for f in fixes.values():
        f["unblocks"] = len(f["jobs"])
        # how many need nothing else: they go out once this is answered (and, for the others, your resume PDF,
        # which is listed first whenever it's missing)
        f["ready_after"] = sum(1 for r in rows if not r["own"] and (
            r["need"] == {f["id"]} if f["id"] == "resume_pdf" else r["need"] - {"resume_pdf"} == {f["id"]}))
    order = sorted(fixes.values(), key=lambda f: (f["id"] != "resume_pdf", -f["unblocks"], f["title"]))
    apps = [{"id": r["job"]["id"], "company": r["job"]["company"], "title": r["job"]["title"],
             "status": r["job"]["status"], "own": r["own"], "fixes": sorted(r["need"])} for r in rows if r["own"]]
    return {"held": len(jobs), "fixes": order, "applications": apps}


def answer(fix_id: str, value: str) -> dict:
    """Answer one fix with your own words, then re-check every held application. Returns what the re-check did."""
    value = value if fix_id.startswith("essay:") else (value or "").strip()
    held = _held_on_answers()           # taken before your answer goes in: the ones it may free
    if fix_id.startswith("profile:"):
        key = fix_id.split(":", 1)[1]
        if key not in LABELS or not value:
            raise ValueError("Pick or type an answer first.")
        profile.set_answer(key, value, confirmed=True)
    elif fix_id.startswith("essay:"):
        essays.save(fix_id.split(":", 1)[1], value)
    elif fix_id.startswith("question:"):
        if not value:
            raise ValueError("Type an answer first.")
        _answer_question(fix_id, value)
    elif fix_id == "resume_pdf":
        if profile.attachment_file() is None:
            raise ValueError("Upload your resume as a PDF first.")
        return recheck(held, more=True)
    else:
        raise ValueError(f"Unknown fix: {fix_id}")
    return recheck(held)


def _answer_question(fix_id: str, value: str) -> int:
    """Your answer, on every held form that asks this question in the same words (with the same choices)."""
    n = 0
    rows = [db.decode(d) for d in db.q("""SELECT d.* FROM drafts d JOIN jobs j ON j.id=d.job_id
                                         WHERE j.status IN ('filled','error') AND d.final_answer IS NULL
                                         AND COALESCE(d.verdict, '') != 'green'""")]
    twins: dict[tuple[str, str], list[dict]] = {}
    for d in rows:
        twins.setdefault((d["job_id"], _twin(d["field"])), []).append(d)
    for d in rows:
        if question_id(d["label"], d["options"] or []) != fix_id:
            continue
        ans = classify.pick_option(value, d["options"]) if d["options"] and value not in d["options"] else value
        if not ans:
            continue          # none of this form's choices is your answer: it stays for you on that form
        for t in twins[(d["job_id"], _twin(d["field"]))]:          # its twin box, if any, gets the same choice
            if t is d or not t["options"]:
                db.x("UPDATE drafts SET final_answer=?, verdict='green', updated_at=? WHERE id=?", (ans, db.now(), t["id"]))
        n += 1
    return n


def _held_on_answers() -> list[str]:
    """Held applications whose answers are what holds them (not the form, you, or a first-send approval)."""
    from . import guardrails
    waiting_approval = {a["job_id"] for a in guardrails.awaiting_approval()}
    out = []
    for row in db.q("SELECT id, hold_reason FROM jobs WHERE status='filled'"):
        jid = row["id"]
        if jid in waiting_approval or STOPPED.match(row["hold_reason"] or "") or not db.q1(
                "SELECT 1 FROM drafts WHERE job_id=? LIMIT 1", (jid,)):
            continue
        if not draft.readiness(jid)["ready"]:
            out.append(jid)             # ready already: held on the form itself, left for you
    return out


def recheck(held: list[str] | None = None, start: bool = True, more: bool = False) -> dict:
    """Look at every held application again, without AI. One whose answers were the only thing holding it, and
    that has nothing left now, goes back to autopilot: it's sent within your daily and per-company limits (or, when
    you approve each one yourself, waits as ready). Ones held on the form itself, stopped by you, or waiting for
    you to approve autopilot's first send on a site are left as they are. more (your resume PDF just arrived, which
    every application waited on): autopilot's next picks start now too, within the same limits."""
    from . import guardrails
    freed: list[str] = []
    for jid in (_held_on_answers() if held is None else held):
        draft.refresh_offline(jid)
        after = draft.readiness(jid)
        if after["ready"] or after["only_ai"]:
            freed.append(jid)
    no_pdf = profile.attachment_file() is None
    for jid in freed:
        db.x("UPDATE jobs SET status='drafted', hold_reason=NULL, error=NULL, updated_at=? WHERE id=?", (db.now(), jid))
    started: list[str] = []
    from . import commands, runner
    from .config import DEMO
    if start and not no_pdf and not DEMO and runner.applies_on_own():
        room = max(0, guardrails.remaining_today())
        started = commands.queue(freed[:room]) if freed else []
        from . import scheduler
        if more and scheduler.enabled(db.get_settings()) and room > len(started):
            picks = [j for j in scheduler.pick_new_jobs(room - len(started)) if j not in started]
            started += commands.queue(picks)
    return {"freed": freed, "started": started,
            "note": "Add your resume as a PDF and they'll go out." if freed and no_pdf else "",
            **compute()}
