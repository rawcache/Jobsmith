"""Research a job, then draft every answer on its form.

Order of preference for each field:
  1. answer bank (your own standard answers; legally sensitive ones are never generated)
  2. a past answer you approved for essentially the same question (learning loop)
  3. one batched AI call for everything else, which must cite fact ids; a validator checks it
"""
from __future__ import annotations

import json
import re

from .skills import voice
from . import classify, db, jobdetail, learn, profile, traps
from . import llm
from .llm import LLMError, complete_json

# --------------------------------------------------------------------------- research
RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-3 sentences: what the company does and where this role sits"},
        "what_the_team_builds": {"type": "string"},
        "tech_stack": {"type": "array", "items": {"type": "string"}},
        "recent_news": {"type": "array", "items": {"type": "object", "properties": {
            "headline": {"type": "string"}, "url": {"type": "string"}, "date": {"type": "string"}}}},
        "people": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "role": {"type": "string"},
            "why_relevant": {"type": "string"}, "source_url": {"type": "string"}}}},
        "values_and_culture": {"type": "string"},
        "fit_angles": {"type": "array", "description": "specific overlaps between the applicant's facts and this "
                       "company/team", "items": {"type": "object", "properties": {
                           "angle": {"type": "string"}, "fact_ids": {"type": "array", "items": {"type": "string"}},
                           "source_url": {"type": "string"}}}},
        "talking_points": {"type": "array", "items": {"type": "string"}},
        "red_flags": {"type": "array", "items": {"type": "string"}},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "talking_points", "fit_angles"],
}

RESEARCH_SYSTEM = (
    "You research a company and role for a job applicant, using web search. Rules:\n"
    "- Only report what you can source; list every URL you relied on in sources.\n"
    "- Prefer the company's own engineering blog, product pages and recent (last 12 months) news.\n"
    "- people: only publicly identified recruiters, hiring managers or team leads relevant to this role "
    "(name, role, source URL). Never guess contact details.\n"
    "- fit_angles: concrete overlaps between the APPLICANT FACTS and what this company/team actually works on, "
    "citing the fact ids. These feed the application answers, so be specific and honest; skip weak overlaps.\n"
    "- talking_points: specific, verifiable things an applicant could genuinely reference.\n"
    "Return JSON only."
)

RESEARCH_REUSE_DAYS = 14


async def research_job(job_id: str) -> dict:
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    # Same company researched recently? Reuse it instead of spending another search.
    recent = db.q("""SELECT id, title, research, updated_at FROM jobs WHERE company=? AND id!=? AND research != '{}'
                     AND updated_at > ? ORDER BY updated_at DESC LIMIT 1""",
                  (job["company"], job_id, db.now() - RESEARCH_REUSE_DAYS * 86400))
    if recent:
        data = dict(json.loads(recent[0]["research"]), _reused_from=recent[0]["title"])
        db.x("UPDATE jobs SET research=?, updated_at=? WHERE id=?", (db.enc(data), db.now(), job_id))
        return data
    # A posting with a line aimed at AI isn't handed to a web-searching AI to read for itself.
    url = "" if traps.found(job) else f"Posting URL: {job['url']}\n"
    prompt = (f"Company: {job['company']}\nRole: {job['title']}\nLocations: {', '.join(job['locations'])}\n"
              f"{url}\nJob description (truncated):\n{traps.redact(job['description'][:5000])}\n\n"
              f"APPLICANT FACTS (cite ids in fit_angles):\n{profile.facts_prompt_block(6000)}")
    with llm.usage_for(job_id, "research"):
        data = await complete_json(RESEARCH_SYSTEM, prompt, schema=RESEARCH_SCHEMA, web=True)
    facts = profile.facts_by_id()
    for a in data.get("fit_angles") or []:
        a["fact_ids"] = [f for f in a.get("fact_ids") or [] if f in facts]
    data["_by"] = llm.label(llm.backend("research"))
    data["_at"] = db.now()
    db.x("UPDATE jobs SET research=?, updated_at=? WHERE id=?", (db.enc(data), db.now(), job_id))
    return data


