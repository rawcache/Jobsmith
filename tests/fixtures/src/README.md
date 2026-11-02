# Sources for built fixtures

## `greenhouse_select.jsx` → `../greenhouse_figma_live.html`

`greenhouse_board_posting.html` is the saved Figma application form (Greenhouse job-boards, blank). It has no
scripts, so its dropdowns can't open. `greenhouse_figma_live.html` is the same page with a script at the end. The
script replaces Country, Location (City) and two Yes/No boxes with real react-select (MIT), set up the way the live
form sets it up:

- Greenhouse controls the menu. It opens on key-up and mouse-up, not on react-select's own key-down or mouse-down.
- Location (City) searches a place lookup as you type. The lookup's answers here are the ones the live form gave for
  "Boston".
- Each box has react-select's hidden "required" input until something is picked.

That behaviour was observed on the live form on 2026-10-28, headless, with every non-GET request blocked. The script
contains none of Greenhouse's code.

To rebuild after changing the source:

```bash
mkdir -p /tmp/gh-select && cp tests/fixtures/src/greenhouse_select.jsx /tmp/gh-select/ && cd /tmp/gh-select
npm init -y >/dev/null && npm install react@18.3.1 react-dom@18.3.1 react-select@5.8.0 esbuild@0.21.5
npx esbuild greenhouse_select.jsx --bundle --minify --format=iife --jsx=automatic \
  --define:process.env.NODE_ENV='"production"' --legal-comments=eof --outfile=bundle.js
cd - && python3 -c "
html = open('tests/fixtures/greenhouse_board_posting.html').read(); js = open('/tmp/gh-select/bundle.js').read()
open('tests/fixtures/greenhouse_figma_live.html', 'w').write(html.replace('</body>', '<script>' + js + '</script></body>', 1))"
```

## `ashby_form.js` + `ashby_fixture.py` → `../ashby_ramp_form.html`

`ashby_ramp_form.html` is Ramp's application form for "Software Engineer, Frontend" on Ashby
(`jobs.ashbyhq.com/ramp/4e64ab86-4e30-403b-b1b9-41dc052570ce/application`), saved blank on 2026-10-29. Ashby builds
the form in the browser from two GraphQL reads, so it was saved with `scripts/capture/capture.py`, which lets
those two reads through and blocks every other non-GET (see the rule in `docs/PHASE1.md`). The capture has Ashby's
scripts removed; `ashby_fixture.py` inlines Ashby's stylesheet (so the hidden Yes/No checkboxes stay hidden),
drops everything that would load from the network, adds `ashby_form.js`, and refuses to write a page with an email
address or phone number in it other than Ashby's placeholders.

`ashby_form.js` is our stand-in for Ashby's script, none of Ashby's code. It does what the live form was seen
doing: a Yes/No button sets `aria-pressed` and ticks the hidden checkbox for Yes; each answer is autosaved with a
POST (`ApiSetFormValue`, not a submission); Submit Application sends `ApiSubmitSingleApplicationFormAction` and
the form gives way to Ashby's thank-you text (taken from Ashby's page script; the live Submit was never pressed).

To rebuild (the stylesheet is the `<link rel=stylesheet>` on the live page, saved with a plain GET):

```bash
uv run python scripts/capture/capture.py \
  https://jobs.ashbyhq.com/ramp/4e64ab86-4e30-403b-b1b9-41dc052570ce/application /tmp/ashby/captured.html
curl -s -o /tmp/ashby/ashby.css "<the page's stylesheet URL>"
uv run python tests/fixtures/src/ashby_fixture.py /tmp/ashby/captured.html /tmp/ashby/ashby.css \
  tests/fixtures/ashby_ramp_form.html
```

Check the result has no real person's details in it (the builder only catches emails and phone numbers).

## `workday_flow.js` + `workday_fixture.py` → `../workday_nvidia_*.html`

