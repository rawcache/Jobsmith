import asyncio
import json

import pytest

from jobsmith import classify, db, draft, jobdetail, learn, match, profile, sources
from conftest import FIXTURES


async def _load_profile():
    return await profile.ingest_document(FIXTURES / "sample_resume.tex")


# --------------------------------------------------------------------------- profile
async def test_latex_resume_becomes_facts_and_answer_bank():
    res = await _load_profile()
    assert res["method"] == "exact (LaTeX)"
    assert res["facts_added"] >= 10
    assert any("alex.r@example.edu" in w for w in res["warnings"])   # mailto != displayed email
    texts = [f["text"] for f in profile.facts()]
    assert any("600,000+ images" in t for t in texts)
    assert any(t.startswith("Programming: C, C++") for t in texts)
    assert not any("should be ignored" in t for t in texts)
    assert not any("leftmargin" in t for t in texts)
    a = profile.answers()
    assert a["first_name"]["value"] == "Alex" and a["last_name"]["value"] == "Rivera"
    assert a["work_authorized_us"]["value"] == "Yes" and a["needs_sponsorship"]["value"] == "No"
    assert a["gpa"]["value"] == "3.71" and a["graduation_year"]["value"] == "2027"
    assert a["school"]["value"] == "Example Institute of Technology"
    assert a["location"]["value"] == "Boston, MA"
    assert a["major"]["value"] == "Computer Engineering" and a["degree"]["value"] == "Bachelor's"
    assert a["first_name"]["confirmed"] == 0   # inferred until the user confirms


# --------------------------------------------------------------------------- classify
@pytest.mark.parametrize("label,key", [
    ("First Name", "first_name"), ("Preferred First Name", "preferred_name"),
    ("Will you now or in the future require visa sponsorship?", "needs_sponsorship"),
    ("Are you legally authorized to work in the United States?", "work_authorized_us"),
    ("What is your cumulative GPA?", "gpa"), ("Expected graduation year", "graduation_year"),
    ("LinkedIn Profile", "linkedin"), ("How did you hear about us?", "how_heard"),
    ("Why do you want to work here?", None),
    ("How did you first learn about Affirm as an employer?", "how_heard"),
    ("Which U.S. State or Canadian Province do you reside in?", "state"),
    ("Other Links", "other_links"), ("Current Company", "current_company"),
    ("Name Pronunciation", "name_pronunciation"),
])
def test_canon(label, key):
    assert classify.canon_for(label) == key


def test_pick_option():
    gpa = ["Below 3.0", "3.0 - 3.49", "3.5 - 3.79", "3.8 - 4.0"]
    assert classify.pick_option("3.71", gpa) == "3.5 - 3.79"
    assert classify.pick_option("3.9", ["3.5+", "Below 3.5"]) == "3.5+"
    assert classify.pick_option("No", ["Yes, I will", "No, I will not"]) == "No, I will not"
    assert classify.pick_option("Decline to self-identify", ["Male", "I don't wish to answer"]) == "I don't wish to answer"
    assert classify.pick_option("2027", ["2026", "2027", "2028"]) == "2027"
    vet = ["I identify as one or more of the classifications of protected veteran", "I am not a protected veteran",
           "I don't wish to answer"]
    assert classify.pick_option("No", vet) == "I am not a protected veteran"
    dis = ["Yes, I have a disability (or previously had a disability)", "No, I do not have a disability",
           "I do not want to answer"]
    assert classify.pick_option("No", dis) == "No, I do not have a disability"
    assert classify.pick_option("Asian (Indian)", ["White", "Asian", "Two or More Races"]) == "Asian"
    assert classify.pick_option("Asian (Indian)", ["East Asian", "South Asian", "White"]) == "South Asian"
    assert classify.pick_option("he/him", ["He/him/his", "She/her/hers"]) == "He/him/his"
    assert classify.pick_option("No", ["I have not previously been employed at Affirm",
                                       "I have been employed at Affirm as an intern"]).startswith("I have not")


# --------------------------------------------------------------------------- sources & matching
async def test_sync_and_score(monkeypatch):
    await _load_profile()
    listings = [
        {"company_name": "Acme Robotics", "title": "Software Engineering Intern", "url": "https://job-boards.greenhouse.io/acme/jobs/123?utm_source=Simplify&ref=Simplify",
         "locations": ["Boston, MA"], "terms": ["Summer 2027"], "category": "Software", "active": True, "is_visible": True,
         "sponsorship": "Other", "date_posted": 1790000000, "degrees": [], "id": "a"},
        {"company_name": "OldCo", "title": "Marketing Intern", "url": "https://oldco.wd5.myworkdayjobs.com/x/job/1",
         "locations": ["NYC"], "terms": ["Summer 2026"], "category": "Marketing", "active": True, "is_visible": True,
         "sponsorship": "Other", "date_posted": 1700000000, "degrees": [], "id": "b"},
    ]

    async def fake_fetch(owner, repo, client):
        return listings
    monkeypatch.setattr(sources, "_fetch_listings_json", fake_fetch)
    src = sources.add_source("https://github.com/SimplifyJobs/Summer2027-Internships")
    res = await sources.sync_source(src)
    assert res["added"] == 2
    match.rescore()
    jobs = {j["company"]: db.decode(j) for j in db.q("SELECT * FROM jobs")}
    assert jobs["Acme Robotics"]["ats"] == "greenhouse"
    assert "utm_source" not in jobs["Acme Robotics"]["url"]
    assert jobs["OldCo"]["ats"] == "workday"
    assert jobs["Acme Robotics"]["fit_score"] > jobs["OldCo"]["fit_score"] + 30
    # re-sync updates instead of duplicating
    res2 = await sources.sync_source(src)
    assert res2["added"] == 0 and res2["updated"] == 2


def test_greenhouse_normalize():
    data = json.loads((FIXTURES / "greenhouse_job.json").read_text())
    fields = jobdetail.normalize_greenhouse(data)
    by = {f["field"]: f for f in fields}
    assert by["resume"]["qtype"] == "file" and by["resume"]["alt_field"] == "resume_text"
    assert by["question_1002"]["options"][2] == "3.5 - 3.79"
    assert by["gender"]["section"] == "eeo"
    assert "latitude" not in by and by["location"]["qtype"] == "text"
    assert "school--0" in by


# --------------------------------------------------------------------------- drafting
async def _setup_job():
    await _load_profile()
    data = json.loads((FIXTURES / "greenhouse_job.json").read_text())
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/123", "Acme Robotics", "SWE Intern")
    db.x("UPDATE jobs SET description=?, questions=? WHERE id=?",
         (jobdetail.html_to_text(data["content"]), db.enc(jobdetail.normalize_greenhouse(data)), jid))
    return jid


def _facts_with(substr):
    return [f["id"] for f in profile.facts() if substr in f["text"]]


