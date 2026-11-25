"""Needs you shows real questions only, and holds that no longer apply can be retried in one click.

A "select all that apply" read as a box per option ("Which offices…?: New York", "…: Boston") is one question,
answered with the set you tick. Demographic and work-authorization boxes stay profile-only (rule 2). "Retry held
applications" runs again only the holds that went stale (your AI is connected now, or an earlier version held
them), within your limits, and never sends. `jobsmith doctor` says whether the engine can start and what its last
error means. All made-up data (Acme, Globex, Initech, Hooli); no network."""
import pytest

from conftest import resume_pdf
from jobsmith import db, draft, fixes, frontdoor, needs, retry, runner
from test_fixes import FIRST, _alex, _held, _job

OFFICES = ["New York", "San Francisco", "Boston"]
ASK = "Which offices could you work from?"


def _offices(required: bool = False) -> list[dict]:
    return [{"field": f"#office_{i}", "label": f"{ASK}: {name}", "qtype": "checkbox", "required": required,
             "options": []} for i, name in enumerate(OFFICES)]


# --------------------------------------------------------------------------- part A: one question, its options
async def test_options_of_one_checkbox_question_are_one_item_with_every_option(fake_llm, tmp_path):
    _alex()
    resume_pdf(tmp_path)
    fake_llm(lambda s, p: {"answers": []})
    jid = await _held("Acme", *_offices())
    qs = [f for f in fixes.compute()["fixes"] if f["kind"] == "question"]
    assert len(qs) == 1
    assert qs[0]["title"] == f"Answer “{ASK}”" and qs[0]["choices"] == OFFICES and qs[0]["multi"]
    assert qs[0]["jobs"] == [jid]
    texts = [i["text"] for i in needs.items()]
    assert texts.count(f"Answer “{ASK}”") == 1
    assert not any(name in t for t in texts for name in OFFICES)              # never "Answer “…: New York”"


async def test_the_same_question_on_two_forms_is_one_item_for_both(fake_llm, tmp_path):
    _alex()
    resume_pdf(tmp_path)
    fake_llm(lambda s, p: {"answers": []})
    a, b = await _held("Acme", *_offices()), await _held("Globex", *_offices())
    qs = [f for f in fixes.compute()["fixes"] if f["kind"] == "question"]
    assert len(qs) == 1 and sorted(qs[0]["jobs"]) == sorted([a, b]) and qs[0]["part"] == "you"


async def test_saving_a_selection_ticks_those_boxes_and_leaves_the_rest_unticked(fake_llm, tmp_path, monkeypatch):
    _alex()
    resume_pdf(tmp_path)
    fake_llm(lambda s, p: {"answers": []})
    monkeypatch.setattr(runner, "applies_on_own", lambda: False)
    jid = await _held("Acme", *_offices())
    fx = next(f for f in fixes.compute()["fixes"] if f["kind"] == "question")
    res = fixes.answer(fx["id"], values=["New York", "Boston"])
    got = {d["label"].split(": ")[-1]: (d["final_answer"], d["verdict"]) for d in draft.drafts_for(jid)
           if d["field"].startswith("#office_")}
    assert got == {"New York": ("Yes", "green"), "San Francisco": ("No", "green"), "Boston": ("Yes", "green")}
    assert res["freed"] == [jid] and not any(f["kind"] == "question" for f in res["fixes"])


