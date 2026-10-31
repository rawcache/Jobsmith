"""Cookie and consent banners: closed with a real click on their most private choice, never accepted for you.

Lever's banner is the one saved with the Palantir form (tests/fixtures/lever_palantir_form.html, captured
read-only); the others in tests/fixtures/banners/ were written for these tests from each vendor's published markup."""
import pytest

from jobsmith.fill import base, generic, greenhouse, multistep
from conftest import FIXTURES

LEVER_FORM = (FIXTURES / "lever_palantir_form.html").resolve().as_uri()
LANGUAGE_BOX = 'input[name="cards[a69a985a-eae9-4c14-90fb-b5a4b891523e][field0]"][value="English (ENG)"]'


def _url(name: str) -> str:
    return (FIXTURES / "banners" / name).resolve().as_uri()


@pytest.fixture
async def page():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        exe = __import__("os").environ.get("JOBSMITH_CHROMIUM_PATH")
        b = await pw.chromium.launch(headless=True, args=base.browser_args(), **({"executable_path": exe} if exe else {}))
        p = await b.new_page()
        yield p
        await b.close()


async def _covered(page, sel: str) -> bool:
    """Whether a real click at the middle of `sel` would land on something else."""
    return await page.eval_on_selector(sel, """e => { const r = e.getBoundingClientRect();
        const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return !!hit && hit !== e && !e.contains(hit) && !(e.labels && [...e.labels].some(l => l.contains(hit))); }""")


async def test_levers_saved_banner_is_denied_with_a_real_click_then_the_languages_box_is_ticked(page):
    """On the saved Palantir form, Lever's cookie banner covers whatever is scrolled to the bottom of the window,
    as the Languages checkboxes were. Jobsmith presses Deny (Lever's banner has no other non-Accept choice), the
    banner closes, Lever records "deny", and the checkbox then takes an ordinary click, no forcing."""
    await page.goto(LEVER_FORM)
    box = page.locator(LANGUAGE_BOX)
    await box.evaluate("e => window.scrollBy(0, e.getBoundingClientRect().bottom - innerHeight + 30)")
    assert await _covered(page, LANGUAGE_BOX)                              # under the banner, as on Lever
    spot = await box.bounding_box()
    await page.mouse.click(spot["x"] + spot["width"] / 2, spot["y"] + spot["height"] / 2)
    assert not await box.is_checked()                                      # a person's click there hits the banner

    pressed = await base.dismiss_banners(page)

    assert [p.lower() for p in pressed] == ["deny"]
    assert await page.evaluate("window.__cookieChoice") == "deny"
    assert not await page.locator(".cc-window").is_visible()
    await box.check(timeout=3000)
    assert await box.is_checked()
    assert await base.dismiss_banners(page) == []                          # nothing left: does nothing


@pytest.mark.parametrize("name, pressed, choice", [
    ("onetrust.html", "Reject All", "reject"),                             # not Settings, Close or Accept
    ("cookiebot.html", "Deny", "deny"),                                    # not "Allow selection"
    ("essential_only.html", "Accept only essential cookies", "essential"),
    ("close_notice.html", "✕", "close"),                                   # a notice with only a close
    ("in_frame.html", "Reject all", "reject"),                             # drawn in its own frame
])
async def test_each_banner_gets_its_most_private_choice(page, name, pressed, choice):
    await page.goto(_url(name))
    if name == "in_frame.html":
        await page.frame_locator("#sp_message_iframe_1").locator("button").first.wait_for()
    else:
        assert await _covered(page, "#agree")
    assert await base.dismiss_banners(page) == [pressed]
    assert await page.evaluate("window.__choice") == choice
    await page.locator("#agree").check(timeout=3000)                       # reachable now, with a real click


@pytest.mark.parametrize("name", [
    "accept_only.html",               # only Accept and Got it: the user's consent isn't Jobsmith's to give
    "closing_agrees.html",            # "by closing this banner you agree": its close is an Accept too
    "consent_question_in_form.html",  # a consent question that's part of the application: the user's to answer
])
async def test_a_banner_that_only_takes_consent_is_left_for_you(page, name):
    await page.goto(_url(name))
    logs = []
    assert await base.dismiss_banners(page, logs.append) == []
    assert await page.evaluate("window.__choice") is None and not logs