NVIDIA's "AI Systems Software Engineering Intern – Summer 2027" on Workday
(`nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-TX-Austin/…_JR2027170`), walked on 2026-10-31 through
`jobsmith/readonly.py` (GETs only; Google Analytics and LinkedIn's apply widget were blocked) from the posting to
sign-in, pressing Apply, Apply Manually, Sign in with email and Create Account and typing nothing. Each page was saved
with its scripts removed. `workday_fixture.py` drops what would load from the network (Workday's own stylesheet is one,
so the pages look plainer than live; the parts the tests use keep their markup and data-automation-ids), starts the
posting's "Start Your Application" box closed, adds `workday_flow.js`, and refuses a page with an email address, a
phone number or a typed value in it.

`workday_flow.js` is our stand-in for Workday's scripts, none of Workday's code: Apply opens the box, Apply Manually,
Autofill with Resume and Use My Last Application go to the sign-in choice, Sign in with email and Create Account go to
those pages, and the sign-in and create-account buttons send nothing (`window.__signInPresses` counts them). The
pages keep Workday's honeypot, "This input is for robots only, do not enter if you're human."

### Signed in: `workday_apply.js` + `workday_fixture.py --signed-in` → My Information … Review

The application itself (`workday_nvidia_my_information.html`, `_my_experience`, `_application_questions`,
`_voluntary_disclosures`, `_review`) was saved on 2026-11-01 from the maintainer's own Chrome, signed in, following
[docs/guides/save-workday-pages.md](../../../docs/guides/save-workday-pages.md). Those five are every page this
posting has (no Self Identify page). They were filled in by hand and by another autofill tool, so every value on them
is treated as a real person's. `workday_fixture.py --signed-in`:

- removes the other tool's markup whole (Simplify's panel, its fonts and its page margin) and stops if any is left;
- empties every box, unticks every choice, puts every dropdown in the form back to "Select One", removes every
  picked item, and writes Alex Rivera's address in place of the account's email address;
- swaps Workday's own ids (32-hex instance ids, UUIDs) for counters, the same one for the same id on every page;
- on Review, writes Alex Rivera's made-up answers in place of what was sent, by the box each sits in, and stops if a
  box it doesn't know holds an answer;
- rounds numbers in icon drawings and colours to one decimal place, so a search of the fixtures for someone's details
  (a GPA, a street number) never lands on an icon;
- then the same checks as the public pages: nothing from the network, no email but Alex's, no phone number but
  Alex's (on Review), nothing typed.

Workday adds its styles from its scripts, so the saved pages carry none and look plain. Before committing, also search
the result for the saver's own details (name, email, school, links, answers): the builder can't know them.

`workday_apply.js` is our stand-in for Workday's scripts on these pages, none of Workday's code and none of its lists
(every list was closed when saved, so the choices are ours, a few per box): a dropdown opens its choices and shows the
one picked; a search box (How Did You Hear About Us?, Country Phone Code, Field of Study, Skills) shows matching
choices after Enter in a list marked `activeListContainer` and adds the pick as a pill, as the saved pages show
picked items. That list's name and a dropdown's open list (`role="option"` items) are our best understanding of
Workday's, not seen on these saves: a check on a live Workday form is still to do; Save and Continue and
Back move between the pages after keeping each page's values in `window.name` for the tests; Submit on Review sends
nothing (`window.__submitPresses` counts it). Workday's Submit sits in the footer's Next slot
(`pageFooterNextButton`), as on the real Review page.

