"""The front door: `jobsmith` (or `jobsmith open`, or the Jobsmith app) opens the dashboard without the user knowing a
command or an address; every Needs-you item links to the page that fixes it; the dashboard stays on this computer.

No engine is started and no browser opens: both are stand-ins. The launcher is only ever made inside a temporary HOME.
Made-up data only (Acme, Globex, Initech)."""
import json
import re
import sys
from pathlib import Path

import pytest

from jobsmith import cli, db, fixes, frontdoor, mcp_server, needs

ROOT = Path(__file__).resolve().parent.parent


class FakeEngine:
    """Stands in for the engine process and the browser: counts starts and opened addresses."""

    def __init__(self, monkeypatch, running: bool = False, starts_ok: bool = True):
        self.running, self.starts_ok = running, starts_ok
        self.started, self.opened = [], []
        monkeypatch.setattr(frontdoor, "engine_up", lambda base=None: self.running)
        monkeypatch.setattr(frontdoor, "_port_taken", lambda base: False)
        monkeypatch.setattr(frontdoor, "start_engine", self.start)
        monkeypatch.setattr(frontdoor.time, "sleep", lambda s: None)
        monkeypatch.setattr(frontdoor.webbrowser, "open", lambda url: self.opened.append(url) or True)
        monkeypatch.setattr(frontdoor, "quiet_open", lambda url: self.opened.append(url) or True)
        from jobsmith import tui
        monkeypatch.setattr(tui, "main", lambda argv: (_ for _ in ()).throw(AssertionError("started the terminal app")))

    def start(self, base):
        self.started.append(base)
        engine = self

        class Proc:
            def poll(self):
                if engine.starts_ok:
                    engine.running = True
                    return None
                return 1
        return Proc()


def _run(monkeypatch, *args) -> int:
    monkeypatch.setattr(sys, "argv", ["jobsmith", *args])
    try:
        cli.main()
    except SystemExit as e:
        return e.code or 0
    return 0


@pytest.mark.parametrize("args", [(), ("open",)])
def test_jobsmith_starts_the_engine_and_opens_the_dashboard(monkeypatch, capsys, args):
    eng = FakeEngine(monkeypatch)
    assert _run(monkeypatch, *args) == 0
    url = frontdoor.base_url()
    assert eng.started == [url] and eng.opened == [url]
    assert capsys.readouterr().out == f"Jobsmith is open at {url}\n"


@pytest.mark.parametrize("args", [(), ("open",)])
def test_a_second_run_only_opens_the_browser(monkeypatch, capsys, args):
    eng = FakeEngine(monkeypatch)
    _run(monkeypatch, *args)
    _run(monkeypatch, *args)
    assert len(eng.started) == 1 and len(eng.opened) == 2
    assert capsys.readouterr().out.count("Jobsmith is open at ") == 2


def test_an_engine_that_fails_to_start_gets_one_plain_line(monkeypatch, capsys):
    FakeEngine(monkeypatch, starts_ok=False)
    assert _run(monkeypatch) == 1
    out = capsys.readouterr()
    lines = out.out.splitlines()
    assert len(lines) == 1 and lines[0].startswith("Jobsmith couldn't start") and "jobsmith doctor" in lines[0]
    assert "Traceback" not in out.out + out.err


def test_an_engine_that_never_answers_or_a_busy_port_gets_one_plain_line(monkeypatch, capsys):
    eng = FakeEngine(monkeypatch)
    eng.start = lambda base: type("P", (), {"poll": lambda self: None})()       # runs, never answers
    monkeypatch.setattr(frontdoor, "start_engine", eng.start)
    assert _run(monkeypatch) == 1
    assert re.fullmatch(r"Jobsmith couldn't start: its engine didn't answer within \d+ seconds\..*\n", capsys.readouterr().out)
    monkeypatch.setattr(frontdoor, "_port_taken", lambda base: True)
    assert _run(monkeypatch) == 1
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "another program is using port" in out


def test_an_unexpected_error_at_the_front_door_is_one_line_not_a_traceback(monkeypatch, capsys):
    FakeEngine(monkeypatch)
    monkeypatch.setattr(frontdoor, "ensure_engine", lambda *a, **k: 1 / 0)
    assert _run(monkeypatch) == 1
    out = capsys.readouterr()
    assert out.out.count("\n") == 1 and "Traceback" not in out.out + out.err


def test_the_terminal_app_is_still_one_flag_away(monkeypatch):
    from jobsmith import tui
    got = []
    monkeypatch.setattr(tui, "main", lambda argv: got.append(list(argv)))
    monkeypatch.setattr(frontdoor, "main", lambda: (_ for _ in ()).throw(AssertionError("opened the browser")))
    for args in (["--terminal"], ["--terminal", "--plain"], ["--plain"], ["status"], ["apply to acme"]):
        monkeypatch.setattr(sys, "argv", ["jobsmith", *args])
        cli.main()
    assert got == [[], ["--plain"], ["--plain"], ["status"], ["apply to acme"]]


