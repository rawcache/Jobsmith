"""Fixes from triaging real held applications: each test is a question a real form asked, reworded only to drop
the company's name."""
import pytest

from jobsmith import classify, draft, profile

JOB = {"id": "j1", "company": "Acme Robotics", "title": "Software Engineer Intern", "locations": ["New York, NY"]}


def field(label, qtype="select", options=None, required=True, name="q"):
    return {"field": name, "label": label, "qtype": qtype, "options": options or [], "required": required}


# Work authorization, citizenship, export control and demographic questions are answered from your confirmed
# profile or left for you, never by AI and never by an answer reused from another job (rule 2).
PROFILE_ONLY = [
    field("U.S. WORK AUTHORIZATION", options=["Yes", "No"]),
    field("Do you have lawful authorization to work in the U.S.?", options=["Yes", "No"]),
    field("Do you identify as transgender?", options=["Yes", "No", "I don't wish to answer"]),
    field("How would you describe your racial/ethnic background?", "multiselect",
          ["Black or of African descent", "East Asian", "Middle Eastern or North African"], required=False),
    field("Are you a Dual citizen?", options=["Yes", "No"]),
    field("If you are a dual citizen, which other country are you a citizen of?", "text"),
    field("EXPORT COMPLIANCE", options=["I am currently a “U.S. Person”", "I am not a “U.S. Person\""]),
    field("Have you ever been the subject to a specific authorization under Part 810 to receive access to Part "
          "810-controlled technology?", options=["Yes", "No"]),
    field("Please confirm whether any of the below applies to you. Select all that apply. Note: This information "
          "will only be used to ensure compliance with U.S. sanctions and export controls.", "multiselect",
          ["I am a citizen of Cuba, Iran, North Korea or Syria", "None of the above"]),
    field("If you selected a response to the prior question other than “none of the above,” please confirm "
          "whether any of the following apply", "multiselect", ["U.S. citizen", "U.S. permanent resident"]),
    field("Are you a citizen of any country that is NOT included in the list below?", options=["Yes", "No"]),
    field("For export compliance, are you a national of any of the countries listed below?", options=["Yes", "No"]),
    field("What is your ethnic heritage?", "text"),
    field("Ethnic category", "text"),
    field("Please select the highest level security clearance and access you currently hold",
          options=["Secret", "Top Secret", "TS/SCI"]),
]


@pytest.mark.parametrize("f", PROFILE_ONLY, ids=lambda f: f["label"][:40])
def test_profile_only_questions_never_reach_ai(f):
    got = draft.offline(f, profile.answers(), JOB)
    assert got is not None, "would have been sent to AI"
    assert got["kind"] == "answer_bank" and got["answer"] == ""
    assert got["issues"] if f["required"] else not got["issues"]


def test_work_authorization_wordings_answer_from_profile():
    profile.set_answer("work_authorized_us", "Yes", confirmed=True)
    for label in ("U.S. WORK AUTHORIZATION", "Do you have lawful authorization to work in the U.S.?"):
        assert classify.canon_for(label) == "work_authorized_us", label
        got = draft.offline(field(label, options=["Yes", "No"]), profile.answers(), JOB)
        assert got["answer"] == "Yes" and not got["issues"], label


def test_racial_ethnic_background_is_race():
    assert classify.canon_for("How would you describe your racial/ethnic background?") == "race"
    assert classify.canon_for("Race / Ethnicity") == "race"


def test_export_compliance_is_us_person():
    assert classify.canon_for("EXPORT COMPLIANCE") == "us_person"


def test_a_demographic_question_that_isnt_a_plain_yes_no_waits_for_you():
    # Rule 2 as one rule: your confirmed answer to a plain question about that one fact. A question your profile
    # has no answer to waits, even when you chose to decline every voluntary one.
    profile.set_answer("gender", "Male", confirmed=False)                      # read from somewhere, not confirmed
    got = draft.offline(field("Gender", options=["Male", "Female", "Decline to self-identify"]), profile.answers(), JOB)
    assert got["answer"] == "" and got["issues"]
    for k in ("gender", "race", "hispanic_latino", "veteran_status", "disability_status", "lgbtq"):
        profile.set_answer(k, "Decline to self-identify", confirmed=True)
    f = field("Do you identify as transgender?", options=["Yes", "No", "I don't wish to answer"])
    got = draft.offline(f, profile.answers(), JOB)
    assert got["answer"] == "" and got["issues"]
    assert draft.offline(dict(f, required=False), profile.answers(), JOB)["answer"] == ""   # optional: left blank


def test_a_plain_demographic_yes_no_gets_your_confirmed_answer():
    f = field("Do you identify as Hispanic/Latino?", options=["Yes", "No"])
    profile.set_answer("hispanic_latino", "No", confirmed=False)
    assert draft.offline(f, profile.answers(), JOB)["answer"] == ""             # not confirmed: waits
    profile.set_answer("hispanic_latino", "No", confirmed=True)
    assert draft.offline(f, profile.answers(), JOB)["answer"] == "No"
    three = field("Do you identify as Hispanic/Latino?", options=["Yes", "No", "Decline to self-identify"])
    assert draft.offline(three, profile.answers(), JOB)["answer"] == "No"       # your No, among three choices


@pytest.mark.parametrize("options", [["Woman", "Man", "Non-binary", "Decline to self-identify"],
                                     ["I am a woman", "I am a man"], ["Woman (F)", "Man (M)"],
                                     ["I am female", "I am male"],
                                     ["Protected veteran", "Not a protected veteran"],
                                     ["Asian", "Black", "White", "Decline to self-identify"]])
def test_demographic_options_under_a_vague_label_stay_yours(options):
    got = draft.offline(field("Please select your status", options=options), profile.answers(), JOB)
    assert got is not None and got["answer"] == ""


@pytest.mark.parametrize("label", ["Are you willing to relocate to other countries?",
                                   "Are you willing to relocate to any of the countries listed below?",
                                   "Describe a project involving data export",
                                   "Describe your experience working with ethnically diverse teams"])
def test_ordinary_questions_are_not_profile_only(label):
    assert not draft._profile_only(field("Language Skill(s)", "multiselect", ["English", "Mandarin (MAN)", "German"]))
    assert draft._profile_only(field("Please select your status", options=["I am a woman", "I am a man"]))
    assert draft._profile_only(field("Please select your status", options=["Woman (F)", "Man (M)"]))
    assert classify.canon_for(label) not in ("other_citizenship", "race")
    assert not draft._profile_only(field(label, "textarea"))


