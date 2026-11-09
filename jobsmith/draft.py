"""Research a job, then draft every answer on its form.

Order of preference for each field:
  1. answer bank (your own standard answers; legally sensitive ones are never generated)
  2. your saved answer to that kind of essay question (essays.py), as you wrote it; an optional essay box with
     none is left blank
  3. a past answer you approved for essentially the same question (learning loop)
  4. one batched AI call for everything else, which must cite fact ids; a validator checks it

Autopilot answers 1-3 first, with no AI. If that already shows the application will wait for you (a fact only you
can give), it's held there, and no AI is spent on it until you've answered.
"""
from __future__ import annotations

import json
import re

from .skills import voice
from . import classify, db, essays, jobdetail, learn, profile, traps
from . import llm
from .llm import BusyError, LLMError, QuotaError, complete_json

# Written by AI once it's available (and, for a held application, once you've answered what it waits on)
PENDING_ISSUE = "Waiting for AI: written once it's available"
AI_MADE = ("generated", "voice", "agent")

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


_STOP = r"(?:in|within|during|over|since|from|between|before|after|until|prior to)"
ASKS_ABOUT = re.compile(r"(?:(?:worked|work|been employed|employed)\s+(?:for|at|by|with)|(former|previous|past)\s+"
                        r"(?:employee|intern|contractor|worker)s?\s+(?:of|at|with))\s+(.+?)"
                        r"(?=\s+(?:before|previously|in the past|at any time|ever)\b|\s*[,?.(]|\s+as\b"
                        rf"|\s+(?:or|and)\s+(?:any|its|their|one)\b|\s+{_STOP}\b|$)", re.I)
INITIALS = re.compile(r"\b(?:[A-Za-z]\.){2,}")
NOT_A_COMPANY = re.compile(r"^(?:a|an|any|another|other)\b", re.I)      # "worked for a government agency"
THIS_COMPANY = re.compile(r"^(?:us|this company|the company|our company|this organi[sz]ation|here)$", re.I)
MEANS_THIS_COMPANY = re.compile(r"\b(?:us|here|our company|this company|this organi[sz]ation)\b", re.I)
GROUP = re.compile(r"\b(subsidiar|affiliat|parent|sister compan|related compan|any of (?:its|our))", re.I)
# A time window ("in the last two years", "during 2020", "from 2020 to 2021"): your resume's dates would have to be
# read against it.
TIMED = re.compile(r"\b(?:in|within|during|over)\s+the\s+(?:last|past)\b|\b(?:last|past)\s+(?:\d+|one|two|three|"
                   r"four|five|six|seven|ten|twelve)\b|\b(?:in|during|since|from|between|before|after|until|prior to)"
                   r"\s+(?:\d{4}|january|february|march|april|may|june|july|august|september|october|november|"
                   r"december)\b|\bwithin\s+\d+", re.I)
AS_KIND = re.compile(r"\bas\s+(?:a|an)\s+([^?.]+)", re.I)               # "as a full-time employee"


def _asked_company(job: dict, label: str) -> tuple[str, bool, bool]:
    """(company the question asks about, whether it asks about one kind of work or one time only, whether that
    company is this job's own).

    This job's company when the question names it ("Previous Figma employee?") or means it ("worked for us
    before?"); another company only when the question names that one alone; "" when it can't be read surely: a kind
    of employer ("a government agency"), a name that runs on, both companies, or wording that names none. Specific:
    "as a full-time employee", "a former intern", "in the last two years", "during 2020"."""
    label = label or ""
    kind = AS_KIND.search(label)
    specific = bool(TIMED.search(label)) or bool(kind and not (re.search(r"employ", kind.group(1), re.I)
                                                               and re.search(r"contract|consult", kind.group(1), re.I)))
    own = (job.get("company") or "").strip()
    own_name = profile.employer_name(own)
    names_own = bool(own_name) and bool(re.search(rf"(?<![a-z0-9]){re.escape(own_name)}(?![a-z0-9])",
                                                  profile.employer_name(label)))
    # "the U.S. Government": the dots of initials aren't the end of the name (a lone "X." may end a sentence)
    m = ASKS_ABOUT.search(INITIALS.sub(lambda i: i.group(0).replace(".", "\u2024"), label))
    named = m.group(2).strip().replace("\u2024", ".") if m else ""
    specific = specific or bool(m and m.group(1))                       # "former intern at", "previous employee of"
    if named and not THIS_COMPANY.match(named):
        name = profile.employer_name(named)
        if names_own and own_name.startswith(name):     # "Life After Hate" in the question, cut at "after": still it
            return own, specific, True
        if names_own or NOT_A_COMPANY.match(named) or len(named.split()) > 6:
            return "", specific, False                                 # two companies, a kind of one, or a run-on
        return named, specific, False
    if names_own or MEANS_THIS_COMPANY.search(label) or (named and THIS_COMPANY.match(named)):
        return own, specific, True
    return "", specific, False


def _worked_here(job: dict, ans: dict, label: str = "") -> tuple[str, str]:
    """("Yes" / "No" / "", where it came from) for "Have you worked for <company> before?".

    Yes when your resume names the company the question asks about, unless the question asks about one kind of
    work or one time ("as an intern", "in 2020"): your resume may not say, so that waits for you. No only for this
    job's own company, when you've confirmed your resume lists every employer and contract you've had and the
    company isn't on it (then it holds for any kind of work and any time), and not when the question also covers
    subsidiaries or affiliates. A company missing from a resume isn't, on its own, a fact. Otherwise "", for you."""
    company, specific, own = _asked_company(job, label)
    hit = profile.employer_fact(company) if company else None
    if hit:
        return ("", "") if specific else ("Yes", f"Your resume lists {company}: {hit['subject'] or hit['text'][:80]}")
    every = ans.get("resume_lists_all_employers") or {}
    if own and company and every.get("confirmed") and (every.get("value") or "").strip().lower() == "yes" \
            and not GROUP.search(label or ""):
        return "No", f"You confirmed your resume lists every employer and contract you've had, and {company} isn't on it"
    return "", ""


# Yes/no questions with legal or employment weight: each answer says where it came from, in the extension's panel
# and the audit trail.
LEGAL_YES_NO = {"work_authorized_us", "needs_sponsorship", "us_citizen", "us_person", "citizenship_status",
                "previously_employed"}