async def test_draft_uses_answer_bank_and_validates_grounding(fake_llm):
    jid = await _setup_job()
    jetson = _facts_with("Jetson")

    def responder(system, prompt):
        assert "FACTS (cite by id)" in prompt and "Acme Robotics" in prompt
        assert "question_1003" not in prompt.split("QUESTIONS TO ANSWER:")[1]  # sponsorship is answer-bank, not AI
        return {"answers": [
            {"field": "question_1004", "answer": "I deployed a detection model on NVIDIA Jetson Nano with sub-200ms "
             "inference at 30 FPS, and I improved accuracy by 45%.", "fact_ids": jetson + ["f_fake"], "confidence": 0.9},
            {"field": "question_1005", "answer": "No", "fact_ids": [], "confidence": 0.3},
            {"field": "cover_letter", "answer": "Dear team, I built an image pipeline.", "fact_ids": _facts_with("600,000"),
             "confidence": 0.8},
        ]}
    fake_llm(responder)
    res = await draft.draft_job(jid, research=False)
    assert res["error"] is None
    d = {x["field"]: x for x in draft.drafts_for(jid)}
    assert d["first_name"]["answer"] == "Alex" and d["first_name"]["kind"] == "answer_bank"
    assert d["question_1002"]["answer"] == "3.5 - 3.79"            # GPA range picked deterministically
    assert d["question_1003"]["answer"] == "No"                    # sponsorship from answer bank
    assert d["question_1001"]["answer"].startswith("https://www.linkedin.com")
    assert d["resume"]["kind"] == "file"
    why = d["question_1004"]
    assert any("45%" in i for i in why["issues"])                 # invented number caught
    assert any("f_fake" in i for i in why["issues"])               # unknown fact caught
    assert why["fact_ids"] == jetson
    assert d["gender"]["answer"] == "" and d["gender"]["kind"] == "answer_bank"   # EEO never guessed by AI
    r = draft.readiness(jid)
    assert not r["ready"]


async def test_feedback_is_reused_and_builds_trust(fake_llm):
    jid = await _setup_job()
    fake_llm(lambda s, p: {"answers": [
        {"field": "question_1004", "answer": "Because of the Jetson work.", "fact_ids": _facts_with("Jetson"), "confidence": 0.9},
        {"field": "question_1005", "answer": "Yes", "fact_ids": [], "confidence": 0.2},
        {"field": "cover_letter", "answer": "Short letter.", "fact_ids": _facts_with("Jetson"), "confidence": 0.8}]})
    await draft.draft_job(jid, research=False)
    d = {x["field"]: x for x in draft.drafts_for(jid)}
    # user corrects the offers question and red-flags the essay with a note
    db.x("UPDATE drafts SET final_answer='No', verdict='green' WHERE id=?", (d["question_1005"]["id"],))
    db.x("UPDATE drafts SET verdict='red', note='Mention the hackathon win, not just Jetson' WHERE id=?",
         (d["question_1004"]["id"],))

    # a second company asks the same offers question
    data = json.loads((FIXTURES / "greenhouse_job.json").read_text())
    jid2 = sources.add_job_url("https://job-boards.greenhouse.io/other/jobs/9", "Other Co", "Intern")
    db.x("UPDATE jobs SET description='x', questions=? WHERE id=?",
         (db.enc(jobdetail.normalize_greenhouse(data)), jid2))
    llm_ = fake_llm(lambda s, p: {"answers": [
        {"field": "question_1004", "answer": "Hackathon.", "fact_ids": _facts_with("hackathon"), "confidence": 0.9},
        {"field": "cover_letter", "answer": "Letter.", "fact_ids": _facts_with("hackathon"), "confidence": 0.8}]})
    await draft.draft_job(jid2, research=False)
    d2 = {x["field"]: x for x in draft.drafts_for(jid2)}
    assert d2["question_1005"]["kind"] == "learned" and d2["question_1005"]["answer"] == "No"
    prompt = llm_.prompts[-1]
    assert "Mention the hackathon win" in prompt                    # red-flag note became guidance
    assert "question_1005" not in prompt.split("QUESTIONS TO ANSWER:")[1]
    label = "Do you have any outstanding offers with deadlines?"
    assert learn.trust_for(label) == 0          # an edited answer teaches the answer, not trust
    db.x("UPDATE drafts SET verdict='green' WHERE id=?", (d2["question_1005"]["id"],))
    assert learn.trust_for(label) == 1          # approved as-is -> trust grows


async def test_user_locked_answers_survive_redraft(fake_llm):
    jid = await _setup_job()
    fake_llm(lambda s, p: {"answers": [{"field": "question_1004", "answer": "v1", "fact_ids": [], "confidence": 0.5}]})
    await draft.draft_job(jid, research=False)
    d = {x["field"]: x for x in draft.drafts_for(jid)}
    db.x("UPDATE drafts SET final_answer='My own words' WHERE id=?", (d["question_1004"]["id"],))
    fake_llm(lambda s, p: {"answers": [{"field": "question_1004", "answer": "v2", "fact_ids": [], "confidence": 0.5}]})
    await draft.draft_job(jid, research=False)
    d = {x["field"]: x for x in draft.drafts_for(jid)}
    assert draft.final_value(d["question_1004"]) == "My own words"


async def test_no_ai_still_drafts_standard_fields():
    jid = await _setup_job()
    res = await draft.draft_job(jid, research=False)
    assert res["error"]
    d = {x["field"]: x for x in draft.drafts_for(jid)}
    assert d["email"]["answer"] == "alex.rivera@example.edu"
    assert d["question_1004"]["answer"] == "" and d["question_1004"]["issues"]


async def test_latex_saved_as_txt_and_reupload_replaces_facts(tmp_path):
    p = tmp_path / "resume.txt"
    p.write_text((FIXTURES / "sample_resume.tex").read_text())
    # a messy earlier import, like the no-AI fallback produces
    profile.add_fact("other", "\\documentclass[a4paper,10pt]{article}", source="old.pdf")
    db.x("INSERT INTO documents(kind, filename, path, text, is_primary, created_at) VALUES('resume','old.pdf','x','',1,0)")
    res = await profile.ingest_document(p)
    assert res["method"] == "exact (LaTeX)"
    texts = [f["text"] for f in profile.facts()]
    assert not any(t.startswith("\\") for t in texts)
    assert any("600,000+ images" in t for t in texts)
    pdf = tmp_path / "resume.pdf"
    from pypdf import PdfWriter
    w = PdfWriter(); w.add_blank_page(100, 100); w.write(str(pdf))
    n = len(profile.facts())
    res2 = await profile.ingest_document(pdf, "resume_pdf")
    assert res2["method"] == "attachment" and len(profile.facts()) == n
    assert profile.primary_resume_pdf() == pdf


def test_board_guesses():
    from jobsmith.jobdetail import _board_guesses
    assert _board_guesses("Databricks")[0] == "databricks"
    assert "thenuclearcompany" in _board_guesses("The Nuclear Company")


def test_state_from_location():
    from jobsmith.draft import state_from_location
    assert state_from_location("Atlanta, Georgia") == "Georgia"
    assert state_from_location("Atlanta, GA") == "Georgia"
    assert state_from_location("London, UK") == ""


async def test_document_slots(tmp_path):
    tex = tmp_path / "resume.txt"
    tex.write_text((FIXTURES / "sample_resume.tex").read_text())
    await profile.ingest_document(tex, "resume")
    n = len(profile.facts())
    await profile.ingest_document(tex, "resume")          # same resume again: replaces, no duplicates
    assert len(profile.facts()) == n
    assert len([d for d in profile.documents() if d["kind"] == "resume"]) == 1
    extra = tmp_path / "aws-cert.txt"
    extra.write_text("AWS Certified Cloud Practitioner, issued March 2025, credential ID ABC123 to Alex Rivera.")
    await profile.ingest_document(extra, "extra")         # no AI in tests -> line import
    assert len(profile.facts()) > n
    doc = next(d for d in profile.documents() if d["kind"] == "extra")
    profile.delete_document(doc["id"])
    assert len(profile.facts()) == n                      # its facts go with it


