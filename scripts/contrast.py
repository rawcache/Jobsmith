"""Check every colour pair Jobsmith shows against WCAG AA, reading the colours from the files themselves.

    uv run python scripts/contrast.py          # prints each pair; exits 1 if any falls short

Text needs 4.5:1 and large text or a control's edge 3:1 (WCAG 2.2, 1.4.3 and 1.4.11). The pairs are the ones each
surface really draws: the dashboard (light and dark), the extension's popup (light and dark) and on-page panel, the
website, and the terminal app. tests/test_contrast.py runs this, so a colour change that drops below AA fails CI."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT, LARGE = 4.5, 3.0


def luminance(hex_: str) -> float:
    h = hex_.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    def chan(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def over(rgba: str, under: str) -> str:
    """A see-through colour ("rgb(74 222 128 / .12)") as it shows on `under`."""
    r, g, b, a = (float(x) for x in re.findall(r"[\d.]+", rgba))
    u = [int(under.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(a * c + (1 - a) * d):02x}" for c, d in zip((r, g, b), u))


def css_vars(css: str, block: str) -> dict[str, str]:
    """The colour custom properties in the first CSS block whose selector matches `block` (a regex). See-through
    ones are shown on the block's card (or page) colour, which is what they sit on."""
    m = re.search(block + r"\s*\{([^{}]*)\}", css)
    if not m:
        raise ValueError(f"no block {block!r}")
    out = {k: v.lower() for k, v in re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,6})\b", m.group(1))}
    base = out.get("card") or out.get("bg") or "#ffffff"
    for k, v in re.findall(r"--([\w-]+):\s*(rgba?\([^)]*/[^)]*\))", m.group(1)):
        out.setdefault(k, over(v, base))
    return out


def py_colours(path: Path) -> dict[str, str]:
    return {k: v.lower() for k, v in re.findall(r'^([A-Z_]+) = "(#[0-9a-fA-F]{6})"', path.read_text(encoding="utf-8"), re.M)}


def surfaces() -> dict[str, tuple[dict[str, str], list[tuple[str, str, float]]]]:
    """surface -> (its colours by name, the pairs it draws: (text or mark, background, minimum ratio))."""
    web = (ROOT / "web/src/style.css").read_text(encoding="utf-8")
    dash_pairs = [("on-strong", "accent", TEXT), ("on-strong", "accent-hover", TEXT),
                  *[("accent", bg, TEXT) for bg in ("bg", "card", "side", "hover")],
                  *[(fg, bg, TEXT) for fg in ("ink", "text", "muted") for bg in ("bg", "card", "side", "hover", "chip")],
                  ("ok", "card", TEXT), ("warn", "card", TEXT), ("bad", "card", TEXT),
                  ("ok-ink", "ok-soft", TEXT), ("warn-ink", "warn-soft", TEXT), ("line-strong", "card", 1.0)]
    popup = (ROOT / "extension/popup.css").read_text(encoding="utf-8")
    popup_pairs = [("on-accent", "accent", TEXT), ("accent", "bg", TEXT), ("fg", "bg", TEXT), ("muted", "bg", TEXT),
                   ("ok", "bg", TEXT), ("warn", "bg", TEXT)]
    js = (ROOT / "extension/content.js").read_text(encoding="utf-8")
    grab = lambda pat: re.search(pat, js).group(1).lower()
    panel = {"paper": grab(r"\.p\{[^}]*background:(#[0-9a-f]{6})"), "card": grab(r"\.job\{background:(#[0-9a-f]{6})"),
             "ink": grab(r"\.wrap\{[^}]*color:(#[0-9a-f]{6})"), "muted": grab(r"\.muted\{color:(#[0-9a-f]{6})"),
             "accent": grab(r"\.go\{[^}]*background:(#[0-9a-f]{6})"), "accent-hover": grab(r"\.go:hover\{background:(#[0-9a-f]{6})"),
             "on-accent": "#ffffff", "chip": grab(r"\.kw span\{[^}]*background:(#[0-9a-f]{6})")}
    panel_pairs = [("on-accent", "accent", TEXT), ("on-accent", "accent-hover", TEXT), ("accent", "paper", TEXT),
                   ("ink", "paper", TEXT), ("ink", "card", TEXT), ("muted", "paper", TEXT), ("muted", "card", TEXT),
                   ("ink", "chip", TEXT)]
    site = (ROOT / "site/index.html").read_text(encoding="utf-8")
    site_light = css_vars(site, r":root")
    site_pairs = [("on-ember", "ember", TEXT), ("on-ember", "ember-hover", TEXT),
                  *[(fg, bg, TEXT) for fg in ("ember", "ink", "text", "muted") for bg in ("paper", "card")],
                  *[(fg, "term", TEXT) for fg in ("term-text", "term-dim", "ember-hot", "ok", "hold")]]
    site_light.setdefault("on-ember", "#ffffff")
    out = {
        "dashboard, light": (css_vars(web, r"(?m)^:root"), dash_pairs),
        "dashboard, dark": (css_vars(web, r':root\[data-theme="dark"\](?=\s*\{\s*--bg)'), dash_pairs),
        "extension popup, light": (css_vars(popup, r"(?m)^:root"), popup_pairs),
        "extension popup, dark": (css_vars(popup, r"prefers-color-scheme: dark\)\s*\{\s*:root"), popup_pairs),
        "extension panel": (panel, panel_pairs),
        "website, light": (site_light, site_pairs),
    }
    dark_site = re.search(r"prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme=\"light\"\]\)", site)
    if dark_site:
        out["website, dark"] = ({**site_light, **css_vars(site, r"prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme=\"light\"\]\)")},
                                site_pairs)
    tui = py_colours(ROOT / "jobsmith/tuiapp.py")
    out["terminal app"] = ({k.lower(): v for k, v in tui.items()},
                           [(fg, bg, TEXT) for fg in ("ember", "ink", "steel", "dim", "warn", "ok", "bad", "ember_hi")
                            for bg in ("bg", "card")])
    return out


