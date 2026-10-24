"""`jobsmith demo show`: three made-up applications played through autopilot in the practice copy only, drawn by the
real terminal app, with no browser, AI or network."""
import asyncio

import httpx
import pytest

from jobsmith import config, db, draft, runner, showcase
from test_tuiapp import _texts, engine  # noqa: F401  (engine is a fixture: a real API server on a spare port)

IDS = [a["id"] for a in showcase.APPS]


@pytest.fixture
def practice(monkeypatch):
    """The practice copy, with every outward door wired to fail the test if it's touched."""
    from jobsmith import api

    def door(*a, **k):
        raise AssertionError("the show must not open a browser, call the network or start a process")
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(api, "DEMO", True)
    monkeypatch.setattr(runner.browser, "new_page", door)
    monkeypatch.setattr(runner.browser, "context", door)
    monkeypatch.setattr(httpx.AsyncClient, "send", door)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", door)
    db.conn()
    yield
    for jid in IDS:
        runner.LIVE.pop(jid, None)
        runner._active.pop(jid, None)


def test_refuses_outside_the_practice_copy(monkeypatch):
    from fastapi.testclient import TestClient
    from jobsmith import api
    monkeypatch.setattr(config, "DEMO", False)
    with pytest.raises(PermissionError):
        asyncio.run(showcase.play(speed=0))
    with TestClient(api.app) as c:
        r = c.post("/api/demo/autopilot-show", json={})
    assert r.status_code == 403 and "practice copy" in r.json()["detail"]
    assert not db.q("SELECT 1 FROM jobs WHERE id LIKE 'show-%'")


def test_two_submitted_one_held(practice, monkeypatch):
    seen: dict[str, list[str]] = {}
    real_set = runner.live_set

    def record(jid, page=None, **kw):
        if "phase" in kw:
            seen.setdefault(jid, []).append(kw["phase"])
        real_set(jid, page, **kw)
    monkeypatch.setattr(runner, "live_set", record)

    ends = asyncio.run(showcase.play(speed=0))

    assert ends == {"show-lumen": "submitted", "show-quarry": "filled", "show-kestrel": "submitted"}
    assert seen["show-lumen"] == seen["show-kestrel"] == ["filling", "submitting", "submitted"]
    assert seen["show-quarry"] == ["filling", "review"]
    held = db.q1("SELECT hold_reason FROM jobs WHERE id='show-quarry'")
    assert held["hold_reason"] == showcase.HELD_REASON
    why = next(d for d in draft.drafts_for("show-quarry") if d["field"] == "why")
    assert why["confidence"] < 0.6 and not draft.readiness("show-quarry")["ready"]    # really held, not submittable
    # the real progress bars and live list see them with no browser tab
    assert [runner.progress(j)["step"] for j in IDS] == [4, 3, 4]
    assert {t["job_id"]: t["phase"] for t in runner.live_list() if t["job_id"] in IDS} == {"show-lumen": "submitted", "show-quarry": "review",
                                                                     "show-kestrel": "submitted"}
    assert db.q1("SELECT COUNT(*) n FROM runs WHERE kind='submit' AND status='done' AND job_id LIKE 'show-%'")["n"] == 2
    # it plays again from the start
    assert asyncio.run(showcase.play(speed=0)) == ends
    assert db.q1("SELECT COUNT(*) n FROM jobs WHERE id LIKE 'show-%'")["n"] == 3