# --------------------------------------------------------------------------- deterministic fields
def _bank_value(key: str, ans: dict) -> tuple[str, bool]:
    if key == "full_name":
        fn, ln = ans.get("first_name", {}).get("value", ""), ans.get("last_name", {}).get("value", "")
        return (f"{fn} {ln}".strip(), bool(ans.get("first_name", {}).get("confirmed")))
    if key == "preferred_name" and not ans.get(key, {}).get("value"):
        return ans.get("first_name", {}).get("value", ""), bool(ans.get("first_name", {}).get("confirmed"))
    if key == "graduation_date" and not ans.get(key, {}).get("value"):
        key = "graduation_year"
    row = ans.get(key) or {}
    return row.get("value", ""), bool(row.get("confirmed"))


US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def state_from_location(loc: str) -> str:
    """'Atlanta, Georgia' or 'Atlanta, GA' -> 'Georgia'."""
    for part in reversed([p.strip() for p in (loc or "").split(",")]):
        if part.upper() in US_STATES:
            return US_STATES[part.upper()]
        for name in US_STATES.values():
            if part.lower() == name.lower():
                return name
    return ""


def location_full(loc: str) -> str:
    """'Boston, MA' -> 'Boston, Massachusetts, United States': how place lookups (Greenhouse's Location (City))
    name a US city, so the right option can be picked from them. Only for a plain "city, state" (optionally ending
    in the US): '' for anything else, and for "Tbilisi, Georgia", where the state name is also a country."""
    parts = [p.strip() for p in (loc or "").split(",") if p.strip()]
    if len(parts) == 3 and parts[2].lower().replace(".", "") in ("us", "usa", "united states", "united states of america"):
        parts = parts[:2]
    if len(parts) != 2:
        return ""
    city, st = parts
    if st.upper() in US_STATES:
        name = US_STATES[st.upper()]
    else:
        name = next((n for n in US_STATES.values() if n.lower() == st.lower() and n not in ALSO_COUNTRIES), "")
    if not name:
        return ""
    return f"{city}, {name}, United States"


ALSO_COUNTRIES = {"Georgia"}       # spelled out, it may mean the country


def _derived(canon: str, ans: dict, job: dict | None = None) -> tuple[str, bool]:
    job = job or {}
    if canon == "referral_name":
        return (job.get("referral_name") or ""), True
    if canon == "how_heard" and job.get("referral_name"):
        return "Employee Referral", True
    v = lambda k: ((ans.get(k) or {}).get("value") or "").strip()
    c = lambda k: bool((ans.get(k) or {}).get("confirmed"))
    if canon == "state":
        st = v("state_province")
        if st:
            return (US_STATES.get(st.upper(), st), c("state_province"))
        return state_from_location(v("location")), c("location")
    if canon == "us_person":
        cit = v("us_citizen").lower()
        return ("Yes" if cit == "yes" else ""), c("us_citizen")
    if canon == "citizenship_status":
        cit = v("us_citizen").lower()
        if cit == "yes":
            return "U.S. Citizen", c("us_citizen")
        return v("citizenships"), c("citizenships")
    if canon == "full_address":
        parts = [v("address_line1"), v("city"), " ".join(x for x in (v("state_province"), v("postal_code")) if x)]
        return ", ".join(p for p in parts if p), all(c(k) for k in ("address_line1", "city") if v(k))
    if canon == "country" and not v("country"):
        # A US citizen, or someone with a US state in their location, lives in the United States.
        if v("us_citizen").lower() == "yes" or state_from_location(v("location")):
            return "United States", c("us_citizen") or c("location")
    if canon == "city" and not v("city"):
        return v("location").split(",")[0].strip(), c("location")
    if canon == "other_links":
        links = [x for x in (v("devpost"), v("website")) if x]
        return ", ".join(links), all(c(k) for k in ("devpost", "website") if v(k))
    if canon == "current_company" and not v("current_company"):
        cur = [e for e in profile.entries("experience") if str(e.get("end", "")).lower() in ("present", "current", "")]
        if cur:
            return cur[0].get("company", ""), True
        return v("school"), c("school")
    return _bank_value(canon, ans)


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def _month_year(text: str) -> tuple[str, str]:
    iso = re.search(r"(\d{4})-(\d{1,2})", text or "")          # "2025-05"
    if iso and 1 <= int(iso.group(2)) <= 12:
        return MONTHS[int(iso.group(2)) - 1], iso.group(1)
    m = re.search(r"([A-Za-z]{3,})\.?\s*(\d{4})", text or "")
    if not m:
        y = re.search(r"(\d{4})", text or "")
        return "", (y.group(1) if y else "")
    mon = next((x for x in MONTHS if x.lower().startswith(m.group(1).lower()[:3])), "")
    return mon, m.group(2)


