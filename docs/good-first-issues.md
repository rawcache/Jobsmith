# Good first issues

Open each section as a GitHub issue: the heading is the title, the text is the body, the last line is the labels.

## SmartRecruiters: fill a single-page application form

Add an adapter in `jobsmith/fill/smartrecruiters.py` (copy `docs/templates/adapter.py`) with a saved form in
`tests/fixtures/` and a test that fills it with the made-up profile and stops before Submit.

Labels: good first issue, job site

## Save a fixture and test for another Greenhouse layout

Some Greenhouse boards use a newer layout. Save one (personal details removed) to `tests/fixtures/` and add a test
in `tests/test_fill.py` that fills it end to end.

Labels: good first issue, job site

## Wellfound as a job source

Read Wellfound job listings into Jobsmith in `jobsmith/sources.py`, with a test that parses a saved page.

Labels: help wanted, source

## Company career pages as a job source

Let users add a list of company career page URLs; Jobsmith reads new postings from each. Start in `jobsmith/sources.py`.

Labels: help wanted, source

## Check a posting is still live before applying

Before autopilot opens a job, confirm the posting still exists (no 404, no "this job is closed"). Start in
`jobsmith/jobdetail.py`, which already notices closed Greenhouse and Ashby postings when it fetches them; extend
that to Lever and other sites, and mark closed jobs instead of failing on them.

Labels: good first issue

## Show why a fit score is what it is

The Matches page shows a fit score. Add the reasons behind it (fields, keywords, location, what you value) from
`jobsmith/match.py`, as a short list beside the score.

Labels: good first issue, dashboard

## Any OpenAI-compatible AI (LM Studio, OpenRouter, vLLM)

Add a setting for a base URL + model name so any OpenAI-compatible endpoint works. Start in `jobsmith/llm.py`.

Labels: good first issue

## More stock phrases the voice skill flags

Add phrases people rarely write themselves ("I am writing to express", "passionate about leveraging") to the list in
`jobsmith/skills/voice/__init__.py`, with a test.

Labels: good first issue, skill

## More questions the terminal ask box understands

Pick a question the ask box can't answer yet (e.g. "which companies haven't replied in two weeks?"), add it to
`jobsmith/ask.py` and a test in `tests/test_ask.py`. No AI allowed: answers come from Jobsmith's records.

Labels: good first issue, terminal

## Windows: sign in to Claude from Jobsmith

On macOS and Linux, Settings can sign you in to Claude with your subscription (it runs `claude setup-token` in a
pseudo-terminal). On Windows it stops with "isn't available on Windows", because `jobsmith/claude_login.py` uses
`pty`, `fcntl` and `termios`, which Windows doesn't have. Find out whether `claude setup-token` works there without
a terminal, or use Windows' own pseudo-terminal (ConPTY, e.g. via `pywinpty`), and add a test.

Labels: help wanted

## Interview prep skill: first version

Write `jobsmith/skills/prep/SKILL.md` as ready and a first feature: likely questions for a role, built from the
posting and the user's own stories (voice skill). Practice only.

Labels: help wanted, skill

## Dark-mode check of every dashboard page

Open every dashboard page in dark mode in the practice copy and fix anything unreadable in `web/src/style.css`.

Labels: good first issue, dashboard
