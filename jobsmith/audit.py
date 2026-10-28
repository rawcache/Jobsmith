"""The audit trail: for every submission, each field, the answer sent, where it came from and the kind check.

When Jobsmith fills a form it captures the fields it actually filled, with their sources, right then. When the
submission is recorded (confirmed, marked by you, or clicked by autopilot without a confirmation page) that capture
becomes the trail, so a redraft in between never changes it. A form Jobsmith didn't fill (you used the extension, or
filled it yourself) is recorded from its drafts and says so. It's what `jobsmith audit` samples to show that no
submitted answer was invented."""
from __future__ import annotations

import json

from . import db, draft, profile

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  run_id INTEGER NOT NULL,          -- the submit run this belongs to
  sent_by TEXT NOT NULL,            -- autopilot | you
  at REAL NOT NULL,
  field TEXT NOT NULL,
  label TEXT NOT NULL,
  qtype TEXT NOT NULL DEFAULT '',
  answer TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL,             -- resume | profile | writing | approved | you | file | none
  detail TEXT NOT NULL DEFAULT '[]',-- what it traces to: [{ref, text}]
  approved INTEGER NOT NULL DEFAULT 0,
  kind_check TEXT NOT NULL DEFAULT 'ok',
  issues TEXT NOT NULL DEFAULT '[]',
  traces INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS audit_job ON audit(job_id);
-- One row per submission, so one with no fields to show still appears.
CREATE TABLE IF NOT EXISTS audit_submissions (
  run_id INTEGER PRIMARY KEY,
  job_id TEXT NOT NULL,
  sent_by TEXT NOT NULL,
  at REAL NOT NULL,
  basis TEXT NOT NULL,              -- filled: what Jobsmith filled | drafted: its drafts, it didn't fill the form
  note TEXT NOT NULL DEFAULT ''
);
-- What Jobsmith filled in a form that's waiting to be submitted.
CREATE TABLE IF NOT EXISTS audit_pending (
  job_id TEXT PRIMARY KEY,
  fields TEXT NOT NULL,
  at REAL NOT NULL
);
-- Proof a submission landed: the confirmation page the site showed, or the confirmation email it sent.
CREATE TABLE IF NOT EXISTS confirmations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  run_id INTEGER,                   -- the submission it confirms
  kind TEXT NOT NULL,               -- page | email
  at REAL NOT NULL,
  url TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',   -- the page's title, or the email's subject
  text TEXT NOT NULL DEFAULT '',    -- what the page or email said, trimmed
  sender TEXT NOT NULL DEFAULT '',
  screenshot TEXT NOT NULL DEFAULT '',
  seen_by TEXT NOT NULL DEFAULT '', -- jobsmith | extension | inbox
  message_id TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS confirmations_job ON confirmations(job_id);