def test_yes_no_profile_facts_never_answer_a_different_question():
    profile.set_answer("work_authorized_us", "Yes", confirmed=True)
    profile.set_answer("us_citizen", "Yes", confirmed=True)
    profile.set_answer("needs_sponsorship", "No", confirmed=True)
    for f in (field("Can you provide your work authorization expiration date?", "text"),
              field("Are you authorized to work in the US, and if so until what date?", "text"),
              field("What is your work authorization expiration date?", "text"),
              field("What type of work authorization do you have?", "text"),
              field("Will your work authorization expire in the next two years?", "text"),
              field("Work authorization document number", "text"),
              field("Please state whether you have ever been denied work authorization in the United States.", "text"),
              field("Have you ever been denied a U.S. visa?", options=["Yes", "No"]),
              field("Did you ever require visa sponsorship?", options=["Yes", "No"]),
              field("Have you previously required sponsorship, or will you ever require it?", options=["Yes", "No"]),
              field("Will you ever require sponsorship, given a visa that was revoked?", "text"),
              field("Will you please indicate whether you have ever required visa sponsorship?", "text"),
              field("Have you, at any time during your professional career, ever required visa sponsorship?", "text"),
              field("Work authorization valid through date", "text"),
              field("Does your visa expire in the next two years?", options=["Yes", "No"]),
              field("Please describe your work authorization", "text"),
              field("Please explain why you need visa sponsorship", "text"),
              field("Do you require an export compliance license?", options=["Yes", "No"]),
              field("For export compliance, are you a national of any of the countries listed below?",
                    options=["Yes", "No"])):
        got = draft.offline(f, profile.answers(), JOB)
        assert got is not None and got["answer"] == "", f["label"]
    yes_no = ["Yes", "No"]
    for label in ("Are you legally authorized to work in the United States?",
                  "Please confirm you are legally authorized to work in the United States.",
                  "* Are you legally authorized\nto work in the US?",
                  "Are you authorized to work lawfully in the United States for Acme Robotics?"):
        assert draft.offline(field(label, options=yes_no), profile.answers(), JOB)["answer"] == "Yes", label
        assert draft.offline(field(label, "text"), profile.answers(), JOB)["answer"] == "", label   # free text waits
    for label in ("Do you require sponsorship for any type of work visa?",
                  "Will you now or in the future require sponsorship for employment visa status (e.g. H-1B)?",
                  "Do you require visa sponsorship now or at a later date?",
                  "Will you now or ever require visa sponsorship?",
                  "Will you now, or ever require visa sponsorship?"):
        assert draft.offline(field(label, options=yes_no), profile.answers(), JOB)["answer"] == "No", label
        assert draft.offline(field(label, "text"), profile.answers(), JOB)["answer"] == "", label
    # an unfamiliar word means it waits: a condition, a negation, a history, a place
    for label in ("Will you require sponsorship when your current authorization expires?",
                  "Are you authorized to work in the United States without sponsorship?",
                  "Are you not authorized to work in the United States?",
                  "Have you ever required visa sponsorship?",
                  "Are you authorized to work in Canada?",
                  "Are you authorized to work in the US or Canada?"):
        assert draft.offline(field(label, options=yes_no), profile.answers(), JOB)["answer"] == "", label


def test_a_question_naming_no_country_means_the_jobs():
    profile.set_answer("needs_sponsorship", "No", confirmed=True)
    f = field("Will you require visa sponsorship?", options=["Yes", "No"])
    assert draft.offline(f, profile.answers(), JOB)["answer"] == "No"
    for where in (["London, UK"], ["New York, NY", "London, UK"], [], ["Remote"]):
        assert draft.offline(f, profile.answers(), dict(JOB, locations=where))["answer"] == "", where


def test_an_ai_answer_to_a_rule_2_question_saved_before_this_rule_isnt_sent():
    from jobsmith import db, sources
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/2", "Acme Robotics", "Software Intern")
    db.x("UPDATE jobs SET locations=? WHERE id=?", (db.enc(["New York, NY"]), jid))
    f = field("Have you ever been denied a U.S. visa?", options=["Yes", "No"])
    draft.save_results(jid, [f], {"q": {"kind": "generated", "answer": "No", "confidence": 0.95, "issues": []}})
    assert any("profile" in i["issue"] for i in draft.readiness(jid)["items"])


def test_your_agent_cant_answer_a_rule_2_question():
    import json
    from jobsmith import db, mcp_server, sources
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/3", "Acme Robotics", "Software Intern")
    f = field("Please describe your visa situation", "textarea")
    draft.save_results(jid, [f], {"q": {"kind": "generated", "answer": "", "confidence": 0.2, "issues": ["x"]}})
    got = json.loads(mcp_server.jobsmith_save_answers(jid, [{"field": "q", "text": "I hold a visa.", "fact_ids": []}]))
    assert "error" in got["saved"][0]
    assert draft.drafts_for(jid)[0]["answer"] == ""



def test_a_plain_question_must_name_the_fact_and_a_company_name_cant_hide_a_word():
    profile.set_answer("needs_sponsorship", "No", confirmed=True)
    profile.set_answer("us_citizen", "Yes", confirmed=True)
    f = field("Are you currently working in the US with a visa?", options=["Yes", "No"])
    assert draft.offline(f, profile.answers(), JOB)["answer"] == ""             # sponsorship's words, another fact
    not_acme = dict(JOB, company="Not Acme")
    assert draft.offline(field("Are you not a US citizen?", options=["Yes", "No"]), profile.answers(),
                         not_acme)["answer"] == ""
    assert draft.offline(field("Are you a US citizen?", options=["Yes", "No"]), profile.answers(),
                         not_acme)["answer"] == "Yes"


@pytest.mark.parametrize("f", [field("Do you have a work permit?", options=["Yes", "No"]),
                               field("What is your national origin?", "text"),
                               dict(field("Additional information", "textarea"),
                                    description="Please explain your visa status"),
                               field("Cover letter explaining your visa status", "file", name="cover_letter")],
                         ids=lambda f: f["label"][:30])
def test_more_rule_2_questions_wait_for_you(f):
    got = draft.offline(f, profile.answers(), JOB)
    assert got is not None and got["answer"] == "" and got["issues"]


