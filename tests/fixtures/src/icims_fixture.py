"""Build the saved iCIMS pages (tests/fixtures/icims_idemia_*.html) from read-only captures (see README.md here).

    uv run python tests/fixtures/src/icims_fixture.py CAPTURE_DIR tests/fixtures

CAPTURE_DIR holds what a headless browser behind jobsmith/readonly.py saved, scripts removed, walking IDEMIA's "Full
Stack Software Engineering Internship" posting up to sign-in, typing nothing:
1_posting_top.html (the careers page around the posting), 1_posting.html (the posting itself, which iCIMS draws in
the page's "icims_content_iframe"), 2_email.html (what that frame shows after Apply: "Enter Your Information",
Email and Next) and 3_auth0_top.html (iCIMS's login at login.icims.com, from "Log back in!").

The signed-in pages were saved from the maintainer's own Chrome (docs/guides/save-icims-pages.md), Simplify off:
only step 1 of 5, "Candidate Profile", was saved. It asks for your profile and makes your account on the same page
("Create a login": Login, Password, Password again; Submit Profile makes it). Build it with

    uv run python tests/fixtures/src/icims_fixture.py --signed-in SAVED_DIR tests/fixtures

Each becomes a fixture with nothing loaded from the network: the page around the posting loads the posting from the
saved frame next to it; the chat widget, the hCaptcha frames, remote images and links go; hCaptcha's site key, the
login's state and the tracking hashes are blanked. icims_flow.js (our stand-in for iCIMS's scripts) is added. It
refuses to write a page with an email address or phone number in it, or a value typed into a field."""
from __future__ import annotations

import re
import sys
from pathlib import Path

NOT_TYPED = re.compile(r'\stype="(submit|button|reset|image|radio|checkbox)"', re.I)
# A hidden input can hold a token or a name the page filled in, so only these are kept: flags, small numbers and the
# login's sign-in choices once blanked (hs-00000-google)
HARMLESS_HIDDEN = re.compile(r"^(true|false|on|off|-?\d{1,4}|hs-00000-[a-z]+)$", re.I)
# iCIMS names each repeating section in a hidden box (portalLabel…): its own words, kept
SECTION_NAMES = {"Phones (1)", "Addresses (1)", "Professional Experience (1)", "Education (1)"}


def typed_values(page: str) -> list[str]:
    """Values that would be someone's: what's in a box you type into (a text box with a value was typed into before
    it was saved), and any hidden value but a harmless one. A radio button's or checkbox's value is its option
    ("Y"), and a button's its label."""
    out = []
    for tag in re.findall(r"<input\b[^>]*>", page):
        if NOT_TYPED.search(tag):
            continue
        hidden = re.search(r'\stype="hidden"', tag, re.I)
        section = hidden and re.search(r'\sname="portalLabel', tag)
        out += [v for v in re.findall(r'\svalue="([^"]+)"', tag)
                if not (hidden and (HARMLESS_HIDDEN.match(v) or (section and v in SECTION_NAMES)))]
    return out


PAGES = {  # capture -> (fixture, which page it is, for the stand-in)
    "1_posting_top.html": ("icims_idemia_posting.html", "top"),
    "1_posting.html": ("icims_idemia_posting_frame.html", "posting"),
    "2_email.html": ("icims_idemia_email_frame.html", "email"),
    "3_auth0_top.html": ("icims_idemia_login.html", "login"),
}
SIGNED_IN = {"1-candidate-profile.html": ("icims_idemia_profile_frame.html", "profile")}
ALEX_EMAIL = "alex.rivera@example.edu"


