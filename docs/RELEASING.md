# Releasing

1. `git pull` on `main`; the `tests` and `install` workflows are green on every system.
2. Bump the version in `pyproject.toml`, `jobsmith/__init__.py` and `extension/manifest.json`.
3. `cd web && npm run build`, then `uv run jobsmith check` (tests, build, screenshots). Look at the screenshots.
4. Add the release to `CHANGELOG.md`: Added · Changed · Fixed, in user words.
5. Check nothing personal is staged: `git status`, and search the diff for keys and real names.
6. Commit `Release vX.Y.Z`, then `git tag vX.Y.Z && git push && git push --tags`.
7. Build the wheel from the tag (`uv build --wheel -o dist`) and zip `extension/` as `jobsmith-extension-X.Y.Z.zip`.
8. Create the release with both files in one command, so it is never public without its wheel:
   `gh release create vX.Y.Z dist/jobsmith-X.Y.Z-py3-none-any.whl jobsmith-extension-X.Y.Z.zip --title "vX.Y.Z"
   --notes-file <(sed -n '/## X.Y.Z/,/## /p' CHANGELOG.md)`.
9. Publishing starts the `install` workflow on the release itself: the real installers on Intel and Apple silicon
   macOS, Linux x86 and ARM, Windows x86 and ARM. Check it passes.

The one-line installers (`install.sh`, `install.ps1`) install the **latest GitHub release tag**, not `main`, with
Python 3.13, the version CI tests. They install the release's wheel with `--no-build`, so nothing is compiled on
the user's computer: where a package's newest version has no wheel for it (cryptography 50 on Intel Macs), uv picks
the newest version that has one. A release without a wheel falls back to GitHub's source archive (no git needed),
still refusing to build the packages with compiled parts (the `native` list, checked against `uv.lock` by
`tests/test_install.py`). Musl Linux (Alpine) isn't supported: Playwright has no wheel for it.
They fall back to `main` only when the repo has no release at all (GitHub answers 404); if GitHub can't be
reached or rate-limits the lookup, they stop and ask the user to try again. So nothing reaches new installs
until step 7 publishes the release, and a bad commit on `main` doesn't ship by itself. Publish the release only
after CI is green on the tagged commit.

## CI runners and actions

Every workflow runs on `ubuntu-24.04`, not `ubuntu-latest`, so GitHub's move of `ubuntu-latest` to Ubuntu 26 can't
change the test system under a release. Move to 26 deliberately: change the label in every workflow in one commit
(`grep -rn ubuntu-24.04 .github/workflows`), run `tests` and `install` on it, and fix what breaks before a release.
Actions are pinned by commit SHA with the version in a comment; update both together.

If GitHub can't find a hosted macOS runner for a `tests` job ("The job was not acquired by Runner of type hosted
even after multiple attempts"), `retry-runner` runs that job once more. It never reruns a job that started, so a
test failure is never retried.
