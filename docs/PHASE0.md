# Phase 0: Go public (Oct 22–31, 2026)

**Gate:** a stranger installs Jobsmith on a clean computer and reaches the practice copy in under 5 minutes.

Work top to bottom. Tick each box in this file as it's done and commit the tick with the work.

## 1. Clean the working tree

- [x] `git status`: about 84 changed files since the last push. Review them by area, not one by one.
- [x] Confirm nothing personal is staged: no `data/`, `_to_delete/`, `downloaded_simplify/`, `.env`, keys, tokens,
      real resumes or real names. Search: `git diff --cached | grep -iE "AIza|sk-ant|sk-[A-Za-z0-9]{20}|password|@gmail"`.
- [x] Remove dead files the restructure left behind (old `skills.py`, `outreach.py`, `followups.py` if present).
- [x] Commit in logical pieces: skills restructure · voice skill · MCP server · terminal app + ask box · cobalt
      redesign · docs. Push to `main`.

## 2. Make the public claims true

- [x] List every site the README, site/index.html and SKILL.md files say works "end to end".
      Only Greenhouse is claimed end to end; Lever/Ashby are described as "filled generically".
- [x] For each, confirm a test in `tests/test_fill.py` fills a saved fixture of that site up to the submit button.
      Lever and Ashby go through `fill/generic.py` and had no site fixture before this phase.
- [x] Either add fixtures + tests for Lever and Ashby (save a real public posting's form HTML, strip anything
      personal) or change the wording to "Greenhouse end to end; Lever, Ashby and most single-page forms filled
      generically". Added `tests/fixtures/lever_form.html` (sanitized real capture) and
      `tests/fixtures/ashby_style_form.html` (hand-written, modeled on Ashby's layout) + tests through
      `fill/generic.py`, stopping before Submit.
- [ ] Same check for the numbers in the README (tests count, sites, sources).

## 3. CI and release

- [ ] Make `.github/workflows/ci.yml` pass on ubuntu, macOS and Windows. Fix Windows failures or mark the specific
      tests `skipif` with a reason and an issue link.
- [ ] Turn on GitHub Pages (Settings → Pages → Source: GitHub Actions) so `pages.yml` publishes `site/`.
- [x] Bump the version to 0.4.0 in `pyproject.toml`, `jobsmith/__init__.py`, `extension/manifest.json`.
- [x] Fill in `CHANGELOG.md` 0.4.0 from the commits.
- [ ] Follow `docs/RELEASING.md` to tag `v0.4.0` and publish the GitHub release.

## 4. Contributor on-ramp

- [x] Move `docs/to-github/*` into `.github/` (`pull_request_template.md` and `ISSUE_TEMPLATE/`), then delete
      `docs/to-github/`. Review them with `CONTRIBUTING.md` and `SECURITY.md`.
- [x] Add `docs/templates/` to the README's Contributing section.
- [x] Create labels: `good first issue`, `help wanted`, `job site`, `skill`, `source`, `terminal`, `dashboard`,
      `extension`, `bug`.
- [x] Open the issues in `docs/good-first-issues.md` with `gh issue create` (one per section; title, body, labels).
- [x] Create GitHub milestones for Phases 1–5 with the dates from the roadmap.

## 5. Fresh-install test (the gate)

- [ ] On a clean macOS user account (or a fresh VM): run the one-line installer from the README, then
      `jobsmith demo`. Time it. Under 5 minutes, or fix what was slow.
- [ ] Same on Windows with `install.ps1`.
- [ ] Load the extension unpacked and confirm the panel appears on a Greenhouse posting.

## 6. The video

- [ ] Record 30 seconds in the practice copy: the terminal asks "what's waiting for me?", autopilot applies with the
      hammer animating, one application held for review and approved. Save as `docs/images/demo.gif` (under 8 MB)
      and put it at the top of the README.

## Carry to Phase 1

- [ ] Capture a sanitized real Ashby application form and test the generic filler against it.

Phase 0 is done when every box is ticked and the gate passes. Then start Phase 1 (`docs/PHASE1.md`, to be written).
