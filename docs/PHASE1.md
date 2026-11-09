# Phase 1: Autopilot you can trust (Oct 27 – Nov 30, 2026)

**Goal:** autopilot applies on the six big job sites with guardrails people can see, and we can prove it doesn't
invent facts.

**Gate (also the public launch):** Phase 1 is done when all three hold:

- [ ] 80% of good matches (fit at or above the user's threshold) are submitted without the user doing anything,
      measured from the audit trail over at least 50 real applications (`jobsmith stats`).
- [ ] Zero invented facts in a 50-application audit: every submitted answer traces to the resume, profile or the
      user's own writing (`jobsmith audit`).
- [ ] 3 people who aren't developers reach their first real application in under 15 minutes without help, watched
      with [docs/launch/usability-test.md](launch/usability-test.md) (item 10).

Work top to bottom. Tick each box in this file as it's done, with a link to the evidence (commit, test, CI run or
issue), and commit the tick with the work.

## Rules for all of Phase 1

- Sign-ins, account creation, CAPTCHAs and emailed codes are always handed to the user. Never type a password or
  create an account. One exception, decided 2026-10-31: the code a job site emails to verify an application right
  after Jobsmith pressed its Submit may be typed by Jobsmith, and only when all of these hold: it's in an inbox the
  user connected; the sender's domain is that application's job site; it arrived within 15 minutes of that Submit;
  it names that company or role (through a job site's shared mail, the company itself), and says it's for an
  application. Never a sign-in, two-step, password-reset, account or access code. Anything that doesn't match goes to
  "Needs you" (`outcomes.application_code`, `tests/test_codes.py`).
- When developing, capturing fixtures, testing or running canaries, touching a live job site is read-only: headless,
  every non-GET request blocked. Never submit to a real posting in tests or CI. (Only the user's own autopilot
  submits for real.) One exception, approved 2026-10-29: Ashby loads its form through two GraphQL reads sent as
  POSTs (`ApiJobPosting`, `ApiOrganizationFromHostedJobsPageName` on `jobs.ashbyhq.com/api/non-user-graphql`), and
  shows no form without them. `scripts/capture/capture.py` lets those two through only when the body is a plain
  `query` with that operation name; autosave, upload, submit and everything else stay blocked
  (`jobsmith/readonly.py`, `tests/test_readonly.py`).
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

## 3b. Supervised first run

- [x] The first real (non-practice) autopilot submission, and the first on each new job site, stops at the filled
      form and shows every answer with its source. It's sent only after the user approves it in the dashboard or the
      terminal; after that, autopilot submits on that site on its own within the caps. Tests.
      Evidence: [78897c5](https://github.com/rawcache/Jobsmith/commit/78897c5). `guardrails.first_run_reason` holds
      the run, the job page's "Approve and send" panel and `/review`'s `s` approve it, and the site is trusted only
      once the confirmation lands. Tests: `test_autopilots_first_submission_waits_for_your_approval` (test_fill.py),
      twelve `test_guardrails.py` tests from `test_first_submission_and_first_on_each_site_need_your_approval` to
      `test_after_a_refill_the_site_is_trusted_only_once_it_lands` (multi-page, closed tab, double click, failed
      click, files swapped), and the `/review` approval test in test_tuiapp.py.
      [CI run](https://github.com/rawcache/Jobsmith/actions/runs/40750079559).

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

- [x] Read Greenhouse, Lever and Ashby public job-board JSON before any browser opens.
      Evidence: [c8abefe](https://github.com/rawcache/Jobsmith/commit/c8abefe). `jobsmith/boards.py` turns a board
      address (`boards.greenhouse.io/figma`, `jobs.lever.co/palantir`, `jobs.ashbyhq.com/ramp`) into a source read
      with one GET to the board's public API; paste it in the terminal or add it in Settings. Roles taken down are put
      away on the next sync, and an answer that isn't a board closes nothing.
- [x] Filter there by experience, seniority words and pay, so unsuitable jobs never reach a browser.
      Evidence: `boards.screen` leaves out senior titles (staff/principal need 7+ years, senior/lead 3+), roles
      requiring 3+ years and more than a year beyond what the profile shows (preferred years don't count), and pay
      under the new "Lowest pay you'd take" (hourly and monthly annualized; USD only; no stated pay passes).
      Experience is screened only when the profile or goals say it. Each sync says how many it left out and why.
      Left-out roles are kept with the reason under a collapsed "Left out (N)" on Matches and with `l` in
      `/matches`, never picked by autopilot, and "Apply anyway" makes one a match for good
      ([942200e](https://github.com/rawcache/Jobsmith/commit/942200e),
      [CI run](https://github.com/rawcache/Jobsmith/actions/runs/40765309244)).
- [x] Tests on saved board responses for each of the three.
      Evidence: `tests/test_boards.py` (26 tests) on trimmed saved responses in `tests/fixtures/boards/` (Figma on
      Greenhouse, Palantir on Lever, Ramp on Ashby), served through a mock that refuses anything but a GET.
      [CI run](https://github.com/rawcache/Jobsmith/actions/runs/40757860637) (with the Windows encoding fix,
      [c56b80d](https://github.com/rawcache/Jobsmith/commit/c56b80d)).

## 6. Greenhouse dropdowns and location autocomplete ([#19](https://github.com/rawcache/Jobsmith/issues/19))

- [x] The extension drives react-select so Country, Location (City) and other dropdowns get filled. (Planned as a
      page-context script; on the live form a whole key press from the content script is enough, because Greenhouse
      opens its menus on key-up and mouse-up and the extension only sent key-down. See #19.)
      Evidence: [7de52a8](https://github.com/rawcache/Jobsmith/commit/7de52a8). `fillCombobox` in
      `extension/content.js` sends whole key presses and a key-up after typing; the engine sends the city as place
      lookups name it (`draft.location_full`: "Boston, MA" → "Boston, Massachusetts, United States", only for a
      plain US city and state). Checked on the live Figma form (headless, every non-GET blocked): Country, Location
      (City) and both Yes/No boxes filled, every hidden "required" copy filled, nothing sent.
- [x] Autopilot's Playwright runner uses real clicks for the same fields.
      Evidence: `fill_combobox` already clicked the control and the option; now proven on Greenhouse's controlled
      menus, on the fixture and on the live form (same check, read-only).
- [x] Tests on the saved Figma form: Country gets "United States", Location gets "Boston, MA" from the
      autocomplete, and anything without a confident match stays under "Needs you".
      Evidence: `tests/fixtures/greenhouse_figma_live.html` is the saved form with real react-select set up as
      the live form is (source and rebuild steps in `tests/fixtures/src/`). Extension (submit watcher on):
      `test_autofill_picks_greenhouse_dropdowns_and_the_city_from_its_lookup`,
      `..._leaves_a_city_the_lookup_doesnt_have_for_you`, `..._picks_a_city_outside_the_us_as_you_wrote_it`;
      autopilot: `test_greenhouse_dropdowns_on_the_saved_figma_form_are_picked_with_real_clicks`; engine:
      `test_engine_names_the_city_to_pick_from_a_place_lookup`, `test_a_us_city_is_named_the_way_place_lookups_name_it`.
      [CI run](https://github.com/rawcache/Jobsmith/actions/runs/40769864788) (Linux, Windows, dashboard passed;
      the macOS runner cancelled the job before its first step, and it's been rerun).
      Checked by hand on the live Figma posting (2026-10-28): phone Country "+1", Location (City) picked from the
      autocomplete, "From where do you intend to work?" under Check these, nothing submitted.

## 7. New job sites, one at a time ([#18](https://github.com/rawcache/Jobsmith/issues/18))

Each site is its own commit series: fixture, `test_fill.py` test, extension autofill test with the submit watcher,
then `ats.SUPPORTED` and the README.

- [x] a. Ashby: capture and sanitize a real Ashby form to replace the hand-written fixture.
      Evidence: [7e82c3a](https://github.com/rawcache/Jobsmith/commit/7e82c3a). `tests/fixtures/ashby_ramp_form.html`
      is Ramp's real "Software Engineer, Frontend" form, saved blank with `scripts/capture/capture.py` (the two
      GraphQL reads above let through, nothing else; `tests/test_capture.py`), Alex Rivera only; rebuild steps in
      `tests/fixtures/src/`. The hand-written `ashby_style_form.html` is gone. Ashby's Yes/No questions (buttons
      beside a hidden checkbox) are now scanned and pressed by autopilot and the extension. Autopilot:
      `test_ashby_saved_ramp_form_is_filled_and_held_before_submit` (work authorization from the confirmed profile;
      the take-home question under Needs you; SMS and WhatsApp consent left for you; Submit never pressed) and
      `test_autopilot_sends_the_saved_ashby_form_once_everything_is_answered` (Ashby's thank-you recorded as proof).
      Extension, submit watcher on: `test_autofill_presses_ashby_yes_no_buttons_on_the_saved_ramp_form` (autosave
      isn't a submit) and `test_the_submit_watcher_sees_ashbys_submit_on_the_saved_ramp_form`. Then `ats.SUPPORTED`,
      README and site. [CI run](https://github.com/rawcache/Jobsmith/actions/runs/40832738244) (macOS failed once on
      an unrelated timing guess in a popup test, #22, fixed in 979174e; the rerun passed on all three).
- [x] b. Lever: end-to-end tests.
      Evidence: [981bfd2](https://github.com/rawcache/Jobsmith/commit/981bfd2),
      [99f3f9b](https://github.com/rawcache/Jobsmith/commit/99f3f9b),
      [5546b48](https://github.com/rawcache/Jobsmith/commit/5546b48). `tests/fixtures/lever_palantir_form.html` is
      Palantir's real "Forward Deployed Software Engineer, Internship" form on Lever, saved blank through
      `jobsmith/readonly.py` (GETs only), Alex Rivera only, Lever's account and editor ids and hCaptcha's site key
      blanked; rebuild steps in `tests/fixtures/src/`. The hand-written `lever_form.html` is gone. Autopilot:
      `test_lever_saved_palantir_form_is_filled_and_held_before_submit` (each question read by its own words, not its
      options; the place picked from Lever's lookup; work authorization from the confirmed profile only because the
      job is in the US; high school questions and the AI notetaker consent left for you; the disability question
      blank because any answer needs your signature; Submit never pressed) and
      `test_autopilot_sends_the_saved_lever_form_once_everything_is_answered` ("Application submitted!" recorded as
      proof). Extension, submit watcher on: `test_autofill_on_the_saved_lever_form_picks_the_place_and_never_signs`,
      the place tests, and `test_the_submit_watcher_sees_levers_submit_on_the_saved_palantir_form`. Lever's cookie
      banner covered the Languages checkboxes: every adapter now closes cookie banners with a real click on the most
      private choice, never Accept (`tests/test_banners.py`, Lever's saved banner plus eight written examples). Then
      `ats.SUPPORTED`, README and site. [CI run](https://github.com/rawcache/Jobsmith/actions/runs/41241943968)
      (Linux, macOS, Windows).
- [x] c. SmartRecruiters: the good-first-issue adapter ([#1](https://github.com/rawcache/Jobsmith/issues/1)),
      only if nobody has claimed it. **Partial:** the first page only; the pages after Next are
      [#35](https://github.com/rawcache/Jobsmith/issues/35), and SmartRecruiters isn't in `ats.SUPPORTED`.
      Evidence: [19c5002](https://github.com/rawcache/Jobsmith/commit/19c5002),
      [e3422f3](https://github.com/rawcache/Jobsmith/commit/e3422f3),
      [e291446](https://github.com/rawcache/Jobsmith/commit/e291446),
      [2d96fd0](https://github.com/rawcache/Jobsmith/commit/2d96fd0),
      [80f6995](https://github.com/rawcache/Jobsmith/commit/80f6995),
      [7d9bcc8](https://github.com/rawcache/Jobsmith/commit/7d9bcc8). #1 was unclaimed. Read-only, SmartRecruiters
      shows DataDome's bot check in place of the form, and getting past it is not ours to do, so Bosch's Application
      Engineer form was saved blank from the maintainer's own Chrome
      ([docs/guides/save-smartrecruiters-form.md](guides/save-smartrecruiters-form.md)) as
      `tests/fixtures/smartrecruiters_bosch_form.html`. Its boxes live in web components' shadow roots; each is read
      by its own words. Autopilot: `test_smartrecruiters_saved_bosch_form_is_filled_and_held_before_next` (the
      resume in the Resume box, never the "autocomplete your application" upload; Next, Submit, Apply With Indeed
      and SEEK never pressed). Extension, submit watcher on:
      `test_autofill_fills_smartrecruiters_form_inside_its_components_and_never_moves_on`. The bot check still
      hands the page to the user (`tests/test_bot_walls.py`).
      [CI run](https://github.com/rawcache/Jobsmith/actions/runs/41393247644) (Linux, macOS, Windows). Known gap:
      SmartRecruiters asks more after Next, and those pages weren't saved
      ([#35](https://github.com/rawcache/Jobsmith/issues/35)), so it stays out of `ats.SUPPORTED`.
- [x] d. Workday: page by page, stopping at review; the sign-in and account step is handed to the user. Public
      pages captured read-only; a short guide for the maintainer to save the signed-in steps, which are then
      sanitized.
      Evidence: [50082e0](https://github.com/rawcache/Jobsmith/commit/50082e0),
      [f124473](https://github.com/rawcache/Jobsmith/commit/f124473),
      [b8ae7d1](https://github.com/rawcache/Jobsmith/commit/b8ae7d1),
      [aba31b4](https://github.com/rawcache/Jobsmith/commit/aba31b4),
      [f675d87](https://github.com/rawcache/Jobsmith/commit/f675d87),
      [7783f4a](https://github.com/rawcache/Jobsmith/commit/7783f4a). Public pages saved read-only from NVIDIA's
      internship posting up to sign-in; the sign-in choice page is handed to the user, Apply Manually is pressed when
      there's no resume, no password box is read and Workday's honeypot is never filled. The five signed-in pages of
      NVIDIA's posting (My Information, My Experience, Application Questions, Voluntary Disclosures, Review) were
      saved by the maintainer ([docs/guides/save-workday-pages.md](guides/save-workday-pages.md)) and emptied by
      `tests/fixtures/src/workday_fixture.py --signed-in`: every value replaced with Alex Rivera's or blanked, another
      extension's markup gone, Workday's ids blanked (`tests/fixtures/workday_nvidia_{my_information,my_experience,
      application_questions,voluntary_disclosures,review}.html`). Autopilot:
      `test_workday_signed_in_page_by_page_to_review_and_never_submits` (each page filled, stops at Review, Submit
      never pressed), `test_workdays_signed_in_pages_are_read_by_their_own_words`,
      `test_workdays_phone_code_search_picks_only_your_numbers_code`,
      `test_workdays_review_submit_is_never_pressed_as_next`. Extension, submit watcher on:
      `test_autofill_fills_workdays_my_information_page_and_never_moves_on`,
      `test_autofill_reads_workdays_application_questions_by_their_words`,
      `test_autofill_answers_workdays_voluntary_questions_from_your_decline_and_never_a_wrong_code`,
      `test_autofill_never_picks_a_phone_code_that_isnt_your_numbers`,
      `test_the_submit_watcher_sees_your_submit_on_workdays_review_page`. Builders:
      `test_a_signed_in_workday_page_is_emptied_and_another_tools_markup_goes`,
      `test_a_review_answer_the_builder_doesnt_know_stops_it`.
      [CI run](https://github.com/rawcache/Jobsmith/actions/runs/41280460214) (Linux, macOS, Windows). Known gaps:
      Workday's lists were closed when saved, so the open lists are a stand-in
      ([#29](https://github.com/rawcache/Jobsmith/issues/29)); a page showing errors after Next wasn't saved
      ([#28](https://github.com/rawcache/Jobsmith/issues/28)). Workday stays out of `ats.SUPPORTED`: it stops at
      Review.
- [x] e. iCIMS: page by page, including multi-step forms in frames. **Partial:** step 1 of 5 (the Candidate
      Profile) only; steps 2-5 and the real dropdown lists are [#31](https://github.com/rawcache/Jobsmith/issues/31),
      and iCIMS isn't in `ats.SUPPORTED`.
      Evidence: [4376649](https://github.com/rawcache/Jobsmith/commit/4376649),
      [9d3d77f](https://github.com/rawcache/Jobsmith/commit/9d3d77f),
      [30e2d99](https://github.com/rawcache/Jobsmith/commit/30e2d99),
      [2fa4707](https://github.com/rawcache/Jobsmith/commit/2fa4707),
      [286d091](https://github.com/rawcache/Jobsmith/commit/286d091). iCIMS draws the application in its
      `icims_content_iframe` frame; the page-by-page filler reads, fills and clicks inside it (`base.InFrame`).
      Public pages saved read-only from IDEMIA's internship posting; the signed-in Candidate Profile saved by the
      maintainer with other extensions off and emptied to Alex Rivera (`tests/fixtures/icims_idemia_*.html`).
      Jobsmith presses "Apply for this job online", hands the email step and the login to the user, and on the
      Candidate Profile (profile and account on one page) fills only the profile: never the Login, Password or
      Password (Re-enter) boxes, never Submit Profile, and the application waits under "Needs you" with "Create
      your login and press Submit Profile yourself". The resume is attached first and the rest is filled after
      iCIMS has read it; a read that takes too long holds the application, and boxes the read draws again get only
      their own answers. Autopilot: `test_icims_saved_pages_draw_the_application_in_a_frame_and_its_sign_in_is_yours`,
      `test_icims_from_the_saved_posting_to_sign_in_is_handed_to_you`,
      `test_icims_profile_page_fills_your_profile_and_leaves_the_login_to_you`. Extension, submit watcher on:
      `test_autofill_fills_nothing_on_icims_sign_in`, `test_autofill_fills_icims_profile_and_leaves_the_login_to_you`,
      and the redraw tests (`test_boxes_drawn_again_are_matched_only_when_sure` and others). Known gaps: only step 1
      of 5 is saved ([#31](https://github.com/rawcache/Jobsmith/issues/31)); iCIMS's search dropdowns were closed
      when saved, so their open lists are a stand-in. iCIMS stays out of `ats.SUPPORTED`.
      [CI run](https://github.com/rawcache/Jobsmith/actions/runs/41401933961) (Linux, macOS, Windows).

## 8. Frames

- [x] Nested frames to depth 3 ([#15](https://github.com/rawcache/Jobsmith/issues/15)).
      Evidence: [ea6b3ef](https://github.com/rawcache/Jobsmith/commit/ea6b3ef), [f0c246d](https://github.com/rawcache/Jobsmith/commit/f0c246d), [1a639f4](https://github.com/rawcache/Jobsmith/commit/1a639f4), [2ede126](https://github.com/rawcache/Jobsmith/commit/2ede126). The top page asks every frame up
      to three deep whether it holds a form (through `window.frames`, which works across sites) and waits for every
      answer, up to a second; a wrapper counts as reached when a form inside it answered, or when nothing inside it
      went unanswered, and frames past the limit count as unseen. `test_the_page_tells_the_popup_which_frames_it_couldnt_reach` (wrappers, 3
      and 4 deep) and `test_the_page_waits_for_a_slow_frame_and_not_forever_for_a_silent_one` (#25, #27).
- [x] "Write with Jobsmith" buttons inside frames ([#16](https://github.com/rawcache/Jobsmith/issues/16)).
      Evidence: [ea6b3ef](https://github.com/rawcache/Jobsmith/commit/ea6b3ef). Open questions in a frame that holds a form get Write buttons; the panel stays on the
      top page. `test_write_with_jobsmith_works_beside_a_question_in_a_job_sites_frame`.
- [x] "Reload this page" when an unlisted frame holds an application
      ([#17](https://github.com/rawcache/Jobsmith/issues/17)).
      Evidence: [ea6b3ef](https://github.com/rawcache/Jobsmith/commit/ea6b3ef). Judged from the frame's address, title, name or height, so a video or a map
      doesn't trigger it. `test_popup_says_reload_when_the_real_application_is_in_another_sites_frame`
      and the YouTube, Maps and Google Forms cases. [CI run](https://github.com/rawcache/Jobsmith/actions/runs/41264108329)
      (Linux, macOS, Windows).

## 9. Canary, reporting and proof it works without AI

- [x] Weekly canary: a scheduled GitHub Actions job, weekly and on demand, opens one real public posting per
      supported site, read-only with non-GET requests blocked, and checks Jobsmith still finds and classifies every
      field without submitting. No credentials in CI. A failure opens an issue labelled `canary`.
      Evidence: [a67628a](https://github.com/rawcache/Jobsmith/commit/a67628a), [4cd8486](https://github.com/rawcache/Jobsmith/commit/4cd8486), [b6c520c](https://github.com/rawcache/Jobsmith/commit/b6c520c), [414f6d0](https://github.com/rawcache/Jobsmith/commit/414f6d0). `scripts/canary/canary.py` and
      `.github/workflows/canary.yml` (Mondays and on demand; contents read, issues write, no secrets). It picks a
      current posting from each site's public job list, opens it behind `jobsmith/readonly.py`, and fails on too few
      fields, a field with no words of its own, an unknown kind, an email or upload read as the wrong kind, a missing
      name, email or resume, or (Greenhouse) a new question kind in any section of its job API.
      `tests/test_canary.py` runs it on the saved forms offline. [Live run](https://github.com/rawcache/Jobsmith/actions/runs/41264108840)
      (Figma on Greenhouse, Palantir on Lever, Ramp on Ashby: all passed).
- [x] "Report this form" in the extension panel and on each application in the dashboard: saves the form's structure
      (labels and field types, no values) and opens a pre-filled GitHub issue for the user to review and post.
      Nothing is sent automatically.
      Evidence: `jobsmith/formreport.py` builds the new-issue link (each question's words, kind, required, choices;
      the site and the page's path without its query string; emails, phone numbers and long numbers masked; cut to
      a length GitHub takes). The panel sends only those four things per field and background.js opens only a
      new-issue link on this repo (`test_report_this_form_sends_the_questions_and_never_what_you_typed`); the
      dashboard's Application tab links it from the saved questions (`/api/jobs/{id}/form-report`).
      `tests/test_formreport.py`.
- [x] A page on the site, "How Jobsmith behaves on job sites": caps, AI-policy respect, posting traps ignored, never
      submitting without verified answers, sign-ins handed to you, read-only canaries, what data leaves your
      computer.
      Evidence: [e14e3f0](https://github.com/rawcache/Jobsmith/commit/e14e3f0), [9e9cf95](https://github.com/rawcache/Jobsmith/commit/9e9cf95). `site/behaviour.html`, linked from the home page's footer, also says
      the emailed-code rule word for word. `test_the_behaviour_page_fits_every_width_and_is_linked_from_home`
      (320 to 1440 px, a wide font, no scripts or requests). [Live](https://rawcache.github.io/Jobsmith/behaviour.html),
      deployed by the [site run](https://github.com/rawcache/Jobsmith/actions/runs/41273551444).
- [x] A CI test proving the practice copy's autopilot runs end to end with every AI provider blocked.
      Evidence: [2d19d9a](https://github.com/rawcache/Jobsmith/commit/2d19d9a), [d8a60d2](https://github.com/rawcache/Jobsmith/commit/d8a60d2). `tests/test_no_ai.py`: with no AI connected, and with each of
      Anthropic, OpenAI and Gemini unreachable (their hosts refused, the claude and ollama programs refused), the
      practice copy's autopilot submits a plain form with every answer traced to the profile, resume or a file,
      holds an optional cover letter box and a written question for you, and never reaches an AI host. An unreachable
      AI is now an AI error, so the profile's answers still go in. [CI run](https://github.com/rawcache/Jobsmith/actions/runs/41273551352) (Linux, macOS, Windows).
- [x] A "What works without AI" table in the README.
      Evidence: [2d19d9a](https://github.com/rawcache/Jobsmith/commit/2d19d9a). [README.md](../README.md#what-works-without-ai): each part of Jobsmith, what it does
      with no AI, and what waits for you.

## 10. Ready for strangers

The launch gate's third check: someone who isn't a developer installs Jobsmith and reaches a first real application
in under 15 minutes without help.

- [x] First-run setup, in the dashboard and mirrored in the terminal, in this order: the resume PDF first; confirm
      every value read from it; one list of every one-time question, each with a default (none for work
      authorization, sponsorship or the employer-list claim, which only the user answers) and a one-line "why we
      ask" (work authorization, sponsorship, "my resume lists every employer", in person or relocating "only in my
      chosen locations", pay expectation, years of experience and whether internships count, start date, voluntary
      questions "decline to answer", optional saved answers); preferences (level, role types from a picker,
      locations); job lists from presets (SimplifyJobs internships, new grad) instead of board addresses.
      Done: `jobsmith/onboarding.py`, `web/src/pages/Onboarding.tsx`, `jobsmith/tui.py` (`jobsmith setup`);
      `tests/test_setup.py`; walked through the dashboard on a clean folder by `tests/test_setup_walk.py`;
      screenshots of every step in [images/setup/](images/setup/).
- [x] Nothing is drafted and autopilot stays off until setup is done; then the supervised first run. No pile of
      "Needs you" on day one: one application waits for approval at a time, one per job site.
      Done: `scheduler.enabled`, `guardrails.first_run_room`; `tests/test_setup.py`
      (`test_day_one_*`, `test_setup_gates_*`).
- [x] Matches narrowed to the user's level, role types, locations and fit bar, with a live "N matches" count in
      setup, aiming for tens to low hundreds. Find and fix why the maintainer's copy counted 3828 good matches and 75
      needing them.
      Done: `match.scope`, `match.preview`. Why 3828: both levels on (two full job lists), no locations, four role
      types, and a fit bar of 40 under a baseline score of 72 with no posting text read, so nearly every open role
      counted. Why 75: closed postings still counted, and setup's Start queued up to ten first applications at
      once. The same copy previews 138 to 367 matches once a level, two role types and places are chosen. It
      applies to an existing copy when setup is run again.
- [x] "Needs you" in two parts: "About you, answer once" and "About one job" (under that company and role, with
      "Skip this job"). An answer for one job is never reused for another; questions many jobs ask become profile
      answers.
      Done: `fixes.compute` (`part`, `questions`), `fixes.skip_job`, `drafts.scope`; dashboard
      `web/src/components/Fixes.tsx` ([picture](images/needs-you.png)), terminal `tui.review_fixes`;
      `tests/test_fixes.py` (`test_needs_you_is_about_you_once…`, `test_an_answer_for_one_job_is_never_reused…`,
      `test_skip_this_job…`).
- [x] Terminal: every line names the company and the role; repeated events collapse ("TikTok · 3 roles couldn't
      finish"); start-up shows one summary line ("12 ready for you, 3 couldn't finish · /review"), not one line per
      job; "couldn't finish" always says why; the log and the list always show the same status.
      Done: `jobsmith/words.py` (one wording and one plain reason for the log, the Review list and the API),
      `tuiapp._paint_state`, `Review.show_jobs`; `tests/test_tuiapp.py` (`test_every_log_line_names…`,
      `test_couldnt_finish_always_says_why…`, `test_start_up_says_one_summary_line…`).
- [x] `docs/getting-started.md` with screenshots: install, setup, first approval, daily use, troubleshooting
      (keychain prompt, a lost terminal, Gemini's free limit, a sleeping Mac and `caffeinate`). The README leads
      with it; the extension is marked optional, with the developer-mode steps.
      Done: [getting-started.md](getting-started.md); README "Quick start" and "Chrome extension (optional)".
- [x] A CI test that walks first-run setup on a clean data folder through the dashboard, and
      `docs/launch/usability-test.md`: a script for watching 3 non-developers set up, with the 15-minute target.
      Done: `tests/test_setup_walk.py` (a real engine on a free port against an empty folder, the seven steps
      through the dashboard; it runs with the rest of CI) and [launch/usability-test.md](launch/usability-test.md).
      The three watched runs themselves are the gate's third check, still to do.
- [ ] The Chrome Web Store listing prepared, not submitted: description, screenshots, privacy answers, permission
      justifications from SECURITY.md. (Submitting stays in Phase 3.)
      Partly done: [launch/chrome-web-store.md](launch/chrome-web-store.md) has the description, privacy answers
      and a justification for every permission, checked against the manifest and SECURITY.md. Left: the five
      screenshots ([#54](https://github.com/rawcache/Jobsmith/issues/54)).

Moved out of Phase 1: the full fit breakdown ([#6](https://github.com/rawcache/Jobsmith/issues/6)) and any
OpenAI-compatible AI ([#7](https://github.com/rawcache/Jobsmith/issues/7)), both Phase 2. The whole plan is in
[ROADMAP.md](ROADMAP.md).

Phase 1 is done when every box is ticked and all three gate checks pass: the first two on real applications, the
third with three people watched through the usability test.
