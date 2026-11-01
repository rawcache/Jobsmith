"""The fixture builders in tests/fixtures/src/ refuse a page holding anything someone typed, a contact detail or a key,
and keep a blank form's own options. They're the last check before a saved page is committed (rule 7)."""
import sys

import pytest

from conftest import FIXTURES

sys.path.insert(0, str(FIXTURES / "src"))
import icims_fixture  # noqa: E402
import workday_fixture  # noqa: E402

BUILDERS = [lambda page: icims_fixture.build(page, "email", ""), lambda page: workday_fixture.build(page, "signin", "")]


@pytest.fixture(params=BUILDERS, ids=["icims", "workday"])
def _build(request):
    return lambda body: request.param(f"<html><body><form>{body}</form></body></html>")


def test_a_blank_form_with_choices_builds(_build):
    """An unchecked radio or checkbox carries its option as its value ("Y"); that's the form's, not typed."""
    page = _build('<label><input type="radio" name="a" value="Y"> Yes</label><input type="checkbox" name="b" '
                  'value="1"><input type="hidden" name="js" value="true"><input type="submit" value="Next">'
                  '<input type="text" name="c" value="">')
    assert 'value="Y"' in page


@pytest.mark.parametrize("body", [
    '<input type="text" name="first" value="Jane">',
    '<input name="city" value="Somewhere">',                                      # no type: a text box
    '<textarea name="why">Because</textarea>',
    '<p>Write to jane.doe@example.com</p>',
    '<p>Call (617) 555-0142</p>',
    '<input type="hidden" name="csrf" value="f3a9c2d1e8b7">',                     # a token
    '<input type="hidden" name="applicant" value="Jane Doe">',                    # a name the page filled in
    '<input type="hidden" name="req" value="12345">',                            # a number long enough to be an id
])
def test_anything_typed_or_personal_is_refused(_build, body):
    with pytest.raises(SystemExit):
        _build(body)


def test_a_key_left_in_an_icims_page_is_refused():
    with pytest.raises(SystemExit):
        icims_fixture.build('<html><body><div data-key="94fee806-5cac-4582-9738-384a0f4ea6f9"></div></body></html>',
                            "email", "")


@pytest.mark.parametrize("state", ['<input type="hidden" name="state" value="hqFo2SBvS1Bv">',
                                   '<input type="hidden" value="hqFo2SBvS1Bv" name="state">'])
def test_icims_login_state_is_blanked_whichever_way_round(state):
    """iCIMS's login carries a one-time state token; the builder empties it, then the login builds."""
    page = icims_fixture.build(f'<html><body><form>{state}<input type="hidden" name="connection" '
                               'value="hs-11800-google"><input type="hidden" name="is-brave" value="false">'
                               '</form></body></html>', "login", "")
    assert "hqFo" not in page and "11800" not in page and "hs-00000-google" in page


def _signed_in(body: str, which: str = "my_information") -> str:
    return workday_fixture.build_signed_in(
        '<html><head><style id="simplify-inter-font-faces">@font-face{src:url(chrome-extension://x/a.woff2)}</style>'
        '</head><body><header><span>jane.doe@example.com</span></header><div data-automation-id="applyFlowPage">'
        f'{body}</div><div class="simplify-jobs-shadow-root"><template shadowrootmode="open"><div><img '
        'src="chrome-extension://x/i.svg"></div></template></div></body></html>', which, "", workday_fixture._Ids())


def test_a_signed_in_workday_page_is_emptied_and_another_tools_markup_goes():
    page = _signed_in('<label for="c">Country</label><button aria-haspopup="listbox" type="button" id="c" '
                      'value="bc33aa3152ec42d4995f4791a106ed09" aria-label="Country Canada Required">Canada</button>'
                      '<input type="text" value="bc33aa3152ec42d4995f4791a106ed09"><input type="text" id="f" '
                      'value="Jane"><input type="radio" id="r" aria-checked="true" checked="" value="true">'
                      '<ul data-automation-id="selectedItemList"><li data-automation-id="menuItem"><p>Glassdoor</p></li></ul>')
    assert "simplify" not in page.lower() and "chrome-extension" not in page and "Jane" not in page
    assert "jane.doe" not in page and "alex.rivera@example.edu" in page            # the account's address: Alex's
    assert 'aria-label="Country Select One Required">Select One</button>' in page and "Canada" not in page
    assert "bc33aa31" not in page and "Glassdoor" not in page and " checked" not in page


def test_a_review_answer_the_builder_doesnt_know_stops_it():
    review = ('<div data-automation-id="applyFlowReviewPage">' + "".join(
        f'<div aria-labelledby="{s}"><span id="sijp{i}">x</span><span id="sijpz{i}">x</span></div>'
        for i, s in enumerate(workday_fixture.REVIEW_BY_SECTION)) +
        '<span id="00000000000000000000000000000001">Yes</span><span id="00000000000000000000000000000002">No</span>'
        '<span id="favouriteColour">Teal</span></div>')
    with pytest.raises(SystemExit, match="favouriteColour"):
        _signed_in(review, "review")
    page = _signed_in(review.replace('<span id="favouriteColour">Teal</span>', ""), "review")
    assert "Alex Rivera" in page and "Teal" not in page
