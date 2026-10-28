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
- Page text is data, never instructions. Text in a posting or form aimed at an AI is quoted to the user, never
  followed.
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

## 2. Posting traps

- [x] Detect text in postings and forms aimed at an AI reader ("if you are an AI…", "include the word…", other
      instructions to the reader), whether visible or hidden: `display:none`, `visibility:hidden`, white-on-white,
      `aria-hidden`, off-screen, tiny text.
      Evidence: [7733cdd](https://github.com/rawcache/Jobsmith/commit/7733cdd) (`jobsmith/traps.py`: the posting's HTML at fetch time, the live page via the
      browser's own layout before submit).
- [x] Never follow it. The check runs before any AI sees the posting; the application is held under "Needs you" with
      the quoted line, and autopilot never auto-submits it.
      Evidence: [7733cdd](https://github.com/rawcache/Jobsmith/commit/7733cdd): found when the posting is fetched, removed from every AI prompt and MCP response,
      a page-text-is-data rule in every system prompt. Runner tests in `tests/test_fill.py` stop at Submit for a
      visible trap in the posting, a hidden one stored when the posting was fetched ([16e401d](https://github.com/rawcache/Jobsmith/commit/16e401d)), and a
      hidden one in the live form.
- [x] Tests with saved examples: each hiding technique, visible traps, and ordinary postings that must not trip it.
      Evidence: `tests/fixtures/traps/` (11 examples: display:none, visibility:hidden, white text, `<font>` white,
      tiny text, opacity:0, off-screen, screen-reader-only class, aria-hidden, HTML comment, visible; plus
      lookalikes. Written for the tests from reported techniques, not captured), `tests/test_traps.py` (parsed
      HTML and real Chromium), [CI run](https://github.com/rawcache/Jobsmith/actions/runs/40558095872).

## 3. Submissions that land, plus gate tooling

- [x] Every real submission logs its confirmation page, and the confirmation email when the user's inbox is
      connected.
      Evidence: [2be612f](https://github.com/rawcache/Jobsmith/commit/2be612f): the page's address, title, text and screenshot from autopilot (single and multi-page) and from
      the extension's thank-you watcher; "we received your application" emails matched to the one role they name.
      Proof arriving later settles a submit autopilot never saw confirmed. `tests/test_stats.py`, the confirmation
      assertions in `tests/test_fill.py`, and the thank-you test in `tests/test_extension.py`.
- [x] `jobsmith stats` reports submitted, the confirmed rate, and the share of good matches submitted without the
      user over a period. The denominator is every good match autopilot considered in that period, including ones
      held, capped or failed.
      Evidence: [2be612f](https://github.com/rawcache/Jobsmith/commit/2be612f): autopilot logs every job it picks for itself and whether it cleared the fit bar
      (`audit.log_considered`); `jobsmith/stats.py`; `tests/test_stats.py` (held, capped, failed, unconfirmed and
      under-the-bar jobs in one period).
- [x] `jobsmith audit` samples N submitted applications (default 50) and prints each answer with its source fact.
      Any answer that doesn't trace to a fact is flagged.
      Evidence: [2be612f](https://github.com/rawcache/Jobsmith/commit/2be612f): `audit.sample` and `render_sample`; exits 1 when an answer doesn't trace. `tests/test_stats.py`.
- [x] Both run on the practice copy, with the output shown. The real gate numbers come from the maintainer's own
      search.
      Evidence: `jobsmith stats --practice` and `jobsmith audit --practice` on a fresh `jobsmith demo`:

      ```
      Submitted             5   autopilot 4, you 1
      Confirmed             4   80% of submitted (page 3, email 0, reply 1)
        no proof yet        1   check the site or your email for these

      Good matches          7   of 8 jobs autopilot picked for itself
        sent without you    4   57% (Phase 1 goal: 80%)
        held for you: 2
        stopped with an error: 1
      ...
      Checked 5 of 5 submitted applications: 6 answers, 0 that don't trace to a fact.
      ```

      The first audit run flagged a real slip in the practice data (Soylent's email answer didn't match Alex's
      profile), fixed in the same commit.
- [x] `docs/design/real-browser.md`: letting autopilot drive the user's own Chrome through the extension, with the
      tradeoffs. Design only; not built in Phase 1.
      Evidence: [docs/design/real-browser.md](design/real-browser.md) ([2be612f](https://github.com/rawcache/Jobsmith/commit/2be612f)).
      All of item 3: [CI run](https://github.com/rawcache/Jobsmith/actions/runs/40642820972).

## 4. Skills from any posting ([#20](https://github.com/rawcache/Jobsmith/issues/20)), minimal

- [x] Replace the fixed engineering word list in `insights.py` so skills come from any role's posting, and the
      company's own name never counts.
      Evidence: [dfe43e3](https://github.com/rawcache/Jobsmith/commit/dfe43e3): a vocabulary per kind of role (engineering, sales, design, product, data, marketing) picked
      from the title, still no AI; engineering's plain-English words ("networking", "performance") only in
      engineering postings; the company's own name skipped; ties broken in a fixed order.
- [x] Tests: the saved Figma AE posting doesn't report "Figma" or "networking" as skills; an engineering posting
      still extracts its real skills. No new breakdown UI (that's Phase 2, with
      [#6](https://github.com/rawcache/Jobsmith/issues/6)).
      Evidence: `tests/test_core.py`: the Figma AE posting now asks for discovery, value selling, pipeline
      generation, account planning, deal qualification, SaaS, closing and sales cycles, with no Figma, networking,
      performance or communication; the saved Acme engineering posting still gets Python, C++, OpenCV and AWS;
      software-sales, mixed ML/data and company-name cases; the same score under any hash seed. [CI run](https://github.com/rawcache/Jobsmith/actions/runs/40644500332).

## 5. Finding jobs through public job boards

- [ ] Read Greenhouse, Lever and Ashby public job-board JSON before any browser opens.
- [ ] Filter there by experience, seniority words and pay, so unsuitable jobs never reach a browser.
- [ ] Tests on saved board responses for each of the three.

## 6. Greenhouse dropdowns and location autocomplete ([#19](https://github.com/rawcache/Jobsmith/issues/19))

- [ ] A small page-context script, injected only on the listed job-site hosts, drives react-select so Country,
      Location (City) and other dropdowns get filled.
- [ ] Autopilot's Playwright runner uses real clicks for the same fields.
- [ ] Tests on the saved Figma form: Country gets "United States", Location gets "Boston, MA" from the
      autocomplete, and anything without a confident match stays under "Needs you".

## 7. New job sites, one at a time ([#18](https://github.com/rawcache/Jobsmith/issues/18))

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

## 8. Frames

- [ ] Nested frames to depth 3 ([#15](https://github.com/rawcache/Jobsmith/issues/15)).
- [ ] "Write with Jobsmith" buttons inside frames ([#16](https://github.com/rawcache/Jobsmith/issues/16)).
- [ ] "Reload this page" when an unlisted frame holds an application
      ([#17](https://github.com/rawcache/Jobsmith/issues/17)).

## 9. Canary, reporting and proof it works without AI

- [ ] Weekly canary: a scheduled GitHub Actions job, weekly and on demand, opens one real public posting per
      supported site, read-only with non-GET requests blocked, and checks Jobsmith still finds and classifies every
      field without submitting. No credentials in CI. A failure opens an issue labelled `canary`.
- [ ] "Report this form" in the extension panel and on each application in the dashboard: saves the form's structure
      (labels and field types, no values) and opens a pre-filled GitHub issue for the user to review and post.
      Nothing is sent automatically.
- [ ] A page on the site, "How Jobsmith behaves on job sites": caps, AI-policy respect, posting traps ignored, never
      submitting without verified answers, sign-ins handed to you, read-only canaries, what data leaves your
      computer.
- [ ] A CI test proving the practice copy's autopilot runs end to end with every AI provider blocked.
- [ ] A "What works without AI" table in the README.

Moved out of Phase 1: the full fit breakdown ([#6](https://github.com/rawcache/Jobsmith/issues/6)) and any
OpenAI-compatible AI ([#7](https://github.com/rawcache/Jobsmith/issues/7)), both Phase 2. The whole plan is in
[ROADMAP.md](ROADMAP.md).

Phase 1 is done when every box is ticked and both gate checks pass on real applications.