def test_migrate_old_documents():
    tex = (FIXTURES / "sample_resume.tex").read_text()
    for name, text in (("resume.txt", tex), ("Resume (30).pdf", "pdf text"), ("resume.txt", tex)):
        db.x("INSERT INTO documents(kind, filename, path, text, is_primary, created_at) VALUES('resume',?,?,?,1,?)",
             (name, f"/x/{name}", text, db.now()))
    profile.migrate_documents()
    kinds = sorted(d["kind"] for d in profile.documents())
    assert kinds == ["resume", "resume_pdf"]
    profile.migrate_documents()
    assert sorted(d["kind"] for d in profile.documents()) == ["resume", "resume_pdf"]


async def test_profile_json_import_and_attachment_name(tmp_path, monkeypatch):
    import json as j
    pj = tmp_path / "profile.json"
    pj.write_text(j.dumps({
        "answers": {"email": "alex@example.com", "state_province": "GA", "us_citizen": "Yes"},
        "experience": [{"title": "Data Engineer", "company": "Acme Data", "start": "2024-01", "end": "present"}],
        "facts": [{"category": "award", "text": "CURO Research Award"}],
        "attachment_name": "Alex Rivera resume.pdf",
    }))
    monkeypatch.setattr(profile, "PROFILE_JSON", pj)
    res = await profile.import_profile_json()
    assert res["answers"] == 3 and res["facts"] == 1
    assert await profile.import_profile_json() is None                     # unchanged file isn't re-imported
    a = profile.answers()
    assert a["email"]["value"] == "alex@example.com" and a["email"]["confirmed"] == 1
    assert any(f["text"] == "CURO Research Award" for f in profile.facts())
    from jobsmith.draft import deterministic
    st = deterministic({"field": "q", "label": "Which state do you reside in?", "qtype": "text", "options": [],
                        "required": True}, a)
    assert st["answer"] == "Georgia"
    cur = deterministic({"field": "q", "label": "Current Company", "qtype": "text", "options": [], "required": False}, a)
    assert cur["answer"] == "Acme Data"
    usp = deterministic({"field": "q", "label": "Are you a U.S. person under export control regulations?",
                         "qtype": "select", "options": ["Yes", "No"], "required": True}, a)
    assert usp["answer"] == "Yes"
    pdf = tmp_path / "Resume (30).pdf"
    from pypdf import PdfWriter
    w = PdfWriter(); w.add_blank_page(100, 100); w.write(str(pdf))
    db.x("INSERT INTO documents(kind, filename, path, text, is_primary, created_at) VALUES('resume_pdf',?,?,'',1,?)",
         (pdf.name, str(pdf), db.now()))
    out = profile.attachment_file()
    assert out.name == "Alex_Rivera_resume.pdf" and out.read_bytes() == pdf.read_bytes()


async def test_openai_and_anthropic_backends_parse(monkeypatch):
    import httpx
    from jobsmith import llm as L
    calls = []

    class R:
        def __init__(self, data): self.status_code, self._d, self.text = 200, data, ""
        def json(self): return self._d

    async def fake_post(self, url, json=None, headers=None):
        calls.append((url, json, headers))
        if "openai" in url:
            return R({"output": [{"type": "web_search_call"}, {"type": "message", "content": [
                {"type": "output_text", "text": "```json\n{\"answers\": []}\n```"}]}]})
        return R({"content": [{"type": "text", "text": "{\"ok\": true}"}]})
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    out = await L.OpenAIAPI("sk-test", "gpt-5.5").complete_json("sys", "hi", schema={"type": "object"}, web=True)
    assert out == {"answers": []}
    assert calls[-1][1]["tools"] == [{"type": "web_search"}] and calls[-1][2]["Authorization"] == "Bearer sk-test"
    out = await L.AnthropicAPI("ak", "sonnet").complete_json("sys", "hi")
    assert out == {"ok": True} and calls[-1][1]["model"] == "claude-sonnet-5-5"
    db.set_settings({"llm_backend": "openai_api", "openai_api_key": "sk-x"})
    assert isinstance(L.backend(), L.OpenAIAPI)


async def test_command_company_and_links(fake_llm, monkeypatch):
    from jobsmith import commands, runner
    await _load_profile()
    started = []
    monkeypatch.setattr(commands, "queue", lambda ids, **kw: started.extend(ids) or ids)
    # a company already in the lists
    for i, title in enumerate(["Software Engineering Intern", "Hardware Intern", "Marketing Intern"]):
        jid = sources.add_job_url(f"https://job-boards.greenhouse.io/apple/jobs/{i}", "Apple", title)
        db.x("UPDATE jobs SET terms=?, category='Software', fit_score=80 WHERE id=?", (db.enc(["Summer 2027"]), jid))

    def responder(system, prompt):
        if "Extract what job applications" in system:
            return {"companies": ["Apple"], "keywords": ["hardware"]}
        return {"postings": [{"title": "ML Intern", "url": "https://jobs.lever.co/nvidia/abc", "location": "Santa Clara, CA"}]}
    fake_llm(responder)

    async def no_fetch(jid):
        return None
    monkeypatch.setattr(commands.jobdetail, "fetch_job", no_fetch)
    monkeypatch.setattr(commands.match, "rescore", lambda ids=None: 0)
    res = await commands.run("hey, apply for apple hardware roles")
    assert len(started) == 1 and "Apple: 1 matching posting" in res["log"][0]
    title = db.q1("SELECT title FROM jobs WHERE id=?", (started[0],))["title"]
    assert title == "Hardware Intern"
    # a company that isn't in the lists -> web discovery
    fake_llm(lambda s, p: {"companies": ["Nvidia"], "keywords": []} if "Extract" in s else
             {"postings": [{"title": "ML Intern", "url": "https://jobs.lever.co/nvidia/abc", "location": "Santa Clara, CA"}]})
    res = await commands.run("apply to Nvidia")
    assert any("found 1 posting" in l for l in res["log"])
    assert db.q1("SELECT company, ats FROM jobs WHERE url LIKE '%nvidia%'")["ats"] == "lever"
    assert commands.history()[0]["text"] == "apply to Nvidia"


async def test_scheduler_picks_respecting_limits(monkeypatch):
    from jobsmith import scheduler, commands
    db.set_settings({"max_applications_per_company": 1, "auto_max_per_run": 5, "notifications": False,
                     "onboarded": True, "auto_run": True, "power_mode": "full"})
    ids = []
    for co, score in (("A", 90), ("A", 85), ("B", 70), ("C", 20)):
        jid = sources.add_job_url(f"https://job-boards.greenhouse.io/{co}/jobs/{score}", co, f"Intern {score}")
        db.x("UPDATE jobs SET fit_score=? WHERE id=?", (score, jid))
        ids.append(jid)
    picked = scheduler.pick_new_jobs(5)
    assert picked == [ids[0], ids[2]]            # one per company, below-threshold C skipped

    async def no_sync():
        return [{"source": "x", "added": 3, "listings": 10}]
    monkeypatch.setattr(scheduler.sources, "sync_all", no_sync)
    monkeypatch.setattr(scheduler.match, "rescore", lambda ids=None: 0)
    monkeypatch.setattr(commands, "queue", lambda ids: ids)
    res = await scheduler.run_once("test")
    assert "Started 2 applications" in res["summary"]