def source_line(canon: str, ans: dict, job: dict | None = None, label: str = "") -> str:
    """Where a legal or employment yes/no answer came from, in plain words: the same field _derived read."""
    if canon == "previously_employed":
        return _worked_here(job or {}, ans, label)[1]
    citizen = ((ans.get("us_citizen") or {}).get("value") or "").strip().lower() == "yes"
    base = {"us_person": "us_citizen",
            "citizenship_status": "us_citizen" if citizen else "citizenships"}.get(canon, canon)
    a = ans.get(base) or {}
    if not (a.get("value") or "").strip():
        return ""
    return f"Profile: {a.get('label') or base}" + (" (you confirmed it)" if a.get("confirmed") else " (not confirmed yet)")


# Work authorization and sponsorship in the profile are for the US. A question about somewhere else ("authorized to
# work in Canada?") isn't answered by them.
ELSEWHERE = re.compile(r"\b(canad(a|ian)|mexic(o|an)|latam|latin america|south america|central america|europe(an)?|"
                       r"\beu\b|\beea\b|\buk\b|united kingdom|britain|england|ireland|germany|france|netherlands|spain|"
                       r"portugal|poland|switzerland|sweden|india|china|japan|korea|singapore|philippines|australia|"
                       r"new zealand|brazil|argentina|colombia|chile|israel|emea|apac|outside (of )?the (u\.?s|united))",
                       re.I)
# Case matters: "US" is the country, "us" is the company asking. "America" alone is left out ("Latin America").
NAMES_US = re.compile(r"\bU\.\s?S\b\.?(\s?A\b\.?)?|\bUSA?\b|\b(?i:united states( of america)?)\b")
# Any place named after "in" ("authorized to work in South Africa?"), so a country missing from ELSEWHERE still counts
PLACE = re.compile(r"\b(?:in|within)\s+(?:the\s+)?([A-Z][\w.'’-]*(?:\s+(?:of\s+)?[A-Z][\w.'’-]*)*)")
ANY_OF = re.compile(r"\bor\b|and/or|one of|any of|either", re.I)


# "Authorized to work in the country for which you are applying?" names no country: it means the job's
JOBS_COUNTRY = re.compile(r"\b(the|this) country (for which|in which|where|to which)|country (you('re| are)|you have) "
                          r"appl|country (of|for) (this|the) (job|role|position|opening)|country (specified|listed|named|"
                          r"indicated|stated) (for|in|on) (this|the) (job|role|position|opening|posting)", re.I)


_NOT_A_PLACE = re.compile(r"\b(remote|hybrid|on-?site|in-office|flexible)\b", re.I)
_ANYWHERE = re.compile(r"\b(worldwide|global(ly)?|anywhere|international)\b", re.I)


def _names_us(loc: str) -> bool:
    """Whether a job location names only places in the US. Stricter than match._in_us, which takes plain "Remote"
    as a match: "Remote" and "Remote - Worldwide" name no country, and "Remote - US / EMEA" or "United States,
    Argentina" name more than one, so none of them can say which country a question means."""
    from .match import _in_us
    if _ANYWHERE.search(loc):
        return False
    us = {k.lower() for k in US_STATES} | {v.lower() for v in US_STATES.values()} | \
        {"us", "usa", "u.s.", "u.s.a.", "united states", "united states of america"}

    def one_place(p: str) -> bool:
        # "Boston, MA, USA": a city, then only US states or the US itself after it
        segs = [x.strip() for x in p.split(",") if x.strip()]
        return bool(segs) and _in_us(p) and all(x.lower() in us for x in segs[1:])

    for alt in re.split(r"[/|;&]|\bor\b|\band\b", loc, flags=re.I):     # alternatives: each must be in the US
        # "Remote - US", "Hybrid - Boston, MA": a work mode, then the place; "US - EMEA" names two
        pieces = [_NOT_A_PLACE.sub(" ", x).strip(" ,:()") for x in re.split(r"\s[-–—]\s", alt)]
        if not _NOT_A_PLACE.sub(" ", alt).strip(" -–—,:()"):
            return False                                  # "United States / Remote": Remote names no country
        if not all(one_place(x) for x in pieces if x):
            return False
    return True


# The whole choice, nothing added: "U.S. citizen", "A United States citizen or national". Not "Non-U.S. citizen" or
# "U.S. citizen with an active clearance".
US_CITIZEN_OPTION = re.compile(r"\W*(i am )?(an? )?(u\.?\s?s\.?(\s?a\.?)?|united states)( of america)? citizen"
                               r"( or (u\.?\s?s\.? )?national( of the (u\.?\s?s\.?|united states))?)?\W*", re.I)


def _citizen_option(options: list[str]) -> str:
    """The one choice that says "U.S. citizen" in a list of statuses (citizen, green card, refugee, none of the
    above), for someone who confirmed they are one. None when no single choice says it."""
    mine = [o for o in options if US_CITIZEN_OPTION.fullmatch(" ".join(o.split()))]
    return mine[0] if len(mine) == 1 else ""


def _place_scope(label: str, job: dict | None = None) -> str:
    """'us' (no other place named), 'any' (the US or somewhere else will do) or 'other'. A question about the job's
    own country is 'us' only when every location the posting lists is in the US."""
    if JOBS_COUNTRY.search(label):
        locs = [l for l in (job or {}).get("locations") or [] if l.strip()]
        return "us" if locs and all(_names_us(l) for l in locs) else "other"
    us = lambda p: NAMES_US.fullmatch(p) or NAMES_US.fullmatch(p.rstrip(".,")) or p in US_STATES.values()
    if not ELSEWHERE.search(label) and all(us(p) for p in PLACE.findall(label)):
        return "us"
    return "any" if NAMES_US.search(label) and ANY_OF.search(label) else "other"


NANP = {"us": "United States", "usa": "United States", "united states": "United States",
        "united states of america": "United States", "canada": "Canada", "ca": "Canada"}


def dialling_country(ans: dict) -> str:
    """The country whose dialling code your phone number has, read from the number itself, never from where you
    live: "+1 617…", or a ten-digit North American number when your confirmed country is the US or Canada (both +1).
    Any other number (another code, or no code and another country) gives "": the code is yours to pick."""
    phone = ((ans.get("phone") or {}).get("value") or "").strip()
    country = ((ans.get("country") or {}).get("value") or "").strip().lower()
    if not phone or not (ans.get("phone") or {}).get("confirmed") or not (ans.get("country") or {}).get("confirmed"):
        return ""
    digits = re.sub(r"\D", "", phone)
    if phone.startswith("+"):
        north_american = digits.startswith("1") and len(digits) == 11
    else:
        north_american = len(digits) == 10 and digits[0] in "23456789" or \
            (len(digits) == 11 and digits.startswith("1") and digits[1] in "23456789")
    return NANP.get(country, "") if north_american else ""


