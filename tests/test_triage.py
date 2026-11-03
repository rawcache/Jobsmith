"""Fixes from triaging real held applications: each test is a question a real form asked, reworded only to drop
the company's name."""
import pytest

from jobsmith import classify, draft, profile

JOB = {"id": "j1", "company": "Acme Robotics", "title": "Software Engineer Intern", "location": "New York, NY"}


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


def test_unmapped_demographic_declined_only_when_you_declined_them_all():
    f = field("Do you identify as transgender?", options=["Yes", "No", "I don't wish to answer"])
    profile.set_answer("race", "Decline to self-identify", confirmed=True)   # one declined isn't all of them
    got = draft.offline(f, profile.answers(), JOB)
    assert got["answer"] == "" and got["issues"]
    for k in draft.VOLUNTARY:
        profile.set_answer(k, "Decline to self-identify", confirmed=True)
    assert draft.offline(f, profile.answers(), JOB)["answer"] == "I don't wish to answer"
    profile.set_answer("gender", "Woman", confirmed=True)       # answered one themselves: the rest isn't a guess
    got = draft.offline(f, profile.answers(), JOB)
    assert got["answer"] == "" and got["issues"]


@pytest.mark.parametrize("options", [["Woman", "Man", "Non-binary", "Decline to self-identify"],
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
    assert classify.canon_for(label) not in ("other_citizenship", "race")
    assert not draft._profile_only(field(label, "textarea"))


def test_yes_no_profile_facts_never_answer_a_different_question():
    profile.set_answer("work_authorized_us", "Yes", confirmed=True)
    profile.set_answer("us_citizen", "Yes", confirmed=True)
    for f in (field("What is your work authorization expiration date?", "text"),
              field("What type of work authorization do you have?", "text"),
              field("Do you require an export compliance license?", options=["Yes", "No"]),
              field("For export compliance, are you a national of any of the countries listed below?",
                    options=["Yes", "No"])):
        got = draft.offline(f, profile.answers(), JOB)
        assert got is not None and got["answer"] == "", f["label"]
    for label in ("Are you legally authorized to work in the United States?",
                  "Please confirm you are legally authorized to work in the United States.",
                  "* Are you legally authorized\nto work in the US?"):
        assert draft.offline(field(label, "text"), profile.answers(), JOB)["answer"] == "Yes", label