def test_outcome_classify_and_match():
    from jobsmith import outcomes
    assert outcomes.classify("Your application to Acme", "Thank you for applying. Unfortunately we will not be moving forward.") == "rejected"
    assert outcomes.classify("Next steps", "Please complete the HackerRank assessment within 7 days") == "assessment"
    assert outcomes.classify("Acme interview", "We'd love to schedule a phone screen") == "interview"
    assert outcomes.classify("Application received", "Thank you for applying to Acme Robotics!") == "received"
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/1", "Acme Robotics", "Intern")
    db.x("UPDATE jobs SET status='submitted' WHERE id=?", (jid,))
    jobs = db.q("SELECT id, company FROM jobs WHERE status='submitted'")
    j = outcomes.match_job("Acme Robotics Recruiting <no-reply@greenhouse.io>", "Update", "", jobs)
    assert j["id"] == jid
    assert outcomes.record(j, "received", "s", "f", 0, "m1") and not outcomes.record(j, "received", "s", "f", 0, "m1")
    outcomes.record(j, "interview", "s", "f", 0, "m2")
    outcomes.record(j, "received", "s", "f", 0, "m3")
    assert db.q1("SELECT outcome FROM jobs WHERE id=?", (jid,))["outcome"] == "interview"
    assert outcomes.funnel()["interview"] == 1


async def test_empty_approved_answer_is_redrafted(fake_llm):
    jid = await _setup_job()
    fake_llm(lambda s, p: {"answers": []})                    # first run: AI writes nothing
    await draft.draft_job(jid, research=False)
    d = {x["field"]: x for x in draft.drafts_for(jid)}
    db.x("UPDATE drafts SET verdict='green' WHERE id=?", (d["question_1004"]["id"],))   # user approved it anyway
    fake_llm(lambda s, p: {"answers": [{"field": "question_1004", "answer": "Because of Jetson.", "fact_ids": [],
                                        "confidence": 0.8}]})
    res = await draft.draft_job(jid, research=False)
    d = {x["field"]: x for x in draft.drafts_for(jid)}
    assert d["question_1004"]["answer"] == "Because of Jetson." and res["drafted"] >= 1


def test_old_greenhouse_questions_are_detected_as_stale():
    from jobsmith.draft import questions_stale
    old = {"ats": "greenhouse", "questions": [{"field": "school--0"}, {"field": "demographic_4028768003"}]}
    new = {"ats": "greenhouse", "questions": [{"field": "school--0"}, {"field": "start-month--0"}, {"field": "4028768003"}]}
    assert questions_stale(old) and not questions_stale(new)
    assert not questions_stale({"ats": "lever", "questions": old["questions"]})


async def test_usage_is_recorded_per_application(fake_llm):
    from jobsmith import llm
    fake_llm(lambda s, p: {"ok": True})
    with llm.usage_for("j_abc", "answers"):
        await llm.complete_json("sys", "prompt")
    await llm.complete_json("sys", "prompt", web=True)
    rows = db.q("SELECT * FROM usage ORDER BY id")
    assert [(r["job_id"], r["purpose"]) for r in rows] == [("j_abc", "answers"), (None, "other")]
    assert rows[0]["input_tokens"] == 1000 and rows[0]["output_tokens"] == 200 and rows[1]["web_searches"] == 1
    from jobsmith.api import job_usage, usage
    assert job_usage("j_abc")["tokens"] == 1200
    assert usage()["all"]["calls"] == 2


def test_document_file_is_viewable(tmp_path):
    from fastapi.testclient import TestClient
    from jobsmith.api import app
    f = tmp_path / "Alex_resume.tex"
    f.write_text("\\\\section{Experience}")
    did = db.x("INSERT INTO documents(kind, filename, path, text, is_primary, created_at) VALUES('resume',?,?,'',1,?)",
               (f.name, str(f), db.now()))
    r = TestClient(app).get(f"/api/documents/{did}/file")
    assert r.status_code == 200 and "section" in r.text and r.headers["content-type"].startswith("text/plain")


def test_keyword_match_counts_what_the_resume_shows():
    from jobsmith import insights
    job = {"title": "Software Engineer Intern", "description":
           "Experience with Python, C/C++ or Java. Frontend experience in JavaScript/React. AWS. Kubernetes a plus. "
           "Strong communication skills. API development."}
    m = insights.keyword_match(job, resume="Built a React app in JavaScript; Python and C++ on AWS. REST API work.")
    assert {"Python", "C++", "React", "JavaScript", "AWS"} <= set(m["matched"])
    assert "Kubernetes" in m["missing"] and "Java" in m["missing"]
    assert 0 < m["score"] < 100 and m["total"] == len(m["matched"]) + len(m["missing"])
    # "C" in "C/C++" shouldn't need a stray capital C to count, and "go" in prose isn't Go
    assert "Go" not in insights.keyword_match({"title": "", "description": "ready to go build things"}, "")["missing"]


def test_linkedin_connections_import_and_company_match():
    from jobsmith import network
    csv_text = ("Notes:\n\"When exporting your connection data, you may notice...\"\n\n"
                "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                "Priya,Shah,https://www.linkedin.com/in/priya,,Apple Inc.,Silicon Engineer,03 Jan 2026\n"
                "Sam,Lee,https://www.linkedin.com/in/sam,,Amazon Web Services (AWS),SDE II,04 Feb 2026\n"
                "Jo,Park,https://www.linkedin.com/in/jo,,Applebee's,Server,05 Feb 2026\n")
    assert network.import_csv(csv_text) == {"imported": 3, "with_company": 3}
    assert [p["first_name"] for p in network.at_company("Apple")] == ["Priya"]
    assert [p["first_name"] for p in network.at_company("Amazon")] == ["Sam"]
    assert network.counts_for(["NVIDIA"]) == {"NVIDIA": 0}


def test_devpost_portfolio_parsing():
    from jobsmith import insights
    d = insights.parse_devpost((FIXTURES / "devpost_portfolio.html").read_text())
    assert d["name"] == "Alex Rivera" and d["bio"] == "CompE @ Example Tech"
    assert [p["name"] for p in d["projects"]] == ["Beacon", "Notes"]
    assert d["projects"][0]["winner"] and not d["projects"][1]["winner"]
    assert d["projects"][0]["tagline"].startswith("Wildfire smoke detection on a Jetson Nano & LoRa")


def test_autopilot_holds_unsure_answers_and_passes_confident_ones():
    from jobsmith import draft
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/9", "Acme", "Intern")
    db.set_settings({"autonomy": "autopilot"})
    fields = [{"field": "why", "label": "Why Acme?", "qtype": "textarea", "required": True, "options": []},
              {"field": "extra", "label": "Anything else?", "qtype": "textarea", "required": True, "options": []}]
    draft.save_results(jid, fields, {
        "why": {"kind": "generated", "answer": "Because of the robots.", "confidence": 0.85, "issues": []},
        "extra": {"kind": "generated", "answer": "Maybe.", "confidence": 0.4, "issues": []}})
    r = draft.readiness(jid)
    assert not r["ready"] and len(r["blockers"]) == 1 and r["blockers"][0].startswith("Anything else?")
    db.set_settings({"autonomy": "copilot"})
    assert len(draft.readiness(jid)["blockers"]) == 1      # same rule either way: only the unsure one waits


