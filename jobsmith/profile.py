"""The user's knowledge base: resume -> atomic, citable facts + an answer bank.

A LaTeX resume is parsed deterministically (free, exact). A PDF is converted to text and,
if an AI backend is available, structured by the model; otherwise each line becomes a fact.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from . import db
from . import llm
from .llm import LLMError, complete_json

# --------------------------------------------------------------------------- answer bank
# Canonical keys for questions that should NEVER be guessed by a model.
# value "" means "ask me". confirmed=0 means Jobsmith inferred it and wants you to confirm.
# (key, label, section). Sections drive how the Profile page groups them.
ANSWER_BANK: list[tuple[str, str, str]] = [
    ("first_name", "Legal first name", "Contact"),
    ("last_name", "Legal last name", "Contact"),
    ("preferred_name", "Preferred first name", "Contact"),
    ("email", "Email for applications", "Contact"),
    ("school_email", "School email", "Contact"),
    ("phone", "Phone", "Contact"),
    ("address_line1", "Street address", "Contact"),
    ("city", "City", "Contact"),
    ("state_province", "State", "Contact"),
    ("postal_code", "ZIP code", "Contact"),
    ("country", "Country", "Contact"),
    ("location", "Location to show employers (City, State)", "Contact"),
    ("name_pronunciation", "How to pronounce your name", "Contact"),
    ("linkedin", "LinkedIn", "Links"),
    ("github", "GitHub", "Links"),
    ("website", "Website / portfolio", "Links"),
    ("devpost", "Devpost", "Links"),
    ("school", "School", "Education"),
    ("degree", "Degree", "Education"),
    ("major", "Major", "Education"),
    ("minor", "Minor", "Education"),
    ("concentration", "Concentration / threads", "Education"),
    ("gpa", "GPA", "Education"),
    ("sat_score", "SAT score (if forms ask)", "Education"),
    ("act_score", "ACT score (if forms ask)", "Education"),
    ("class_standing", "Class standing (e.g. Senior)", "Education"),
    ("enrollment_start", "Started at this school (e.g. Aug 2023)", "Education"),
    ("graduation_date", "Graduation (e.g. May 2027)", "Education"),
    ("graduation_year", "Graduation year", "Education"),
    ("work_authorized_us", "Authorized to work in the US?", "Work authorization"),
    ("needs_sponsorship", "Need visa sponsorship now or later?", "Work authorization"),
    ("us_citizen", "US citizen?", "Work authorization"),
    ("security_clearance", "Security clearance (e.g. None, Secret, TS/SCI)", "Work authorization"),
    ("citizenships", "Citizenship(s)", "Work authorization"),
    ("work_authorized_other", "Also allowed to work in (other countries)", "Work authorization"),
    ("headline", "Headline (one line about you, like on LinkedIn)", "Credentials"),
    ("years_experience", "Years of work experience", "Credentials"),
    ("certifications", "Certifications (e.g. AWS Solutions Architect, 2025)", "Credentials"),
    ("licenses", "Professional licenses (e.g. EIT, PE)", "Credentials"),
    ("languages", "Languages you speak", "Credentials"),
    ("current_company", "Current employer (or school)", "Logistics"),
    ("willing_to_relocate", "Willing to relocate?", "Logistics"),
    ("earliest_start", "Earliest start date", "Logistics"),
    ("work_mode", "On-site / hybrid / remote preference", "Logistics"),
    ("desired_pay", "Pay expectation (blank = skip when optional)", "Logistics"),
    ("how_heard", "Default answer to 'How did you hear about us?'", "Common questions"),
    ("previously_employed", "Worked at the company before?", "Common questions"),
    ("relatives_at_company", "Relatives working at the company?", "Common questions"),
    ("over_18", "18 or older?", "Common questions"),
    ("acknowledge_notices", "Agree to privacy notices and terms forms ask you to acknowledge?", "Common questions"),
    ("ai_tools_consent", "OK with employers using AI tools (e.g. interview notes)?", "Common questions"),
    ("background_check_ok", "OK with a background check?", "Common questions"),
    ("non_compete", "Bound by a non-compete?", "Common questions"),
    ("gender", "Gender", "Demographics (optional)"),
    ("race", "Race / ethnicity", "Demographics (optional)"),
    ("hispanic_latino", "Hispanic or Latino?", "Demographics (optional)"),
    ("veteran_status", "Veteran status", "Demographics (optional)"),
    ("disability_status", "Disability status", "Demographics (optional)"),
    ("pronouns", "Pronouns", "Demographics (optional)"),
    ("lgbtq", "LGBTQ+ / sexual orientation", "Demographics (optional)"),
    ("first_gen", "First-generation college student?", "Demographics (optional)"),
]
SECTION = {k: sec for k, _, sec in ANSWER_BANK}
EEO_KEYS = {"gender", "race", "hispanic_latino", "veteran_status", "disability_status", "pronouns", "lgbtq",
            "first_gen"}

# Answers that must only ever come from you. Everything else falls back to AI when left blank.
SENSITIVE_KEYS = {k for k, _, sec in ANSWER_BANK if sec in ("Contact", "Links", "Education", "Work authorization", "Credentials",
                                                              "Demographics (optional)")} | {
    "full_name", "desired_pay", "relatives_at_company", "over_18", "background_check_ok", "non_compete", "us_person",
    "citizenship_status", "full_address", "acknowledge_notices", "ai_tools_consent"}
DEFAULTS = {"previously_employed": "No"}


def ensure_answer_bank() -> None:
    for key, label, _ in ANSWER_BANK:
        db.x("INSERT OR IGNORE INTO answers(key, label, value, confirmed, updated_at) VALUES(?,?,?,?,?)",
             (key, label, DEFAULTS.get(key, ""), int(key in DEFAULTS), db.now()))
        db.x("UPDATE answers SET label=? WHERE key=?", (label, key))
    for key, val in DEFAULTS.items():
        db.x("UPDATE answers SET value=?, confirmed=1 WHERE key=? AND value=''", (val, key))


def answers() -> dict[str, dict]:
    ensure_answer_bank()
    order = {k: i for i, (k, _, _) in enumerate(ANSWER_BANK)}
    rows = db.q("SELECT * FROM answers")
    rows.sort(key=lambda r: order.get(r["key"], 999))
    for r in rows:
        r["section"] = SECTION.get(r["key"], "Other")
    return {r["key"]: r for r in rows}


def set_answer(key: str, value: str, confirmed: bool = True, label: str | None = None) -> None:
    ensure_answer_bank()
    existing = db.q1("SELECT * FROM answers WHERE key=?", (key,))
    if existing is None:
        db.x("INSERT INTO answers(key,label,value,confirmed,updated_at) VALUES(?,?,?,?,?)",
             (key, label or key, value, int(confirmed), db.now()))
    else:
        db.x("UPDATE answers SET value=?, confirmed=?, updated_at=? WHERE key=?",
             (value, int(confirmed), db.now(), key))


def infer_answer(key: str, value: str) -> None:
    """Set a value only if the user hasn't already set/confirmed one."""
    if not value:
        return
    row = answers().get(key)
    if row and (row["confirmed"] or row["value"]):
        return
    set_answer(key, value, confirmed=False)


