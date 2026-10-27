# Phase 1: Autopilot you can trust (Oct 27 – Nov 30, 2026)

**Goal:** autopilot applies on the six big job sites with guardrails people can see, and we can prove it doesn't
invent facts.

**Gate:** Phase 1 is done when both hold:

- [ ] 80% of good matches (fit at or above the user's threshold) are submitted without the user doing anything,
      measured from the audit trail over at least 50 real applications (`jobsmith stats`).
- [ ] Zero invented facts in a 50-application audit: every submitted answer traces to the resume, profile or the
      user's own writing (`jobsmith audit`).

Work top to bottom. Tick each box in this file as it's done, with a link to the evidence (commit, test, CI run or
issue), and commit the tick with the work.

## Rules for all of Phase 1

- Sign-ins, account creation, CAPTCHAs and emailed codes are always handed to the user. Never type a password or
  create an account.
- When developing, capturing fixtures, testing or running canaries, touching a live job site is read-only: headless,
  every non-GET request blocked. Never submit to a real posting in tests or CI. (Only the user's own autopilot
  submits for real.)
- Fixtures are saved real forms, sanitized, filled only with Alex Rivera. No real applicant's details, ever.
- No LinkedIn automation.
- Every new site gets a fixture in `tests/fixtures/`, a `tests/test_fill.py` test (filled fields and what lands under
  "Needs you"), and an extension autofill test with the submit watcher on. `ats.SUPPORTED` and the README change
  only when those pass.
- Commit and push after each item if tests pass and the Codex review finds nothing blocking. Ask before cutting a
  release.

## 1. Guardrails (before any new site)

- [x] Default caps: 20 submissions a day and 3 per company per week. Editable in settings and shown on the dashboard
      ("12 of 20 today"). Autopilot stops at a cap and says which one.
      Evidence: [1810a1b](https://github.com/rawcache/Jobsmith/commit/1810a1b), `tests/test_guardrails.py` (caps, scheduler, cancel, unconfirmed submits),
      CI passed.
- [x] Employer AI policies: detect postings and forms that say not to use AI or automated tools. Autopilot never
      auto-submits those; they go to "Needs you" with the quoted line.
      Evidence: [095bc86](https://github.com/rawcache/Jobsmith/commit/095bc86), `tests/test_guardrails.py` (policy and not-policy wording, multi-page forms),
      CI passed.
- [x] Per-application audit trail: for every submission, store each field, the answer sent, where it came from
      (resume line, profile field, writing sample, user-typed) and the kind check's result. Viewable per
      application on the dashboard and exportable as JSON.
      Evidence: [3e37ee1](https://github.com/rawcache/Jobsmith/commit/3e37ee1), `tests/test_audit.py`, audit assertions in `tests/test_fill.py`,
      [CI run](https://github.com/rawcache/Jobsmith/actions/runs/40461438613).
- [x] Visible fit gate: autopilot applies only at or above the user's fit threshold, and each match shows why it
      passed or failed.
      Evidence: [7d7cdb4](https://github.com/rawcache/Jobsmith/commit/7d7cdb4), fit-gate tests in `tests/test_guardrails.py`, [CI run](https://github.com/rawcache/Jobsmith/actions/runs/40462725556).

## 2. Fit breakdown, plus [#20](https://github.com/rawcache/Jobsmith/issues/20)

- [ ] Replace the fixed engineering word list in `insights.py` with skill extraction that works for any role and
      never counts the company's own name.
- [ ] The breakdown shows matched skills, missing skills, location, level and what the user values, each with its
      weight (also closes [#6](https://github.com/rawcache/Jobsmith/issues/6)).
- [ ] Tests: the saved Figma AE posting doesn't report "Figma" or "networking" as skills; an engineering posting
      still extracts its real skills.

## 3. Greenhouse dropdowns and location autocomplete ([#19](https://github.com/rawcache/Jobsmith/issues/19))

- [ ] A small page-context script, injected only on the listed job-site hosts, drives react-select so Country,
      Location (City) and other dropdowns get filled.
- [ ] Autopilot's Playwright runner uses real clicks for the same fields.
- [ ] Tests on the saved Figma form: Country gets "United States", Location gets "Boston, MA" from the
      autocomplete, and anything without a confident match stays under "Needs you".

## 4. New job sites, one at a time ([#18](https://github.com/rawcache/Jobsmith/issues/18))

Each site is its own commit series: fixture, `test_fill.py` test, extension autofill test with the submit watcher,
then `ats.SUPPORTED` and the README.

- [ ] a. Ashby: capture and sanitize a real Ashby form to replace the hand-written fixture.
- [ ] b. Lever: end-to-end tests.
- [ ] c. SmartRecruiters: the good-first-issue adapter ([#1](https://github.com/rawcache/Jobsmith/issues/1)),
      only if nobody has claimed it.
- [ ] d. Workday: page by page, stopping at review; the sign-in and account step is handed to the user. Public
      pages captured read-only; a short guide for the maintainer to save the signed-in steps, which are then
      sanitized.
- [ ] e. iCIMS: page by page, including multi-step forms in frames.

## 5. Frames

- [ ] Nested frames to depth 3 ([#15](https://github.com/rawcache/Jobsmith/issues/15)).
- [ ] "Write with Jobsmith" buttons inside frames ([#16](https://github.com/rawcache/Jobsmith/issues/16)).
- [ ] "Reload this page" when an unlisted frame holds an application
      ([#17](https://github.com/rawcache/Jobsmith/issues/17)).

## 6. Weekly canary

- [ ] A scheduled GitHub Actions job, weekly and on demand, opens one real public posting per supported site,
      read-only with non-GET requests blocked, and checks Jobsmith still finds and classifies every field without
      submitting. No credentials in CI.
- [ ] A failure opens an issue labelled `canary`.

## 7. Telling people how it behaves

- [ ] "Report this form" in the extension panel and on each application in the dashboard: saves the form's structure
      (labels and field types, no values) and opens a pre-filled GitHub issue for the user to review and post.
      Nothing is sent automatically.
- [ ] A page on the site, "How Jobsmith behaves on job sites": caps, AI-policy respect, never submitting without
      verified answers, sign-ins handed to you, read-only canaries, what data leaves your computer.

## 8. Any OpenAI-compatible AI ([#7](https://github.com/rawcache/Jobsmith/issues/7))

- [ ] Base URL and model name in settings (LM Studio, OpenRouter, vLLM). A good first issue: build it only if no
      outside contributor has claimed it by mid-November (check the assignee and comments first).

## 9. Gate tooling

- [ ] `jobsmith audit` samples N submitted applications (default 50) and prints each answer with its source fact and
      whether it traces. Anything that doesn't trace is flagged in red.
- [ ] `jobsmith stats` reports the share of good matches submitted without the user over a period. The denominator
      is every good match autopilot considered in that period, including ones held, capped or failed.
- [ ] Both run on the practice copy, with the output shown. The real gate numbers come from the maintainer's own
      search.

Phase 1 is done when every box is ticked and both gate checks pass on real applications.
