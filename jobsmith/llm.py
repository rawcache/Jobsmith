"""Swappable LLM backends.

- ClaudeCLI: shells out to your local `claude -p` (Claude Code), so a personal copy
  runs on your own Claude subscription. Per Anthropic's terms, a version distributed
  to other people must use API keys (AnthropicAPI) rather than claude.ai login.
- AnthropicAPI: bring-your-own API key.
- NoLLM: raises; callers fall back to deterministic behaviour.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import os
import re
import shutil
import time

from .config import LLM_WORKDIR
from .db import get_settings


class LLMError(RuntimeError):
    pass


class QuotaError(LLMError):
    """A free tier's limit ran out. Jobsmith falls back to smith when it's installed."""


# Which application (and what for) the current AI call belongs to; set by callers with `usage_for`.
_usage_ctx: contextvars.ContextVar[tuple[str | None, str]] = contextvars.ContextVar("usage_ctx", default=(None, "other"))


def usage_for(job_id: str | None, purpose: str):
    """Tag AI calls made in the current task: `with usage_for(job_id, "research"): ...`"""
    class _Ctx:
        def __enter__(self):
            self.tok = _usage_ctx.set((job_id, purpose))

        def __exit__(self, *a):
            _usage_ctx.reset(self.tok)
    return _Ctx()


def _record_usage(b: "Backend", seconds: float) -> None:
    u = getattr(b, "last_usage", None)
    if not u:
        return
    job_id, purpose = _usage_ctx.get()
    try:
        from . import db
        db.x("""INSERT INTO usage(job_id, purpose, backend, model, input_tokens, output_tokens, cached_tokens,
                web_searches, cost_usd, seconds, at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
             (job_id, purpose, b.name, getattr(b, "model", ""), int(u.get("input", 0)), int(u.get("output", 0)),
              int(u.get("cached", 0)), int(u.get("searches", 0)), u.get("cost"), round(seconds, 1), time.time()))
    except Exception:
        pass