def test_a_plain_question_with_a_note_under_it_waits():
    profile.set_answer("work_authorized_us", "Yes", confirmed=True)
    f = dict(field("Are you authorized to work in the United States?", options=["Yes", "No"]),
             description="Answer No if your authorization depends on your current employer")
    assert draft.offline(f, profile.answers(), JOB)["answer"] == ""


@pytest.mark.parametrize("label", ["Are you non-binary?", "Do you identify as Black?",
                                   "Do you have permission to work in the US?"])
def test_these_are_rule_2_too(label):
    got = draft.offline(field(label, options=["Yes", "No"]), profile.answers(), JOB)
    assert got is not None and got["answer"] == "" and got["issues"]


def test_a_company_name_counts_only_where_a_company_goes():
    profile.set_answer("us_citizen", "Yes", confirmed=True)
    one_word = dict(JOB, company="Not")
    assert draft.offline(field("Are you not a US citizen?", options=["Yes", "No"]), profile.answers(),
                         one_word)["answer"] == ""
    profile.set_answer("work_authorized_us", "Yes", confirmed=True)
    assert draft.offline(field("Are you authorized to work in the US for Not?", options=["Yes", "No"]),
                         profile.answers(), one_word)["answer"] == "Yes"


def test_needing_sponsorship_answers_only_a_question_about_later_and_no_one_visa():
    # your Yes means now or later, any visa: "currently" or "H-1B" alone may have another answer
    profile.set_answer("needs_sponsorship", "Yes", confirmed=True)
    ask = lambda label: draft.offline(field(label, options=["Yes", "No"]), profile.answers(), JOB)["answer"]
    assert ask("Will you now or in the future require visa sponsorship?") == "Yes"
    assert ask("Do you currently require visa sponsorship in the US?") == ""
    assert ask("Will you require H-1B sponsorship in the US?") == ""
    profile.set_answer("needs_sponsorship", "No", confirmed=True)        # a No is true of every narrower question
    assert ask("Do you currently require visa sponsorship in the US?") == "No"


def test_saved_drafts_keep_the_note_under_their_question():
    import json
    from jobsmith import db, mcp_server, sources
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/4", "Acme Robotics", "Software Intern")
    q = dict(field("Additional information", "textarea"), description="Please explain your visa status")
    db.x("UPDATE jobs SET questions=? WHERE id=?", (db.enc([q]), jid))
    draft.save_results(jid, [q], {"q": {"kind": "generated", "answer": "I hold an F-1 visa.", "confidence": 0.95,
                                        "issues": []}})                  # written by AI before this rule
    assert draft.readiness(jid)["items"]
    got = json.loads(mcp_server.jobsmith_save_answers(jid, [{"field": "q", "text": "F-1.", "fact_ids": []}]))
    assert "error" in got["saved"][0]


@pytest.mark.parametrize("f", [field("Password", "text", name="#password"),
                               field("Confirm password", "text", name="confirm"),
                               field("Create a PIN", "text", name="#pin")], ids=lambda f: f["label"])
def test_a_password_box_is_never_drafted(f):
    got = draft.offline(f, profile.answers(), JOB)
    assert got is not None and got["answer"] == ""                  # never AI's to write (rule 5)
    assert got["issues"]


def test_a_site_password_for_your_portfolio_is_still_asked():
    # "Portfolio, Video, or Website Password": the password to your own work, which only you know
    profile.set_answer("website", "https://alexrivera.example", confirmed=True)
    got = draft.offline(field("Portfolio, Video, or Website Password", "text", required=False), profile.answers(), JOB)
    assert got is not None and got["answer"] == ""


@pytest.mark.parametrize("label", ["Portfolio PIN code", "Enter the PIN code sent to your email address",
                                   "Portfolio access\nPIN code", "Postal / PIN code"])
def test_every_pin_waits_for_you(label):
    got = draft.offline(field(label, "text"), profile.answers(), JOB)
    assert got is not None and got["answer"] == "" and got["issues"]