EDU_DATE_FIELDS = {"start-month--0": ("enrollment_start", 0), "start-year--0": ("enrollment_start", 1),
                   "end-month--0": ("graduation_date", 0), "end-year--0": ("graduation_date", 1)}


EDU_DATE_LABEL = re.compile(r"^(start|end|graduation|expected graduation|enrollment)\s*(date)?\s*(month|year)$", re.I)


def _edu_date(field: dict) -> tuple[str, int] | None:
    """Greenhouse's education date pickers, by field name or (on other sites, or via the extension) by label."""
    if field["field"] in EDU_DATE_FIELDS:
        return EDU_DATE_FIELDS[field["field"]]
    if re.search(r"employ|experience|work history", field.get("group") or "", re.I):
        return None
    m = EDU_DATE_LABEL.match(field.get("label", "").strip())
    if m:
        return ("enrollment_start" if m.group(1).lower() in ("start", "enrollment") else "graduation_date",
                0 if m.group(3).lower() == "month" else 1)
    return None


def deterministic(field: dict, ans: dict, job: dict | None = None) -> dict | None:
    edu = _edu_date(field)
    if edu:
        key, idx = edu
        row = ans.get(key) or {}
        val = _month_year(row.get("value", ""))[idx]
        issues = [] if val else [f"Add '{row.get('label', key)}' on the Profile page"]
        return {"kind": "answer_bank", "canon": key, "answer": val, "confidence": 1.0 if val else 0,
                "issues": issues if field["required"] else []}
    canon = classify.canon_for(field["label"])
    if field["qtype"] == "file" and "transcript" in (field["label"] + field["field"]).lower():
        has = profile.transcript_file() is not None
        if not field["required"]:
            return {"kind": "file", "canon": "transcript", "answer": "", "confidence": 1.0, "issues": [],
                    "rationale": "Optional transcript: skipped (you asked for transcripts only when required)"}
        return {"kind": "file", "canon": "transcript", "answer": "transcript" if has else "", "confidence": 1.0 if has else 0,
                "issues": [] if has else ["This form requires a transcript; add one on the Profile page"]}
    if field["qtype"] == "file":
        if canon == "resume" or "resume" in field["field"]:
            return {"kind": "file", "canon": "resume", "answer": "primary resume", "confidence": 1.0}
        if canon == "cover_letter" or "cover" in field["field"]:
            return None  # generated below
        return {"kind": "file", "canon": None, "answer": "", "confidence": 0.0,
                "issues": ["Jobsmith doesn't know what file this wants; attach it yourself"]}
    if not canon or canon in ("resume", "cover_letter"):
        return None
    value, confirmed = _derived(canon, ans, job)
    sensitive = canon in profile.SENSITIVE_KEYS
    if canon in profile.EEO_KEYS and value and not confirmed:
        # Demographics are never on a resume, so an unconfirmed one has nothing behind it: never filled (rule 2).
        return {"kind": "answer_bank", "canon": canon, "answer": "", "confidence": 0.0,
                "issues": ["Confirm your demographic answers on the Profile page (or 'Decline to self-identify')"]}
    if canon in ("acknowledge_notices", "ai_tools_consent") and value.lower() != "yes":
        return {"kind": "answer_bank", "canon": canon, "answer": "", "confidence": 1.0,
                "issues": ["Asks you to agree to something; you chose to answer these yourself"] if field["required"] else []}
    if canon == "referral_name" and not value and re.search(r"\bn/?a\b|if not|if no\b|otherwise", field["label"], re.I):
        return {"kind": "answer_bank", "canon": canon, "answer": "N/A", "confidence": 1.0, "issues": []}
    if canon == "referral_name" and not value:
        return {"kind": "answer_bank", "canon": canon, "answer": "", "confidence": 1.0, "issues":
                ["Asks who referred you; add the referrer on this job if you have one"] if field["required"] else []}
    if not value and not sensitive:
        return None  # e.g. "how did you hear about us": let the AI pick from the options
    issues = []
    out = value
    if field["options"] and value:
        out = classify.pick_option(value, field["options"]) or ""
        if not out:
            if not sensitive:
                return None
            issues.append(f"Your answer '{value}' doesn't match any option here; pick one")
    if not value:
        if field["required"]:
            issues.append("Add this to your answers on the Profile page" if canon not in profile.EEO_KEYS
                          else "Set your demographic answers on the Profile page (or 'Decline to self-identify')")
    elif not confirmed:
        issues.append("Read from your resume; confirm it on the Profile page")
    return {"kind": "answer_bank", "canon": canon, "answer": out,
            "confidence": 1.0 if (out and confirmed) else 0.5 if out else 0.0, "issues": issues}


