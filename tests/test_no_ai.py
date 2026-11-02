"""Proof that autopilot works with no AI: the practice copy, made-up Alex Rivera, every AI provider blocked (Gemini,
Claude, OpenAI, a local smith, the Claude Code login), and autopilot run end to end on saved forms.

A form whose questions all come from the profile is filled and sent, with every answer traced to the profile. A form
with a written question is filled as far as the profile goes and held for Alex, with that question left empty:
nothing is made up to fill the gap. Both hold whether no AI is connected or every connected one is unreachable."""
import asyncio
import json
import subprocess

import httpx
import pytest

from conftest import FIXTURES, trust
from jobsmith import audit, config, db, draft, jobdetail, llm, profile, runner, sources
from test_extension import browser

AI_HOSTS = ("generativelanguage.googleapis.com", "api.anthropic.com", "api.openai.com", "127.0.0.1:11434",
            "localhost:11434")
ESSAY, OFFERS = "question_1004", "question_1005"
KEYS = {"anthropic_api": "anthropic_api_key", "openai_api": "openai_api_key", "gemini_api": "gemini_api_key"}
HOST = {"anthropic_api": "api.anthropic.com", "openai_api": "api.openai.com",
        "gemini_api": "generativelanguage.googleapis.com"}
CASES = ["none connected", *(f"unreachable: {k}" for k in KEYS)]
DEMO_RESUME = config.__file__.replace("config.py", "demo_data/resume.tex")


@pytest.fixture
def no_ai(monkeypatch, request):
    """The practice copy with every way to an AI shut: their hosts refuse, `claude` and `ollama` can't start, and
    (for "unreachable: <provider>") that provider's key is set and chosen, so Jobsmith tries it and is refused."""
    tried: list[str] = []
    monkeypatch.setattr(config, "DEMO", True)
    llm.set_backend_override(None)
    monkeypatch.setattr(llm, "_auto_cache", None)
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(llm, "find_claude", lambda *a, **k: None)
    monkeypatch.setattr(llm, "OLLAMA_URL", "http://127.0.0.1:11434")      # whatever OLLAMA_HOST says, it's blocked

    def refuse(url: str) -> None:
        if any(h in str(url) for h in AI_HOSTS):
            tried.append(str(url))
            raise httpx.ConnectError(f"blocked in this test: {url}")
    real_async, real_sync = httpx.AsyncClient.send, httpx.Client.send

    async def async_send(self, req, *a, **k):
        refuse(req.url)
        return await real_async(self, req, *a, **k)

    def sync_send(self, req, *a, **k):
        refuse(req.url)
        return real_sync(self, req, *a, **k)
    monkeypatch.setattr(httpx.AsyncClient, "send", async_send)
    monkeypatch.setattr(httpx.Client, "send", sync_send)
    real_exec, real_popen = asyncio.create_subprocess_exec, subprocess.Popen

    def no_ai_process(cmd):
        name = str(cmd[0] if isinstance(cmd, (list, tuple)) else cmd).split("/")[-1]
        if name in ("claude", "ollama"):
            tried.append(name)
            raise FileNotFoundError(name)

    async def exec_(*cmd, **k):
        no_ai_process(cmd)
        return await real_exec(*cmd, **k)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", exec_)
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, *a, **k: no_ai_process(cmd) or real_popen(cmd, *a, **k))
    settings = {"llm_backend": "auto", "research_backend": "same"}
    if request.param.startswith("unreachable"):
        kind = request.param.split(": ")[1]
        settings.update({KEYS[kind]: "test-key-not-real", "llm_backend": kind})
    db.set_settings(settings)
    return tried


async def _alex(tmp_path) -> None:
    """The practice copy's made-up applicant, with the answers only Alex can confirm, confirmed."""
    await profile.ingest_document(DEMO_RESUME)
    for k, v in {"first_name": "Alex", "last_name": "Rivera", "email": "alex.rivera@example.com",
                 "phone": "617-555-0123", "country": "United States", "needs_sponsorship": "No",
                 "work_authorized_us": "Yes"}.items():
        profile.set_answer(k, v, confirmed=True)
    profile.set_answer("enrollment_start", "Aug 2023", confirmed=True)
    for k, a in profile.answers().items():          # Alex looked over what was read from the resume and confirmed it
        if a.get("value") and not a.get("confirmed"):
            profile.set_answer(k, a["value"], confirmed=True)
    pdf = tmp_path / "Alex_Rivera_resume.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    db.x("INSERT INTO documents(kind, filename, path, text, is_primary, created_at) VALUES('resume',?,?,'',1,?)",
         (pdf.name, str(pdf), db.now()))


def _job(tmp_path, name: str, essay: bool = False, letter: bool = False) -> str:
    """The saved Greenhouse-style form as a job. Without `essay`, its written question and its offers question (which
    only Alex can answer) are taken out; without `letter`, its optional cover letter box, which only an AI or Alex
    could write. With neither, the profile answers the whole form."""
    page = (FIXTURES / "mock_greenhouse.html").read_text(encoding="utf-8")
    data = json.loads((FIXTURES / "greenhouse_job.json").read_text(encoding="utf-8"))
    gone = ([] if essay else [ESSAY, OFFERS, "Do you have any outstanding offers?"]) + ([] if letter else ["cover_letter"])
    page = "\n".join(line for line in page.split("\n") if not any(g in line for g in gone))
    data["questions"] = [q for q in data["questions"] if not any(f["name"] in gone for f in q["fields"])]
    form = tmp_path / f"{name}.html"
    form.write_text(page, encoding="utf-8")
    jid = sources.add_job_url(f"https://job-boards.greenhouse.io/acme/jobs/{name}", "Acme Robotics", f"SWE Intern {name}")
    db.x("UPDATE jobs SET url=?, description='Robotics software internship.', questions=?, fit_score=90 WHERE id=?",
         (form.resolve().as_uri(), db.enc(jobdetail.normalize_greenhouse(data)), jid))
    return jid