async def test_a_selection_through_the_dashboard_and_its_checks(fake_llm, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from jobsmith.api import app
    _alex()
    resume_pdf(tmp_path)
    fake_llm(lambda s, p: {"answers": []})
    monkeypatch.setattr(runner, "applies_on_own", lambda: False)
    jid = await _held("Acme", *_offices(required=True))
    fx = next(f for f in fixes.compute()["fixes"] if f["kind"] == "question")
    c = TestClient(app)
    assert c.post("/api/fixes/answer", json={"id": fx["id"], "values": ["Paris"]}).status_code == 400
    r = c.post("/api/fixes/answer", json={"id": fx["id"], "values": []})        # required: at least one
    assert r.status_code == 400 and "at least one" in r.json()["detail"]
    r = c.post("/api/fixes/answer", json={"id": fx["id"], "values": ["San Francisco"]})
    assert r.status_code == 200 and r.json()["freed"] == [jid]
    assert {d["final_answer"] for d in draft.drafts_for(jid) if d["field"].startswith("#office_")} == {"Yes", "No"}


async def test_a_checkbox_list_saves_every_ticked_option_as_one_answer(fake_llm, tmp_path, monkeypatch):
    _alex()
    resume_pdf(tmp_path)
    fake_llm(lambda s, p: {"answers": []})
    monkeypatch.setattr(runner, "applies_on_own", lambda: False)
    clubs = {"field": "q_clubs", "label": "Which clubs were you part of?", "qtype": "multiselect", "required": True,
             "options": ["Robotics", "Chess", "Debate"]}
    jid = await _held("Initech", clubs)
    fx = next(f for f in fixes.compute()["fixes"] if f["kind"] == "question")
    assert fx["multi"] and fx["choices"] == clubs["options"]
    fixes.answer(fx["id"], "Robotics; Debate")                                 # typed as a list (the terminal)
    d = next(d for d in draft.drafts_for(jid) if d["field"] == "q_clubs")
    assert d["final_answer"] == "Robotics; Debate" and d["verdict"] == "green"


@pytest.mark.parametrize("ask,options", [
    ("Race/Ethnicity (select all that apply)", ["Asian", "Black or African American", "White"]),
    ("Gender identity", ["Woman", "Man", "Non-binary"]),
    ("Work authorization", ["US citizen", "Green card holder", "Need sponsorship"]),
])
async def test_demographic_and_work_authorization_boxes_are_never_grouped_into_a_question(fake_llm, tmp_path, ask,
                                                                                          options):
    """Rule 2: these come only from your confirmed profile. Never offered as a question to tick here, and never
    written by AI."""
    _alex()
    resume_pdf(tmp_path)
    asked = []
    fake_llm(lambda s, p: asked.append(p) or {"answers": []})
    boxes = [{"field": f"#d_{i}", "label": f"{ask}: {o}", "qtype": "checkbox", "required": False, "options": []}
             for i, o in enumerate(options)]
    jid = await _held("Hooli", *boxes)
    assert fixes._checkbox_groups(jid) == {}
    assert not any(f.get("multi") or f["key"] == ask for f in fixes.compute()["fixes"])
    with pytest.raises(ValueError):
        fixes.answer(fixes.question_id(ask, options), values=options[:1])
    assert not any(d["answer"] for d in draft.drafts_for(jid) if d["field"].startswith("#d_"))
    assert not any(o in p for p in asked for o in options)


# --------------------------------------------------------------------------- part B: retry stale holds
def _hold(company: str, reason: str, *drafts: dict, status: str = "filled") -> str:
    jid = _job(company, FIRST)
    db.x("UPDATE jobs SET status=?, hold_reason=?, updated_at=? WHERE id=?", (status, reason, db.now(), jid))
    for d in drafts:
        db.x("""INSERT INTO drafts(job_id, field, label, qtype, required, options, kind, answer, issues, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (jid, d["field"], d["label"], d.get("qtype", "textarea"),
                                                 int(d.get("required", True)), "[]", d["kind"], "",
                                                 db.enc(d.get("issues", [])), db.now()))
    return jid


WAITS_FOR_AI = {"field": "q_why", "label": "Why this team?", "kind": "pending"}
NO_AI = {"field": "q_why", "label": "Why this team?", "kind": "generated",
         "issues": ["Needs your AI connected (Settings), or more of your writing (Voice), then Redraft"]}
YOURS = {"field": "q_pay", "label": "Expected salary", "kind": "answer_bank", "qtype": "text",
         "issues": ["required and empty"]}


@pytest.fixture
def spawned(monkeypatch):
    """What a retry starts, without starting it: every call to autopilot, with its arguments."""
    calls = []

    def autopilot(ids, **kw):
        calls.append((ids, kw))
        return None

    def spawn(jid, label, coro):
        return True
    monkeypatch.setattr(runner, "autopilot", autopilot)
    monkeypatch.setattr(runner, "spawn", spawn)
    return calls


def test_retry_runs_only_stale_holds_never_sends_and_shows_its_count_first(tmp_path, spawned):
    _alex()
    resume_pdf(tmp_path)
    db.set_settings({"autonomy": "autopilot", "max_applications_per_day": 10})
    since = retry.version_since()
    ai = _hold("Acme", "Waiting for AI", WAITS_FOR_AI)
    ai2 = _hold("Globex", "Needs your AI", NO_AI)
    yours = _hold("Initech", "Expected salary: required and empty", YOURS)
    stopped = _hold("Hooli", "Stopped by you")
    signin = _hold("Umbrella", "Greenhouse asks you to sign in. Jobsmith never signs in for you", status="error")
    old = _hold("Soylent", "Something went wrong on the site", status="error")
    new = _hold("Wonka", "Something went wrong on the site", status="error")
    db.x("UPDATE jobs SET updated_at=? WHERE id IN (?, ?)", (since - 100, old, signin))
    sent = _hold("Tyrell", "Waiting for AI", WAITS_FOR_AI)
    db.x("INSERT INTO runs(job_id, kind, status) VALUES(?, 'submit', 'unconfirmed')", (sent,))

    assert {r["id"] for r in retry.stale(ai_connected=False)} == {old}
    plan = retry.plan(ai_connected=True)
    assert {r["id"] for r in plan["jobs"]} == {ai, ai2, old} and plan["count"] == 3
    before = {r["id"]: r["status"] for r in db.q("SELECT id, status FROM jobs")}
    assert before[ai] == "filled"                                             # the count is read-only

    res = retry.run(ai_connected=True)
    assert sorted(res["started"]) == sorted([ai, ai2, old])
    assert all(kw == {"submit": False, "every_check": True} for _, kw in spawned)   # every check, never a send
    after = {r["id"]: r for r in db.q("SELECT id, status, hold_reason FROM jobs")}
    for jid in (yours, stopped, signin, new, sent):
        assert after[jid]["status"] == before[jid]                           # untouched
    assert after[ai]["status"] == "drafted" and after[ai]["hold_reason"] is None
    assert db.q("SELECT job_id FROM runs WHERE kind='submit'") == [{"job_id": sent}]   # nothing new was sent


def test_retry_keeps_within_your_daily_limit_and_needs_your_resume(tmp_path, spawned):
    _alex()
    db.set_settings({"autonomy": "autopilot", "max_applications_per_day": 1})
    retry.version_since()
    a, b = _hold("Acme", "Waiting for AI", WAITS_FOR_AI), _hold("Globex", "Waiting for AI", WAITS_FOR_AI)
    p = retry.plan(ai_connected=True)
    assert p["count"] == 0 and p["stale"] == 2 and "resume" in p["note"]      # no resume PDF: none start
    assert retry.run(ai_connected=True)["started"] == [] and not spawned
    resume_pdf(tmp_path)
    p = retry.plan(ai_connected=True)
    assert p["count"] == 1 and p["waiting"] == 1 and "limits" in p["note"]
    res = retry.run(ai_connected=True)
    assert len(res["started"]) == 1 and len(spawned) == 1
    left = ({a, b} - set(res["started"])).pop()
    assert db.q1("SELECT status FROM jobs WHERE id=?", (left,))["status"] == "filled"


def test_a_new_version_makes_older_holds_retryable():
    first = retry.version_since()
    assert retry.version_since() == first
    db.x("UPDATE settings SET value=? WHERE key=?", (db.enc({"version": "0.0.1", "since": 1.0}), retry.SEEN))
    assert retry.version_since() >= first


# --------------------------------------------------------------------------- part C: doctor
def test_doctor_says_in_plain_words_when_the_engine_cant_start(tmp_path, monkeypatch, capsys):
    from jobsmith import cli
    log = tmp_path / "server.log"
    log.write_text("INFO: started\nTraceback (most recent call last):\n  File \"/opt/app/server.py\", line 9\n"
                   "OSError: [Errno 48] error while attempting to bind on address ('127.0.0.1', 8765): "
                   "address already in use\n")
    monkeypatch.setattr(frontdoor, "_log_path", lambda: log)
    monkeypatch.setattr(frontdoor, "engine_up", lambda base=None: False)
    monkeypatch.setattr(frontdoor, "_port_taken", lambda base: True)
    assert cli.doctor_engine() is False
    out = capsys.readouterr().out
    assert "Engine: NOT READY - can't start: another program is using port" in out
    assert "Last engine error: Another program was using the engine's port" in out
    assert "/opt/app" not in out


def test_doctor_reports_a_free_port_a_running_engine_and_other_errors(tmp_path, monkeypatch):
    log = tmp_path / "server.log"
    monkeypatch.setattr(frontdoor, "_log_path", lambda: log)
    monkeypatch.setattr(frontdoor, "engine_up", lambda base=None: False)
    monkeypatch.setattr(frontdoor, "_port_taken", lambda base: False)
    assert frontdoor.engine_check()[0] and "free" in frontdoor.engine_check()[1]
    monkeypatch.setattr(frontdoor, "engine_up", lambda base=None: True)
    port = frontdoor._port(frontdoor.base_url())
    assert frontdoor.engine_check() == (True, f"running, answering on port {port}")
    assert frontdoor.last_error() is None                                     # no log yet
    log.write_text("ModuleNotFoundError: No module named 'textual'\n")
    assert frontdoor.last_error()[0].startswith("A part of Jobsmith is missing (textual)")
    log.write_text("ValueError: bad row in /tmp/data/jobs.db\nINFO: fine again\n")
    assert frontdoor.last_error()[0] == "The engine stopped on an error it didn't expect (ValueError: bad row in jobs.db)."