# --------------------------------------------------------------------------- generation
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {"answers": {"type": "array", "items": {"type": "object", "properties": {
        "field": {"type": "string"},
        "answer": {"type": "string"},
        "fact_ids": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
    }, "required": ["field", "answer", "fact_ids", "confidence"]}}},
    "required": ["answers"],
}

DRAFT_SYSTEM = """You fill out job applications for one specific person, in their own voice (first person).

HARD RULES
- Every claim about the applicant must come from the FACTS list. Cite the ids you used in fact_ids.
- Never invent experience, numbers, skills, dates, titles, or awards. Copy numbers exactly as they appear in facts.
- If the facts cannot support a good answer, write the best honest answer you can, set confidence <= 0.4,
  and say what's missing in rationale.
- For select questions, the answer must be exactly one of the listed options. If it depends on a personal
  preference the facts don't cover (e.g. office preference, competing offers), pick the most neutral option
  and set confidence <= 0.3.
- Tie answers to this specific company/role using the job description and research. Be specific, not generic.
- Respect any character/word limits in the question. Default: short answers 2-4 sentences; cover letters
  under 250 words, no greeting placeholders like [Hiring Manager].
- Plain, confident, human writing. No clichés ("I am excited to", "passionate", "leverage", "synergy"),
  no em-dashes, no exclamation marks.
- Follow the USER GUIDANCE; it comes from the applicant's past feedback and overrides style defaults.
Return JSON only."""


def _limit(field: dict) -> tuple[str, int] | None:
    text = f"{field['label']} {field.get('description', '')}".lower()
    m = re.search(r"(\d[\d,]*)\s*(characters|chars|words)", text)
    if m:
        return ("words" if "word" in m.group(2) else "chars", int(m.group(1).replace(",", "")))
    return None


def build_prompt(job: dict, fields: list[dict]) -> str:
    parts = [f"JOB: {job['title']} at {job['company']} ({', '.join(job['locations'])})"]
    if job.get("referral_name"):
        parts.append(f"REFERRAL: The applicant was referred by {job['referral_name']}.")
    parts.append("JOB DESCRIPTION:\n" + traps.redact((job.get("description") or "(not available)")[:6000]))
    if job.get("research"):
        r = traps.redact_obj({k: v for k, v in job["research"].items()
                              if not k.startswith("_") and k not in ("people", "sources")})
        parts.append("COMPANY RESEARCH (use fit_angles and talking_points to make answers specific):\n" +
                     json.dumps(r, ensure_ascii=False)[:4000])
    parts.append("FACTS (cite by id):\n" + profile.facts_prompt_block())
    vals = db.get_setting("values") or []
    if vals:
        parts.append("WHAT THE APPLICANT VALUES IN A ROLE (their own words; use only for 'why this company/role' answers and "
                     "cover letters, and only where this job honestly offers it): " + ", ".join(vals[:3]))
    bank = {k: v["value"] for k, v in profile.answers().items() if v["value"] and k not in profile.EEO_KEYS}
    parts.append("APPLICANT BASICS:\n" + json.dumps(bank, ensure_ascii=False))
    notes = voice.style_notes()
    if notes:
        parts.append("THE APPLICANT'S VOICE (measured from their own writing; match it, and reuse their own sentences "
                     "from applicants_own_writing_on_this where they fit): " + notes)
    rules = learn.guidance_rules()
    if rules:
        parts.append("USER GUIDANCE (from past feedback):\n- " + "\n- ".join(rules))
    edits = learn.edit_examples()
    if edits:
        parts.append("HOW THE USER REWRITES DRAFTS (match the 'after' style):\n" + "\n".join(
            f"Q: {e['label']}\nBEFORE: {e['answer'][:500]}\nAFTER: {e['final_answer'][:500]}" for e in edits))
    qs = []
    for f in fields:
        q = {"field": f["field"], "question": traps.redact(f["label"]), "type": f["qtype"], "required": f["required"]}
        if f.get("description"):
            q["help_text"] = traps.redact(f["description"][:400])
        if f["options"]:
            q["options"] = f["options"]
        lim = _limit(f)
        if lim:
            q["limit"] = f"{lim[1]} {lim[0]}"
        if f["qtype"] in ("textarea", "text") and not f["options"]:
            own = voice.search(f["label"], job, k=2)
            if own:
                q["applicants_own_writing_on_this"] = [o["text"][:900] for o in own]
        ex = learn.similar_examples(f["label"], f["qtype"], k=2)
        if ex:
            q["approved_answers_to_similar_questions"] = [
                {"company": e["company"], "question": e["label"], "answer": e["final"][:700]} for e in ex]
        qs.append(q)
    parts.append("QUESTIONS TO ANSWER:\n" + json.dumps(qs, ensure_ascii=False, indent=1))
    return "\n\n".join(parts)


