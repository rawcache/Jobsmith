"""'Report this form' (jobsmith/formreport.py): a pre-filled GitHub issue about a form, for the user to read and post.
Only the form's questions go in: never a value, the page's query string, or a contact detail in a question's words."""
import json
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from jobsmith import api, db, formreport, sources


def _issue(link: str) -> tuple[str, str, str]:
    u = urlsplit(link)
    q = parse_qs(u.query)
    return f"{u.scheme}://{u.netloc}{u.path}", q["title"][0], q["body"][0]


FIELDS = [{"label": "First Name", "qtype": "text", "required": True, "value": "Alex", "filled": True},
          {"label": "Questions? Write to recruiting@northwind.test or call (617) 555-0142", "qtype": "text"},
          {"label": "Requisition 4412097 | Austin", "qtype": "select", "options": ["Yes", "No"]},
          {"label": "Why us?", "type": "textarea", "answer": "Because I built a robot arm."}]


def test_the_issue_has_the_questions_and_nothing_typed_or_personal():
    where, title, body = _issue(formreport.issue_url(
        "https://jobs.northwind.test/apply/78?token=abc123&email=alex.rivera%40example.com#step2", FIELDS, "Northwind"))
    assert where == "https://github.com/rawcache/Jobsmith/issues/new" and title == "Form report: jobs.northwind.test"
    assert "First Name" in body and "Why us?" in body and "Yes, No" in body and "textarea" in body
    for gone in ("Alex", "robot arm", "token", "abc123", "alex.rivera", "step2", "recruiting@northwind.test",
                 "555-0142", "4412097"):
        assert gone not in body, gone
    assert "`/apply/78`" in body and "[email]" in body and "[number]" in body
    assert "| Requisition [number] / Austin |" in body                 # a | in a question can't break the table


def test_a_long_form_is_cut_to_a_link_github_takes_and_says_how_many_are_left_out():
    fields = [{"label": f"Question {i}: " + "tell us about a time you did something hard " * 3, "qtype": "textarea",
               "options": [f"Option {j}" for j in range(12)]} for i in range(200)]
    link = formreport.issue_url("https://jobs.northwind.test/apply", fields)
    assert len(link) <= formreport.MAX_URL
    _, _, body = _issue(link)
    assert "(200 fields;" in body and "more |" in body and "and 4 more" in body      # 12 choices: 8 shown


def test_a_saved_applications_questions_lose_their_hidden_fields_and_answers():
    qs = [{"label": "Email", "qtype": "text", "required": 1, "answer": "alex.rivera@example.com"},
          {"label": "csrf", "qtype": "hidden", "value": "f3a9c2d1"}]
    assert formreport.from_questions(qs) == [{"label": "Email", "qtype": "text", "required": True, "options": []}]


def test_the_engine_builds_the_link_for_the_panel_and_for_a_saved_application():
    c = TestClient(api.app)
    r = c.post("/api/ext/form-report", json={"url": "https://jobs.northwind.test/apply?ref=x", "site_name": "Northwind",
                                             "fields": FIELDS}).json()
    _, _, body = _issue(r["url"])
    assert "First Name" in body and "Alex" not in body and "ref=x" not in body

    jid = sources.add_job_url("https://job-boards.greenhouse.io/northwind/jobs/78", "Northwind Labs", "Robotics Intern")
    db.x("UPDATE jobs SET questions=? WHERE id=?", (json.dumps(
        [{"label": "LinkedIn Profile", "qtype": "text", "required": False}, {"label": "t", "qtype": "hidden"}]), jid))
    _, title, body = _issue(c.get(f"/api/jobs/{jid}/form-report").json()["url"])
    assert title == "Form report: job-boards.greenhouse.io" and "LinkedIn Profile" in body and "(1 field;" in body
    assert c.get("/api/jobs/nope/form-report").status_code == 404


def test_contact_details_written_into_the_pages_path_are_masked_even_encoded():
    _, _, body = _issue(formreport.issue_url("https://jobs.northwind.test/apply/alex.rivera%40example.com/"
                                            "%2B1%20617%20555%200142/7781234", FIELDS))
    assert "alex.rivera" not in body and "555" not in body and "7781234" not in body
    assert "`/apply/[email]/[number]/[number]`" in body

