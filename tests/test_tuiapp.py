"""The terminal app, driven like a person would: ask, review, autopilot. Runs against a real engine on a spare port."""
import asyncio
import socket
import threading
import time

import pytest
import uvicorn

from jobsmith import db, draft


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def engine():
    from jobsmith.api import app
    port = _port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


def _held_job():
    now = db.now()
    db.x("""INSERT INTO jobs(id, company, title, url, ats, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)""",
         ("j1", "Acme Robotics", "Robotics Intern", "https://x/1", "greenhouse", "filled", now, now))
    draft.save_results("j1", [{"field": "why", "label": "Why Acme?", "qtype": "textarea", "required": True},
                              {"field": "name", "label": "First Name", "qtype": "text", "required": True}],
                       {"why": {"kind": "generated", "answer": "Because robots.", "confidence": 0.4, "issues": ["Too short"]},
                        "name": {"kind": "standard", "answer": "Alex", "confidence": 1}})


def _texts(app) -> str:
    from textual.widgets import Static
    return "\n".join(str(w.render()) for w in app.query_one("#chat").query(Static))


def test_ask_review_and_autopilot(engine):
    from jobsmith.tuiapp import EditAnswer, Jobsmith, Review
    db.conn()
    _held_job()

    async def go():
        app = Jobsmith(engine, splash=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(1)
            app.query_one("#prompt").value = "what is waiting for me to send?"
            await pilot.press("enter")
            for _ in range(40):
                await pilot.pause(0.1)
                if "from your records" in _texts(app):
                    break
            out = _texts(app)
            assert "Filled, waiting for you to submit" in out and "Acme Robotics" in out

            app.query_one("#prompt").value = "/rev"           # the menu, then enter runs the highlighted command
            await pilot.pause(0.1)
            assert app.menu_items[0][0] == "/review"
            await pilot.press("enter")
            await pilot.pause(1.2)
            assert isinstance(app.screen, Review)
            assert app.screen.current()["label"] == "Why Acme?"   # problems first
            await pilot.press("e")
            await pilot.pause(0.3)
            assert isinstance(app.screen, EditAnswer)
            app.screen.query_one("#ta").text = "I build perception pipelines and want to see them on real robots."
            await pilot.press("ctrl+s")
            await pilot.pause(0.8)
            d = next(x for x in draft.drafts_for("j1") if x["field"] == "why")
            assert d["verdict"] == "green" and d["final_answer"].startswith("I build")
            assert draft.readiness("j1")["ready"]
            await pilot.press("escape")
            await pilot.pause(0.2)

            before = bool(db.get_setting("auto_run"))
            await pilot.press("shift+tab")
            await pilot.pause(0.5)
            assert bool(db.get_setting("auto_run")) != before
    asyncio.run(go())


def test_review_shows_a_first_submission_with_sources_and_s_approves_it(engine, monkeypatch):
    """Autopilot's first submission waits in Review with every answer it filled in and where each came from;
    s approves it (and, with its tab gone, fills it again to send)."""
    import json
    from jobsmith import audit, guardrails, runner
    from jobsmith.tuiapp import EditAnswer, Jobsmith, Review
    db.conn()
    _held_job()
    audit._ensure()
    fields = [{"field": "why", "label": "Why Acme?", "qtype": "textarea", "answer": "I built a Jetson detector.",
               "source": "resume", "detail": [{"ref": "your profile", "text": "Built a fire detector on Jetson Nano"}],
               "traces": True, "approved": True, "kind_check": "ok", "issues": []},
              {"field": "name", "label": "First Name", "qtype": "text", "answer": "Alex", "source": "profile",
               "detail": [{"ref": "Profile: First name", "text": "Alex"}], "traces": True, "approved": True,
               "kind_check": "ok", "issues": []}]
    db.x("INSERT INTO audit_pending(job_id, fields, at) VALUES(?,?,?)", ("j1", json.dumps(fields), db.now()))
    guardrails.ask_approval("j1", "greenhouse")
    db.x("UPDATE jobs SET hold_reason=? WHERE id='j1'", (guardrails.first_run_reason({"ats": "greenhouse"}),))
    started = []

    def fake_spawn(jid, label, coro):
        coro.close()
        started.append((jid, label))
        return True
    monkeypatch.setattr(runner, "spawn", fake_spawn)

    async def go():
        app = Jobsmith(engine, splash=False)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(1)
            app.query_one("#prompt").value = "/review"
            await pilot.press("enter")
            await pilot.pause(1.5)
            screen = app.screen
            assert isinstance(screen, Review) and screen.approval["site_name"] == "Greenhouse"
            from textual.widgets import DataTable, Static
            qs = screen.query_one("#qs", DataTable)
            assert qs.row_count == 2 and "first submission on Greenhouse" in str(qs.border_title)
            from rich.console import Console
            import io
            con = Console(width=200, record=True, file=io.StringIO())
            con.print(screen.query_one("#detail", Static).content)
            detail = con.export_text()
            assert "Came from: Your resume" in detail and "Built a fire detector on Jetson Nano" in detail
            assert "This is autopilot's first submission" in detail
            await pilot.press("e")                          # already filled: change it in the form, not here
            await pilot.pause(0.3)
            assert not isinstance(app.screen, EditAnswer)
            await pilot.press("s")
            await pilot.pause(1.5)
    asyncio.run(go())
    assert started == [("j1", "submitting")]                 # its tab was gone: filled again, to send if it matches
    row = db.q1("SELECT approved_at, answers FROM first_runs WHERE job_id='j1'")
    assert row["approved_at"] is None and row["answers"] == guardrails.answers_key(fields)


def test_a_running_job_is_named_before_its_tab_opens(engine):
    """Researching and drafting happen before a browser tab exists; the terminal should name the company from the
    first frame, not show the job's id."""
    from textual.widgets import DataTable
    from jobsmith import runner
    from jobsmith.tuiapp import Board, Jobsmith
    db.conn()
    now = db.now()
    db.x("""INSERT INTO jobs(id, company, title, url, ats, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)""",
         ("gh_7f3a91", "Northwind Labs", "Firmware Intern", "https://x/2", "greenhouse", "new", now, now))
    runner._active["gh_7f3a91"] = "autopilot"
    assert "gh_7f3a91" not in runner.LIVE                                # no tab yet

    async def go():
        app = Jobsmith(engine, splash=False)
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(30):
                await pilot.pause(0.1)
                if app.state.get("st"):
                    break
            await pilot.pause(0.3)
            live = str(app.query_one("#live").render())
            assert "Northwind Labs" in live and "gh_7f3a91" not in live, live
            await pilot.press("ctrl+o")
            await pilot.pause(0.8)
            assert isinstance(app.screen, Board)
            row = [str(c) for c in app.screen.query_one("#live", DataTable).get_row_at(0)]
            assert "Northwind Labs" in row and "Firmware Intern" in row and "gh_7f3a91" not in row, row
    try:
        asyncio.run(go())
    finally:
        runner._active.pop("gh_7f3a91", None)


def test_job_name_prefers_the_tab_then_the_record_then_the_id():
    from jobsmith.api import _names
    from jobsmith.tuiapp import Jobsmith
    db.conn()
    now = db.now()
    db.x("INSERT INTO jobs(id, company, title, url, ats, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
         ("r1", "Globex", "Data Intern", "https://x/3", "greenhouse", "new", now, now))
    assert _names([]) == {}
    assert _names(["r1", "gone"]) == {"r1": {"company": "Globex", "title": "Data Intern"}}   # unknown ids are left out
    app = Jobsmith("http://127.0.0.1:9", splash=False)
    app.state = {"st": {"names": _names(["r1"])}}
    assert app.job_name("r1") == ("Globex", "Data Intern")
    assert app.job_name("r1", {"company": "Globex Corp", "title": ""}) == ("Globex Corp", "Data Intern")
    assert app.job_name("gone") == ("gone", "")


def test_timers_survive_the_app_closing(engine):
    """The logo animates every 0.1 s and engine updates repaint the welcome box; a tick that lands after the
    widgets are removed (quitting) must be skipped, not crash. Seen on CI as NoMatches('#logo')."""
    from jobsmith.tuiapp import Jobsmith
    db.conn()

    async def go():
        app = Jobsmith(engine, splash=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            for sel in ("#welcome", "#live", "#think", "#status"):
                await app.query_one(sel).remove()
            app.strike = 3
            app.animate()                                          # would raise NoMatches('#logo')
            app.apply_state({"active": {}, "demo": True}, [], {}, {})   # would raise NoMatches('#hello')
    asyncio.run(go())


@pytest.mark.parametrize("demo", [True, False])
def test_the_practice_copy_says_whose_data_it_is(engine, demo):
    """In the practice copy you're the made-up Alex Rivera; "Welcome back, Alex!" read as if it were your own data."""
    from textual.widgets import Static
    from jobsmith.tuiapp import Jobsmith
    db.conn()

    async def go():
        app = Jobsmith(engine, splash=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            app.state = {"st": {"demo": demo}, "home": {"first_name": "Alex"}}
            app.paint_hello()
            return str(app.query_one("#hello", Static).render())
    hello = asyncio.run(go())
    if demo:
        assert hello.startswith("Welcome to the practice copy. You're Alex Rivera, a made-up student.")
        assert "Welcome back" not in hello
    else:
        assert hello.startswith("Welcome back, Alex!")