# --------------------------------------------------------------------------- facts
def fact_id(text: str) -> str:
    return "f_" + hashlib.sha1(text.strip().lower().encode()).hexdigest()[:8]


def add_fact(category: str, text: str, subject: str = "", source: str = "user") -> str:
    text = " ".join(text.split())
    fid = fact_id(subject + "|" + text)
    db.x("""INSERT INTO facts(id, category, subject, text, source, active, created_at)
            VALUES(?,?,?,?,?,1,?) ON CONFLICT(id) DO UPDATE SET active=1, category=excluded.category""",
         (fid, category, subject, text, source, db.now()))
    return fid


def facts(active_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM facts" + (" WHERE active=1" if active_only else "") + " ORDER BY created_at, id"
    return db.q(sql)


def facts_by_id() -> dict[str, dict]:
    return {f["id"]: f for f in facts()}


def facts_prompt_block(limit_chars: int = 12000) -> str:
    """Facts formatted for prompts: one per line, with the id the model must cite."""
    lines = []
    for f in facts():
        subj = f" [{f['subject']}]" if f["subject"] else ""
        lines.append(f"{f['id']} ({f['category']}){subj}: {f['text']}")
    out = "\n".join(lines)
    return out[:limit_chars]


# --------------------------------------------------------------------------- LaTeX parsing
def _strip_tex(s: str) -> str:
    s = re.sub(r"(?<!\\)%.*", "", s)                       # comments
    s = re.sub(r"\\(v|h)space\*?\{[^}]*\}", " ", s)
    s = re.sub(r"\\(begin|end)\{(center|flushleft|flushright|minipage)\}", " ", s)
    s = re.sub(r"\\\\(\[[^\]]*\])?", " | ", s)              # LaTeX line breaks -> separator
    s = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", s)    # \href{url}{text} -> text
    s = s.replace("$\\sim$", "~").replace("\\textasciitilde", "~").replace("$\\rightarrow$", "->")
    s = s.replace("$^\\circ$", "°").replace("\\&", "&").replace("\\%", "%").replace("\\$", "$")
    s = s.replace("--", "–").replace("\\;", " ").replace("\\textbar", "|")
    s = re.sub(r"\\(textbf|textit|textnormal|emph|underline|small|large|Large|LARGE)\b", "", s)
    s = re.sub(r"\\fontsize\{[^}]*\}\{[^}]*\}\\selectfont", "", s)
    s = re.sub(r"\\(hfill|selectfont|centering|noindent)\b", " | ", s)
    s = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", "", s)      # remaining commands
    s = s.replace("{", "").replace("}", "").replace("$", "")
    s = re.sub(r"\s*\|\s*(\|\s*)+", " | ", s)
    return " ".join(s.split()).strip(" |")


SECTION_CATEGORY = {
    "education": "education", "experience": "experience", "work": "experience",
    "research": "experience", "project": "project", "hackathon": "project",
    "skill": "skill", "technical": "skill", "award": "award", "certification": "award",
    "leadership": "leadership", "activit": "leadership", "volunteer": "leadership",
}


def _category_for(section: str) -> str:
    s = section.lower()
    for k, v in SECTION_CATEGORY.items():
        if k in s:
            return v
    return "other"


def parse_latex(tex: str) -> dict:
    """Deterministically parse a typical one-column LaTeX resume."""
    body = tex.split("\\begin{document}", 1)[-1].split("\\end{document}", 1)[0]
    # drop commented-out lines entirely
    body = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("%"))
    body = re.sub(r"\\begin\{itemize\}\[[^\n]*", r"\\begin{itemize}", body)  # drop list options
    raw_links = re.findall(r"\\href\{([^}]*)\}\{([^}]*)\}", body)

    header_part, _, rest = body.partition("\\section")
    identity: dict = {}
    name = re.search(r"\\textbf\{([^}]+)\}", header_part)
    if name:
        identity["name"] = _strip_tex(name.group(1))
    head_txt = _strip_tex(header_part)
    if identity.get("name") and head_txt.startswith(identity["name"]):
        head_txt = head_txt[len(identity["name"]):].strip(" |")
    em = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", head_txt)
    if em:
        identity["email"] = em.group(0)
    mailtos = [u.replace("mailto:", "") for u, _ in raw_links if u.startswith("mailto:")]
    if mailtos and identity.get("email") and mailtos[0] != identity["email"]:
        identity["email_conflict"] = [identity["email"], mailtos[0]]
    ph = re.search(r"\(?\d{3}\)?[-.\s]*\d{3}[-.\s]*\d{4}", head_txt)
    if ph:
        identity["phone"] = ph.group(0)
    for url, _ in raw_links:
        u = url.lower()
        if "linkedin.com" in u:
            identity["linkedin"] = url
        elif "github.com" in u and "github" not in identity:
            identity["github"] = url
    parts = [p.strip() for p in head_txt.split("|")]
    for p in parts:
        if re.match(r"^[A-Z][a-zA-Z .]+,\s*[A-Z]{2}$", p):
            identity["location"] = p
        if re.search(r"citizen|permanent resident|visa|authorized", p, re.I):
            identity["work_status"] = p

    sections: list[dict] = []
    for chunk in re.split(r"\\section\*?", "\\section" + rest)[1:]:
        m = re.match(r"\s*\{([^}]*)\}(.*)", chunk, re.S)
        if not m:
            continue
        title, content = _strip_tex(m.group(1)), m.group(2)
        cat = _category_for(title)
        entries: list[dict] = []
        current: dict | None = None
        # Split into "heading" lines and \item bullets, preserving order.
        tokens = re.split(r"(\\item\b)", content)
        pre = tokens[0]
        items = ["".join(tokens[i:i + 2]) for i in range(1, len(tokens), 2)]

        def flush_heading(text: str):
            nonlocal current
            heads = [h for h in (_strip_tex(x) for x in re.split(r"\\begin\{itemize\}|\\end\{itemize\}", text)) if h]
            for h in heads:
                current = {"heading": h, "bullets": []}
                entries.append(current)

        flush_heading(pre)
        for it in items:
            # an item may be followed by the next entry's heading after \end{itemize}
            bullet_txt, *after = re.split(r"\\end\{itemize\}", it, maxsplit=1)
            b = _strip_tex(bullet_txt.replace("\\item", "", 1))
            if b:
                if current is None:
                    current = {"heading": "", "bullets": []}
                    entries.append(current)
                current["bullets"].append(b)
            if after:
                flush_heading(after[0])
        sections.append({"title": title, "category": cat, "entries": entries})
    return {"identity": identity, "sections": sections}


