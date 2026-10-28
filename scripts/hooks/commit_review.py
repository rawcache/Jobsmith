#!/usr/bin/env python3
"""PreToolUse hook: Codex reviews the staged diff before any `git commit`, wherever it sits in the command.

Reads the hook's JSON on stdin. If the Bash command runs `git commit` anywhere (after &&, ;, |, a newline, inside
if/then, $(...), sh -c or eval, behind env vars, `env`, `sudo`, or git options like -C), it runs a read-only Codex
review and passes it back as context. A command that changes the stage and commits in one go (`git add … && git
commit`, `git commit -a`, `git commit <paths>`) is refused: the review runs before the command starts, so it would
see the wrong stage.

A small shell tokenizer, not a full parser: it knows quotes, escapes, comments, operators, redirects, heredocs and
command substitution, which is what the commands Claude Code runs use. When it can't make sense of a command
(unbalanced quotes) it falls back to a plain search and reviews.

Opt in from your own .claude/settings.json (see README.md here). Stdlib only. Cases: test_commit_review.py."""
from __future__ import annotations

import json
import re
import subprocess
import sys

SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}", "time"}
# Commands that run the rest of the line, and their options that take a separate value.
WRAPPERS = {"sudo": {"-u", "-g", "-C", "-h", "-p", "-U", "-r", "-t", "-D", "-R", "-T"},
            "env": {"-u", "--unset", "-C", "--chdir"},
            "command": set(), "exec": {"-a"}, "nohup": set(), "nice": {"-n"}, "builtin": set(),
            "xargs": {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a"}, "timeout": {"-s", "-k"}}
# git's global options that take a separate value (`git -C path commit`).
GIT_VALUED = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
              "--super-prefix", "--list-cmds"}
# `git commit` options that take a value, so it isn't mistaken for a path.
COMMIT_VALUED_LONG = {"--message", "--file", "--reuse-message", "--reedit-message", "--author", "--date",
                      "--template", "--fixup", "--squash", "--cleanup", "--trailer"}
COMMIT_VALUED_SHORT = set("mFCct")          # value attached or next word
COMMIT_OPTIONAL_SHORT = set("uS")           # value only when attached (-uno, -Skeyid)
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OPS = set("&|;()<>")


class Word(str):
    """A shell word, with the command substitutions inside it and whether any of it was quoted."""
    subs: list[str]
    quoted: bool


def _word(chars: list[str], subs: list[str], quoted: bool) -> Word:
    w = Word("".join(chars))
    w.subs, w.quoted = subs, quoted
    return w


def _close_paren(s: str, i: int) -> int:
    """Index of the ) closing the $( whose ( is at s[i]; quotes inside are skipped."""
    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "'":
            k = s.find("'", j + 1)
            if k < 0:
                raise ValueError("unbalanced '")
            j = k + 1
            continue
        if c == '"':
            j = _close_dquote(s, j + 1) + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise ValueError("unbalanced (")


def _close_dquote(s: str, i: int) -> int:
    j = i
    while j < len(s):
        if s[j] == "\\":
            j += 2
        elif s[j] == '"':
            return j
        elif s.startswith("$(", j):
            j = _close_paren(s, j + 1) + 1
        else:
            j += 1
    raise ValueError('unbalanced "')


def _subs_in(text: str) -> list[str]:
    """Command substitutions in text the shell expands (an unquoted heredoc body)."""
    out, i = [], 0
    while i < len(text):
        if text.startswith("$(", i):
            j = _close_paren(text, i + 1)
            out.append(text[i + 2:j])
            i = j + 1
        elif text[i] == "`":
            j = text.find("`", i + 1)
            if j < 0:
                break
            out.append(text[i + 1:j])
            i = j + 1
        else:
            i += 1
    return out


def lex(s: str) -> list[Word | tuple[str]]:
    """Words and operators. An operator is a 1-tuple, so a quoted ";" stays a word."""
    toks: list = []
    chars: list[str] | None = None
    subs: list[str] = []
    quoted = False
    heredocs: list[tuple[str, bool, bool]] = []     # (delimiter, quoted, strip tabs) waiting for the newline
    i, n = 0, len(s)

    def flush():
        nonlocal chars, subs, quoted
        if chars is not None:
            toks.append(_word(chars, subs, quoted))
        chars, subs, quoted = None, [], False

    def start():
        nonlocal chars
        if chars is None:
            chars = []

    while i < n:
        c = s[i]
        if c in " \t\r":
            flush()
            i += 1
        elif c == "\\":
            if s.startswith("\n", i + 1):             # line continuation
                i += 2
                continue
            start()
            chars.append(s[i + 1:i + 2])
            i += 2
        elif c == "'":
            k = s.find("'", i + 1)
            if k < 0:
                raise ValueError("unbalanced '")
            start()
            chars.append(s[i + 1:k])
            quoted = True
            i = k + 1
        elif c == '"':
            k = _close_dquote(s, i + 1)
            start()
            body = s[i + 1:k]
            subs += _subs_in(body)
            chars.append(body)
            quoted = True
            i = k + 1
        elif s.startswith("$(", i):
            k = _close_paren(s, i + 1)
            start()
            subs.append(s[i + 2:k])
            chars.append(s[i:k + 1])
            i = k + 1
        elif c == "`":
            k = s.find("`", i + 1)
            if k < 0:
                raise ValueError("unbalanced `")
            start()
            subs.append(s[i + 1:k])
            chars.append(s[i:k + 1])
            i = k + 1
        elif c == "#" and chars is None:              # a comment runs to the end of the line
            k = s.find("\n", i)
            i = n if k < 0 else k
        elif c == "\n":
            flush()
            toks.append(("\n",))
            i += 1
            for delim, q, tabs in heredocs:          # skip each heredoc's body; an unquoted one still expands $(...)
                body = []
                while i < n:
                    k = s.find("\n", i)
                    line = s[i:] if k < 0 else s[i:k]
                    i = n if k < 0 else k + 1
                    if (line.lstrip("\t") if tabs else line) == delim:
                        break
                    body.append(line)
                if not q:
                    for sub in _subs_in("\n".join(body)):
                        toks.extend([_word(list("eval"), [], False), _word(list(sub), [], True), ("\n",)])
            heredocs = []
        elif c in OPS:
            flush()
            k = i
            while k < n and s[k] in OPS:
                k += 1
            op = s[i:k]
            toks.append((op,))
            i = k
            if op in ("<<", "<<-"):
                while i < n and s[i] in " \t":
                    i += 1
                m = re.match(r"""(['"]?)([^\s'";&|<>()]+)\1""", s[i:])
                if m:
                    heredocs.append((m.group(2), bool(m.group(1)), op == "<<-"))
        else:
            start()
            chars.append(c)
            i += 1
    flush()
    return toks


def _simple_commands(toks: list) -> list[list[Word]]:
    """Split on ; && || | & ( ) and newlines; drop redirects (`2>&1`, `> out`, `<<EOF`) and their targets."""
    cmds, cur, i = [], [], 0
    while i < len(toks):
        t = toks[i]
        if isinstance(t, tuple):
            op = t[0]
            if set(op) & set("<>"):
                if cur and cur[-1].isdigit() and not cur[-1].quoted:     # the 2 in 2>&1
                    cur.pop()
                i += 2                                # the target or heredoc delimiter goes too
                continue
            if cur:
                cmds.append(cur)
            cur = []
        else:
            cur.append(t)
        i += 1
    if cur:
        cmds.append(cur)
    return cmds


def _unwrap(words: list[Word]) -> list[Word]:
    """Skip `VAR=x`, keywords (if/then/!), `env -u X`, `sudo -u root` and the like in front of the real command.
    `env -S 'cmd'` splits its string into a command; it's returned as `sh -c cmd` so it's inspected too."""
    i = 0
    while i < len(words):
        w = words[i]
        base = w.rsplit("/", 1)[-1]
        if ASSIGN.match(w) or w in KEYWORDS:
            i += 1
        elif base in WRAPPERS:
            valued = WRAPPERS[base]
            i += 1
            while i < len(words) and (words[i].startswith("-") or (base == "env" and ASSIGN.match(words[i]))):
                if base == "env" and words[i] in ("-S", "--split-string") and i + 1 < len(words):
                    return [_word(list("sh"), [], False), _word(list("-c"), [], False), words[i + 1]]
                i += 2 if words[i] in valued else 1
            if base == "timeout" and i < len(words):
                i += 1                                # the duration
        else:
            break
    return words[i:]


def _commit_stages(args: list[str]) -> bool:
    """Does this `git commit` stage on its own (-a, --all, -i/-o, or paths)?"""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return i + 1 < len(args)
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if name in {"--all", "--include", "--only", "--pathspec-from-file"}:
                return True
            if name in COMMIT_VALUED_LONG and "=" not in a:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            for j, ch in enumerate(a[1:]):
                if ch in "aio":
                    return True
                if ch in COMMIT_OPTIONAL_SHORT:
                    break
                if ch in COMMIT_VALUED_SHORT:
                    if j == len(a) - 2:               # value is the next word
                        i += 1
                    break
        else:
            return True                               # a path: commits the working copy of that file
        i += 1
    return False


def _changes_stage(sub: str, args: list[str]) -> bool:
    """git add/rm/mv/reset/restore --staged/apply --cached: the stage the review saw is no longer the one committed."""
    if sub in ("add", "stage"):
        return not any(a in ("-n", "--dry-run") for a in args)
    if sub in ("rm", "mv", "reset"):
        return not any(a in ("-n", "--dry-run", "-h") for a in args)
    if sub == "restore":
        return any(a in ("-S", "--staged") or (a.startswith("-") and not a.startswith("--") and "S" in a)
                   for a in args)
    if sub == "apply":
        return any(a in ("--cached", "--index") for a in args)
    return False


def _git(words: list[str]) -> tuple[str, list[str], str | None] | None:
    """(subcommand, its args, the -C path) for a git command, else None."""
    if not words or words[0].rsplit("/", 1)[-1] != "git":
        return None
    i, where = 1, None
    while i < len(words) and words[i].startswith("-"):
        w = words[i]
        if w in ("--help", "-h", "--version", "-v"):
            return None
        if w in GIT_VALUED:
            if w == "-C" and i + 1 < len(words):
                where = words[i + 1]
            i += 2
        else:
            i += 1
    return (words[i], words[i + 1:], where) if i < len(words) else None


def _inspect(cmd: str, state: dict, depth: int) -> None:
    """Walk the command in the order it runs, noting staging and commits into `state`."""
    if depth > 6:
        return
    for words in _simple_commands(lex(cmd)):
        for w in words:                               # $(...) runs before the command it's part of
            for sub in w.subs:
                _inspect(sub, state, depth + 1)
        words = _unwrap(words)
        if not words:
            continue
        base = words[0].rsplit("/", 1)[-1]
        if base in SHELLS:
            for k, w in enumerate(words[1:], 1):
                if w.startswith("-") and not w.startswith("--") and "c" in w[1:] and k + 1 < len(words):
                    _inspect(words[k + 1], state, depth + 1)
                    break
            continue
        if base == "eval":
            _inspect(" ".join(words[1:]), state, depth + 1)
            continue
        g = _git(words)
        if not g:
            continue
        sub, args, where = g
        if _changes_stage(sub, args):
            state["staged"] = True
        elif sub == "commit":
            state["commit"] = True
            state["stages"] = state["stages"] or state["staged"] or _commit_stages(args)
            state["where"] = state["where"] or where


QUOTED_HEREDOC = re.compile(r"""<<(-?)\s*(['"])([^'"\s]+)\2""")


def _strip_quoted_heredocs(cmd: str) -> str:
    """Drop the bodies of <<'EOF' heredocs first: they're plain text (commit messages) that may hold apostrophes
    or parentheses, even inside "$(cat <<'EOF' … )"."""
    out, lines, i = [], cmd.split("\n"), 0
    while i < len(lines):
        out.append(lines[i])
        opened = QUOTED_HEREDOC.findall(lines[i])
        i += 1
        for tabs, _q, delim in opened:
            while i < len(lines) and (lines[i].lstrip("\t") if tabs else lines[i]) != delim:
                i += 1
            if i < len(lines):
                out.append(lines[i])
                i += 1
    return "\n".join(out)


def inspect(cmd: str) -> dict:
    """What a shell command does with git: {"commit": bool, "stages": bool, "where": the -C path or None}.
    `stages` is true when the stage changes in the same command before (or as part of) a commit."""
    state = {"commit": False, "stages": False, "where": None, "staged": False}
    try:
        _inspect(_strip_quoted_heredocs(cmd), state, 0)
    except ValueError:                                # can't tokenize: search, and err on the side of review
        state["commit"] = bool(re.search(r"\bgit\b[^\n]*\bcommit\b", cmd))
        state["stages"] = state["commit"] and bool(re.search(r"\bgit\b[^\n]*\b(add|stage|rm|mv|reset)\b", cmd))
        state["where"] = None
    state.pop("staged")
    return state


PROMPT = "Review git diff --staged against CLAUDE.md. List bugs, rule breaks and missing tests. Do not edit files."


def main() -> None:
    data = json.load(sys.stdin)
    cmd = (data.get("tool_input") or {}).get("command") or ""
    found = inspect(cmd)
    if not found["commit"]:
        return
    if found["stages"]:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": (
                "This command changes the stage and commits in one go, so the Codex review (which runs before the "
                "command starts) would see the wrong stage. Run `git add` (or rm, reset) as its own command, then "
                "`git commit` without -a or paths.")}}))
        return
    where = found["where"] or data.get("cwd") or "."
    try:
        r = subprocess.run(["codex", "exec", "-s", "read-only", "-C", where, PROMPT],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=280)
        review = (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        review = f"Codex review didn't run: {e}"
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": ("Codex pre-commit review of the staged diff (advisory, commit NOT blocked):\n\n"
                              + review + "\n\nRead this now; if it flags a real bug, rule break, or missing test, "
                              "fix it before continuing.")}}))


if __name__ == "__main__":
    main()