# --------------------------------------------------------------------------- this computer only
def test_the_dashboard_only_ever_listens_on_this_computer(monkeypatch):
    import uvicorn
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: seen.update(k))
    monkeypatch.setattr(sys, "argv", ["jobsmith", "serve", "--no-open"])
    cli.main()
    assert seen["host"] == "127.0.0.1"
    # the engine the front door starts is that same `serve`, with no way to pass another address
    started = []
    monkeypatch.setattr(frontdoor.subprocess, "Popen", lambda args, **kw: started.append(args))
    frontdoor.start_engine("http://127.0.0.1:9")
    assert started[0][-4:] == ["serve", "--no-open", "--port", "9"] and "--host" not in started[0]
    # an address pointing off this computer is never used
    monkeypatch.setenv("JOBSMITH_URL", "http://203.0.113.5:8765")
    assert frontdoor.base_url().startswith("http://127.0.0.1:")
    monkeypatch.setenv("JOBSMITH_URL", "http://localhost:9")
    assert frontdoor.base_url() == "http://localhost:9"


def test_no_code_binds_anywhere_but_localhost():
    """Every listener in the package: uvicorn on 127.0.0.1, nothing on 0.0.0.0 or a public address, and no other
    kind of server at all."""
    for f in (ROOT / "jobsmith").rglob("*.py"):
        text = f.read_text(errors="replace")
        assert "--host" not in text, f
        assert not re.search(r"""(host\s*=\s*|bind\(\(?)["']0\.0\.0\.0""", text), f
        assert not re.search(r"socketserver|http\.server|start_server|\.listen\(", text), f
        for host in re.findall(r"""\bhost=["']([^"']+)["']""", text):
            assert host == "127.0.0.1", (f, host)


# --------------------------------------------------------------------------- MCP: the link, not the menus
def _held(jid: str, company: str, status: str = "filled") -> None:
    now = db.now()
    db.x("""INSERT INTO jobs(id, company, title, url, ats, description, status, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)""", (jid, company, "Software Intern", f"https://example.com/{jid}", "greenhouse",
                                         "Build software.", status, now, now))


def _every_kind_of_fix(monkeypatch):
    """One of each thing Needs you can hold on: AI, resume PDF, profile facts (salary, languages, citizenship,
    clearance), a saved answer, a shared question, one job's question, a first-submission approval, a site error."""
    _held("acme1", "Acme")
    _held("globex1", "Globex")
    _held("initech1", "Initech", status="error")
    _held("approve1", "Acme")
    db.x("INSERT INTO first_runs(job_id, site, asked_at) VALUES('approve1', 'greenhouse', ?)", (db.now(),))
    fx = [{"id": "resume_pdf", "kind": "resume_pdf", "key": "resume", "title": "Add your resume as a PDF", "unblocks": 3},
          *[{"id": f"profile:{k}", "kind": "profile", "key": k, "title": f"Add: {k}", "unblocks": 2, "part": "you"}
            for k in ("desired_pay", "languages", "us_citizen", "security_clearance")],
          {"id": "essay:why_us", "kind": "essay", "key": "why_us", "title": "Save your answer to “Why us?”", "unblocks": 2},
          {"id": "question:aaa", "kind": "question", "key": "Start date?", "title": "Answer “Start date?”",
           "unblocks": 2, "part": "you", "jobs": ["acme1", "globex1"]},
          {"id": "question:bbb", "kind": "question", "key": "Favorite robot?", "title": "Answer “Favorite robot?”",
           "unblocks": 1, "part": "job", "jobs": ["globex1"]}]
    apps = [{"id": "initech1", "company": "Initech", "title": "Software Intern", "status": "error",
             "own": ["The site said the form expired"], "fixes": [], "questions": []},
            {"id": "approve1", "company": "Acme", "title": "Software Intern", "status": "filled",
             "own": ["Autopilot's first submission on Greenhouse waits for you"], "fixes": [], "questions": []}]
    monkeypatch.setattr(fixes, "compute", lambda: {"held": 4, "fixes": fx, "applications": apps})


def test_every_needs_you_item_links_to_the_page_that_fixes_it(monkeypatch):
    _every_kind_of_fix(monkeypatch)
    rows = needs.items(ai=(False, "No AI is set up"))
    href = {r["key"]: r["href"] for r in rows}
    assert href["ai"] == "#/settings/ai"
    assert href["resume_pdf"] == "#/profile/resume"
    assert href["profile:desired_pay"] == "#/profile/desired_pay"
    assert href["profile:languages"] == "#/profile/languages"
    assert href["profile:us_citizen"] == "#/profile/us_citizen"
    assert href["profile:security_clearance"] == "#/profile/security_clearance"
    assert href["essay:why_us"] == "#/settings/saved-answers"
    assert href["question:aaa"] == "#/"                          # asked by several: Needs you on Home
    assert href["question:bbb"] == "#/job/globex1"               # this application's own
    assert href["approve:approve1"] == "#/job/approve1"          # first-submission approval: its review page
    assert href["job:initech1"] == "#/job/initech1"
    assert "job:approve1" not in href                            # listed once, as the approval
    base = frontdoor.base_url()
    for r in rows:
        assert r["link"] == f"{base}/{r['href']}" and r["page"] and r["text"]
    texts = {r["key"]: r["text"] for r in rows}
    assert texts["profile:desired_pay"] == "Add your salary range"
    assert texts["profile:us_citizen"] == "Say whether you're a US citizen"
    # the banner: what's about you, never one application's own problem
    assert {r["key"] for r in needs.blocking(rows)} == {
        "ai", "resume_pdf", "profile:desired_pay", "profile:languages", "profile:us_citizen",
        "profile:security_clearance", "essay:why_us", "question:aaa"}


