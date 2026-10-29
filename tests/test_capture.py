"""scripts/capture/capture.py: saving a live form for a fixture lets through GETs and the listed read queries
only. A submit, an autosave, or a read query with a mutation tucked in never leaves the browser."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("capture", Path(__file__).parents[1] / "scripts/capture/capture.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)

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
    assert capture.allowed(method, url, body) is ok
