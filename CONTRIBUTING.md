# Contributing to Jobsmith

Thanks for helping. Most contributions are one small, self-contained piece: a job site, a job source, or a skill.
You can build and test each one without touching the rest.

## Set up

```bash
git clone https://github.com/rawcache/Jobsmith && cd Jobsmith
uv sync && uv run playwright install chromium
uv run pytest -q          # all tests should pass
uv run jobsmith demo      # a practice copy with a made-up person; nothing real is touched
```

Tests run in a random order each time (pytest-randomly), so a test that leans on another's leftovers fails early.
To repeat a failing order, pass the seed: `uv run pytest -p randomly --randomly-seed=1234`. Give each test its own
setup (the `monkeypatch` fixture is the easy way) rather than resetting shared state afterwards.

Work only in the practice copy. It blocks every outward action, so you can't apply anywhere by accident.

## Add a job site

Each site Jobsmith can fill is an adapter in `jobsmith/fill/`.

1. Save the application form of a real public posting as HTML in `tests/fixtures/<site>_form.html`. Remove anything
   personal or tracking-related.
2. Copy `docs/templates/adapter.py` to `jobsmith/fill/<site>.py` and fill in `open_form` and `fill`.
3. Add the URL pattern to `ATS_PATTERNS` in `jobsmith/ats.py`, and the site to `SUPPORTED` once it fills end to end.
4. Add a test in `tests/test_fill.py` that fills the fixture with the made-up profile and stops before Submit.

An adapter must never press Submit by itself, type a password, or solve a CAPTCHA. The runner decides when to
submit; sign-ins and CAPTCHAs go to the user.

## Add a skill

A skill is a folder in `jobsmith/skills/<name>/` with a `SKILL.md` and its code. Copy `docs/templates/skill/` to
start. The frontmatter is read by the app, the terminal, and people's AI agents:

```yaml
name: jobsmith-<name>        # for AI agents
title: Interview prep        # shown in the app
description: One sentence on what it does and when to use it.
status: planned              # or ready
order: 60                    # position in lists
page: "#/prep"               # optional dashboard page
command: jobsmith prep       # optional terminal command
```

## The rules every change follows

- Never invent facts about the user. Written answers cite their facts and pass the checks in `draft.py`.
- Work-authorization and demographic answers come only from the user's confirmed profile, never from an AI.
- Never send messages for the user. Drafts only.
- Interview features need everyone's consent. No hidden help during real interviews.
- No LinkedIn automation, no account creation, no CAPTCHA solving.
- Nothing leaves the user's computer except the applications they send and calls to the AI they chose.

Pull requests that break one of these are closed, however useful they are otherwise.

## Before you commit

- Use the practice copy's made-up person, Alex Rivera, for tests, fixtures and screenshots. Never commit a real
  resume, cover letter, profile, or a saved page that shows a real applicant's details.
- Saved job forms in `tests/fixtures/` must be blank or filled with Alex's details.
- No keys, tokens, cookies or `.env` files. `.gitignore` keeps the common ones out, and the `secrets` check
  (gitleaks) fails a push or pull request that contains a recognisable key or token. It can't catch everything,
  so look at `git status` before you commit.

## Pull requests

- One change per pull request, with a test.
- `uv run pytest -q` passes. If you touched `web/`, run `cd web && npm run build` and commit `jobsmith/web_dist/`.
- Write user-facing text plainly: say what happens, in the user's words.
- Explain why in the description, and link the issue.

## Be decent

Be kind and assume good intent. Harassment or personal attacks get you removed from the project. Report problems
to the maintainer through GitHub.
