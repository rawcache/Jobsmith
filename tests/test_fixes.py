"""What your first real run showed (Nov 2026), fixed: AI spent on applications that were held anyway, every call
not logged, one quota message per application; Needs you listed by application instead of by what to do; essays
only AI could write; and a missing resume PDF as a note instead of the first thing to fix.

All made-up data (Acme, Globex, Initech); no network: AI is a fake, and Gemini's address is refused."""
import httpx
import pytest

from conftest import resume_pdf
from jobsmith import commands, db, draft, essays, fixes, llm, profile, scheduler, sources

WORK_AUTH = {"field": "q_auth", "label": "Are you legally authorized to work in the United States?", "qtype": "select",
             "required": True, "options": ["Yes", "No"]}
WHY_US = {"field": "q_why", "label": "Why do you want to work at {co}?", "qtype": "textarea", "required": True,
          "options": []}
EXTRA = {"field": "q_extra", "label": "Additional information", "qtype": "textarea", "required": False, "options": []}
OFFICE = {"field": "q_office", "label": "Are you able to come in 5 days a week?", "qtype": "select", "required": True,
          "options": ["Yes", "No"]}
FIRST = {"field": "first_name", "label": "First Name", "qtype": "text", "required": True, "options": []}


def _job(company: str, *fields: dict, title: str = "Software Intern") -> str:
    jid = sources.add_job_url(f"https://job-boards.greenhouse.io/{company.lower()}/jobs/1", company, title)
    qs = [dict(f, label=f["label"].replace("{co}", company)) for f in fields]
    db.x("UPDATE jobs SET questions=?, description='Build software.', fit_score=90 WHERE id=?", (db.enc(qs), jid))
    return jid


def _alex(work_auth: bool = True) -> None:
    for k, v in {"first_name": "Alex", "last_name": "Rivera", "email": "alex.rivera@example.com"}.items():
        profile.set_answer(k, v, confirmed=True)
    if work_auth:
        profile.set_answer("work_authorized_us", "Yes", confirmed=True)


# --------------------------------------------------------------------------- every AI call, logged
async def test_every_ai_call_is_logged_with_its_reason_application_and_tokens_even_a_failed_one(fake_llm):
    jid = _job("Acme", FIRST)
    fake_llm(lambda s, p: {"ok": True})
    with llm.usage_for(jid, "research"):
        await llm.complete_json("sys", "prompt", web=True)

    class Refused(llm.Backend):
        name = "fake"

        async def complete_json(self, *a, **k):            # fails before any tokens are counted
            raise llm.LLMError("Gemini API 500: try again")
    llm.set_backend_override(Refused())
    with llm.usage_for(jid, "answers"), pytest.raises(llm.LLMError):
        await llm.complete_json("sys", "prompt")
    rows = db.q("SELECT job_id, purpose, input_tokens, output_tokens, ok, error FROM usage ORDER BY id")
    assert rows[0] == {"job_id": jid, "purpose": "research", "input_tokens": 1000, "output_tokens": 200, "ok": 1,
                       "error": None}
    assert rows[1]["job_id"] == jid and rows[1]["purpose"] == "answers" and rows[1]["ok"] == 0
    assert rows[1]["error"] == "Gemini API 500: try again" and rows[1]["input_tokens"] == 0   # not the last call's


async def test_the_daily_ai_budget_stops_calls_and_a_batch_started_at_once_cant_overshoot(fake_llm):
    db.set_settings({"ai_daily_budget": 2})
    fake_llm(lambda s, p: {"ok": True})
    import asyncio
    got = await asyncio.gather(*(llm.complete_json("sys", f"p{i}") for i in range(5)), return_exceptions=True)
    assert sum(1 for g in got if g == {"ok": True}) == 2
    assert all(isinstance(g, llm.BudgetError) for g in got if g != {"ok": True})
    assert db.q1("SELECT COUNT(*) n FROM usage")["n"] == 2                     # refused ones were never calls
    today = llm.ai_today()
    assert today["calls"] == 2 and today["budget"] == 2 and "budget is used" in today["out"]


def test_gemini_gets_a_budget_well_under_its_free_tier_by_default_and_others_none():
    db.set_settings({"llm_backend": "gemini_api", "ai_daily_budget": None})
    assert llm.ai_budget() == llm.GEMINI_FREE_BUDGET == 15
    db.set_settings({"llm_backend": "anthropic_api"})
    assert llm.ai_budget() is None
    db.set_settings({"ai_daily_budget": 40})
    assert llm.ai_budget() == 40
    db.set_settings({"ai_daily_budget": 0})
    assert llm.ai_budget() is None                                           # 0: no limit