async def test_eu_greenhouse_postings_come_from_the_one_api_host():
    import httpx
    from jobsmith import jobdetail
    asked = []

    def handle(req):
        asked.append(req.url.host)
        if req.url.host != "boards-api.greenhouse.io":
            raise httpx.ConnectError("nodename nor servname provided, or not known", request=req)
        return httpx.Response(200, json={"id": 4962456101, "title": "Machine Learning Engineer Intern",
                                         "absolute_url": "https://job-boards.eu.greenhouse.io/acme/jobs/4962456101",
                                         "content": "", "questions": [], "location": {"name": "Amsterdam"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        got = await jobdetail.fetch_greenhouse("https://job-boards.eu.greenhouse.io/acme/jobs/4962456101", client)
    assert asked == ["boards-api.greenhouse.io"]
    assert got["title"] == "Machine Learning Engineer Intern"
    assert "job-boards.eu.greenhouse.io" in got["apply_url"]           # the form is still the EU board's


# One question, read twice: the posting's API calls it "question_7", the live page "#question_7". Each one is one
# thing for you to do, and the answer you gave one is the answer to the other.
TRANSGENDER = {"field": "question_7", "label": "Do you identify as transgender?", "qtype": "select", "required": True,
               "options": ["Yes", "No", "I don't wish to answer"]}


def _greenhouse_job() -> str:
    from jobsmith import db, sources
    jid = sources.add_job_url("https://job-boards.greenhouse.io/acme/jobs/1", "Acme Robotics", "Software Intern")
    db.x("UPDATE jobs SET questions=? WHERE id=?", (db.enc([TRANSGENDER]), jid))
    return jid


def test_a_question_read_twice_is_one_thing_to_do():
    jid = _greenhouse_job()
    twin = dict(TRANSGENDER, field="#question_7")
    blank = {"kind": "answer_bank", "answer": "", "confidence": 0, "issues": ["answer it yourself"]}
    draft.save_results(jid, [TRANSGENDER], {"question_7": blank})
    draft.save_results(jid, [twin], {"#question_7": blank})
    assert len(draft.readiness(jid)["items"]) == 1


async def test_the_second_pass_reuses_the_answer_to_its_twin(monkeypatch):
    from jobsmith import db
    from jobsmith.fill import sweep
    jid = _greenhouse_job()
    draft.save_results(jid, [TRANSGENDER], {"question_7": {"kind": "answer_bank", "answer": "", "confidence": 0,
                                                           "issues": ["answer it yourself"]}})
    db.x("UPDATE drafts SET final_answer='No' WHERE job_id=? AND field='question_7'", (jid,))   # you answered it
    filled = []

    async def scan(page):
        return [dict(TRANSGENDER, field="#question_7", value="")]

    async def fill(page, sel, qtype, val, *a):
        filled.append((sel, val))
        return True

    async def no_ai(*a, **k):
        raise AssertionError("asked again")
    monkeypatch.setattr(sweep, "scan_form", scan)
    monkeypatch.setattr(sweep, "fill_field", fill)
    monkeypatch.setattr(sweep.draft, "answer_fields", no_ai)
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    await sweep.sweep(None, job)
    assert filled == [("#question_7", "No")]
    assert [d["field"] for d in draft.drafts_for(jid)] == ["question_7"]


@pytest.mark.parametrize("pending_first", [True, False])
def test_of_two_copies_the_one_that_needs_you_is_kept(pending_first):
    jid = _greenhouse_job()
    twin = dict(TRANSGENDER, field="#question_7")
    pending = {"kind": "pending", "answer": "", "confidence": 0, "issues": [draft.PENDING_ISSUE]}
    yours = {"kind": "answer_bank", "answer": "", "confidence": 0, "issues": ["answer it yourself"]}
    first, second = (pending, yours) if pending_first else (yours, pending)
    draft.save_results(jid, [TRANSGENDER], {"question_7": first})
    draft.save_results(jid, [twin], {"#question_7": second})
    [item] = draft.readiness(jid)["items"]
    assert not item.get("pending")


async def _sweep_once(monkeypatch, jid, live):
    from jobsmith import db
    from jobsmith.fill import sweep
    filled = []

    async def scan(page):
        return [dict(live, value="")]

    async def fill(page, sel, qtype, val, *a):
        filled.append((sel, val))
        return True
    monkeypatch.setattr(sweep, "scan_form", scan)
    monkeypatch.setattr(sweep, "fill_field", fill)
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    return filled, await sweep.sweep(None, job)


async def test_a_turned_down_twin_stays_blank_and_a_filled_one_is_audited_by_its_saved_id(monkeypatch):
    from jobsmith import db
    jid = _greenhouse_job()
    draft.save_results(jid, [TRANSGENDER], {"question_7": {"kind": "answer_bank", "answer": "", "confidence": 0,
                                                           "issues": ["answer it yourself"]}})
    db.x("UPDATE drafts SET final_answer='No' WHERE job_id=?", (jid,))
    filled, res = await _sweep_once(monkeypatch, jid, dict(TRANSGENDER, field="#question_7"))
    assert filled == [("#question_7", "No")] and res["sent"] == ["question_7"]
    db.x("UPDATE drafts SET final_answer=NULL, answer='No', verdict='red' WHERE job_id=?", (jid,))
    filled, res = await _sweep_once(monkeypatch, jid, dict(TRANSGENDER, field="#question_7"))
    assert filled == [] and res["sent"] == []


async def test_a_rule_2_twin_with_other_choices_on_the_page_gets_its_own_check(monkeypatch):
    from jobsmith import db
    profile.set_answer("hispanic_latino", "No", confirmed=True)
    jid = _greenhouse_job()
    api = {"field": "question_8", "label": "Are you Hispanic/Latino?", "qtype": "select", "required": True,
           "options": ["Yes", "No"]}
    draft.save_results(jid, [api], {"question_8": draft.deterministic(api, profile.answers(), {})})
    live = dict(api, field="#question_8", options=["Mexican", "Puerto Rican", "Cuban"])
    filled, res = await _sweep_once(monkeypatch, jid, live)
    assert filled == [] and res["sent"] == []                       # no choice on the page means your No: yours
    assert db.q1("SELECT answer FROM drafts WHERE job_id=? AND field='question_8'", (jid,))["answer"] == "No"


async def test_your_decision_on_a_twin_stands_even_when_the_page_shows_other_choices(monkeypatch):
    from jobsmith import db
    profile.set_answer("hispanic_latino", "No", confirmed=True)
    jid = _greenhouse_job()
    api = {"field": "question_8", "label": "Are you Hispanic/Latino?", "qtype": "select", "required": True,
           "options": ["Yes", "No", "Decline to self-identify"]}
    draft.save_results(jid, [api], {"question_8": draft.deterministic(api, profile.answers(), {})})
    live = dict(api, field="#question_8", options=["Yes", "No"])
    db.x("UPDATE drafts SET final_answer='Yes' WHERE job_id=?", (jid,))              # your own answer
    filled, _ = await _sweep_once(monkeypatch, jid, live)
    assert filled == [("#question_8", "Yes")]
    db.x("UPDATE drafts SET final_answer=NULL, answer='No', verdict='red' WHERE job_id=?", (jid,))   # turned down
    filled, _ = await _sweep_once(monkeypatch, jid, live)
    assert filled == []


async def test_a_rule_2_answer_the_page_doesnt_offer_exactly_isnt_swapped_for_another(monkeypatch):
    from jobsmith import db
    jid = _greenhouse_job()
    draft.save_results(jid, [TRANSGENDER], {"question_7": {"kind": "answer_bank", "answer": "", "confidence": 0,
                                                           "issues": ["answer it yourself"]}})
    db.x("UPDATE drafts SET final_answer='No' WHERE job_id=?", (jid,))
    live = dict(TRANSGENDER, field="#question_7", options=["Yes", "Prefer not to answer"])
    filled, res = await _sweep_once(monkeypatch, jid, live)
    assert filled == [] and res["sent"] == []


@pytest.mark.parametrize("answer,filled", [("Asian; White", True), ("Asian\nWhite", True), ("Asian; Other", False)])
async def test_each_of_several_rule_2_choices_must_be_offered(monkeypatch, answer, filled):
    from jobsmith import db
    jid = _greenhouse_job()
    race = {"field": "question_9", "label": "Race", "qtype": "multiselect", "required": True,
            "options": ["Asian", "White", "Black"]}
    draft.save_results(jid, [race], {"question_9": {"kind": "answer_bank", "answer": "", "confidence": 0,
                                                    "issues": ["answer it yourself"]}})
    db.x("UPDATE drafts SET final_answer=? WHERE job_id=?", (answer, jid))
    got, _ = await _sweep_once(monkeypatch, jid, dict(race, field="#question_9"))
    assert bool(got) == filled


async def test_one_choice_fields_take_one_rule_2_answer(monkeypatch):
    from jobsmith import db
    jid = _greenhouse_job()
    race = {"field": "question_10", "label": "Race", "qtype": "radio", "required": True,
            "options": ["Asian", "White", "Two or more; please specify"]}
    draft.save_results(jid, [race], {"question_10": {"kind": "answer_bank", "answer": "", "confidence": 0,
                                                     "issues": ["answer it yourself"]}})
    db.x("UPDATE drafts SET final_answer='Asian; White' WHERE job_id=?", (jid,))
    got, res = await _sweep_once(monkeypatch, jid, dict(race, field="#question_10"))
    assert got == [] and res["sent"] == []
    db.x("UPDATE drafts SET final_answer='Two or more; please specify' WHERE job_id=?", (jid,))   # exact, whole
    got, _ = await _sweep_once(monkeypatch, jid, dict(race, field="#question_10"))
    assert got == [("#question_10", "Two or more; please specify")]


# Misreads from triage: each label is a real form's question.
@pytest.mark.parametrize("label,want", [
    ("Are you currently enrolled in an Undergraduate program?", None),
    ("Are you returning to an undergraduate or graduate program after this internship?", None),
    ("Are you on track to graduate by June 2027?", "graduation_date"),
    ("Expected graduation date", "graduation_date"),
    ("Please share how you use AI tools today", None),
    ("Do you consent to the use of AI tools to transcribe your interview?", "ai_tools_consent"),
    ("What is your Legal Name?", "full_name"),
    ("Please state your full legal name:", "full_name"),
    ("Legal first name", "first_name"),
    ("Applicant Privacy Acknowledgement", "acknowledge_notices"),
    ("Personal Information Policy", "acknowledge_notices"),
    ("Are you comfortable developing AI models?", None),
    ("Please enter legal name", "full_name"),
    ("Please provide full legal name", "full_name"),
    ("Privacy Policy (required)", "acknowledge_notices"),
    ("Do you consent to AI being used during your interview?", "ai_tools_consent"),
    ("Please enter the legal name of your school", None),
    ("Have you ever changed your legal name?", None),
    ("Please provide a link to your privacy policy", None),
    ("Are you comfortable with the use of AI note-taking in your interview?", "ai_tools_consent"),
])
def test_triage_misreads(label, want):
    assert classify.canon_for(label) == want, label


def test_a_degree_spelled_without_its_apostrophe_is_picked():
    assert classify.pick_option("Bachelor's", ["Associates", "Bachelors", "Masters", "PhD"]) == "Bachelors"
    assert classify.pick_option("Master's", ["Bachelor's Degree", "Master's Degree"]) == "Master's Degree"


def test_male_is_man_but_never_cisgender_man():
    assert classify.pick_option("Male", ["Woman", "Man", "Non-binary"]) == "Man"
    assert classify.pick_option("Female", ["Man", "Woman"]) == "Woman"
    assert classify.pick_option("Man", ["Male", "Female"]) == "Male"
    assert classify.pick_option("Male", ["Cisgender woman", "Cisgender man", "Transgender man", "Non-binary"]) is None


def test_asian_indian_is_asian_never_american_indian():
    eeo = ["Hispanic or Latino A person of Cuban, Mexican, Puerto Rican, South or Central American origin.",
           "White (Not Hispanic or Latino) A person having origins in Europe, the Middle East, or North Africa.",
           "Asian (Not Hispanic or Latino) A person having origins in the Far East, Southeast Asia, or the Indian "
           "Subcontinent, including, for example, China, India, Japan and Korea.",
           "American Indian or Alaska Native (Not Hispanic or Latino) A person having origins in any of the original "
           "peoples of North and South America."]
    assert classify.strict_pick("Asian (Indian)", eeo) is None            # "Not Hispanic" isn't confirmed
    assert classify.strict_pick("Asian (Indian)", eeo, not_hispanic=True) == eeo[2]
    assert classify.strict_pick("Asian (Indian)", ["White\xa0", "Asian\xa0", "Black\xa0"]) == "Asian\xa0"
    assert classify.strict_pick("Asian (Indian)", ["American Indian or Alaska Native", "White"]) is None
    assert classify.pick_option("Asian (Indian)", ["American Indian or Alaska Native", "White"]) is None


def test_none_is_the_no_clearance_choice():
    assert classify.pick_option("None", ["No Clearance", "Secret", "Top Secret"]) == "No Clearance"
    assert classify.pick_option("None", ["Secret", "Top Secret", "TS/SCI"]) is None
    assert classify.pick_option("None", ["None", "No Clearance"]) == "None"


EXPORT_LISTS = [
    ["A United States citizen or national", "A person lawfully admitted for permanent residence of the United States "
     "(i.e., “Green Card” holder)", "A person admitted as a refugee to the United States under 8 U.S.C. 1157",
     "None of the above"],
    ["US citizen or national", 'US permanent resident (i.e., "green card holder")', "None of the above"],
    ["U.S. Citizen", "U.S. lawful permanent resident - Green card", "None of the above"],
    ["U.S. citizen", "U.S. non-citizen national", "U.S. permanent resident (Green Card holder)",
     "Individual granted citizenship in a country other than Cuba, Iran, North Korea, or Syria"],
]


@pytest.mark.parametrize("options", EXPORT_LISTS, ids=lambda o: o[0])
def test_a_confirmed_citizen_gets_the_citizen_choice_on_an_export_control_list(options):
    f = field("This position requires access to information and technology that is subject to US export controls. "
              "Are you any of the following?", options=options)
    assert draft.offline(f, profile.answers(), JOB)["answer"] == ""             # nothing confirmed: yours
    profile.set_answer("us_citizen", "Yes", confirmed=False)
    assert draft.offline(f, profile.answers(), JOB)["answer"] == ""             # read from a resume isn't confirmed
    profile.set_answer("us_citizen", "Yes", confirmed=True)
    got = draft.offline(f, profile.answers(), JOB)
    assert got["answer"] == options[0] and not got["issues"]
    profile.set_answer("us_citizen", "No", confirmed=True)                      # which status then is yours to say
    assert draft.offline(f, profile.answers(), JOB)["answer"] == ""


@pytest.mark.parametrize("options", [["Non-U.S. citizen", "Permanent resident", "Other"],
                                     ["U.S. citizen and hold an active security clearance", "Other"],
                                     ["U.S. citizen", "United States citizen or national"]])
def test_a_citizen_choice_that_says_something_else_waits(options):
    profile.set_answer("us_citizen", "Yes", confirmed=True)
    f = field("This position is subject to US export controls. Are you any of the following?", options=options)
    got = draft.offline(f, profile.answers(), JOB)
    assert got["answer"] == "" and got["issues"]


def test_the_country_specified_for_a_us_job_is_the_us():
    profile.set_answer("work_authorized_us", "Yes", confirmed=True)
    f = field("Are you legally authorized to work in the Country specified for this position?", options=["Yes", "No"])
    assert draft.offline(f, profile.answers(), dict(JOB, locations=["New York, NY"]))["answer"] == "Yes"
    assert draft.offline(f, profile.answers(), dict(JOB, locations=["London, UK"]))["answer"] == ""
    assert draft.offline(f, profile.answers(), dict(JOB, locations=[]))["answer"] == ""


def test_legal_name_and_privacy_policy_of_something_else():
    assert classify.canon_for("Please enter legal name for your previous employer") is None
    assert classify.canon_for("Privacy Policy effective date") is None


GENDER = ["Woman", "Man", "Non-binary", "Decline to self-identify"]


@pytest.mark.parametrize("key,value,label,options,want", [
    ("gender", "Male", "Gender", GENDER, "Man"),
    ("gender", "Male", "What is your gender identity?", GENDER, "Man"),
    ("gender", "Male", "What is your gender identity?", ["Cisgender woman", "Cisgender man", "Two-spirit"], ""),
    ("gender", "Male", "Which gender were you assigned at birth?", GENDER, ""),          # another question
    ("gender", "Decline to self-identify", "Gender", GENDER, "Decline to self-identify"),
    ("race", "Asian (Indian)", "Race", ["White", "Asian", "American Indian or Alaska Native"], "Asian"),
    ("race", "Asian (Indian)", "Race", ["White", "Asian (Not Hispanic or Latino)"], ""),   # not confirmed non-Hispanic
    ("race", "Asian (Indian)", "Race", ["White", "Asian (East Asian)"], ""),               # another ancestry
    ("race", "White", "Race", ["White (Hispanic or Latino)", "Asian"], ""),
    ("security_clearance", "Secret", "Security clearance level", ["Secret / SCI", "None"], ""),
    ("disability_status", "Yes", "Disability Status",
     ["Previously had a disability", "No disability", "Decline to self-identify"], ""),
    ("disability_status", "No", "Disability Status",
     ["Yes, I have a disability", "No, I do not have a disability", "I do not want to answer"],
     "No, I do not have a disability"),
    ("disability_status", "No", "Disability Status",
     ["Yes", "No, I do not have a disability and have not had one in the past"], ""),      # says more than your No
    ("race", "Asian (Indian)", "How would you describe your racial/ethnic background?",
     ["East Asian", "South Asian", "White"], ""),                                         # which one is yours to say
    ("race", "Asian (Indian)", "Race", ["American Indian or Alaska Native", "White"], ""),
    ("veteran_status", "No", "Protected Veteran Status",
     ["I am not a protected veteran", "I identify as a protected veteran", "I don't wish to answer"],
     "I am not a protected veteran"),
    ("security_clearance", "None", "Do you currently hold a security clearance?", ["No Clearance", "Secret"],
     "No Clearance"),
    ("security_clearance", "None", "Please select the highest level security clearance you currently hold",
     ["Secret", "Top Secret", "TS/SCI"], ""),
])
def test_a_confirmed_answer_is_picked_only_from_a_plain_question_and_one_matching_choice(key, value, label, options, want):
    profile.set_answer(key, value, confirmed=True)
    got = draft.offline(field(label, options=options), profile.answers(), JOB)
    assert got["answer"] == want and bool(got["issues"]) == (not want)
    profile.set_answer(key, value, confirmed=False)
    assert draft.offline(field(label, options=options), profile.answers(), JOB)["answer"] == ""


def test_yes_and_no_in_the_forms_own_words():
    opts = ["I have a disability", "I have no disability", "Decline to answer"]
    assert classify.strict_pick("Yes", opts) == opts[0] and classify.strict_pick("No", opts) == opts[1]
    # a protected veteran is more than a veteran: your Yes doesn't say which
    assert classify.strict_pick("Yes", ["I am a protected veteran", "I am not a protected veteran"]) is None
    assert classify.strict_pick("Yes", ["I have a disability that requires accommodation", "I have no disability"]) is None
    assert classify.strict_pick("None", ["None (past)", "Secret", "Top Secret"]) is None
    assert classify.strict_pick("No", ["No disability", "Disability"]) == "No disability"
    assert classify.strict_pick("No", ["No, I have no disability", "Yes"]) == "No, I have no disability"
    assert classify.strict_pick("No", ["I have no disability and have never had one", "I have a disability"]) is None
    assert classify.strict_pick("No", ["I am not a protected veteran", "I am a protected veteran"]) == \
        "I am not a protected veteran"
    profile.set_answer("disability_status", "No", confirmed=True)
    got = draft.offline(field("Disability Status", options=["I have no disability and have never had one",
                                                           "I have a disability"]), profile.answers(), JOB)
    assert got["answer"] == "" and got["issues"]


@pytest.mark.parametrize("hispanic,confirmed,want", [("No", True, "Asian (Not Hispanic or Latino)"), ("No", False, ""),
                                                     ("Yes", True, ""), (None, False, "")])
def test_the_not_hispanic_race_choice_needs_that_confirmed_too(hispanic, confirmed, want):
    profile.set_answer("race", "Asian (Indian)", confirmed=True)
    if hispanic:
        profile.set_answer("hispanic_latino", hispanic, confirmed=confirmed)
    f = field("Race", options=["White (Not Hispanic or Latino)", "Asian (Not Hispanic or Latino)", "Hispanic or Latino"])
    assert draft.offline(f, profile.answers(), JOB)["answer"] == want


def test_a_company_name_with_dots_is_read_whole():
    company, _, own = draft._asked_company({"company": "Rocket Lab"},
                                           "Have you ever worked for the U.S. Government or Department of Defense?")
    assert company != "the U" and not own
    assert company == ""                                 # two employers in one: named as "them", never "the U"
    company, _, own = draft._asked_company({"company": "Rocket Lab"}, "Have you ever worked for the U.S. Government?")
    assert company == "the U.S. Government" and not own
    company, _, own = draft._asked_company({"company": "Acme Robotics"}, "Have you worked for Acme Robotics. If so, when?")
    assert company == "Acme Robotics" and own
    company, _, _ = draft._asked_company({"company": "Rocket Lab"}, "Have you worked for X. If yes, when?")
    assert company == "X"
    company, _, _ = draft._asked_company({"company": "Rocket Lab"}, "Have you ever worked for the u.s. Government?")
    assert company == "the u.s. Government"


# "Needs your AI connected" was shown when the AI was connected and only busy (Gemini 503s, a timeout).
WHY = {"field": "q_why", "label": "Why do you want to work here?", "qtype": "textarea", "required": True, "options": []}


async def test_a_busy_ai_is_waited_for_not_handed_to_you(monkeypatch):
    import httpx
    from jobsmith import db, llm

    async def send(self, req, *a, **k):
        return httpx.Response(503, json={"error": {"code": 503, "message": "The model is overloaded."}}, request=req)

    async def no_wait(s):
        return None
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    monkeypatch.setattr(llm.asyncio, "sleep", no_wait)
    monkeypatch.setattr(llm, "_busy_until", {})
    with pytest.raises(llm.BusyError, match="busy"):
        await llm.GeminiAPI("test-key-not-real").complete_json("sys", "prompt")
    llm.set_backend_override(llm.GeminiAPI("test-key-not-real"))
    jid = _greenhouse_job()
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    got, err = await draft.answer_fields(job, [dict(WHY)])
    assert got["q_why"]["kind"] == "pending" and "busy" in err          # the application waits for AI, not for you
    assert "busy" in (llm.out_of_ai() or "")                            # and autopilot doesn't hammer it meanwhile
    sent = []
    real_send = send

    async def counted(self, req, *a, **k):
        sent.append(req.url.host)
        return await real_send(self, req, *a, **k)
    monkeypatch.setattr(httpx.AsyncClient, "send", counted)
    with pytest.raises(llm.BusyError):                                  # asked again right away: nothing is sent
        await llm.complete_json("sys", "prompt")
    assert sent == []
    assert all(until > llm.time.time() for until, _ in llm._busy_until.values())
    monkeypatch.setattr(llm, "_busy_until", {k: (llm.time.time() - 1, "busy") for k in llm._busy_until})   # later
    with pytest.raises(llm.BusyError):
        await llm.complete_json("sys", "prompt")
    assert sent                                                         # it's asked again


async def test_an_ai_that_cant_be_used_says_why(fake_llm):
    from jobsmith import db, llm

    def refuse(s, p):
        raise llm.LLMError("That Gemini key isn't valid. Copy it again from aistudio.google.com/apikey.")
    fake_llm(refuse)
    jid = _greenhouse_job()
    got, _ = await draft.answer_fields(db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,))), [dict(WHY)])
    issue = got["q_why"]["issues"][0]
    assert "key isn't valid" in issue and "Needs your AI connected" not in issue
    llm.set_backend_override(None)                                      # no AI at all: that is what it says
    got, _ = await draft.answer_fields(db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,))), [dict(WHY)])
    assert "Needs your AI connected" in got["q_why"]["issues"][0]
    fields = [dict(WHY)]
    fake_llm(refuse)
    got, _ = await draft.answer_fields(db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,))), fields)
    draft.save_results(jid, fields, got)
    assert "key isn't valid" in draft.readiness(jid)["blockers"][0]     # Needs you says it too


