"""Identify the applicant tracking system (ATS) behind a job URL."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

ATS_PATTERNS = [
    ("greenhouse", r"greenhouse\.io"),
    ("lever", r"jobs\.(eu\.)?lever\.co"),
    ("ashby", r"ashbyhq\.com"),
    ("workday", r"myworkday(jobs|site)\.com"),
    ("icims", r"icims\.com"),
    ("smartrecruiters", r"smartrecruiters\.com"),
    ("oracle", r"oraclecloud\.com"),
    ("workable", r"workable\.com"),
    ("eightfold", r"eightfold\.ai"),
    ("rippling", r"rippling\.com"),
    ("jobvite", r"jobvite\.com"),
    ("taleo", r"taleo\.net"),
    ("successfactors", r"successfactors\.(com|eu)|jobs\.sap\.com"),
]

# Which ATSes Jobsmith can fill end-to-end today.
SUPPORTED = {"greenhouse", "ashby", "lever"}


def detect(url: str) -> str:
    for name, pat in ATS_PATTERNS:
        if re.search(pat, url, re.I):
            return name
    return "other"


def greenhouse_ids(url: str) -> tuple[str | None, str | None, str]:
    """Return (board_token, job_id, region) for a Greenhouse URL. region is '' or 'eu'."""
    u = urlparse(url)
    region = "eu" if ".eu." in u.netloc else ""
    qs = parse_qs(u.query)
    m = re.search(r"/([^/]+)/jobs/(\d+)", u.path)
    if m and m.group(1) != "embed":
        return m.group(1), m.group(2), region
    job_id = (qs.get("token") or qs.get("gh_jid") or [None])[0]
    board = (qs.get("for") or [None])[0]
    return board, job_id, region


def lever_ids(url: str) -> tuple[str | None, str | None]:
    m = re.search(r"lever\.co/([^/]+)/([0-9a-f-]{36})", url)
    return (m.group(1), m.group(2)) if m else (None, None)


def ashby_ids(url: str) -> tuple[str | None, str | None]:
    m = re.search(r"ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", url)
    return (m.group(1), m.group(2)) if m else (None, None)


def clean_url(url: str) -> str:
    """Strip tracking params SimplifyJobs adds (utm_*, ref=Simplify)."""
    u = urlparse(url)
    keep = [(k, v) for k, vs in parse_qs(u.query).items() for v in vs
            if not k.lower().startswith("utm_") and k.lower() not in ("ref", "source")]
    from urllib.parse import urlencode
    return u._replace(query=urlencode(keep)).geturl()
