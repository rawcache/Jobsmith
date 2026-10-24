# Releasing

1. `git pull` on `main`; CI is green on all three systems.
2. Bump the version in `pyproject.toml`, `jobsmith/__init__.py` and `extension/manifest.json`.
3. `cd web && npm run build`, then `uv run jobsmith check` (tests, build, screenshots). Look at the screenshots.
4. Add the release to `CHANGELOG.md`: Added · Changed · Fixed, in user words.
5. Check nothing personal is staged: `git status`, and search the diff for keys and real names.
6. Commit `Release vX.Y.Z`, then `git tag vX.Y.Z && git push && git push --tags`.
7. `gh release create vX.Y.Z --title "vX.Y.Z" --notes-file <(sed -n '/## X.Y.Z/,/## /p' CHANGELOG.md)`.
8. Zip `extension/` as `jobsmith-extension-X.Y.Z.zip` and attach it to the release (`gh release upload`).
9. Check the one-line installer picks up the new version on a clean machine.

The one-line installers (`install.sh`, `install.ps1`) install the **latest GitHub release tag**, not `main`, from
GitHub's source archive (no git needed) with Python 3.13, the version CI tests.
They fall back to `main` only when the repo has no release at all (GitHub answers 404); if GitHub can't be
reached or rate-limits the lookup, they stop and ask the user to try again. So nothing reaches new installs
until step 7 publishes the release, and a bad commit on `main` doesn't ship by itself. Publish the release only
after CI is green on the tagged commit.
