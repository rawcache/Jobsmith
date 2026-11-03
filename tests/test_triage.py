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
    # Rule 2 as one rule: only your confirmed Yes or No to a plain Yes/No question. A pick from a list waits, even
    # one your profile answers ("Male") and even when you chose to decline them all.
    profile.set_answer("gender", "Male", confirmed=True)
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
    assert draft.offline(three, profile.answers(), JOB)["answer"] == ""         # not a plain Yes/No


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
