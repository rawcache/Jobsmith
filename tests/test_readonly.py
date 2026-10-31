"""jobsmith/readonly.py, behind saving a live form for a fixture and the weekly canary: only GETs and the listed
read queries leave the browser. A submit, an autosave, or a read query with a mutation tucked in never does."""
import importlib.util
import json
from pathlib import Path

import pytest

from jobsmith import readonly
from test_extension import CHROMIUM, browser

API = "https://jobs.ashbyhq.com/api/non-user-graphql"


def gql(op: str, query: str | None = None, name: str | None = None) -> str:
    return json.dumps({"operationName": name or op, "query": query or f"query {op}($id: String!) {{ posting {{ id }} }}"})


@pytest.mark.parametrize("method,url,body,ok", [
    ("GET", "https://jobs.ashbyhq.com/ramp/123/application", None, True),
    ("POST", f"{API}?op=ApiJobPosting", gql("ApiJobPosting"), True),
    ("POST", f"{API}?op=ApiOrganizationFromHostedJobsPageName", gql("ApiOrganizationFromHostedJobsPageName"), True),
    # what the form does when you use it: autosave, upload, submit
    ("POST", f"{API}?op=ApiSetFormValue", gql("ApiSetFormValue", "mutation ApiSetFormValue { x }"), False),
    ("POST", f"{API}?op=ApiSubmitSingleApplicationFormAction",
     gql("ApiSubmitSingleApplicationFormAction", "mutation ApiSubmitSingleApplicationFormAction { x }"), False),
    # a listed name that isn't a plain query, or says one name and sends another
    ("POST", f"{API}?op=ApiJobPosting", gql("ApiJobPosting", "mutation ApiJobPosting { x }"), False),
    ("POST", f"{API}?op=ApiJobPosting", gql("ApiJobPosting", "query ApiJobPosting { a } mutation M { b }"), False),
    ("POST", f"{API}?op=ApiJobPosting", gql("ApiJobPosting", name="ApiSubmitSingleApplicationFormAction"), False),
    ("POST", f"{API}?op=ApiJobPosting", "not json", False),
    ("POST", f"{API}?op=ApiJobPosting", None, False),
    # the same query anywhere else, or by another method
    ("POST", "https://evil.example/api/non-user-graphql?op=ApiJobPosting", gql("ApiJobPosting"), False),
    ("POST", "https://jobs.ashbyhq.com/api/other?op=ApiJobPosting", gql("ApiJobPosting"), False),
    ("PUT", f"{API}?op=ApiJobPosting", gql("ApiJobPosting"), False),
    ("POST", "https://www.recaptcha.net/recaptcha/api2/reload", "x", False),
])
def test_only_reads_leave_the_browser(method, url, body, ok):
    assert readonly.allowed(method, url, body) is ok


def test_the_capture_script_uses_the_shared_rules():
    spec = importlib.util.spec_from_file_location("capture", Path(__file__).parents[1] / "scripts/capture/capture.py")
    capture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture)
    assert capture.guard is readonly.guard and capture.allowed is readonly.allowed


@browser
async def test_the_guard_lets_a_page_read_but_nothing_it_sends_leaves(tmp_path):
    """A page that loads, then posts its form and beacons: the GET goes out, the POSTs are stopped and listed."""
    from playwright.async_api import async_playwright
    from jobsmith.fill.base import browser_args
    seen = []
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, executable_path=CHROMIUM, args=browser_args())
        context = await b.new_context()

        async def site(route):                     # stands in for the job site, behind the guard
            seen.append(route.request.method)
            await route.fulfill(body="<form method=post action=/apply><button>Submit</button></form><script>"
                                     "fetch('/autosave', {method: 'POST', body: 'x'}).catch(() => {});</script>",
                                content_type="text/html")
        await context.route("https://jobs.example.com/**", site)
        blocked = await readonly.guard(context)          # last, so it's asked first
        page = await context.new_page()
        await page.goto("https://jobs.example.com/acme/1")
        await page.click("button")
        await page.wait_for_timeout(300)
        await b.close()
    assert seen == ["GET"]
    assert ("POST", "https://jobs.example.com/autosave") in blocked
    assert ("POST", "https://jobs.example.com/apply") in blocked
