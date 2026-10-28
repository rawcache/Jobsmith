"""The opt-in commit hook in scripts/hooks/ finds `git commit` anywhere in a command and refuses one that also stages.
Its cases live beside it, so they can be run without pytest; this runs them in CI too."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "hooks"))
from commit_review import inspect  # noqa: E402
from test_commit_review import CASES  # noqa: E402


@pytest.mark.parametrize("cmd,commits,stages,where", CASES, ids=[c[0][:40] for c in CASES])
def test_the_commit_hook_reads_the_command(cmd, commits, stages, where):
    assert inspect(cmd) == {"commit": commits, "stages": stages, "where": where}