# A careers site whose Apply button Jobsmith couldn't press (a guide's mask over the page), or that wants a sign-in
# first. Was: a 30-second timeout and "couldn't finish" with a browser's error for a reason.
@pytest.fixture
async def page():
    from playwright.async_api import async_playwright
    from jobsmith.fill import base
    async with async_playwright() as pw:
        exe = __import__("os").environ.get("JOBSMITH_CHROMIUM_PATH")
        b = await pw.chromium.launch(headless=True, args=base.browser_args(), **({"executable_path": exe} if exe else {}))
        p = await b.new_page()
        await p.route("http*://**", lambda r: r.abort())
        yield p
        await b.close()


def _apply_page(name: str) -> str:
    from conftest import FIXTURES
    return (FIXTURES / "apply_button" / name).resolve().as_uri()


async def test_a_covered_apply_button_is_handed_to_you_quickly_with_the_reason(page):
    import time
    from jobsmith.fill import base, generic
    t0 = time.time()
    with pytest.raises(base.NeedsYou, match="Apply button"):
        await generic.open_form(page, _apply_page("covered.html"))
    assert time.time() - t0 < 20
    assert not await page.evaluate("window.applied === true")


async def test_the_apply_button_is_the_one_that_says_just_that_and_a_sign_in_after_it_is_yours(page):
    from jobsmith.fill import base, generic
    with pytest.raises(base.NeedsYou, match="sign in"):
        await generic.open_form(page, _apply_page("menu_first.html"))
    assert page.url.endswith("sign_in.html")                     # it pressed "Apply to this job", not the menu
    assert await page.locator('input[type="password"]').input_value() == ""