def dialling_option(country: str, options: list[str]) -> str:
    """The choice that is +1 for `country` (dialling_country only gives +1 countries): a bare "+1", else the one
    +1 choice whose name is that country's. Never a choice with another code, however alike the names ("United
    Kingdom"), nor another +1 place that shares words with it ("United States Minor Outlying Islands")."""
    plus1 = [o for o in options if re.search(r"\+\s*1(?!\d)", o)]
    bare = [o for o in plus1 if re.fullmatch(r"\W*\+\s*1\W*", o.strip())]
    if bare:
        return bare[0]
    same = {k for k, v in NANP.items() if v == NANP.get(country.strip().lower())}      # "United States of America"
    exact = [o for o in plus1 if re.sub(r"\(?\+\s*1\)?|[^\w\s]", " ", o).split() and
             " ".join(re.sub(r"\(?\+\s*1\)?|[^\w\s]", " ", o).split()).lower() in same]
    return exact[0] if len(exact) == 1 else ""


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
    if m := re.search(r"--(first|last)YearAttended-dateSectionYear-input", field["field"]):     # Workday
        return ("enrollment_start" if m.group(1) == "first" else "graduation_date", 1)
    if re.search(r"employ|experience|work history", field.get("group") or "", re.I):
        return None
    m = EDU_DATE_LABEL.match(field.get("label", "").strip())
    if m:
        return ("enrollment_start" if m.group(1).lower() in ("start", "enrollment") else "graduation_date",
                0 if m.group(3).lower() == "month" else 1)
    return None


# "SMS: Yes - I consent to receiving SMS text messages": whether a company may text you is yours to decide.
MESSAGING = re.compile(r"\b(sms|text messages?|texts? (from|about)|whatsapp)\b", re.I)


# A signature (Lever's "Name" and "Date" under the disability question are eeo[disabilitySignature…]): never ours.
SIGNATURE = re.compile(r"signature|\bsign (here|below)|\be-?sign\b", re.I)
# Lever's disability question: any answer, even "I do not want to answer", shows Name and Date below it and makes
# them required, a signature. Jobsmith never signs for you, so it's left blank, which discloses nothing either way.
SIGNED_ANSWER = re.compile(r"disabilitySelectElement|eeo\[disability\]")
# Your profile's disability answer says one thing: whether you have a disability. It fills only a question that asks
# exactly that. Anything else about a disability or an accommodation (a PWD card or ID, its type, help you'd need) is
# yours: never guessed from the nearest answer, and never the AI's (rule 2).
# The verb is ordinary ("how would you accommodate changing requirements?"); "accommodations" you'd need is yours.
DISABILITY_ANY = re.compile(r"disabilit|\bdisabled\b|\bpwds?\b|handicap|\baccommodations?\b", re.I)
# The question, whole: an intro ("Please indicate your") may come first, and nothing may follow but "(PWD)" or "or had
# one in the past". "Do you have a disability that requires treatment?" asks more than your answer says.
DISABILITY_INTRO = re.compile(r"^(please )?(indicate|select|state|choose|provide|specify|tell us|share)( your)?\s+|"
                              r"^what is your\s+")
DISABILITY_STATUS = re.compile(
    r"^(disability( status)?|disabled|pwd|(voluntary )?self[- ]identification of disability( form)?|"
    r"(do|did) you (currently )?(have|had) (a |any )?disabilit(y|ies)|"
    r"(are you|i am) (a )?(pwd|disabled|(person|individual) with (a )?disabilit(y|ies))|"
    r"(do you )?(identify as|consider yourself)( to be| to have)? (a |having a )?"
    r"(disabled|disability|(person|individual) with (a )?disabilit(y|ies))( person)?)"
    r"(\s*\(pwds?\))?(,? or (have |had |have had )?(had )?(one|a disability)( in the past)?|"
    r",? or (a )?(history|record) of (having )?(one|a disability))?$")


def _disability_detail(label: str) -> bool:
    """A question about a disability, or help for one, that isn't "do you have one" (see above)."""
    l = " ".join((label or "").split()).lower().strip(" *?:.")
    if not DISABILITY_ANY.search(l):
        return False
    rest = DISABILITY_INTRO.sub("", l, count=1)
    # after an intro, only "disability status": "Please specify your disability" asks which one
    if rest != l and not rest.startswith("disability status"):
        return True
    return not DISABILITY_STATUS.search(rest)


# Questions only your confirmed profile may answer (rule 2): work authorization, citizenship, export control,
# clearance and demographics. One Jobsmith can't map to your profile is left for you, never given to AI or filled
# with an answer you approved for another job.
PROFILE_ONLY = re.compile(r"citizen|nationality|\bnational of\b|export (control|compliance|regulat|law|administration)|"
                          r"sanction|embargo|\bitar\b|\bear\b|part 810|"
                          r"clearance|authori[sz]\w* to work|work authori|\bvisas?\b|sponsor|immigration|green card|"
                          r"work permit|right to work|eligib\w* to work|legally (able|allowed|permitted) to work|"
                          r"national origin|country of (birth|origin)|place of birth|permission to work|"
                          r"non-?binary|cisgender|\bblack\b|african american|\basian\b|pacific islander|"
                          r"alaska native|native american|indigenous|"
                          r"permanent resident|asyl|refugee|\brac(e|ial)\b|\bethnic(ity)?\b|transgender|gender|sexual orientation|"
                          r"lgbt|veteran|disabilit|hispanic|latin[aox]|pronoun", re.I)
PROFILE_ONLY_OPTION = re.compile(r"citizen|green card|permanent resident|u\.?s\.? person|^\W*(i am an? )?(wo)?m[ae]n\b|"
                                 r"^\W*(i am )?(fe)?male\b|non-?binary|"
                                 r"veteran|disabilit|hispanic|latin[aox]|african american|\basian\b|\bwhite\b|"
                                 r"pacific islander|alaska native|transgender|cisgender", re.I)
# The profile keys and classifier answers that put a question under rule 2, whatever its wording
RULE2_CANONS = {"work_authorized_us", "needs_sponsorship", "us_citizen", "us_person", "citizenship_status",
                "other_citizenship", "export_license", "security_clearance", "citizenships", "work_authorized_other",
                *profile.EEO_KEYS}