@pytest.mark.parametrize("prose, buttons, pressed", [
    ("Closing this banner means you agree to our cookies.", '<button aria-label="Close">×</button>', []),
    ("We use cookies. Continue browsing to consent to them.", "<button>Close</button>", []),
    ("If you navigate away you accept cookies.", "<button>Dismiss</button>", []),
    ("By clicking X you agree to cookies.", "<button>X</button>", []),
    ("We use cookies. Closing this notice opts you in.", "<button>Close</button>", []),
    ("We use cookies. By closing you opt-in to tracking.", "<button>Close</button>", []),
    # its buttons say Accept and Close, but nothing says closing agrees: Close is the private choice
    ("We use cookies for analytics.", "<button>Accept</button><button>Close</button>", ["Close"]),
])
async def test_a_close_that_agrees_is_never_pressed(page, prose, buttons, pressed):
    await page.set_content(f'<div class="cookie-banner" style="position:fixed;bottom:0;left:0;right:0"><p>{prose}</p>'
                           f'{buttons}</div><script>document.querySelectorAll("button").forEach(b => b.onclick = '
                           f'() => b.parentElement.remove())</script>')
    assert await base.dismiss_banners(page) == pressed


async def test_an_applications_own_consent_dialog_is_left_for_you(page):
    """A floating dialog asking to record the interview, or to keep your details for later roles, is a question for
    the user, with Decline and Accept like a banner's. It's about consent but not about cookies: never pressed."""
    await page.set_content("""<div role="dialog" aria-label="Consent" style="position:fixed;bottom:0;left:0;right:0">
        <p>Do you consent to this interview being recorded and transcribed by our AI notetaker?</p>
        <button onclick="window.__choice='decline'">Decline</button><button onclick="window.__choice='accept'">Accept</button>
        </div><div role="alertdialog" style="position:fixed;top:0">May we keep your details for future openings?
        <button onclick="window.__choice='no'">Decline</button></div><script>window.__choice = null</script>""")
    assert await base.dismiss_banners(page) == []
    assert await page.evaluate("window.__choice") is None


async def test_every_adapter_closes_the_banner_before_it_reads_or_fills(page, tmp_path):
    """generic (Lever, Ashby, company sites), greenhouse and multistep (Workday, iCIMS) all close the banner when they
    open the form, so nothing under it is missed, and multistep says so in its log."""
    assert [p.lower() for p in await generic.open_form(page, LEVER_FORM)] == ["deny"]
    assert await page.evaluate("window.__cookieChoice") == "deny"

    assert await greenhouse.open_form(page, _url("onetrust.html")) == ["Reject All"]
    assert await page.evaluate("window.__choice") == "reject"

    logs = []

    async def answer(fields):
        return {f["field"]: "Yes" for f in fields if f["label"] == "I have read the job description"}

    res = await multistep.run(page, _url("cookiebot.html"), answer=answer, files={}, log=logs.append,
                              wait_for_user=None, allow_submit=lambda: False)
    assert await page.evaluate("window.__choice") == "deny"
    assert any('Closed a cookie banner with "Deny"' in line for line in logs), logs
    assert res["status"] == "review" and await page.locator("#agree").is_checked()


async def test_a_banner_that_shows_up_late_is_closed_before_filling(page):
    """Consent managers often load a second or two after the page. generic.fill checks again before it fills, and
    returns what it pressed so autopilot's log can say so."""
    await page.goto(_url("onetrust.html"))
    await page.evaluate("""() => { const b = document.querySelector('.bar'); b.style.display = 'none';
        setTimeout(() => { b.style.display = ''; }, 50); }""")
    await page.wait_for_timeout(200)
    drafts = [{"field": "#agree", "label": "I have read the job description", "qtype": "checkbox", "required": True,
               "value": "Yes"}]
    result = await generic.fill(page, drafts, {})
    assert result["banners"] == ["Reject All"] and not result["failed"], result
    assert await page.locator("#agree").is_checked()
