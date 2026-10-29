"""Map form questions to canonical answer-bank keys and choose select options deterministically."""
from __future__ import annotations

import re

# Order matters: first match wins.
RULES: list[tuple[str, str]] = [
    (r"preferred (first )?name|nickname", "preferred_name"),
    (r"^first name|^legal first name|given name", "first_name"),
    (r"^last name|^legal last name|surname|family name", "last_name"),
    (r"^full name|^name$|^your name", "full_name"),
    (r"(school|university|college|\.edu|student) e-?mail", "school_email"),
    (r"e-?mail", "email"),
    (r"phone|mobile", "phone"),
    (r"^resume|^cv\b|resume/cv", "resume"),
    (r"cover letter", "cover_letter"),
    (r"linkedin", "linkedin"),
    (r"github", "github"),
    (r"devpost", "devpost"),
    (r"other links|additional links|any other (links|urls)|links? to (your )?(work|projects)", "other_links"),
    (r"website|portfolio|personal (site|url)", "website"),
    (r"pronunciation|pronounce", "name_pronunciation"),
    (r"current (company|employer)|most recent (company|employer)|current organi[sz]ation", "current_company"),
    (r"which (u\.?s\.? )?state|state (or|/) ?(canadian )?province|state of residence|province.*reside|"
     r"state.*(reside|live)|^state$", "state"),
    (r"u\.?s\.? person|export control|\bitar\b|\bear\b regulations|deemed export|international traffic in arms", "us_person"),
    (r"citizenship status|status of (your )?citizenship|^citizenship$|what is your citizenship", "citizenship_status"),
    (r"sponsor|visa", "needs_sponsorship"),
    (r"authori[sz]ed to work|eligible to work|legally (able|permitted|authori)|right to work", "work_authorized_us"),
    (r"u\.?s\.? citizen|citizenship", "us_citizen"),
    (r"(confirm|acknowledge)( receipt)?.*(notice|polic|agreement|statement|terms)|privacy notice|\bccpa\b|\bgdpr\b|"
     r"arbitration agreement|i (have read|acknowledge|agree|consent|certify)|acknowledge,? (confirm|and)|"
     r"(agree|consent) to the (following|above)|by (checking|selecting|submitting)", "acknowledge_notices"),
    (r"ai[- ]assisted|ai (tools?|note[- ]?tak|transcri)|(record|transcri)\w* (of )?(the |your )?interview|"
     r"may use ai", "ai_tools_consent"),
    (r"security clearance|clearance level|active clearance|hold a clearance", "security_clearance"),
    (r"(list|any|relevant|professional)\s+certifications?|certifications? (do you|you) (hold|have)|^certifications?$", "certifications"),
    (r"professional licen[cs]e|licen[cs]ed (engineer|professional)|\b(pe|eit|fe) licen[cs]e", "licenses"),
    (r"languages? (do you|you) speak|language proficiency|fluent in|^languages?$", "languages"),
    (r"how many years of (professional |work |relevant )?experience|years of (professional |work )?experience do you", "years_experience"),
    (r"hispanic|latin[oa]", "hispanic_latino"),
    (r"lgbt|sexual orientation", "lgbtq"),
    (r"first[- ]generation", "first_gen"),
    (r"\bgender\b|\bsex\b", "gender"),
    (r"\brace\b|ethnicity", "race"),
    (r"veteran", "veteran_status"),
    (r"disabilit", "disability_status"),
    (r"pronoun", "pronouns"),
    (r"\bgpa\b|grade point", "gpa"),
    (r"\bminor\b", "minor"),
    (r"concentration|threads?\b|specialization|\btrack\b|focus area", "concentration"),
    (r"class standing|year in school|current (academic )?year|class level|academic (standing|level)", "class_standing"),
    (r"(start|begin|enroll)(ed|ment)? (date )?(of|at|in) (your )?(degree|program|school|university|education)|"
     r"enrollment (start|date)", "enrollment_start"),
    (r"graduation (year)|year of graduation|grad(uation)? year|class of", "graduation_year"),
    (r"graduat", "graduation_date"),
    (r"^(school|university|college)( name)?\b|which (school|university)|what (school|university)|"
     r"currently (attend|enrolled)", "school"),
    (r"^degree\b|degree (type|level)|highest degree|degree (are you|you are) (currently )?(pursuing|working|obtaining)|"
     r"highest (level of )?education|level of education|education level", "degree"),
    (r"^sat\b|\bsat (score|total)", "sat_score"),
    (r"^act\b|\bact (score|composite)", "act_score"),
    (r"major|discipline|field of study|area of study", "major"),
    (r"relocat", "willing_to_relocate"),
    (r"salary|compensation (expectation|requirement)|desired (pay|compensation|salary)|expected (pay|salary|"
     r"compensation)|hourly rate|pay expectation", "desired_pay"),
    (r"18 years|at least 18|over (the age of )?18|legal (working )?age", "over_18"),
    (r"background (check|screen)|drug (test|screen)", "background_check_ok"),
    (r"non-?compete|restrictive covenant|non-?solicit", "non_compete"),
    (r"relative|family members?.*(work|employ)|related to (any|an) (current )?employee", "relatives_at_company"),
    (r"earliest start|available to start|start date|when can you start", "earliest_start"),
    (r"who referred|referr(er|ed by|al name)|name of (the )?(employee|person) who referred|employee referral name",
     "referral_name"),
    (r"how did you (first )?(hear|find|learn|come across)|where did you (first )?(hear|find|learn)|"
     r"referral source|source of application|how .*learn about", "how_heard"),
    (r"(previously|ever|formerly) (been )?(employed|worked)|(former|previous|past|prior) (\S+ )?(employee|intern|"
     r"contractor|worker)\b|^prior employment( (with|at) .{1,60})?\??$|worked (here|for us) before|"
     r"(have you|did you) (ever )?(worked|work|been employed) (for|at|with|by)|worked for .{0,60}(in the past|before|previously)", "previously_employed"),
    (r"(current|legal|full|permanent|residential|home|mailing) address|what is your address|^your address", "full_address"),
    (r"^(street )?address( line)?( 1)?$|street address", "address_line1"),
    (r"^city$|^city of residence|current city", "city"),
    (r"zip|postal", "postal_code"),
    (r"^country( of residence| or region)?$|country you (live|reside)", "country"),
    (r"^location|current location|city.*(reside|live)|where (are you|do you) (located|live|based)|"
     r"^city\b|where do you (intend|plan|expect) to work|(list|enter) (your )?city and state", "location"),
]

