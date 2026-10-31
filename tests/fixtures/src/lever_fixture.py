"""Build tests/fixtures/lever_palantir_form.html from a capture of a live Lever form (see README.md here).

    uv run python tests/fixtures/src/lever_fixture.py CAPTURED.html tests/fixtures/lever_palantir_form.html

The capture (scripts/capture/capture.py) is the rendered form with Lever's scripts removed. Lever puts its whole
stylesheet in the page, twice; this keeps only the rules whose classes and ids the page uses, drops fonts and
everything else that would load from the network
(local fonts stand in for Lever's), blanks what the capture's browser filled in (the time zone),
the company's Lever account id and the Lever accounts that last edited each question, cuts the hidden copy of each question card down to its first few options (Lever
posts it back; nothing here reads it), adds lever_form.js (our stand-in for Lever's scripts), and refuses to
write a page with an email address or phone number in it other than the posting's own."""
from __future__ import annotations

import html as htmllib
import json
import re
import sys
from pathlib import Path

POSTING_OWN = {"accommodations@palantir.com"}       # in the posting's accommodation note, not anyone's details
NO_ACCOUNT = "00000000-0000-0000-0000-000000000000"
KEEP_OPTIONS = 3
# Lever's fonts load from its CDN; these stand in from the machine's own, so the page keeps its look offline
LOCAL_FONTS = "".join(f'@font-face{{font-family:{name};src:local("{name}"),local("Helvetica Neue"),local("Arial")}}'
                      for name in ("Lato", "Meta", "Meta-Caps", "Avenir"))


def _blocks(css: str):
    """Top-level (prelude, body) pairs of a stylesheet; body is None for a statement like @charset."""
    i, n = 0, len(css)
    while i < n:
        j = css.find("{", i)
        semi = css.find(";", i)
        if j < 0:
            return
        if 0 <= semi < j and css[i:semi].lstrip().startswith("@"):
            yield css[i:semi + 1].strip(), None
            i = semi + 1
            continue
        depth, k = 1, j + 1
        while depth and k < n:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        yield css[i:j].strip(), css[j + 1:k - 1]
        i = k


def _used(selector: str, classes: set[str], ids: set[str]) -> bool:
    """Whether a selector can match this page: every class and id it names is on the page somewhere."""
    bare = re.sub(r"\[[^\]]*\]|::?[\w-]+(\([^)]*\))?", "", selector)
    return all(c in classes for c in re.findall(r"\.([\w-]+)", bare)) and \
        all(i in ids for i in re.findall(r"#([\w-]+)", bare))


def prune(css: str, classes: set[str], ids: set[str]) -> str:
    out = []
    for prelude, body in _blocks(css):
        if body is None:
            continue
        if prelude.startswith("@font-face"):
            continue                                                    # Lever's own fonts: see LOCAL_FONTS
        if prelude.startswith(("@media", "@supports")):
            inner = prune(body, classes, ids)
            if inner:
                out.append(f"{prelude}{{{inner}}}")
        elif prelude.startswith("@"):
            out.append(f"{prelude}{{{body}}}")                         # @keyframes and the like: small, kept
        elif any(_used(s, classes, ids) for s in prelude.split(",")):
            out.append(f"{prelude}{{{body}}}")
    return "".join(out)


def _trim_card(match: re.Match) -> str:
    """A hidden card (Lever's JSON copy of a question card) with each option list cut to its first few."""
    card = json.loads(htmllib.unescape(match.group(1)))

    def cut(o):
        if isinstance(o, dict):
            o = {k: NO_ACCOUNT if k.endswith("UserId") else cut(v) for k, v in o.items()   # who edited the card
                 if not (re.fullmatch(r"options\d+", k) and int(k[7:]) >= KEEP_OPTIONS)}
            return o
        if isinstance(o, list):
            return [cut(v) for v in o][:KEEP_OPTIONS] if o and isinstance(o[0], dict) and "optionId" in o[0] \
                else [cut(v) for v in o]
        return o
    return f'value="{htmllib.escape(json.dumps(cut(card), separators=(",", ":")), quote=True)}"'


def build(captured: str, script: str) -> str:
    page = re.sub(r"<link\b[^>]*>", "", captured)
    classes = {c for attr in re.findall(r'\sclass="([^"]*)"', page) for c in attr.split()}
    ids = set(re.findall(r'\sid="([^"]*)"', page))
    # the classes the stand-in script adds (lever_form.js): keep their rules too
    classes |= {"has-file", "dropdown-location", "dropdown-location-active", "break-word", "width-full", "py1", "px2"}
    page = re.sub(r"<style\b[^>]*>(.*?)</style>",
                  lambda m: f"<style>{prune(m.group(1), classes, ids)}</style>", page, flags=re.S)
    page = re.sub(r"<style>(.*?)</style>\s*<style>\1</style>", r"<style>\1</style>", page, flags=re.S)
    page = page.replace("</head>", f"<style>{LOCAL_FONTS}</style></head>", 1)
    page = re.sub(r"url\((['\"]?)https?://[^)]*\)", "none", page)
    page = re.sub(r"\s(src|srcset|href)=\"https?://[^\"]*\"", "", page)
    account = re.search(r'name="accountId" value="([^"]+)"', page).group(1)
    page = page.replace(account, NO_ACCOUNT)                     # the field, each card, the logo's address
    page = re.sub(r'(id="applicant-timezone" value=")[^"]*"', r'\1"', page)
    page = re.sub(r'value="(\{&quot;createdAt&quot;[^"]*)"', _trim_card, page)
    page = page.replace("</body>", f"<script>{script}</script></body>", 1)
    left = re.findall(r"\s(?:src|srcset|href|poster|data|action)=\"(https?://[^\"]*)\"|url\(['\"]?(https?://[^)'\"]*)",
                      page)
    if left:
        raise SystemExit(f"still loads from the network: {left[:5]}")
    if "cdn.lever.co/fonts" in page or account in page or \
            re.search(r"UserId&quot;:&quot;(?!0{8}-)", page):
        raise SystemExit("fonts or the account id are still in the page")
    text = re.sub(r"<[^>]+>", " ", page)
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", htmllib.unescape(text))) - POSTING_OWN
    phones = re.findall(r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b", text)
    if emails or phones:
        raise SystemExit(f"contact details in the page: {sorted(emails)} {phones}")
    return page


if __name__ == "__main__":
    captured, out = sys.argv[1:3]
    script = (Path(__file__).parent / "lever_form.js").read_text(encoding="utf-8")
    Path(out).write_text(build(Path(captured).read_text(encoding="utf-8"), script), encoding="utf-8")
