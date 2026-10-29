"""scripts/ci/retry_runner.py: a macOS tests job is retried once when it never got a runner, and never otherwise."""
import importlib.util
import urllib.error
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("retry_runner", Path(__file__).parents[1] / "scripts/ci/retry_runner.py")
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)

NO_RUNNER = "The job was not acquired by Runner of type hosted even after multiple attempts"
STEPS = [{"name": "Run uv run pytest -q", "conclusion": "failure"}]


def _gh(jobs: list[dict], notes: dict[int, list[str]], fail: str = ""):
    """A stand-in for GitHub's API: answers the job list and annotations, records reruns, or fails one path."""
    calls = []

    def call(path, method="GET"):
        calls.append((method, path))
        if fail and fail in path:
            raise urllib.error.HTTPError(path, 503, "Service Unavailable", {}, None)
        if path.endswith("/rerun"):
            return None
        if "/annotations" in path:
            return [{"message": m} for m in notes.get(int(path.split("/")[-2]), [])]
        page = int(path.split("page=")[-1])
        return {"jobs": jobs[(page - 1) * 100:page * 100]}
    return call, calls


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("REPO", "rawcache/Jobsmith")
    monkeypatch.setenv("RUN", "40769864788")
    monkeypatch.setenv("ATTEMPT", "1")


def _reruns(calls):
    return [p for m, p in calls if m == "POST"]


def test_a_macos_job_that_never_got_a_runner_is_run_once_more():
    jobs = [{"id": 1, "name": "test (macos-latest)", "conclusion": "cancelled", "steps": []},
            {"id": 2, "name": "test (ubuntu-24.04)", "conclusion": "success", "steps": STEPS}]
    call, calls = _gh(jobs, {1: [NO_RUNNER, "Due to capacity constraints, jobs targeting macOS arm64 runners …"]})
    assert rr.main(call) == [1]
    assert _reruns(calls) == ["repos/rawcache/Jobsmith/actions/jobs/1/rerun"]


@pytest.mark.parametrize("job,notes", [
    ({"id": 1, "name": "test (macos-latest)", "conclusion": "failure", "steps": STEPS}, [NO_RUNNER]),   # it started
    ({"id": 1, "name": "test (macos-latest)", "conclusion": "cancelled", "steps": []}, ["Canceled by a user"]),
    ({"id": 1, "name": "test (windows-latest)", "conclusion": "cancelled", "steps": []}, [NO_RUNNER]),  # not macOS
    ({"id": 1, "name": "test (macos-latest)", "conclusion": "success", "steps": STEPS}, []),
], ids=["test-failure", "other-annotation", "not-macos", "passed"])
def test_nothing_else_is_retried(job, notes):
    call, calls = _gh([job], {1: notes})
    assert rr.main(call) == [] and _reruns(calls) == []


def test_only_once(monkeypatch):
    monkeypatch.setenv("ATTEMPT", "2")
    call, calls = _gh([{"id": 1, "name": "test (macos-latest)", "conclusion": "cancelled", "steps": []}], {1: [NO_RUNNER]})
    assert rr.main(call) == [] and calls == []


@pytest.mark.parametrize("fail", ["/jobs?", "/annotations", "/rerun"])
def test_a_github_api_error_fails_the_step_instead_of_skipping_the_retry(fail):
    call, calls = _gh([{"id": 1, "name": "test (macos-latest)", "conclusion": "cancelled", "steps": []}],
                      {1: [NO_RUNNER]}, fail=fail)
    with pytest.raises(urllib.error.HTTPError):
        rr.main(call)
    assert _reruns(calls) == ([] if fail != "/rerun" else ["repos/rawcache/Jobsmith/actions/jobs/1/rerun"])


def test_the_real_api_call_raises_on_an_http_error(monkeypatch):
    def refuse(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", {}, None)
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(rr.urllib.request, "urlopen", refuse)
    with pytest.raises(urllib.error.HTTPError):
        rr.api("repos/rawcache/Jobsmith/check-runs/1/annotations")


def test_a_macos_job_on_a_later_page_is_found():
    jobs = [{"id": n, "name": f"test (linux-{n})", "conclusion": "success", "steps": STEPS} for n in range(2, 152)]
    jobs.append({"id": 1, "name": "test (macos-latest)", "conclusion": "cancelled", "steps": []})
    call, calls = _gh(jobs, {1: [NO_RUNNER]})
    assert rr.main(call) == [1]
    assert [p.split("page=")[-1] for m, p in calls if "/jobs?" in p] == ["1", "2"]


class _Reply:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


def test_the_real_api_call_reads_json_and_an_empty_reply(monkeypatch):
    sent = []
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(rr.urllib.request, "urlopen", lambda req, timeout: sent.append(req) or _Reply(b'[{"message": "m"}]'))
    assert rr.api("repos/r/check-runs/1/annotations") == [{"message": "m"}]
    assert sent[0].full_url == "https://api.github.com/repos/r/check-runs/1/annotations"
    assert sent[0].get_header("Authorization") == "Bearer x"
    monkeypatch.setattr(rr.urllib.request, "urlopen", lambda req, timeout: sent.append(req) or _Reply(b""))
    assert rr.api("repos/r/actions/jobs/1/rerun", "POST") is None and sent[1].get_method() == "POST"
