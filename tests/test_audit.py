"""The per-application audit trail: what each submission sent and where every answer came from."""
from fastapi.testclient import TestClient

from conftest import FIXTURES
from jobsmith import audit, db, draft, guardrails, profile, runner, sources


async def _job_with_every_kind_of_answer() -> str:
    await profile.ingest_document(FIXTURES / "sample_resume.tex")
    profile.set_answer("work_authorized_us", "Yes", confirmed=True)
    jetson = [f["id"] for f in profile.facts() if "Jetson" in f["text"]]
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/1", "Acme Robotics", "SWE Intern")
    fields = [{"field": f, "label": l, "qtype": q} for f, l, q in (
        ("auth", "Are you authorized to work in the US?", "select"), ("why", "Why Acme Robotics?", "textarea"),
        ("story", "Tell us about a project you're proud of", "textarea"), ("heard", "How did you hear about us?", "text"),
        ("edited", "What's your favorite robot?", "text"), ("made_up", "Describe your leadership style", "textarea"),
        ("blank", "Anything else?", "textarea"), ("resume", "Resume", "file"), ("nope", "Pronouns", "text"))]
    draft.save_results(jid, fields, {
        "auth": {"kind": "answer_bank", "canon": "work_authorized_us", "answer": "Yes", "confidence": 1.0},
        "why": {"kind": "generated", "answer": "I deployed a detection model on NVIDIA Jetson Nano.",
                "fact_ids": jetson, "confidence": 0.9},
        "story": {"kind": "voice", "answer": "When I built the rover, I learned to test early and often.",
                  "rationale": "Your own words, from essay.txt", "confidence": 0.8},
        "heard": {"kind": "learned", "answer": "LinkedIn", "rationale": "Reused your approved answer (Globex)",
                  "confidence": 0.9},
        "edited": {"kind": "generated", "answer": "AI's guess", "confidence": 0.9},
        "made_up": {"kind": "generated", "answer": "I lead with empathy and data.", "confidence": 0.9},
        "blank": {"kind": "generated", "answer": "", "confidence": 0},
        "resume": {"kind": "file", "canon": "resume", "answer": "primary resume", "confidence": 1.0},
        "nope": {"kind": "generated", "answer": "they/them", "confidence": 0.9},
    })
    db.x("UPDATE drafts SET final_answer='Spot, from Boston Dynamics', verdict='green' WHERE job_id=? AND field='edited'",
         (jid,))
    db.x("UPDATE drafts SET verdict='red' WHERE job_id=? AND field='nope'", (jid,))
    return jid


async def test_each_answer_records_where_it_came_from():
    jid = await _job_with_every_kind_of_answer()
    runner.mark_submitted(jid)
    [sub] = audit.for_job(jid)
    assert sub["sent_by"] == "you" and sub["confirmed"] is True
    by = {f["field"]: f for f in sub["fields"]}
    assert set(by) == {"auth", "why", "story", "heard", "edited", "made_up", "resume"}   # blank and red-flagged weren't sent
    assert by["auth"]["source"] == "profile" and by["auth"]["detail"][0]["text"] == "Yes"
    assert by["auth"]["detail"][0]["ref"].startswith("Profile: ")
    assert by["why"]["source"] == "resume" and "Jetson" in by["why"]["detail"][0]["text"]
    assert by["story"]["source"] == "writing" and "essay.txt" in by["story"]["detail"][0]["ref"]
    assert by["heard"]["source"] == "approved"
    assert by["edited"]["source"] == "you" and by["edited"]["answer"] == "Spot, from Boston Dynamics"
    assert by["resume"]["source"] == "file" and by["resume"]["answer"] == "Your resume PDF"
    assert by["why"]["detail"][0]["fact_id"].startswith("f_") and by["why"]["detail"][0]["ref"] == "sample_resume.tex"
    assert by["made_up"]["source"] == "none" and by["made_up"]["traces"] is False
    assert all(f["traces"] for k, f in by.items() if k != "made_up")
    assert sub["untraced"] == 1
    assert by["heard"]["kind_check"] == "ok"


