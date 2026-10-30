"""The project website in a real (headless) browser, with GitHub's API answered locally: the top bar stays one row
at every width once the star count arrives, the headline is two whole lines, nothing scrolls sideways, and the
install tabs show each system's command (picking yours when it can tell)."""
import re
from pathlib import Path

import pytest

from jobsmith.fill.base import browser_args
from test_extension import CHROMIUM, browser

SITE_DIR = Path(__file__).resolve().parents[1] / "site"
SITE = (SITE_DIR / "index.html").as_uri()
MAC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
WIN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
LINUX_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
WIDE = "Verdana, 'DejaVu Sans', sans-serif"     # Linux's usual fallback (DejaVu) and its look-alike elsewhere
ANDROID_UA = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Mobile Safari/537.36"


def _with_font(font: str, folder: Path) -> str:
    """A copy of the site in `folder` whose font stack is `font` from the first paint, as on a machine without the
    system fonts it names. It points back at the site for its images."""
    html = SITE_DIR.joinpath("index.html").read_text()
    html = re.sub(r"--font: [^;]+;", f"--font: {font};", html, count=1)
    html = html.replace("<head>", f'<head><base href="{SITE_DIR.as_uri()}/">', 1)
    out = folder / "index.html"
    out.write_text(html)
    return out.as_uri()


async def _open(pw, width: int, system: tuple[str, str, str] | None = None, font: str = "", folder: Path | None = None):
    """The site at `width`. `system` is what the browser says it runs on: (userAgentData.platform, platform,
    userAgent), each possibly empty, so a test doesn't depend on the machine it runs on. `font`, if given, replaces
    the page's font stack (see _with_font; the copy goes in `folder`)."""
    b = await pw.chromium.launch(headless=True, executable_path=CHROMIUM, args=browser_args())
    page = await (await b.new_context(viewport={"width": width, "height": 900})).new_page()
    if system:
        uad, platform, ua = system
        await page.add_init_script(f"""
          const nav = Object.getPrototypeOf(navigator);
          Object.defineProperty(nav, 'userAgentData', {{get: () => {uad!r} ? {{platform: {uad!r}}} : undefined}});
          Object.defineProperty(nav, 'platform', {{get: () => {platform!r}}});
          Object.defineProperty(nav, 'userAgent', {{get: () => {ua!r}}});""")

    async def github(route):
        url = route.request.url
        if "/releases/latest" in url:
            await route.fulfill(json={"tag_name": "v9.9.9", "published_at": "2026-10-01T00:00:00Z"})
        elif "api.github.com/repos/rawcache/Jobsmith" in url:
            await route.fulfill(json={"stargazers_count": 123456})    # a wide count: the worst case for the bar
        else:
            await route.abort()
    await page.route(re.compile(r"^https?://"), github)    # every web request; the glob "http*://**" matched none
    await page.goto(_with_font(font, folder) if font else SITE)
    await page.wait_for_function("document.getElementById('stars').getAttribute('aria-label') === '123456 stars'")
    return b, page


@browser
@pytest.mark.parametrize("font", ["", WIDE])
@pytest.mark.parametrize("width", [320, 360, 390, 768, 1024, 1440])
async def test_the_page_fits_every_width_with_the_star_count_in(width, font, tmp_path):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b, page = await _open(pw, width, font=font, folder=tmp_path)
        got = await page.evaluate("""() => {
          // the logo, each visible nav link (with its star count) and the Install button, left to right
          const items = [...document.querySelectorAll('.bar .brand, .bar nav a, .bar .cta')]
            .filter(e => getComputedStyle(e).display !== 'none').map(e => e.getBoundingClientRect());
          const mid = r => (r.top + r.bottom) / 2;
          const h1 = document.querySelector('h1'), lh = parseFloat(getComputedStyle(h1).lineHeight);
          return {sideways: document.documentElement.scrollWidth - innerWidth,
                  oneRow: items.every(r => Math.abs(mid(r) - mid(items[0])) < 4),
                  apart: items.every((r, i) => i === 0 || r.left >= items[i - 1].right),
                  inside: items.every(r => r.left >= 0 && r.right <= innerWidth),
                  lines: Math.round(h1.getBoundingClientRect().height / lh)}; }""")
        await b.close()
    assert got == {"sideways": 0, "oneRow": True, "apart": True, "inside": True, "lines": 2}


@browser
async def test_a_wide_font_headline_refits_as_the_window_changes(tmp_path):
    """Shrunk on a phone, back to full size on a desktop, and shrunk again: the fit follows every resize."""
    from playwright.async_api import async_playwright
    # resize events run at the next frame, so look a frame after resizing
    look = """new Promise(done => requestAnimationFrame(() => requestAnimationFrame(() => done(
      [parseFloat(getComputedStyle(document.querySelector('h1')).fontSize), document.documentElement.scrollWidth - innerWidth]))))"""
    async with async_playwright() as pw:
        b, page = await _open(pw, 360, font=WIDE, folder=tmp_path)
        phone = await page.evaluate(look)
        await page.set_viewport_size({"width": 1440, "height": 900})
        desk = await page.evaluate(look)
        await page.set_viewport_size({"width": 360, "height": 900})
        again = await page.evaluate(look)
        await b.close()
    assert phone[1] == desk[1] == again[1] == 0
    assert desk[0] == 72 and phone[0] < 36 and again[0] == phone[0]


@browser
@pytest.mark.parametrize("system, first", [
    (("macOS", "MacIntel", MAC_UA), "mac"),
    (("Windows", "Win32", WIN_UA), "win"),
    (("Linux", "Linux x86_64", LINUX_UA), "linux"),
    (("Windows", "", ""), "win"),                          # only the newer userAgentData says
    (("", "", WIN_UA), "win"),                             # only the user agent says
    (("", "Win32", ""), "win"),                            # only navigator.platform says
    (("", "Linux x86_64", ""), "linux"),
    (("Android", "Linux armv8l", ANDROID_UA), "mac"),      # a phone: not Linux's command; macOS is the default
    (("", "", ""), "mac"),                                 # it says nothing
])
async def test_the_install_tabs_show_each_systems_command(system, first):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b, page = await _open(pw, 1024, system)
        selected = await page.get_attribute("[role=tab][aria-selected=true]", "id")
        shown = {}
        for tab in ("mac", "linux", "win"):
            await page.click(f"#t-{tab}")
            shown[tab] = (await page.text_content("#cmd"), await page.text_content("#where"))
        await b.close()
    assert selected == f"t-{first}"
    assert shown["mac"][0] == shown["linux"][0] and shown["mac"][0].startswith("curl -LsSf") and shown["mac"][0].endswith("install.sh | sh")
    assert shown["win"][0].startswith("powershell") and "install.ps1" in shown["win"][0]
    assert [w for _, w in shown.values()] == ["Paste it into Terminal", "Paste it into a terminal", "Paste it into PowerShell"]
