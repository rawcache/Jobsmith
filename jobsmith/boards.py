"""Public job boards: a company's Greenhouse, Lever or Ashby board, read as JSON before any browser opens.

All three publish every open role at a public, read-only address, the same data their job pages show:

    Greenhouse  boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true&pay_transparency=true
    Lever       api.lever.co/v0/postings/{company}?mode=json
    Ashby       api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true

Jobsmith only GETs them; no sign-in, nothing sent. Each role is screened right there on what the board says:
seniority words in the title, the years of experience the posting asks for, and the pay against your minimum.
Roles that fail never become matches, so no browser ever opens for them; the sync says how many were left out and
why. Like eligibility.py, only what's stated counts: a posting that doesn't give pay passes the pay check."""
from __future__ import annotations

import html
import re
import time
from collections import Counter
from datetime import datetime

import httpx

from . import ats, db, profile
from .eligibility import JUNIOR_OK, YEARS

UA = {"User-Agent": "jobsmith (+https://github.com/rawcache/Jobsmith)"}

BOARD_URLS = [
    ("greenhouse", re.compile(r"(?:job-)?boards(?:-api)?(?:\.eu)?\.greenhouse\.io/(?:v1/boards/)?([A-Za-z0-9_-]+)/?(?:jobs/?)?(?:[?#].*)?$", re.I)),
    ("lever", re.compile(r"(?:jobs(?:\.eu)?\.lever\.co|api\.lever\.co/v0/postings)/([A-Za-z0-9_.-]+)/?(?:[?#].*)?$", re.I)),
    ("ashby", re.compile(r"(?:jobs\.ashbyhq\.com|api\.ashbyhq\.com/posting-api/job-board)/([A-Za-z0-9_.%-]+)/?(?:[?#].*)?$", re.I)),
]


def board_of(url: str) -> tuple[str, str] | None:
    """("greenhouse", "figma") for a board's own address (not one posting on it), else None."""
    for kind, pat in BOARD_URLS:
        m = pat.search((url or "").strip())
        if m and m.group(1).lower() not in ("embed", "v1", "jobs"):
            return kind, m.group(1)
    return None


def api_url(kind: str, board: str) -> str:
    return {"greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true&pay_transparency=true",
            "lever": f"https://api.lever.co/v0/postings/{board}?mode=json",
            "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true"}[kind]


def _name(board: str) -> str:
    """Lever and Ashby don't send the company's name: "scale-ai" reads as "Scale Ai" until the posting says more."""
    return " ".join(w.capitalize() for w in re.split(r"[-_.%20]+", board) if w) or board