The page that shows Workday's errors when a required box is empty wasn't saved:
[#28](https://github.com/rawcache/Jobsmith/issues/28).

```bash
uv run python tests/fixtures/src/workday_fixture.py --signed-in SAVED_DIR tests/fixtures
```

To rebuild, walk the posting again with a read-only capture (save `2_start.html`, `3_after_manual.html`,
`4_signin_email.html` and `5_create_account.html`), then:

```bash
uv run python tests/fixtures/src/workday_fixture.py /tmp/workday tests/fixtures
```

## `icims_flow.js` + `icims_fixture.py` → `../icims_idemia_*.html`

IDEMIA's "Full Stack Software Engineering Internship" on iCIMS
(`uscareers-idemia.icims.com/jobs/8707/full-stack-software-engineering-internship/job`), walked on 2026-10-31 through
`jobsmith/readonly.py` (GETs only; analytics, New Relic and hCaptcha's site check were blocked) from the posting to
sign-in, pressing "Apply for this job online" and "Log back in!" and typing nothing. iCIMS draws the posting in its
careers page's `icims_content_iframe` frame, so the page around it and the frame were saved apart, scripts removed:
`icims_idemia_posting.html` loads `icims_idemia_posting_frame.html` in that frame; `icims_idemia_email_frame.html` is
what the frame shows after Apply ("Enter Your Information": Email, then Next, behind an invisible hCaptcha); and
`icims_idemia_login.html` is iCIMS's login at login.icims.com (Auth0's "Username or email address", Continue with
Google, LinkedIn…). `icims_fixture.py` drops what would load from the network (iCIMS's stylesheets too, so the
pages look plainer than live), the chat widget and the hCaptcha frames; blanks hCaptcha's site key, the login's
one-time state, iCIMS's link hashes and its customer number; adds `icims_flow.js`; and refuses a page with an email
address, a phone number, a typed value or a key left in it.

`icims_flow.js` is our stand-in for iCIMS's scripts, none of iCIMS's code: Apply moves the frame to the email step,
"Log back in!" opens the login in place of the page, and Next and every Continue send nothing
(`window.__signInPresses` counts them, in the frame or page the button is on).

The pages behind sign-in come from the maintainer's own browser: [docs/guides/save-icims-pages.md](../../../docs/guides/save-icims-pages.md).

### Signed in: `icims_fixture.py --signed-in` → `../icims_idemia_profile_frame.html`

Step 1 of 5 of the same posting's application, "Candidate Profile", saved on 2026-11-01 from the maintainer's
Chrome (Simplify off) as the frame shows it, blank but for the email iCIMS carried over from its email step. It asks
for your profile (resume, name, email, phone, address, how you heard, education level, work history, education) and
makes your account on the same page ("Create a login": Login, Password, Password (Re-enter); Submit Profile makes
it). Steps 2-5 weren't saved ([#31](https://github.com/rawcache/Jobsmith/issues/31)).

```bash
uv run python tests/fixtures/src/icims_fixture.py --signed-in ~/Desktop/jobsmith-pages/icims tests/fixtures
```

Besides the rules above, the builder sets the Email box to Alex's, blanks iCIMS's per-field hashes and the hCaptcha
widget's id, drops every attribute holding a URL (OneDrive's app key, hCaptcha's nonces) and keeps iCIMS's own
section names (`portalLabel…`: "Phones (1)").

On this page `icims_flow.js` also stands in for:

- iCIMS's search dropdowns (Country, State/Province, Highest Level of Education, School, Degree, Major…): the
  `<select>` is hidden, a link shows the choice and opens its list, and picking from the list fills the `<select>`.
  iCIMS loads each choice's value as you pick, so here a choice's value is its words; the lists are the 25 entries
  saved, and a country's State list is a short one of ours (the saved one was empty);
- the resume read: choosing a file shows "Parsing resume, please wait..." for a moment, then what was read replaces
  the form's boxes, as the page says it does. Here nothing is read, so they come back empty (`window.__resumeRead`
  counts it), which shows whether Jobsmith filled the form before or after the read;
- Submit Profile, which makes the account: it sends nothing, and `window.__signInPresses` counts it;
- iCIMS's stylesheet rules its widgets need (hidden `<select>`, closed lists, the reading notice) and no-ops for the
  page's inline handlers (`icimsChangeParent`).