def test_posting_sections_pull_out_requirements_and_duties():
    from jobsmith import insights
    text = ("At Affirm, we exist for the moments that matter.\nWhat You'll Do\nShip a project to production.\n"
            "Present to the org.\nWhat We Look For\nExperience with Python, C/C++ or Java\nStrong communication skills\n"
            "Compensation is a set amount.\nUSA hourly base pay: $55.00\nBenefits designed for you\nHealth coverage at no cost.")
    s = {x["kind"]: x["items"] for x in insights.posting_sections(text)}
    assert s["responsibilities"] == ["Ship a project to production.", "Present to the org."]
    assert s["requirements"][0] == "Experience with Python, C/C++ or Java"
    assert "benefits" in s


def _answers(**kw):
    return {k: {"value": v} for k, v in kw.items()}


def test_eligibility_blocks_clear_requirements_only():
    from jobsmith.eligibility import check
    me = _answers(us_citizen="Yes", needs_sponsorship="No", degree="Bachelor's", graduation_year="2027", security_clearance="")
    ok = check({"title": "Software Engineer Intern", "description": "Python. Bonus: PhD research experience."}, me)
    assert ok["ok"], ok
    assert not check({"title": "Senior Software Engineer", "description": ""}, me)["ok"]
    assert check({"title": "Hardware Engineering Intern", "description": "Active Top Secret clearance required."}, me)["reasons"] == \
        ["Requires an active security clearance"]
    assert "security clearance" in check({"title": "Intern", "description": "Ability to obtain a security clearance."}, me)["notes"][0]
    assert not check({"title": "Research Intern", "description": "Currently pursuing a PhD in Computer Science."}, me)["ok"]
    assert check({"title": "Research Intern", "description": "Pursuing a PhD or Bachelor's in CS."}, me)["ok"]
    grads = check({"title": "Intern", "description": "Expected graduation between December 2025 and June 2026."}, me)
    assert grads["reasons"] and "2027" in grads["reasons"][0]
    assert check({"title": "Intern", "description": "Graduating in 2027 or 2028"}, me)["ok"]
    assert "5+ years" in check({"title": "Software Engineer", "description": "5+ years of professional experience"}, me)["reasons"][0]
    visa = _answers(us_citizen="No", needs_sponsorship="Yes", degree="Bachelor's", graduation_year="2027")
    assert not check({"title": "Intern", "description": "We are unable to sponsor visas for this role."}, visa)["ok"]
    assert not check({"title": "Intern", "sponsorship": "U.S. Citizenship is Required", "description": ""}, visa)["ok"]
    assert check({"title": "Intern", "description": "We are unable to sponsor visas."}, me)["ok"]


def test_ineligible_jobs_are_not_auto_picked():
    from jobsmith import commands, match, scheduler
    for k, v in {"us_citizen": "No", "needs_sponsorship": "Yes", "graduation_year": "2027"}.items():
        profile.set_answer(k, v)
    a = sources.add_job_url("https://job-boards.greenhouse.io/a/jobs/1", "A", "Software Engineer Intern")
    b = sources.add_job_url("https://job-boards.greenhouse.io/b/jobs/2", "B", "Software Engineer Intern")
    db.x("UPDATE jobs SET description='Must be a U.S. citizen.' WHERE id=?", (b,))
    db.set_settings({"min_fit_score": 0})
    match.rescore()
    assert scheduler.pick_new_jobs(10) == [a]
    assert commands._pick([a, b], 10) == [a] and set(commands._pick([a, b], 10, keep_ineligible=True)) == {a, b}


async def test_gemini_and_ollama_backends_parse_json_and_usage(monkeypatch):
    import httpx
    from jobsmith import llm
    sent = {}

    async def fake_post(self, url, json=None, headers=None, **kw):
        sent["url"], sent["body"], sent["headers"] = url, json, headers
        if "generativelanguage" in url:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}],
                                             "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 8}})
        return httpx.Response(200, json={"message": {"content": '{"ok": true}'}, "prompt_eval_count": 90, "eval_count": 5})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    g = llm.GeminiAPI("k", "gemini-flash-latest")
    assert await g.complete_json("sys", "hi", schema={"type": "object"}) == {"ok": True}
    assert sent["headers"]["x-goog-api-key"] == "k" and sent["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert g.last_usage["input"] == 120 and g.last_usage["output"] == 8
    await g.complete_json("sys", "research", web=True)
    assert sent["body"]["tools"] == [{"google_search": {}}] and "responseMimeType" not in sent["body"]["generationConfig"]

    o = llm.OllamaLocal("qwen3:8b")
    assert await o.complete_json("sys", "hi", schema={"type": "object"}) == {"ok": True}
    assert sent["url"].endswith("/api/chat") and sent["body"]["format"] == {"type": "object"} and sent["body"]["model"] == "qwen3:8b"
    assert o.last_usage == {"input": 90, "output": 5, "cached": 0, "searches": 0, "cost": 0.0}


def test_auto_detects_keys_from_settings_or_environment(monkeypatch):
    from jobsmith import llm
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert llm.detected({}, []) == []
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert [d["kind"] for d in llm.detected({}, ["qwen3:8b"])] == ["gemini_api", "ollama"]
    assert [d["kind"] for d in llm.detected({"anthropic_api_key": "a"}, [])][0] == "anthropic_api"
    assert llm.pick_ollama_model(["tinyllama:1b", "llama3.1:8b", "qwen3:14b"]) == "qwen3:14b"


def test_scheduler_waits_for_setup():
    from jobsmith import scheduler
    db.set_settings({"auto_run": True, "onboarded": False})
    assert not scheduler.enabled(db.get_settings())
    db.set_settings({"onboarded": True})
    assert scheduler.enabled(db.get_settings())
    db.set_settings({"auto_run": False})
    assert not scheduler.enabled(db.get_settings())


def test_smith_picks_a_model_that_fits_memory():
    from jobsmith import smith
    assert smith.recommended(64)["model"].startswith("qwen3:30b-a3b-instruct")
    assert smith.recommended(24)["model"] == "qwen3:14b"
    assert smith.recommended(16)["model"] == "qwen3:8b"
    assert smith.recommended(8)["model"].startswith("qwen3:4b-instruct") and smith.recommended(8)["slow"]
    assert smith.recommended(4)["model"] == "qwen3:1.7b"


async def test_smith_setup_downloads_with_progress_and_switches_to_it(monkeypatch):
    """Ollama already running, model missing: smith pulls it, reports progress, and becomes the AI."""
    import httpx
    from jobsmith import db, llm, smith
    pulled: list[str] = []
    seen: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.12.0"})
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in pulled]})
        if req.url.path == "/api/pull":
            name = json.loads(req.content)["model"]
            pulled.append(name)
            lines = [{"status": "pulling manifest"},
                     {"status": "pulling abc", "total": 1000, "completed": 250},
                     {"status": "pulling abc", "total": 1000, "completed": 1000},
                     {"status": "success"}]
            return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())
        return httpx.Response(404)

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: real(*a, transport=httpx.MockTransport(handler),
                                                                 **{x: y for x, y in k.items() if x != "transport"}))
    orig_set = smith._set
    monkeypatch.setattr(smith, "_set", lambda ph, m="", p=None, **kw: (seen.append(p) if ph == "downloading" and p else None,
                                                                       orig_set(ph, m, p, **kw)))
    before = db.get_settings()
    try:
        st = await smith.setup("qwen3:4b")
        assert st["phase"] == "ready", st
        assert pulled == ["qwen3:4b"] and 0.25 in seen and 1.0 in seen
        s = db.get_settings()
        assert s["llm_backend"] == "ollama" and s["ollama_model"] == "qwen3:4b"
        b = llm.make_backend("ollama", s)
        assert llm.label(b) == "smith (qwen3:4b)"
    finally:
        db.set_settings({k: before.get(k) for k in ("llm_backend", "ollama_model", "research_backend")})
        smith.STATE.update(phase="idle", message="", progress=None)


