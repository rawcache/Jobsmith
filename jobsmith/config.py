"""Paths and default settings. Everything lives under ./data (git-ignored)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = Path(__file__).resolve().parent


def _default_data_dir() -> Path:
    """A source checkout keeps its data in ./data; an installed copy uses ~/.jobsmith (%APPDATA%\\jobsmith on Windows)."""
    if (ROOT / "pyproject.toml").exists() and (ROOT / "jobsmith").is_dir():
        return ROOT / "data"
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "jobsmith"
    return Path.home() / ".jobsmith"


def _migrate_from_wyzard(data: Path) -> None:
    """Jobsmith was called wyzard. Carry an existing install's data over, once."""
    old = data.parent / data.name.replace("jobsmith", "wyzard") if data.name != "data" else None
    if old and old.is_dir() and not data.exists():
        try:
            old.rename(data)
        except OSError:
            pass
    if (data / "wyzard.db").exists() and not (data / "jobsmith.db").exists():
        for suffix in ("", "-wal", "-shm"):
            src = data / f"wyzard.db{suffix}"
            if src.exists():
                src.rename(data / f"jobsmith.db{suffix}")


# Demo mode (`jobsmith demo`): a throwaway copy with a made-up person and jobs. Nothing real is ever opened,
# synced, read or sent from it, so it's safe for trying changes to the dashboard or the setup flow.
DEMO = os.environ.get("JOBSMITH_DEMO") == "1"
DATA_DIR = Path(os.environ.get("JOBSMITH_DATA") or os.environ.get("WYZARD_DATA") or _default_data_dir()).resolve()
_migrate_from_wyzard(DATA_DIR)
DB_PATH = DATA_DIR / "jobsmith.db"
UPLOADS_DIR = DATA_DIR / "uploads"
RUNS_DIR = DATA_DIR / "runs"            # screenshots + snapshots of what was submitted
BROWSER_PROFILE = DATA_DIR / "browser-profile"
LLM_WORKDIR = DATA_DIR / "llm"          # cwd for `claude -p` so no project CLAUDE.md leaks in
EXTENSION_DIR = PKG / "extension" if (PKG / "extension" / "manifest.json").exists() else ROOT / "extension"
WEB_DIST = PKG / "web_dist" if (PKG / "web_dist" / "index.html").exists() else ROOT / "web" / "dist"

def _build() -> str:
    """Changes whenever the code does, so the terminal can tell it's talking to an engine from an older version."""
    import hashlib
    h = hashlib.sha1()
    for f in sorted(PKG.rglob("*.py")):
        st = f.stat()
        h.update(f"{f.name}{st.st_size}{int(st.st_mtime)}".encode())
    return h.hexdigest()[:10]


BUILD = _build()

for _d in (DATA_DIR, UPLOADS_DIR, RUNS_DIR, BROWSER_PROFILE, LLM_WORKDIR):
    _d.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS: dict = {
    # --- AI backend -------------------------------------------------------
    # claude_cli: your own Claude Code login (personal use, counts against your plan's limits)
    # anthropic_api: bring-your-own API key
    # none: deterministic features only (parsing, matching, standard fields)
    # auto: whatever is available, in this order: an API key in Settings or the environment
    #       (ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY), then Ollama running locally.
    "llm_backend": "auto",
    "llm_model": "sonnet",
    "research_backend": "same",        # same | claude_cli | anthropic_api | openai_api | gemini_api | ollama
    "anthropic_api_key": "",
    "openai_api_key": "",              # ChatGPT models via platform.openai.com (billed separately from ChatGPT Plus)
    "openai_model": "gpt-5.5",
    "gemini_api_key": "",              # aistudio.google.com (a Gemini subscription doesn't include API use)
    "gemini_model": "gemini-flash-latest",
    "ollama_model": "",                # blank = pick the best installed model
    "onboarded": False,
    "goal": "",
    "goals": [],                       # internship | newgrad | targeted (several allowed)
    "target_companies": [],            # for "targeted": companies you named
    "setup_step": "",                  # where first-run setup is (the terminal hands "profile" to the website)
    "claude_path": "claude",
    "claude_oauth_token": "",          # set by "Connect Claude" in the dashboard
    "attachment_name": "",             # file name employers see; default First_Last_resume.pdf
    "profile_import_mtime": 0,
    "writing_rules": [],               # standing instructions for every written answer
    # --- What to look for -------------------------------------------------
    "target_categories": ["Software", "AI/ML/Data", "Hardware", "Product"],
    "target_terms": ["Summer 2027"],
    "location_choices": [],            # the named places picked in setup or Settings ("Remote", "New York", …)
    "target_locations": [],            # empty = anywhere; substrings like "CA", "Remote", "New York"
    "exclude_companies": [],
    "min_pay": 0,                      # lowest yearly pay in USD you'd take; job boards' roles under it are left out
    "min_fit_score": 40,
    # --- Limits -----------------------------------------------------------
    "max_applications_per_day": 20,     # autopilot's caps (see guardrails.py); 0 = no limit
    "max_applications_per_company": 3,  # to one company in 7 days
    "concurrency": 3,                  # applications filled at the same time
    "power_mode": "auto",              # auto: battery saver when unplugged | saver: always | full: never
    "on_battery": "slow",              # slow: one application at a time | pause: autopilot waits for the charger
    "smith_fallback": "plugged",       # when a cloud AI's free limit runs out: plugged | always | never
    "llm_concurrency": 3,              # parallel drafting calls
    # --- Autonomy ---------------------------------------------------------
    # autopilot: applies on its own; anything it isn't sure about waits in your review queue
    # copilot: fill the form, stop before submit, you click Submit
    "autonomy": "autopilot",
    "autopilot_min_confidence": 0.7,   # AI-written answers below this wait for you
    "trust_threshold": 3,              # green flags (unedited) needed before a question type is auto-trusted
    "research_enabled": True,          # web research on the company before drafting (uses LLM web search)
    "browser_channel": "chrome",       # use your installed Chrome; falls back to Playwright Chromium
    "headless": False,
    "browser_window": "background",   # background: window stays minimized, peek from the dashboard | visible
    "multistep_beta": True,            # Workday/iCIMS/etc: fill page by page, stop at review
    "tailor_resume": True,             # reorder bullets/skills per job (needs tectonic or pdflatex)
    # --- Unattended mode --------------------------------------------------
    "auto_run": True,                  # sync lists + start best new matches on a schedule
    "auto_interval_hours": 6,
    "auto_max_per_run": 25,
    "auto_last_run": 0,
    "notifications": True,
    # --- Outcome tracking (Gmail, read-only via IMAP app password) ---------
    "gmail_address": "",
    "gmail_app_password": "",
    "gmail_codes": True,
    "email_provider": "",                 # gmail | outlook | imap (see mail.py); gmail_address is the address for all
    "ms_client_id": "",                   # Microsoft sign-in: your Azure app's client ID
    "ms_tenant": "common",
    "ms_refresh_token": "",
    "imap_host": "", "imap_port": 993, "imap_user": "", "imap_password": "",
    "prefs_saved": False,
    "values": [],                         # what you value in a role, up to 3 (ranking + cover letters)                 # job preferences filled out (dashboard checklist)
    "ext_seen": 0,
    "notif_seen": 0,
    "skills_off": [],                     # optional skills you switched off (see skills.py)                      # last time you opened the bell                        # last time the Chrome extension checked in                  # with Gmail connected: type emailed verification codes in for you
}