-- Every job autopilot picked for itself, and whether it was a good match (at or above your fit bar) at the
-- time. The denominator of "good matches sent without you".
CREATE TABLE IF NOT EXISTS considered (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  at REAL NOT NULL,
  good INTEGER NOT NULL,
  fit REAL
);
CREATE INDEX IF NOT EXISTS considered_at ON considered(at);
"""

SOURCE_LABEL = {"resume": "Your resume", "profile": "Your profile", "writing": "Your writing",
                "approved": "An answer you approved before", "you": "You typed it", "file": "A file you added",
                "none": "Nothing: doesn't trace"}


def _ensure() -> None:
    db.conn().executescript(SCHEMA)


def _fact_source(f: dict) -> str:
    src = (f.get("source") or "").lower()
    return "LinkedIn export" if "linkedin" in src else "your profile" if src in ("", "user") else src


def provenance(d: dict, answers: dict, facts: dict, job: dict | None = None) -> dict:
    """Where one answer came from. `traces` is true only when it leads back to you: your resume, profile,
    writing, an answer you approved or typed, or a file you added."""
    value = draft.final_value(d)
    edited = bool(d.get("final_answer")) and d["final_answer"] != d.get("answer")
    if edited:
        return {"source": "you", "detail": [{"ref": "Your edit", "text": d["final_answer"]}], "traces": True}
    kind = d.get("kind")
    if kind == "file":
        name = profile.attachment_file()
        ref = {"resume": f"Your resume PDF{f' ({name.name})' if name else ''}",
               "transcript": "Your transcript"}.get(d.get("canon") or "", "A file you added")
        return {"source": "file", "detail": [{"ref": ref, "text": ""}], "traces": True}
    if kind in ("answer_bank", "standard"):
        canon = d.get("canon") or ""
        if canon == "employment":
            return {"source": "resume", "detail": [{"ref": "Your work history", "text": value}], "traces": True}
        a = answers.get(canon)
        if a:
            ref = f"Profile: {a['label']}" + ("" if a.get("confirmed") else " (not confirmed yet)")
            # What your profile gives for this field today, mapped to the form's options the same way (a GPA of 3.6
            # becomes "3.5 - 3.79"). If that's not what was sent, the profile changed after it was drafted.
            now = draft.deterministic(dict(d, required=bool(d.get("required"))), answers, job)
            norm = lambda v: " ".join((v or "").lower().split())
            if now is not None and norm(now.get("answer")) != norm(value):
                return {"source": "profile", "traces": False,
                        "detail": [{"ref": ref + " says something else", "text": a.get("value") or ""}]}
            return {"source": "profile", "detail": [{"ref": ref, "text": a.get("value") or ""}], "traces": True}
        return {"source": "profile", "detail": [{"ref": f"Profile ({canon or 'standard field'})", "text": value}],
                "traces": True}
    if kind == "learned":
        return {"source": "approved", "detail": [{"ref": d.get("rationale") or "Your approved answer", "text": ""}],
                "traces": True}
    if kind == "voice":
        return {"source": "writing", "detail": [{"ref": d.get("rationale") or "Your writing", "text": ""}],
                "traces": True}
    cited = [facts[i] for i in d.get("fact_ids") or [] if i in facts]
    if cited:
        return {"source": "resume", "traces": True,
                "detail": [{"ref": _fact_source(f), "text": f["text"], "fact_id": f["id"]} for f in cited]}
    return {"source": "none", "detail": [], "traces": False}


def snapshot(job_id: str, filled: set[str] | None = None) -> list[dict]:
    """Each field as it would be sent now, with its source and checks. With `filled` (the field ids a fill
    reports it set), only those: a field that failed to fill wasn't sent."""
    answers, facts = profile.answers(), profile.facts_by_id()
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    out = []
    for d in draft.drafts_for(job_id):
        value = draft.final_value(d)
        if d["verdict"] == "red" and not d.get("final_answer"):
            continue                                     # you said no: it isn't filled
        if not value.strip() and d["qtype"] != "file":
            continue                                     # left blank: nothing sent
        if d["qtype"] == "file" and d["kind"] == "file" and not value:
            continue
        if filled is not None and d["field"] not in filled:
            continue
        p = provenance(d, answers, facts, job)
        if d["kind"] == "file":
            value = p["detail"][0]["ref"]                # the file itself, not the internal "primary resume"
        fits = None if d["qtype"] == "file" else draft.answer_fits(d, value)
        out.append({"field": d["field"], "label": d["label"], "qtype": d["qtype"], "answer": value,
                    "source": p["source"], "detail": p["detail"], "traces": p["traces"],
                    "approved": d["verdict"] == "green" or bool(d.get("final_answer")),
                    "kind_check": fits or "ok", "issues": d.get("issues") or []})
    return out


def implicit_row(f: dict, answers: dict) -> dict:
    """A field filled straight from your profile with no draft (Greenhouse's phone country, Hispanic/Latino).
    `answer` is what the box shows; `profile` is the answer it was filled from. Only confirmed answers trace."""
    norm = lambda v: " ".join((v or "").lower().split())
    a = answers.get(f["canon"]) or {}
    citizen = answers.get("us_citizen") or {}
    matches = bool(a) and norm(a.get("value")) == norm(f.get("profile"))
    by_citizen = f["canon"] == "country" and f.get("profile") == "United States" and \
        norm(citizen.get("value")) == "yes"
    # The same order the runner fills in: your confirmed answer, then (for country) confirmed citizenship.
    if matches and a.get("confirmed"):
        src = a
    elif by_citizen and citizen.get("confirmed"):
        src = citizen
    else:
        src = a if matches else citizen if by_citizen else None
    if src is None:
        detail, traces = [{"ref": f"Profile ({f['canon']}) says something else", "text": a.get("value") or ""}], False
    else:
        traces = bool(src.get("confirmed"))
        detail = [{"ref": f"Profile: {src['label']}" + ("" if traces else " (not confirmed yet)"),
                   "text": src.get("value") or ""}]
    return {"field": f["field"], "label": f["label"], "qtype": "select", "answer": f.get("answer") or f.get("profile") or "",
            "source": "profile", "detail": detail, "traces": traces, "approved": False, "kind_check": "ok",
            "issues": []}