def test_old_wyzard_data_is_carried_over(tmp_path):
    from jobsmith.config import _migrate_from_wyzard
    old = tmp_path / ".wyzard"
    old.mkdir()
    (old / "wyzard.db").write_text("x")
    new = tmp_path / ".jobsmith"
    _migrate_from_wyzard(new)
    assert (new / "jobsmith.db").read_text() == "x" and not old.exists()


def test_moved_project_folder_keeps_uploaded_files(tmp_path):
    """Paths saved under an old folder (wyzard/data/...) are found again under today's data folder."""
    from jobsmith import config
    from jobsmith.db import _rehome
    f = config.DATA_DIR / "uploads" / "rehome-test.pdf"
    f.write_bytes(b"%PDF")
    try:
        assert _rehome("/Users/someone/wyzard/data/uploads/rehome-test.pdf") == str(f)
        assert _rehome(r"C:\Users\someone\wyzard\data\uploads\rehome-test.pdf") == str(f)   # saved on Windows
        assert _rehome("uploads/rehome-test.pdf") is None                                     # relative: left alone
        assert _rehome("/Users/someone/wyzard/data/uploads/missing.pdf") is None
        assert _rehome(str(f)) is None
    finally:
        f.unlink()


def test_no_platform_only_time_formats():
    """%-I and %-d work on macOS and Linux but Windows strftime rejects them, so the app would crash there."""
    import re
    from pathlib import Path
    from jobsmith import config
    src = Path(config.__file__).parent
    hits = [f"{f.relative_to(src)}:{n}" for f in src.rglob("*.py")
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
            if re.search(r"%-[a-zA-Z]", line.split("#")[0])]
    assert not hits, hits


def test_clock_drops_leading_zeros():
    import datetime as dt
    from jobsmith.ask import clock
    today = dt.datetime.now()
    at = lambda **k: today.replace(second=0, microsecond=0, **k).timestamp()
    assert clock(at(hour=0, minute=5)) == "12:05 AM"
    assert clock(at(hour=9, minute=5)) == "9:05 AM"
    assert clock(at(hour=12, minute=0)) == "12:00 PM"
    assert clock(at(hour=14, minute=30)) == "2:30 PM"
    three_days = (today - dt.timedelta(days=3)).replace(hour=7, minute=15)
    assert clock(three_days.timestamp()) == f"{three_days:%a} 7:15 AM"
    assert clock(dt.datetime(2020, 3, 4, 14, 5).timestamp()) == "Mar 4"
    assert clock(None) == ""


def test_autopilot_waits_for_the_first_supervised_run():
    import time
    from jobsmith import db, onboarding, scheduler
    before = db.get_settings()
    try:
        db.set_settings({"onboarded": False, "auto_last_run": 0})
        onboarding.finish("autopilot")
        s = db.get_settings()
        interval = float(s.get("auto_interval_hours") or 6) * 3600
        starts_in = s["auto_last_run"] + interval - time.time()
        assert scheduler.enabled(s) and 15 * 60 < starts_in <= 20 * 60 + 5
    finally:
        db.set_settings({k: before.get(k) for k in ("onboarded", "auto_last_run", "autonomy", "auto_run")})


def test_setup_goals_are_multi_select(monkeypatch):
    from jobsmith import db, onboarding, sources
    added = []
    monkeypatch.setattr(sources, "add_source", lambda url: added.append(url))
    before = db.get_settings()
    try:
        p = onboarding.set_goal(["internship", "newgrad", "targeted"], ["Software"], ["NVIDIA", " Ramp ", ""])
        assert p["goals"] == ["internship", "newgrad", "targeted"]
        assert set(p["target_terms"]) == {"Summer 2027", "New Grad"} and p["target_companies"] == ["NVIDIA", "Ramp"]
        assert len(added) == 2
        assert onboarding.goals_of({"goal": "both"}) == ["internship", "newgrad"]      # older installs
    finally:
        db.set_settings({k: before.get(k) for k in ("goal", "goals", "target_terms", "target_categories",
                                                     "target_companies", "min_fit_score")})


def test_setup_checklist_says_what_autopilot_still_needs():
    from jobsmith import onboarding
    items = {c["key"]: c for c in onboarding.checklist()}
    assert {"resume", "pdf", "name", "email", "work_authorized_us", "needs_sponsorship"} <= {k for k, c in items.items() if c["required"]}
    assert onboarding.profile_ready() == all(c["done"] for c in items.values() if c["required"])


async def test_watching_an_application_before_its_form_opens(monkeypatch):
    """Press a number in the terminal while it's still researching: the window comes up when the form opens."""
    from jobsmith import runner
    shown = []

    async def fake_set_window(page, state):
        shown.append(state)
        return True

    class Page:
        def is_closed(self):
            return False

    # Its own browser state: a headed window nobody is watching yet, whatever earlier tests left behind.
    monkeypatch.setattr(runner, "browser", runner.Browser())
    monkeypatch.setattr(runner.browser, "ctx_headless", False)
    monkeypatch.setattr(runner.browser, "set_window", fake_set_window)
    monkeypatch.setattr(runner, "LIVE", {})
    monkeypatch.setattr(runner, "WATCH", set())
    assert await runner.live_show("job-early") == "pending" and "job-early" in runner.WATCH
    runner.live_set("job-early", Page(), phase="opening")
    await asyncio.sleep(0.05)
    assert shown == ["normal"] and "job-early" not in runner.WATCH and runner.browser.shown


def test_a_closed_browser_is_not_headless():
    """Closing the background browser forgets that it was headless, so "Show" never takes the take-over path
    for a browser that no longer exists."""
    from jobsmith import runner
    b = runner.Browser()
    b.ctx_headless, b.ua = True, "ua"
    asyncio.run(b._close_ctx())
    assert b.ctx is None and b.ctx_headless is None and b.ua is None

    old, new = object(), object()                 # Chrome closing the window itself
    b.ctx, b.ctx_headless, b.ua = new, True, "ua"
    b._closed(old)                                # a late event from an older context changes nothing
    assert b.ctx is new and b.ctx_headless is True and b.ua == "ua"
    b._closed(new)
    assert b.ctx is None and b.ctx_headless is None and b.ua is None


async def test_gemini_free_quota_falls_back_to_smith(monkeypatch):
    import httpx
    from jobsmith import llm
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        if "googleapis" in req.url.host:
            return httpx.Response(429, text='{"error": {"details": [{"quotaId": "GenerateRequestsPerDayPerProject"}]}}')
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})
        return httpx.Response(200, json={"message": {"content": '{"answer": "from smith"}'},
                                         "prompt_eval_count": 5, "eval_count": 3})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: real(*a, transport=httpx.MockTransport(handler),
                                                                 **{x: y for x, y in k.items() if x != "transport"}))
    db.set_settings({"smith_fallback": "always"})   # let smith stand in regardless of battery state
    llm.set_backend_override(None)
    monkeypatch.setattr(llm, "_models_cache", (0.0, []))
    monkeypatch.setattr(llm, "_quota_hit", {})
    monkeypatch.setattr(llm, "backend", lambda role="write": llm.GeminiAPI("k"))
    out = await llm.complete_json("sys", "q")
    assert out == {"answer": "from smith"} and calls.count("generativelanguage.googleapis.com") == 1


