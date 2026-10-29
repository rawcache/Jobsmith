"""Build tests/fixtures/ashby_ramp_form.html from a capture of a live Ashby form (see README.md here).

    uv run python tests/fixtures/src/ashby_fixture.py CAPTURED.html ASHBY.css tests/fixtures/ashby_ramp_form.html

The capture (scripts/capture/capture.py) is the rendered form with Ashby's scripts removed. This inlines Ashby's
stylesheet so hidden inputs stay hidden, drops everything that would load from the network (icons, logo, fonts),
adds ashby_form.js (our stand-in for Ashby's script), and refuses to write a page with an email address or phone
number in it other than Ashby's own placeholders."""
from __future__ import annotations

import re
import sys
from pathlib import Path

PLACEHOLDERS = {"hello@example.com"}


def build(captured: str, css: str, script: str) -> str:
    html = re.sub(r"<link\b[^>]*>", "", captured)
    css = re.sub(r"url\((['\"]?)https?://[^)]*\)", "none", css)               # nothing from the network
    html = re.sub(r"\s(src|srcset|href)=\"https?://[^\"]*\"", "", html)
    html = html.replace("</head>", f"<style>{css}</style></head>", 1)
    html = html.replace("</body>", f"<script>{script}</script></body>", 1)
    # anything the page would fetch: an attribute that loads, or a CSS url() (a link written in the text is fine)
    left = re.findall(r"\s(?:src|srcset|href|poster|data|action)=\"(https?://[^\"]*)\"|url\(['\"]?(https?://[^)'\"]*)",
                      html)
    if left:
        raise SystemExit(f"still loads from the network: {left[:5]}")
    text = re.sub(r"<[^>]+>", " ", html)
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)) - PLACEHOLDERS
    phones = re.findall(r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b", text)
    if emails or phones:
        raise SystemExit(f"contact details in the page: {sorted(emails)} {phones}")
    return html


if __name__ == "__main__":
    captured, css, out = sys.argv[1:4]
    script = (Path(__file__).parent / "ashby_form.js").read_text(encoding="utf-8")
    Path(out).write_text(build(Path(captured).read_text(encoding="utf-8"), Path(css).read_text(encoding="utf-8"),
                               script), encoding="utf-8")
