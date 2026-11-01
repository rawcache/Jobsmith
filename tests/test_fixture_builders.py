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
])
def test_anything_typed_or_personal_is_refused(_build, body):
    with pytest.raises(SystemExit):
        _build(body)


def test_a_key_left_in_an_icims_page_is_refused():
    with pytest.raises(SystemExit):
        icims_fixture.build('<html><body><div data-key="94fee806-5cac-4582-9738-384a0f4ea6f9"></div></body></html>',
                            "email", "")