async def test_gemini_bad_key_is_explained(monkeypatch):
    import httpx
    from jobsmith import llm
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: real(*a, transport=httpx.MockTransport(
        lambda r: httpx.Response(400, text='{"error": {"message": "API key not valid. Please pass a valid API key."}}')),
        **{x: y for x, y in k.items() if x != "transport"}))
    with pytest.raises(llm.LLMError, match="isn't valid"):
        await llm.GeminiAPI("bad").complete_json("s", "p")


def test_engine_refuses_websites_but_serves_the_extension():
    from fastapi.testclient import TestClient
    from jobsmith.api import app
    c = TestClient(app)
    assert c.get("/api/ext/ping", headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.get("/api/ext/ping", headers={"Host": "attacker.example"}).status_code == 403
    ok = c.get("/api/ext/ping", headers={"Origin": "chrome-extension://abcdefghijklmnop"})
    assert ok.status_code == 200 and ok.json()["name"] == "Jobsmith"


async def test_extension_answers_fields_from_the_profile():
    from jobsmith import extension, profile
    profile.set_answer("email", "alex@example.com", True)
    profile.set_answer("graduation_date", "May 2027", True)
    r = await extension.answers("https://job-boards.greenhouse.io/acme/jobs/123/apply",
                                [{"id": "js1", "label": "Email", "type": "text", "required": True},
                                 {"id": "js2", "label": "End date year", "type": "text"},
                                 {"id": "js3", "label": "Resume/CV", "type": "file"}], title="Intern")
    by = {a["id"]: a for a in r["answers"]}
    assert r["company"] == "Acme" and by["js1"]["value"] == "alex@example.com"
    assert by["js2"]["value"] == "2027" and by["js3"]["file"] == "resume"
    # the same posting again finds the same job
    assert extension.find_or_add("https://job-boards.greenhouse.io/acme/jobs/123") == r["job_id"]


def test_finished_application_is_not_shown_as_still_working():
    from jobsmith import db, runner
    db.x("INSERT OR IGNORE INTO jobs(id, company, title, url, ats, created_at, updated_at) VALUES('busy1','Acme','Intern','https://x','greenhouse',0,0)")
    db.x("UPDATE jobs SET status='filling' WHERE id='busy1'")
    runner._active["busy1"] = "autopilot"
    try:
        assert runner.active().get("busy1") == "filling"
        runner.live_set("busy1", phase="review")          # filled in, tab waiting for you
        assert "busy1" not in runner.active()
        runner.live_drop("busy1")
        db.x("UPDATE jobs SET status='submitted' WHERE id='busy1'")
        assert "busy1" not in runner.active()
    finally:
        runner._active.pop("busy1", None)


def test_cover_letter_becomes_a_pdf(tmp_path):
    from jobsmith import db, letters, profile
    db.x("INSERT OR IGNORE INTO jobs(id, company, title, url, ats, created_at, updated_at) VALUES('cl1','Acme','Intern','https://y','greenhouse',0,0)")
    db.x("""INSERT OR REPLACE INTO drafts(job_id, field, label, qtype, required, options, kind, answer, fact_ids, rationale,
            confidence, issues, updated_at) VALUES('cl1','cover_letter','Cover Letter','file',0,'[]','generated',
            'I build data pipelines — fast ones.\nI would love to do that at Acme.','[]','',0.9,'[]',0)""")
    profile.set_answer("first_name", "Alex", True)
    p = letters.cover_pdf("cl1", tmp_path)
    assert p and p.read_bytes().startswith(b"%PDF") and p.stat().st_size > 800
    assert letters.cover_text("cl1").startswith("I build")


def test_location_choices_match_whole_words():
    from jobsmith import match, onboarding
    s = {"target_locations": onboarding.LOCATIONS["SF Bay Area"]}
    _, sf = match.score_job({"locations": ["San Francisco, CA"], "title": "x"}, s, set(), {})
    _, other = match.score_job({"locations": ["Sfax Robotics HQ, Chicago, IL"], "title": "x"}, s, set(), {})
    assert "+ location" in sf and "- location" in other     # "SF" doesn't match inside "Sfax"


def test_out_of_gemini_quota_routes_to_smith(monkeypatch):
    import time
    from jobsmith import llm
    db.set_settings({"smith_fallback": "always"})   # let smith stand in regardless of battery state
    monkeypatch.setattr(llm, "_quota_hit", {"gemini_api": time.time() + 3600})
    monkeypatch.setattr(llm, "_models_cache", (time.time(), ["qwen3:8b"]))
    b = llm.make_backend("gemini_api", {"gemini_api_key": "k"})
    assert isinstance(b, llm.OllamaLocal)
    r = llm.gemini_reset()
    assert 0 < r - time.time() <= 86400


def test_linkedin_archive_fills_the_profile():
    import io
    import zipfile
    from jobsmith import linkedin, profile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Basic_LinkedInDataExport/Profile.csv",
                   "First Name,Last Name,Maiden Name,Address,Birth Date,Headline,Summary,Industry,Zip Code,Geo Location,Twitter Handles,Websites,Instant Messengers\n"
                   'Sam,Lee,,,,"Hardware engineer, FPGA",Builds things.,,,"Austin, Texas",,"[PORTFOLIO:https://github.com/samlee]",\n')
        z.writestr("Positions.csv", "Company Name,Title,Description,Location,Started On,Finished On\n"
                                    "Acme,FPGA Intern,Timing closure on a 400 MHz design,Austin,Jun 2025,Aug 2025\n")
        z.writestr("Certifications.csv", "Name,Url,Authority,Started On,Finished On,License Number\n"
                                         "AWS Cloud Practitioner,,Amazon Web Services,Mar 2025,,\n")
        z.writestr("Languages.csv", "Name,Proficiency\nSpanish,Professional working proficiency\n")
    r = linkedin.import_archive(buf.getvalue(), "export.zip")
    a = {k: v["value"] for k, v in profile.answers().items()}
    assert r["ok"] and a["first_name"] == "Sam" and a["headline"].startswith("Hardware engineer")
    assert "AWS Cloud Practitioner" in a["certifications"] and a["languages"].startswith("Spanish")
    assert any(e["company"] == "Acme" for e in profile.entries("experience"))
    assert any("Certification: AWS" in f["text"] for f in profile.facts())



async def test_autopilot_off_stops_work_in_progress():
    """The switch is a kill switch: turning autopilot off cancels applications mid-way."""
    import asyncio
    from jobsmith import db, runner
    db.x("INSERT OR IGNORE INTO jobs(id, company, title, url, ats, created_at, updated_at) VALUES('stop1','Acme','Intern','https://z','greenhouse',0,0)")
    db.x("UPDATE jobs SET status='filling' WHERE id='stop1'")
    started = asyncio.Event()

    async def slow():
        started.set()
        await asyncio.sleep(60)
    assert runner.spawn("stop1", "autopilot", slow())
    await started.wait()
    r = await runner.stop()
    assert r["stopped"] == 1 and "stop1" not in runner.active()
    row = db.q1("SELECT status, hold_reason FROM jobs WHERE id='stop1'")
    assert row["status"] == "drafted" and row["hold_reason"] == "Stopped by you"


