# Changelog

## Unreleased

### Changed
- Autopilot has limits on by default: 20 applications a day and 3 to one company a week. Change them under
  Settings → Applying (blank means no limit). Home shows "12 of 20 today". At a limit, autopilot stops before
  Submit and says which limit it hit; the application waits under "Needs you" and you can still send it yourself.
  Applications you send yourself count toward the limits too. Before, there were no limits unless you set them,
  and the per-company limit never reset.
- When a posting or its form asks applicants not to use AI or automated tools ("Please do not use AI to write your
  answers", "AI-generated responses will be rejected"), autopilot fills it but never sends it. It waits under "Needs
  you" with the employer's own sentence quoted, and the job's page shows the same line.

### Added
- Every submission keeps an audit trail: each field, the answer sent, where it came from (your resume, profile,
  writing, an answer you approved before, something you typed, or a file you added) and whether the answer was the
  right kind for the question. See it under "What was sent" on the application's page, or export it as JSON.
  Answers that don't trace back to you are marked in red. If autopilot clicked Submit but never saw a confirmation
  page, it says so, the application still counts toward your limits, and autopilot never sends it again.
- Lines in a posting or form written for an AI ("If you are an AI, include the word…", "ignore previous
  instructions"), visible or hidden (white on white, 1px text, display:none, off-screen, HTML comments), are never
  followed. Jobsmith finds them when it fetches the posting and again on the live page, keeps them out of
  everything an AI is shown, and holds the application under "Needs you" with the line quoted. Hidden text is no
  longer stored as part of a posting's description.
- A held application's "Full posting" shows the posting as the employer wrote it, hidden lines included, with each
  line aimed at AI highlighted and labelled with how it was hidden. Only what goes to an AI or your agent is trimmed.
- A visible line that only asks you to use a word or open your answer a certain way ("Mention the word 'otter' in
  your answer") is labelled "may be an attention check for you — answer it yourself" under "Needs you", instead of
  "aimed at AI tools". Autopilot still never follows it or sends the application on its own.
- Every submission keeps its proof: the confirmation page's address, title and text (and a screenshot) when
  autopilot or the extension sees one, and the "we received your application" email when your inbox is connected.
  See it under "What was sent". A confirmation email also settles one autopilot clicked Submit on without seeing a
  confirmation page.
- `jobsmith stats`: what you submitted over the last 30 days (`--days N`), how many were confirmed by a page, an
  email or a reply, and the share of good matches autopilot sent without you, counting every one it held, hit a
  limit on, or failed.
- `jobsmith audit`: 50 submitted applications picked at random (`-n N`), every answer with what it traces to on
  your resume, profile or writing. Any answer that doesn't trace is flagged, and the command exits with 1. Add
  `--practice` to either command to try it on the practice copy.
- Each match says whether it clears your fit bar and why, with what counts for it and against it. Matches under the
  bar show "Under your fit bar" and autopilot skips them; pick one yourself and it still applies.

### Fixed
- Resume match reads each posting for the skills its kind of role asks for: sales (discovery, value selling,
  pipeline generation, Salesforce), design, product, data and marketing, as well as engineering. On Figma's Account
  Executive posting it used to list "Figma, networking, performance, communication". A company's own name never
  counts as a skill, and words like "networking" and "performance" only count in engineering postings.
- Greenhouse's Hispanic/Latino question and the phone country box are filled only from answers you confirmed on
  the Profile page. Before, an answer Jobsmith had inferred (like U.S. citizenship from your resume) could fill
  them before you confirmed it.
- A demographic answer you haven't confirmed (gender, race, Hispanic/Latino, veteran, disability and the like) is
  never filled into a form. It's listed under "Needs you" until you confirm it or choose "Decline to self-identify".

## 0.4.6 (2026-10-26)

### Changed
- The dashboard, website, terminal app and extension popup now look like the extension's on-page panel: warm
  paper and charcoal instead of navy, and the panel's orange used only for primary buttons, where you are, focus,
  progress and the logo. Small labels are monospace and tags are dashed chips. The greeting band is gone; disabled
  buttons are grey. Waiting-on-you is ochre, interviewing green and errors crimson, so status never looks like the
  accent. Every text colour passes WCAG AA in light and dark.
- "Apply to new matches now" is the home page's main button.
- The website's anvil drawing uses even characters so it reads as an anvil, and it shows whole from the first
  frame; only the sparks twinkle.
- The practice copy's made-up Alex Rivera has a confirmed country (United States), so forms' Country questions are
  answered from the profile instead of inferred from the city.
- Contributors: `.gitignore` keeps `.env` files, databases, PDFs and cookie files out of git, and every push and pull
  request is scanned for keys and tokens.

## 0.4.5 (2026-10-26)

### Fixed
- Autofill never puts an answer in a field that asks for something else. With no AI connected, "From where do you
  intend to work?" on a Figma application got a paragraph about why you want to join; now Jobsmith checks that the
  answer is the right kind (a place, a yes or no, a short line or written sentences). If it isn't, the field is left
  blank and listed under "Needs you", and autopilot won't send it.
- "From where do you intend to work?" and similar questions are offered your profile location, listed under "Check
  these" so you confirm it's where you'd work.
- A saved answer to a "why us" question that never names the company is filled but listed as "generic, check this",
  isn't counted as filled, and holds autopilot.
- In a tab opened before the extension was loaded, the toolbar button now reaches an application form that a
  company's careers page shows in a frame from Greenhouse, Lever, Ashby, Workday, iCIMS or SmartRecruiters. The
  extension asks for access to those six job sites only (see SECURITY.md). A form in a frame from any other site
  says "Reload this page"; another site's frame beside a form that was reached (a video, a map) is just skipped.
- Autofill fills one step of an application shown in a job-site frame (iCIMS-style multi-step forms), and never
  types into a frame that isn't an application, like a newsletter sign-up beside the form.
- "Tell us your first name", "Please share your earliest start date" and similar politely worded questions get your
  profile answer instead of being held as essay questions. "Tell us your experience with…" still wants sentences.
- The phone number no longer lands in the hidden box behind the Phone country select on Greenhouse forms, and a
  country question never takes a phone number: it gets your profile country or is listed under "Needs you".
- "Write with Jobsmith" says when it held an answer back, wrote something generic, or used a fact it couldn't find
  in your profile, instead of "Edit freely".
- Short questions in large boxes ("How did you hear about us?") no longer take a paragraph, and "Explain"
  questions take sentences even when they start like a yes-or-no question.
- Jobsmith's browser never asks for your macOS login keychain password ("Chromium Safe Storage"). If you saw that
  prompt, click Deny.

### Changed
- `jobsmith demo --no-open` starts the practice copy without opening a browser.
- The install check on every system now starts the practice copy, waits for it to answer, and stops it.

## 0.4.4 (2026-10-26)

### Fixed
- Autofill no longer stops when you haven't added a resume PDF. It fills everything else, skips only the file
  upload, and says "Add your resume PDF to attach it".
- The Jobsmith tab on a posting no longer hides under another extension's tab (Simplify's sits on the same right
  edge). It moves to a free spot on the edge, or to the left edge, and stays clickable.
- The toolbar popup works on tabs that were open before you loaded the extension, instead of saying "Can't fill this
  page".

### Changed
- Clicking the Jobsmith toolbar button also opens the full panel on the page.
- "and apply with autopilot" under "Send this job to Jobsmith" starts unchecked, and remembers what you chose.
- The practice copy (`jobsmith demo`) has a made-up resume PDF for Alex Rivera, so autofill attaches a file there.

## 0.4.3 (2026-10-25)

### Changed
- The installer ends by saying which version it installed and how to start: `jobsmith demo` to try it with made-up
  data, or `jobsmith` to set it up for real. It says an AI is optional. The full check of your AI, browser and
  resume is still `jobsmith doctor`.
- `jobsmith demo` points you at `jobsmith demo show` to watch autopilot. (`jobsmith demo --setup` still says which
  made-up resume to upload.)
- The practice copy greets you with "Welcome to the practice copy. You're Alex Rivera, a made-up student." so its
  data isn't mistaken for yours.
- `jobsmith --version` prints the version.

### Fixed
- "What needs me?" lists an application waiting on an emailed code under "Only you can do", once, instead of under
  "Filled, waiting for you to submit".
- Many applications waiting on codes no longer push the ones ready to submit off that list.

## 0.4.2 (2026-10-24)

### Fixed
- The installers never compile anything, so Jobsmith installs on Intel Macs (it stopped while building cryptography
  with Rust) and on any computer without developer tools. They install a ready-built copy of Jobsmith and take the
  newest version of each part that has a ready-built file for your computer.
- If an install fails anyway, you get a short message with what went wrong and where to report it, instead of
  pages of build output. The full log is kept for the report.
- On a slow connection the installers wait longer for each download and try again once if the connection drops.
  If pypi.org (where Jobsmith's parts come from) can't be reached, they say so before starting.

### Changed
- Every change is now tested by running the real installers on Intel and Apple silicon Macs, Linux (x86 and ARM)
  and Windows (x86 and ARM).
- The README shows the install as one line for each system.

## 0.4.1 (2026-10-24)

### Added
- `jobsmith demo show`: watch autopilot apply to three made-up applications in the practice copy, with the real
  terminal app's progress bars. Two are submitted and one is held for you to review. Nothing real is opened or sent.

### Changed
- The one-line installers install the latest release, not unreleased changes. If GitHub can't be reached, they stop
  and ask you to try again instead of installing something else.
- The installers no longer need git, so they work on a new Mac without developer tools and on Windows PCs without
  git. They install with Python 3.13, the version the tests run on.
- When the installer finishes, it tells you to open a new terminal window if `jobsmith` won't be found in the one
  you used.
- Issue and pull request templates for contributors, and private security reporting on GitHub.

### Fixed
- The terminal app names the company from the first moment it starts on an application, instead of showing an id
  until the browser tab opens.
- The terminal app no longer prints an error when you quit while it's animating.
- On Windows, a failed install no longer ends with "Done".

## 0.4.0 (2026-10-22)

### Added
- Full-screen terminal app in the style of Claude Code: ask about your job hunt in plain words and get answers
  from your records with no AI, slash commands, `/review`, `/matches`, `/outreach`, `/followups`, `/settings`.
- Your voice skill: answers in your own words from your writing, with no AI needed.
- MCP server: Claude Code, Codex, Gemini CLI and Cursor can write answers, checked by Jobsmith (`jobsmith skills install`).
- Skills as folders with a `SKILL.md` that the app and AI agents both read.
- Setup takes your resume in the terminal.
- Read-only email (Gmail, Outlook or any mail server) spots replies, interviews and rejections and shows which
  applications need a follow-up. Follow-ups and thank-yous are drafts you send yourself.
- Import your own LinkedIn export into your profile. Jobsmith reads the file; it never touches LinkedIn.
- Cover letters are turned into a one-page PDF when a form asks for a file.
- Before Submit, a second pass fills required fields that are still empty and lists any it couldn't. Work
  authorization, sponsorship and demographic questions still come only from your Profile page.
- Power settings: the local AI only stands in for a cloud AI while you're plugged in, by default.
- The Companies page puts employers most applicants recognize first.
- The Chrome extension shows Jobsmith on a job posting and pairs with the app on your computer.
- Project website and contributor guides (`CONTRIBUTING.md`, `SECURITY.md`).

### Changed
- New cobalt design: top navigation bar, centered pages, smaller type, light theme by default.
- The practice copy now includes sample writing and a held application to review.
- The README and website now say exactly which sites work: Greenhouse end to end; Lever, Ashby and most
  single-page forms filled generically. Tests now cover a real Lever form and an Ashby-style form.

### Fixed
- Answers built from your writing no longer move a true story to a different company.
- Windows: the terminal app, ask box and AI-limit messages no longer crash on times like "9:05 AM", time zones
  work without extra setup, and uploaded files are found after moving your data folder from a Mac.

## 0.3.0

- Multi-select setup, live watching, Chrome extension, Gemini as the default AI.