_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")


def validate(field: dict, answer: str, fact_ids: list[str], facts: dict[str, dict],
             job_text: str = "") -> tuple[list[str], list[str]]:
    """Return (issues, valid_fact_ids)."""
    issues = []
    valid = [f for f in fact_ids if f in facts]
    bad = [f for f in fact_ids if f not in facts]
    if bad:
        issues.append(f"Cited unknown facts: {', '.join(bad)}")
    if field["qtype"] in ("select", "multiselect"):
        if field["options"] and answer not in field["options"]:
            issues.append("Answer is not one of the options")
        return issues, valid
    if not answer.strip():
        if field["required"]:
            issues.append("Required but empty")
        return issues, valid
    if field["qtype"] == "textarea" or len(answer) > 120:
        if not valid:
            issues.append("No supporting facts cited")
    # every number must appear in the applicant's facts or the job posting
    corpus = " ".join(f["text"] for f in facts.values()) + " " + " ".join(
        v["value"] for v in profile.answers().values()) + " " + job_text     # "66 Degrees" is the company, not a claim
    corpus_nums = {n.replace(",", "").rstrip("%") for n in _NUM.findall(corpus)}
    for n in _NUM.findall(answer):
        core = n.replace(",", "").rstrip("%")
        if core in corpus_nums or len(core) <= 1 or re.fullmatch(r"(19|20)\d\d", core):
            continue
        issues.append(f"Number '{n}' not found in your facts")
    lim = _limit(field)
    if lim:
        size = len(answer.split()) if lim[0] == "words" else len(answer)
        if size > lim[1]:
            issues.append(f"Over limit: {size}/{lim[1]} {lim[0]}")
    if "—" in answer:
        issues.append("Contains an em-dash")
    return issues, valid


async def generate(job: dict, fields: list[dict]) -> dict[str, dict]:
    if not fields:
        return {}
    with llm.usage_for(job.get("id"), "answers"):
        data = await complete_json(DRAFT_SYSTEM, build_prompt(job, fields), schema=DRAFT_SCHEMA)
    facts = profile.facts_by_id()
    out: dict[str, dict] = {}
    by_field = {f["field"]: f for f in fields}
    for a in data.get("answers", []):
        f = by_field.get(a.get("field"))
        if not f:
            continue
        answer = (a.get("answer") or "").strip()
        if f["options"] and answer not in f["options"]:
            answer = classify.pick_option(answer, f["options"]) or answer
        issues, valid = validate(f, answer, a.get("fact_ids") or [], facts,
                                 f"{job.get('company', '')} {job.get('title', '')} {job.get('description', '')}")
        if f["qtype"] in ("textarea", "text") and len(answer) > 80:
            issues += voice.style_issues(answer)
        conf = float(a.get("confidence") or 0)
        if conf < 0.5 and not issues:
            issues.append("Low confidence: " + (a.get("rationale") or "the facts don't clearly cover this"))
        conf = max(0.0, min(1.0, conf - 0.15 * len(issues)))
        out[f["field"]] = {"kind": "generated", "canon": None, "answer": answer, "fact_ids": valid,
                           "model": llm.label(llm.backend("write")),
                           "rationale": a.get("rationale", ""), "confidence": conf, "issues": issues}
    for f in fields:
        out.setdefault(f["field"], {"kind": "generated", "answer": "", "confidence": 0,
                                    "issues": ["Model skipped this question"]})
    return out