# Questions that look standard but depend on the company — always generated, never reused verbatim.
COMPANY_SPECIFIC = re.compile(r"why .*(us|company|team|role|position|interest)|what (excites|interests|draws)|"
                              r"interest(ed)? in (this|the|our)|tell us about|describe", re.I)


# What shape of answer a question wants, so a reused paragraph never lands in a city box (or "Yes" in an essay).
PLACE_Q = re.compile(r"\b(city|location|located|based|reside|relocat\w*)\b|(city|country),? (and |or |/)?state|"
                     r"state (of residence|/province)|(which|what) state|^state$|where (are|do|will|would) you( \w+){0,3} "
                     r"(live|work|be (located|based|working))|work from|which (office|city)", re.I)
YES_NO_Q = re.compile(r"^(are|do|did|have|has|will|would|can|could|is|were) (you|your)\b", re.I)
ESSAY_Q = re.compile(r"\b(why|describe|tell us|explain|walk us through|what (excites|interests|draws|motivates)|"
                     r"how (have|did|would|do) you (approach|handle|solve|deal|use|apply|go about|define|measure|"
                     r"balance|prioriti[sz]e|manage|stay|keep))\b", re.I)
# "Please tell us your LinkedIn profile URL (so we can reach you)": a polite way to ask for one plain fact. Only
# these facts, named exactly, count; anything else after "tell us your" may be a story and stays one.
POLITE = re.compile(r"^(please )?(tell us|share|provide|give us|let us know|enter|list) (your|the) (.+?)"
                    r"(,? (so|in case|because|for|to) .*)?$", re.I)
PLAIN_FACTS = re.compile(r"((legal |preferred )?(first|last|full) name|e-?mail( address)?|(mobile |cell )?phone( number)?|"
                         r"linkedin( profile)?( url| link)?|github( profile)?( url| link)?|(personal )?website( url)?|"
                         r"portfolio( url| link)?|city|country|(current )?location|city and state|zip code|postal code|"
                         r"(desired |expected )?salary( expectations?| range)?|(desired|expected) compensation|"
                         r"compensation expectations?|(desired |expected )pay|pay expectations?|hourly rate|"
                         r"(earliest )?start date)",
                         re.I)


def plain_fact(label: str) -> str | None:
    """The fact a politely worded question asks for ("Tell us your country" -> "country"), or None."""
    plain = " ".join((label or "").split()).strip(" *?:.")
    note = re.search(r"\s*\(([^)]*)\)$", plain)                  # "(so we can reach you)", but not "(explain how…)"
    if note and not ESSAY_Q.search(note.group(1)):
        plain = plain[:note.start()]
    m = POLITE.match(plain.strip(" *?:."))
    return m.group(4) if m and PLAIN_FACTS.fullmatch(m.group(4)) else None


# "Why us" questions: an answer that never names the company is generic. (Not "describe a project": that's yours.)
WHY_COMPANY = re.compile(r"why (do you want to|would you like to|are you interested|are you applying|us\b|this "
                         r"(company|role|team|position)|join|work (at|for|with))|interest(ed)? in (this|the|our|joining)|"
                         r"what (excites|interests|draws|attracts) you (about|to)", re.I)
# Where you'd work isn't where you live: Jobsmith offers your profile location, for you to check.
WORK_INTENT = re.compile(r"where do you (intend|plan|expect|want) to work|work from", re.I)


