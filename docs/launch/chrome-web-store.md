# Jobsmith: Chrome Web Store listing draft

Prepared for Phase 1 item 10; submitting is Phase 3 (ROADMAP).

Prepared only; nothing has been uploaded or submitted. See [ROADMAP](../ROADMAP.md) and
[Phase 1](../PHASE1.md). Screenshot paths below are TODOs, not existing assets
([#54](https://github.com/rawcache/Jobsmith/issues/54)).

## Review against SECURITY.md and the manifest (2026-11-09)

Checked line by line against `extension/manifest.json`, [SECURITY.md](../../SECURITY.md) and the three scripts:

- **Permissions match.** The manifest asks for `storage`, `activeTab` and `scripting`, and eight host permissions
  (two for this computer, six job sites). Each has a row below, none is justified that the manifest doesn't ask
  for, and the six job sites are the same six SECURITY.md lists and `tests/test_extension.py` checks.
- **Every code reference was found** where the draft says it is: `chrome.storage.local.get("engine")` and
  `DEFAULT_ENGINE` in `background.js`; `panelOpen`, `isPosting`, `holdsForm`, `checkThanks`, the `jobsmith-submit`
  marker with its ten-minute limit, and the 20,000- and 4,000-character caps in `content.js`; `applyWithAutopilot`,
  `JOB_SITES` and `allFrames: true` in `popup.js`.
- **The content script's reach is stated, not hidden.** It runs on every page (`https://*/*`, `http://*/*`, all
  frames), which the store will ask about. The draft says so and says what it reads; SECURITY.md now says the same
  (what is read from a posting, and that "Report this form" opens GitHub at the user's click).
- **Site support matches the README**: end to end on Greenhouse, Ashby and Lever only; Workday, iCIMS and
  SmartRecruiters are named as partial.
- **Nothing here says more than the tests prove.** The short summary is 123 characters (the limit is 132).
- **Still to do before Phase 3:** the five screenshots (#54), a privacy policy page on the site (the checklist at
  the end), and a fresh read of the dashboard's wording on the day.

## 1. Store fields

| Field | Prepared value |
|---|---|
| Name | Jobsmith |
| Short summary | Fill job applications from your profile, check your resume match, and draft answers with the Jobsmith app on your computer. |
| Category | Productivity |
| Language | English (United States) — en-US |

### Full description

Jobsmith adds a panel to job postings so you can fill applications from your saved profile and keep track of the
roles you find. It needs the local Jobsmith app running on your computer at http://127.0.0.1:8765. Install and set
up the app first: https://rawcache.github.io/Jobsmith/.

On a job posting, open the Jobsmith panel to:

- Fill the current application from your profile and saved answers, and attach your resume PDF.
- See which skills in the posting appear on your resume and which are missing.
- See people you know at the company, if you have added your connections to Jobsmith.
- Write a cover letter or use “Write with Jobsmith” beside an open question to draft an answer you can edit.
- Save the role to Jobsmith, open it in the app, or ask the app to apply.

Click “Autofill this page” or press Alt+J. Autofill fills the page without pressing Submit. Check the answers and
submit when you are ready. Jobsmith leaves questions it cannot answer for you. Profile answers work without AI;
written answers can use your saved answers or your own writing. Cover letters need an AI connected in the app.

The toolbar popup also shows what applications need from you. Save a missing answer once to help the local app
recheck applications waiting on it. If you have allowed automatic applications, resolving a missing answer can
let the app start them within your limits.

The local app supports applications from start to finish on Greenhouse, Ashby and Lever only. Its first
application, and its first on each new job site, waits for your approval. Autofill can help with forms on other
sites that you review and submit yourself; those sites do not have proven support from start to finish. Workday
stops at review, and iCIMS and SmartRecruiters have partial support.

Jobsmith uses your confirmed profile for work authorization, sponsorship and demographic answers. It never sends
messages, types passwords or solves CAPTCHAs. You handle sign-ins and account creation. Referral requests and
follow-ups remain drafts for you to send.

Jobsmith has no account service, no Jobsmith servers and no telemetry. The extension sends its requests only to
your own local app. When you fill a form, the job site can read the answers and files you put on its page. The
local app contacts job sites and, if you choose one, your AI provider; it can also read your own connected inbox.
Choose a local model or no AI if you do not want to use an outside AI provider. You remain responsible for what
you submit in your name.

Read how Jobsmith behaves: https://rawcache.github.io/Jobsmith/behaviour.html.

### Evidence for the copy (not part of the store description)

- [README](../../README.md): “Supported sites,” “Safe by design,” “Works with a weak AI, or none,” and the extension
  description under “The other ways in.” [Behaviour page source](../../site/behaviour.html): limits and data flow.
- [tests/test_fill.py](../../tests/test_fill.py): Greenhouse saved-form coverage,
  `test_autopilot_sends_the_saved_lever_form_once_everything_is_answered` and
  `test_autopilot_sends_the_saved_ashby_form_once_everything_is_answered` support the three-site claim.
- [tests/test_extension.py](../../tests/test_extension.py): autofill tests watch for submissions and navigation;
  resume attachment, held written answers, confirmed legal answers, manual submission confirmation, popup fixes,
  and remembered preferences have specific coverage. These are saved forms and test stand-ins, not a claim that
  tests submit to live employers.

## 2. Screenshots to take

Take exactly these five screenshots at **1280 × 800 pixels**. Use the made-up Alex Rivera profile and saved forms
or test stand-ins. Keep all employer submissions blocked; do not use real applicant data. The practice app uses
port 8766, so point the screenshot session's extension at that local practice address. Capture the actual UI;
these captions describe the state to show.

| # | Page and state | Caption | TODO path |
|---|---|---|---|
| 1 | Saved Greenhouse posting, local app connected, panel open with role details and Resume match visible. | See how your resume matches the role. | TODO: `docs/launch/cws/resume-match.png` |
| 2 | Saved Lever application after Autofill; show filled contact fields, attached demo resume and the instruction to check before submitting. Do not click Submit. | Fill from your profile, then check and submit yourself. | TODO: `docs/launch/cws/autofill-review.png` |
| 3 | Saved Ashby application with an open written question; show “Write with Jobsmith” and its editable draft with the source note. | Draft an answer from your own facts and edit it freely. | TODO: `docs/launch/cws/write-answer.png` |
| 4 | Job posting behind the open toolbar popup; show “Needs you,” one missing fact and its count of applications it unblocks, before saving. | Answer once for applications waiting on the same fact. | TODO: `docs/launch/cws/needs-you.png` |
| 5 | Saved form's thank-you page after a simulated manual submission; show “Application submitted” in the panel and local application logging. | Keep a record when you submit an application yourself. | TODO: `docs/launch/cws/submission-record.png` |

## 3. Privacy practices tab

Prepared answers follow the [Chrome Web Store privacy-field guidance](https://developer.chrome.com/docs/webstore/cws-dashboard-privacy).
Recheck the dashboard's wording before Phase 3 submission. The choices below disclose data handled for the
feature, even though Jobsmith does not receive it on a developer server.

### Single purpose statement

Help the user complete and track job applications from their own saved profile through the Jobsmith app running
on their computer.

### Permission justifications

The permission set comes from [extension/manifest.json](../../extension/manifest.json). The scope and embedded-form
reason come from [SECURITY.md](../../SECURITY.md), “What the extension may reach.” Each row identifies and quotes
the code that uses the permission.

| Permission | Prepared justification and code evidence |
|---|---|
| `storage` | Remember the local app address, whether the page panel is open and whether the user selected automatic applications in the popup. `extension/background.js`: `chrome.storage.local.get("engine")`; `extension/content.js`: `chrome.storage.local.set({ panelOpen: true })`; `extension/popup.js`: `chrome.storage.local.set({ applyWithAutopilot: $("apply").checked })`. These preferences stay in local extension storage. Resume and answer records live in the local app. |
| `activeTab` | On a toolbar click, identify the current tab and reach its page so the popup can offer autofill or save that job. This also grants temporary access to a tab opened before installation. `extension/popup.js`, `activeTab()`: `chrome.tabs.query({ active: true, currentWindow: true })`; the save action passes `url: tab.url, title: tab.title` to the local app. It does not request the browser's history. |
| `scripting` | Add the packaged page script when the user opens the toolbar popup on a tab that predates installation or extension reload. Reach permitted embedded job forms too. `extension/popup.js`, `pageScript()`: `chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] })` and the corresponding call with `allFrames: true`. |

### Host permission justifications

| Host permission | Prepared justification and code evidence |
|---|---|
| `http://127.0.0.1/*` | Reach the user's own Jobsmith app for profile answers, attachments, saved jobs and application records. `extension/background.js`: `const DEFAULT_ENGINE = "http://127.0.0.1:8765"` and `fetch(base + path, ...)` in `call()`. Chrome's host pattern covers ports; the normal app uses 8765. |
| `http://localhost/*` | Allow the same local connection when the stored app address uses localhost. `extension/background.js`, `engine()`: `return (engine || DEFAULT_ENGINE).replace(/\/$/, "")`; `call()` and `file()` fetch from that address. This is the user's computer, not a Jobsmith server. |
| `https://*.greenhouse.io/*` | Reach an embedded Greenhouse application in a tab opened before installation, after the user clicks the toolbar. `extension/popup.js`, `JOB_SITES` includes `greenhouse\.io`; `pageScript()` injects packaged `content.js` with `allFrames: true`. |
| `https://*.lever.co/*` | Reach an embedded Lever application in the same toolbar recovery flow. `extension/popup.js`, `JOB_SITES` includes `lever\.co`; `pageScript()` uses `allFrames: true`. |
| `https://*.ashbyhq.com/*` | Reach an embedded Ashby application in the same toolbar recovery flow. `extension/popup.js`, `JOB_SITES` includes `ashbyhq\.com`; `pageScript()` uses `allFrames: true`. |
| `https://*.myworkdayjobs.com/*` | Reach an embedded Workday application step in the same toolbar recovery flow. `extension/popup.js`, `JOB_SITES` includes `myworkdayjobs\.com`; `pageScript()` uses `allFrames: true`. This permission does not imply support from start to finish. |
| `https://*.icims.com/*` | Reach an embedded iCIMS application step in the same toolbar recovery flow. `extension/popup.js`, `JOB_SITES` includes `icims\.com`; `pageScript()` uses `allFrames: true`. Account creation and sign-in remain the user's task. |
| `https://*.smartrecruiters.com/*` | Reach an embedded SmartRecruiters form in the same toolbar recovery flow. `extension/popup.js`, `JOB_SITES` includes `smartrecruiters\.com`; `pageScript()` uses `allFrames: true`. This permission does not imply support from start to finish. |

The manifest also declares content-script matches `https://*/*` and `http://*/*`, with `all_frames: true`. These let
the panel and autofill work on company careers pages and embedded forms after page load. `extension/content.js`
uses `isPosting()` and `holdsForm()` to recognize postings and forms. It scans field labels, kinds and choices;
`load()` sends the current page URL, title, site name and up to 20,000 characters of page text to the local app.
The broad matches are distinct from the eight host permissions above. An unlisted embedded site in an older tab
gets a reload hint rather than a new host permission. `tests/test_extension.py` checks the six-site list and
manifest permissions, plus embedded forms and reload hints.

### Data-usage checkboxes

Use these prepared selections to disclose handling, not to imply telemetry or sale. Optional profile answers and
documents may contain sensitive data, so do not describe the extension as handling no personal data.

| Dashboard data type | Prepared selection | What the extension handles |
|---|---|---|
| Personally identifiable information | Check | Name, email, phone, resume, education, work history, profile links, confirmed demographic answers and contacts shown for a company. `extension/content.js`: `fill()`, `attach()` and `render()`; the local app supplies the values. |
| Health information | Check | Optional confirmed disability-status answers used on application forms. `jobsmith/extension.py`, `answers()`, uses the shared answer rules; `jobsmith/draft.py` leaves questions asking for further disability details to the user. |
| Financial and payment information | Check | Desired pay supplied for application questions, if saved in the profile. `jobsmith/classify.py` maps salary questions to `desired_pay`; `jobsmith/extension.py`, `answers()`, returns profile answers for `extension/content.js` to fill. No payment processing or card collection. |
| Authentication information | Leave unchecked | Passwords and sign-in/account fields are excluded from autofill. `extension/content.js`: `isPassword()`, `accountBox()`, `scan()` and the sign-in checks in `fill()`. The extension does not need AI keys or inbox credentials from the local app. |
| Personal communications | Check | Cover letters and written application answers handled as drafts, including writing returned by the local app. `extension/content.js`: `attach()`, cover-letter actions and `addWriteButtons()`. The extension does not read an inbox or send messages. |
| Location | Check | Profile city/address and job location used for application answers and the panel. `extension/content.js`: `fillLookup()`, `fillOne()` and `render()`. It does not request device geolocation. |
| Web history | Check | Current posting and confirmation URLs and titles, saved to the local application record. `extension/popup.js` saves the active tab's URL/title; `extension/content.js`: `load()` and `checkThanks()`. No browser-history API or record of unrelated browsing. |
| User activity | Check | An application Submit click and its time, followed by a matching thank-you page, to log the user's submission. `extension/content.js` stores `jobsmith-submit` in the page's `sessionStorage` and consumes it in `checkThanks()`; records older than ten minutes are discarded when checked. No general keystroke or mouse tracking. |
| Website content | Check | Posting text, form questions/options, nearby question text and confirmation text. `extension/content.js`: `scan()`, `load()`, `addWriteButtons()` and `checkThanks()`. Confirmation text sent to the local app is capped at 4,000 characters. |

Nothing is sold or sent to Jobsmith servers; there are no Jobsmith servers or telemetry. Extension requests carrying
these data go only to the user's own local app through `extension/background.js`. The app stores the user's
profile, answers and application records locally. Extension storage holds preferences; the page's session storage
temporarily holds the submission marker described above.

Filling inserts answers and files into the employer's page, where that site may read or upload them even before
Submit. The local app may contact job sites, the user's chosen AI and their own connected email, as described in
`README.md`, `SECURITY.md` and `site/behaviour.html`. This draft does not promise that the whole app is offline.
“Report this form” is a separate user-requested action: `extension/background.js` opens a pre-filled GitHub issue
URL with form questions, never answers, for the user to check and post. Opening the link contacts GitHub; Jobsmith
does not post the issue automatically.

### Remote code

**None.** Select the dashboard's option indicating no remote code. The manifest loads packaged `background.js`,
`popup.js` and `content.js`; toolbar injection names the packaged `content.js`. Local app responses supply JSON,
text and documents, not executable code. The extension does not download and execute JavaScript or WebAssembly.

### Three required certifications

Prepared selections: check all three when completing the dashboard, after checking the release still matches
these statements. These are paraphrases of the dashboard certifications:

- [x] We do not sell or transfer user data to third parties outside the uses allowed by Chrome Web Store policy.
- [x] We use or transfer user data only to serve the extension's stated single purpose.
- [x] We do not use or transfer user data to assess creditworthiness or make lending decisions.

These are draft answers only; no certification has been submitted.

## 4. Pre-submission checklist

Complete in Phase 3, before uploading or submitting:

- [ ] Confirm the version in `extension/manifest.json` matches `pyproject.toml` and `jobsmith/__init__.py`.
  All three read `0.4.6` when this draft was prepared; recheck the release to submit.
- [ ] Build the store ZIP from the contents of `extension/`, with `manifest.json` at the ZIP root, the three
  scripts, popup HTML and icons included. Keep app files, local data and credentials out of it. Inspect the ZIP
  and load its extracted contents in Chrome before uploading. No ZIP was built for this draft.
- [ ] Publish a privacy policy on the project site and enter its working public HTTPS URL in the Privacy practices
  tab. **TODO URL:** `https://rawcache.github.io/Jobsmith/privacy.html` (proposed; no `site/privacy.html` exists
  at preparation time). Cover data types, local storage, retention/deletion, job-site form access, chosen AI,
  local-app transfers, the GitHub report action and the three certifications. The behaviour page supplies context
  but is not a completed privacy policy.
- [ ] Take all five screenshots above, confirm each is 1280 × 800, and verify every TODO path exists and contains
  only made-up applicant data.
- [ ] Recheck description, supported sites, permission justifications and privacy selections against the release's
  README, SECURITY, manifest, scripts and tests. Confirm the short summary is at most 132 characters.
- [ ] Confirm Phase 3 submission is authorized under the ROADMAP before any upload, submission or publication.
