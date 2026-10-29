"""The engine's "is your AI connected?" answer never holds up a page that asks every second or two. A check is a
real request; Gemini's could wait out a rate limit for minutes, and while it did, every /api/status reply was past
the terminal app's 8 s timeout ("Lost Jobsmith's engine… / Back in touch", over and over)."""
import asyncio
import time

import httpx
import pytest

from jobsmith import llm


class SlowCheck(llm.Backend):
    """An AI whose connection check takes as long as the test says."""
    name = "slow_test"

    def __init__(self, answer: str = "connected"):
        self.checks = 0
        self.answer = answer
        self.release = asyncio.Event()
        self.started = asyncio.Event()

    async def available(self):
        self.checks += 1
        n, release, answer = self.checks, self.release, self.answer      # as things stood when it started
        self.started.set()
        await release.wait()
        return answer == "connected", f"{answer} (check {n})"

    async def complete_json(self, *a, **k):
        return {}


@pytest.fixture
def slow():
    llm._avail_cache.clear()
    llm._avail_checks.clear()
    b = SlowCheck()
    llm.set_backend_override(b)
    return b


async def test_the_last_answer_comes_back_at_once_while_one_check_refreshes_it(slow):
    key = llm._check_key(slow)
    llm._avail_cache[key] = (time.time() - 3600, True, "connected (earlier)")          # stale
    t0 = time.monotonic()
    answers = await asyncio.gather(*[llm.available_cached() for _ in range(5)])
    assert time.monotonic() - t0 < 0.5
    assert answers == [(True, "connected (earlier)")] * 5
    await asyncio.sleep(0)
    assert slow.checks == 1                                    # five pages asking, one check
    slow.release.set()
    await llm._avail_checks[key]
    assert await llm.available_cached() == (True, "connected (check 1)")


async def test_the_first_check_waits_a_little_then_says_its_checking(slow, monkeypatch):
    monkeypatch.setattr(llm, "FIRST_CHECK_WAIT", 0.2)
    assert await llm.available_cached() == (False, "Checking your AI connection…")
    slow.release.set()
    await asyncio.sleep(0.05)
    assert await llm.available_cached() == (True, "connected (check 1)")


async def test_testing_the_connection_waits_for_a_fresh_answer(slow):
    llm._avail_cache[llm._check_key(slow)] = (time.time(), False, "old answer")
    task = asyncio.create_task(llm.available_cached(ttl=0))
    await asyncio.sleep(0.1)
    assert not task.done()                                     # you asked: it waits for the real check
    slow.release.set()
    assert await task == (True, "connected (check 1)")


async def test_no_check_while_out_of_quota(slow, monkeypatch):
    key = llm._check_key(slow)
    llm._avail_cache[key] = (time.time() - 3600, False, "Gemini's free tier limit is used up for now.")
    monkeypatch.setitem(llm._quota_hit, slow.name, time.time() + 3600)
    assert (await llm.available_cached())[1] == "Gemini's free tier limit is used up for now."
    assert slow.checks == 0