def question_kind(label: str, qtype: str, options: list[str] | None = None) -> str:
    """'choice', 'file', 'location', 'yes_no', 'essay', 'open' or 'short'. Choices are checked against their
    options elsewhere. The wording decides, not the box: "How did you hear about us?" in a big box is still short
    to answer, and "Why us?" in a one-line box still wants sentences."""
    l = " ".join((label or "").split())
    if qtype == "file":
        return "file"
    if options:
        return "choice"
    canon = canon_for(l)                          # "Please tell us your country" is asking for your country
    if ESSAY_Q.search(l) and not plain_fact(l):   # "Are you willing to relocate? Explain." wants sentences
        return "essay"
    if canon in ("location", "city", "country"):
        return "location"
    if YES_NO_Q.search(l) and qtype != "textarea":                                # "Are you willing to relocate?"
        return "yes_no"
    if canon and canon not in ("cover_letter", "resume"):   # a question Jobsmith knows has a short answer, any box size
        return "short"
    if PLACE_Q.search(l):
        return "location"
    return "open" if qtype == "textarea" else "short"


def canon_for(label: str) -> str | None:
    l = (plain_fact(label) or " ".join((label or "").split())).lower().strip(" *?:")
    for pat, key in RULES:
        if re.search(pat, l):
            return key
    return None


DECLINE = re.compile(r"decline|prefer not|don.?t wish|do not wish|choose not|not to (answer|disclose|say)|"
                     r"rather not|wish not", re.I)


SYNONYMS = {
    r"\b(indian|pakistani|bangladeshi|sri lankan|nepali|bhutanese)\b": "south asian",
    r"\b(chinese|japanese|korean|taiwanese|mongolian)\b": "east asian",
    r"\b(filipino|vietnamese|thai|indonesian|malaysian|cambodian)\b": "southeast asian",
    r"\bhe/him\b": "he/him/his", r"\bshe/her\b": "she/her/hers", r"\bthey/them\b": "they/them/theirs",
}


def _nums(s: str) -> list[float]:
    return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", s)]


def pick_option(answer: str, options: list[str]) -> str | None:
    """Best option for an answer. Handles yes/no, decline-to-answer, numeric ranges (GPA), years."""
    if not options or answer is None:
        return None
    a = answer.strip()
    al = a.lower()
    if not a:
        return None
    for o in options:                                    # exact
        if o.strip().lower() == al:
            return o
    if DECLINE.search(a):                                # decline-to-self-identify family
        for o in options:
            if DECLINE.search(o):
                return o
    if al in ("yes", "no", "true", "false"):
        want = "yes" if al in ("yes", "true") else "no"
        for o in options:
            if re.match(rf"^\s*{want}\b", o, re.I):
                return o
        # EEO-style wording: "I am not a protected veteran", "No, I do not have a disability"
        real = [o for o in options if not DECLINE.search(o)]
        if want == "no":
            neg = [o for o in real if re.search(r"\bnot\b|\bno\b|don.?t have|do not have", o, re.I)]
            if len(neg) == 1:
                return neg[0]
        else:
            pos = [o for o in real if not re.search(r"\bnot\b|\bno\b|don.?t|do not", o, re.I)]
            if len(pos) == 1:
                return pos[0]
            # acknowledgments: "Confirmed", "I acknowledge", "I agree", "Accept"
            ack = [o for o in pos if re.search(r"confirm|acknowledg|agree|accept|understand|consent", o, re.I)]
            if len(ack) >= 1:
                return ack[0]
    nums = _nums(a)
    if nums:
        v = nums[0]
        for o in options:                                # numeric ranges like "3.50 - 3.79", "3.8+", "Above 3.5"
            ol = o.lower()
            on = _nums(o)
            if len(on) >= 2 and re.search(r"\d\s*(-|–|to)\s*\d", o) and on[0] <= v <= on[1]:
                return o
            if len(on) == 1 and ("+" in o or "above" in ol or "or higher" in ol or "greater" in ol) and v >= on[0]:
                return o
            if len(on) == 1 and ("below" in ol or "less" in ol or "under" in ol or "<" in o) and v < on[0]:
                return o
            if len(on) == 1 and on[0] == v:
                return o
    for o in options:                                    # prefix / containment
        ol = o.lower()
        if ol.startswith(al) or al.startswith(ol):
            return o
    if "citizen" in al:                                 # "U.S. Citizen" vs "US Citizen / National", "Citizen"
        cands = [o for o in options if re.search(r"citizen", o, re.I) and not re.search(r"non-?citizen|not a", o, re.I)]
        if cands:
            return min(cands, key=len)
    expanded = al
    for pat, rep in SYNONYMS.items():                    # "Asian (Indian)" -> also "south asian"
        if re.search(pat, al):
            expanded += " " + rep
            for o in options:
                if rep in o.lower():
                    return o
    for o in options:
        if len(al) > 3 and (al in o.lower() or o.lower() in al):
            return o
    words = set(re.findall(r"[a-z]{3,}", expanded))    # best word overlap, if it's unambiguous
    scored = sorted(((len(words & set(re.findall(r"[a-z]{3,}", o.lower()))), o) for o in options
                     if not DECLINE.search(o)), reverse=True)
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None