def test_an_application_that_needs_you_first_says_why():
    from jobsmith import db, runner
    jid = _greenhouse_job()
    job = db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    runner._held_for_you(job, runner.Run(jid, "fill"), "asks you to sign in before it shows its application form")
    job = db.q1("SELECT status, hold_reason, error FROM jobs WHERE id=?", (jid,))
    assert "sign in" in job["hold_reason"] and "never signs in" in job["hold_reason"]
    assert job["status"] == "error" and "Timeout" not in job["error"]


def test_another_model_isnt_the_busy_one():
    from jobsmith import llm
    a, b = llm.GeminiAPI("test-key-not-real"), llm.GeminiAPI("test-key-not-real")
    b.model = a.model + "-other"
    assert llm._busy_key(a) != llm._busy_key(b)


async def test_a_second_apply_button_is_pressed_when_the_first_is_covered(page):
    from jobsmith.fill import generic
    await generic.open_form(page, _apply_page("second_works.html"))
    assert await page.evaluate("window.applied") == "second" and not await page.evaluate("window.menu === true")


async def test_a_menu_with_the_word_isnt_pressed_past_a_covered_apply_button(page):
    from jobsmith.fill import base, generic
    with pytest.raises(base.NeedsYou, match="Apply button"):
        await generic.open_form(page, _apply_page("only_menu_free.html"))
    assert not await page.evaluate("window.menu === true")