async def test_the_trail_is_a_snapshot_and_each_submission_keeps_its_own():
    jid = await _job_with_every_kind_of_answer()
    runner.mark_submitted(jid)
    db.x("UPDATE drafts SET final_answer='Changed later' WHERE job_id=? AND field='heard'", (jid,))
    [sub] = audit.for_job(jid)
    assert next(f for f in sub["fields"] if f["field"] == "heard")["answer"] == "LinkedIn"
    runner.mark_submitted(jid)                    # sent again (a second submission is its own record)
    newest, oldest = audit.for_job(jid)
    assert next(f for f in newest["fields"] if f["field"] == "heard")["answer"] == "Changed later"
    assert next(f for f in oldest["fields"] if f["field"] == "heard")["answer"] == "LinkedIn"


async def test_autopilot_submissions_and_unconfirmed_ones_are_labelled():
    jid = await _job_with_every_kind_of_answer()
    guardrails.claim(jid)
    runner.mark_submitted(jid)
    assert audit.for_job(jid)[0]["sent_by"] == "autopilot"
    other = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/2", "Acme Robotics", "HW Intern")
    draft.save_results(other, [{"field": "auth", "label": "Authorized?", "qtype": "text"}],
                       {"auth": {"kind": "answer_bank", "canon": "work_authorized_us", "answer": "Yes", "confidence": 1}})
    guardrails.claim(other)
    guardrails.abandon(other, "the tab closed")
    [sub] = audit.for_job(other)
    assert sub["sent_by"] == "autopilot" and sub["confirmed"] is False


async def test_the_dashboard_shows_and_exports_the_trail():
    from jobsmith.api import app
    jid = await _job_with_every_kind_of_answer()
    runner.mark_submitted(jid)
    c = TestClient(app)
    r = c.get(f"/api/jobs/{jid}/audit")
    assert r.status_code == 200 and r.json()["submissions"][0]["untraced"] == 1
    r = c.get(f"/api/jobs/{jid}/audit.json")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="jobsmith-audit-Acme-Robotics-SWE-Intern.json"'
    body = r.json()
    assert body["job"]["company"] == "Acme Robotics" and len(body["submissions"][0]["fields"]) == 7
    assert c.get("/api/jobs/nope/audit").status_code == 404


async def test_the_kind_check_result_is_kept():
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/3", "Acme", "Intern")
    draft.save_results(jid, [{"field": "where", "label": "From where do you intend to work?", "qtype": "text"}],
                       {"where": {"kind": "generated", "confidence": 0.9,
                                  "answer": "I want to join because I love robots. I built many of them."}})
    runner.mark_submitted(jid)
    [f] = audit.for_job(jid)[0]["fields"]
    assert f["kind_check"] == "asks where, but the answer isn't a place"


async def test_the_trail_is_what_the_fill_set_not_later_drafts():
    jid = await _job_with_every_kind_of_answer()
    audit.capture(jid, {"auth", "why", "heard", "resume"})   # "story" failed to fill, so it wasn't sent
    db.x("UPDATE drafts SET answer='Redrafted later' WHERE job_id=? AND field='why'", (jid,))
    guardrails.claim(jid)
    runner.mark_submitted(jid)
    [sub] = audit.for_job(jid)
    assert sub["basis"] == "filled" and sub["note"] == "" and sub["sent_by"] == "autopilot"
    by = {f["field"]: f for f in sub["fields"]}
    assert set(by) == {"auth", "why", "heard", "resume"}
    assert by["why"]["answer"].startswith("I deployed a detection model")


async def test_you_submitting_a_filled_form_says_browser_edits_arent_shown():
    jid = await _job_with_every_kind_of_answer()
    audit.capture(jid, {"why"})
    runner.mark_submitted(jid)
    [sub] = audit.for_job(jid)
    assert sub["sent_by"] == "you" and "changed in the browser" in sub["note"]


