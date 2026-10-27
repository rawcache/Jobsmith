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
- [x] Confirm `main` history is clean: all 42 commits authored and committed by the maintainer, no `Co-Authored-By`
      lines (checked 2026-10-26). GitHub's Contributors sidebar is stale; GitHub Support has been asked to refresh it.

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

- [x] Make `.github/workflows/ci.yml` pass on ubuntu, macOS and Windows. Fix Windows failures or mark the specific
      tests `skipif` with a reason and an issue link. All three pass, plus the dashboard build
      ([run 40434098779](https://github.com/rawcache/Jobsmith/actions/runs/40434098779)). The only skips are
      platform ones (`install.sh` tests off Windows, `install.ps1` tests on it, browser tests with no Chromium), not
      hidden failures.
- [x] Turn on GitHub Pages (Settings → Pages → Source: GitHub Actions) so `pages.yml` publishes `site/`.
      Live at https://rawcache.github.io/Jobsmith/, published by
      [run 40431888492](https://github.com/rawcache/Jobsmith/actions/runs/40431888492).
- [x] Bump the version to 0.4.0 in `pyproject.toml`, `jobsmith/__init__.py`, `extension/manifest.json`.
- [x] Fill in `CHANGELOG.md` 0.4.0 from the commits.
- [x] Follow `docs/RELEASING.md` to tag `v0.4.0` and publish the GitHub release. Done for v0.4.0 and every release
      since; the latest is [v0.4.5](https://github.com/rawcache/Jobsmith/releases/tag/v0.4.5), whose install run
      starts the practice copy on all six machines
      ([run 40422272957](https://github.com/rawcache/Jobsmith/actions/runs/40422272957)).

## 4. Contributor on-ramp

- [x] Move `docs/to-github/*` into `.github/` (`pull_request_template.md` and `ISSUE_TEMPLATE/`), then delete
      `docs/to-github/`. Review them with `CONTRIBUTING.md` and `SECURITY.md`.
- [x] Add `docs/templates/` to the README's Contributing section.
- [x] Create labels: `good first issue`, `help wanted`, `job site`, `skill`, `source`, `terminal`, `dashboard`,
      `extension`, `bug`.
- [x] Open the issues in `docs/good-first-issues.md` with `gh issue create` (one per section; title, body, labels).
- [x] Create GitHub milestones for Phases 1–5 with the dates from the roadmap.

## 5. Fresh-install test (the gate)

- [x] On a clean macOS user account (or a fresh VM): run the one-line installer from the README, then
      `jobsmith demo`. Time it. Under 5 minutes, or fix what was slow.
      Passed 2026-10-24 on an Intel Mac (bash, conda active): install 25 s, `jobsmith demo` almost instant,
      `jobsmith demo show` played all 3 applications, the ask box answered from records. (v0.4.2)
- [x] Same on Windows with `install.ps1`. No Windows PC on hand; covered by `install.yml`, which runs the real
      `install.ps1` on `windows-latest` (x86) and `windows-11-arm` and checks nothing builds from source and
      `jobsmith --help` runs. Both passed for the v0.4.3 release (run 40164099148, 35 s and 1 min 45 s). Since v0.4.5
      it also starts `jobsmith demo`, waits for :8766 to answer and stops it, on all six machines: on Windows the
      practice copy answered in 8 s (x86) and 10 s (ARM)
      ([run 40422272957](https://github.com/rawcache/Jobsmith/actions/runs/40422272957)).
- [x] Load the extension unpacked and confirm the panel appears on a Greenhouse posting. Retested v0.4.5 on Figma's
      Greenhouse posting with Simplify installed (2026-10-26): the panel sits clear of Simplify's tab, autopilot
      starts unticked, the resume PDF attaches, nothing was submitted and there was no keychain prompt. "From where
      do you intend to work?" got the profile location under "Check these", the "why Figma" answer was flagged
      generic, and "Needs you" listed Country, Location (City), work authorization and "worked at Figma before".
      Country and Location are Greenhouse dropdowns the extension can't open yet
      ([#19](https://github.com/rawcache/Jobsmith/issues/19)).

## 6. The video

- [ ] Record 30 seconds in the practice copy: the terminal asks "what's waiting for me?", autopilot applies with the
      hammer animating, one application held for review and approved. Save as `docs/images/demo.gif` (under 8 MB)
      and put it at the top of the README.

## Carry to Phase 1

- [ ] Capture a sanitized real Ashby application form and test the generic filler against it. Tracked in
      [#18](https://github.com/rawcache/Jobsmith/issues/18).

Phase 0 is done when every box is ticked and the gate passes. Then start Phase 1 (`docs/PHASE1.md`, to be written).