To rebuild, walk the posting again with a read-only capture (save `1_posting_top.html`, the frame's `1_posting.html`,
the frame's `2_email.html` after Apply, and `3_auth0_top.html` after "Log back in!"), then:

```bash
uv run python tests/fixtures/src/icims_fixture.py /tmp/icims tests/fixtures
```

## `lever_form.js` + `lever_fixture.py` → `../lever_palantir_form.html`

`lever_palantir_form.html` is Palantir's application form for "Forward Deployed Software Engineer, Internship -
Commercial" on Lever (`jobs.lever.co/palantir/4d29249a-d7e8-4c39-880d-3b35d7b2f6f6/apply`), saved blank on
2026-10-30 with `scripts/capture/capture.py` (GETs only; every POST, including Lever's hCaptcha and analytics, was
blocked; see `jobsmith/readonly.py`). Lever puts its stylesheet in the page twice; `lever_fixture.py` keeps only the
rules the page uses, replaces Lever's web fonts with local ones, drops everything that would load from the network,
blanks Palantir's Lever account id, the Lever accounts that last edited each question, hCaptcha's public site key
(key-shaped, so the secrets scan stops on it) and the time zone the capture's browser filled in, and cuts Lever's hidden JSON copy of each question card to its first three options (the
visible university list keeps all 3,302). It refuses to write a page with an email address or phone number in it
other than the posting's own accommodations address, or with an editor's account id left in.

`lever_form.js` is our stand-in for Lever's scripts, none of Lever's code. It does what Lever's `application.js`,
`requiredCheckboxGroups.js` and `retrieveLocations.js` were read to do, and the live form was seen doing:

- choosing a resume shows its file name;
- a required group of checkboxes (Languages) stays required until one is ticked;
- Current location is a lookup: a key press searches after a pause, picking a place fills the box and the hidden
  `selectedLocation`, and leaving the box with the list open (without picking) empties both. The answers are the
  ones Lever's lookup gave for "Boston" (read through the same guard, typing in the live box, nothing sent);
- any answer to Disability status, even "I do not want to answer", shows Name and Date and makes them required;
- the cookie banner (saved with the page: the cookieconsent widget, fixed along the bottom of the window, over
  whatever is scrolled there) closes on Deny or Accept and stores the choice in `cookieconsent_status`, as that
  widget does; `window.__cookieChoice` records which (`tests/test_banners.py`);
- Submit application runs the captcha step (passes at once; `window.__captchaChallenge = true` shows a challenge
  frame instead), clicks Lever's hidden submit button so the browser checks required fields, then posts the form to
  its own address with `fetch` and shows Lever's "Application submitted!" (the words from Lever's thank-you page,
  read with a GET; the live Submit was never pressed).

To rebuild:

```bash
uv run python scripts/capture/capture.py \
  https://jobs.lever.co/palantir/4d29249a-d7e8-4c39-880d-3b35d7b2f6f6/apply /tmp/lever/captured.html
uv run python tests/fixtures/src/lever_fixture.py /tmp/lever/captured.html tests/fixtures/lever_palantir_form.html
```

Check the result has no real person's details in it (the builder only catches emails and phone numbers).

## `smartrecruiters_flow.js` + `smartrecruiters_fixture.py` → `../smartrecruiters_bosch_form.html`

`smartrecruiters_bosch_form.html` is Bosch's "Application Engineer" form on SmartRecruiters (its "Easy apply" page),
saved blank on 2026-10-31 from the maintainer's own Chrome with the console snippet in
[docs/guides/save-smartrecruiters-form.md](../../../docs/guides/save-smartrecruiters-form.md) (the guide's internship
posting had closed). SmartRecruiters shows a bot check to a headless browser, so this one wasn't captured by
`scripts/capture/`; no posting URL is kept. The form is drawn by web components whose insides are shadow roots, saved
as declarative templates (`<template shadowrootmode="open">`) that the browser turns back into shadow roots.

```bash
uv run python tests/fixtures/src/smartrecruiters_fixture.py ~/Desktop/jobsmith-pages/smartrecruiters.html tests/fixtures
```

The saved page stays outside the repo. `smartrecruiters_fixture.py` removes another browser extension's panel, fonts
and styles (Simplify's), everything that would load from the network (SmartRecruiters' stylesheets, flag images,
OneTrust's cookie script, links, and any attribute holding a URL), SmartRecruiters' company, publication and
channel ids, and gives each icon a size of ours (without SmartRecruiters' stylesheets they fill the page). It
refuses to write a page with an email address, a phone number, a typed value or anything left that loads from the
network.

`smartrecruiters_flow.js` is our stand-in for SmartRecruiters' scripts, none of its code:

- the phone's Country code button opens and closes its list (245 countries, United States picked, as saved), and
  picking one marks it and shows its code on the button;
- City suggests places from a short list of ours as you type (its list was empty when saved, so these are made
  up: what SmartRecruiters' own suggestions look like is still to be checked);
- the footer's Next sends nothing: `window.__nextPresses` counts it. The pages after Next weren't saved, so
  Jobsmith fills this page and stops on it.
