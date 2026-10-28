import os
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="jobsmith-test-")
os.environ["JOBSMITH_DATA"] = _tmp

from jobsmith import db, llm  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_terminal_summary(terminalreporter, config):
    """Tests run in a random order; say which, even under -q, so a failure in CI can be replayed exactly."""
    seed = getattr(config.option, "randomly_seed", None)
    if isinstance(seed, int):
        terminalreporter.write_line(f"Random order seed: {seed} (repeat with -p randomly --randomly-seed={seed})")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    db.reset_for_tests(tmp_path / "test.db")
    db.set_settings({"research_enabled": False, "llm_backend": "none"})
    yield
    llm.set_backend_override(None)


def trust(*sites: str) -> None:
    """Autopilot's first submission on these sites was approved earlier, so it sends on its own now."""
    for s in sites:
        db.x("INSERT INTO first_runs(job_id, site, asked_at, approved_at) VALUES(?,?,?,?)",
             (f"earlier-{s}", s, db.now(), db.now()))


class FakeLLM(llm.Backend):
    """Returns canned answers; records prompts so tests can assert on them."""
    name = "fake"

    def __init__(self, responder):
        self.responder = responder
        self.prompts = []

    async def available(self):
        return True, "fake"

    async def complete_json(self, system, prompt, schema=None, web=False, timeout=240):
        self.prompts.append(prompt)
        self.last_usage = {"input": 1000, "output": 200, "cached": 0, "searches": 1 if web else 0}
        return self.responder(system, prompt)


@pytest.fixture
def fake_llm():
    def install(responder):
        b = FakeLLM(responder)
        llm.set_backend_override(b)
        return b
    return install
