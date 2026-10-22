# Jobsmith: notes for Claude Code

Jobsmith is an open-source, local job-hunt app: it finds roles, fills and submits applications for the user, and
helps with everything around them. The repo is github.com/rawcache/Jobsmith (MIT). Brand is "Jobsmith" in prose;
the command, package, import and data folder are lowercase `jobsmith`.

The roadmap lives in the user's Claude Project ("Jobsmith Roadmap"). The current phase and its checklist are in
`docs/PHASE0.md`. Work through that file top to bottom and tick items off as they're done.

## Rules that never bend

1. **Never invent facts about the user.** Every written answer cites facts from their resume/profile and is checked
   (`draft.validate`) before anything is submitted. Never weaken those checks to make autopilot submit more.
2. **Work authorization, sponsorship and demographic answers come only from the user's confirmed profile.** Never
   let an AI write them, and never add code that guesses them.
3. **Never send messages for the user.** Outreach, follow-ups and thank-yous are drafts the user sends.
4. **No hidden help in real interviews.** Interview notes need a consent step; live talking points are for practice
   and mock interviews only.
5. **Never type passwords, create accounts, or solve CAPTCHAs.** Hand those to the user (the bell / takeover).
6. **No LinkedIn automation.** Read the user's own export only.
7. **Nothing personal is committed.** `data/`, `_to_delete/`, `downloaded_simplify/` and any key or token stay out of
   git. Before every commit run `git status` and check no personal files, keys or real names (other than the
   LICENSE copyright line) are staged. Demo data is the made-up Alex Rivera only.
8. **Local-first.** No telemetry, no Jobsmith servers. Network calls go only to job sites, the user's chosen AI and
   the user's own email.

## Layout

| Path | What it is |
| --- | --- |
| `jobsmith/api.py` | FastAPI engine on 127.0.0.1:8765 (practice copy: 8766) |
| `jobsmith/runner.py` | Applies to jobs: opens, fills, waits, submits; live tabs |
| `jobsmith/fill/` | Job-site adapters (`greenhouse.py`, `generic.py`, `multistep.py`) and shared helpers (`base.py`) |
| `jobsmith/ats.py` | Detects the site behind a URL; `SUPPORTED` = fillable end to end |
| `jobsmith/draft.py` | Drafts and validates answers; `readiness()` decides if autopilot may submit |
| `jobsmith/skills/<name>/` | One folder per skill: `SKILL.md` (frontmatter) + code. Registry in `skills/__init__.py` |
| `jobsmith/ask.py` | The no-AI question answerer behind the terminal ask box and `/api/ask` |
| `jobsmith/tuiapp.py` | Full-screen terminal app (Textual), Claude Code style |
| `jobsmith/tui.py`, `cli.py`, `clicmds.py`, `devtools.py` | Commands, setup, practice copy, checks |
| `jobsmith/mcp_server.py` | MCP server so the user's own agent can write answers |
| `jobsmith/llm.py`, `smith.py` | AI backends (Gemini, Claude, OpenAI, local smith via Ollama) |
| `web/` | React + Vite dashboard; `npm run build` writes `jobsmith/web_dist/` (committed) |
| `extension/` | Chrome extension (MV3) |
| `site/` | Project website (GitHub Pages) |
| `tests/` | pytest; `tests/fixtures/` holds saved copies of real forms |

## Commands

```bash
uv sync                                  # install
uv run pytest -q                         # all tests (about 70 s)
uv run jobsmith demo                     # practice copy at :8766 with made-up data
uv run jobsmith demo stop
uv run jobsmith dev                      # practice copy + dashboard live reload
uv run jobsmith check                    # tests + dashboard build + screenshots of every page
cd web && npm run build                  # rebuild the dashboard into jobsmith/web_dist/
uv run jobsmith                          # the terminal app (needs the engine; starts it)
```

Never point tests or experiments at the user's real data folder. Use the practice copy (`JOBSMITH_DEMO=1`), which
blocks every outward action.

## Conventions

- Python 3.13 (`.python-version`), plain asyncio. Type hints, small functions, docstrings that say why.
- User-facing words: plain, specific, active voice, no jargon ("applications waiting for you", not "pending queue").
- UI: cobalt palette and centered column (see `web/src/style.css` tokens). Light theme by default.
- Every new job site gets a fixture in `tests/fixtures/` and a test in `tests/test_fill.py`.
- Every new skill gets `SKILL.md` frontmatter: `name`, `description`, `title`, `status` (ready|planned), `order`,
  and optional `page`, `command`, `core`.
- Version lives in three places: `pyproject.toml`, `jobsmith/__init__.py`, `extension/manifest.json`.
- Commits: imperative subject under 72 characters, body says why. Small commits.

## Known gaps to keep honest

- `ats.SUPPORTED` is only `{"greenhouse"}`; Lever and Ashby go through `fill/generic.py`. Public claims about which
  sites work end to end must match what the tests prove (Phase 0 task).
- Workday / iCIMS: filled page by page, stop at review; sign-in is the user's.

## Working with Codex

Codex (OpenAI's CLI, signed in with the user's ChatGPT account) is run from the shell; it is not an MCP server.
Claude Code leads: it plans, edits, runs tests, and is the only one that commits or pushes. Codex is a second
engineer for three jobs. Run `codex review --help` and `codex exec --help` once per session to confirm the flags.

1. **Review.** After each logical change and before every commit, stage it and run a read-only review:
   `codex review` (or `codex exec -s read-only -C . "Review git diff --staged against CLAUDE.md. List bugs, rule
   breaks (invented facts, sent messages, personal data) and missing tests. Do not edit files."`).
   Fix what holds up; tell the user what you didn't take and why.
2. **Parallel, separate work.** Hand Codex one self-contained task in files you aren't touching:
   `codex exec -s workspace-write -C . "<task, files to create, test to run>"`. It must not commit. Then run the
   tests and review its changes as you would a contributor's (`git diff`).
3. **Second opinion** on a design choice when two approaches look close (`-s read-only`).

Never use `--dangerously-bypass-approvals-and-sandbox` or `-s danger-full-access`, never let Codex commit or push,
and never give it anything from `data/`. Long tasks can take minutes; run them in the background and keep working.