async def test_no_ai_is_spent_on_a_form_behind_your_sign_in(fake_llm, monkeypatch):
    from jobsmith import db, runner, sources
    from jobsmith.fill import base
    ai = fake_llm(lambda s, p: {"answers": []})
    jid = sources.add_job_url("https://careers.example.com/jobs/1", "Example", "Software Intern")

    async def scan(job, run):
        raise base.NeedsYou("asks you to sign in before it shows its application form")
    monkeypatch.setattr(runner, "do_scan", scan)
    db.x("UPDATE jobs SET description='Build software.' WHERE id=?", (jid,))
    await runner.prepare(jid)
    job = db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (jid,))
    assert "sign in" in job["hold_reason"] and ai.prompts == [] and draft.drafts_for(jid) == []


async def test_an_apply_online_link_opens_the_form_when_the_button_is_covered(page):
    from jobsmith.fill import generic
    fields = await generic.scan(page, _apply_page("link_opens_form.html"))
    assert [f["label"] for f in fields] == ["First name", "Email", "Why this role?"]


def test_a_timeout_is_a_busy_ai_but_no_connection_is_yours_to_see():
    import httpx
    from jobsmith import llm
    assert isinstance(llm._unreached("Gemini", httpx.ReadTimeout("slow")), llm.BusyError)
    for e in (httpx.ConnectError("refused"), httpx.ConnectTimeout("no route")):
        got = llm._unreached("Gemini", e)
        assert not isinstance(got, llm.BusyError) and "Couldn't reach Gemini" in str(got)