async def test_a_form_jobsmith_didnt_fill_is_marked_as_drafts():
    jid = await _job_with_every_kind_of_answer()
    runner.mark_submitted(jid)
    [sub] = audit.for_job(jid)
    assert sub["basis"] == "drafted" and "didn't fill this form" in sub["note"]


def test_a_submission_with_nothing_recorded_still_appears():
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/9", "Acme", "Intern")
    runner.mark_submitted(jid)
    other = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/10", "Acme", "Intern 2")
    guardrails.claim(other)
    guardrails.abandon(other, "the tab closed")
    [a], [b] = audit.for_job(jid), audit.for_job(other)
    assert a["fields"] == [] and a["confirmed"] is True
    assert b["fields"] == [] and b["confirmed"] is False


async def test_a_profile_answer_that_changed_since_drafting_doesnt_trace():
    jid = await _job_with_every_kind_of_answer()
    profile.set_answer("work_authorized_us", "No", confirmed=True)
    runner.mark_submitted(jid)
    auth = next(f for f in audit.for_job(jid)[0]["fields"] if f["field"] == "auth")
    assert auth["answer"] == "Yes" and auth["traces"] is False
    assert auth["detail"][0]["ref"].endswith("says something else") and auth["detail"][0]["text"] == "No"


async def test_two_fields_with_one_label_only_the_one_that_filled_is_recorded():
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/11", "Acme", "Intern")
    draft.save_results(jid, [{"field": "start_1", "label": "Start date", "qtype": "text"},
                             {"field": "start_2", "label": "Start date", "qtype": "text"}],
                       {"start_1": {"kind": "answer_bank", "canon": "start", "answer": "May 2027", "confidence": 1},
                        "start_2": {"kind": "answer_bank", "canon": "start", "answer": "June 2027", "confidence": 1}})
    audit.capture(jid, {"start_1"})
    runner.mark_submitted(jid)
    assert [f["field"] for f in audit.for_job(jid)[0]["fields"]] == ["start_1"]


def test_profile_only_fills_trace_only_to_confirmed_answers():
    profile.set_answer("hispanic_latino", "No", confirmed=False)
    profile.set_answer("us_citizen", "Yes", confirmed=True)
    ans = profile.answers()
    hisp = audit.implicit_row({"field": "hispanic_ethnicity", "label": "Hispanic/Latino", "canon": "hispanic_latino",
                               "profile": "No", "answer": "No"}, ans)
    assert hisp["traces"] is False and hisp["detail"][0]["ref"].endswith("(not confirmed yet)")
    country = audit.implicit_row({"field": "country", "label": "Phone country", "canon": "country",
                                  "profile": "United States", "answer": "United States +1"}, ans)
    assert country["traces"] is True and country["answer"] == "United States +1"
    assert country["detail"][0]["ref"].startswith("Profile: ")


def test_country_traces_to_confirmed_citizenship_over_an_unconfirmed_country():
    profile.set_answer("country", "United States", confirmed=False)
    profile.set_answer("us_citizen", "Yes", confirmed=True)
    row = audit.implicit_row({"field": "country", "label": "Phone country", "canon": "country",
                              "profile": "United States", "answer": "United States +1"}, profile.answers())
    assert row["traces"] is True and row["detail"][0]["text"] == "Yes"


def test_an_unconfirmed_demographic_answer_is_never_drafted():
    profile.set_answer("hispanic_latino", "No", confirmed=False)
    job = {"id": "x", "company": "Acme", "description": ""}
    r = draft.deterministic({"field": "q", "label": "Are you Hispanic/Latino?", "qtype": "select",
                             "options": ["Yes", "No", "Decline to self-identify"], "required": True}, profile.answers(), job)
    assert r["answer"] == "" and "Confirm your demographic answers" in r["issues"][0]
    profile.set_answer("hispanic_latino", "No", confirmed=True)
    r = draft.deterministic({"field": "q", "label": "Are you Hispanic/Latino?", "qtype": "select",
                             "options": ["Yes", "No", "Decline to self-identify"], "required": True}, profile.answers(), job)
    assert r["answer"] == "No" and not r["issues"]