# Rule 2, as one rule: a question on any of these topics gets your confirmed profile answer only when it is a plain
# Yes/No question about exactly that fact. Anything else waits for you. "Plain" is decided by an allowlist, so an
# unfamiliar word ("ever required", "denied", "explain", "Canada", "without") means it waits rather than guesses.
_ASKING = "are you do will please confirm indicate whether currently a an the to of in for at this that any position role job"
_US = "us u s usa united states america"
# "...in the country for which you are applying?": the job's own country, which counts only when every place the
# posting lists is in the US (see _plain_yes_no)
_JOBS_COUNTRY = "country which where applying applied located based specified"
PLAIN_YES_NO = {
    "work_authorized_us": f"{_ASKING} {_US} {_JOBS_COUNTRY} legally lawfully authorized authorised eligible "
                          "permitted have lawful "
                          "work authorization authorisation employer",
    "needs_sponsorship": f"{_ASKING} {_US} {_JOBS_COUNTRY} now or ever future point time later date require need "
                         "sponsorship sponsor "
                         "visa immigration employment work status maintain obtain authorization would legally "
                         "continue continued working in order our company from by with type employer etc "
                         "e g i h 1b h1 h1b b tn o 1 j f 3 stem opt cpt",
    "us_citizen": f"{_ASKING} {_US} citizen",
    "hispanic_latino": f"{_ASKING} identify as hispanic latino latina latinx or origin",
    "veteran_status": f"{_ASKING} veteran",
    "disability_status": f"{_ASKING} have disability status your",
    "first_gen": f"{_ASKING} first generation college student",
}
PLAIN_YES_NO = {k: set(v.split()) for k, v in PLAIN_YES_NO.items()}
# ...and it must name the fact itself: "working in the US with a visa?" uses sponsorship's words but asks another thing
PLAIN_CORE = {"work_authorized_us": [{"authorized", "authorised", "eligible", "authorization", "authorisation"}],
              "needs_sponsorship": [{"require", "need"}, {"sponsorship", "sponsor"}],
              "us_citizen": [{"citizen"}], "hispanic_latino": [{"hispanic", "latino", "latina", "latinx"}],
              "veteran_status": [{"veteran"}], "disability_status": [{"disability"}],
              "first_gen": [{"first"}, {"generation"}]}
# ...or a pick from a list, when the label is plainly that one fact and exactly one choice means your confirmed
# answer (classify.strict_pick): "Gender" with Man/Woman for "Male", never "Cisgender man", never the nearest match.
_WHICH = f"{_ASKING} what is your my i identify as how would you describe which best describes select one option status"
_EXPORT = (f"{_ASKING} {_US} position requires require may access information technology items subject export "
           "control controls laws law regulations regulation ear itar international traffic arms such as following "
           "one protected individuals individual person persons defined under immigration naturalization nationality act "
           "8 usc c 1324b 3 and purposes complying comply federal best applies you your citizenship status citizen is what")
PLAIN_PICK = {
    "gender": f"{_WHICH} gender identity sex",
    "race": f"{_WHICH} race ethnicity racial ethnic background origin group category",
    "hispanic_latino": f"{_WHICH} hispanic latino latina latinx or origin",
    "veteran_status": f"{_WHICH} veteran protected",
    "disability_status": f"{_WHICH} have disability",
    "security_clearance": f"{_WHICH} have hold security clearance level highest current active and",
    "us_person": _EXPORT, "us_citizen": _EXPORT, "citizenship_status": _EXPORT,
}
PLAIN_PICK = {k: set(v.split()) for k, v in PLAIN_PICK.items()}
PICK_CORE = {"gender": [{"gender", "sex"}], "race": [{"race", "ethnicity", "racial", "ethnic"}],
             "hispanic_latino": [{"hispanic", "latino", "latina", "latinx"}], "veteran_status": [{"veteran"}],
             "disability_status": [{"disability"}], "security_clearance": [{"clearance"}],
             "us_person": [{"export", "itar", "ear", "person"}], "us_citizen": [{"citizen"}],
             "citizenship_status": [{"citizenship"}]}
CITIZEN_LISTS = {"us_person", "us_citizen", "citizenship_status"}
US_ONLY = {"work_authorized_us", "needs_sponsorship"}      # your profile answers these for the US
# Your "Yes, I need sponsorship" means now or later, for whichever visa: a question about only now, or about one
# visa type, may have another answer, so a Yes answers only one that asks about the future and names no visa
LATER = {"future", "ever", "later", "point", "time", "will", "would"}
VISA_TYPES = {"h", "1b", "h1", "h1b", "tn", "o", "1", "j", "f", "e", "3", "stem", "opt", "cpt"}
_PLACEHOLDER = re.compile(r"^\W*((please )?(select|choose)\b.*)?$", re.I)


def _profile_only(field: dict) -> bool:
    return bool(PROFILE_ONLY.search(f"{field.get('label') or ''} {field.get('description') or ''}") or
                any(PROFILE_ONLY_OPTION.search(o) for o in field.get("options") or []) or
                classify.canon_for(field.get("label") or "") in RULE2_CANONS)


def _plain_yes_no(field: dict, ans: dict, job: dict | None) -> dict | None:
    """Your confirmed Yes or No, when the field offers exactly Yes and No, uses only the plain words for one fact,
    and (for work authorization and sponsorship) is about the US. None in every other case."""
    canon = classify.canon_for(field["label"])
    company = " ".join(re.findall(r"[a-z0-9]+", ((job or {}).get("company") or "").lower()))

    def words(text: str) -> set[str]:
        t = " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))
        if company:          # "for Affirm", "at Graham Capital": the whole name, only where a company goes
            t = re.sub(rf"\b(for|at|with|by|from|join) {re.escape(company)}\b", r"\1", t)
        return set(t.split())
    asked = words(field["label"])
    if canon not in PLAIN_YES_NO or not asked or not all(asked & core for core in PLAIN_CORE[canon]):
        return None
    if (asked | words(field.get("description") or "")) - PLAIN_YES_NO[canon]:       # a note under it counts too
        return None
    if field["qtype"] not in ("select", "radio", "listbox"):       # one choice from a list
        return None
    options = {o.strip(" .").lower(): o for o in field.get("options") or [] if not _PLACEHOLDER.match(o)}
    if set(options) != {"yes", "no"}:
        return None
    row = ans.get(canon) or {}
    value = (row.get("value") or "").strip().lower()
    if value not in ("yes", "no") or not row.get("confirmed"):
        return None
    if canon == "needs_sponsorship" and value == "yes" and (not asked & LATER or asked & VISA_TYPES):
        return None
    if canon in US_ONLY and not NAMES_US.search(field["label"]):
        # names no country: it means the job's, which is the US only when every place the posting lists is
        locs = [l for l in (job or {}).get("locations") or [] if l.strip()]
        if not locs or not all(_names_us(l) for l in locs):
            return None
    return {"kind": "answer_bank", "canon": canon, "answer": options[value], "confidence": 1.0, "issues": [],
            "rationale": source_line(canon, ans, job, field["label"]) or f"Profile: {row.get('label') or canon}"}


