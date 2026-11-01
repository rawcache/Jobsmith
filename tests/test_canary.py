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
    ([{"field": "#n", "label": "Full name", "qtype": "text"}, {"field": "#e", "label": "Email", "qtype": "text"},
      {"field": "#r", "label": "Resume", "qtype": "file"}, {"field": "#w", "label": "Why us?", "qtype": "textarea"},
      {"field": "#x", "label": "Start date", "qtype": "datepicker"}], "of a kind Jobsmith doesn't know"),
    ([{"field": f"#q{i}", "label": f"Question {i}", "qtype": "textarea"} for i in range(6)], "no name field found"),
])
def test_the_canary_says_what_broke(fields, problem):
    assert any(problem in p for p in canary.check_fields(fields)), canary.check_fields(fields)


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