async def test_gemini_out_for_the_day_is_never_asked_again_and_its_check_spends_nothing(monkeypatch):
    """Once Gemini's free day is used up, no request goes to it until midnight Pacific. Checking the connection asks
    about the model (GET), never for an answer (POST): the old check spent a request every 10 minutes."""
    sent = []

    async def send(self, req, *a, **k):
        sent.append((req.method, str(req.url)))
        return httpx.Response(200, json={"name": "models/gemini-flash-latest"}, request=req)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    g = llm.GeminiAPI("test-key-not-real")
    assert (await g.available())[0] and sent == [("GET", "https://generativelanguage.googleapis.com/v1beta/models/"
                                                          "gemini-flash-latest")]
    monkeypatch.setitem(llm._quota_hit, "gemini_api", llm.gemini_reset())
    monkeypatch.setitem(llm._quota_daily, "gemini_api", True)
    with pytest.raises(llm.QuotaError, match="daily limit is used up"):
        await g.complete_json("sys", "prompt")
    assert len(sent) == 1


async def test_a_per_minute_limit_is_a_minute_not_the_day(monkeypatch):
    async def send(self, req, *a, **k):
        return httpx.Response(429, json={"error": {"details": [{"quotaId": "GenerateRequestsPerMinutePerProject"}]}},
                              request=req)

    async def no_wait(s):
        return None
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    monkeypatch.setattr(llm.asyncio, "sleep", no_wait)
    monkeypatch.setattr(llm, "_quota_hit", {})
    with pytest.raises(llm.QuotaError, match="per-minute"):
        await llm.GeminiAPI("test-key-not-real").complete_json("sys", "prompt")
    assert llm._quota_hit["gemini_api"] < llm.time.time() + 61


# --------------------------------------------------------------------------- no AI on what's held anyway
async def test_autopilot_spends_no_ai_on_an_application_held_for_a_missing_profile_fact(fake_llm, tmp_path):
    _alex(work_auth=False)
    resume_pdf(tmp_path)
    db.set_settings({"research_enabled": True, "autonomy": "autopilot"})
    jid = _job("Acme", FIRST, WORK_AUTH, WHY_US)
    ai = fake_llm(lambda s, p: {"answers": []})
    res = await draft.draft_job(jid, hold_first=True)
    assert res["held"] and ai.prompts == []                                    # no research, no answers
    job = db.q1("SELECT status, hold_reason, research FROM jobs WHERE id=?", (jid,))
    assert job["status"] == "filled" and "Are you legally authorized" in job["hold_reason"]
    assert job["research"] in ("{}", "", None)
    why = next(d for d in draft.drafts_for(jid) if d["field"] == "q_why")
    assert why["kind"] == "pending"                                            # written once the rest is answered


async def test_autopilot_spends_no_ai_on_a_role_you_may_not_qualify_for(fake_llm, tmp_path):
    """The posting requires US citizenship and you said you're not a citizen: autopilot skips it, as before, but
    now decides that before any research or writing."""
    from jobsmith import runner
    _alex()
    profile.set_answer("us_citizen", "No", confirmed=True)
    resume_pdf(tmp_path)
    db.set_settings({"research_enabled": True, "autonomy": "autopilot"})
    jid = _job("Acme", FIRST, WHY_US)
    db.x("UPDATE jobs SET description='US citizenship is required for this role.' WHERE id=?", (jid,))
    ai = fake_llm(lambda s, p: {"answers": []})
    await runner.autopilot([jid])
    assert ai.prompts == []
    job = db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (jid,))
    assert job["status"] == "skipped" and "Requires US citizenship" in job["hold_reason"]


async def test_no_research_when_nothing_needs_writing(fake_llm):
    _alex()
    db.set_settings({"research_enabled": True})
    jid = _job("Acme", FIRST, WORK_AUTH, EXTRA)
    ai = fake_llm(lambda s, p: {"answers": []})
    await draft.draft_job(jid, hold_first=True)
    assert ai.prompts == [] and draft.readiness(jid)["ready"]