def test_needs_you_never_carries_a_profile_answer(monkeypatch):
    from jobsmith import profile
    profile.set_answer("us_citizen", "Yes", confirmed=False)
    _every_kind_of_fix(monkeypatch)
    rows = needs.items(ai=None)
    assert all("value" not in r for r in rows) and all(r["key"] != "ai" for r in rows)


def test_status_gives_the_dashboard_and_a_link_for_every_needs_you_item(monkeypatch):
    _every_kind_of_fix(monkeypatch)
    out = json.loads(mcp_server.jobsmith_status())
    base = frontdoor.base_url()
    assert out["dashboard"] == base
    assert out["needs_you"] and all(i["link"].startswith(base + "/#/") and i["page"] for i in out["needs_you"])
    assert {"ai", "approve:approve1", "profile:desired_pay"} <= {i["key"] for i in out["needs_you"]}


async def test_the_dashboard_tool_is_annotated_honestly():
    tools = {t.name: t for t in await mcp_server.mcp.list_tools()}
    a = tools["jobsmith_dashboard"].annotations
    assert a.read_only_hint is False and a.destructive_hint is False
    assert "link" in tools["jobsmith_status"].description.lower()


def test_the_dashboard_tool_opens_the_page_and_returns_its_link(monkeypatch, capsys):
    eng = FakeEngine(monkeypatch)
    base = frontdoor.base_url()
    out = json.loads(mcp_server.jobsmith_dashboard())
    assert out["dashboard"] == base and out["opened"] and eng.opened == [base] and len(eng.started) == 1
    out = json.loads(mcp_server.jobsmith_dashboard(f"{base}/#/profile/desired_pay"))
    assert out["opened_page"] == f"{base}/#/profile/desired_pay" and len(eng.started) == 1
    out = json.loads(mcp_server.jobsmith_dashboard("https://evil.example/#/x"))     # never another site
    assert eng.opened[-1] == base
    assert capsys.readouterr().out == ""                         # stdout is the agent's conversation


def test_the_dashboard_tool_says_plainly_when_the_engine_cant_start(monkeypatch):
    FakeEngine(monkeypatch, starts_ok=False)
    out = json.loads(mcp_server.jobsmith_dashboard())
    assert out["error"].startswith("Jobsmith couldn't start") and out["dashboard"] == frontdoor.base_url()


def test_the_banner_reads_needs_you_from_the_engine(monkeypatch):
    from fastapi.testclient import TestClient
    from jobsmith.api import app
    _every_kind_of_fix(monkeypatch)
    r = TestClient(app).get("/api/needs").json()
    keys = [i["key"] for i in r["blocking"]]
    assert keys[0] == "ai" and "profile:desired_pay" in keys and "job:initech1" not in keys
    assert all(i["href"].startswith("#/") for i in r["blocking"])


# --------------------------------------------------------------------------- the macOS launcher
@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert Path.home() == home                                   # never the real one
    return home


def test_install_launcher_creates_and_removes_the_app_in_a_temporary_home(fake_home, monkeypatch, capsys):
    import plistlib
    monkeypatch.setattr(sys, "platform", "darwin")
    assert _run(monkeypatch, "install-launcher") == 0
    app = fake_home / "Applications" / "Jobsmith.app"
    plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert plist["CFBundleIdentifier"] == frontdoor.APP_ID and plist["CFBundleExecutable"] == "Jobsmith"
    exe = app / "Contents" / "MacOS" / "Jobsmith"
    assert exe.stat().st_mode & 0o111 and "-m jobsmith open" in exe.read_text()
    assert str(app) in capsys.readouterr().out
    assert _run(monkeypatch, "install-launcher", "--remove") == 0
    assert not app.exists() and (fake_home / "Applications").exists()
    assert "Removed" in capsys.readouterr().out


def test_install_launcher_leaves_an_app_it_didnt_make_alone(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    other = fake_home / "Applications" / "Jobsmith.app"
    (other / "Contents").mkdir(parents=True)
    (other / "Contents" / "keep.txt").write_text("someone else's")
    assert _run(monkeypatch, "install-launcher", "--remove") == 1
    assert _run(monkeypatch, "install-launcher") == 1
    assert (other / "Contents" / "keep.txt").read_text() == "someone else's"


def test_install_launcher_is_macos_only(fake_home, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    assert _run(monkeypatch, "install-launcher") == 1
    assert "macOS" in capsys.readouterr().out and not (fake_home / "Applications").exists()
