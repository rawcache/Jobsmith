"""Build the saved Workday pages (tests/fixtures/workday_nvidia_*.html) from read-only captures (see README.md here).

    uv run python tests/fixtures/src/workday_fixture.py CAPTURE_DIR tests/fixtures
    uv run python tests/fixtures/src/workday_fixture.py --signed-in SAVED_DIR tests/fixtures

CAPTURE_DIR holds what a headless browser behind jobsmith/readonly.py saved, scripts removed, walking NVIDIA's
"AI Systems Software Engineering Intern - Summer 2027" posting up to sign-in, typing nothing:
2_start.html (the posting with its "Start Your Application" box open), 3_after_manual.html (the sign-in choice),
4_signin_email.html and 5_create_account.html. Each becomes a fixture with nothing loaded from the network (the
LinkedIn widget's frame, the canonical link and remote images go), and workday_flow.js (our stand-in for Workday's
scripts) added. The posting's box starts closed, as on the live page, and opens on Apply. It refuses to write a page
with an email address or phone number in it, or a value typed into a field."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from icims_fixture import typed_values  # noqa: E402  (one rule for what counts as typed)

PAGES = {  # capture -> (fixture, which page it is, for the stand-in)
    "2_start.html": ("workday_nvidia_posting.html", "posting"),
    "3_after_manual.html": ("workday_nvidia_signin.html", "signin"),
    "4_signin_email.html": ("workday_nvidia_signin_email.html", "signin_email"),
    "5_create_account.html": ("workday_nvidia_create_account.html", "create_account"),
}


def build(captured: str, which: str, script: str, phone_ok: str | None = None) -> str:
    page = re.sub(r"<link\b[^>]*>", "", captured)
    page = re.sub(r"<iframe\b[^>]*\bsrc=\"https?://[^\"]*\"[^>]*>\s*</iframe>", "", page)
    page = re.sub(r"url\((['\"]?)https?://[^)]*\)", "none", page)
    page = re.sub(r"\s(src|srcset)=\"https?://[^\"]*\"", "", page)
    page = re.sub(r"\shref=\"https?://[^\"]*\"", ' href="#"', page)
    if which == "posting":            # the box opens on Apply, as on the live page
        page = re.sub(r'(data-automation-id="wd-popup-(glass|frame)")', r'\1 hidden', page)
    page = page.replace("<html", f'<html data-jobsmith-page="{which}"', 1)
    page = page.replace("</body>", f"<script>{script}</script></body>", 1)
    left = re.findall(r"\s(?:src|srcset|href|poster|data|action)=\"(https?://[^\"]*)\"|url\(['\"]?(https?://[^)'\"]*)",
                      page)
    if left:
        raise SystemExit(f"still loads from the network: {left[:5]}")
    # anywhere in the page, attributes too (an aria-label can hold an address), and any text a box holds
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[a-z]{2,}\b", page)) - {"alex.rivera@example.edu"}
    shown = re.sub(r"<style\b.*?</style>", "", page, flags=re.S)
    if phone_ok:                                 # Alex's own number, on the Review page only
        shown = shown.replace(phone_ok, "")
    phones = re.findall(r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b", shown)
    typed = typed_values(page) + \
        [t for t in re.findall(r"<textarea\b[^>]*>(.*?)</textarea>", page, flags=re.S) if t.strip()]
    if emails or phones or typed:
        raise SystemExit(f"personal details or typed values in the page: {sorted(emails)} {phones} {typed[:5]}")
    return page


# ---------------------------------------------------------------------------------------------------- signed in
# The application itself, behind sign-in, saved from the maintainer's own Chrome with "Save as… Webpage, Complete"
# (docs/guides/save-workday-pages.md), filled in by hand and by another autofill tool. Every value on these pages is
# treated as someone's: each box is emptied, each choice unpicked, and the Review page shows Alex Rivera's made-up
# answers instead.
SIGNED_IN = {  # saved page -> (fixture, which page it is, for the stand-in)
    "1-my-information.html": ("workday_nvidia_my_information.html", "my_information"),
    "2-my-experience.html": ("workday_nvidia_my_experience.html", "my_experience"),
    "3-application-questions.html": ("workday_nvidia_application_questions.html", "application_questions"),
    "4-voluntary-disclosures.html": ("workday_nvidia_voluntary_disclosures.html", "voluntary_disclosures"),
    "5-review.html": ("workday_nvidia_review.html", "review"),
}
ALEX_EMAIL = "alex.rivera@example.edu"
ALEX_PHONE = "+1 (617) 555-0123"
# What the Review page shows, as Alex sent it: by the id of the box that shows it, or by the section it's in.
# The two application questions are keyed by their place (first, second), since their ids are blanked.
REVIEW_BY_ID = {
    "source": "LinkedIn", "candidateIsPreviousWorker": "No",
    "schoolName": "Example Institute of Technology", "degree": "Bachelor's Degree",
    "fieldOfStudy": "Computer Engineering", "gradeAverage": "3.62", "firstYearAttended": "2023",
    "lastYearAttended": "2027", "attachments": "Alex_Rivera_resume.pdf", "url": "https://github.com/alexr-test",
    "linkedInAccount": "https://www.linkedin.com/in/alex-rivera-test/",
    "ethnicity": "I do not wish to answer. (United States of America)", "gender": "I do not wish to answer.",
    "veteranStatus": "I do not wish to self-identify", "acceptTermsAndAgreements": "Yes",
}
REVIEW_BY_SECTION = {
    "Legal-Name-section": ["Alex Rivera", "No"],                  # the name, then "I have a preferred name"
    "Address-section": ["Boston, MA<br>United States of America"],
    "Email-Address-section": [ALEX_EMAIL],
    "Phone-section": [f"{ALEX_PHONE} (Home)"],
}
REVIEW_QUESTIONS = ["Yes", "No"]                    # authorized to work there; needs the employer's support to


def _drop_element(page: str, start: int) -> str:
    """Cut the element whose start tag begins at `start`, with everything inside it (same-name tags counted)."""
    name = re.match(r"<([\w-]+)", page[start:]).group(1)
    depth, i = 0, start
    for m in re.compile(rf"<(/?){name}\b[^>]*>", re.I).finditer(page, start):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return page[:start] + page[m.end():]
        i = m.end()
    raise SystemExit(f"unclosed <{name}> at {start}")


def _strip_other_tools(page: str) -> str:
    """Another browser extension's markup (Simplify's panel, its fonts and its page margin), whole."""
    page = re.sub(r"<style\b[^>]*\bid=\"simplify[^\"]*\"[^>]*>.*?</style>", "", page, flags=re.S | re.I)
    while (m := re.search(r"<div\b[^>]*\bclass=\"[^\"]*simplify[^\"]*\"", page, re.I)):
        page = _drop_element(page, m.start())
    if re.search(r"simplify|chrome-extension://", page, re.I):
        raise SystemExit("another extension's markup is left in the page")
    return page


class _Ids:
    """Workday's own ids (32-hex instance ids, UUIDs) swapped for counters, the same one for the same id on every
    page, so the Review page still points at the questions it shows."""
    def __init__(self):
        self.seen: dict[str, str] = {}

    def __call__(self, page: str) -> str:
        def wid(m):
            return self.seen.setdefault(m.group(0), f"{len(self.seen) + 1:032x}")

        def uuid(m):
            return self.seen.setdefault(m.group(0), f"00000000-0000-4000-8000-{len(self.seen) + 1:012x}")
        page = re.sub(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", wid, page)
        return re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", uuid, page)


def _label_text(page: str, for_id: str) -> str:
    m = re.search(rf'<label\b[^>]*\bfor="{re.escape(for_id)}"[^>]*>(.*?)</label>', page, re.S)
    return " ".join(re.sub(r"<[^>]+>|\*", " ", m.group(1)).split()) if m else ""


def _blank_boxes(page: str) -> str:
    """Every box emptied, every choice unpicked, every dropdown back to "Select One", every picked item gone."""
    def box(m):
        tag = m.group(0)
        if re.search(r'\stype="(radio|checkbox)"', tag):
            tag = re.sub(r'\schecked(="[^"]*")?', "", tag)
            return re.sub(r'aria-checked="true"', 'aria-checked="false"', tag)
        if re.search(r'\stype="(submit|button|reset|image)"', tag):
            return tag
        return re.sub(r'\svalue="[^"]*"', ' value=""', tag)
    page = re.sub(r"<input\b[^>]*>", box, page)

    def dropdown(m):
        tag, ident = m.group(1), re.search(r'\sid="([^"]*)"', m.group(1))
        label = _label_text(page, ident.group(1)) if ident else ""
        required = " Required" if re.search(r'aria-label="[^"]*Required"', tag) else ""
        tag = re.sub(r'\svalue="[^"]*"', ' value=""', tag)
        tag = re.sub(r'\saria-label="[^"]*"', f' aria-label="{label} Select One{required}"', tag)
        return f"{tag}Select One</button>"
    form = page.index('data-automation-id="applyFlowPage"')       # the header's own menus (Settings) stay
    page = page[:form] + re.sub(r'(<button\b[^>]*aria-haspopup="listbox"[^>]*>).*?</button>', dropdown, page[form:],
                                flags=re.S)
    page = re.sub(r'<li\b[^>]*data-automation-id="menuItem"[^>]*>.*?</li>', "", page, flags=re.S)
    page = re.sub(r'(data-automation-id="promptAriaInstruction"[^>]*>)[^<]*', r"\1", page)
    return page


def _review(page: str) -> str:
    """The Review page's answers, all of them Alex's. Any answer box left unrecognised stops the build."""
    start = page.index('data-automation-id="applyFlowReviewPage"')
    head, body = page[:start], page[start:]
    done = set()

    def span(m):
        ident = m.group(2)
        if ident in REVIEW_BY_ID:
            done.add(m.start())
            return f"{m.group(1)}{REVIEW_BY_ID[ident]}</span>"
        return m.group(0)
    body = re.sub(r'(<span\b[^>]*\bid="([^"]+)"[^>]*>)(?:(?!<span\b).)*?</span>', span, body, flags=re.S)
    for section, values in REVIEW_BY_SECTION.items():
        at = body.index(f'aria-labelledby="{section}"')
        for value in values:
            m = re.compile(r'(<span\b[^>]*\bid="sijp\w+"[^>]*>)(?:(?!<span\b).)*?</span>', re.S).search(body, at)
            body = body[:m.start()] + f"{m.group(1)}{value}</span>" + body[m.end():]
            done.add(m.start())
            at = m.start() + len(m.group(1)) + len(value)
    questions = iter(REVIEW_QUESTIONS)
    found = list(re.finditer(r'(<span\b[^>]*\bid="[0-9a-f]{32}"[^>]*>)[^<]*</span>', body))
    if len(found) != len(REVIEW_QUESTIONS):
        raise SystemExit(f"expected {len(REVIEW_QUESTIONS)} application questions on Review, found {len(found)}")
    out, last = [], 0
    for m in found:
        out += [body[last:m.start()], f"{m.group(1)}{next(questions)}</span>"]
        last = m.end()
    body = "".join(out) + body[last:]
    left = [i for i in re.findall(r'<span\b[^>]*\bid="([^"]+)"[^>]*>(?:(?!<span\b).)*?</span>', body, flags=re.S)
            if i not in REVIEW_BY_ID and not re.fullmatch(r"sijp\w+|[0-9a-f]{32}", i)]
    if left:
        raise SystemExit(f"answers on the Review page not replaced: {left}")
    return head + body


def build_signed_in(saved: str, which: str, script: str, ids: _Ids) -> str:
    page = _strip_other_tools(saved)
    page = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", lambda m: m.group(0) if re.search(
        r"\.(png|svg|js|css|woff2?)$|@\d", m.group(0)) else ALEX_EMAIL, page)        # the account's address
    page = _blank_boxes(page)
    page = ids(page)
    if which == "review":
        page = _review(page)
    page = re.sub(r'\s(src|srcset)="/[^"]*"', "", page)          # the site's own logo, by its path on the site
    # icon drawings and colours to one decimal place: a search of the fixtures for someone's details (a GPA, a
    # street number) then never lands on an icon's path or a colour
    page = re.sub(r'(\sd="[^"]*")', lambda m: re.sub(r"(\d+\.\d)\d+", r"\1", m.group(1)), page)
    page = re.sub(r"oklch\([^)]*\)", lambda m: re.sub(r"(\d+\.\d)\d+", r"\1", m.group(0)), page)
    return build(page, which, script, phone_ok=ALEX_PHONE if which == "review" else None)


if __name__ == "__main__":
    if sys.argv[1] == "--signed-in":             # the application behind sign-in, from the maintainer's own saves
        saved, out, ids = Path(sys.argv[2]), Path(sys.argv[3]), _Ids()
        script = (Path(__file__).parent / "workday_apply.js").read_text(encoding="utf-8")
        for name, (fixture, which) in SIGNED_IN.items():
            (out / fixture).write_text(build_signed_in((saved / name).read_text(encoding="utf-8"), which, script, ids),
                                       encoding="utf-8")
        sys.exit()
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    script = (Path(__file__).parent / "workday_flow.js").read_text(encoding="utf-8")
    for name, (fixture, which) in PAGES.items():
        (out / fixture).write_text(build((src / name).read_text(encoding="utf-8"), which, script), encoding="utf-8")
