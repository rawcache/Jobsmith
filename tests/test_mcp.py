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
