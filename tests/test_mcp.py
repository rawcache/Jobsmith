"""The MCP server: an agent reads open questions and writes answers that Jobsmith checks."""
import json

from jobsmith import db, draft, mcp_server, profile
from conftest import FIXTURES


async def test_agent_answers_open_questions_and_jobsmith_checks_them():
    await profile.ingest_document(FIXTURES / "sample_resume.tex")
    now = db.now()
    db.x("""INSERT INTO jobs(id, company, title, url, ats, description, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
         ("j1", "Acme Robotics", "Software Intern", "https://x/1", "greenhouse", "Robotics, Python.", "drafted", now, now))
    f = {"field": "why", "label": "Why Acme Robotics?", "qtype": "textarea", "required": True, "options": []}
    draft.save_results("j1", [f], {"why": {"kind": "generated", "answer": "", "confidence": 0, "issues": ["Needs your AI"]}})
    pending = json.loads(mcp_server.jobsmith_pending_questions())
    assert [q["field"] for q in pending["questions"]] == ["why"]
    fid = next(iter(profile.facts_by_id()))
    out = json.loads(mcp_server.jobsmith_save_answers("j1", [{"field": "why", "text": "I build robots and want to keep doing it at Acme.", "fact_ids": [fid]}]))
    assert out["saved"][0]["saved"] and not out["saved"][0]["issues"]
    d = draft.drafts_for("j1")[0]
    assert d["kind"] == "agent" and d["confidence"] > 0.8
    assert json.loads(mcp_server.jobsmith_pending_questions())["questions"] == []
    bad = json.loads(mcp_server.jobsmith_save_answers("j1", [{"field": "why", "text": "I am passionate about synergy and grew revenue 400%.", "fact_ids": []}]))
    assert bad["saved"][0]["issues"]                  # stock phrases and an unsupported number get caught
    prof = json.loads(mcp_server.jobsmith_profile())
    assert "facts" in prof and "phone" not in prof["answers"]       # contact details stay out of the agent


def test_an_agent_cant_answer_profile_questions():
    """Work authorization, "worked here before?" and other profile answers come only from the user (rule 2)."""
    now = db.now()
    db.x("""INSERT INTO jobs(id, company, title, url, ats, description, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
         ("j1", "Figma", "Intern", "https://x/1", "greenhouse", "", "drafted", now, now))
    fields = [{"field": f, "label": l, "qtype": "select", "required": True, "options": ["Yes", "No"]}
              for f, l in (("worked", "Have you ever worked for Figma before?"), ("auth", "Authorized to work in the US?"))]
    draft.save_results("j1", fields, {
        "worked": {"kind": "answer_bank", "canon": "previously_employed", "answer": "", "confidence": 0, "issues": ["x"]},
        "auth": {"kind": "answer_bank", "canon": "work_authorized_us", "answer": "", "confidence": 0, "issues": ["x"]}})
    out = json.loads(mcp_server.jobsmith_save_answers("j1", [{"field": "worked", "text": "No"},
                                                            {"field": "auth", "text": "Yes"}]))
    assert all("profile" in r["error"] for r in out["saved"])
    assert all(d["answer"] == "" and d["kind"] == "answer_bank" for d in draft.drafts_for("j1"))


# --------------------------------------------------------------------------- safe by default
# The user's agent can fill applications and add jobs, but a human submits (from the dashboard) and starts runs.

def _job(jid: str, fit: float = 90, status: str = "new") -> str:
    now = db.now()
    db.x("""INSERT INTO jobs(id, company, title, url, ats, description, status, fit_score, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)""", (jid, "Acme Robotics", "Software Intern", f"https://x/{jid}", "greenhouse",
                                             "Robotics, Python.", status, fit, now, now))
    return jid


def _through_the_engine(monkeypatch):
    """The MCP tools' requests go to the real engine routes in-process; runs are caught instead of started."""
    from fastapi.testclient import TestClient
    from jobsmith import runner
    from jobsmith.api import app
    c = TestClient(app)
    monkeypatch.setattr(mcp_server, "_post", lambda path, body: c.post(path, json=body).json())
    spawned = []

    def spawn(jid, label, coro):
        spawned.append((jid, label, coro))
        return True
    monkeypatch.setattr(runner, "spawn", spawn)
    return spawned


def _stub_the_browser(monkeypatch):
    from jobsmith import eligibility, runner
    filled = []

    async def prepare(jid, **kw):
        db.x("UPDATE jobs SET status='drafted' WHERE id=?", (jid,))

    async def fill(jid, submit=None, **kw):
        filled.append((jid, submit))
    monkeypatch.setattr(runner, "prepare", prepare)
    monkeypatch.setattr(runner, "fill", fill)
    monkeypatch.setattr(eligibility, "check", lambda job: {"ok": True, "reasons": [], "notes": []})
    return filled


async def test_apply_from_an_agent_fills_and_never_submits(monkeypatch, tmp_path):
    """Even with autopilot on and every site trusted, the agent's apply stops before Submit."""
    from conftest import resume_pdf, trust
    trust("greenhouse")
    resume_pdf(tmp_path)
    db.set_settings({"autonomy": "autopilot", "auto_run": True, "min_fit_score": 40})
    spawned = _through_the_engine(monkeypatch)
    filled = _stub_the_browser(monkeypatch)
    out = json.loads(mcp_server.jobsmith_apply([_job("j1")]))
    assert out["started"] == 1 and [s[:2] for s in spawned] == [("j1", "filling")]
    await spawned[0][2]
    assert filled == [("j1", False)]
    assert "submit" not in mcp_server.jobsmith_apply.__code__.co_varnames     # no way to ask for it


async def test_apply_from_an_agent_runs_every_check(monkeypatch, tmp_path):
    """The fit gate, eligibility, the caps and the resume check all run, as for a job autopilot picks itself."""
    from jobsmith import eligibility, guardrails
    db.set_settings({"min_fit_score": 40})
    spawned = _through_the_engine(monkeypatch)
    filled = _stub_the_browser(monkeypatch)

    async def run(*ids):
        json.loads(mcp_server.jobsmith_apply(list(ids)))
        for _, _, coro in spawned:
            await coro
        spawned.clear()

    await run(_job("no_resume"))                                               # resume check
    assert filled == [] and "resume" in db.q1("SELECT hold_reason FROM jobs WHERE id='no_resume'")["hold_reason"]
    resume_pdf_path = tmp_path / "r"
    resume_pdf_path.mkdir()
    from conftest import resume_pdf
    resume_pdf(resume_pdf_path)

    await run(_job("weak_fit", fit=10))                                        # fit gate
    assert filled == [] and "under your bar" in db.q1("SELECT hold_reason FROM jobs WHERE id='weak_fit'")["hold_reason"]

    monkeypatch.setattr(guardrails, "cap_reason", lambda job: "Daily cap reached: 5 of 5 sent today.")
    await run(_job("capped"))                                                  # caps
    assert filled == [] and "Daily cap" in db.q1("SELECT hold_reason FROM jobs WHERE id='capped'")["hold_reason"]
    monkeypatch.setattr(guardrails, "cap_reason", lambda job: None)

    monkeypatch.setattr(eligibility, "check", lambda job: {"ok": False, "reasons": ["Requires US citizenship"], "notes": []})
    await run(_job("ineligible"))                                              # eligibility
    row = db.q1("SELECT status, hold_reason FROM jobs WHERE id='ineligible'")
    assert filled == [] and row["status"] == "skipped" and "citizenship" in row["hold_reason"]


async def test_add_jobs_from_an_agent_never_starts_a_run(monkeypatch):
    from jobsmith import commands, jobdetail, runner
    db.set_settings({"autonomy": "autopilot", "auto_run": True, "min_fit_score": 0, "max_applications_per_day": 0})

    async def fetch(jid):
        return db.decode(db.q1("SELECT * FROM jobs WHERE id=?", (jid,)))
    monkeypatch.setattr(jobdetail, "fetch_job", fetch)
    spawned = _through_the_engine(monkeypatch)
    out = json.loads(mcp_server.jobsmith_add_jobs("Apply to https://jobs.example.com/acme/123 please"))
    assert out["started"] == [] and spawned == [] and out["found"] == 1 and len(out["job_ids"]) == 1
    assert db.q1("SELECT status FROM jobs WHERE id=?", (out["job_ids"][0],))["status"] in ("new", "fetched")
    # the same words from the terminal or dashboard still start one: only the agent's path is queue-only
    await commands.run("Apply to https://jobs.example.com/acme/456 please")
    assert len(spawned) == 1
    for *_, coro in spawned:
        coro.close()


def test_tracker_writes_nothing():
    tables = lambda: {r["name"] for r in db.q("SELECT name FROM sqlite_master")}  # noqa: E731
    before = tables()
    assert "outcomes" not in before
    _job("s1", status="submitted")
    out = json.loads(mcp_server.jobsmith_tracker())
    assert out["funnel"] == {"submitted": 1, "no_reply": 1} and tables() == before


def test_people_and_voice_examples_make_no_tables_on_first_run():
    """Before any LinkedIn import or writing sample there's nothing to find, and reading doesn't make the tables."""
    tables = lambda: {r["name"] for r in db.q("SELECT name FROM sqlite_master")}  # noqa: E731
    jid = _job("j1")
    before = tables()
    assert not {"connections", "voice_passages"} & before
    assert json.loads(mcp_server.jobsmith_people_at("Acme Robotics")) == []
    assert json.loads(mcp_server.jobsmith_voice_examples("Why Acme Robotics?", jid))["passages"] == []
    assert tables() == before


def test_people_and_voice_examples_still_find_what_was_added():
    from jobsmith import network
    from jobsmith.skills import voice
    network._ensure()
    db.x("INSERT INTO connections(first_name, last_name, company, company_norm) VALUES('Sam','Lee','Acme Robotics',?)",
         (network.norm_company("Acme Robotics"),))
    voice.add("I build small robots in my garage and write the Python that drives them. " * 4, "pasted", "Robots")
    assert [p["first_name"] for p in json.loads(mcp_server.jobsmith_people_at("Acme Robotics"))] == ["Sam"]
    assert json.loads(mcp_server.jobsmith_voice_examples("What robots have you built?"))["passages"]


async def test_every_tool_says_whether_it_changes_anything():
    tools = {t.name: t.annotations for t in await mcp_server.mcp.list_tools()}
    assert len(tools) == 14 and all(a is not None for a in tools.values())
    read_only = {n for n, a in tools.items() if a.read_only_hint}
    assert read_only == {"jobsmith_status", "jobsmith_profile", "jobsmith_find_jobs", "jobsmith_job",
                         "jobsmith_pending_questions", "jobsmith_tracker", "jobsmith_people_at", "jobsmith_voice_examples"}
    assert all(a.destructive_hint is not None for a in tools.values())
    assert tools["jobsmith_save_answers"].destructive_hint                    # replaces a draft answer
