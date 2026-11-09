"""First-run setup, walked through the dashboard on a clean data folder, the way a new person meets it.

A real engine runs on a free port against an empty folder made for this test (never the real data folder or the
practice copy's ports), in practice mode so nothing can leave the machine. The folder holds only made-up job
listings, so setup's live match count has something to count. The person is the made-up Alex Rivera.

Set JOBSMITH_SHOTS_DIR to keep a screenshot of every step (docs/images/setup/ is made this way)."""
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from jobsmith.fill.base import browser_args

ROOT = Path(__file__).parent.parent
SHOTS = os.environ.get("JOBSMITH_SHOTS_DIR")
STEPS = ["Start with your resume", "Check what we read", "Questions forms ask", "What you're looking for",
         "Where to look", "Writing help (optional)", "Your first application"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(port: int, path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return json.loads(r.read())


@pytest.fixture
def engine(tmp_path):
    """A fresh install: an empty data folder, the practice-mode engine on a free port. Yields (port, data folder)."""
    data, port = tmp_path / "data", _free_port()
    data.mkdir()
    env = dict(os.environ, JOBSMITH_DATA=str(data), JOBSMITH_DEMO_DATA=str(data), JOBSMITH_DEMO="1",
               JOBSMITH_PORT=str(port))
    seed = subprocess.run([sys.executable, "-m", "jobsmith", "demo-seed", "--setup"], env=env, cwd=ROOT,
                          capture_output=True, text=True)
    assert seed.returncode == 0, seed.stderr[-2000:]
    log = open(data / "server.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "jobsmith", "serve", "--no-open", "--port", str(port)], env=env,
                            cwd=ROOT, stdout=log, stderr=log, stdin=subprocess.DEVNULL)
    try:
        for _ in range(120):
            try:
                _get(port, "/api/status")
                break
            except OSError:
                time.sleep(0.25)
        else:
            raise AssertionError("the engine didn't start:\n" + (data / "server.log").read_text()[-2000:])
        yield port, data
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


async def _shot(page, name: str) -> None:
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(Path(SHOTS) / f"{name}.png"), full_page=True)


async def test_a_new_person_gets_from_a_resume_to_their_first_application(engine):
    from playwright.async_api import async_playwright, expect
    port, data = engine
    state = _get(port, "/api/onboarding")
    assert not state["resume"]["pdf"] and not _get(port, "/api/status").get("onboarded")     # a clean start
    async with async_playwright() as pw:
        exe = os.environ.get("JOBSMITH_CHROMIUM_PATH")
        browser = await pw.chromium.launch(headless=True, args=browser_args(), **({"executable_path": exe} if exe else {}))
        page = await browser.new_page(viewport={"width": 1180, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/s2/favicons**", lambda r: r.abort())
        await page.goto(f"http://127.0.0.1:{port}/")
        heading = page.locator("h1")
        go = page.locator(".onb-act .btn.primary")

        # 1. the resume PDF comes first, and nothing else is asked until it's read
        await expect(heading).to_have_text(STEPS[0])
        await expect(go).to_be_disabled()
        await _shot(page, "1-resume")
        await page.set_input_files('input[type="file"]', str(data / "Alex_Rivera_resume.pdf"))
        await expect(page.locator(".drop")).to_contain_text("Alex_Rivera_resume.pdf", timeout=60000)
        await _shot(page, "1-resume-read")
        await go.click()

        # 2. every value read from it is shown to be checked
        await expect(heading).to_have_text(STEPS[1])
        await expect(page.get_by_label("Email for applications")).to_have_value("alex.rivera@example.edu")
        await expect(page.get_by_label("Legal first name")).to_have_value("Alex")
        await _shot(page, "2-confirm")
        await go.click()

        # 3. the one-time questions: work authorization, sponsorship and the employer list have no default
        await expect(heading).to_have_text(STEPS[2])
        await expect(go).to_be_disabled()
        await expect(go).to_contain_text("Answer 3 more")
        await _shot(page, "3-questions")
        for label, answer in (("Are you authorized to work in the US?", "Yes"),
                              ("Will you need visa sponsorship, now or later?", "No"),
                              ("Does your resume list every employer", "Yes")):
            group = page.get_by_role("group", name=label, exact=False).first
            await group.get_by_role("button", name=answer, exact=True).click()
        await expect(go).to_have_text("Save and continue")
        await _shot(page, "3-questions-answered")
        await go.click()

        # 4. what they're looking for, with a live count of matches
        await expect(heading).to_have_text(STEPS[3])
        count = page.locator(".count-n")
        await expect(count).to_have_text(re.compile(r"^\d+$"), timeout=15000)
        assert 0 < int(await count.inner_text()) < 300
        await _shot(page, "4-looking")
        await go.click()

        # 5. job lists from presets, never a board address to paste
        await expect(heading).to_have_text(STEPS[4])
        assert not await page.locator('input[type="url"], input[placeholder*="http"]').count()
        await _shot(page, "5-sources")
        await go.click()

        # 6. AI is optional
        await expect(heading).to_have_text(STEPS[5])
        await _shot(page, "6-ai")
        await page.get_by_role("button", name="Skip for now").click()

        # 7. the supervised first application; nothing was drafted and autopilot was off until here
        await expect(heading).to_have_text(STEPS[6])
        assert not _get(port, "/api/status").get("auto_run")
        await _shot(page, "7-start")
        await go.click()
        await page.wait_for_function("!location.hash.startsWith('#/setup')", timeout=30000)
        await page.wait_for_timeout(800)
        await _shot(page, "8-home")
        await browser.close()
    assert not errors, errors
    done = _get(port, "/api/onboarding")
    assert done["resume"]["pdf"] and all(done["step_done"].get(k) for k in ("resume", "confirm", "questions", "prefs"))