def extract_json(text: str):
    """Pull the first JSON object/array out of a model response."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"Model did not return JSON: {text[:300]}")


def find_claude(path: str = "claude") -> str | None:
    """`claude` may not be on the PATH Jobsmith was started with; check the usual install spots."""
    found = shutil.which(path or "claude")
    if found:
        return found
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", "")
    for c in (f"{home}/.local/bin/claude", f"{home}/.claude/local/claude", "/opt/homebrew/bin/claude",
              "/usr/local/bin/claude", os.path.join(appdata, "npm", "claude.cmd") if appdata else ""):
        if not c:
            continue
        if os.path.exists(c):
            return c
    return None


class Backend:
    name = "base"

    async def complete_json(self, system: str, prompt: str, schema: dict | None = None,
                            web: bool = False, timeout: float = 240) -> dict | list:
        raise NotImplementedError

    async def available(self) -> tuple[bool, str]:
        return False, "not configured"


class ClaudeCLI(Backend):
    name = "claude_cli"

    def __init__(self, path: str = "claude", model: str = "sonnet", token: str = ""):
        self.path = path
        self.model = model
        self.token = token

    def _env(self) -> dict:
        env = dict(os.environ)
        if self.token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self.token
        return env

    _probe_cache: tuple[float, bool, str] | None = None

    async def available(self) -> tuple[bool, str]:
        exe = find_claude(self.path)
        if not exe:
            return False, "Claude Code isn't installed on this Mac."
        if self.token:
            return await self._probe()
        # Fast path: `claude auth status` (newer CLIs). Exit code 0 = logged in.
        try:
            proc = await asyncio.create_subprocess_exec(
                exe, "auth", "status", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _ = await asyncio.wait_for(proc.communicate(), 20)
            if proc.returncode == 0:
                try:
                    return True, f"logged in ({json.loads(out.decode() or '{}').get('authMethod', 'ok')})"
                except json.JSONDecodeError:
                    return True, "logged in"
        except Exception:
            pass
        return await self._probe()

    async def _probe(self) -> tuple[bool, str]:
        # A tiny real request, cached for 10 minutes so the dashboard doesn't burn usage.
        now = time.time()
        if ClaudeCLI._probe_cache and now - ClaudeCLI._probe_cache[0] < 600:
            return ClaudeCLI._probe_cache[1], ClaudeCLI._probe_cache[2]
        try:
            await self._run("Reply with the JSON {\"ok\": true} and nothing else.", "ping", None, False, 60)
            result = (True, "connected")
        except LLMError as e:
            msg = str(e)
            result = (False, "Not connected to Claude yet." if re.search(r"log ?in|auth|credential|token", msg, re.I)
                      else f"Claude didn't answer: {msg[:200]}")
        ClaudeCLI._probe_cache = (now, *result)
        return result

    async def complete_json(self, system, prompt, schema=None, web=False, timeout=240):
        try:
            return await self._run(system, prompt, schema, web, timeout)
        except LLMError:
            if not schema:
                raise
            # Older CLIs may not support --json-schema; ask for JSON in the prompt instead.
            hint = "\n\nReturn ONLY a JSON value matching this schema:\n" + json.dumps(schema)
            return await self._run(system, prompt + hint, None, web, timeout)

    async def _run(self, system, prompt, schema, web, timeout):
        exe = find_claude(self.path)
        if not exe:
            raise LLMError("Claude Code CLI not found")
        args = [exe, "-p", "--output-format", "json", "--model", self.model,
                "--no-session-persistence", "--system-prompt", system,
                "--disallowedTools", "mcp__*"]
        if web:
            # Research mode: allow only web search/fetch, nothing that touches your machine.
            # Search only (no full-page fetches) and a turn cap keep research to a sensible token budget.
            args += ["--tools", "WebSearch", "--allowedTools", "WebSearch", "--max-turns", "6"]
        else:
            args += ["--tools", "", "--max-turns", "3"]
        if schema:
            args += ["--json-schema", json.dumps(schema)]
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(LLM_WORKDIR), env=self._env(), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise LLMError("Claude Code timed out")
        raw = out.decode(errors="replace")
        try:
            env = json.loads(raw)
        except json.JSONDecodeError:
            raise LLMError(f"Unexpected CLI output: {raw[:300]} {err.decode()[:300]}")
        u = env.get("usage") or {}
        self.last_usage = {
            "input": (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0),
            "cached": u.get("cache_read_input_tokens") or 0,
            "output": u.get("output_tokens") or 0,
            "searches": (u.get("server_tool_use") or {}).get("web_search_requests") or 0,
            "cost": env.get("total_cost_usd"),
        }
        if env.get("is_error"):
            detail = str(env.get("result") or env.get("subtype"))
            if re.search(r"not logged in|/login|invalid api key|oauth", detail, re.I):
                raise LLMError("Claude isn't connected. Use Connect Claude in Jobsmith.")
            raise LLMError(f"Claude error: {detail}")
        if env.get("structured_output") is not None:
            return env["structured_output"]
        return extract_json(env.get("result", ""))


def _schema_hint(prompt: str, schema: dict | None) -> str:
    if not schema:
        return prompt
    return prompt + "\n\nReturn ONLY a JSON value matching this schema, with no prose around it:\n" + json.dumps(schema)


class AnthropicAPI(Backend):
    """Claude via an Anthropic API key (console.anthropic.com), billed per token."""
    name = "anthropic_api"
    MODEL_ALIASES = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5", "haiku": "claude-haiku-4-5-20251001"}

    def __init__(self, key: str, model: str = "sonnet"):
        self.key = key
        self.model = self.MODEL_ALIASES.get(model, model)

    async def available(self):
        if not self.key:
            return False, "Add your Anthropic API key in Settings."
        try:
            await self.complete_json('Reply with the JSON {"ok": true}.', "ping", timeout=60)
            return True, f"connected ({self.model})"
        except LLMError as e:
            return False, str(e)[:200]

    async def complete_json(self, system, prompt, schema=None, web=False, timeout=240):
        import httpx
        body = {"model": self.model, "max_tokens": 4096, "system": system,
                "messages": [{"role": "user", "content": _schema_hint(prompt, schema)}]}
        if web:
            body["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}]
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post("https://api.anthropic.com/v1/messages", json=body, headers={
                "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        if r.status_code != 200:
            raise LLMError(f"Anthropic API {r.status_code}: {r.text[:200]}")
        u = r.json().get("usage") or {}
        self.last_usage = {
            "input": (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0),
            "cached": u.get("cache_read_input_tokens") or 0, "output": u.get("output_tokens") or 0,
            "searches": (u.get("server_tool_use") or {}).get("web_search_requests") or 0}
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        return extract_json(text)


class OpenAIAPI(Backend):
    """ChatGPT models via an OpenAI API key (platform.openai.com), billed per token.
    A ChatGPT Plus/Pro subscription does not include API usage; the key is billed separately."""
    name = "openai_api"

    def __init__(self, key: str, model: str = "gpt-5.5"):
        self.key = key
        self.model = model or "gpt-5.5"

    async def available(self):
        if not self.key:
            return False, "Add your OpenAI API key in Settings."
        try:
            await self.complete_json('Reply with the JSON {"ok": true}.', "ping", timeout=60)
            return True, f"connected ({self.model})"
        except LLMError as e:
            return False, str(e)[:200]

    async def complete_json(self, system, prompt, schema=None, web=False, timeout=240):
        import httpx
        body = {"model": self.model, "instructions": system, "input": _schema_hint(prompt, schema)}
        if web:
            body["tools"] = [{"type": "web_search"}]
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post("https://api.openai.com/v1/responses", json=body,
                             headers={"Authorization": f"Bearer {self.key}"})
        if r.status_code != 200:
            raise LLMError(f"OpenAI API {r.status_code}: {r.text[:200]}")
        data = r.json()
        u = data.get("usage") or {}
        cached = (u.get("input_tokens_details") or {}).get("cached_tokens") or 0
        self.last_usage = {"input": (u.get("input_tokens") or 0) - cached, "cached": cached,
                           "output": u.get("output_tokens") or 0,
                           "searches": sum(1 for it in data.get("output", []) if it.get("type") == "web_search_call")}
        text = data.get("output_text") or "".join(
            part.get("text", "") for item in data.get("output", []) if item.get("type") == "message"
            for part in item.get("content", []) if part.get("type") in ("output_text", "text"))
        return extract_json(text)


class GeminiAPI(Backend):
    """Gemini via a Google AI Studio API key (aistudio.google.com). Research uses Google Search grounding."""
    name = "gemini_api"

    def __init__(self, key: str, model: str = "gemini-flash-latest"):
        self.key = key
        self.model = model or "gemini-flash-latest"

    async def available(self):
        if not self.key:
            return False, "Add your Gemini API key in Settings."
        try:
            await self.complete_json('Reply with the JSON {"ok": true}.', "ping", timeout=60)
            return True, f"connected ({self.model})"
        except LLMError as e:
            return False, str(e)[:200]

    async def complete_json(self, system, prompt, schema=None, web=False, timeout=240):
        import httpx
        body: dict = {"system_instruction": {"parts": [{"text": system}]},
                      "contents": [{"role": "user", "parts": [{"text": _schema_hint(prompt, schema)}]}],
                      "generationConfig": {"temperature": 0.4}}
        if web:
            body["tools"] = [{"google_search": {}}]   # can't be combined with JSON mode
        else:
            body["generationConfig"]["responseMimeType"] = "application/json"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        for attempt in range(4):
            try:
                async with httpx.AsyncClient(timeout=timeout) as c:
                    r = await c.post(url, json=body, headers={"x-goog-api-key": self.key})
            except httpx.HTTPError as e:
                raise LLMError(f"Couldn't reach Gemini: {e.__class__.__name__}")
            if r.status_code not in (429, 500, 503) or attempt == 3:
                break
            if r.status_code == 429 and "PerDay" in r.text:
                break                                     # waiting won't help today
            m = re.search(r'"retryDelay":\s*"(\d+)', r.text)
            await asyncio.sleep(min(60, int(m.group(1)) + 1) if m else 2 ** attempt * 3)
        if r.status_code == 429:
            daily = "PerDay" in r.text
            _quota_hit["gemini_api"] = gemini_reset() if daily else time.time() + 60
            if daily:
                _learn_limit(gemini_used_today())
            raise QuotaError("Gemini's free tier limit is used up for now"
                             + (f" (daily limit; it resets at {time.strftime('%I:%M %p', time.localtime(gemini_reset())).lstrip('0')})." if daily else "."))
        if r.status_code in (400, 403) and ("API_KEY_INVALID" in r.text or "API key not valid" in r.text):
            raise LLMError("That Gemini key isn't valid. Copy it again from aistudio.google.com/apikey.")
        if r.status_code != 200:
            raise LLMError(f"Gemini API {r.status_code}: {r.text[:200]}")
        data = r.json()
        u = data.get("usageMetadata") or {}
        cached = u.get("cachedContentTokenCount") or 0
        self.last_usage = {"input": (u.get("promptTokenCount") or 0) - cached, "cached": cached,
                           "output": (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0),
                           "searches": len(((data.get("candidates") or [{}])[0].get("groundingMetadata") or {})
                                           .get("webSearchQueries") or [])}
        parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        return extract_json("".join(p.get("text", "") for p in parts))


OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = "http://" + OLLAMA_URL
# Good small models first. Any installed model works; these are just the preferred picks.
OLLAMA_PREFERRED = ("qwen3", "qwen2.5", "llama3.3", "llama3.1", "gemma3", "mistral-small", "phi4", "mistral", "llama3")


_models_cache: tuple[float, list[str]] = (0.0, [])


async def ollama_models(timeout: float = 2.0) -> list[str]:
    """Models installed in a local Ollama, or [] when Ollama isn't running. Cached for a few seconds:
    the dashboard asks often, and each answer is a request to Ollama."""
    import httpx
    global _models_cache
    if time.time() - _models_cache[0] < 5:
        return _models_cache[1]
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
        models = [m["name"] for m in r.json().get("models", [])] if r.status_code == 200 else []
    except Exception:
        models = []
    _models_cache = (time.time(), models)
    return models


# --------------------------------------------------------------------------- free-tier quota
# Google resets Gemini's free daily limits at midnight Pacific time. It doesn't say how many requests are left,
# so Jobsmith counts its own, and remembers the count at which the limit last ran out.
_quota_hit: dict[str, float] = {}      # backend -> time until which it's out of quota


def gemini_reset(now: float | None = None) -> float:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    pt = ZoneInfo("America/Los_Angeles")
    d = datetime.fromtimestamp(now or time.time(), pt)
    nxt = (d + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.timestamp()


def gemini_used_today() -> int:
    from . import db
    start = gemini_reset() - 86400
    return (db.q1("SELECT COUNT(*) n FROM usage WHERE backend='gemini_api' AND at>=?", (start,)) or {"n": 0})["n"]


def _learn_limit(n: int) -> None:
    from . import db
    if n >= 5:
        db.set_settings({"gemini_daily_seen_limit": n})


def _local_ok() -> bool:
    """smith only stands in for a cloud AI when the power settings allow it (by default: plugged in)."""
    from . import power
    return power.local_ai_allowed()


def gemini_limited() -> bool:
    return _quota_hit.get("gemini_api", 0) > time.time()


def quota_status() -> dict | None:
    """For the bar in the dashboard's top right: today's Gemini use and when it resets."""
    s = get_settings()
    kinds = {s.get("llm_backend"), s.get("research_backend")}
    if s.get("llm_backend") == "auto" and _auto_cache:
        kinds.add(_auto_cache[1])
    if "gemini_api" not in kinds:
        return None
    used = gemini_used_today()
    limit = int(s.get("gemini_daily_seen_limit") or 0) or None
    return {"name": "Gemini", "used": used, "limit": limit, "resets_at": gemini_reset(), "limited": gemini_limited(),
            "fallback": "smith" if _models_cache[1] and _local_ok() else None}


async def recheck_gemini() -> dict:
    """'Check again': forget the remembered limit and ask Gemini directly (one tiny request)."""
    s = get_settings()
    key = _key(s, "gemini_api_key", "GEMINI_API_KEY", "GOOGLE_API_KEY")
    if not key:
        return {"ok": False, "message": "Add your Gemini API key in Settings first.", "quota": quota_status()}
    _quota_hit.pop("gemini_api", None)
    for k in [k for k in _avail_cache if k[0] == "gemini_api"]:
        _avail_cache.pop(k, None)
    ok, msg = await GeminiAPI(key, s.get("gemini_model") or "gemini-flash-latest").available()
    if ok:
        return {"ok": True, "message": "Gemini is back. Autopilot will use it again.", "quota": quota_status()}
    if gemini_limited():
        at = time.strftime("%I:%M %p", time.localtime(gemini_reset())).lstrip("0")
        return {"ok": False, "message": f"Still at today's free limit. Google resets it at midnight Pacific ({at} your time).",
                "quota": quota_status()}
    return {"ok": False, "message": msg, "quota": quota_status()}


def pick_ollama_model(models: list[str]) -> str:
    for pref in OLLAMA_PREFERRED:
        hit = next((m for m in models if m.split(":")[0] == pref or m.startswith(pref)), None)
        if hit:
            return hit
    return models[0] if models else ""


def _smith_progress() -> str:
    """While smith is still downloading, say so instead of 'no AI'."""
    from . import smith
    st = smith.STATE
    if st.get("phase") in ("starting", "installing", "downloading"):
        pct = f" ({st['progress'] * 100:.0f}%)" if st.get("progress") else ""
        return f"smith is getting ready{pct}"
    return ""


class OllamaLocal(Backend):
    """smith: a model running on this computer (or a Mac mini on your network) through Ollama. Free and private.
    smith.setup() installs and downloads everything. It can't search the web, so company research
    falls back to what the posting itself says."""
    name = "ollama"

    def __init__(self, model: str = ""):
        self.model = model

    async def _model(self) -> str:
        if not self.model:
            self.model = pick_ollama_model(await ollama_models())
        return self.model

    async def available(self):
        if busy := _smith_progress():
            return False, busy
        models = await ollama_models()
        if not models:
            return False, "smith isn't running. Set it up in Settings, or run: jobsmith smith"
        m = self.model or pick_ollama_model(models)
        if self.model and self.model not in models:
            return False, f"smith's model ({self.model}) isn't downloaded yet. Set it up in Settings, or run: jobsmith smith"
        return True, f"smith is running {m} on this computer"

    async def complete_json(self, system, prompt, schema=None, web=False, timeout=600):
        import httpx
        model = await self._model()
        if not model:
            raise LLMError("smith isn't set up yet. Run: jobsmith smith")
        if web:
            prompt = ("You can't browse the web here. Use only the text below and say so where you'd need more.\n\n"
                      + prompt)
        body = {"model": model, "stream": False, "format": schema or "json",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": _schema_hint(prompt, schema)}],
                "options": {"temperature": 0.3, "num_ctx": 8192}, "keep_alive": "3m"}
        if model.startswith(("qwen3", "deepseek-r1")) and "instruct" not in model:
            body["think"] = False     # thinking models: answer directly, much faster
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{OLLAMA_URL}/api/chat", json=body)
        except httpx.HTTPError as e:
            raise LLMError(f"Couldn't reach Ollama at {OLLAMA_URL}: {e.__class__.__name__}")
        if r.status_code != 200:
            raise LLMError(f"Ollama {r.status_code}: {r.text[:200]}")
        data = r.json()
        self.last_usage = {"input": data.get("prompt_eval_count") or 0, "output": data.get("eval_count") or 0,
                           "cached": 0, "searches": 0, "cost": 0.0}
        return extract_json((data.get("message") or {}).get("content", ""))


class NoLLM(Backend):
    name = "none"

    async def available(self):
        if busy := _smith_progress():
            return False, busy
        return False, "No AI yet. Run `jobsmith smith` for a free one on this computer, or add an Anthropic, OpenAI or Gemini key in Settings."

    async def complete_json(self, *a, **k):
        raise LLMError("AI backend disabled")


_override: Backend | None = None  # tests inject a fake backend here


def set_backend_override(b: Backend | None) -> None:
    global _override
    _override = b


def _key(s: dict, setting: str, *envs: str) -> str:
    """A key from Settings, else from the environment (so `export OPENAI_API_KEY=...` just works)."""
    return (s.get(setting) or "").strip() or next((os.environ[e] for e in envs if os.environ.get(e)), "")


def detected(s: dict | None = None, ollama: list[str] | None = None) -> list[dict]:
    """Every AI Jobsmith can use right now without asking, best first. `ollama` is the installed model list."""
    s = s if s is not None else get_settings()
    out = []
    if _key(s, "anthropic_api_key", "ANTHROPIC_API_KEY"):
        out.append({"kind": "anthropic_api", "label": "Claude (Anthropic API key)"})
    if _key(s, "openai_api_key", "OPENAI_API_KEY"):
        out.append({"kind": "openai_api", "label": "ChatGPT (OpenAI API key)"})
    if _key(s, "gemini_api_key", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        out.append({"kind": "gemini_api", "label": "Gemini (Google AI Studio key)"})
    if ollama:
        out.append({"kind": "ollama", "label": f"smith, on this computer ({pick_ollama_model(ollama)})", "models": ollama})
    if find_claude(s.get("claude_path") or "claude") and s.get("claude_oauth_token"):
        out.append({"kind": "claude_cli", "label": "Claude Code login (personal use)"})
    return out


_auto_cache: tuple[float, str] | None = None


def resolve_auto(s: dict) -> str:
    """'auto' means: the first AI that's available. Cached for a minute so it isn't re-probed per call."""
    global _auto_cache
    if _auto_cache and time.time() - _auto_cache[0] < 60:
        return _auto_cache[1]
    import httpx
    models = []
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=1.0)
        models = [m["name"] for m in r.json().get("models", [])] if r.status_code == 200 else []
    except Exception:
        pass
    found = detected(s, models)
    kind = found[0]["kind"] if found else "none"
    _auto_cache = (time.time(), kind)
    return kind


def make_backend(kind: str, s: dict) -> Backend:
    if kind == "auto":
        kind = resolve_auto(s)
    if kind == "gemini_api" and gemini_limited() and _models_cache[1] and _local_ok():
        return OllamaLocal(s.get("ollama_model") or "")      # Gemini's free day is used up: smith until it resets
    if kind == "gemini_api":
        return GeminiAPI(_key(s, "gemini_api_key", "GEMINI_API_KEY", "GOOGLE_API_KEY"), s.get("gemini_model") or "gemini-flash-latest")
    if kind == "ollama":
        return OllamaLocal(s.get("ollama_model") or "")
    if kind == "claude_cli":
        return ClaudeCLI(s.get("claude_path") or "claude", s.get("llm_model") or "sonnet",
                         s.get("claude_oauth_token") or "")
    if kind == "anthropic_api":
        return AnthropicAPI(_key(s, "anthropic_api_key", "ANTHROPIC_API_KEY"), s.get("llm_model") or "sonnet")
    if kind == "openai_api":
        return OpenAIAPI(_key(s, "openai_api_key", "OPENAI_API_KEY"), s.get("openai_model") or "gpt-5.5")
    return NoLLM()


def backend(role: str = "write") -> Backend:
    """role: 'write' (answers, cover letters, profile parsing) or 'research' (company research, job discovery)."""
    if _override is not None:
        return _override
    s = get_settings()
    kind = s.get("llm_backend")
    if role == "research" and s.get("research_backend") not in (None, "", "same"):
        kind = s["research_backend"]
    return make_backend(kind, s)


def label(b: Backend) -> str:
    """Human name for what produced an answer: shown on drafts, research and the sidebar."""
    if isinstance(b, ClaudeCLI):
        return f"Claude {b.model.capitalize()} (subscription)"
    if isinstance(b, AnthropicAPI):
        tier = next((k for k, v in AnthropicAPI.MODEL_ALIASES.items() if v == b.model), b.model)
        return f"Claude {tier.capitalize()} (API)"
    if isinstance(b, OpenAIAPI):
        return f"ChatGPT {b.model} (API)"
    if isinstance(b, GeminiAPI):
        return f"Gemini {b.model.replace('gemini-', '')} (API)"
    if isinstance(b, OllamaLocal):
        return f"smith ({b.model})" if b.model else "smith"
    if isinstance(b, NoLLM):
        return "No AI connected"
    return getattr(b, "name", "none")


_sem: asyncio.Semaphore | None = None
_local_sem: asyncio.Semaphore | None = None


async def complete_json(system: str, prompt: str, schema: dict | None = None, web: bool = False,
                        role: str | None = None):
    """Concurrency-limited entry point used by the rest of the app.
    Web-enabled calls default to the research backend. Every prompt has lines aimed at AI (planted in postings)
    removed, and every system prompt says page text is data, not instructions."""
    from . import traps
    system, prompt = f"{system}\n\n{traps.DATA_RULE}", traps.redact(prompt)
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(int(get_settings().get("llm_concurrency", 3)))
    b = backend(role or ("research" if web else "write"))
    if isinstance(b, OllamaLocal):
        # One local generation at a time: running several at once on a laptop is slower overall, and hot.
        global _local_sem
        _local_sem = _local_sem or asyncio.Semaphore(1)
        async with _local_sem:
            t0 = time.time()
            try:
                return await b.complete_json(system, prompt, schema=schema, web=web)
            finally:
                _record_usage(b, time.time() - t0)
    async with _sem:
        t0 = time.time()
        try:
            return await b.complete_json(system, prompt, schema=schema, web=web)
        except QuotaError:
            if isinstance(b, OllamaLocal) or not _local_ok() or not await ollama_models():
                raise
            b = OllamaLocal(get_settings().get("ollama_model") or "")   # out of free quota: smith takes over
            t0 = time.time()
            return await b.complete_json(system, prompt, schema=schema, web=web)
        finally:
            _record_usage(b, time.time() - t0)


_avail_cache: dict[tuple, tuple[float, bool, str]] = {}


async def available_cached(ttl: float = 600, role: str = "write") -> tuple[bool, str]:
    """Status checks for API backends make a real (tiny) request, so cache them."""
    b = backend(role)
    if isinstance(b, (ClaudeCLI, OllamaLocal, NoLLM)):
        return await b.available()
    key = (b.name, getattr(b, "key", "")[-8:], getattr(b, "model", ""))
    hit = _avail_cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1], hit[2]
    ok, msg = await b.available()
    _avail_cache[key] = (time.time(), ok, msg)
    return ok, msg