def _plain_pick(field: dict, ans: dict, job: dict | None) -> dict | None:
    """Your confirmed answer, picked from a list, when the label is plainly that one fact and exactly one choice
    means it. A list of statuses under an export-control question gets "U.S. citizen" only from a confirmed Yes."""
    canon = classify.canon_for(field["label"])
    asked = set(re.findall(r"[a-z0-9]+", f"{field['label']} {field.get('description') or ''}".lower()))
    if canon not in PLAIN_PICK or not all(asked & core for core in PICK_CORE[canon]) or asked - PLAIN_PICK[canon]:
        return None
    options = [o for o in field.get("options") or [] if not _PLACEHOLDER.match(o)]
    if field["qtype"] not in ("select", "radio", "listbox", "multiselect") or not options:
        return None
    row = ans.get("us_citizen" if canon in CITIZEN_LISTS else canon) or {}
    value = (row.get("value") or "").strip()
    if not value or not row.get("confirmed"):
        return None
    if canon in CITIZEN_LISTS:
        out = _citizen_option(options) if value.lower() == "yes" else ""
    else:
        h = ans.get("hispanic_latino") or {}
        out = classify.strict_pick(value, options, not_hispanic=bool(h.get("confirmed")) and
                                   (h.get("value") or "").strip().lower() == "no") or ""
    if not out:
        return None
    return {"kind": "answer_bank", "canon": canon, "answer": out, "confidence": 1.0, "issues": [],
            "rationale": source_line(canon, ans, job, field["label"]) or f"Profile: {row.get('label') or canon}"}


def _yours_to_answer(field: dict, canon: str | None) -> dict:
    """A rule-2 question that isn't a plain Yes/No about one fact in your confirmed profile: left for you."""
    return {"kind": "answer_bank", "canon": canon, "answer": "", "confidence": 0.0 if field["required"] else 1.0,
            "issues": ["Only you can answer this one (work authorization, citizenship or a voluntary question); "
                       "answer it yourself"] if field["required"] else [],
            "rationale": "Left for you: Jobsmith answers these only with your confirmed Yes or No to a plain question"}


def deterministic(field: dict, ans: dict, job: dict | None = None) -> dict | None:
    """The answer from your profile alone, or None when AI (or a saved answer) may write it."""
    got = _deterministic(field, ans, job)
    if not _profile_only(field):
        return got
    if field["qtype"] == "file":             # "Cover letter explaining your visa status": never AI's to write
        return dict(_yours_to_answer(field, None), kind="file")
    if got is not None and not (got.get("answer") or "").strip() and not got.get("no_option"):
        return got          # already left for you, with its own reason (a signature, a place outside the US)
    return _plain_yes_no(field, ans, job) or _plain_pick(field, ans, job) or \
        (got if got and got.get("no_option") else _yours_to_answer(field, classify.canon_for(field["label"])))


# A password or PIN (a sign-in's, or the one to your portfolio) is never Jobsmith's to type (rule 5). Any "PIN" is
# taken for one, even India's postal "PIN code": when in doubt, it waits for you.
PASSWORD = re.compile(r"\bpass(word|wd|code|phrase)s?\b|\bpin\b", re.I)
PASSWORD_NAME = re.compile(r"pass(word|wd)|(^|[\s#_-])pwd($|\s)", re.I)


