"""Tailored resume per job, built from your LaTeX source.

Only reorders what's already there: bullets within each role/project, entries within each section,
and the lines of your skills section, so the most relevant ones come first. No wording changes,
nothing added or removed, so it can never claim something your resume doesn't.
Needs a LaTeX compiler on your Mac (`brew install tectonic`, or MacTeX's pdflatex)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from . import db, profile
from .match import tokens


def compiler() -> tuple[str, str] | None:
    """(kind, path) of an available LaTeX compiler."""
    for exe in ("tectonic", "pdflatex"):
        path = shutil.which(exe) or next((p for p in (f"/opt/homebrew/bin/{exe}", f"/usr/local/bin/{exe}",
                                                       f"/Library/TeX/texbin/{exe}") if Path(p).exists()), None)
        if path:
            return exe, path
    return None


def _score(text: str, jd: set[str]) -> int:
    return len(tokens(text) & jd)


def _reorder_items(block: str, jd: set[str]) -> str:
    """Sort the \\item entries inside one itemize block by relevance (stable for ties). Line-based, and
    leaves any block containing commented-out lines untouched."""
    lines = block.split("\n")
    if any(l.lstrip().startswith("%") for l in lines):
        return block
    head, items, tail = [], [], []
    for l in lines:
        st = l.lstrip()
        if st.startswith("\\end{itemize}") or tail:
            tail.append(l)
        elif st.startswith("\\item"):
            items.append([l])
        elif items:
            items[-1].append(l)
        else:
            head.append(l)
    if len(items) < 2:
        return block
    ranked = sorted(enumerate(items), key=lambda t: (-_score(" ".join(t[1]), jd), t[0]))
    return "\n".join(head + [l for _, it in ranked for l in it] + tail)


def tailor_tex(tex: str, job_text: str) -> str:
    jd = tokens(job_text)
    # 1) bullets inside each (uncommented) itemize block
    out, pos = [], 0
    for m in re.finditer(r"\\begin\{itemize\}.*?\\end\{itemize\}", tex, re.S):
        line_start = tex.rfind("\n", 0, m.start()) + 1
        if tex[line_start:m.start()].lstrip().startswith("%"):
            continue
        out.append(tex[pos:m.start()])
        out.append(_reorder_items(m.group(0), jd))
        pos = m.end()
    out.append(tex[pos:])
    tex = "".join(out)
    # 2) skills lines: "\\textbf{Group:} a, b, c \\\\" lines inside the skills section
    m = re.search(r"(\\section\*?\{[^}]*Skill[^}]*\}\s*\n)(.*?)(?=\n\s*(%|\\section))", tex, re.S)
    if m:
        lines = [l for l in m.group(2).split("\n") if l.strip()]
        if len(lines) > 1 and all("\\textbf" in l and not l.lstrip().startswith("%") for l in lines):
            body = [l.rstrip().removesuffix("\\\\").rstrip() for l in lines]
            ranked = [b for _, b in sorted(enumerate(body), key=lambda t: (-_score(t[1], jd), t[0]))]
            new = " \\\\\n".join(ranked) + "\n"
            tex = tex[:m.start(2)] + new + tex[m.end(2):]
    return tex


def tailored_pdf(job: dict, out_dir: Path, name: str) -> Path | None:
    """Compile a tailored copy for this job. Returns None (use the normal PDF) if anything is missing."""
    if not db.get_setting("tailor_resume"):
        return None
    src = db.q1("SELECT text FROM documents WHERE kind='resume' ORDER BY created_at DESC")
    cmd = compiler()
    if not src or not profile.looks_like_latex(src["text"]) or not cmd:
        return None
    tex = tailor_tex(src["text"], f"{job.get('title', '')}\n{job.get('description', '')}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(name).stem
    tex_path = out_dir / f"{stem}.tex"
    tex_path.write_text(tex)
    kind, exe = cmd
    args = [exe, "--outdir", str(out_dir), str(tex_path)] if kind == "tectonic" else \
        [exe, "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    try:
        subprocess.run(args, cwd=out_dir, capture_output=True, timeout=180, check=True)
    except Exception:
        return None
    pdf = out_dir / f"{stem}.pdf"
    return pdf if pdf.exists() else None