# --------------------------------------------------------------------------- per-job pipeline
def default_fields(job: dict) -> list[dict]:
    """For ATSes whose questions we can't read ahead of time, draft the common long-form ones."""
    return [
        {"field": "why_interested", "label": f"Why are you interested in {job['company']} and this role?",
         "qtype": "textarea", "required": False, "options": [], "description": "", "section": "main"},
        {"field": "cover_letter", "label": "Cover letter", "qtype": "textarea", "required": False,
         "options": [], "description": "Under 250 words.", "section": "main"},
    ]


def questions_stale(job: dict) -> bool:
    """Greenhouse questions saved by older Jobsmith versions miss the education dates and use
    made-up ids for the demographic survey."""
    if job.get("ats") != "greenhouse" or not job.get("questions"):
        return False
    fields = {q["field"] for q in job["questions"]}
    return any(f.startswith("demographic_") for f in fields) or ("school--0" in fields and "start-month--0" not in fields)


async def refresh_questions(job_id: str, log=None) -> dict:
    """Re-read a Greenhouse form's questions if they're stale, drop drafts for fields that no
    longer exist, and answer any new fields. Returns the fresh job."""
    log = log or (lambda m: None)
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    if not questions_stale(job):
        return job
    log("Refreshing this form's questions (saved by an older version)…")
    try:
        job = await jobdetail.fetch_job(job_id)
    except Exception as e:
        log(f"Couldn't refresh questions: {e}")
        return job
    fields = [f for f in job["questions"] if f["qtype"] != "hidden"]
    keep = {f["field"] for f in fields}
    have = {d["field"] for d in db.q("SELECT field FROM drafts WHERE job_id=?", (job_id,))}
    for f in have - keep:
        db.x("DELETE FROM drafts WHERE job_id=? AND field=?", (job_id, f))
    new = [f for f in fields if f["field"] not in have]
    if new:
        results, err = await answer_fields(job, new)
        save_results(job_id, new, results, error=err)
        log(f"Answered {len(results)} new fields")
    return job


async def draft_job(job_id: str, research: bool | None = None, log=None) -> dict:
    log = log or (lambda m: None)
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    if not job["questions"] and not job["description"]:
        job = await jobdetail.fetch_job(job_id)
    elif questions_stale(job):
        job = await refresh_questions(job_id, log)
    settings = db.get_settings()
    if research is None:
        research = settings.get("research_enabled", True)
    if research and not job.get("research"):
        import time as _t
        t0 = _t.time()
        log(f"Researching {job['company']} on the web (usually 20-60s)…")
        try:
            job["research"] = await research_job(job_id)
            log(f"Research done in {int(_t.time() - t0)}s" +
                (f" (reused from {job['research'].get('_reused_from')})" if job["research"].get("_reused_from") else ""))
        except LLMError as e:
            job["research"] = {}
            log(f"Research skipped: {e}")
    log("Writing answers…")

    fields = [f for f in (job["questions"] or default_fields(job)) if f["qtype"] != "hidden"]
    results, gen_error = await answer_fields(job, fields)
    save_results(job_id, fields, results, status="drafted", error=gen_error)
    return {"job_id": job_id, "drafted": len(results), "error": gen_error}


# --------------------------------------------------------------------------- does the answer fit the question
_SENTENCE = re.compile(r"[.!?](\s|$)")


def answer_fits(field: dict, answer: str) -> str | None:
    """Why this answer can't go in this field, or None. Matching by words alone once put a 'why us' paragraph
    in "From where do you intend to work?"; this checks the shape instead: a place, a yes or no, a short line,
    or an essay."""
    return shape_fits(classify.question_kind(field.get("label", ""), field.get("qtype", "text"), field.get("options")),
                      answer)


