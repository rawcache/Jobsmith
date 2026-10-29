"""Sign in to Claude from the dashboard.

Runs `claude setup-token` in a pseudo-terminal. That opens Claude's normal sign-in page in your
browser; when you approve, the CLI prints a long-lived token that only works for model requests.
Jobsmith stores it locally (data/jobsmith.db) and passes it to `claude -p` as CLAUDE_CODE_OAUTH_TOKEN.
"""
from __future__ import annotations

import asyncio
import os
import re
import time

from . import db

CURSOR_FWD = re.compile(r"\x1b\[\d*C")
ANSI = re.compile(r"\x1b\[[0-9;?>]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[78=>]|\r")
TOKEN_DONE = re.compile(r"(sk-ant-oat[0-9A-Za-z_\-]{40,})(?=\s)")
URL = re.compile(r"(https://\S+/oauth/authorize\S+)")


class LoginFlow:
    def __init__(self):
        self.state = "idle"          # idle | waiting | done | error
        self.url: str | None = None
        self.message = ""
        self.output = ""
        self._proc: asyncio.subprocess.Process | None = None
        self._master: int | None = None
        self._task: asyncio.Task | None = None
        self.started = 0.0

    def snapshot(self) -> dict:
        return {"state": self.state, "url": self.url, "message": self.message}

    async def start(self, claude_path: str) -> dict:
        if self.state == "waiting" and self._proc and self._proc.returncode is None:
            return self.snapshot()
        from .llm import find_claude
        exe = find_claude(claude_path or "claude")
        if not exe:
            self.state, self.message = "error", "Claude Code isn't installed on this computer. Install it from code.claude.com, then try again."
            return self.snapshot()
        if os.name == "nt":
            self.state, self.message = "error", ("Signing in to Claude from Jobsmith isn't available on Windows. "
                                                 "Use an Anthropic API key or Ollama in Settings.")
            return self.snapshot()
        import fcntl
        import pty
        import struct
        import termios
        master, slave = pty.openpty()
        # A very wide terminal so the sign-in URL and token never wrap.
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 1000, 0, 0))
        env = dict(os.environ, BROWSER=os.environ.get("BROWSER", ""), TERM="xterm-256color", COLUMNS="200")
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        self._proc = await asyncio.create_subprocess_exec(
            exe, "setup-token", stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True)
        os.close(slave)
        self._master = master
        self.state, self.url, self.message, self.output = "waiting", None, "Opening Claude's sign-in page…", ""
        self.started = time.time()
        self._task = asyncio.create_task(self._pump())
        return self.snapshot()

    async def _pump(self) -> None:
        loop = asyncio.get_running_loop()
        assert self._master is not None
        try:
            while True:
                try:
                    chunk = await loop.run_in_executor(None, os.read, self._master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                text = CURSOR_FWD.sub(" ", chunk.decode(errors="replace"))
                self.output += ANSI.sub("", text)
                if not self.url:
                    m = URL.search(self.output)
                    if m:
                        self.url = m.group(1).rstrip(".,)")
                        self.message = "Approve Jobsmith in the browser tab that opened. If none opened, use the link below."
                # Only accept a complete token: it must be followed by whitespace (the CLI prints a newline
                # after it). Matching too early saves half a token, which Claude then rejects.
                m = TOKEN_DONE.search(self.output)
                if m:
                    self.message = "Checking the connection…"
                    await self._finish(m.group(1))
                    break
                if time.time() - self.started > 600:
                    self.state, self.message = "error", "Sign-in timed out. Try again."
                    break
        finally:
            await self._cleanup()
        if self.state == "waiting":
            tail = " ".join(self.output.split())[-300:]
            self.state = "error"
            self.message = f"Sign-in didn't finish. {tail}" if tail else "Sign-in didn't finish. Try again."

    async def _finish(self, token: str) -> None:
        """Save the token only after a real request with it succeeds."""
        from . import llm
        from .llm import ClaudeCLI, LLMError
        s = db.get_settings()
        cli = ClaudeCLI(s.get("claude_path") or "claude", "haiku", token)
        try:
            await cli._run('Reply with the JSON {"ok": true} and nothing else.', "ping", None, False, 90)
        except LLMError as e:
            self.state, self.message = "error", f"Signed in, but Claude rejected the connection ({e}). Try again."
            return
        db.set_settings({"claude_oauth_token": token, "llm_backend": "claude_cli"})
        llm.forget_checks()
        self.state, self.message = "done", "Connected to Claude."

    async def send_code(self, code: str) -> dict:
        """When the browser shows a code instead of redirecting back, it gets typed into the CLI."""
        if self._master is not None and self.state == "waiting":
            os.write(self._master, (code.strip() + "\r").encode())
            self.message = "Code sent, finishing sign-in…"
        return self.snapshot()

    async def cancel(self) -> dict:
        await self._cleanup()
        self.state, self.message = "idle", ""
        return self.snapshot()

    async def _cleanup(self) -> None:
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
        if self._master is not None:
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = None


flow = LoginFlow()


def disconnect() -> None:
    db.set_settings({"claude_oauth_token": ""})
    from . import llm
    llm.forget_checks()
