"""The fixture builders in tests/fixtures/src/ refuse a page holding anything someone typed, a contact detail or a key,
and keep a blank form's own options. They're the last check before a saved page is committed (rule 7)."""
import sys

import pytest

from conftest import FIXTURES

sys.path.insert(0, str(FIXTURES / "src"))
import icims_fixture  # noqa: E402


def _build(body: str) -> str:
    return icims_fixture.build(f"<html><body><form>{body}</form></body></html>", "email", "")


def test_a_blank_form_with_choices_builds():
    """An unchecked radio or checkbox carries its option as its value ("Y"); that's the form's, not typed."""
    page = _build('<label><input type="radio" name="a" value="Y"> Yes</label><input type="checkbox" name="b" '
                  'value="1"><input type="hidden" name="state" value="abc"><input type="submit" value="Next">'
                  '<input type="text" name="c" value="">')
    assert 'value="Y"' in page


@pytest.mark.parametrize("body", [
    '<input type="text" name="first" value="Jane">',
    '<input name="city" value="Somewhere">',                                      # no type: a text box
    '<textarea name="why">Because</textarea>',
    '<p>Write to jane.doe@example.com</p>',
    '<p>Call (617) 555-0142</p>',
    '<div data-key="94fee806-5cac-4582-9738-384a0f4ea6f9"></div>',               # an id or key left in
])
def test_anything_typed_or_personal_is_refused(body):
    with pytest.raises(SystemExit):
        _build(body)