def _deterministic(field: dict, ans: dict, job: dict | None = None) -> dict | None:
    where = f"{field['field']} {field.get('name') or ''}"       # the extension's ids are its own; name is the page's
    if PASSWORD.search(field["label"]) or PASSWORD_NAME.search(where):
        return {"kind": "answer_bank", "canon": None, "answer": "", "confidence": 0.0 if field["required"] else 1.0,
                "issues": ["Asks for a password; Jobsmith never types passwords, so enter it yourself"]
                if field["required"] else [], "rationale": "A password: left for you"}
    if SIGNATURE.search(f"{where} {field['label']}"):
        return {"kind": "answer_bank", "canon": None, "answer": "", "confidence": 0.0 if field["required"] else 1.0,
                "issues": ["Asks for your signature; Jobsmith never signs for you, so sign it yourself"]
                if field["required"] else [], "rationale": "A signature: left for you"}
    if SIGNED_ANSWER.search(where):
        return {"kind": "answer_bank", "canon": "disability_status", "answer": "", "confidence": 1.0, "issues": [],
                "rationale": "Left blank: Lever asks you to sign any answer here (your name and the date), and Jobsmith "
                             "never signs for you. To answer it, pick yours on the form and sign it yourself"}
    if field["qtype"] in ("radio", "checkbox", "select", "multiselect") and \
            MESSAGING.search(" ".join([field["label"], *(field.get("options") or [])])):
        return {"kind": "answer_bank", "canon": None, "answer": "", "confidence": 0.0 if field["required"] else 1.0,
                "issues": ["Asks whether they may text you; answer it yourself"] if field["required"] else [],
                "rationale": "Whether they may text you is your call; left for you"}
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
    if field["qtype"] != "file" and canon in ("disability_status", None) and _disability_detail(field["label"]):
        return {"kind": "answer_bank", "canon": None, "answer": "", "confidence": 0.0 if field["required"] else 1.0,
                "issues": ["Asks about your disability beyond whether you have one; answer it yourself"]
                if field["required"] else [],
                "rationale": "About your disability beyond your profile's answer: left for you"}
    if not canon or canon in ("resume", "cover_letter"):
        return None
    if canon == "phone_extension":
        # Your profile has no extension, and nothing but digits ever goes in one (a "+1" there made Workday's phone
        # "x+1"): left blank, as you would
        need = ["Asks for a phone extension, and your profile has none; fill it in yourself"] if field["required"] else []
        return {"kind": "answer_bank", "canon": canon, "answer": "", "confidence": 0.0 if need else 1.0, "issues": need,
                "rationale": "A phone extension: your profile has none, so it's left blank"}
    if canon == "phone_country_code" and field["qtype"] in ("select", "listbox", "radio"):
        country = dialling_country(ans)
        # a list: the +1 choice for your country; a search box (no list yet): the country with its code, so the
        # filler picks only a +1 choice
        out = "" if not country else dialling_option(country, field["options"]) if field["options"] else f"{country} (+1)"
        why = ("Your phone number doesn't say its country code" if not country else
               "None of the choices is your phone number's code (+1)")
        return {"kind": "answer_bank", "canon": canon, "answer": out, "confidence": 1.0 if out else 0.0,
                "issues": [f"{why}; pick it yourself"] if field["required"] and not out else [],
                "rationale": "From your phone number's country code" if out else f"{why}, so it's left for you"}
    if canon == "phone_country_code":
        # A typed dialling code box: left as the site set it. A list of countries is answered from your country.
        return {"kind": "answer_bank", "canon": canon, "answer": "", "confidence": 1.0, "issues": [],
                "rationale": "A dialling code box: left as the site set it"}
    if canon in ("other_citizenship", "export_license"):
        # Your profile answers for the US; another country's citizenship, or whether you need an export licence,
        # is yours to say
        return _yours_to_answer(field, canon)
    if canon == "high_school":
        # Your profile is about college and work; a high school's name or year would be a guess, AI's or ours
        return {"kind": "answer_bank", "canon": canon, "answer": "", "confidence": 0.0 if field["required"] else 1.0,
                "issues": ["Asks about your high school, which your profile doesn't cover; answer it yourself"]
                if field["required"] else [],
                "rationale": "About your high school: left for you"}
    if canon == "previously_employed":
        value, confirmed = _worked_here(job or {}, ans, field["label"])[0], True
    else:
        value, confirmed = _derived(canon, ans, job)
    if canon in ("work_authorized_us", "needs_sponsorship"):
        scope = _place_scope(field["label"], job)
        # "Authorized in the US, Canada or LATAM?": your US "Yes" answers it; a US "No" or a US sponsorship need doesn't
        if scope == "other" or (scope == "any" and not (canon == "work_authorized_us" and value.lower() == "yes")):
            why = ("Asks about the country of this job, which isn't (or isn't only) the US; your profile answers for "
                   "the US, so answer it yourself") if JOBS_COUNTRY.search(field["label"]) else \
                  "Asks about working somewhere other than the US; your profile answers for the US, so answer it yourself"
            return {"kind": "answer_bank", "canon": canon, "answer": "", "confidence": 0.0,
                    "issues": [why] if field["required"] else []}
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
    no_option = False            # your answer isn't among the choices as written: a stricter pick may still find it
    if field["options"] and value:
        out = classify.pick_option(value, field["options"]) or ""
        if not out:
            if not sensitive:
                return None
            issues.append(f"Your answer '{value}' doesn't match any option here; pick one")
            no_option = True
    if not value:
        if canon == "previously_employed":
            # confirming your resume lists every employer answers it only for this job's own company, not its
            # subsidiaries or another one (the U.S. Government): offered only then
            company, _, own = _asked_company(job or {}, field["label"])
            helps = own and company and not GROUP.search(field["label"] or "")
            issues.append(f"Your resume doesn't say whether you've worked for {company or 'them'}. Answer it yourself"
                          + (", or confirm on your Profile page that your resume lists every employer and contract "
                             "you've had" if helps else ""))
        elif field["required"]:
            issues.append("Add this to your answers on the Profile page" if canon not in profile.EEO_KEYS
                          else "Set your demographic answers on the Profile page (or 'Decline to self-identify')")
    elif not confirmed:
        issues.append("Read from your resume; confirm it on the Profile page")
    out_row = {"kind": "answer_bank", "canon": canon, "answer": out,
               "confidence": 1.0 if (out and confirmed) else 0.5 if out else 0.0, "issues": issues}
    if canon in LEGAL_YES_NO and out:
        out_row["rationale"] = source_line(canon, ans, job, field["label"])
    if no_option:
        out_row["no_option"] = True
    return out_row


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


async def draft_job(job_id: str, research: bool | None = None, log=None, hold_first: bool = False) -> dict:
    """Draft every answer on this application's form. hold_first (autopilot): answer what needs no AI first, and if
    that already holds the application for you, hold it there: no research, no AI. Answers AI wrote on an earlier
    pass are kept then, not paid for again."""
    log = log or (lambda m: None)
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    if not job["questions"] and not job["description"]:
        job = await jobdetail.fetch_job(job_id)
    elif questions_stale(job):
        job = await refresh_questions(job_id, log)
    fields = [f for f in (job["questions"] or default_fields(job)) if f["qtype"] != "hidden"]
    for f in fields:
        f.setdefault("options", [])
        f.setdefault("required", False)
    if hold_first:
        mine, _ = await answer_fields(job, fields, use_ai=False, keep_written=True)
        rows = [dict(r, field=f["field"], label=f["label"], qtype=f["qtype"], required=int(bool(f.get("required"))),
                     options=f.get("options") or []) for f in fields if (r := mine.get(f["field"]))]
        held = [b["text"] for r in rows if (b := _blocker(r, job, profile.answers())) and not b.get("pending")]
        if held:
            save_results(job_id, fields, mine)
            db.x("UPDATE jobs SET status='filled', error=NULL, hold_reason=?, updated_at=? WHERE id=?",
                 ("; ".join(held[:3])[:500], db.now(), job_id))
            log("Held for you before any AI was used: " + "; ".join(held[:3]))
            return {"job_id": job_id, "drafted": len(mine), "error": None, "held": held}
    settings = db.get_settings()
    if research is None:
        research = settings.get("research_enabled", True)
    # Research only feeds written answers: none to write, none paid for
    essays_left = [f for f in fields if essays.is_essay(f) and offline(f, profile.answers(), job) is None]
    if research and not job.get("research") and essays_left and not llm.out_of_ai():
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
    results, gen_error = await answer_fields(job, fields, keep_written=hold_first)
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


def ai_writes_optional() -> bool:
    """Settings, "Let AI write optional essays" (off by default): optional essay boxes you have no saved answer for
    are then written by AI, against your daily budget, and left blank whenever it can't or isn't sure."""
    return bool(db.get_setting("ai_optional_essays"))


