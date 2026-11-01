"""Emailed codes Jobsmith may type for you (decision of 2026-10-31): only the code a job site emails to verify an
application right after Jobsmith pressed its Submit. From the inbox you connected; from that application's job site;
within 15 minutes of the click; naming the company or the role; never a sign-in, two-step, password-reset or account
code. Anything else waits for you."""
import time

import pytest

from conftest import FIXTURES
from jobsmith import guardrails, outcomes, runner, scheduler, sources
from test_fill import page  # noqa: F401  (a headless browser tab)

GH_SUBJECT = "Security code for your application to Acme Robotics"
GH_BODY = ("Hi Alex, Copy and paste this code into the security code field on your application: kD8sQw2Z "
           "After you enter the code, resubmit your application.")
JOB = {"company": "Acme Robotics", "title": "Software Engineering Intern", "ats": "greenhouse",
       "url": "https://job-boards.greenhouse.io/acme/jobs/123"}


def _mail(clicked: float, **kw) -> dict:
    return {"from": "Acme Robotics <no-reply@us.greenhouse-mail.io>", "subject": GH_SUBJECT, "body": GH_BODY,
            "when": clicked + 40, **kw}


def test_the_code_greenhouse_sends_for_this_application_is_used():
    now = time.time()
    assert outcomes.application_code([_mail(now)], JOB, now) == ("kD8sQw2Z", [])
    role = _mail(now, subject="Your security code", body="Your code for the Software Engineering Intern application: 4829135")
    assert outcomes.application_code([role], JOB, now)[0] == "4829135"            # names the role, not the company
    own = dict(JOB, ats="unknown", url="https://careers.acme-robotics.com/apply/7")
    mine = _mail(now, **{"from": "Acme Careers <jobs@mail.acme-robotics.com>"})
    assert outcomes.application_code([mine], own, now)[0] == "kD8sQw2Z"            # the application page's own site


@pytest.mark.parametrize("change, why", [
    ({"from": "Acme Robotics <no-reply@acme-robotics-careers.net>"}, "not Acme Robotics job site"),
    ({"from": "Greenhouse <no-reply@greenhouse-mail.io.evil.test>"}, "not Acme Robotics job site"),
    ({"when_after": 16 * 60}, "not within 15 minutes of Submit"),
    ({"when_after": -10 * 60}, "not within 15 minutes of Submit"),
    ({"subject": "Your sign-in code for Acme Robotics"}, "sign-in or account code"),
    ({"subject": "Acme Robotics: your two-step verification code"}, "sign-in or account code"),
    ({"subject": "Reset your password: code for Acme Robotics"}, "sign-in or account code"),
    ({"subject": "Verify your email to create your account with Acme Robotics"}, "sign-in or account code"),
    ({"subject": "Security code for your application to Northwind Labs",
      "body": "Copy and paste this code into the security code field on your application: Zq81mKp3"},
     "doesn't name Acme Robotics"),                                                  # a code for another application
])
def test_a_code_that_breaks_any_rule_is_refused(change, why):
    now = time.time()
    after = change.pop("when_after", 40)
    msg = _mail(now, when=now + after, **change)
    code, refused = outcomes.application_code([msg], JOB, now)
    assert code is None and len(refused) == 1 and why in refused[0], refused


def test_no_code_without_jobsmiths_own_submit_click():
    code, refused = outcomes.application_code([_mail(time.time())], JOB, None)
    assert code is None and "Submit wasn't pressed by Jobsmith" in refused[0]


def test_the_newest_matching_email_wins_and_others_are_named():
    now = time.time()
    other = _mail(now, when=now + 90, subject="Security code for your application to Northwind Labs",
                  body="Copy and paste this code into the security code field on your application: Zq81mKp3")
    code, refused = outcomes.application_code([_mail(now), other], JOB, now)
    assert code == "kD8sQw2Z" and len(refused) == 1 and "Northwind" in refused[0]


async def _watch(page, monkeypatch, inbox: list[dict], click: bool = True, prompt_page: str = "mock_code.html"):
    """The live tab after Submit on the saved code form, with the inbox stood in for: which codes were typed."""
    jid = sources.add_job_url(JOB["url"], JOB["company"], JOB["title"])
    typed, read = [], []
    monkeypatch.setattr(outcomes, "email_ready", lambda: True)
    monkeypatch.setattr(outcomes, "_recent", lambda since: read.append(since) or inbox)
    monkeypatch.setattr(scheduler, "notify", lambda *a, **k: None)

    async def live_code(job_id, code):
        typed.append(code)
        return {"ok": True}
    monkeypatch.setattr(runner, "live_code", live_code)
    await page.goto((FIXTURES / prompt_page).resolve().as_uri())
    if click:
        guardrails.claim(jid)
    await page.click("#submit")
    run = runner.Run(jid, "fill")
    job = {**JOB, "id": jid}
    await runner._watch(jid, page, FIXTURES, run, job, time.time() + 3)
    guardrails.release(jid)
    guardrails._clicked_at.pop(jid, None)
    return typed, read, run


async def test_the_runner_types_this_applications_code_from_your_email(page, monkeypatch):
    typed, _, _ = await _watch(page, monkeypatch, [_mail(time.time())])
    assert typed == ["kD8sQw2Z"]


@pytest.mark.parametrize("change", [
    {"from": "Acme Robotics <no-reply@acme-robotics-careers.net>"},
    {"when_after": 20 * 60},
    {"subject": "Your login code for Acme Robotics"},
    {"subject": "Security code for your application to Northwind Labs"},
])
async def test_the_runner_leaves_any_other_code_for_you(page, monkeypatch, change):
    after = change.pop("when_after", 40)
    now = time.time()
    typed, read, _ = await _watch(page, monkeypatch, [_mail(now, when=now + after, **change)])
    assert typed == [] and read                                       # looked, found nothing it may use


async def test_the_runner_never_reads_email_for_a_submit_it_didnt_press(page, monkeypatch):
    typed, read, _ = await _watch(page, monkeypatch, [_mail(time.time())], click=False)
    assert typed == [] and read == []