def test_battery_saver_rules(monkeypatch):
    from jobsmith import db, power
    monkeypatch.setattr(power, "battery", lambda: {"percent": 50, "plugged": False, "draining_plugged": False, "minutes_left": 90})
    db.set_settings({"power_mode": "auto", "smith_fallback": "plugged", "on_battery": "pause"})
    assert power.saver() and not power.local_ai_allowed() and power.paused()
    monkeypatch.setattr(power, "battery", lambda: {"percent": 50, "plugged": True, "draining_plugged": False, "minutes_left": None})
    assert not power.saver() and power.local_ai_allowed() and not power.paused()
    db.set_settings({"power_mode": "full", "on_battery": "slow"})


# --------------------------------------------------------------------------- email codes, dashboard
def test_emailed_codes_are_found_and_matched_to_the_company():
    from jobsmith import outcomes
    gh = ("Security code for your application to Acme Robotics",
          "Hi Alex, Copy and paste this code into the security code field on your application: kD8sQw2Z After you enter the code, resubmit.")
    assert outcomes.extract_code(*gh) == "kD8sQw2Z"
    assert outcomes.extract_code("Your verification code", "Your one-time code is 482913. It expires in 10 minutes.") == "482913"
    assert outcomes.extract_code("Thanks for applying", "We received your application for the Software Engineer role.") is None
    msgs = [{"from": "Other Co <no-reply@other.com>", "subject": "Your code", "body": "Your code is 111222", "when": 5},
            {"from": "Acme Robotics <no-reply@us.greenhouse-mail.io>", "subject": gh[0], "body": gh[1], "when": 4}]
    assert outcomes.pick_code(msgs, "Acme Robotics") == "kD8sQw2Z"
    assert outcomes.pick_code(msgs[:1], "Acme Robotics") is None


async def test_dashboard_checklists():
    from jobsmith import onboarding
    await _load_profile()
    st = onboarding.strength()
    keys = {i["key"]: i for i in st["items"]}
    assert sum(i["points"] for i in st["items"]) == 100
    assert keys["contact"]["done"] and keys["skills"]["done"]
    assert 0 < st["percent"] <= 100
    started = onboarding.get_started(ai_ok=True)
    assert len(started) == 6 and next(i for i in started if i["key"] == "ai")["done"]
    assert not next(i for i in started if i["key"] == "email")["done"]
    db.set_settings({"gmail_address": "a@gmail.com", "gmail_app_password": "abcd efgh ijkl mnop"})
    assert next(i for i in onboarding.get_started(ai_ok=False) if i["key"] == "email")["done"]
    onboarding.set_prefs(picky="good")
    assert onboarding.prefs_done()
    assert set(onboarding.stages(set())) == {"working", "paused", "needs", "applied", "interviewing", "offer", "rejected"}


async def test_check_again_clears_a_stale_gemini_limit(monkeypatch):
    from jobsmith import llm
    db.set_settings({"llm_backend": "gemini_api", "gemini_api_key": "k"})
    llm._quota_hit["gemini_api"] = llm.gemini_reset()

    async def ok(self):
        return True, "connected"
    monkeypatch.setattr(llm.GeminiAPI, "available", ok)
    r = await llm.recheck_gemini()
    assert r["ok"] and not llm.gemini_limited()


def test_job_facts_row():
    from jobsmith import insights
    assert insights.pay_of("Pay: $45 - $55 per hour.") == "$45 - $55/hr"
    assert insights.pay_of("The base salary range is $140,000 - $180,000 USD annually.") == "$140k - $180k/yr"
    assert insights.pay_of("You'll get a $5 coffee credit and $1,000 for books.") == ""
    f = insights.job_facts({"title": "Software Engineering Intern", "terms": ["Summer 2027"], "locations": ["Boston, MA"],
                            "description": "Hybrid in Boston. We are unable to sponsor visas for this role. $50/hr"})
    assert f["level"] == "Intern" and f["mode"] == "Hybrid" and f["sponsorship"] == "No visa sponsorship" and f["pay"] == "$50/hr"
    assert insights.job_facts({"title": "Senior Software Engineer", "locations": ["Remote"]})["level"] == "Senior"


def test_values_nudge_ranking_and_reach_the_prompt():
    from jobsmith import match, onboarding
    job = {"company": "Tiny Robots", "title": "Founding Engineer Intern", "description": "Seed-stage startup, small team. Return offer for strong interns.",
           "locations": ["Remote"]}
    assert not match.value_bonus(job, [])
    got = dict(match.value_bonus(job, ["Small team, big ownership", "Path to a full-time offer", "Remote or flexible"]))
    assert set(got) == {"small teams", "a full-time path", "flexibility"}
    onboarding.set_prefs(values=["Pay", "Not a real value", "Pay2", "Work-life balance", "Hard technical problems", "Impact on real users"])
    assert db.get_setting("values") == ["Pay", "Work-life balance", "Hard technical problems"]
    prompt = draft.build_prompt({"title": "Intern", "company": "X", "locations": []}, [])
    assert "VALUES IN A ROLE" in prompt and "Work-life balance" in prompt


def test_version_needs_no_engine(monkeypatch, capsys):
    """The installer prints the version it installed from `jobsmith --version`; it mustn't start anything."""
    import sys
    import jobsmith
    from jobsmith import cli, tui
    monkeypatch.setattr(tui, "main", lambda argv: (_ for _ in ()).throw(AssertionError("started the terminal app")))
    monkeypatch.setattr(sys, "argv", ["jobsmith", "--version"])
    cli.main()
    assert capsys.readouterr().out == f"jobsmith {jobsmith.__version__}\n"


@pytest.mark.parametrize("found,download_ok", [(True, True), (False, True), (False, False)])
def test_doctor_browser_is_quiet_unless_it_downloads(monkeypatch, capsys, found, download_ok):
    """The installer's browser check: silent when Chrome or Edge works, one line before a Chromium download, and
    what to do if the download fails. It never fails the install itself."""
    import subprocess
    import sys
    from jobsmith import cli

    def launch(coro):                       # stands in for starting Chrome, Edge or Chromium
        coro.close()
        if not found:
            raise OSError("no browser")
    monkeypatch.setattr(cli.asyncio, "run", launch)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0 if download_ok else 1, "", "no disk"))
    monkeypatch.setattr(sys, "argv", ["jobsmith", "doctor", "--browser"])
    cli.main()
    out = capsys.readouterr().out.splitlines()
    if found:
        assert out == []
    else:
        assert out[0] == "Downloading a browser for Jobsmith to fill applications in (about 150 MB)..."
        assert (len(out) == 1) == download_ok
        if not download_ok:
            assert "Run `jobsmith doctor` later to try again" in out[1]


@pytest.mark.parametrize("platform, args", [("darwin", ["--use-mock-keychain"]), ("linux", ["--password-store=basic"]),
                                            ("win32", [])])
def test_browser_never_asks_for_the_keychain(monkeypatch, platform, args):
    """No browser launched: on each system (faked), Chromium gets the flags that stop it asking for the login keychain
    ('Chromium Safe Storage') or a keyring."""
    import sys
    from jobsmith.fill.base import browser_args
    monkeypatch.setattr(sys, "platform", platform)
    assert browser_args() == args