def build(captured: str, which: str, script: str) -> str:
    page = captured
    if which == "top":                    # the posting comes from the saved frame next to it
        page = re.sub(r'(<iframe\b[^>]*\bname="icims_content_iframe"[^>]*\bsrc=")[^"]*"',
                      r'\g<1>icims_idemia_posting_frame.html"', page)
    page = re.sub(r"<iframe\b[^>]*\bsrc=\"https?://[^\"]*\"[^>]*>\s*</iframe>", "", page)   # chat widget, hCaptcha
    page = re.sub(r"<link\b[^>]*>", "", page)
    page = re.sub(r"url\((['\"]?)https?://[^)]*\)", "none", page)
    page = re.sub(r"\s(src|srcset)=\"https?://[^\"]*\"", "", page)
    page = re.sub(r"\shref=\"https?://[^\"]*\"", ' href="#"', page)
    page = re.sub(r"\saction=\"[^\"]*\"", ' action="#"', page)
    # hCaptcha's site key, the login's one-time state and iCIMS's link hashes and customer number: not ours to keep
    page = re.sub(r'(sitekey="?|sitekey=)[0-9a-f-]{36}', r"\g<1>00000000-0000-0000-0000-000000000000", page)
    page = re.sub(r'(name="state"[^>]*\svalue=")[^"]*"', r'\g<1>"', page)
    page = re.sub(r'(\svalue=")[^"]*("[^>]*name="state")', r"\g<1>\g<2>", page)
    page = re.sub(r"hashed=-?\d+", "hashed=0", page)
    page = re.sub(r"hs-\d+-", "hs-00000-", page)
    # the signed-in page: iCIMS's per-field hashes, the hCaptcha widget's id, and the email iCIMS carried over from
    # the email step (shown in the Email box, as iCIMS does): Alex's
    page = re.sub(r'\shash="[0-9a-f]{64}"', ' hash=""', page)
    page = re.sub(r"(h-captcha-response-|data-hcaptcha-widget-id=\")[0-9a-z]{8,}", r"\g<1>0", page)
    if which == "profile":
        # an attribute holding a URL (OneDrive's and hCaptcha's settings, with their keys and nonces): it goes; any
        # other key-shaped id is blanked
        page = re.sub(r'\s[\w-]+=(?:"[^"]*https?:(?://|%2F%2F)[^"]*"|\'[^\']*https?:(?://|%2F%2F)[^\']*\')', "", page)
        page = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "00000000-0000-0000-0000-000000000000",
                      page)
        page = re.sub(r'(<input\b[^>]*\bid="PersonProfileFields\.Email"[^>]*\svalue=")[^"]*"', rf'\g<1>{ALEX_EMAIL}"',
                      page)
    page = page.replace("<html", f'<html data-jobsmith-page="{which}"', 1)
    page = page.replace("</body>", f"<script>{script}</script></body>", 1)
    left = re.findall(r"\s(?:src|srcset|href|poster|data|action)=\"(https?://[^\"]*)\"|url\(['\"]?(https?://[^)'\"]*)",
                      page)
    if left:
        raise SystemExit(f"still loads from the network: {left[:5]}")
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[a-z]{2,}\b", page)) - {"alex.rivera@example.edu"}
    phones = re.findall(r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b", re.sub(r"<style\b.*?</style>", "", page, flags=re.S))
    typed = [v for v in typed_values(page) if not (which == "profile" and v == ALEX_EMAIL)] + \
        [t for t in re.findall(r"<textarea\b[^>]*>(.*?)</textarea>", page, flags=re.S) if t.strip()]
    if emails or phones or typed:
        raise SystemExit(f"personal details or typed values in the page: {sorted(emails)} {phones} {typed[:5]}")
    if re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", page.replace("0" * 8, "")):
        raise SystemExit("a key or id is left in the page")
    return page


if __name__ == "__main__":
    signed_in = sys.argv[1] == "--signed-in"
    src, out = Path(sys.argv[1 + signed_in]), Path(sys.argv[2 + signed_in])
    script = (Path(__file__).parent / "icims_flow.js").read_text(encoding="utf-8")
    for name, (fixture, which) in (SIGNED_IN if signed_in else PAGES).items():
        (out / fixture).write_text(build((src / name).read_text(encoding="utf-8"), which, script), encoding="utf-8")