def facts_from_parsed(parsed: dict, source: str) -> list[str]:
    ids = []
    ident = parsed.get("identity", {})
    if ident.get("name"):
        ids.append(add_fact("identity", f"Name: {ident['name']}", source=source))
    if ident.get("work_status"):
        ids.append(add_fact("identity", f"Work status: {ident['work_status']}", source=source))
    if ident.get("location"):
        ids.append(add_fact("identity", f"Based in {ident['location']}", source=source))
    for k in ("linkedin", "github"):
        if ident.get(k):
            ids.append(add_fact("link", f"{k.title()}: {ident[k]}", source=source))
    for sec in parsed["sections"]:
        cat = sec["category"]
        for e in sec["entries"]:
            head = e["heading"]
            if cat in ("skill", "education") and not e["bullets"]:
                # "Programming: C, C++, ..." lines -> one fact per line
                for line in (l.strip() for l in head.split(" | ")):
                    if line:
                        ids.append(add_fact(cat, line, subject="" if cat == "skill" else head.split(" | ")[0],
                                            source=source))
                continue
            if not e["bullets"]:
                ids.append(add_fact(cat, head, source=source))
                continue
            ids.append(add_fact(cat, head, subject=head, source=source))
            for b in e["bullets"]:
                ids.append(add_fact(cat, b, subject=head, source=source))
    return ids


