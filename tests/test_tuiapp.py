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