async def test_status_answers_quickly_while_the_ai_check_hangs(slow, monkeypatch):
    """The page the terminal app polls, end to end, with an AI check that never finishes."""
    from jobsmith.api import app
    monkeypatch.setattr(llm, "FIRST_CHECK_WAIT", 0.2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        for _ in range(3):
            t0 = time.monotonic()
            r = await c.get("/api/status")
            assert r.status_code == 200 and time.monotonic() - t0 < 2
    assert slow.checks == 1
    slow.release.set()


async def test_status_checks_a_separate_research_ai_side_by_side(monkeypatch):
    """With research on its own AI, both checks are cold at start-up: they start together and their waits overlap
    instead of adding up past the terminal app's timeout."""
    from jobsmith import db
    from jobsmith.api import app
    llm._avail_cache.clear()
    llm._avail_checks.clear()
    write, research = SlowCheck(), SlowCheck()
    research.name = "slow_research"
    monkeypatch.setattr(llm, "backend", lambda role="write": research if role == "research" else write)
    monkeypatch.setattr(llm, "FIRST_CHECK_WAIT", 1.0)
    db.set_settings({"llm_backend": "gemini_api", "research_backend": "openai_api"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        t0 = time.monotonic()
        assert (await c.get("/api/status")).status_code == 200
        assert time.monotonic() - t0 < 1.8                       # one wait, not one after the other
    assert (write.checks, research.checks) == (1, 1)
    write.release.set()
    research.release.set()


async def test_a_new_token_or_cli_path_is_checked_afresh(slow):
    """The cached answer belongs to one configuration: sign in with a new token, or point Jobsmith at another copy
    of the CLI, and that's checked, not the old answer reused (the everyday ttl, not a forced recheck)."""
    slow.release.set()
    slow.token, slow.path = "old-token", "/usr/local/bin/claude"
    await llm.available_cached()
    await llm._avail_checks[llm._check_key(slow)]
    assert await llm.available_cached() == (True, "connected (check 1)")
    for attr, value in (("token", "new-token"), ("path", "/opt/homebrew/bin/claude")):
        setattr(slow, attr, value)
        before = slow.checks
        assert await llm.available_cached() == (True, f"connected (check {before + 1})")
        assert slow.checks == before + 1


async def test_a_check_from_before_you_signed_in_never_overwrites_the_new_answer(slow):
    """You sign in while a check of the old sign-in is still out: when it comes back, it's dropped."""
    slow.answer = "not signed in"
    old = asyncio.create_task(llm.available_cached(ttl=0))
    await slow.started.wait()                                   # the old check is out
    old_release = slow.release
    llm.forget_checks()                                         # you signed in
    slow.answer, slow.release = "connected", asyncio.Event()
    slow.release.set()
    assert await llm.available_cached(ttl=0) == (True, "connected (check 2)")
    old_release.set()                                           # the old check finishes last
    await old
    assert await llm.available_cached() == (True, "connected (check 2)")


async def test_the_claude_cli_probe_is_kept_per_sign_in(monkeypatch):
    """The Claude CLI's own ten-minute probe: a new token is a real request, not the last token's "connected"."""
    pinged = []

    async def run(self, *a):
        pinged.append(self.token)
        if self.token == "bad":
            raise llm.LLMError("401 invalid token")
        return {"ok": True}
    monkeypatch.setattr(llm.ClaudeCLI, "_run", run)
    llm.forget_checks()
    assert (await llm.ClaudeCLI("claude", "haiku", "good")._probe())[0] is True
    assert (await llm.ClaudeCLI("claude", "haiku", "good")._probe())[0] is True           # cached
    assert (await llm.ClaudeCLI("claude", "haiku", "bad")._probe())[0] is False
    assert (await llm.ClaudeCLI("/opt/homebrew/bin/claude", "haiku", "good")._probe())[0] is True   # another CLI
    assert pinged == ["good", "bad", "good"]


async def test_a_claude_cli_probe_from_before_you_signed_in_is_dropped(monkeypatch):
    """Same for the CLI's own probe: an old one that fails late doesn't replace the new "connected"."""
    held, started = asyncio.Event(), asyncio.Event()

    async def run(self, *a):
        if self.model == "old":
            started.set()
            await held.wait()
            raise llm.LLMError("401 invalid token")
        return {"ok": True}
    monkeypatch.setattr(llm.ClaudeCLI, "_run", run)
    monkeypatch.setattr(llm, "_check_key", lambda b: ("claude_cli", "same"))   # the same configuration either way
    llm.forget_checks()
    old = asyncio.create_task(llm.ClaudeCLI("claude", "old", "t")._probe())
    await started.wait()
    llm.forget_checks()                                          # you signed in again
    assert (await llm.ClaudeCLI("claude", "new", "t")._probe())[0] is True
    held.set()
    assert (await old)[0] is False
    assert llm.ClaudeCLI._probe_cache[("claude_cli", "same")][1] is True
