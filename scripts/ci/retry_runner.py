"""Run a macOS tests job once more when GitHub couldn't find a hosted runner for it.

Called by .github/workflows/retry-runner.yml when a `tests` run finishes. Only that failure is retried: the job ran
no step and carries GitHub's "was not acquired by Runner" annotation, so a test failure (or anything else that went
wrong after the job started) never is. Once only: the rerun is the run's second attempt, and later attempts are
skipped. Any GitHub API error fails this script, so a lookup that didn't work never reads as "nothing to retry"."""
from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable

NO_RUNNER = "was not acquired by Runner"


def to_retry(jobs: list[dict], annotations: Callable[[int], list[str]]) -> list[int]:
    """The macOS jobs in this attempt that never got a runner."""
    out = []
    for j in jobs:
        never_started = j.get("conclusion") in ("cancelled", "failure") and not j.get("steps")
        if j["name"].startswith("test (macos") and never_started and any(NO_RUNNER in m for m in annotations(j["id"])):
            out.append(j["id"])
    return out


def api(path: str, method: str = "GET") -> dict | list | None:
    req = urllib.request.Request(f"https://api.github.com/{path}", method=method, headers={
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as r:     # an HTTP error raises: the step fails, nothing is skipped
        body = r.read()
    return json.loads(body) if body else None


def all_jobs(call: Callable, repo: str, run: str) -> list[dict]:
    """Every job in the run's first attempt, page by page."""
    jobs, page = [], 1
    while True:
        got = call(f"repos/{repo}/actions/runs/{run}/attempts/1/jobs?per_page=100&page={page}")["jobs"]
        jobs += got
        if len(got) < 100:
            return jobs
        page += 1


def main(call: Callable = api) -> list[int]:
    repo, run, attempt = os.environ["REPO"], os.environ["RUN"], os.environ["ATTEMPT"]
    if attempt != "1":
        print(f"Attempt {attempt}: already retried once, not again")
        return []
    jobs = all_jobs(call, repo, run)
    ids = to_retry(jobs, lambda i: [a["message"] for a in call(f"repos/{repo}/check-runs/{i}/annotations?per_page=100")])
    for i in ids:
        print(f"macOS job {i} never got a runner: running it once more")
        call(f"repos/{repo}/actions/jobs/{i}/rerun", "POST")
    if not ids:
        print("No macOS job failed for want of a runner: nothing to retry")
    return ids


if __name__ == "__main__":
    main()
