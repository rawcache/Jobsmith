"""Cover letters: the text Jobsmith wrote (or you edited), turned into a clean one-page PDF for the form."""
from __future__ import annotations

import re
import time
from pathlib import Path

from . import db, draft, profile
from .config import DATA_DIR

LETTERS_DIR = DATA_DIR / "letters"


def cover_draft(job_id: str) -> dict | None:
    return db.q1("""SELECT * FROM drafts WHERE job_id=? AND (lower(field) LIKE '%cover%' OR lower(label) LIKE '%cover letter%')
                    ORDER BY id LIMIT 1""", (job_id,))


def cover_text(job_id: str) -> str:
    d = cover_draft(job_id)
    return draft.final_value(d).strip() if d else ""


_PLAIN = {"—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...",
          " ": " ", "•": "-"}


def _latin1(s: str) -> str:
    """The PDF's built-in font is Latin-1: swap typographic punctuation for plain equivalents."""
    for a, b in _PLAIN.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def cover_pdf(job_id: str, out_dir: Path | None = None) -> Path | None:
    text = cover_text(job_id)
    if not text:
        return None
    from fpdf import FPDF
    job = db.q1("SELECT company, title FROM jobs WHERE id=?", (job_id,)) or {}
    a = {k: (v.get("value") or "") for k, v in profile.answers().items()}
    name = " ".join(x for x in (a.get("first_name"), a.get("last_name")) if x) or "Applicant"
    contact = "  |  ".join(x for x in (a.get("email"), a.get("phone"), a.get("location"), a.get("linkedin")) if x)

    pdf = FPDF(format="Letter")
    pdf.set_margins(25, 25, 25)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, _latin1(name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(0, 5, _latin1(contact), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, time.strftime("%B %d, %Y").replace(" 0", " "), new_x="LMARGIN", new_y="NEXT")
    if job.get("company"):
        pdf.cell(0, 6, _latin1(f"{job['company']}, {job.get('title', '')}".strip(", ")), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    body = text if text.lower().startswith(("dear", "hello", "hi ", "to ")) else f"Dear {job.get('company') or 'Hiring'} team,\n\n{text}"
    closing = re.search(r"(sincerely|best regards|regards|thank you|best),?\s*\n", body[-200:].lower())
    if not closing and not body.rstrip().lower().endswith(name.lower()):
        body = body.rstrip() + f"\n\nSincerely,\n{name}"
    for para in body.split("\n"):
        if para.strip():
            pdf.multi_cell(0, 6, _latin1(para.strip()), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        else:
            pdf.ln(2)
    out = (out_dir or LETTERS_DIR / job_id)
    out.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in name if c.isalnum() or c in " -").strip().replace(" ", "_") or "Cover"
    path = out / f"{safe}_Cover_Letter.pdf"
    pdf.output(str(path))
    return path


async def write_cover(job_id: str) -> str:
    """Write a cover letter for this job even if its form doesn't ask for one (you can attach it yourself)."""
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    if cover_draft(job_id):
        return cover_text(job_id)
    f = {"field": "cover_letter", "label": "Cover letter", "qtype": "textarea", "required": False, "options": [],
         "description": "Cover letter, under 250 words.", "section": "main"}
    results, err = await draft.answer_fields(job, [f], skip_locked=False)
    if err:
        raise RuntimeError(err)
    draft.save_results(job_id, [f], results)
    return cover_text(job_id)