def test_the_terminal_app_plays_it(practice, engine, monkeypatch):  # noqa: F811
    from jobsmith.tuiapp import Jobsmith
    # The app polls the engine every 1.5 s and announces a change only for a job it has already seen, so each step
    # must outlast one poll (the real show's steps are 2-4.5 s). Shorter would test a speed nobody watches.
    monkeypatch.setattr(showcase, "STEP_SECONDS", {k: 1.6 for k in showcase.STEP_SECONDS})
    monkeypatch.setattr(showcase, "STAGGER", 0.3)

    async def go():
        app = Jobsmith(engine, splash=False, start="show")
        async with app.run_test(size=(120, 40)) as pilot:
            saw_bar = False
            for _ in range(200):
                await pilot.pause(0.1)
                live = str(app.query_one("#live").render())
                saw_bar = saw_bar or ("Applying to" in live and "▰" in live)
                assert "show-" not in live, live                 # company names, never internal ids
                if _texts(app).count("submitted ✓") == 2 and "waiting for you" in _texts(app):
                    break
            out = _texts(app)
            assert "Practice copy:" in out and "3 made-up applications" in out
            assert "Lumen Robotics" in out and "Kestrel AI" in out and out.count("submitted ✓") == 2
            assert "Quarry Labs" in out and "is filled and waiting for you" in out
            assert saw_bar, "the spinner line and progress bars never showed"
            assert "practice copy" in str(app.query_one("#status").render())
    asyncio.run(go())


def test_stop_stops_the_show(practice, monkeypatch):
    """/stop and autopilot off go through runner.stop(); the show must stop with them, mid-step."""
    monkeypatch.setattr(showcase, "STEP_SECONDS", {k: 0.2 for k in showcase.STEP_SECONDS})
    monkeypatch.setattr(showcase, "STAGGER", 0.05)

    async def go():
        assert showcase.start(speed=1) and not showcase.start(speed=1)     # a second start while playing is refused
        await asyncio.sleep(0.5)                                         # every one is past reading, none finished
        out = await runner.stop()
        assert out["stopped"] == 3 and not showcase.running()
        before = {r["id"]: r["status"] for r in db.q("SELECT id, status FROM jobs WHERE id LIKE 'show-%'")}
        await asyncio.sleep(1.5)                                         # longer than the rest of the show
        after = {r["id"]: r["status"] for r in db.q("SELECT id, status FROM jobs WHERE id LIKE 'show-%'")}
        assert before == after and "submitted" not in after.values()
        assert not any(j in runner._active or j in runner.LIVE for j in IDS)   # no spinner left turning
        assert not db.q("SELECT 1 FROM runs WHERE job_id LIKE 'show-%'")
        assert showcase.start(speed=0)                                   # and it plays again from the start
        await asyncio.gather(*showcase._playing)
        ends = {r["id"]: r["status"] for r in db.q("SELECT id, status FROM jobs WHERE id LIKE 'show-%'")}
        assert ends == {"show-lumen": "submitted", "show-quarry": "filled", "show-kestrel": "submitted"}
        assert not any(j in runner._by_job for j in IDS)                  # nothing left registered as running
    asyncio.run(go())


def test_finished_practice_entries_expire_like_real_ones(practice):
    asyncio.run(showcase.play(speed=0))
    for jid in IDS:
        runner.LIVE[jid]["since"] -= 601
    assert [t["job_id"] for t in runner.live_list() if t["job_id"] in IDS] == ["show-quarry"]   # held stays, like its tab


def test_api_starts_it_once(practice):
    from fastapi.testclient import TestClient
    from jobsmith import api
    with TestClient(api.app) as c:
        first = c.post("/api/demo/autopilot-show", json={"speed": 0.5}).json()
        second = c.post("/api/demo/autopilot-show", json={}).json()
        c.post("/api/stop", json={})
    assert first == {"started": True, "playing": True} and second["started"] is False


def test_demo_show_points_the_terminal_at_its_own_practice_copy(monkeypatch):
    from jobsmith import devtools, tuiapp
    calls = {}
    monkeypatch.setattr(devtools, "demo", lambda **kw: calls.setdefault("demo", kw) and "http://127.0.0.1:8766/#/")
    monkeypatch.setattr(tuiapp, "run", lambda base, **kw: calls.update(run=(base, kw)))
    devtools.main(["demo", "show"])
    assert calls["demo"] == {"open_browser": False}                   # always a fresh practice copy of its own
    assert calls["run"] == ("http://127.0.0.1:8766", {"splash": False, "start": "show"})
