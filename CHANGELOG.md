# Changelog

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
