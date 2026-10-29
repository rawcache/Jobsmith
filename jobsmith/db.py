"""SQLite storage. Plain sqlite3 + small helpers; JSON columns are stored as TEXT."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterable

from .config import DB_PATH, DEFAULT_SETTINGS

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Uploaded source material (resume = the "holy grail", plus LinkedIn export, etc.)
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,              -- resume | linkedin | other
  filename TEXT NOT NULL,
  path TEXT NOT NULL,
  text TEXT NOT NULL DEFAULT '',
  is_primary INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);

-- Atomic, citable facts about the user. Every generated claim must cite these.
CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY,             -- f_xxxxxx
  category TEXT NOT NULL,          -- identity|education|experience|project|skill|award|leadership|link|other
  subject TEXT NOT NULL DEFAULT '',-- e.g. "Rooms To Go - ML Engineer Intern"
  text TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '', -- filename or "user"
  active INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL
);

-- Answer bank for standard / legally sensitive questions. Only the user sets these.
CREATE TABLE IF NOT EXISTS answers (
  key TEXT PRIMARY KEY,            -- canonical key, e.g. work_authorized_us
  label TEXT NOT NULL,
  value TEXT NOT NULL DEFAULT '',
  confirmed INTEGER NOT NULL DEFAULT 0, -- 0 = inferred, needs user confirmation
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,              -- simplify_github | url
  url TEXT NOT NULL UNIQUE,
  active INTEGER NOT NULL DEFAULT 1,
  last_synced REAL,
  last_count INTEGER
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  source_id INTEGER,
  external_id TEXT,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  ats TEXT NOT NULL DEFAULT 'unknown',
  locations TEXT NOT NULL DEFAULT '[]',
  terms TEXT NOT NULL DEFAULT '[]',
  category TEXT NOT NULL DEFAULT '',
  sponsorship TEXT NOT NULL DEFAULT '',
  degrees TEXT NOT NULL DEFAULT '[]',
  date_posted REAL,
  active INTEGER NOT NULL DEFAULT 1,
  description TEXT NOT NULL DEFAULT '',
  questions TEXT NOT NULL DEFAULT '[]',  -- normalized form fields
  research TEXT NOT NULL DEFAULT '{}',
  fit_score REAL,
  fit_reasons TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'new',     -- new|left_out|skipped|fetched|drafted|filling|filled|submitted|error
  verdict TEXT,                           -- job-level green/red from the user
  verdict_note TEXT,
  error TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS jobs_company ON jobs(company);

-- One row per form field per job: what Jobsmith proposes and what the user decided.
CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  field TEXT NOT NULL,             -- form field name (e.g. question_12345)
  label TEXT NOT NULL,
  qtype TEXT NOT NULL,             -- text|textarea|select|multiselect|file|checkbox
  required INTEGER NOT NULL DEFAULT 0,
  options TEXT NOT NULL DEFAULT '[]',
  kind TEXT NOT NULL,              -- standard|answer_bank|generated|file
  canon TEXT,                      -- canonical key for standard/answer-bank questions
  answer TEXT NOT NULL DEFAULT '',
  fact_ids TEXT NOT NULL DEFAULT '[]',
  rationale TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0,
  issues TEXT NOT NULL DEFAULT '[]', -- validator findings
  verdict TEXT,                    -- green|red|null
  note TEXT,                       -- user's reason (esp. for red)
  final_answer TEXT,               -- user's edited answer, if any
  updated_at REAL NOT NULL,
  UNIQUE(job_id, field)
);

-- AI usage per call, so you can see what each application costs.
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,                     -- NULL for profile parsing, commands, etc.
  purpose TEXT NOT NULL,           -- research|answers|command|profile|other
  backend TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cached_tokens INTEGER NOT NULL DEFAULT 0,
  web_searches INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL,                   -- what the provider reported (Claude Code reports an API-equivalent figure)
  seconds REAL,
  at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS usage_job ON usage(job_id);

-- Background work: drafting, filling, submitting.
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  kind TEXT NOT NULL,              -- fetch|research|draft|fill|submit
  status TEXT NOT NULL,            -- queued|running|done|error|waiting_user
  log TEXT NOT NULL DEFAULT '',
  screenshot TEXT,
  snapshot TEXT,
  started_at REAL,
  finished_at REAL
);

-- Autopilot's first real submission, and its first on each job site, waits for you to approve it. One row per
-- application it held for that; approved_at is set when you approved it, and from then on that site is trusted.
CREATE TABLE IF NOT EXISTS first_runs (
  job_id TEXT PRIMARY KEY,
  site TEXT NOT NULL,              -- greenhouse | lever | … | the host name for any other site
  asked_at REAL NOT NULL,
  approved_at REAL,
  answers TEXT,                    -- the answers you approved when its tab had closed: sent only if a refill matches
  files TEXT                       -- the resume and transcript (by content) when it was filled and held
);

-- Limits a company states in its postings ("up to 5 applications during any rolling 30-day period", "may not
-- reapply to the same role within 90 days of a rejection"). Autopilot keeps to them as well as to your own caps.
CREATE TABLE IF NOT EXISTS company_limits (
  company TEXT PRIMARY KEY,        -- lower(trim(company)), the way the caps match companies
  name TEXT NOT NULL,              -- as the posting names it
  windows TEXT NOT NULL DEFAULT '[]',        -- [[per, days], …]: at most `per` applications in `days` days
  reapply_days INTEGER,            -- not to the same role within this many days of a rejection
  while_active INTEGER NOT NULL DEFAULT 0,   -- not to the same role while an application to it is open
  lines TEXT NOT NULL DEFAULT '[]',          -- the posting's own sentences
  job_id TEXT,                     -- the posting they were read from
  updated_at REAL NOT NULL
);
"""

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        # company_limits is read again from saved postings, so an early copy with a single limit is just rebuilt
        lim = {r[1] for r in c.execute("PRAGMA table_info(company_limits)").fetchall()}
        if lim and "windows" not in lim:
            c.execute("DROP TABLE company_limits")
        c.executescript(SCHEMA)
        cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)").fetchall()}
        for col in ("referral_name", "referral_url", "hold_reason", "outcome"):
            if col not in cols:
                c.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
        if "eligibility" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN eligibility TEXT NOT NULL DEFAULT '{}'")
        if "traps" not in cols:        # lines in the posting aimed at AI, found when it was fetched
            c.execute("ALTER TABLE jobs ADD COLUMN traps TEXT NOT NULL DEFAULT '[]'")
        if "original" not in cols:     # the posting as written, hidden lines included, kept only when it has traps
            c.execute("ALTER TABLE jobs ADD COLUMN original TEXT NOT NULL DEFAULT ''")
        if "left_out" not in cols:     # why a job board's role was left out (senior|experience|pay), or 'waived'
            c.execute("ALTER TABLE jobs ADD COLUMN left_out TEXT")
        fcols = {r[1] for r in c.execute("PRAGMA table_info(first_runs)").fetchall()}
        for col in ("answers", "files"):
            if col not in fcols:
                c.execute(f"ALTER TABLE first_runs ADD COLUMN {col} TEXT")
        dcols = {r[1] for r in c.execute("PRAGMA table_info(drafts)").fetchall()}
        if "model" not in dcols:
            c.execute("ALTER TABLE drafts ADD COLUMN model TEXT")
        _conn = c
        _rehome_paths(c)
    return _conn


