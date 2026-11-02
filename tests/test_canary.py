"""The weekly canary (scripts/canary/canary.py, .github/workflows/canary.yml): it reads each supported site's live
form read-only and reports what broke. Here it runs on the saved copies of those same forms, offline."""
import sys
from pathlib import Path

import pytest
import yaml

from conftest import FIXTURES
from jobsmith import ats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "canary"))
import canary  # noqa: E402

SAVED = {"greenhouse": "greenhouse_figma_live.html", "lever": "lever_palantir_form.html", "ashby": "ashby_ramp_form.html"}


def test_every_supported_site_has_a_canary_and_a_saved_form():
    assert set(canary.BOARDS) == set(ats.SUPPORTED) == set(SAVED)


@pytest.mark.parametrize("site, listing, url", [
    ("greenhouse", {"jobs": [{"absolute_url": "https://job-boards.greenhouse.io/figma/jobs/1"}]},
     "https://job-boards.greenhouse.io/figma/jobs/1"),
    ("lever", [{"applyUrl": "https://jobs.lever.co/palantir/abc/apply"}], "https://jobs.lever.co/palantir/abc/apply"),
    ("ashby", {"jobs": [{"isListed": False, "applyUrl": "https://jobs.ashbyhq.com/ramp/hidden/application"},
                        {"isListed": True, "applyUrl": "https://jobs.ashbyhq.com/ramp/x/application"}]},
     "https://jobs.ashbyhq.com/ramp/x/application"),
])
def test_a_posting_is_picked_from_each_sites_public_list(site, listing, url):
    assert canary.posting_url(site, listing) == url


@pytest.fixture
async def browser():
    import os
    from playwright.async_api import async_playwright
    from jobsmith.fill.base import browser_args
    async with async_playwright() as pw:
        exe = os.environ.get("JOBSMITH_CHROMIUM_PATH")
        b = await pw.chromium.launch(headless=True, args=browser_args(), **({"executable_path": exe} if exe else {}))
        yield b
        await b.close()


@pytest.mark.parametrize("site", sorted(SAVED))
async def test_the_canary_passes_on_the_saved_copy_of_each_sites_form(site, browser, monkeypatch):
    """The same run as the weekly one, on the saved form: found, labelled, the standard fields there, nothing typed."""
    url = (FIXTURES / SAVED[site]).resolve().as_uri()
    monkeypatch.setattr(canary, "find_posting", lambda s: url)
    res = await canary.run_site(site, browser)
    assert res.ok and res.fields >= canary.MIN_FIELDS, res


@pytest.mark.parametrize("fields, problem", [
    ([{"field": "#a", "label": "Email", "qtype": "text"}], "found 1 fields"),
    ([{"field": f"#f{i}", "label": "", "qtype": "text"} for i in range(6)], "has no label"),
    ([{"field": f'[id="{i}abc"]', "label": f"{i}abc", "qtype": "text", "unworded": True} for i in range(6)],
     "has no label"),
    ([{"field": "#n", "label": "Full name", "qtype": "text"}, {"field": "#e", "label": "Email", "qtype": "text"},
      {"field": "#r", "label": "Resume", "qtype": "file"}, {"field": "#w", "label": "Why us?", "qtype": "textarea"},
      {"field": "#x", "label": "Start date", "qtype": "datepicker"}], "of a kind Jobsmith doesn't know"),
    ([{"field": f"#q{i}", "label": f"Question {i}", "qtype": "textarea"} for i in range(6)], "no name field found"),
])
def test_the_canary_says_what_broke(fields, problem):
    assert any(problem in p for p in canary.check_fields(fields)), canary.check_fields(fields)


async def test_a_field_without_a_label_fails_the_canary(browser, monkeypatch, tmp_path):
    """The saved Lever form plus one box with no words of its own: every other field is fine, and it still fails.
    (Jobsmith reads such a box by its name, "mystery", which is no label; one with no name either is dropped.)"""
    page = (FIXTURES / SAVED["lever"]).read_text(encoding="utf-8")
    broken = tmp_path / "lever_no_label.html"
    broken.write_text(page.replace("</form>", '<div><div><div><div><div><input type="text" name="mystery"></div></div></div></div></div></form>', 1),
                      encoding="utf-8")
    monkeypatch.setattr(canary, "find_posting", lambda s: broken.resolve().as_uri())
    res = await canary.run_site("lever", browser)
    assert any("has no label" in p and "mystery" in p for p in res.problems), res


def test_greenhouses_saved_job_api_passes_and_a_new_question_kind_fails():
    import copy
    import json
    data = json.loads((FIXTURES / "greenhouse_job.json").read_text(encoding="utf-8"))
    assert canary.check_greenhouse_api(data) == []
    for where in (lambda d: d["questions"][0]["fields"][0],
                  lambda d: (d.setdefault("location_questions", []).append({"label": "Where?", "fields": [{"name": "w"}]})
                             or d["location_questions"][-1]["fields"][0]),
                  lambda d: (d.setdefault("compliance", []).append({"questions": [{"label": "EEO", "fields": [{"name": "e"}]}]})
                             or d["compliance"][-1]["questions"][0]["fields"][0])):
        changed = copy.deepcopy(data)
        where(changed)["type"] = "input_rich_text"
        assert any("new kind: input_rich_text" in p for p in canary.check_greenhouse_api(changed))
    changed = copy.deepcopy(data)
    changed["demographic_questions"] = {"questions": [{"label": "Gender", "type": "free_text", "answer_options": []}]}
    assert any("new kind: free_text" in p for p in canary.check_greenhouse_api(changed))
    assert canary.check_greenhouse_api({"title": "x"}) == ["Greenhouse's job API gave no questions list"]