def seed_answers_from_identity(ident: dict, parsed: dict | None = None) -> None:
    name = ident.get("name", "")
    if name:
        bits = name.split()
        infer_answer("first_name", bits[0])
        infer_answer("last_name", " ".join(bits[1:]))
    for k in ("email", "phone", "location", "linkedin", "github"):
        infer_answer(k, ident.get(k, ""))
    ws = (ident.get("work_status") or "").lower()
    if "citizen" in ws and "not" not in ws:
        infer_answer("us_citizen", "Yes")
        infer_answer("work_authorized_us", "Yes")
        infer_answer("needs_sponsorship", "No")
    if parsed:
        for sec in parsed["sections"]:
            if sec["category"] != "education":
                continue
            for e in sec["entries"]:
                h = e["heading"]
                gpa = re.search(r"GPA:?\s*([0-9.]+)", h)
                if gpa:
                    infer_answer("gpa", gpa.group(1))
                school = re.match(r"([A-Z][\w .&'-]+?(University|Institute of Technology|College|Institute)[\w ]*)", h)
                if school:
                    infer_answer("school", school.group(1).strip(" ;,"))
                grad = re.search(r"(Expected\s+)?((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+(20\d\d))", h)
                if grad:
                    infer_answer("graduation_date", grad.group(2))
                    infer_answer("graduation_year", grad.group(4))
                deg = re.search(r"(Bachelor|Master|Doctor|B\.S\.|M\.S\.|Ph\.D)\S*(?: of [A-Z][a-z]+)?(?: in|,)\s+"
                                r"([A-Z][\w&]*(?: (?:&|and|of|[A-Z][\w&]*))*)", h)
                if deg:
                    infer_answer("degree", "Bachelor's" if deg.group(1).startswith(("Bachelor", "B.")) else
                                 "Master's" if deg.group(1).startswith(("Master", "M.")) else "PhD")
                    infer_answer("major", deg.group(2).strip())


