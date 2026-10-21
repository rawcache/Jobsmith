"""The voice skill: answers in your own words, with or without an AI."""
from jobsmith import db, draft
from jobsmith.skills import voice

ESSAY = """I led a team of four in my junior design class to build a warehouse robot that sorts packages by color.
When our motor controller kept overheating, I spent two nights reading datasheets and found we were driving it
at twice its rated current. We fixed it with a new driver board and finished a week early.

I want to work at Globex because their robotics team ships autonomy features to real customer sites, and I've
spent the last year building perception pipelines that I'd love to see running outside a lab. I'm happiest when
I can test my code on hardware the same day I write it.

Dear hiring manager,"""


def _job(company="Acme Robotics"):
    now = db.now()
    db.x("""INSERT INTO jobs(id, company, title, url, ats, description, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
         ("j1", company, "Robotics Software Intern", "https://x/1", "greenhouse", "Autonomy, perception, robotics, C++.", "new", now, now))
    db.x("""INSERT INTO jobs(id, company, title, url, ats, description, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
         ("j0", "Globex", "Intern", "https://x/0", "greenhouse", "", "submitted", now, now))
    return db.decode(db.q1("SELECT * FROM jobs WHERE id='j1'"))


def test_splits_and_finds_your_story():
    assert voice.add(ESSAY, "essay.md") == 2              # two passages; the salutation is dropped
    hits = voice.search("Tell us about a time you showed leadership")
    assert hits and hits[0]["text"].startswith("I led a team of four")
    cov = {c["key"]: c["have"] for c in voice.coverage()}
    assert cov["leadership"] and cov["why_company"] and not cov["conflict"]


def test_composes_in_your_words_for_the_right_company():
    voice.add(ESSAY, "essay.md")
    job = _job()
    r = voice.compose(job, {"field": "why", "label": "Why do you want to work at Acme Robotics?", "qtype": "textarea", "options": [], "description": ""})
    assert r and r["kind"] == "voice" and "Acme Robotics" in r["answer"] and "Globex" not in r["answer"]
    assert any("Globex" in i for i in r["issues"])        # tells you it adapted a past answer
    short = voice.compose(job, {"field": "w", "label": "Why us? (50 words max)", "qtype": "textarea", "options": [], "description": ""})
    assert len(short["answer"].split()) <= 50


def test_style_catches_answers_that_dont_sound_like_you():
    voice.add(ESSAY, "essay.md")
    st = voice.style()
    assert st["samples"] == 2 and st["contractions_per_100"] > 0 and "passionate about" in st["never_uses"]
    assert voice.style_issues("I am passionate about robotics and eager to contribute to a dynamic team.")
    assert not voice.style_issues("I built a robot that sorts packages, and I'd like to do that at your company.")
    assert "Never writes" in voice.style_notes()


async def test_drafting_falls_back_to_your_writing_without_an_ai():
    voice.add(ESSAY, "essay.md")
    job = _job()
    fields = [{"field": "q1", "label": "Tell us about a time you led a team.", "qtype": "textarea", "required": True, "options": []}]
    results, err = await draft.answer_fields(job, fields)          # tests run with no AI connected
    assert results["q1"]["kind"] == "voice" and results["q1"]["answer"].startswith("I led a team of four")


def test_prompt_carries_your_voice():
    voice.add(ESSAY, "essay.md")
    job = _job()
    p = draft.build_prompt(job, [{"field": "q", "label": "Why do you want to join us?", "qtype": "textarea", "required": False, "options": []}])
    assert "applicants_own_writing_on_this" in p and "THE APPLICANT'S VOICE" in p


def test_never_moves_a_true_story_to_another_company():
    """A story that happened at Globex stays at Globex: only 'why I want to join' passages are re-pointed."""
    voice.add("When our hackathon team at Globex disagreed about scope, I asked each person what they'd demo with one hour "
              "left and wrote the answers on the whiteboard. Two ideas overlapped, so we merged them, dropped the third, "
              "and won first place the next morning.", "essay.md")
    job = _job()
    r = voice.compose(job, {"field": "c", "label": "Tell us about a time you disagreed with a teammate.", "qtype": "textarea",
                            "options": [], "description": ""})
    assert r and "at Globex" in r["answer"] and "Acme Robotics" not in r["answer"]
    assert r["confidence"] < 0.6 and any("Globex" in i for i in r["issues"])   # held for you to check
