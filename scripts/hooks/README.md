# Codex review before every commit (opt in)

`commit_review.py` is a [Claude Code hook](https://docs.claude.com/en/docs/claude-code/hooks). Before Claude Code
runs a shell command that contains `git commit`, the hook has Codex review the staged diff, read-only, against
`CLAUDE.md`. It passes the review back to Claude Code. It also refuses a command that stages and commits in one go
(`git add … && git commit`, `git commit -a`, `git commit <paths>`), because the review runs before the command and
would see the wrong stage.

It finds `git commit` anywhere in a command, not just at the start:
- after `&&`, `;`, `||`, `|` or a newline
- inside `sh -c`, `eval`, `$(…)` or `if … then`
- behind `VAR=x`, `env`, `sudo` or `timeout`
- with `git -C <path>` in front, in which case Codex reviews that repo

The review is advisory: Claude Code is told what Codex found, and the commit goes ahead.

The hook only reads your staged diff. It never edits files, commits or pushes, and it never runs Codex with more
than `-s read-only`.

## Opt in

1. Install the [Codex CLI](https://github.com/openai/codex) and sign in, so `codex` runs in your terminal. Without
   it, the hook still refuses stage-and-commit commands, and its review says Codex didn't run.
2. Add the hook to your own `.claude/settings.json` (or `.claude/settings.local.json`) in your clone:

   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "Bash",
           "hooks": [
             {
               "type": "command",
               "command": "python3 \"$CLAUDE_PROJECT_DIR/scripts/hooks/commit_review.py\"",
               "timeout": 300,
               "statusMessage": "Codex reviewing staged diff before commit"
             }
           ]
         }
       ]
     }
   }
   ```

3. Commit the way the hook expects: `git add` as its own command, then `git commit` on its own.

To opt out, remove the entry. Nothing else changes.

## Tests

```bash
python3 scripts/hooks/test_commit_review.py   # 73 commands: what commits, what stages, which repo
```

`uv run pytest` runs the same cases through `tests/test_commit_hook.py`. If you change the matcher, add the
command that prompted the change to `CASES`.