async def test_a_box_whose_label_matches_its_id_is_labelled(browser):
    """<label for="Email">Email</label>: the words happen to match the id, and they are still the page's words."""
    from jobsmith.fill import base
    page = await browser.new_page()
    deep = lambda box: f"<div><div><div><div><div>{box}</div></div></div></div></div>"
    await page.set_content("<form>" + "".join(deep(b) for b in (
        '<label for="Email">Email</label><input id="Email">', '<input id="123abc">', '<input name="q_9">',
        '<input name="city" placeholder="Your city">',
        '<input type="checkbox" name="mystery">',                                   # a lone box, no words
        '<input type="radio" name="pick" value="a"><input type="radio" name="pick" value="b">',
        '<button type="button" aria-haspopup="listbox" id="dd">Select One</button>',
        '<label for="agree">agree</label><input type="checkbox" id="agree">',        # words that match its id
        '<fieldset><legend>Size</legend><label><input type="radio" name="size"> S</label>'
        '<label><input type="radio" name="size"> M</label></fieldset>',
        '<button type="button" aria-haspopup="listbox" id="state" aria-label="State">Select One</button>',
        '<div><p>Are you 18 or older?</p><label><input type="radio" name="adult" value="y"> Yes</label>'
        '<label><input type="radio" name="adult" value="n"> No</label></div>')) + "</form>")
    raw = {f["field"]: f for f in await page.evaluate(base.SCAN_JS)}
    assert sorted(k for k, f in raw.items() if f.get("unworded")) == sorted(
        ['[id="123abc"]', '[name="q_9"]', '[name="mystery"]', '[name="pick"]', '#dd']), raw
    assert raw['[name="adult"]']["label"] == "Are you 18 or older?" and raw["#state"]["label"] == "State"
    await page.close()


def test_the_canary_catches_broken_classification(monkeypatch):
    fields = [{"field": "#n", "label": "Full name", "qtype": "text"}, {"field": "#e", "label": "Email", "qtype": "text"},
              {"field": "#r", "label": "Resume", "qtype": "file"}, {"field": "#w", "label": "Why us?", "qtype": "textarea"},
              {"field": "#p", "label": "Phone", "qtype": "text"}]
    assert canary.check_fields(fields) == []
    monkeypatch.setattr(canary.classify, "question_kind", lambda label, qtype, options=None: "essay")
    problems = canary.check_fields(fields)
    assert any("asks for your email but reads as essay" in p for p in problems)
    assert any("is an upload but reads as essay" in p for p in problems)


def test_the_canary_only_reads():
    """It never fills or submits: no fill helper, no Submit, and every visit goes through the read-only guard."""
    src = (ROOT / "scripts" / "canary" / "canary.py").read_text(encoding="utf-8")
    assert "fill_field" not in src and ".fill(" not in src and "submit" not in src.lower().replace("submitting", "")
    assert "await guard(context)" in src and "new_context" in src


def test_the_canary_workflow_runs_weekly_with_no_credentials():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "canary.yml").read_text(encoding="utf-8"))
    on = wf[True] if True in wf else wf["on"]                    # YAML reads a bare `on:` as true
    assert "schedule" in on and "workflow_dispatch" in on
    assert wf["permissions"] == {"contents": "read", "issues": "write"}
    text = (ROOT / ".github" / "workflows" / "canary.yml").read_text(encoding="utf-8")
    assert "secrets." not in text and "--label canary" in text
    assert "scripts/canary/canary.py" in text


class _Reply:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def _urlopen(replies: list):
    calls = []

    def fake(req, timeout):
        calls.append(req.full_url)
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return _Reply(r)
    return fake, calls


def test_a_job_list_that_times_out_once_is_read_again_not_reported(monkeypatch):
    """#34: one timeout reading Lever's job list opened a canary issue. The network gets two more tries."""
    fake, calls = _urlopen([TimeoutError("The read operation timed out"),
                            b'[{"applyUrl": "https://jobs.lever.co/palantir/1/apply"}]'])
    monkeypatch.setattr(canary.urllib.request, "urlopen", fake)
    monkeypatch.setattr(canary.time, "sleep", lambda s: None)
    assert canary.find_posting("lever") == "https://jobs.lever.co/palantir/1/apply" and len(calls) == 2


def test_a_job_list_cut_off_mid_reply_is_read_again(monkeypatch):
    import http.client
    fake, calls = _urlopen([http.client.IncompleteRead(b"[{"), b'[{"applyUrl": "https://jobs.lever.co/p/1/apply"}]'])
    monkeypatch.setattr(canary.urllib.request, "urlopen", fake)
    monkeypatch.setattr(canary.time, "sleep", lambda s: None)
    assert canary.find_posting("lever") == "https://jobs.lever.co/p/1/apply" and len(calls) == 2


def test_a_job_list_that_never_answers_or_answers_an_error_is_still_reported(monkeypatch):
    import urllib.error
    monkeypatch.setattr(canary.time, "sleep", lambda s: None)
    fake, calls = _urlopen([TimeoutError("timed out")] * canary.TRIES)
    monkeypatch.setattr(canary.urllib.request, "urlopen", fake)
    with pytest.raises(TimeoutError):
        canary.find_posting("lever")
    assert len(calls) == canary.TRIES
    fake, calls = _urlopen([urllib.error.HTTPError("u", 404, "Not Found", {}, None)])
    monkeypatch.setattr(canary.urllib.request, "urlopen", fake)
    with pytest.raises(urllib.error.HTTPError):                 # the site's own answer: not tried again
        canary.find_posting("lever")
    assert len(calls) == 1