# --------------------------------------------------------------------------- PDF / LLM path
def pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    try:
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    except Exception:          # a damaged or unusual PDF: keep the file (it can still be attached), skip reading it
        return ""


PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "identity": {"type": "object", "properties": {
            "name": {"type": "string"}, "email": {"type": "string"}, "phone": {"type": "string"},
            "location": {"type": "string"}, "linkedin": {"type": "string"}, "github": {"type": "string"},
            "work_status": {"type": "string"}}},
        "facts": {"type": "array", "items": {"type": "object", "properties": {
            "category": {"type": "string", "enum": ["identity", "education", "experience", "project",
                                                     "skill", "award", "leadership", "link", "other"]},
            "subject": {"type": "string"}, "text": {"type": "string"}},
            "required": ["category", "text"]}},
    },
    "required": ["identity", "facts"],
}

PROFILE_SYSTEM = (
    "You convert a resume into atomic facts. Copy wording and numbers exactly as written; never add, "
    "infer, or embellish. One fact per bullet point. For each role/project, also emit one fact whose "
    "text is the heading line (organization, title, dates). 'subject' is the role/project heading."
)


async def facts_from_text_llm(text: str, source: str, extra: bool = False) -> tuple[list[str], dict]:
    label = ("Document about the applicant (certificate, award, transcript, profile export, or notes). "
             "Extract only facts about the applicant:" if extra else "Resume text:")
    with llm.usage_for(None, "profile"):
        data = await complete_json(PROFILE_SYSTEM, f"{label}\n\n{text[:30000]}", schema=PROFILE_SCHEMA)
    ids = [add_fact(f.get("category", "other"), f["text"], f.get("subject", ""), source)
           for f in data.get("facts", []) if f.get("text")]
    return ids, data.get("identity", {})


def facts_from_text_plain(text: str, source: str) -> list[str]:
    """No-AI fallback: rejoin lines that PDF extraction wrapped, then one fact per bullet/line."""
    merged: list[str] = []
    for raw in text.splitlines():
        line = raw.strip(" •◦o-\t")
        if not line:
            continue
        if merged and (raw[:1].islower() or line[:1].islower() or not re.search(r"[.!?)%]$|\d{4}$", merged[-1])) \
                and len(merged[-1]) > 60:
            merged[-1] += " " + line
        else:
            merged.append(line)
    return [add_fact("other", m, source=source) for m in merged if len(m) > 25]


# --------------------------------------------------------------------------- documents
# Three kinds of upload, each with one job:
#   resume      the "holy grail" resume (one at a time). .tex is read exactly; .pdf/.docx/.txt via AI.
#   resume_pdf  the file attached to applications (one at a time). Defaults to the resume if it's a PDF.
#   extra       anything else about you: certifications, awards, transcript, LinkedIn PDF, project write-ups.
SLOTS = ("resume", "resume_pdf", "transcript", "extra")