def test_a_required_unconfirmed_demographic_holds_autopilot():
    profile.set_answer("gender", "Woman", confirmed=False)
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/12", "Acme", "Intern")
    f = {"field": "g", "label": "Gender", "qtype": "select", "options": ["Man", "Woman", "Decline to self-identify"],
         "required": True}
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    draft.save_results(jid, [f], {"g": draft.deterministic(f, profile.answers(), job)})
    ready = draft.readiness(jid)
    assert not ready["ready"] and ready["blockers"][0].startswith("Gender: ")


async def test_legal_and_employment_answers_carry_their_source_in_the_trail():
    await profile.ingest_document(FIXTURES / "sample_resume.tex")
    profile.set_answer("work_authorized_us", "Yes", confirmed=True)
    jid = sources.add_job_url("https://job-boards.greenhouse.io/northwind/jobs/1", "Northwind Labs", "Intern")
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    fields = [{"field": "auth", "label": "Are you authorized to work in the US?", "qtype": "select",
               "options": ["Yes", "No"], "required": True},
              {"field": "worked", "label": "Have you ever worked for Northwind Labs before?", "qtype": "select",
               "options": ["Yes", "No"], "required": True}]
    ans = profile.answers()
    draft.save_results(jid, fields, {f["field"]: draft.deterministic(f, ans, job) for f in fields})
    runner.mark_submitted(jid)
    by = {f["field"]: f for f in audit.for_job(jid)[0]["fields"]}
    assert by["auth"]["detail"][0]["ref"] == "Profile: Authorized to work in the US? (you confirmed it)"
    assert by["auth"]["traces"] is True
    assert by["worked"]["answer"] == "Yes" and by["worked"]["source"] == "resume" and by["worked"]["traces"] is True
    assert by["worked"]["detail"][0]["ref"].startswith("Your resume lists Northwind Labs: Northwind Labs | Boston, MA")


async def test_a_worked_here_no_that_nothing_backs_doesnt_trace():
    """An old draft that says "No" with nothing confirmed behind it (the blanket default this replaced)."""
    jid = sources.add_job_url("https://job-boards.greenhouse.io/figma/jobs/1", "Figma", "Intern")
    draft.save_results(jid, [{"field": "worked", "label": "Have you ever worked for Figma before?", "qtype": "select",
                              "options": ["Yes", "No"], "required": True}],
                       {"worked": {"kind": "answer_bank", "canon": "previously_employed", "answer": "No", "confidence": 1}})
    runner.mark_submitted(jid)
    [worked] = audit.for_job(jid)[0]["fields"]
    assert worked["traces"] is False and worked["detail"][0]["ref"] == "Nothing you've confirmed says this"


async def test_an_unconfirmed_legal_answer_traces_only_when_you_approved_it_and_it_still_matches():
    await profile.ingest_document(FIXTURES / "sample_resume.tex")        # sponsorship "No", read from the resume
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/3", "Acme Robotics", "Intern")
    f = {"field": "spons", "label": "Will you now or in the future require visa sponsorship?", "qtype": "select",
         "options": ["Yes", "No"], "required": True}
    draft.save_results(jid, [f], {"spons": draft.deterministic(f, profile.answers(), {"company": "Acme Robotics"})})
    trail = lambda: next(x for x in audit.snapshot(jid) if x["field"] == "spons")
    assert trail()["answer"] == "No" and trail()["traces"] is False
    db.x("UPDATE drafts SET verdict='green' WHERE job_id=?", (jid,))                 # you approved it here
    assert trail()["traces"] is True
    profile.set_answer("needs_sponsorship", "Yes", confirmed=True)                 # and then your profile changed
    assert trail()["traces"] is False and trail()["detail"][0]["ref"].endswith("says something else")
