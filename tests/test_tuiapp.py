"""The terminal app, driven like a person would: ask, review, autopilot. Runs against a real engine on a spare port."""
import asyncio
import itertools
import re
import socket
import threading
import time

import pytest
import uvicorn
from rich.console import Console

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
    """The logo's swing and the live rows tick on timers and engine updates repaint the welcome box; a tick that lands after the
    widgets are removed (quitting) must be skipped, not crash. Seen on CI as NoMatches('#logo')."""
    from jobsmith.tuiapp import Jobsmith
    db.conn()

    async def go():
        app = Jobsmith(engine, splash=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            for sel in ("#welcome", "#live", "#think", "#status"):
                await app.query_one(sel).remove()
            app.motion = True
            app.swing()                                            # would raise NoMatches('#logo')
            app.animate()
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


def test_matches_shows_left_out_roles_on_l_and_enter_applies_anyway(engine, monkeypatch):
    """Job board roles left out for you are counted in /matches; l lists them with why, and enter applies anyway."""
    from jobsmith import runner
    from jobsmith.tuiapp import Jobsmith, Matches
    db.conn()
    now = db.now()
    for jid, title, status, left, why in (
            ("m1", "Software Engineer Intern", "new", None, None),
            ("m2", "Senior Software Engineer", "left_out", "senior", 'Left out: "Senior" in the title: more senior than you\'re looking for')):
        db.x("""INSERT INTO jobs(id, company, title, url, ats, status, left_out, hold_reason, fit_score, created_at,
                updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
             (jid, "Acme Robotics", title, f"https://x/{jid}", "lever", status, left, why, 80, now, now))
    started = []

    def fake_spawn(jid, label, coro):
        coro.close()
        started.append((jid, label))
        return True
    monkeypatch.setattr(runner, "spawn", fake_spawn)

    async def go():
        from textual.widgets import DataTable, Static
        app = Jobsmith(engine, splash=False)
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.pause(1)
            app.query_one("#prompt").value = "/matches"
            await pilot.press("enter")
            await pilot.pause(1.5)
            screen = app.screen
            assert isinstance(screen, Matches)
            t = screen.query_one("#m", DataTable)
            assert t.row_count == 1 and "l left out (1)" in str(screen.query_one("#t", Static).content)
            await pilot.press("l")
            await pilot.pause(1)
            assert t.row_count == 1 and str(t.border_title) == "Left out"
            assert "more senior than you're looking for" in str(t.get_row_at(0)[2])
            await pilot.press("enter")
            await pilot.pause(0.5)
    asyncio.run(go())
    assert started == [("m2", "autopilot")]


def test_losing_the_engine_shows_on_one_status_line_and_logs_only_a_long_outage(engine, monkeypatch):
    """The terminal app said "Lost Jobsmith's engine… Retrying" and "Back in touch" over and over, one pair per slow
    reply. Now a missed poll shows on the status line, counting in place; the log hears once, and only after the
    engine has been away for DOWN_LOG_AFTER seconds, and then once more when it's back."""
    import httpx
    from textual.widgets import Static
    from jobsmith import tuiapp
    from jobsmith.tuiapp import Jobsmith
    db.conn()
    monkeypatch.setattr(tuiapp, "DOWN_LOG_AFTER", 2.5)
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)
    # The engine gone, refused at once: a real closed port takes Windows about 2 s to refuse (it retries the
    # connection), longer than the pauses below, so CI there never saw a failed poll in time.
    nowhere = httpx.Client(base_url="http://127.0.0.1:9", transport=httpx.MockTransport(refuse))

    async def go():
        app = Jobsmith(engine, splash=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(1)
            real = app.http
            status = lambda: str(app.query_one("#status", Static).render())
            for _ in range(3):                                   # three short blips: the log stays quiet
                app.http = nowhere
                await pilot.pause(1.7)
                assert "reconnecting to the engine…" in status()
                app.http = real
                await pilot.pause(1.7)
                assert "reconnecting" not in status()
            assert "engine" not in _texts(app)
            app.http = nowhere                                   # a long one: said once, then once more when back
            await pilot.pause(5)
            assert _texts(app).count("Can't reach Jobsmith's engine") == 1
            app.http = real
            await pilot.pause(2)
            assert _texts(app).count("Back in touch with the engine") == 1
            assert "reconnecting" not in status()
    asyncio.run(go())


def test_the_hammer_swings_once_about_the_end_of_its_handle_and_rests():
    """About a second: the head comes down in an arc, the handle's end stays put (it's the pivot, like a real
    swing), sparks fly only from the strike, and it ends on the resting frame."""
    from jobsmith.tuiapp import EMBER, STRIKE, logo_text, swing_frames
    frames = swing_frames()
    assert 0.8 <= sum(secs for _, secs in frames) <= 1.2
    assert frames[-1][0].plain == logo_text().plain and frames[-1][1] == 0
    rows = [f.plain.split("\n") for f, _ in frames]
    for i, r in enumerate(rows):
        assert r[2][17] != " "                                  # the handle's end, in every frame
        assert [re.sub("[✦✧·]", " ", line) for line in r[3:]] == rows[-1][3:]   # the anvil never moves
        assert any(ch in "".join(r) for ch in "✦✧·") == (STRIKE <= i < len(rows) - 1)
    head = [max((n for n, line in enumerate(f.split("\n")) if any(s.style == EMBER for s in line.spans)), default=-1)
            for f, _ in frames[:STRIKE + 1]]
    assert head == sorted(head) and head[-1] == 2               # the head only comes down, onto the anvil
    assert "▐██▌━━━━━" in rows[-1][2]                          # resting on the anvil


@pytest.mark.parametrize("env, tty, system, moves", [
    ({}, True, False, True),
    ({"NO_COLOR": "1"}, True, False, False),
    ({"TERM": "dumb"}, True, False, False),
    ({}, False, False, False),                                  # not a terminal: piped, CI, a log
    ({"JOBSMITH_REDUCED_MOTION": "1"}, True, False, False),
    ({}, True, True, False),                                    # Reduce motion in the system's settings
    ({"JOBSMITH_REDUCED_MOTION": "0"}, True, True, True),       # asked for it anyway
])
def test_the_hammer_keeps_still_when_motion_is_unwelcome(monkeypatch, env, tty, system, moves):
    from jobsmith import tuiapp
    for k in ("NO_COLOR", "TERM", "JOBSMITH_REDUCED_MOTION"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(tuiapp.sys.stdout, "isatty", lambda: tty, raising=False)
    monkeypatch.setattr(tuiapp, "_system_reduces_motion", lambda: system)
    assert tuiapp.motion_ok() is moves


@pytest.mark.parametrize("motion", [True, None])
def test_the_swing_plays_once_then_nothing_wakes_the_app(engine, motion):
    """With motion it plays through and stops; without (here: headless, so not a terminal) only the resting frame is
    drawn. Either way, once it rests no timer is left running for it, and with nothing applying or thinking the
    0.1 s tick is paused too, so an idle terminal app costs no CPU."""
    from textual.widgets import Static
    from jobsmith.tuiapp import Jobsmith, logo_text
    db.conn()

    async def go():
        app = Jobsmith(engine, splash=False, motion=motion)
        drawn = []
        async with app.run_test(size=(120, 40)) as pilot:
            logo = app.query_one("#logo", Static)
            update = logo.update
            logo.update = lambda art="": (drawn.append(art.plain), update(art))
            app.swing()
            await pilot.pause(1.5)
            assert drawn[-1] == logo_text().plain
            assert app.swing_timer is None and not app.swing_left
            assert app.ticker._active.is_set() is False         # paused: nothing to animate
            app.start_busy()
            assert app.ticker._active.is_set()                  # thinking: it ticks again
            app.stop_busy()
        return drawn
    drawn = asyncio.run(go())
    from jobsmith.tuiapp import swing_frames
    assert len(set(drawn)) == (len({f.plain for f, _ in swing_frames()}) if motion else 1)


def screen_text(app) -> str:
    """What export_screenshot draws, as text (its SVG puts every block character in an element of its own)."""
    import io
    console = Console(width=app.size.width, height=app.size.height, file=io.StringIO(), force_terminal=True,
                      color_system="truecolor", record=True, legacy_windows=False, safe_box=False)
    console.print(app.screen._compositor.render_update(full=True, screen_stack=app._background_screens))
    return console.export_text()


@pytest.mark.parametrize("platform, says, reduces", [
    ("darwin", "1\n", True), ("darwin", "0\n", False), ("darwin", OSError, False),
    ("linux", "false\n", True), ("linux", "true\n", False),
])
def test_reduce_motion_is_read_from_the_system(monkeypatch, platform, says, reduces):
    import subprocess
    from jobsmith import tuiapp

    def run(cmd, **kw):
        if says is OSError:
            raise OSError("no defaults")
        return subprocess.CompletedProcess(cmd, 0, stdout=says)
    monkeypatch.setattr(tuiapp.sys, "platform", platform)
    monkeypatch.setattr(tuiapp.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(tuiapp.subprocess, "run", run)
    assert tuiapp._system_reduces_motion() is reduces


@pytest.mark.parametrize("answered, animations, reduces", [(1, 1, False), (1, 0, True), (0, 0, False)])
def test_reduce_motion_on_windows_reads_a_whole_bool(monkeypatch, answered, animations, reduces):
    """SystemParametersInfoW writes a 4-byte BOOL; when the call fails, its answer isn't read."""
    import ctypes
    from ctypes import wintypes
    from jobsmith import tuiapp

    class User32:
        def SystemParametersInfoW(self, action, _, ref, __):
            assert action == 0x1042 and type(ref._obj) is wintypes.BOOL     # 4 bytes on Windows
            ref._obj.value = animations
            return answered
    monkeypatch.setattr(tuiapp.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", type("W", (), {"user32": User32()})(), raising=False)
    assert tuiapp._system_reduces_motion() is reduces


def test_the_hammer_swings_after_the_splash_on_help_and_when_an_application_is_sent(engine):
    """Not while the splash covers it; then once on /help and once when an application goes out. And the live
    rows' tick, paused while nothing ran, picks up again when one starts."""
    from jobsmith.tuiapp import Jobsmith, Splash
    db.conn()

    async def go():
        app = Jobsmith(engine, splash=True, motion=True)
        swings = []
        app.swing = lambda real=app.swing: (swings.append(len(app.screen_stack)), real())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            assert isinstance(app.screen, Splash) and swings == []
            await pilot.press("x")                                  # any key skips the splash
            await pilot.pause(0.2)
            assert swings == [1]                                    # once it's gone, not behind it
            await pilot.pause(1.5)
            assert not app.ticker._active.is_set()
            app.apply_state({"active": {"j9": "filling"}}, [], {}, {})
            assert app.ticker._active.is_set()                      # an application started: it ticks again
            app.apply_state({"active": {"j9": "submitted"}}, [], {}, {})
            assert len(swings) == 2                                 # sent
            app.query_one("#prompt").focus()
            await pilot.press(*"/help", "enter")
            await pilot.pause(0.2)
            assert len(swings) == 3
    asyncio.run(go())


def test_the_screenshot_shows_the_resting_hammer(engine):
    """The terminal app as it first looks, motion off: the resting frame, whole, beside the welcome."""
    from jobsmith.tuiapp import LOGO_W, Jobsmith, logo_text
    db.conn()

    async def go():
        app = Jobsmith(engine, splash=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.5)
            return screen_text(app)
    screen = asyncio.run(go())
    rest = logo_text().plain.split("\n")
    at = screen.index(rest[2])
    left = at - screen.rfind("\n", 0, at) - 1                  # the logo's column on screen
    lines = screen.split("\n")
    row = next(n for n, line in enumerate(lines) if line[left:left + LOGO_W] == rest[2])
    assert [line[left:left + LOGO_W] for line in lines[row - 2:row + 4]] == [r.ljust(LOGO_W) for r in rest]


def test_jobsmith_checks_gallery_gets_the_terminal_app_at_rest(engine, tmp_path):
    from jobsmith.devtools import terminal_screenshot
    db.conn()
    asyncio.run(terminal_screenshot(engine, tmp_path / "terminal.svg"))
    svg = (tmp_path / "terminal.svg").read_text(encoding="utf-8")
    assert svg.startswith("<svg") and "▐" in svg and "━" in svg