def looks_like_latex(text: str) -> bool:
    return "\\documentclass" in text or "\\begin{document}" in text


def read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return pdf_text(path)
    if suffix == ".docx":
        import zipfile
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode(errors="replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    return path.read_text(errors="replace")


def migrate_documents() -> None:
    """Older versions stored every upload as kind='resume'. Sort them into slots (idempotent)."""
    db.x("UPDATE documents SET kind='extra' WHERE kind IN ('linkedin','other')")
    resumes = db.q("SELECT * FROM documents WHERE kind='resume' ORDER BY created_at DESC")
    if len(resumes) <= 1:
        return
    latex = [r for r in resumes if looks_like_latex(r["text"] or "")]
    keep = latex[0] if latex else resumes[0]
    pdfs = [r for r in resumes if r["path"].lower().endswith(".pdf") and r["id"] != keep["id"]]
    if pdfs and not db.q1("SELECT 1 FROM documents WHERE kind='resume_pdf'"):
        db.x("UPDATE documents SET kind='resume_pdf', is_primary=1 WHERE id=?", (pdfs[0]["id"],))
        pdfs = pdfs[1:]
    for r in resumes:
        if r["id"] != keep["id"] and db.q1("SELECT kind FROM documents WHERE id=?", (r["id"],))["kind"] == "resume":
            db.x("DELETE FROM documents WHERE id=?", (r["id"],))
    db.x("UPDATE documents SET is_primary=1 WHERE id=?", (keep["id"],))


def documents() -> list[dict]:
    return db.q("SELECT id, kind, filename, created_at FROM documents ORDER BY kind, created_at DESC")


def _retire_facts_from(filenames: list[str]) -> None:
    for fn in filenames:
        db.x("UPDATE facts SET active=0 WHERE source=?", (fn,))


def delete_document(doc_id: int) -> None:
    d = db.q1("SELECT * FROM documents WHERE id=?", (doc_id,))
    if not d:
        return
    still_used = db.q1("SELECT 1 FROM documents WHERE filename=? AND id!=?", (d["filename"], doc_id))
    if not still_used:
        _retire_facts_from([d["filename"]])
    db.x("DELETE FROM documents WHERE id=?", (doc_id,))


async def ingest_document(path: Path, slot: str = "resume") -> dict:
    """Store an upload in its slot and turn it into facts. Returns a summary for the UI."""
    path = Path(path)
    if slot not in SLOTS:
        slot = "extra"
    warnings: list[str] = []
    identity: dict = {}
    text = read_text(path)

    if slot in ("resume_pdf", "transcript"):
        old = db.q("SELECT id FROM documents WHERE kind=?", (slot,))
        for o in old:
            db.x("DELETE FROM documents WHERE id=?", (o["id"],))
        db.x("INSERT INTO documents(kind, filename, path, text, is_primary, created_at) VALUES(?,?,?,?,1,?)",
             (slot, path.name, str(path), text, db.now()))
        what = "attached to applications" if slot == "resume_pdf" else "attached only when a form requires a transcript"
        return {"facts_added": 0, "method": "attachment", "warnings": [], "message": f"{path.name} will be {what}."}

    if slot == "resume":
        old = db.q("SELECT id, filename FROM documents WHERE kind='resume'")
        _retire_facts_from([o["filename"] for o in old])
        for o in old:
            db.x("DELETE FROM documents WHERE id=?", (o["id"],))
    else:
        # re-uploading the same extra file replaces it
        old = db.q("SELECT id FROM documents WHERE kind='extra' AND filename=?", (path.name,))
        _retire_facts_from([path.name] if old else [])
        for o in old:
            db.x("DELETE FROM documents WHERE id=?", (o["id"],))

    if looks_like_latex(text):
        parsed = parse_latex(text)
        ids = facts_from_parsed(parsed, path.name)
        identity = parsed["identity"]
        if slot == "resume":
            seed_answers_from_identity(identity, parsed)
        method = "exact (LaTeX)"
    else:
        try:
            ids, identity = await facts_from_text_llm(text, path.name, extra=(slot == "extra"))
            if slot == "resume":
                seed_answers_from_identity(identity)
            method = "AI"
        except LLMError as e:
            ids = facts_from_text_plain(text, path.name)
            warnings.append(f"Claude isn't connected, so {path.name} was imported line by line. "
                            "Connect Claude and upload it again for cleaner facts.")
            method = "line by line"

    if identity.get("email_conflict"):
        a, b = identity["email_conflict"]
        warnings.append(f"Your resume shows the email '{a}' but its link points to '{b}'. "
                        f"Check which one is right in your answers.")
    db.x("INSERT INTO documents(kind, filename, path, text, is_primary, created_at) VALUES(?,?,?,?,?,?)",
         (slot, path.name, str(path), text, int(slot == "resume"), db.now()))
    return {"facts_added": len(set(ids)), "method": method, "warnings": warnings, "identity": identity}


def rebuild_from_primary() -> dict | None:
    """Re-parse the current LaTeX resume (repairs facts imported by an older version)."""
    doc = db.q1("SELECT * FROM documents WHERE kind='resume' ORDER BY created_at DESC")
    if not doc or not looks_like_latex(doc["text"]):
        return None
    db.x("UPDATE facts SET active=0 WHERE source != 'user' AND source NOT IN "
         "(SELECT filename FROM documents WHERE kind='extra')")
    parsed = parse_latex(doc["text"])
    ids = facts_from_parsed(parsed, doc["filename"])
    seed_answers_from_identity(parsed["identity"], parsed)
    return {"facts_added": len(set(ids))}


def primary_resume_pdf() -> Path | None:
    """The file uploaded to application forms."""
    for kind in ("resume_pdf", "resume"):
        for r in db.q("SELECT * FROM documents WHERE kind=? ORDER BY created_at DESC", (kind,)):
            if r["path"].lower().endswith(".pdf") and Path(r["path"]).exists():
                return Path(r["path"])
    return None


def transcript_file() -> Path | None:
    r = db.q1("SELECT path FROM documents WHERE kind='transcript' ORDER BY created_at DESC")
    return Path(r["path"]) if r and Path(r["path"]).exists() else None


def resume_status() -> dict:
    src = db.q1("SELECT id, filename FROM documents WHERE kind='resume' ORDER BY created_at DESC")
    pdf = db.q1("SELECT id, filename FROM documents WHERE kind='resume_pdf' ORDER BY created_at DESC")
    attach = primary_resume_pdf()
    tr = db.q1("SELECT id, filename FROM documents WHERE kind='transcript' ORDER BY created_at DESC")
    return {"resume": src, "resume_pdf": pdf, "transcript": tr, "attached": attach.name if attach else None,
            "attachment_name": (attachment_file().name if attach else None),
            "exact": bool(src and src["filename"] and looks_like_latex(
                (db.q1("SELECT text FROM documents WHERE id=?", (src["id"],)) or {}).get("text", "")))}


# --------------------------------------------------------------------------- profile.json
# data/profile.json is a hand-editable (or Claude-written) profile. Jobsmith loads it on start and
# whenever it changes: answers become confirmed answers, work/education become entries, facts are added.
import json as _json  # noqa: E402

from .config import DATA_DIR  # noqa: E402

PROFILE_JSON = DATA_DIR / "profile.json"


def _ensure_entries_table() -> None:
    db.x("""CREATE TABLE IF NOT EXISTS entries (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
            pos INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL, updated_at REAL NOT NULL)""")


def entries(kind: str | None = None) -> list[dict]:
    _ensure_entries_table()
    rows = db.q("SELECT * FROM entries" + (" WHERE kind=?" if kind else "") + " ORDER BY kind, pos",
                (kind,) if kind else ())
    return [dict(id=r["id"], kind=r["kind"], **_json.loads(r["data"])) for r in rows]


def save_entry(kind: str, data: dict, entry_id: int | None = None) -> None:
    _ensure_entries_table()
    clean = {k: v for k, v in data.items() if k not in ("id", "kind")}
    if entry_id:
        db.x("UPDATE entries SET data=?, updated_at=? WHERE id=?", (_json.dumps(clean), db.now(), entry_id))
    else:
        pos = (db.q1("SELECT COALESCE(MAX(pos),-1)+1 p FROM entries WHERE kind=?", (kind,)) or {"p": 0})["p"]
        db.x("INSERT INTO entries(kind, pos, data, updated_at) VALUES(?,?,?,?)", (kind, pos, _json.dumps(clean), db.now()))


def delete_entry(entry_id: int) -> None:
    _ensure_entries_table()
    db.x("DELETE FROM entries WHERE id=?", (entry_id,))


async def import_profile_json(force: bool = False) -> dict | None:
    if not PROFILE_JSON.exists():
        return None
    mtime = PROFILE_JSON.stat().st_mtime
    if not force and float(db.get_setting("profile_import_mtime") or 0) >= mtime:
        return None
    data = _json.loads(PROFILE_JSON.read_text())
    # Documents named in the file (paths relative to data/) are loaded into their slots if they changed.
    for slot in ("resume", "resume_pdf", "transcript"):
        rel = data.get(slot)
        if not rel:
            continue
        path = (DATA_DIR / rel).resolve()
        if not path.exists():
            continue
        cur = db.q1("SELECT path FROM documents WHERE kind=? ORDER BY created_at DESC", (slot,))
        if not cur or Path(cur["path"]).resolve() != path or force:
            await ingest_document(path, slot)
    n_ans = 0
    for key, value in (data.get("answers") or {}).items():
        if value is None:
            continue
        confirmed = True
        if isinstance(value, dict):      # {"value": "...", "confirmed": false} = needs your OK
            confirmed = bool(value.get("confirmed", True))
            value = value.get("value", "")
        label = next((l for k, l, _ in ANSWER_BANK if k == key), key.replace("_", " ").capitalize())
        set_answer(key, str(value), confirmed, label)
        n_ans += 1
    _ensure_entries_table()
    for kind in ("experience", "education", "project"):
        if kind in data:
            db.x("DELETE FROM entries WHERE kind=?", (kind,))
            for e in data[kind]:
                save_entry(kind, e)
    db.x("UPDATE facts SET active=0 WHERE source='profile.json'")
    n_facts = 0
    for f in data.get("facts") or []:
        add_fact(f.get("category", "other"), f["text"], f.get("subject", ""), "profile.json")
        n_facts += 1
    settings = {k: v for k, v in (data.get("settings") or {}).items()}
    if "rules" in data:
        settings["writing_rules"] = [r for r in data["rules"] if r]
    for u in data.get("sources") or []:
        db.x("INSERT OR IGNORE INTO sources(kind, url, active) VALUES('simplify_github', ?, 1)", (u,))
    if data.get("attachment_name"):
        settings["attachment_name"] = data["attachment_name"]
    settings["profile_import_mtime"] = mtime
    db.set_settings(settings)
    return {"answers": n_ans, "facts": n_facts, "experience": len(data.get("experience") or [])}


def attachment_file() -> Path | None:
    """The resume PDF, copied under the file name employers see (e.g. First_Last_resume.pdf)."""
    src = primary_resume_pdf()
    if not src:
        return None
    name = (db.get_setting("attachment_name") or "").strip()
    if not name:
        a = answers()
        fn, ln = a.get("first_name", {}).get("value", ""), a.get("last_name", {}).get("value", "")
        name = f"{fn}_{ln}_resume.pdf" if fn and ln else src.name
    name = re.sub(r"[^\w.\-]+", "_", name)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    out_dir = DATA_DIR / "attach"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / name
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime or out.stat().st_size != src.stat().st_size:
        import shutil
        shutil.copyfile(src, out)
    return out
