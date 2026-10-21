"""Outreach drafts: short messages to people you know at a company, asking for a referral or a word with the
recruiter. Jobsmith only drafts. You copy the message and send it yourself, from your own account."""
from __future__ import annotations

import json

from ... import db, llm, network, profile

KINDS = {"referral": "Ask for a referral", "recruiter": "Note to a recruiter", "thanks": "Thank-you after an interview"}


def _ensure() -> None:
    db.x("""CREATE TABLE IF NOT EXISTS outreach (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, person TEXT NOT NULL,
            kind TEXT NOT NULL, text TEXT NOT NULL, sent_at REAL, created_at REAL NOT NULL)""")


def overview(limit: int = 40) -> list[dict]:
    """Companies you're applying to where you know someone, best matches and live applications first."""
    _ensure()
    rows = db.q("""SELECT id, company, title, status, fit_score FROM jobs WHERE active=1 AND status != 'skipped'
                   ORDER BY (status IN ('submitted','filled','drafted','filling')) DESC, COALESCE(fit_score,0) DESC LIMIT 400""")
    seen: dict[str, dict] = {}
    for r in rows:
        key = network.norm_company(r["company"])
        if not key or key in seen:
            continue
        people = network.at_company(r["company"], 6)
        if not people:
            continue
        drafts = db.q("SELECT id, person, kind, text, sent_at, created_at FROM outreach WHERE job_id IN "
                      "(SELECT id FROM jobs WHERE company=?) ORDER BY created_at DESC", (r["company"],))
        seen[key] = {"company": r["company"], "job_id": r["id"], "title": r["title"], "status": r["status"],
                     "people": people, "drafts": drafts}
        if len(seen) >= limit:
            break
    return list(seen.values())


def _template(kind: str, first: str, me: dict, job: dict) -> str:
    who = me.get("first_name") or "I"
    school = me.get("school") or ""
    role = f"the {job['title']} role at {job['company']}"
    if kind == "recruiter":
        return (f"Hi {first}, I just applied for {role} and wanted to introduce myself. "
                f"I'm {who}{f', studying at {school}' if school else ''}, and the work your team does lines up closely with what I've built. "
                "Would you be open to a quick chat, or is there anything I could share that would help?")
    if kind == "thanks":
        return (f"Hi {first}, thank you for taking the time to talk with me about {role}. "
                "I enjoyed hearing about the team's work and I'm even more excited about the role. Please let me know if I can send anything else.")
    return (f"Hi {first}, I hope you're doing well! I'm applying for {role} and saw you're at {job['company']}. "
            "Would you be comfortable referring me, or sharing what the team is like? Happy to send my resume and a short note you can forward.")


async def draft(job_id: str, person: dict, kind: str = "referral") -> dict:
    """A message under ~120 words, from your real background. Falls back to a plain template with no AI."""
    _ensure()
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    if not job:
        raise KeyError(job_id)
    me = {k: v["value"] for k, v in profile.answers().items() if v.get("value")}
    first = (person.get("first_name") or person.get("name", "").split(" ")[0] or "there").strip()
    name = " ".join(x for x in (person.get("first_name"), person.get("last_name")) if x) or person.get("name", "")
    text = ""
    ok, _ = await llm.available_cached(role="write")
    if ok:
        system = ("You draft short networking messages for a student or new grad, in their voice. Only mention experience that is in "
                  "the FACTS. Under 120 words, plain and warm, no clichés, no em-dashes, no subject line. Return JSON {\"text\": ...}.")
        prompt = (f"KIND: {KINDS.get(kind, kind)}\nTO: {name}, {person.get('position', '')} at {job['company']}\n"
                  f"ROLE: {job['title']} ({', '.join(job.get('locations') or [])})\n"
                  f"JOB DESCRIPTION:\n{(job.get('description') or '')[:2500]}\n\nFACTS:\n{profile.facts_prompt_block(4000)}\n"
                  f"APPLICANT: {json.dumps({k: me.get(k) for k in ('first_name', 'last_name', 'school', 'major', 'graduation_date')})}")
        try:
            text = ((await llm.complete_json(system, prompt)) or {}).get("text", "").strip()
        except llm.LLMError:
            text = ""
    if not text:
        text = _template(kind, first, me, job)
    db.x("INSERT INTO outreach(job_id, person, kind, text, created_at) VALUES(?,?,?,?,?)",
         (job_id, name, kind, text, db.now()))
    rid = db.q1("SELECT MAX(id) id FROM outreach WHERE job_id=? AND person=?", (job_id, name))["id"]
    return {"id": rid, "text": text, "person": name, "kind": kind, "ai": bool(ok and text)}


def mark_sent(draft_id: int, sent: bool = True) -> None:
    _ensure()
    db.x("UPDATE outreach SET sent_at=? WHERE id=?", (db.now() if sent else None, draft_id))
