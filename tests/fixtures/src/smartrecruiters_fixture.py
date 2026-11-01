"""Build the saved SmartRecruiters form (tests/fixtures/smartrecruiters_bosch_form.html) from the maintainer's own save.

    uv run python tests/fixtures/src/smartrecruiters_fixture.py SAVED.html tests/fixtures

SmartRecruiters shows a bot check to a headless browser, so the form was saved from the maintainer's own Chrome
(docs/guides/save-smartrecruiters-form.md): Bosch's "Application Engineer", its "Easy apply" page, blank. The page is
built from web components whose insides are shadow roots, saved as declarative templates (<template
shadowrootmode="open">), which the browser turns back into shadow roots when the fixture opens.

The builder removes another browser extension's markup (Simplify's panel, fonts and page margin), what would load
from the network (SmartRecruiters' stylesheets, flag images, OneTrust's cookie script, tracking links), the
SmartRecruiters company and channel ids, and adds smartrecruiters_flow.js (our stand-in for its scripts), and gives each
icon a size of ours. It refuses
to write a page with an email address, a phone number, a typed value or another extension's markup in it."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from icims_fixture import typed_values  # noqa: E402  (one rule for what counts as typed)
from workday_fixture import _strip_other_tools  # noqa: E402  (another extension's markup, whole)

FIXTURE = "smartrecruiters_bosch_form.html"


def build(saved: str, script: str) -> str:
    page = _strip_other_tools(saved)
    page = re.sub(r"<link\b[^>]*>", "", page)
    page = re.sub(r"<iframe\b[^>]*\bsrc=\"https?://[^\"]*\"[^>]*>\s*</iframe>", "", page)
    page = re.sub(r"url\((['\"]?)https?://[^)]*\)", "none", page)
    page = re.sub(r"\s(src|srcset)=\"https?://[^\"]*\"", "", page)
    page = re.sub(r"\shref=\"https?://[^\"]*\"", ' href="#"', page)
    # ids that are SmartRecruiters' or a widget's, not the form's: blanked
    page = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "00000000-0000-4000-8000-000000000000",
                  page)
    page = re.sub(r"(?<![0-9a-f])[0-9a-f]{24}(?![0-9a-f])", "0" * 24, page)
    # a URL left inside an attribute's JSON (a widget's settings): the attribute goes
    page = re.sub(r'\s[\w-]+=(?:"[^"]*https?:(?://|&#x2F;)[^"]*"|\'[^\']*https?:(?://|&#x2F;)[^\']*\')', "", page)
    page = page.replace("<html", '<html data-jobsmith-page="smartrecruiters"', 1)
    # without SmartRecruiters' stylesheets its icons fill the page; they're inside shadow roots, where a page style
    # doesn't reach, so each icon gets a size of ours
    page = re.sub(r"<svg\b(?![^>]*\sdata-jobsmith-size)", '<svg data-jobsmith-size style="max-width:1.5em;max-height:1.5em"',
                  page)
    page = page.replace("</body>", f"<script>{script}</script></body>", 1)
    left = re.findall(r"\s[\w-]+=[\"'][^\"']*https?:(?://|&#x2F;)|url\(['\"]?https?://", page)
    if left:
        raise SystemExit(f"still loads from the network: {left[:5]}")
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[a-z]{2,}\b", page)) - {"alex.rivera@example.edu"}
    phones = re.findall(r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b", re.sub(r"<style\b.*?</style>", "", page, flags=re.S))
    typed = typed_values(page) + \
        [t for t in re.findall(r"<textarea\b[^>]*>(.*?)</textarea>", page, flags=re.S) if t.strip()]
    if emails or phones or typed:
        raise SystemExit(f"personal details or typed values in the page: {sorted(emails)} {phones} {typed[:5]}")
    return page


if __name__ == "__main__":
    saved, out = Path(sys.argv[1]), Path(sys.argv[2])
    script = (Path(__file__).parent / "smartrecruiters_flow.js").read_text(encoding="utf-8")
    (out / FIXTURE).write_text(build(saved.read_text(encoding="utf-8"), script), encoding="utf-8")