@browser
@pytest.mark.parametrize("no_ai", CASES, indirect=True)
async def test_the_practice_copys_autopilot_runs_end_to_end_with_every_ai_blocked(no_ai, tmp_path, monkeypatch, request):
    no_ai_kind = request.node.callspec.params["no_ai"]
    await _alex(tmp_path)
    plain, letter = _job(tmp_path, "plain"), _job(tmp_path, "letter", letter=True)
    written = _job(tmp_path, "written", essay=True, letter=True)
    held_pages, real_watch = {}, runner.watch_tab

    async def watch(job_id, page, *a):            # a held form stays open for Alex; here it's looked at, then closed
        if (runner.LIVE.get(job_id) or {}).get("phase") == "submitting":
            return await real_watch(job_id, page, *a)    # autopilot pressed Submit: the thank-you page is the proof
        held_pages[job_id] = page
    monkeypatch.setattr(runner, "watch_tab", watch)
    monkeypatch.setattr(runner, "_slots", runner._Slots())          # locks belong to this test's event loop
    monkeypatch.setattr(runner.browser, "_lock", asyncio.Lock())
    trust("greenhouse")
    db.set_settings({"browser_channel": "", "headless": True, "autonomy": "autonomous", "trust_threshold": 0,
                     "fit_threshold": 0})
    try:
        await asyncio.wait_for(runner.autopilot([plain, letter, written]), 120)
        page = held_pages.get(written) or runner.LIVE[written]["page"]
        assert await page.input_value("#first_name") == "Alex"           # filled as far as the profile goes
        assert await page.input_value(f"#{ESSAY}") == ""                 # the written question left for Alex
        assert await page.evaluate("document.title") != "Thanks"
    finally:
        await runner.browser.close()

    # the form the profile answers whole: sent by autopilot, every answer from the profile or resume, whether no AI
    # is connected or the connected one can't be reached
    runs = db.q("SELECT kind, status, log FROM runs WHERE job_id=? ORDER BY id", (plain,))
    assert db.q1("SELECT status FROM jobs WHERE id=?", (plain,))["status"] == "submitted", runs
    [sub] = audit.for_job(plain)
    assert sub["sent_by"] == "autopilot" and sub["confirmations"]
    sent = {f["label"]: f for f in sub["fields"]}
    assert sent["First Name"]["answer"] == "Alex" and sent["Email"]["answer"] == "alex.rivera@example.com"
    assert sub["untraced"] == 0 and {f["source"] for f in sub["fields"] if f["answer"]} <= {"profile", "resume", "file"}, sub
    assert not [d for d in draft.drafts_for(plain) if d["kind"] in ("generated", "agent") and draft.final_value(d)]

    # the same form with an optional cover letter box, and no saved cover letter: the box is left blank (an optional
    # essay never holds an application) and the rest goes, all from the profile
    [sent_letter] = audit.for_job(letter)
    assert sent_letter["sent_by"] == "autopilot" and sent_letter["untraced"] == 0
    box = next(d for d in draft.drafts_for(letter) if "cover" in d["field"].lower())
    assert box["kind"] == "left_blank" and not draft.final_value(box)

    # what it tried: with "auto" and nothing connected, only a look for a local smith (refused); otherwise the one
    # AI that's connected (refused)
    asked = {u.split("/")[2] if "//" in u else u for u in no_ai}
    if no_ai_kind == "none connected":
        assert asked <= {"127.0.0.1:11434"}, no_ai
    else:
        assert asked == {HOST[no_ai_kind.split(": ")[1]]}, no_ai                 # it really tried, and was refused

    # the form with a written question: held for Alex, the question left empty, nothing sent
    job = db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (written,))
    assert job["status"] != "submitted" and not audit.for_job(written), job
    essay = next(d for d in draft.drafts_for(written) if d["field"] == ESSAY)
    assert not (essay.get("final_answer") or essay.get("answer"))
    assert not draft.readiness(written)["ready"]
    assert any("Acme Robotics" in b or "Why" in b for b in draft.readiness(written)["blockers"])


@pytest.mark.parametrize("make", [lambda: llm.AnthropicAPI("sk-ant-test"), lambda: llm.OpenAIAPI("sk-test"),
                                  lambda: llm.GeminiAPI("AIza-test")])
async def test_an_unreachable_ai_is_an_ai_error_so_the_profiles_answers_still_go_in(make, monkeypatch):
    """Offline, or the provider refuses: an LLMError like a bad key, which drafting turns into "needs you", never an
    error that stops the whole application."""
    async def refused(self, req, *a, **k):
        raise httpx.ConnectError("refused", request=req)
    monkeypatch.setattr(httpx.AsyncClient, "send", refused)
    with pytest.raises(llm.LLMError, match="reach"):
        await make().complete_json("system", "prompt")
