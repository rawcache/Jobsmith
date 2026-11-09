"""First-run setup and what it narrows: level, role types, places and posting age are filters; day one is one
supervised application, not a pile; nothing starts until setup is done (Phase 1 item 10)."""
import json
import time

from jobsmith import db, guardrails, match, onboarding, scheduler

DAY = 86400


def _job(jid, title="Software Engineer Intern", company="Acme", terms=("Summer 2027",), category="Software",
         locations=("New York, NY",), age_days=3, ats="greenhouse", url=None, status="new"):
    now = db.now()
    db.x("""INSERT INTO jobs(id, company, title, url, ats, locations, terms, category, date_posted, status,
                             created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
         (jid, company, title, url or f"https://boards.greenhouse.io/{company.lower()}/jobs/{jid}", ats,
          json.dumps(list(locations)), json.dumps(list(terms)), category, now - age_days * DAY, status, now, now))
    return jid


def _settings(**kw):
    s = {"goals": ["internship"], "target_terms": ["Summer 2027"], "target_categories": ["Software"],
         "target_locations": [], "target_companies": [], "max_posting_age_days": 60}
    s.update(kw)
    return s


def test_level_comes_from_the_lists_season_or_the_title():
    assert match.level_of({"terms": ["New Grad"], "title": "Software Engineer"}) == "newgrad"
    assert match.level_of({"terms": ["Fall 2026"], "title": "Software Engineer"}) == "internship"
    assert match.level_of({"terms": [], "title": "Software Engineering Intern"}) == "internship"
    assert match.level_of({"terms": ["N/A"], "title": "Software Engineer, Early Career"}) == "newgrad"
    assert match.level_of({"terms": [], "title": "Software Engineer"}) == ""
    assert match.level_of({"terms": [], "title": "International Sales Lead"}) == ""   # "intern" inside a word


def test_a_role_outside_your_level_role_type_place_or_age_isnt_a_match_at_any_fit():
    s = _settings(target_locations=onboarding.LOCATIONS["New York"])
    base = {"title": "Software Engineer Intern", "terms": ["Summer 2027"], "category": "Software",
            "locations": ["New York, NY"], "date_posted": time.time() - DAY, "company": "Acme"}
    assert match.scope(base, s) == []
    assert match.scope(base | {"terms": ["New Grad"], "title": "Software Engineer"}, s) == \
        ["not your level (a new grad role)"]
    assert match.scope(base | {"terms": ["Fall 2026"]}, s) == ["not your season (Fall 2026)"]
    assert match.scope(base | {"category": "Hardware"}, s) == ["not a role type you picked (Hardware)"]
    assert match.scope(base | {"locations": ["Austin, TX"]}, s) == ["not in your places"]
    assert match.scope(base | {"date_posted": time.time() - 90 * DAY}, s) == ["posted over 60 days ago"]
    # No places picked: anywhere in the US, nowhere else
    us = _settings()
    assert match.scope(base | {"locations": ["Austin, TX"]}, us) == []
    assert match.scope(base | {"locations": ["London, UK"]}, us) == ["outside the US"]
    # A company you named keeps any level
    assert match.scope(base | {"terms": [], "title": "Software Engineer"}, _settings(target_companies=["Acme"])) == []
    assert match.scope(base | {"terms": [], "title": "Software Engineer"}, _settings()) == ["not an internship"]


def test_out_of_scope_scores_under_every_fit_bar_setup_offers_and_says_why():
    s = _settings()
    job = {"title": "Software Engineer", "terms": ["New Grad"], "category": "Software", "locations": ["NYC"],
           "date_posted": time.time() - DAY, "ats": "greenhouse", "active": 1, "company": "Acme"}
    score, why = match.score_job(job, s, set(), {})
    assert score <= match.OUT_OF_SCOPE < min(onboarding.PICKY.values())
    assert why[0] == "- outside what you're looking for: not your level (a new grad role)"


def test_setup_counts_matches_live_without_saving_your_choices():
    _job("a")                                                    # NYC intern, Software
    _job("b", locations=("San Francisco, CA",))
    _job("c", title="Software Engineer", terms=("New Grad",))
    _job("d", category="Hardware", title="FPGA Intern")
    _job("e", age_days=120)
    _job("f", status="submitted")                                # already sent: not a match to count
    db.set_settings(_settings())
    before = db.get_settings()
    assert match.preview({})["matches"] == 2                     # a, b: anywhere in the US
    ny = match.preview({"target_locations": onboarding.LOCATIONS["New York"]})
    assert ny["matches"] == 1 and ny["outside"]["place"] >= 1
    both = match.preview({"goals": ["internship", "newgrad"], "target_terms": ["Summer 2027", "New Grad"],
                          "target_categories": ["Software", "Hardware"], "max_posting_age_days": 0})
    assert both["matches"] == 5
    assert db.get_settings() == before


def _trusted(site):
    db.x("INSERT INTO first_runs(job_id, site, asked_at, approved_at) VALUES(?,?,?,?)",
         (f"earlier-{site}", site, db.now(), db.now()))


def _row(jid):
    return db.q1("SELECT id, url, referral_url, ats FROM jobs WHERE id=?", (jid,))


def test_day_one_is_one_supervised_application_not_a_pile():
    jobs = [_row(_job(f"j{i}", company=f"Co{i}")) for i in range(5)]
    assert guardrails.first_run_room(jobs, [], 10) == ["j0"]          # nothing approved yet: one
    assert guardrails.first_run_room(jobs[1:], [jobs[0]], 10) == []   # while it's being filled: none more
    guardrails.ask_approval("j0", "greenhouse")
    db.x("UPDATE jobs SET status='filled' WHERE id='j0'")
    assert guardrails.first_run_room(jobs[1:], [], 10) == []          # while it waits for you: none more


def test_after_your_first_approval_one_waits_per_new_site():
    _trusted("greenhouse")
    gh = [_row(_job(f"g{i}", company=f"G{i}")) for i in range(3)]
    lever = [_row(_job(f"l{i}", company=f"L{i}", ats="lever", url=f"https://jobs.lever.co/l{i}/x")) for i in range(3)]
    picked = guardrails.first_run_room(gh + lever, [], 10)
    assert picked == ["g0", "g1", "g2", "l0"]                         # trusted site: all; Lever: its first only
    guardrails.ask_approval("l0", "lever")
    db.x("UPDATE jobs SET status='filled' WHERE id='l0'")
    assert guardrails.first_run_room(lever[1:], [], 10) == []
    assert guardrails.first_run_room(gh, [], 2) == ["g0", "g1"]       # the limit still holds


def test_scheduler_picks_one_on_day_one(tmp_path):
    from conftest import resume_pdf
    resume_pdf(tmp_path)
    for i in range(6):
        _job(f"p{i}", company=f"P{i}")
    db.set_settings(_settings() | {"min_fit_score": 0, "max_applications_per_day": 0})
    match.rescore()
    assert len(scheduler.pick_new_jobs(10)) == 1


def test_nothing_runs_on_its_own_until_setup_is_done():
    db.set_settings({"auto_run": True, "onboarded": False, "setup_step": ""})
    assert not scheduler.enabled(db.get_settings())
    onboarding.finish("autopilot", final=False)                      # the website saves the mode one step early
    assert not scheduler.enabled(db.get_settings())
    onboarding.skip()                                                # skipping opens the dashboard, autopilot off
    s = db.get_settings()
    assert s["onboarded"] and not s["auto_run"] and not scheduler.enabled(s)
    db.set_settings({"auto_run": True})
    assert not scheduler.enabled(db.get_settings())                  # even switched on: setup isn't done
    onboarding.finish("autopilot")
    assert scheduler.enabled(db.get_settings())


# --------------------------------------------------------------------------- the one list of questions
def _field(label, options=("Yes", "No"), required=True, qtype="radio"):
    return {"field": "q1", "label": label, "qtype": qtype, "required": required, "options": list(options)}


def _answers(**kv):
    from jobsmith import profile
    for k, v in kv.items():
        profile.set_answer(k, v, confirmed=True)
    return profile.answers()


def test_in_person_and_relocation_are_yes_only_in_your_places():
    from jobsmith import draft
    db.set_settings({"target_locations": onboarding.LOCATIONS["New York"]})
    ans = _answers(willing_to_relocate="Only in my chosen locations")
    ny, austin = {"locations": ["New York, NY"]}, {"locations": ["Austin, TX"]}
    for label in ("Are you willing to relocate?", "Are you able to work in the office 3 days a week?",
                  "Are you willing to work on-site?"):
        here = draft.deterministic(_field(label), ans, ny)
        assert here["answer"] == "Yes" and "New York, NY is one of your places" in here["rationale"], label
        there = draft.deterministic(_field(label), ans, austin)
        assert there["answer"] == "" and "Austin, TX, which isn't one of your places" in there["issues"][0], label
    anywhere = _answers(willing_to_relocate="Yes, anywhere")
    assert draft.deterministic(_field("Are you willing to relocate?"), anywhere, austin)["answer"] == "Yes"


def test_an_unconfirmed_relocation_answer_is_never_used():
    from jobsmith import draft, profile
    profile.set_answer("willing_to_relocate", "Yes, anywhere", confirmed=False)
    r = draft.deterministic(_field("Are you willing to relocate?"), profile.answers(), {"locations": ["Austin, TX"]})
    assert r["answer"] == "" and r["issues"]


def test_years_counted_the_other_way_wait_for_you():
    from jobsmith import draft
    f = lambda label: _field(label, options=(), qtype="text")
    ans = _answers(years_experience="2", internships_count="Yes")
    assert draft.deterministic(f("How many years of professional experience do you have?"), ans, {})["answer"] == "2"
    held = draft.deterministic(f("How many years of experience do you have, excluding internships?"), ans, {})
    assert held["answer"] == "" and "without internships" in held["issues"][0]
    ans = _answers(internships_count="No")
    held = draft.deterministic(f("How many years of experience do you have (including internships)?"), ans, {})
    assert held["answer"] == "" and "with internships" in held["issues"][0]


def test_work_authorization_and_sponsorship_have_no_default_and_only_you_answer_them():
    qs = {q["key"]: q for q in onboarding.questions()}
    for k in ("work_authorized_us", "needs_sponsorship", "resume_lists_all_employers"):
        assert qs[k]["required"] and not qs[k].get("default") and qs[k]["value"] == "", k
    assert not onboarding.questions_done()
    missing = onboarding.save_questions({"work_authorized_us": "Yes"})
    assert "Will you need visa sponsorship, now or later?" in missing
    onboarding.save_questions({"needs_sponsorship": "Maybe"})        # not one of its choices: not saved
    assert {q["key"]: q for q in onboarding.questions()}["needs_sponsorship"]["value"] == ""
    onboarding.save_questions({"needs_sponsorship": "No", "resume_lists_all_employers": "Yes"})
    assert onboarding.questions_done()


def test_voluntary_questions_decline_but_keep_an_answer_you_gave():
    from jobsmith import profile
    profile.set_answer("veteran_status", "I am not a protected veteran", confirmed=True)
    onboarding.save_questions({"voluntary": "Decline to answer"})
    a = profile.answers()
    assert a["gender"]["value"] == onboarding.DECLINE and a["gender"]["confirmed"]
    assert a["veteran_status"]["value"] == "I am not a protected veteran"
    assert {q["key"]: q for q in onboarding.questions()}["voluntary"]["value"] == "I'll answer them on my Profile"


def test_checking_what_was_read_confirms_only_what_you_saw():
    from fastapi.testclient import TestClient
    from jobsmith import profile
    from jobsmith.api import app
    profile.set_answer("email", "alex@example.com", confirmed=False)
    profile.set_answer("work_authorized_us", "Yes", confirmed=False)      # read from somewhere, never shown in step 2
    c = TestClient(app)
    r = c.post("/api/onboarding/confirm", json={"values": {"email": "alex.rivera@example.com", "first_name": "Alex",
                                                           "work_authorized_us": "Yes"}}).json()
    a = profile.answers()
    assert a["email"]["value"] == "alex.rivera@example.com" and a["email"]["confirmed"]
    assert not a["work_authorized_us"]["confirmed"]                         # rule 2: only step 3 asks it
    assert {x["key"] for x in r["read_back"]} == set(onboarding.READ_BACK)


def test_setup_saves_level_and_brings_its_list_and_the_count_matches(monkeypatch):
    from fastapi.testclient import TestClient
    from jobsmith import api
    monkeypatch.setattr(api, "spawn_sync", lambda: None)
    _job("a")
    _job("b", title="Software Engineer", terms=("New Grad",))
    c = TestClient(api.app)
    body = {"levels": ["newgrad"], "categories": ["Software"], "locations": ["New York"], "picky": "good"}
    assert c.post("/api/onboarding/preview", json=body).json()["matches"] == 1
    c.post("/api/onboarding/looking", json=body)
    s = db.get_settings()
    assert s["goals"] == ["newgrad"] and s["target_terms"] == ["New Grad"] and s["prefs_saved"]
    presets = {p["key"]: p["on"] for p in c.get("/api/onboarding").json()["presets"]}
    assert presets == {"simplify_internships": False, "simplify_newgrad": True}
    assert db.q1("SELECT COUNT(*) n FROM jobs WHERE fit_score >= 40")["n"] == 1


def test_a_pdf_read_without_ai_still_fills_in_what_setup_shows_back():
    from jobsmith import profile
    text = ("Alex Rivera\nBoston, MA | (617)-555-0123 | alex.rivera@example.edu | https://www.linkedin.com/in/alex-rivera-test/ |\n"
            "https://github.com/alexr-test | US Citizen\nEDUCATION\nExample Institute of Technology; GPA: 3.62/4.00 | "
            "Expected May 2027 | Bachelor of Science in Computer\nEngineering | Coursework: Data Structures\n")
    ident, parsed = profile.identity_from_text(text)
    assert ident == {"email": "alex.rivera@example.edu", "phone": "(617)-555-0123", "name": "Alex Rivera",
                     "linkedin": "https://www.linkedin.com/in/alex-rivera-test",
                     "github": "https://github.com/alexr-test", "location": "Boston, MA"}
    profile.seed_answers_from_identity(ident, parsed)
    got = {r["key"]: (r["value"], r["confirmed"]) for r in onboarding.read_back()}
    assert got["first_name"] == ("Alex", False) and got["school"] == ("Example Institute of Technology", False)
    assert got["gpa"][0] == "3.62" and got["graduation_date"][0] == "May 2027" and got["major"][0] == "Computer Engineering"


def test_a_work_authorization_read_from_a_resume_is_a_hint_never_a_pick():
    from jobsmith import profile
    profile.set_answer("work_authorized_us", "Yes", confirmed=False)
    q = {x["key"]: x for x in onboarding.questions()}["work_authorized_us"]
    assert q["value"] == "" and q["hint"] == "Your resume says: Yes"


def test_saving_choices_and_lists_starts_a_sync_without_failing(monkeypatch):
    """Both start a background sync, which needs the server's event loop: a plain function's thread has none."""
    from fastapi.testclient import TestClient
    from jobsmith import api, sources

    async def no_sync():
        return []
    monkeypatch.setattr(sources, "sync_all", no_sync)
    c = TestClient(api.app)
    assert c.post("/api/onboarding/looking", json={"levels": ["internship"], "categories": ["Software"]}).status_code == 200
    r = c.post("/api/onboarding/sources", json={"presets": ["simplify_internships"]})
    assert r.status_code == 200 and r.json()["step_done"]["sources"]