def _when(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return v / 1000 if v > 1e11 else float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


PER = {"year": 1, "month": 12, "hour": 2080}


def _pay(lo, hi, per: str, currency: str) -> dict | None:
    if lo is None and hi is None:
        return None
    return {"lo": float(lo if lo is not None else hi), "hi": float(hi if hi is not None else lo), "per": per,
            "currency": (currency or "USD").upper()}


def _text_pay(text: str) -> dict | None:
    """Pay as the posting's text states it ("$145,000 - $155,000"), when the board has no structured pay."""
    from .insights import pay_range
    r = pay_range(text)
    return _pay(r[0], r[1], "hour" if r[2] else "year", "USD") if r else None


def _gh_range(r: dict) -> dict | None:
    lo, hi = (r.get("min_cents") or 0) / 100 or None, (r.get("max_cents") or 0) / 100 or None
    # Its label says "Annual Base Salary Range:", "Hourly", or just "Internship" ($55): then the amount tells.
    t, top = r.get("title") or "", hi or lo
    per = "hour" if re.search(r"hour", t, re.I) else "month" if re.search(r"month", t, re.I) else \
        "year" if re.search(r"annual|year|salary", t, re.I) else \
        "hour" if top < 300 else "month" if top < 20000 else "year"
    return _pay(lo, hi, per, r.get("currency_type"))


def parse(kind: str, data, company: str = "") -> list[dict]:
    """The board's roles, each as {external_id, title, company, url, locations, description, html, date_posted,
    pay, remote}. Descriptions are what a person reads (hidden text left out); `html` is the posting as served."""
    from .jobdetail import html_to_text
    out = []
    if kind == "greenhouse":
        for j in data.get("jobs", []):
            raw = html.unescape(j.get("content") or "")
            ranges = [r for r in j.get("pay_input_ranges") or [] if r.get("min_cents") or r.get("max_cents")]
            # One range per location is common; the best one counts, so a role isn't left out over another city's.
            pays = [p for p in map(_gh_range, ranges) if p]
            pay = max(pays, key=lambda p: (p["currency"] == "USD", p["hi"] * PER[p["per"]]), default=None)
            text = html_to_text(raw)
            loc = (j.get("location") or {}).get("name") or ""
            out.append({"external_id": str(j.get("id")), "title": (j.get("title") or "").strip(),
                        "company": (j.get("company_name") or company).strip(), "url": j.get("absolute_url") or "",
                        "locations": [x.strip() for x in re.split(r"\s*[•;|]\s*", loc) if x.strip()],
                        "description": text, "html": raw, "date_posted": _when(j.get("first_published") or j.get("updated_at")),
                        "pay": pay or _text_pay(text), "remote": bool(re.search(r"\bremote\b", loc, re.I))})
    elif kind == "lever":
        for j in data if isinstance(data, list) else []:
            raw = "\n".join([j.get("description") or "", *(f"<h3>{x.get('text', '')}</h3>{x.get('content', '')}"
                                                            for x in j.get("lists", [])), j.get("additional") or ""])
            text = html_to_text(raw)
            cats = j.get("categories") or {}
            sr = j.get("salaryRange") or {}
            per = "hour" if "hour" in (sr.get("interval") or "") else "month" if "month" in (sr.get("interval") or "") \
                else "year"
            out.append({"external_id": j.get("id") or "", "title": (j.get("text") or "").strip(), "company": company,
                        "url": j.get("hostedUrl") or "", "locations": cats.get("allLocations") or
                        ([cats["location"]] if cats.get("location") else []),
                        "description": text, "html": raw, "date_posted": _when(j.get("createdAt")),
                        "pay": _pay(sr.get("min"), sr.get("max"), per, sr.get("currency")) if sr else _text_pay(text),
                        "remote": (j.get("workplaceType") or "") == "remote"})
    elif kind == "ashby":
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            raw = j.get("descriptionHtml") or ""
            text = html_to_text(raw) if raw else j.get("descriptionPlain") or ""
            pay = None
            for c in (j.get("compensation") or {}).get("summaryComponents") or []:
                if c.get("compensationType") in ("Salary", "Hourly") and (c.get("minValue") or c.get("maxValue")):
                    iv = (c.get("interval") or "").upper()
                    per = "hour" if "HOUR" in iv else "month" if "MONTH" in iv else "year"
                    pay = _pay(c.get("minValue"), c.get("maxValue"), per, c.get("currencyCode"))
                    break
            locs = [j.get("location") or ""] + [x.get("location") or "" for x in j.get("secondaryLocations") or []]
            out.append({"external_id": j.get("id") or "", "title": (j.get("title") or "").strip(), "company": company,
                        "url": j.get("jobUrl") or "", "locations": [x for x in locs if x], "description": text,
                        "html": raw, "date_posted": _when(j.get("publishedAt")), "pay": pay or _text_pay(text),
                        "remote": bool(j.get("isRemote"))})
    return [j for j in out if j["title"] and j["url"]]


# --------------------------------------------------------------------------- screening
# Seniority words in a title, and the years of experience you'd want before applying to each.
SENIOR_TITLE = [(re.compile(r"\b(principal|staff|director|head of|vp|vice president|chief|distinguished|fellow|"
                            r"engineering manager)\b", re.I), 7),
                (re.compile(r"\b(senior|sr\.?|lead)\b", re.I), 3)]


def your_years(ans: dict | None = None, s: dict | None = None) -> float | None:
    """About how many years you've worked: your profile's answer, 0 if you're a student or looking for internships
    or new grad roles, None when Jobsmith can't tell (then seniority and experience aren't screened)."""
    ans = ans if ans is not None else profile.answers()
    s = s if s is not None else db.get_settings()
    m = re.search(r"\d+(?:\.\d+)?", (ans.get("years_experience") or {}).get("value") or "")
    if m:
        return float(m.group(0))
    goals = set(s.get("goals") or [])
    if goals and goals <= {"internship", "newgrad"}:
        return 0.0
    grad = re.search(r"20\d\d", (ans.get("graduation_year") or ans.get("graduation_date") or {}).get("value") or "")
    if grad and int(grad.group(0)) >= time.localtime().tm_year:
        return 0.0
    return None


PREFERRED = re.compile(r"prefer|nice[- ]to[- ]have|bonus|ideal|\ba plus\b|desired|desirable", re.I)
REQUIRED = re.compile(r"minimum|required|\bmust\b|at least", re.I)
HEADING = re.compile(r"^\s*[A-Za-z][A-Za-z ,'’&/()-]{2,60}:?\s*$")
# A heading: a line ending in a colon, a short line naming a section ("What We Require"), or a whole line that is
# one ("Preferred experience", "Preferred background", but not "CPA preferred" or "Experience with Python").
SECTION = re.compile(r"qualifications|requirements|\brequire|skills|\bneed|\bbring|\bhave\b|looking for|"
                     r"about you|bonus|\bplus\b|you are|you're|what you", re.I)
SHORT_SECTION = re.compile(r"^\s*(?:preferred\s+|required\s+|relevant\s+)?(?:experience|qualifications|skills)\s*$|"
                           r"^\s*(?:preferred|nice to have|responsibilities|about (?:the role|you)|the role|benefits)\s*$|"
                           r"^\s*(?:preferred|bonus|nice to have)\b(?:\s+[A-Za-z]+){0,2}\s*$", re.I)


def years_asked(text: str) -> int:
    """The years of experience a posting requires. A role left out here is never stored, so you can't "apply
    anyway": read it generously. Years only preferred don't count (unless the line also says minimum or required),
    alternatives in one sentence ("5 years of experience with a BS, or 3 years of experience with an MS") take the
    easier, and a range ("3-5 years") its low end."""
    need, preferred = 0, False
    for line in text.splitlines():
        words = len(line.split())
        if HEADING.match(line) and (line.rstrip().endswith(":") or SECTION.search(line) and words <= 7
                                    or SHORT_SECTION.match(line)):
            # "Preferred qualifications:" or "Nice to have" covers the lines under it, up to the next heading
            preferred = bool(PREFERRED.search(line)) and not REQUIRED.search(line)
            continue
        for sentence in re.split(r"(?<=[.;!?])\s+", line):
            if (preferred or PREFERRED.search(sentence)) and not REQUIRED.search(sentence):
                continue
            found, asks = [], []
            for m in YEARS.finditer(sentence):
                low = re.search(r"(\d{1,2})\s*(?:-|–|—|to)\s*$", sentence[:m.start()])
                n = min(int(m.group(1)), int(low.group(1))) if low else int(m.group(1))
                if n < 30:
                    found.append(m)
                    asks.append(n)
            # Asks joined by "or" are alternatives; otherwise each one applies.
            either = any(re.search(r"\bor\b", sentence[a.end():b.start()], re.I) for a, b in zip(found, found[1:]))
            if asks:
                need = max(need, min(asks) if either else max(asks))
    return need


def _usd(n: float) -> str:
    return f"${n / 1000:,.0f}k" if n >= 1000 else f"${n:,.0f}"


def screen(job: dict, years: float | None, min_pay: float) -> tuple[str, str] | None:
    """(kind, reason in plain words) when this role isn't worth an application, else None. kind is one of
    senior | experience | pay."""
    title = job.get("title") or ""
    if years is not None and not JUNIOR_OK.search(title):
        for pat, need in SENIOR_TITLE:
            m = pat.search(title)
            if m and years < need:
                return "senior", f'"{m.group(0)}" in the title: more senior than you\'re looking for'
    if years is not None:
        asks = years_asked(job.get("description") or "")
        if asks >= 3 and asks > years + 1:
            return "experience", f"Asks for {asks}+ years of experience"
    pay = job.get("pay")
    if min_pay and pay and pay["currency"] == "USD":
        top = pay["hi"] * PER[pay["per"]]
        if top < min_pay:
            stated = f"{_usd(pay['hi'])} a year" if pay["per"] == "year" else \
                f"${pay['hi']:,.0f} a{'n' if pay['per'] == 'hour' else ''} {pay['per']} (about {_usd(top)} a year)"
            return "pay", f"Pays up to {stated}, under your minimum of {_usd(min_pay)} a year"
    return None


WHY = {"senior": "senior titles", "experience": "ask for more experience", "pay": "pay under your minimum"}


def left_out_words(why: dict[str, int]) -> str:
    """ "90 senior titles, 30 ask for more experience" """
    return ", ".join(f"{n} {WHY[k]}" for k, n in sorted(why.items(), key=lambda x: -x[1]) if n)


# --------------------------------------------------------------------------- sync
def _terms(title: str) -> list[str]:
    m = re.search(r"\b(summer|fall|winter|spring)\s+(20\d\d)\b", title, re.I)
    if m:
        return [f"{m.group(1).capitalize()} {m.group(2)}"]
    if re.search(r"new ?grad|early career|university grad|entry[- ]level", title, re.I):
        return ["New Grad"]
    return []


# What autopilot may still pick up on its own (scheduler.pick_new_jobs): ones in these states that stop passing,
# or leave the board, are put away. Anything you've filled, sent or held stays as it is.
UNTOUCHED = ("new", "fetched", "drafted", "error")


def store(source: dict, kind: str, roles: list[dict]) -> dict:
    """Store the board's roles. Ones that pass the screen are matches; the rest are kept as left out, with the
    reason, where autopilot never picks them and you can still apply anyway. Ones that stop passing (you changed
    your minimum) are left out the same way, and ones gone from the board are put away."""
    from . import traps
    from .jobdetail import original_text
    from .match import guess_category
    from .sources import job_id_for
    years, min_pay = your_years(), float(db.get_setting("min_pay") or 0)
    why: Counter = Counter()
    added = updated = 0
    with db.tx() as c:
        seen: list[str] = []
        for r in roles:
            jid = job_id_for(r["url"], r["company"], r["title"])
            seen.append(jid)
            exists = c.execute("SELECT status, left_out FROM jobs WHERE id=?", (jid,)).fetchone()
            if exists and exists["status"] not in UNTOUCHED + ("left_out",):
                continue                                 # you've filled, sent or skipped it: it stays as it is
            out = None if exists and exists["left_out"] == "waived" else screen(r, years, min_pay)
            if out:
                why[out[0]] += 1
            found = traps.unique(traps.scan_html(r["html"]) + traps.scan_text(r["description"]))
            row = (source["id"], r["external_id"], r["company"], r["title"], ats.clean_url(r["url"]), kind,
                   db.enc(r["locations"]), db.enc(_terms(r["title"])), guess_category(r["title"]), r["date_posted"],
                   r["description"], db.enc(found), original_text(r["html"]) if found else "")
            if out:
                state = ("left_out", out[0], "Left out: " + out[1])
            elif exists and exists["status"] == "left_out":
                state = ("new", None, None)              # it passes now
            else:
                state = None
            if exists:
                c.execute("""UPDATE jobs SET source_id=?, external_id=?, company=?, title=?, url=?, ats=?, locations=?,
                             terms=?, category=?, date_posted=?, description=?, traps=?, original=?, active=1,
                             hold_reason=CASE WHEN hold_reason='No longer on the board' THEN NULL ELSE hold_reason END,
                             updated_at=? WHERE id=?""", row + (db.now(), jid))
                if state:
                    c.execute("UPDATE jobs SET status=?, left_out=?, hold_reason=? WHERE id=?", state + (jid,))
                updated += not out
            else:
                c.execute("""INSERT INTO jobs(source_id, external_id, company, title, url, ats, locations, terms,
                             category, date_posted, description, traps, original, active, id, created_at, updated_at,
                             status, left_out, hold_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?)""",
                          row + (jid, db.now(), db.now()) + (state or ("new", None, None)))
                added += not out
        # Roles taken down since the last sync are closed: put away the ones autopilot could still pick.
        marks = ",".join("?" * len(seen))
        gone = UNTOUCHED + ("left_out",)
        closed = c.execute(f"""UPDATE jobs SET active=0, hold_reason='No longer on the board', updated_at=?
                               WHERE source_id=? AND active=1 AND status IN ({",".join("?" * len(gone))})
                               {f"AND id NOT IN ({marks})" if seen else ""}""",
                           (db.now(), source["id"], *gone, *seen)).rowcount
        c.execute("UPDATE sources SET last_synced=?, last_count=? WHERE id=?", (db.now(), len(roles), source["id"]))
    return {"source": source["url"], "listings": len(roles), "added": added, "updated": updated,
            "left_out": sum(why.values()), "why": dict(why), "closed": closed}


def waive(job_id: str) -> None:
    """You chose to apply to a left-out role anyway: it's a match again, and later syncs don't leave it out."""
    db.x("UPDATE jobs SET status='new', left_out='waived', hold_reason=NULL, updated_at=? WHERE id=? AND status='left_out'",
         (db.now(), job_id))


async def sync(source: dict, client: httpx.AsyncClient | None = None) -> dict:
    """Read one board and store what passes. Only GET requests."""
    kind, board = board_of(source["url"]) or (None, None)
    if not kind:
        return {"source": source["url"], "error": "Not a Greenhouse, Lever or Ashby job board address"}
    own = client is None
    client = client or httpx.AsyncClient(headers=UA, timeout=60, follow_redirects=True)
    try:
        r = await client.get(api_url(kind, board))
        if r.status_code == 404:
            return {"source": source["url"], "error": f"No {kind.capitalize()} job board called {board!r}"}
        r.raise_for_status()
        data = r.json()
    finally:
        if own:
            await client.aclose()
    # An answer in the wrong shape mustn't read as an empty board, which would put every role away as closed.
    if not (isinstance(data, list) if kind == "lever" else isinstance(data, dict) and isinstance(data.get("jobs"), list)):
        return {"source": source["url"], "error": f"{kind.capitalize()} sent something that isn't a job board"}
    return store(source, kind, parse(kind, data, _name(board)))