def _rehome(p: str | None) -> str | None:
    """A file saved under an old data folder (the project folder was moved or renamed): find it in today's."""
    if not p:
        return None
    import re
    from pathlib import Path, PureWindowsPath
    from .config import DATA_DIR
    path = Path(p)
    if path.exists() or not (path.is_absolute() or p.startswith("/") or PureWindowsPath(p).is_absolute()):
        return None
    parts = [s for s in re.split(r"[\\/]+", p) if s]    # saved on any OS: split on / and \
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] in ("uploads", "runs", "attach", "documents"):
            cand = DATA_DIR.joinpath(*parts[i:])
            if cand.exists():
                return str(cand)
    return None


def _rehome_paths(c: sqlite3.Connection) -> None:
    for table, col in (("documents", "path"), ("runs", "screenshot"), ("runs", "snapshot")):
        try:
            rows = c.execute(f"SELECT id, {col} FROM {table} WHERE {col} IS NOT NULL AND {col} != ''").fetchall()
        except sqlite3.Error:
            continue
        for r in rows:
            new = _rehome(r[1])
            if new:
                c.execute(f"UPDATE {table} SET {col}=? WHERE id=?", (new, r[0]))


def reset_for_tests(path) -> None:
    """Point the module at a fresh database (used by tests)."""
    global _conn
    import jobsmith.config as cfg
    cfg.DB_PATH = path
    globals()["DB_PATH"] = path
    _conn = None


@contextmanager
def tx():
    c = conn()
    with _lock:
        c.execute("BEGIN")
        try:
            yield c
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise


def q(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, tuple(params)).fetchall()]


def q1(sql: str, params: Iterable[Any] = ()) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def x(sql: str, params: Iterable[Any] = ()) -> int:
    with _lock:
        cur = conn().execute(sql, tuple(params))
        return cur.lastrowid


def now() -> float:
    return time.time()


# ---------------------------------------------------------------- JSON helpers
JSON_COLS = {
    "locations", "terms", "degrees", "questions", "research", "fit_reasons",
    "options", "fact_ids", "issues", "eligibility", "traps",
}


def decode(row: dict | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for k in JSON_COLS & out.keys():
        v = out[k]
        if isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except json.JSONDecodeError:
                pass
    return out


def enc(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


# ---------------------------------------------------------------- settings
def get_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    for r in q("SELECT key, value FROM settings"):
        try:
            s[r["key"]] = json.loads(r["value"])
        except json.JSONDecodeError:
            s[r["key"]] = r["value"]
    return s


def get_setting(key: str):
    return get_settings().get(key)


def set_settings(values: dict) -> dict:
    for k, v in values.items():
        if k not in DEFAULT_SETTINGS:
            continue
        x("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
          (k, json.dumps(v)))
    return get_settings()