async def test_out_of_ai_an_application_waits_quietly_instead_of_being_held(fake_llm, tmp_path):
    """A free limit or the day's budget running out isn't something you can fix: the application stays where it
    is (not under Needs you), and is written when there's room."""
    _alex()
    db.set_settings({"ai_daily_budget": 1})
    db.x("""INSERT INTO usage(job_id, purpose, backend, model, at) VALUES(NULL, 'answers', 'fake', '', ?)""",
         (db.now(),))
    jid = _job("Acme", FIRST, WORK_AUTH, WHY_US)
    fake_llm(lambda s, p: {"answers": []})
    await draft.draft_job(jid, hold_first=True)
    assert db.q1("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "drafted"
    r = draft.readiness(jid)
    assert r["only_ai"] and not r["ready"]
    assert fixes.compute()["held"] == 0


# --------------------------------------------------------------------------- your saved essay answers
def test_questions_are_sorted_into_the_kinds_you_save_answers_for():
    k = lambda label, co="Acme": essays.kind_of(label, co)
    assert k("Why do you want to work at Acme?") == k("Why Acme?") == k("Why are you interested in Acme and this role?") \
        == "why_company"
    assert k("Why do you want to join us?") == "why_company"
    assert k("Why this role?") == k("Why are you interested in this position?") == "why_role"
    assert k("Additional information") == k("Is there anything else you'd like us to know?") == "additional_info"
    assert k("Cover letter") == "cover_letter"
    assert k("Describe a project you're proud of") is None and k("How did you hear about us?") is None


async def test_your_saved_answer_goes_in_as_written_with_company_and_role_filled_in(fake_llm):
    _alex()
    text = "I want to build tools at {company} as a {role}.  Plain words, mine."
    essays.save("why_company", text)
    assert essays.saved()["why_company"] == text                                # kept exactly, spaces too
    jid = _job("Acme", FIRST, WORK_AUTH, WHY_US, title="Robotics Intern")
    ai = fake_llm(lambda s, p: {"answers": []})
    await draft.draft_job(jid, hold_first=True)
    why = next(d for d in draft.drafts_for(jid) if d["field"] == "q_why")
    assert why["kind"] == "saved" and why["answer"] == "I want to build tools at Acme as a Robotics Intern.  Plain words, mine."
    assert "your saved answer" in why["rationale"].lower()
    assert ai.prompts == [] and draft.readiness(jid)["ready"]                   # counts as filled: nothing held


async def test_an_optional_essay_box_with_no_saved_answer_is_left_blank_not_held(fake_llm):
    _alex()
    jid = _job("Acme", FIRST, WORK_AUTH, EXTRA)
    fake_llm(lambda s, p: {"answers": []})
    await draft.draft_job(jid)
    extra = next(d for d in draft.drafts_for(jid) if d["field"] == "q_extra")
    assert extra["kind"] == "left_blank" and not extra["answer"] and draft.readiness(jid)["ready"]


@pytest.mark.parametrize("text, issue", [
    ("At {company} I'd ship 400 robots a week.", "Number '400' not found in your facts"),
    ("Robots. " * 60, "Over limit: 60/50 words"),
])
async def test_your_saved_answer_is_checked_like_any_other_and_never_changed_to_pass(fake_llm, text, issue):
    """Rule 1: what goes in is checked before it's sent, your words too. A number that's in neither your resume,
    profile nor the posting, or more than the box allows, holds it for you; the text stays exactly yours."""
    _alex()
    essays.save("why_company", text)
    jid = _job("Acme", FIRST, WORK_AUTH, dict(WHY_US, label="Why do you want to work at {co}? (50 words max)"))
    fake_llm(lambda s, p: {"answers": []})
    await draft.draft_job(jid, hold_first=True)
    why = next(d for d in draft.drafts_for(jid) if d["field"] == "q_why")
    assert why["kind"] == "saved" and why["answer"] == text.replace("{company}", "Acme")
    assert issue in why["issues"] and not draft.readiness(jid)["ready"]


async def test_a_limit_in_a_boxs_help_text_still_holds_your_saved_answer_after_a_recheck(fake_llm):
    """The limit is only in the help text under the box. Answering something else in Needs you re-checks the
    application; your too-long saved answer still holds it."""
    _alex(work_auth=False)
    essays.save("why_company", "Robots. " * 60)
    jid = _job("Acme", FIRST, WORK_AUTH, dict(WHY_US, description="Please keep it to 50 words."))
    fake_llm(lambda s, p: {"answers": []})
    await draft.draft_job(jid, hold_first=True)
    fixes.answer("profile:work_authorized_us", "Yes")
    why = next(d for d in draft.drafts_for(jid) if d["field"] == "q_why")
    assert "Over limit: 60/50 words" in why["issues"] and not draft.readiness(jid)["ready"]
    assert db.q1("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "filled"


@pytest.mark.parametrize("cls", [llm.AnthropicAPI, llm.OpenAIAPI])
async def test_checking_an_ai_with_no_key_sends_nothing_and_counts_nothing(cls):
    db.set_settings({"ai_daily_budget": 1})
    b = cls(key="")
    ok, msg = await llm._check(llm._check_key(b), b)
    assert not ok and "API key" in msg
    assert db.q1("SELECT COUNT(*) n FROM usage")["n"] == 0 and llm.budget_left() == 1


async def test_your_saved_answer_traces_to_you_in_the_audit(fake_llm):
    from jobsmith import audit
    _alex()
    essays.save("why_company", "Your tools taught me to build.")
    jid = _job("Acme", FIRST, WORK_AUTH, WHY_US, EXTRA)
    fake_llm(lambda s, p: {"answers": []})
    await draft.draft_job(jid, hold_first=True)
    ds = {d["field"]: d for d in draft.drafts_for(jid)}
    for f in ("q_why", "q_extra"):
        p = audit.provenance(ds[f], profile.answers(), profile.facts_by_id())
        assert p["source"] == "you" and p["traces"], (f, p)


async def test_an_optional_cover_letter_left_blank_is_written_when_you_ask(fake_llm):
    """Autopilot leaves an optional cover letter box blank; asking for a cover letter still writes one."""
    from jobsmith import letters
    _alex()
    jid = _job("Acme", FIRST, {"field": "cover_letter_text", "label": "Cover Letter", "qtype": "textarea",
                               "required": False, "options": []})
    fake_llm(lambda s, p: {"answers": []})
    await draft.draft_job(jid, hold_first=True)
    assert letters.cover_text(jid) == ""
    jet = [f["id"] for f in profile.facts()][:1]
    fake_llm(lambda s, p: {"answers": [{"field": "cover_letter", "answer": "I build tools.", "fact_ids": jet,
                                        "confidence": 0.9}]})
    assert await letters.write_cover(jid) == "I build tools."


async def test_a_connection_check_that_is_a_real_request_keeps_to_the_budget_and_is_logged(monkeypatch):
    """Claude's and OpenAI's check is a one-line request: with today's budget used it isn't sent (the last answer
    stands), and one that fails is logged like any failed call."""
    sent = []

    class Claude(llm.AnthropicAPI):
        async def available(self):
            sent.append(1)
            return False, "Anthropic API 401: invalid key"
    b = Claude(key="sk-test")
    db.set_settings({"ai_daily_budget": 1})
    ok, msg = await llm._check(llm._check_key(b), b)
    assert sent == [1] and not ok
    row = db.q1("SELECT purpose, backend, ok, error FROM usage")
    assert row == {"purpose": "connection check", "backend": "anthropic_api", "ok": 0,
                   "error": "Anthropic API 401: invalid key"}
    ok, msg = await llm._check(llm._check_key(b), b)                     # that call used today's one: not sent,
    assert sent == [1] and msg == "Anthropic API 401: invalid key"       # the last answer stands
    llm.forget_checks()
    ok, msg = await llm._check(llm._check_key(b), b)
    assert sent == [1] and not ok and "budget is used" in msg


# --------------------------------------------------------------------------- Needs you, by fix
async def _held(company: str, *fields: dict) -> str:
    """Autopilot's drafting; held before AI when a profile fact is missing, else held where the form filler holds
    it (here AI wrote nothing: the fake answers no questions)."""
    jid = _job(company, FIRST, *fields)
    await draft.draft_job(jid, hold_first=True)
    if db.q1("SELECT status FROM jobs WHERE id=?", (jid,))["status"] == "drafted":
        db.x("UPDATE jobs SET status='filled', hold_reason=? WHERE id=?",
             ("; ".join(draft.readiness(jid)["blockers"][:3]), jid))
    return jid


async def test_needs_you_lists_each_fix_once_with_how_many_it_unblocks_resume_pdf_first(fake_llm):
    _alex(work_auth=False)
    fake_llm(lambda s, p: {"answers": []})
    a, b = await _held("Acme", WORK_AUTH), await _held("Globex", WORK_AUTH, OFFICE)
    c, d = await _held("Initech", OFFICE), await _held("Hooli", OFFICE)
    out = fixes.compute()
    assert out["held"] == 4
    first, *rest = out["fixes"]
    assert first["id"] == "resume_pdf" and first["unblocks"] == 4            # no PDF: every application waits
    by = {f["id"]: f for f in rest}
    auth = by["profile:work_authorized_us"]
    assert auth["title"] == "Add: Authorized to work in the US?" and auth["choices"] == ["Yes", "No"]
    assert auth["unblocks"] == 2 and set(auth["jobs"]) == {a, b}
    # Globex's office question waits for AI (it never got to write it), not for you; AI wrote nothing for the others
    office = by[fixes.question_id(OFFICE["label"], OFFICE["options"])]
    assert office["unblocks"] == 2 and set(office["jobs"]) == {c, d} and office["choices"] == ["Yes", "No"]
    assert office["ready_after"] == 2 and auth["ready_after"] == 2


async def test_answering_a_fix_rechecks_every_held_application_and_sends_the_complete_ones(fake_llm, tmp_path,
                                                                                         monkeypatch):
    _alex(work_auth=False)
    resume_pdf(tmp_path)
    db.set_settings({"autonomy": "autopilot", "max_applications_per_day": 10})
    fake_llm(lambda s, p: {"answers": []})
    a, b = await _held("Acme", WORK_AUTH), await _held("Globex", WORK_AUTH, OFFICE)
    c = await _held("Initech", OFFICE)
    queued = []
    monkeypatch.setattr(commands, "queue", lambda ids: queued.extend(ids) or ids)
    res = fixes.answer("profile:work_authorized_us", "Yes")
    assert profile.answers()["work_authorized_us"]["value"] == "Yes"
    # Acme is complete; Globex has only its office question left, for AI to write: both go back to autopilot
    assert sorted(res["freed"]) == sorted([a, b]) and sorted(queued) == sorted([a, b])
    assert db.q1("SELECT status, hold_reason FROM jobs WHERE id=?", (a,)) == {"status": "drafted", "hold_reason": None}
    assert db.q1("SELECT status FROM jobs WHERE id=?", (c,))["status"] == "filled"
    res = fixes.answer(fixes.question_id(OFFICE["label"], OFFICE["options"]), "Yes")
    assert res["freed"] == [c] and queued[-1] == c
    office = next(d for d in draft.drafts_for(c) if d["field"] == "q_office")
    assert office["final_answer"] == "Yes" and office["verdict"] == "green"


@pytest.mark.parametrize("twin", ["#q_office", '[name="q_office"]'])
async def test_a_question_read_as_two_boxes_is_one_fix_and_your_answer_fills_both(fake_llm, tmp_path, monkeypatch,
                                                                                 twin):
    """Greenhouse's dropdowns and checkbox lists are read as two boxes, "question_1" and "#question_1" or
    '[name="question_1"]' (the box behind it, with no choices). Your real data listed each such question twice;
    it's one question: listed once, answered once."""
    _alex()
    resume_pdf(tmp_path)
    fake_llm(lambda s, p: {"answers": []})
    jid = await _held("Initech", OFFICE, dict(OFFICE, field=twin, options=[]))
    office = [f for f in fixes.compute()["fixes"] if f["kind"] == "question"]
    assert len(office) == 1 and office[0]["choices"] == ["Yes", "No"] and office[0]["jobs"] == [jid]
    monkeypatch.setattr(commands, "queue", lambda ids: ids)
    res = fixes.answer(office[0]["id"], "Yes")
    assert {d["field"]: d["final_answer"] for d in draft.drafts_for(jid) if "office" in d["field"]} == \
        {"q_office": "Yes", twin: "Yes"}
    assert res["freed"] == [jid]


WORKED = {"field": "q_worked", "label": "Have you worked for {co} before?", "qtype": "select", "required": True,
          "options": ["Yes", "No"]}


async def test_have_you_worked_here_waits_on_one_confirmation_only_where_it_answers_it(fake_llm, tmp_path, monkeypatch):
    """"Have you worked for <company> before?" on many forms waits on one thing of yours: confirming your resume
    lists every employer and contract you've had. Not when the question also covers subsidiaries (your resume
    can't say): that one stays with its application. Once you confirm, each is answered No, with where from."""
    _alex()
    resume_pdf(tmp_path)
    fake_llm(lambda s, p: {"answers": []})
    a, b = await _held("Acme", WORKED), await _held("Globex", WORKED)
    c = await _held("Initech", dict(WORKED, label="Have you worked for {co} or any of its subsidiaries?"))
    out = fixes.compute()
    every = next(f for f in out["fixes"] if f["id"] == "profile:resume_lists_all_employers")
    assert set(every["jobs"]) == {a, b} and every["choices"] == ["Yes", "No"] and every["ready_after"] == 2
    assert "My resume lists every employer" in every["title"]
    own = {x["id"]: x["own"] for x in out["applications"]}
    assert c in own and "lists every employer" not in own[c][0]           # not offered where it can't answer it
    monkeypatch.setattr(commands, "queue", lambda ids: ids)
    res = fixes.answer("profile:resume_lists_all_employers", "Yes")
    assert sorted(res["freed"]) == sorted([a, b])
    worked = next(d for d in draft.drafts_for(a) if d["field"] == "q_worked")
    assert worked["answer"] == "No" and "Acme isn't on it" in worked["rationale"]
    assert db.q1("SELECT status FROM jobs WHERE id=?", (c,))["status"] == "filled"


async def test_a_fix_answered_past_the_days_limit_waits_for_room(fake_llm, tmp_path, monkeypatch):
    _alex(work_auth=False)
    resume_pdf(tmp_path)
    db.set_settings({"autonomy": "autopilot"})
    fake_llm(lambda s, p: {"answers": []})
    a = await _held("Acme", WORK_AUTH)
    from jobsmith import guardrails
    monkeypatch.setattr(guardrails, "remaining_today", lambda: 0)
    queued = []
    monkeypatch.setattr(commands, "queue", lambda ids: queued.extend(ids) or ids)
    res = fixes.answer("profile:work_authorized_us", "Yes")
    assert res["freed"] == [a] and queued == []
    assert a in scheduler.pick_new_jobs(5)                                      # the next run sends it


async def test_work_authorization_is_only_ever_what_you_typed(fake_llm):
    """Rule 2: the fix sets your profile answer from what you entered; nothing is guessed for you, and an empty
    answer is refused."""
    _alex(work_auth=False)
    fake_llm(lambda s, p: {"answers": [{"field": "q_auth", "answer": "Yes", "fact_ids": [], "confidence": 1}]})
    await _held("Acme", WORK_AUTH)
    with pytest.raises(ValueError):
        fixes.answer("profile:work_authorized_us", "")
    assert not (profile.answers().get("work_authorized_us") or {}).get("value")


async def test_a_held_application_stopped_by_you_or_held_on_the_form_isnt_sent_by_a_recheck(fake_llm, tmp_path,
                                                                                         monkeypatch):
    _alex()
    resume_pdf(tmp_path)
    db.set_settings({"autonomy": "autopilot"})
    fake_llm(lambda s, p: {"answers": []})
    stopped, form = _job("Acme", FIRST, WORK_AUTH), _job("Globex", FIRST, WORK_AUTH)
    for jid, why in ((stopped, "Stopped by you"), (form, "Create your login and press Submit Profile yourself")):
        await draft.draft_job(jid)
        db.x("UPDATE jobs SET status='filled', hold_reason=? WHERE id=?", (why, jid))
    queued = []
    monkeypatch.setattr(commands, "queue", lambda ids: queued.extend(ids) or ids)
    res = fixes.recheck()
    assert res["freed"] == [] and queued == []
    own = {a["id"]: a["own"] for a in res["applications"]}
    assert own[stopped] == ["Stopped by you"] and own[form] == ["Create your login and press Submit Profile yourself"]


async def test_out_of_ai_autopilot_still_sends_what_needs_none_and_says_so_once(fake_llm, tmp_path, monkeypatch):
    _alex()
    resume_pdf(tmp_path)
    db.set_settings({"onboarded": True, "auto_run": True, "power_mode": "full", "notifications": False,
                     "ai_daily_budget": 1, "autonomy": "autopilot"})
    db.x("INSERT INTO usage(job_id, purpose, backend, model, at) VALUES(NULL, 'answers', 'fake', '', ?)", (db.now(),))
    fake_llm(lambda s, p: {"answers": []})
    needs_ai, plain = _job("Acme", FIRST, WHY_US), _job("Globex", FIRST, WORK_AUTH)
    draft.save_results(needs_ai, [dict(WHY_US, label="Why do you want to work at Acme?")],
                       {"q_why": draft.pending(WHY_US)}, status="drafted")

    async def no_sync():
        return []
    queued = []
    monkeypatch.setattr(scheduler.sources, "sync_all", no_sync)
    monkeypatch.setattr(scheduler.match, "rescore", lambda ids=None: 0)
    monkeypatch.setattr(commands, "queue", lambda ids: queued.extend(ids) or ids)
    res = await scheduler.run_once("test")
    assert queued == [plain]                                                   # the one waiting for AI keeps its turn
    assert res["summary"].count("AI budget is used") == 1