def shape_fits(kind: str, answer: str) -> str | None:
    """The shape rules for each kind of question. The extension's fits() in content.js applies the same ones to
    the kind the engine sends; tests/test_extension.py checks they agree."""
    a = " ".join((answer or "").split())
    if not a:
        return None
    words, sentences = len(a.split()), len(_SENTENCE.findall(a))
    if kind == "location" and (words > 8 or sentences > 1 or re.match(r"(i|i'm|my|we)\b", a, re.I) or
                               not re.search(r"[^\W\d_]", a)):                 # a phone number isn't a place
        return "asks where, but the answer isn't a place"
    if kind == "yes_no" and not re.match(r"(yes|no|n/?a)\b", a, re.I) and (words > 25 or sentences > 2):
        return "asks yes or no, but the answer is a paragraph"
    if kind == "short" and (words > 40 or sentences > 2):
        return "a short field, but the answer is a paragraph"
    if kind == "essay" and words < 3 and not re.match(r"n/?a$", a, re.I):
        return "asks for a written answer, but the answer is a word or two"
    return None


def _why_company(field: dict, job: dict) -> bool:
    company = (job.get("company") or "").strip()
    return bool(classify.WHY_COMPANY.search(field.get("label", "")) or
                (company and re.search(rf"\b{re.escape(company)}\b", field.get("label", ""), re.I)))


def _flag(r: dict, note: str, issue: str) -> dict:
    """Filled, but for you to read first: shown under 'Check these', and an issue, so autopilot won't send it."""
    return dict(r, check=note, confidence=min(r.get("confidence", 0), 0.5), issues=[issue] + list(r.get("issues") or []))


def _checked(field: dict, r: dict, job: dict) -> dict:
    """Hold an answer that doesn't fit its question; flag a stored 'why us' essay that never names this company,
    and a home location offered for where you'd work."""
    why = answer_fits(field, r.get("answer", ""))
    if why:
        return dict(r, answer="", confidence=0, held=why, fact_ids=[],
                    issues=[f"Held for you: {why}."] + list(r.get("issues") or []))
    answer, company = (r.get("answer") or "").strip(), (job.get("company") or "").strip()
    if (r.get("kind") in ("voice", "learned") and company and answer and _why_company(field, job)
            and not re.search(rf"\b{re.escape(company)}\b", answer, re.I)):
        return _flag(r, f"generic, doesn't mention {company}: check this",
                     f"Generic: doesn't mention {company}. Check this.")
    if r.get("canon") == "location" and answer and classify.WORK_INTENT.search(field.get("label", "")):
        return _flag(r, "your profile location: check it's where you'd work",
                     "This is where you live, from your profile. Check it's where you'd work.")
    return r


async def answer_fields(job: dict, fields: list[dict], skip_locked: bool = True) -> tuple[dict[str, dict], str | None]:
    """Answer form fields: your profile first, then your past approvals, then one AI call for the rest."""
    existing = {d["field"]: d for d in db.q("SELECT * FROM drafts WHERE job_id=?", (job["id"],))}
    ans = profile.answers()
    results: dict[str, dict] = {}
    to_generate: list[dict] = []
    for f in fields:
        f.setdefault("options", [])
        f.setdefault("required", False)
        prev = existing.get(f["field"])
        if skip_locked and prev and is_locked(prev):
            continue  # locked by the user
        det = deterministic(f, ans, job)
        if det:
            results[f["field"]] = det
            continue
        if f["qtype"] != "file":
            reuse = learn.reusable_answer(f["label"], f["qtype"], f["options"])
            if reuse:
                results[f["field"]] = {
                    "kind": "learned", "answer": reuse["answer"],
                    "confidence": min(1.0, 0.6 + 0.1 * reuse["support"]),
                    "rationale": f"Reused your approved answer ({reuse['from']})", "issues": []}
                continue
        if f["qtype"] == "file":  # cover letter upload -> generate text, attached as a file when filling
            if "cover" in (f["label"] + f["field"]).lower():
                to_generate.append(dict(f, qtype="textarea", description="Cover letter, under 250 words."))
        else:
            to_generate.append(dict(f, qtype="select" if f["qtype"] == "listbox" else f["qtype"]))
    gen_error = None
    try:
        results.update(await generate(job, to_generate))
    except LLMError as e:
        gen_error = str(e)
        for f in to_generate:
            results[f["field"]] = {"kind": "generated", "answer": "", "confidence": 0,
                                   "issues": ["Needs your AI connected (Settings), or more of your writing (Voice), then Redraft"]}
    # No AI, the free limit ran out, or the AI came back empty: answer from your own writing instead.
    for f in to_generate:
        r = results.get(f["field"]) or {}
        if f["qtype"] in ("textarea", "text") and not f["options"] and not (r.get("answer") or "").strip():
            mine = voice.compose(job, f)
            if mine:
                results[f["field"]] = mine
    by_field = {f["field"]: f for f in fields}
    return {k: _checked(by_field[k], r, job) if k in by_field else r for k, r in results.items()}, gen_error


