#!/usr/bin/env python3
"""Cases for the commit hook's matcher. Run: python3 scripts/hooks/test_commit_review.py (pytest runs them too,
through tests/test_commit_hook.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from commit_review import inspect  # noqa: E402

MSG = """git commit -m "$(cat <<'EOF'
Fix the thing

Don't git add everything; it's fine.
EOF
)\""""

# (command, commits?, stages in the same command?, -C path)
CASES = [
    # plain and amend
    ("git commit -m 'x'", True, False, None),
    ("git commit --amend --no-edit", True, False, None),
    (MSG, True, False, None),
    ("git commit -F - <<EOF\nwhy: git add . && git commit -a\nEOF", True, False, None),
    ("git commit -m x 2>&1 | tail -5", True, False, None),
    ("git commit -m x > /dev/null", True, False, None),
    # after &&, ;, ||, |, newline, in a subshell
    ("cd /repo && git commit -m x", True, False, None),
    ("uv run pytest -q; git commit -m x", True, False, None),
    ("false || git commit -m x", True, False, None),
    ("echo hi | git commit -F -", True, False, None),
    ("git status\ngit commit -m x", True, False, None),
    ("(cd sub && git commit -m x)", True, False, None),
    # env vars, env, wrappers, git options in front
    ("GIT_AUTHOR_DATE=now git commit -m x", True, False, None),
    ("FOO=1 BAR=2 git commit -m x", True, False, None),
    ("env -i HOME=/h git commit -m x", True, False, None),
    ("/usr/bin/git commit -m x", True, False, None),
    ("git -C /some/repo commit -m x", True, False, "/some/repo"),
    ("git -c user.name=A -C ../r commit -m x", True, False, "../r"),
    ("git --no-pager -C r commit -m x", True, False, "r"),
    ("time git commit -m x", True, False, None),
    # inside sh -c, bash -lc, eval
    ("sh -c 'git commit -m x'", True, False, None),
    ("bash -lc \"cd r && git -C r commit -m x\"", True, False, "r"),
    ("zsh -c 'FOO=1 git commit -m x'", True, False, None),
    ("eval git commit -m x", True, False, None),
    # stages and commits in one command: refused
    ("git add -A && git commit -m x", True, True, None),
    ("git add a.py; git commit -m x", True, True, None),
    ("git rm old.py && git commit -m x", True, True, None),
    ("sh -c 'git add . && git commit -m x'", True, True, None),
    ("git add . && sh -c 'git commit -m x'", True, True, None),
    ("git commit -am x", True, True, None),
    ("git commit -a -m x", True, True, None),
    ("git commit --all -m x", True, True, None),
    ("git commit -m x a.py", True, True, None),
    ("git commit -m x -- a.py", True, True, None),
    ("git commit -i a.py -m x", True, True, None),
    # shell syntax, wrappers and command substitution (from Codex's review of the first version)
    ("if true; then git commit -m x; fi", True, False, None),
    ("! git commit -m x", True, False, None),
    ('echo "$(git commit -m x)"', True, False, None),
    ("echo `git commit -m x`", True, False, None),
    ("env --unset FOO git commit -m x", True, False, None),
    ("env -S 'git commit -m x'", True, False, None),
    ("sudo -u root git commit -m x", True, False, None),
    ("timeout 60 git commit -m x", True, False, None),
    ("cat <<EOF\n$(git commit -m x)\nEOF", True, False, None),
    ('echo "<<EOF"\ngit commit -m x', True, False, None),
    ("git commit -m \"$(cat <<'EOF'\nIt's (mostly) done; git add later\nEOF\n)\"", True, False, None),
    ("git commit -uno -m x", True, False, None),
    ("git commit -Sdeadbeef -m x", True, False, None),
    ("git add --dry-run . && git commit -m x", True, False, None),
    ("git apply patch.diff && git commit -m x", True, False, None),
    ("git status # then; git commit -m x\ngit commit -m y", True, False, None),
    # staging hidden in a subshell, eval or $(...)
    ("sh -c 'git add .' && git commit -m x", True, True, None),
    ("eval 'git rm a'; git commit -m x", True, True, None),
    ("sh -c 'git mv a b'; git commit -m x", True, True, None),
    ("sh -c 'git commit -m first; git add .'; git commit -m second", True, True, None),
    ('git commit -m "$(git add .; echo x)"', True, True, None),
    ("git reset HEAD a.py && git commit -m x", True, True, None),
    ("git restore --staged a.py; git commit -m x", True, True, None),
    ("git apply --cached p.diff && git commit -m x", True, True, None),
    # comments, quoted operators, help: no false commits or staging
    ("git commit -m x # comment", True, False, None),
    ('echo ";" git commit -m x', False, False, None),
    ("# git status; git commit -m x", False, False, None),
    ("git status # ; git commit -m x", False, False, None),
    ("cat <<'END-MSG'\ngit commit -m x\nEND-MSG", False, False, None),
    ("git --help commit", False, False, None),
    ("git status", False, False, None),
    ("git log --grep 'git commit'", False, False, None),
    ("grep -n 'git commit' CLAUDE.md", False, False, None),
    ("echo git commit", False, False, None),
    ("git commit-tree HEAD^{tree}", False, False, None),
    ("git add -A", False, False, None),
    ("rg commit && git diff --staged", False, False, None),
    ("cat <<EOF\ngit commit -m x\nEOF", False, False, None),
]


def main() -> int:
    bad = 0
    for cmd, commits, stages, where in CASES:
        got = inspect(cmd)
        want = {"commit": commits, "stages": stages, "where": where}
        if got != want:
            bad += 1
            print(f"FAIL {cmd!r}\n  want {want}\n  got  {got}")
    print(f"{len(CASES) - bad} of {len(CASES)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