def offline(field: dict, ans: dict, job: dict, blank_optional: bool | None = None) -> dict | None:
    """The answer to one field without AI, or None when only AI (or you) could write it: your profile, your saved
    answer to this kind of essay (an optional essay box with none is left blank, unless you let AI write those), or
    an answer you approved before. blank_optional=None follows that setting."""
    if blank_optional is None:
        blank_optional = not ai_writes_optional()
    det = deterministic(field, ans, job)
    if det:
        return det
    if essays.is_essay(field):
        mine = essays.answer_for(field, job)
        if mine:
            return mine
        if blank_optional and not field.get("required"):
            return essays.left_blank(field)
    if field["qtype"] != "file":
        reuse = learn.reusable_answer(field["label"], field["qtype"], field["options"])
        if reuse:
            return {"kind": "learned", "answer": reuse["answer"], "confidence": min(1.0, 0.6 + 0.1 * reuse["support"]),
                    "rationale": f"Reused your approved answer ({reuse['from']})", "issues": []}
    return None


NO_AI_ISSUES = ("Needs your AI connected", "Your AI couldn't write this")


def _no_ai_issue(e: Exception) -> str:
    """Why AI wrote nothing, in the answer's own "Needs you" line: no AI connected at all, or what your AI said (a
    key that isn't valid, a model that doesn't exist), so you fix the right thing."""
    if isinstance(llm.backend("write"), llm.NoLLM):
        return "Needs your AI connected (Settings), or more of your writing (Voice), then Redraft"
    return f"Your AI couldn't write this: {str(e).rstrip('.')[:160]}. Fix it in Settings, then Redraft"


def pending(field: dict) -> dict:
    return {"kind": "pending", "answer": "", "confidence": 0, "issues": [PENDING_ISSUE]}


async def answer_fields(job: dict, fields: list[dict], skip_locked: bool = True, use_ai: bool = True,
                        keep_written: bool = False, blank_optional: bool | None = None) -> tuple[dict[str, dict], str | None]:
    """Answer form fields: your profile first, then your saved and approved answers, then one AI call for the rest.
    use_ai=False leaves the rest pending (no AI spent). keep_written keeps what AI wrote on an earlier pass instead
    of paying for it again. A free limit or your daily budget running out leaves them pending too, to be written
    when there's room: the application waits quietly instead of being held for you. blank_optional=False when you
    asked for this answer yourself ("Write with Jobsmith", a cover letter): an optional essay is written then.
    None follows Settings: optional essays are left blank, or, if you let AI write them, written when there's AI to
    spare and left blank when there isn't or the answer isn't sure enough to send. Never held, never waited for."""
    optional_by_ai = blank_optional is None and ai_writes_optional()
    if blank_optional is None:
        blank_optional = not optional_by_ai
    existing = {d["field"]: db.decode(d) for d in db.q("SELECT * FROM drafts WHERE job_id=?", (job["id"],))}
    ans = profile.answers()
    results: dict[str, dict] = {}
    to_generate: list[dict] = []
    # optional essays AI may write (the switch on): whatever answers them, if it can't be sent as it is, is left
    # blank, never held. Your saved answer is the exception: it's yours, so a failed check holds it for you.
    optional = {f["field"] for f in fields if optional_by_ai and not f.get("required") and essays.is_essay(f)}
    for f in fields:
        f.setdefault("options", [])
        f.setdefault("required", False)
        prev = existing.get(f["field"])
        if skip_locked and prev and is_locked(prev):
            continue  # locked by the user
        mine = offline(f, ans, job, blank_optional)
        if mine:
            results[f["field"]] = mine
            continue
        if keep_written and prev and prev["kind"] in AI_MADE and (prev["answer"] or "").strip():
            if f["field"] in optional and (why := _unsure(prev, f, job, ans)):
                results[f["field"]] = _optional_blank(f, why)
            continue  # written already: kept, not paid for again
        if f["qtype"] == "file":  # cover letter upload -> generate text, attached as a file when filling
            if "cover" in (f["label"] + f["field"]).lower():
                to_generate.append(dict(f, qtype="textarea", description="Cover letter, under 250 words."))
        else:
            to_generate.append(dict(f, qtype="select" if f["qtype"] == "listbox" else f["qtype"]))
    if use_ai and any(f["field"] in optional for f in to_generate) and llm.out_of_ai():
        for f in [f for f in to_generate if f["field"] in optional]:   # no AI to spare today: blank, not waited for
            results[f["field"]] = _optional_blank(f, "no AI left today")
        to_generate = [f for f in to_generate if f["field"] not in optional]
    gen_error = None
    if to_generate and use_ai:
        try:
            results.update(await generate(job, to_generate))
        except (QuotaError, BusyError) as e:   # today's budget, a free limit, or a busy AI: written later, not held
            gen_error = str(e)
            for f in to_generate:
                results[f["field"]] = pending(f)
        except LLMError as e:
            gen_error = str(e)
            for f in to_generate:
                results[f["field"]] = {"kind": "generated", "answer": "", "confidence": 0,
                                       "issues": [_no_ai_issue(e)]}
    else:
        for f in to_generate:
            results[f["field"]] = pending(f)
    # No AI, the free limit ran out, or the AI came back empty: answer from your own writing instead.
    for f in to_generate:
        r = results.get(f["field"]) or {}
        if f["qtype"] in ("textarea", "text") and not f["options"] and not (r.get("answer") or "").strip() and \
                (use_ai or r.get("kind") != "pending"):
            mine = voice.compose(job, f)
            if mine:
                results[f["field"]] = mine
    by_field = {f["field"]: f for f in fields}
    out = {k: _checked(by_field[k], r, job) if k in by_field else r for k, r in results.items()}
    for k in optional & out.keys():
        if out[k].get("kind") == "pending" and not use_ai:
            continue                                  # AI's turn comes next (autopilot answers what needs none first)
        if out[k].get("kind") != "saved" and (why := _unsure(out[k], by_field[k], job, ans)):
            out[k] = _optional_blank(by_field[k], why)
    return out, gen_error


def _unsure(r: dict, field: dict, job: dict, ans: dict) -> str | None:
    """Why an answer to an optional essay can't be sent as it is, or None: it's left blank rather than held. Every
    answer gets this box's checks, whenever it was written: your writing or an answer you approved elsewhere is
    checked like your saved answers (numbers, this box's limit), and each fits the question (`_checked`). Then the
    same question readiness asks (`_blocker`), so whatever would hold the application blanks the box instead."""
    if r.get("kind") == "left_blank":
        return None
    if not (r.get("answer") or "").strip():
        return "AI couldn't write it"
    if r.get("kind") in ("voice", "learned"):
        r = dict(r, issues=list(r.get("issues") or []) + essays.checks(field, r["answer"], job))
    r = _checked(field, r, job)
    if r.get("issues") or r.get("held"):
        return "the answer didn't pass the checks"
    d = dict(r, field=field["field"], label=field.get("label", ""), qtype=field.get("qtype", "textarea"),
             options=field.get("options") or [], required=False)
    if _blocker(d, job, ans):
        return "it wasn't sure enough to send"
    return None


