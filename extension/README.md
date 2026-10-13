# Jobsmith for Chrome

Two buttons on any job site, powered by the Jobsmith app on your computer:

- **Fill this application.** Reads the form, gets answers from your Jobsmith profile (and your AI for open questions, with the same no-made-up-facts rules as autopilot), fills it, and attaches your resume. It never clicks Submit. Shortcut: Alt+J. It also offers itself when a page looks like an application.
- **Send this job to Jobsmith.** Adds the posting you're looking at to your matches, with your fit and eligibility, and (if you leave the box ticked) has autopilot apply.

The extension stores nothing about you. Everything stays in the Jobsmith app, which only answers requests from this computer.

## Install (until it's in the Chrome Web Store)

1. Run `jobsmith extension` to see where the folder is (or use `extension/` in a source checkout).
2. Open `chrome://extensions`, turn on **Developer mode** (top right).
3. Click **Load unpacked** and pick that folder.
4. Pin Jobsmith from the puzzle-piece menu.

Jobsmith (`jobsmith` in a terminal) needs to be running for the buttons to work. If it runs on a different port, set it in the extension's storage key `engine` (default `http://127.0.0.1:8765`).
