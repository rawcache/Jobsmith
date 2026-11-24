"""The dashboard bundle is committed, so its sources must never carry anything that names a person or owner.

Whatever sits in web/src ends up in jobsmith/web_dist. A handle used as a hint or an owner's repo used as an example
would be published with every rebuild, so this scans the sources and fails on any such string.
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "web" / "src"
SKIP_DIRS = {"tests", "test", "__tests__", "docs"}
EXTS = {".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".json", ".md"}

EMAIL = re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")
GITHUB_OWNER = re.compile(r"github\.com/([A-Za-z0-9][A-Za-z0-9-]*)", re.I)
PLACEHOLDER = "you"  # "you@...", "github.com/you": obvious stand-ins, never a real account
PLACEHOLDER_DOMAIN = "example.com"  # reserved for examples (RFC 2606), so "name@example.com" names no one


def _placeholder_email(m: re.Match) -> bool:
    local, domain = m.group(1).lower(), m.group(2).lower()
    return local == PLACEHOLDER or domain == PLACEHOLDER_DOMAIN or domain.endswith("." + PLACEHOLDER_DOMAIN)


def scan(text: str) -> list[str]:
    """Return every identifying string found in one file's text."""
    hits = [m.group(0) for m in EMAIL.finditer(text) if not _placeholder_email(m)]
    hits += [m.group(0) for m in GITHUB_OWNER.finditer(text) if m.group(1).lower() != PLACEHOLDER]
    return hits


def source_files() -> list[Path]:
    return [p for p in SRC.rglob("*")
            if p.is_file() and p.suffix in EXTS and not SKIP_DIRS & set(p.relative_to(SRC).parts[:-1])]


def test_scanner_catches_identifying_strings():
    assert scan("mail jane.doe@example.org") and scan('placeholder="jane@mail.example.net"')
    assert scan('"https://github.com/SomeOrg/list"') and scan("http://github.com/someone")


def test_scanner_allows_placeholders_and_templates():
    assert scan('placeholder="you@school.edu"') == []
    assert scan('placeholder="name@example.com"') == [] and scan("ops@mail.example.com") == []
    assert scan('"https://github.com/you"') == []
    assert scan("`https://github.com/${s}`") == []
    assert scan("const devMode = import.meta.env.DEV") == []


def test_dashboard_sources_name_no_one():
    files = source_files()
    assert files, "web/src not found"
    found = {str(p.relative_to(SRC)): h for p in files if (h := scan(p.read_text(encoding="utf-8", errors="ignore")))}
    assert found == {}, f"identifying strings in web/src (they would ship in the bundle): {found}"