def _optional_blank(field: dict, why: str) -> dict:
    return dict(essays.left_blank(field), rationale=f"Optional, so it's left blank: {why}")


def refresh_offline(job_id: str | None = None, *, job: dict | None = None) -> int:
    """Answer again, without AI, every field of this application that isn't yours (approved or rewritten) and isn't
    AI's finished work: after you answer something in Needs you, your new profile facts and saved answers reach
    every held form at once. Returns how many answers changed."""
    job = job or db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,)))
    ans = profile.answers()
    changed, fields, results = 0, [], {}
    # the form's own words beside each box (a "50 words max" in its help text): checked again, never dropped
    asked = {q.get("field"): q for q in job.get("questions") or []}
    for d in drafts_for(job["id"]):
        if is_locked(d) or (d["kind"] in AI_MADE and (d["answer"] or "").strip() and not d["issues"]):
            continue
        q = asked.get(d["field"]) or {}
        f = {"field": d["field"], "label": d["label"], "qtype": d["qtype"], "required": bool(d["required"]),
             "options": d["options"] or [], "description": q.get("description") or "",
             "section": q.get("section") or "main"}
        r = offline(f, ans, job)
        if r is None:
            continue
        r = _checked(f, r, job)
        if (r.get("answer") or "") != (d["answer"] or "") or r.get("issues", []) != (d["issues"] or []) or \
                r["kind"] != d["kind"]:
            fields.append(f)
            results[f["field"]] = r
            changed += 1
    if results:
        save_results(job["id"], fields, results)
    return changed


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


def _blocker(d: dict, job: dict, ans: dict, autopilot: bool | None = None) -> dict | None:
    """Why this one answer keeps the application from being sent on its own, or None. `pending` marks an answer AI
    will write once it's available: the application waits for AI, not for you."""
    if autopilot is None:
        autopilot = db.get_setting("autonomy") in ("autopilot", "autonomous")
    threshold = int(db.get_setting("trust_threshold") or 3)
    min_conf = float(db.get_setting("autopilot_min_confidence") or 0.7)
    norm = lambda v: " ".join((v or "").lower().split())
    val = final_value(d) or ""
    issues = d.get("issues") or []
    item = lambda issue, **kw: {"field": d.get("field"), "label": d["label"], "canon": d.get("canon"),
                                "kind": d.get("kind"), "qtype": d.get("qtype"), "options": d.get("options") or [],
                                "required": bool(d.get("required")), "draft_id": d.get("id"), "issue": issue,
                                "text": f"{d['label']}: {issue}", **kw}
    if d.get("verdict") == "red":
        return item("you red-flagged this")
    if d.get("kind") == "pending" and not val:
        return item(PENDING_ISSUE, pending=True)
    if d.get("required") and not val and d["qtype"] != "file":
        # your own reason when there is one: a profile answer to add, or why your AI couldn't write it
        says = issues and (d.get("kind") == "answer_bank" or issues[0].startswith(NO_AI_ISSUES))
        return item(issues[0] if says else "required and empty")
    if d.get("verdict") == "green" or d.get("final_answer"):
        return None
    if val and (d.get("canon") in LEGAL_YES_NO and d.get("kind") == "answer_bank" or
                _profile_only(dict(d, description=description_of(job, d.get("field"))))):
        # Drafted earlier (an old blanket "No" for "worked here before?", a profile answer you've changed since, or
        # an answer AI wrote to a rule-2 question before it was kept from AI): only sent if your profile and resume
        # give the same answer today.
        now = deterministic(dict(d, required=bool(d.get("required"))), ans, job)
        if now is None or norm(now.get("answer")) != norm(val) or now.get("issues"):
            return item("your profile doesn't give this answer now; check it")
    if not d.get("required") and not val and d.get("kind") in ("answer_bank", "left_blank") and \
            d.get("canon") != "previously_employed":
        return None  # optional (e.g. EEO, an optional essay) left blank on purpose; "worked here before?" waits either way
    if issues:
        return item(issues[0])
    if d.get("kind") in AI_MADE and ((d.get("confidence") or 0) < min_conf or not val.strip()) and \
            learn.trust_for(d["label"]) < threshold:
        who = "Your-writing match" if d["kind"] == "voice" else "AI"
        return item(f"{who} wasn't sure ({round((d.get('confidence') or 0) * 100)}% confident)")
    if d.get("kind") == "learned" and (d.get("confidence") or 0) < (0.6 if autopilot else 0.8):
        return item("reused answer has little support yet")
    return None


_BY_NAME = re.compile(r'^\[name="(.+)"\]$')


def twin_key(field: str) -> str:
    """A form's one question can be read as two boxes: "question_1" (the posting's API) and "#question_1" (the live
    page), or "question_2[]" and '[name="question_2[]"]' (a checkbox list). The same key for both."""
    f = (field or "").lstrip("#")
    m = _BY_NAME.match(f)
    return m.group(1) if m else f


def description_of(job: dict | None, field: str | None) -> str:
    """The note under a question, from the posting's saved questions (draft rows don't keep it)."""
    key = twin_key(field or "")
    return next((q.get("description") or "" for q in (job or {}).get("questions") or []
                 if twin_key(q.get("field") or "") == key), "")


def readiness(job_id: str) -> dict:
    """Can this job be auto-submitted? Every field must be trusted and issue-free. `items` says why not, one per
    answer; `only_ai` means all that's left is for AI to write (nothing waits on you)."""
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (job_id,))) or {}
    ans = profile.answers()
    autopilot = db.get_setting("autonomy") in ("autopilot", "autonomous")
    items, at = [], {}
    for d in drafts_for(job_id):                  # one per question, the one that needs you over one waiting for AI
        if not (b := _blocker(d, job, ans, autopilot)):
            continue
        key = twin_key(d["field"])
        if key not in at:
            at[key] = len(items)
            items.append(b)
        elif items[at[key]].get("pending") and not b.get("pending"):
            items[at[key]] = b
    return {"ready": not items, "blockers": [b["text"] for b in items], "items": items,
            "only_ai": bool(items) and all(b.get("pending") for b in items)}
