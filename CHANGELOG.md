# Changelog

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