def save_results(job_id: str, fields: list[dict], results: dict[str, dict], status: str | None = None,
                 error: str | None = None) -> None:
    by_field = {f["field"]: f for f in fields}
    with db.tx() as c:
        for field_name, r in results.items():
            f = by_field[field_name]
            c.execute("""INSERT INTO drafts(job_id, field, label, qtype, required, options, kind, canon, answer,
                         fact_ids, rationale, confidence, issues, verdict, note, final_answer, updated_at, model)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,?,?)
                         ON CONFLICT(job_id, field) DO UPDATE SET label=excluded.label, qtype=excluded.qtype,
                         required=excluded.required, options=excluded.options, kind=excluded.kind,
                         canon=excluded.canon, answer=excluded.answer, fact_ids=excluded.fact_ids,
                         rationale=excluded.rationale, confidence=excluded.confidence, issues=excluded.issues,
                         verdict=NULL, note=NULL, updated_at=excluded.updated_at, model=excluded.model""",
                      (job_id, field_name, f["label"], f["qtype"], int(bool(f.get("required"))),
                       db.enc(f.get("options") or []), r["kind"], r.get("canon"), r.get("answer", ""),
                       db.enc(r.get("fact_ids", [])), r.get("rationale", ""), r.get("confidence", 0),
                       db.enc(r.get("issues", [])), db.now(), r.get("model")))
        if status:
            c.execute("UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?", (status, error, db.now(), job_id))


def is_locked(d: dict) -> bool:
    """An answer you approved or rewrote is kept on redraft, unless it's empty (nothing to keep)."""
    if d.get("final_answer"):
        return True
    return d.get("verdict") == "green" and bool((d.get("answer") or "").strip() or d.get("qtype") == "file")


def drafts_for(job_id: str) -> list[dict]:
    order = {f["field"]: i for i, f in enumerate(
        db.decode(db.q1("SELECT questions FROM jobs WHERE id=?", (job_id,)))["questions"] or [])}
    rows = [db.decode(r) for r in db.q("SELECT * FROM drafts WHERE job_id=?", (job_id,))]
    rows.sort(key=lambda r: order.get(r["field"], 999))
    return rows


def final_value(d: dict) -> str:
    return d["final_answer"] if d.get("final_answer") else d["answer"]


def readiness(job_id: str) -> dict:
    """Can this job be auto-submitted? Every field must be trusted and issue-free."""
    threshold = int(db.get_setting("trust_threshold") or 3)
    autopilot = db.get_setting("autonomy") in ("autopilot", "autonomous")
    min_conf = float(db.get_setting("autopilot_min_confidence") or 0.7)
    blockers = []
    for d in drafts_for(job_id):
        val = final_value(d)
        if d["verdict"] == "red":
            blockers.append(f"{d['label']}: you red-flagged this")
            continue
        if d["required"] and not val and d["qtype"] != "file":
            blockers.append(f"{d['label']}: required and empty")
            continue
        if d["verdict"] == "green" or d.get("final_answer"):
            continue
        if not d["required"] and not val and d["kind"] == "answer_bank":
            continue  # optional (e.g. EEO) left blank on purpose
        if d["issues"]:
            blockers.append(f"{d['label']}: {d['issues'][0]}")
        elif d["kind"] in ("generated", "voice", "agent") and ((d["confidence"] or 0) < min_conf or not val.strip()) and \
                learn.trust_for(d["label"]) < threshold:
            who = "Your-writing match" if d["kind"] == "voice" else "AI"
            blockers.append(f"{d['label']}: {who} wasn't sure ({round((d['confidence'] or 0) * 100)}% confident)")
        elif d["kind"] == "learned" and d["confidence"] < (0.6 if autopilot else 0.8):
            blockers.append(f"{d['label']}: reused answer has little support yet")
    return {"ready": not blockers, "blockers": blockers}