# Ashby's "select all that apply": every choice is a checkbox with a name of its own (name="Gay", name="Parent"), so
# each was read as a question, and "Other" in two questions as one. A sexual-orientation choice reached the AI queue.
def _dyna() -> str:
    from conftest import FIXTURES
    return (FIXTURES / "ashby_dyna_form.html").resolve().as_uri()


async def test_ashby_checkbox_choices_are_one_question_each_group(page):
    from jobsmith.fill import base
    await page.goto(_dyna())
    fields = await base.scan_form(page)
    labels = [f["label"] for f in fields]
    assert not {"Gay", "Parent", "Other", "White", "Veteran", "Diversity Survey"} & set(labels), labels
    groups = {f["label"]: f for f in fields if f["qtype"] == "multiselect"}
    assert len(groups) == 3 and len({f["field"] for f in groups.values()}) == 3
    orientation = next(f for l, f in groups.items() if "sexual orientation" in l)
    assert orientation["options"] == ["Bisexual", "Lesbian", "Gay", "Queer", "Heterosexual / straight", "Other",
                                      "I prefer not to answer"]
    communities = next(f for l, f in groups.items() if "communities" in l)
    assert await base.fill_field(page, communities["field"], "multiselect", "Parent")
    assert await page.evaluate("[...document.querySelectorAll('input[type=checkbox]:checked')].map(e => e.name)") == ["Parent"]
    # every question on this form's survey is yours (rule 2): none goes to AI, none is answered without your profile
    survey = [f for f in fields if f["qtype"] in ("radio", "multiselect")]
    assert len(survey) == 6
    for f in survey:
        got = draft.offline(dict(f, required=True), profile.answers(), JOB)
        assert got is not None and got["answer"] == "" and got["issues"], f["label"]


@pytest.mark.parametrize("label", ["Gay", "Heterosexual / straight", "Neurodiverse", "What is your current age?",
                                   "Diversity Survey"])
def test_a_choice_saved_as_a_question_before_this_fix_is_still_yours(label):
    got = draft.offline(field(label, "checkbox"), profile.answers(), JOB)
    assert got is not None and got["answer"] == ""


@pytest.mark.parametrize("choice", ["Asexual", "Straight"])
def test_orientation_choices_under_a_vague_label_are_yours(choice):
    got = draft.offline(field("Which best describes you?", options=[choice, "Other", "Prefer not to answer"]),
                        profile.answers(), JOB)
    assert got is not None and got["answer"] == ""


async def test_separate_consents_in_one_fieldset_stay_separate_questions(page):
    from jobsmith.fill import base
    await page.set_content("""<form><fieldset>
      <input type="checkbox" id="consent-privacy" name="privacy" required><label for="consent-privacy">I accept the privacy notice</label>
      <input type="checkbox" id="consent-news" name="news"><label for="consent-news">Send me the newsletter</label>
      </fieldset><fieldset><legend>Before you apply</legend>
      <input type="checkbox" id="agree-terms" name="terms" required><label for="agree-terms">I agree to the terms</label>
      <input type="checkbox" id="agree-data" name="data" aria-required="true"><label for="agree-data">I agree to data retention</label>
      </fieldset><input name="first_name" id="first_name"><label for="first_name">First name</label></form>""")
    fields = await base.scan_form(page)
    boxes = [f for f in fields if f["qtype"] in ("checkbox", "multiselect")]
    assert [f["qtype"] for f in boxes] == ["checkbox"] * 4 and [f["required"] for f in boxes] == [True, False, True, True]
    assert [f["label"] for f in boxes] == ["I accept the privacy notice", "Send me the newsletter",
                                           "Before you apply: I agree to the terms",
                                           "Before you apply: I agree to data retention"]
    assert len({f["field"] for f in boxes}) == 4


async def test_a_demographic_fieldset_that_cant_be_grouped_keeps_its_heading(page):
    from jobsmith.fill import base
    await page.set_content("""<form><fieldset><legend>Sexual orientation</legend>
      <input type="checkbox" id="a" name="straight"><label for="a">Straight</label>
      <input type="checkbox" id="b" name="other"><label for="b">Other</label></fieldset>
      <fieldset><legend>Agreements</legend>
      <input type="checkbox" id="terms-1" name="t1" aria-required="true"><label for="terms-1">I agree to the terms</label>
      <input type="checkbox" id="terms-2" name="t2"><label for="terms-2">Keep my data</label></fieldset></form>""")
    fields = await base.scan_form(page)
    assert [f["label"] for f in fields] == ["Sexual orientation: Straight", "Sexual orientation: Other",
                                            "Agreements: I agree to the terms", "Agreements: Keep my data"]
    for f in fields[:2]:
        got = draft.offline(f, profile.answers(), JOB)
        assert got is not None and got["answer"] == ""                 # still yours: never AI's (rule 2)
