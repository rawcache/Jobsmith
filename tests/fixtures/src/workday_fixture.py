"""Build the saved Workday pages (tests/fixtures/workday_nvidia_*.html) from read-only captures (see README.md here).

    uv run python tests/fixtures/src/workday_fixture.py CAPTURE_DIR tests/fixtures

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

PAGES = {  # capture -> (fixture, which page it is, for the stand-in)
    "2_start.html": ("workday_nvidia_posting.html", "posting"),
    "3_after_manual.html": ("workday_nvidia_signin.html", "signin"),
    "4_signin_email.html": ("workday_nvidia_signin_email.html", "signin_email"),
    "5_create_account.html": ("workday_nvidia_create_account.html", "create_account"),
}


def build(captured: str, which: str, script: str) -> str:
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
    text = re.sub(r"<[^>]+>", " ", page)
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[a-z]{2,}\b", text))
    phones = re.findall(r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b", text)
    typed = [v for v in re.findall(r'<input\b[^>]*\svalue="([^"]+)"', page) if v not in ("on", "true", "false")]
    if emails or phones or typed:
        raise SystemExit(f"personal details or typed values in the page: {sorted(emails)} {phones} {typed[:5]}")
    return page


if __name__ == "__main__":
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    script = (Path(__file__).parent / "workday_flow.js").read_text(encoding="utf-8")
    for name, (fixture, which) in PAGES.items():
        (out / fixture).write_text(build((src / name).read_text(encoding="utf-8"), which, script), encoding="utf-8")