# Faded with opacity on purpose and not text: a chart's bars, the "working" dots, the step in progress. Disabled
# controls are exempt from AA (1.4.3).
FADE_OK = {".bars .bar span", ".dots i", ".steps-bar .segs i.now"}
SHEETS = ("web/src/style.css", "extension/popup.css", "extension/content.js", "site/index.html")


def selectors(group: str) -> list[str]:
    """A rule's selectors, split at its top-level commas (not those inside :is(...) or [attr="a,b"])."""
    out, depth, quote, cur, escaped = [], 0, "", "", False
    for ch in group:
        if escaped or ch == "\\":
            escaped = not escaped and ch == "\\"
            cur += ch
            continue
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        cur += ch
    return [" ".join(x.split()) for x in out + [cur] if x.strip()]


def subject(sel: str) -> str:
    """The part of a selector naming the element itself: its last compound (after the last top-level space, >, + or
    ~), with escapes and quoted attribute values made inert so text like [title=":disabled ("] or .a\\+b can't
    be read as selector syntax."""
    sel = re.sub(r"\\.", "_", sel)                         # an escaped character is part of a name, never syntax
    sel = re.sub(r"""(["'])(?:(?!\1).)*\1""", '""', sel)
    depth, last = 0, 0
    for i, ch in enumerate(sel):
        depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(ch, 0)
        if depth == 0 and ch in " >+~":
            last = i + 1
    return sel[last:]


def disabled(sel: str) -> bool:
    """Whether the selector only ever matches a disabled control: `:disabled` on the element itself, outside any
    parentheses, or an :is()/:where() there whose every branch is disabled. So `:is(:disabled)` counts;
    `:is(.active, :disabled)`, `:not(:disabled)` and `button:disabled + a` don't."""
    sel, outside, i = subject(sel), "", 0
    while i < len(sel):
        m = re.match(r":(is|where|not|has)\(|\(", sel[i:])
        if not m:
            outside += sel[i]
            i += 1
            continue
        depth, j = 1, i + m.end()
        while j < len(sel) and depth:
            depth += {"(": 1, ")": -1}.get(sel[j], 0)
            j += 1
        inner = sel[i + m.end():j - 1]
        if m.group(1) in ("is", "where") and all(disabled(b) for b in selectors(inner)):
            return True
        i = j
    return bool(re.search(r":disabled|\[disabled\]", outside))


def fades() -> list[str]:
    """Rules that fade an element with opacity: its text then shows at less contrast than its colours say, which the
    pairs above can't see. Each one is reported unless it's a disabled control or listed in FADE_OK."""
    out = []
    for sheet in SHEETS:
        css = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", (ROOT / sheet).read_text(encoding="utf-8"))
        for sels, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            m = re.search(r"(?<![\w-])opacity\s*:\s*([\d.]+)(%?)", body)
            if not m or not 0 < float(m.group(1)) < (100 if m.group(2) else 1):
                continue                                     # not faded: shown, or hidden (opacity 0)
            for sel in selectors(sels):
                if not disabled(sel) and sel not in FADE_OK:
                    out.append(f"{sheet}: {sel} fades to opacity {m.group(1)}{m.group(2)}; use a colour token instead")
    return out


def check(surfaces_=None) -> list[str]:
    """Every pair that falls short, as 'surface: fg on bg is 3.9:1, needs 4.5:1', and every opacity fade."""
    short = []
    for name, (colours, pairs) in (surfaces_ or surfaces()).items():
        for fg, bg, need in pairs:
            r = ratio(colours[fg], colours[bg])
            if r < need:
                short.append(f"{name}: {fg} {colours[fg]} on {bg} {colours[bg]} is {r:.2f}:1, needs {need}:1")
    return short + (fades() if surfaces_ is None else [])


if __name__ == "__main__":
    for name, (colours, pairs) in surfaces().items():
        print(f"\n{name}")
        for fg, bg, need in pairs:
            r = ratio(colours[fg], colours[bg])
            print(f"  {'ok ' if r >= need else 'LOW'} {r:5.2f}:1 (needs {need})  {fg} {colours[fg]} on {bg} {colours[bg]}")
    for f in fades():
        print(f"  LOW  {f}")
    bad = check()
    print("\nAll pairs pass AA." if not bad else f"\n{len(bad)} pair(s) below AA.")
    sys.exit(1 if bad else 0)