def capture(job_id: str, filled: set[str] | None = None, implicit: list[dict] | None = None) -> None:
    """Jobsmith just filled this form: keep exactly what it put in, for when it's submitted."""
    _ensure()
    answers = profile.answers()
    rows = [implicit_row(f, answers) for f in implicit or []] + snapshot(job_id, filled)
    db.x("INSERT OR REPLACE INTO audit_pending(job_id, fields, at) VALUES(?,?,?)",
         (job_id, json.dumps(rows, ensure_ascii=False), db.now()))


def record(job_id: str, run_id: int, sent_by: str) -> int:
    """Write the trail for one submission. Returns how many fields it holds."""
    _ensure()
    pending = db.q1("SELECT fields FROM audit_pending WHERE job_id=?", (job_id,))
    if pending:
        rows, basis = json.loads(pending["fields"]), "filled"
        note = "" if sent_by == "autopilot" else \
            "You submitted it yourself: anything you changed in the browser first isn't shown here."
    else:
        rows, basis = snapshot(job_id), "drafted"
        note = "Jobsmith didn't fill this form, so these are its drafts, not necessarily what the form sent."
    with db.tx() as c:
        c.execute("DELETE FROM audit_pending WHERE job_id=?", (job_id,))
        c.execute("INSERT OR REPLACE INTO audit_submissions(run_id, job_id, sent_by, at, basis, note) VALUES(?,?,?,?,?,?)",
                  (run_id, job_id, sent_by, db.now(), basis, note))
        for r in rows:
            c.execute("""INSERT INTO audit(job_id, run_id, sent_by, at, field, label, qtype, answer, source, detail,
                         approved, kind_check, issues, traces) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (job_id, run_id, sent_by, db.now(), r["field"], r["label"], r["qtype"], r["answer"],
                       r["source"], json.dumps(r["detail"], ensure_ascii=False), int(r["approved"]), r["kind_check"],
                       json.dumps(r["issues"], ensure_ascii=False), int(r["traces"])))
    return len(rows)


def log_confirmation(job_id: str, kind: str, *, run_id: int | None = None, url: str = "", title: str = "",
                     text: str = "", sender: str = "", screenshot: str = "", seen_by: str = "jobsmith",
                     message_id: str | None = None, at: float | None = None) -> bool:
    """Keep the proof a submission landed. Without `run_id` it belongs to the job's latest submission. False when
    there's no submission to attach it to, or this email was already logged."""
    _ensure()
    if run_id is None:
        r = db.q1("SELECT id FROM runs WHERE job_id=? AND kind='submit' AND status IN ('done','unconfirmed') "
                  "ORDER BY id DESC LIMIT 1", (job_id,))
        if not r:
            return False
        run_id = r["id"]
    try:
        db.x("""INSERT INTO confirmations(job_id, run_id, kind, at, url, title, text, sender, screenshot, seen_by,
                message_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
             (job_id, run_id, kind, at or db.now(), url[:1000], title[:300], " ".join(text.split())[:4000],
              sender[:200], screenshot, seen_by, message_id))
    except Exception:
        return False                                      # the same email again
    _settle(job_id, run_id, kind)
    return True


def _settle(job_id: str, run_id: int, kind: str) -> None:
    """Autopilot clicked Submit but never saw the confirmation page, so the application was held "check your email".
    Proof arrived after all: it was sent, by autopilot, and nothing is waiting on you."""
    run = db.q1("SELECT status FROM runs WHERE id=?", (run_id,))
    if not run or run["status"] != "unconfirmed":
        return
    what = "confirmation email" if kind == "email" else "confirmation page"
    db.x("UPDATE runs SET status='done', log=COALESCE(log,'') || ? WHERE id=?", (f"\nConfirmed later by its {what}.", run_id))
    db.x("UPDATE jobs SET status='submitted', hold_reason=NULL, updated_at=? WHERE id=? AND status='filled'",
         (db.now(), job_id))


def confirmations(run_id: int) -> list[dict]:
    _ensure()
    return db.q("SELECT kind, at, url, title, text, sender, screenshot, seen_by FROM confirmations WHERE run_id=? "
                "ORDER BY at", (run_id,))


def log_considered(job_id: str, good: bool, fit: float | None) -> None:
    """Autopilot looked at this job on its own: counted in `jobsmith stats` whatever happens to it next."""
    _ensure()
    db.x("INSERT INTO considered(job_id, at, good, fit) VALUES(?,?,?,?)", (job_id, db.now(), int(good), fit))


def for_job(job_id: str) -> list[dict]:
    """Every submission of this application, newest first, each with its fields."""
    _ensure()
    subs = db.q("""SELECT r.id run_id, r.status, r.finished_at at, s.sent_by, s.basis, s.note
                   FROM runs r JOIN audit_submissions s ON s.run_id=r.id
                   WHERE r.job_id=? AND r.kind='submit' ORDER BY r.id DESC""", (job_id,))
    out = []
    for s in subs:
        fields = db.q("SELECT * FROM audit WHERE run_id=? ORDER BY id", (s["run_id"],))
        for f in fields:
            f["detail"], f["issues"] = json.loads(f["detail"]), json.loads(f["issues"])
            f["approved"], f["traces"] = bool(f["approved"]), bool(f["traces"])
            f["source_label"] = SOURCE_LABEL.get(f["source"], f["source"])
            for k in ("id", "job_id", "run_id", "at", "sent_by"):
                f.pop(k, None)
        out.append({"run_id": s["run_id"], "submitted_at": s["at"], "confirmed": s["status"] == "done",
                    "confirmations": confirmations(s["run_id"]),
                    "sent_by": s["sent_by"], "basis": s["basis"], "note": s["note"], "fields": fields,
                    "untraced": sum(1 for f in fields if not f["traces"])})
    return out


def export(job_id: str) -> dict:
    """The JSON you can download from the job's page."""
    job = db.q1("SELECT id, company, title, url FROM jobs WHERE id=?", (job_id,)) or {}
    from . import __version__
    return {"jobsmith": __version__, "job": job, "submissions": for_job(job_id)}


def _day(t: float) -> str:
    """"Oct 5", built by hand: the strftime code that drops the zero isn't available on Windows."""
    import time
    lt = time.localtime(t)
    return f"{time.strftime('%b', lt)} {lt.tm_mday}"


def sample(n: int = 50, seed: int | None = None) -> list[dict]:
    """`jobsmith audit`: up to n submitted applications picked at random (all of them when there are fewer), each
    with every answer it sent and what that answer traces to."""
    import random
    _ensure()
    runs = [r["run_id"] for r in db.q("""SELECT s.run_id FROM audit_submissions s JOIN runs r ON r.id=s.run_id
                                          WHERE r.kind='submit' ORDER BY s.run_id""")]
    picked = sorted(random.Random(seed).sample(runs, min(n, len(runs))))
    out = []
    for run_id in picked:
        job_id = db.q1("SELECT job_id FROM audit_submissions WHERE run_id=?", (run_id,))["job_id"]
        sub = next(s for s in for_job(job_id) if s["run_id"] == run_id)
        job = db.q1("SELECT company, title FROM jobs WHERE id=?", (job_id,)) or {}
        replied = bool(db.q("SELECT name FROM sqlite_master WHERE name='outcomes'")) and bool(db.q1(
            "SELECT 1 FROM outcomes WHERE job_id=? AND received_at>=?", (job_id, sub["submitted_at"] - 3600)))
        out.append(dict(sub, job_id=job_id, company=job.get("company", ""), title=job.get("title", ""),
                        replied=replied))
    return out


def render_sample(subs: list[dict], total: int) -> str:
    """Plain words for the terminal: every answer with its source, and a flag on any that doesn't trace."""
    import time
    lines = []
    for s in subs:
        when = _day(s["submitted_at"])
        proof = ", ".join(sorted({c["kind"] for c in s["confirmations"]} | ({"reply"} if s.get("replied") else set()))) \
            or "no confirmation logged"
        lines += ["", f"{s['company']} · {s['title']}",
                  f"  sent by {s['sent_by']} on {when} · {proof}" + (f" · {s['note']}" if s["note"] else "")]
        if not s["fields"]:
            lines.append("  (no answers recorded for this one)")
        for f in s["fields"]:
            answer = " ".join((f["answer"] or "").split())
            answer = answer if len(answer) <= 100 else answer[:97] + "..."
            lines.append(f"  {'✓' if f['traces'] else '✗'} {f['label']}: {answer}")
            if not f["traces"]:
                lines.append("      DOESN'T TRACE to anything you gave Jobsmith")
            for d in f["detail"][:2]:
                text = " ".join((d.get("text") or "").split())
                text = text if len(text) <= 90 else text[:87] + "..."
                lines.append(f"      ← {d['ref']}" + (f": {text}" if text and text != answer else ""))
    answers = sum(len(s["fields"]) for s in subs)
    bad = [(s, f) for s in subs for f in s["fields"] if not f["traces"]]
    lines += ["", f"Checked {len(subs)} of {total} submitted applications: {answers} answers, "
                  f"{len(bad)} that {'doesn' if len(bad) == 1 else 'don'}'t trace to a fact."]
    lines += [f"  ✗ {s['company']}: {f['label']}" for s, f in bad]
    return "\n".join(lines).lstrip("\n")
