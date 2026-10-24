#!/usr/bin/env bash
# Install Jobsmith on macOS or Linux:
#   curl -LsSf https://raw.githubusercontent.com/rawcache/Jobsmith/main/install.sh | sh
set -eu
repo="https://github.com/rawcache/Jobsmith"
issues="$repo/issues/new"
start_path="$PATH"      # the PATH your terminal has, to tell you whether `jobsmith` works in it right away
# uv's 30 s default gives up on a slow connection partway through a big download (Playwright is ~40 MB)
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-120}" UV_HTTP_RETRIES="${UV_HTTP_RETRIES:-5}"
# Packages with compiled parts. Never build them here: a computer without a wheel for the newest version (an Intel
# Mac for cryptography 50) would need Rust or a C compiler. uv then picks the newest version that has a wheel.
# Only used for a source install; a release wheel installs with --no-build, which covers every package.
# tests/test_install.py checks this list against uv.lock.
native="cffi cryptography fonttools greenlet httptools pillow playwright psutil pydantic-core pywin32 pyyaml rpds-py uvloop watchfiles websockets"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
# Install the latest release, not whatever is on main. Only "no release yet" (404) falls back to main;
# any other failure (offline, rate limit, timeout) stops, so an unreleased main never ships by accident.
# A curl failure (even after a 200 or 404 header arrived, e.g. a timeout mid-body) counts as unreachable.
# JOBSMITH_WHEEL (a wheel file) skips the lookup: CI uses it to run this script on the commit it tests.
wheel="${JOBSMITH_WHEEL:-}"
if [ -n "$wheel" ]; then
  ref="from $wheel"
else
  # CI's shared runners use up GitHub's 60 anonymous lookups an hour, so CI passes its own token (never set otherwise)
  set --
  [ -z "${JOBSMITH_GITHUB_TOKEN:-}" ] || set -- -H "Authorization: Bearer $JOBSMITH_GITHUB_TOKEN"
  resp=$(curl -sS --max-time 30 --retry 2 --retry-delay 3 "$@" -w '\n%{http_code}' https://api.github.com/repos/rawcache/Jobsmith/releases/latest 2>/dev/null) || resp="000"
  code=$(printf '%s\n' "$resp" | tail -n 1)
  if [ "$code" = "404" ]; then
    ref="main"
  elif [ "$code" = "200" ]; then
    ref=$(printf '%s\n' "$resp" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)
    if ! printf '%s' "$ref" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
      echo "The latest Jobsmith release has an unexpected tag ('$ref'). Nothing was installed." >&2
      exit 1
    fi
    # The release's ready-built wheel (pure Python), only from this repo's own download folder for that tag
    wheel=$(printf '%s\n' "$resp" | sed -n 's/.*"browser_download_url": *"\([^"]*\)".*/\1/p' \
      | grep -E "^$repo/releases/download/$ref/jobsmith-[0-9.]+-py3-none-any\.whl\$" | head -n 1) || wheel=""
  else
    echo "Couldn't reach GitHub to find the latest Jobsmith release (HTTP ${code:-none}). Try again in a minute." >&2
    exit 1
  fi
fi
# Say so now, rather than after a minute of uv retrying. A mirror set up for uv (UV_DEFAULT_INDEX) skips the check.
if [ -z "${UV_DEFAULT_INDEX:-}${UV_INDEX_URL:-}" ] && ! curl -sS --max-time 30 --retry 2 --retry-delay 3 -o /dev/null https://pypi.org/simple/ 2>/dev/null; then
  echo "Couldn't reach pypi.org, where Jobsmith downloads its parts from. Check your internet connection" >&2
  echo "(on a school or work network, pypi.org may be blocked) and try again. Nothing was installed." >&2
  exit 1
fi
if [ -n "$wheel" ]; then
  set -- --no-build "$wheel"
else
  # GitHub's source archive, not git+https: a new Mac has no working git (it asks to install developer tools)
  if [ "$ref" = "main" ]; then src="$repo/archive/refs/heads/main.tar.gz"; else src="$repo/archive/refs/tags/$ref.tar.gz"; fi
  set -- "$src"
  for p in $native; do set -- --no-build-package "$p" "$@"; done
fi
echo "Installing Jobsmith $ref (this can take a minute or two)"
# The full output goes to a log, so a failure shows a short message instead of pages of build output. A new file of
# its own (mktemp), never a fixed name another user could have planted; kept only on failure. CI names its own.
log="${JOBSMITH_INSTALL_LOG:-$(mktemp "${TMPDIR:-/tmp}/jobsmith-install.XXXXXX")}"
network_error() { grep -Eqi 'failed to fetch|error sending request|timed out|dns error|connection (reset|refused|closed)|tcp connect' "$log"; }
# Python 3.13, the version CI tests (.python-version); left to choose, uv may download any version 3.11-3.13.
ok=0
uv tool install --force --python 3.13 "$@" >"$log" 2>&1 && ok=1
if [ "$ok" = 0 ] && network_error; then
  echo "The connection dropped while downloading. Trying once more..."
  sleep 5
  uv tool install --force --python 3.13 "$@" >"$log" 2>&1 && ok=1
fi
if [ "$ok" = 0 ]; then
  echo >&2
  if network_error; then
    echo "Jobsmith couldn't download everything it needs: the connection to pypi.org keeps dropping." >&2
    echo "Try again on a steadier connection. Nothing was installed. (Full log: $log)" >&2
  else
    echo "Jobsmith couldn't install a package for this computer. Please open an issue with this output:" >&2
    echo "  $issues" >&2
    echo >&2
    echo "  $(uname -sm) ($(sw_vers -productVersion 2>/dev/null || uname -r)), Jobsmith $ref, $(uv --version)" >&2
    # uv's own error (from the first "error" or "×" line), not the build output that follows it
    excerpt=$(awk '/^ *(error|×)/ { f = 1 } f' "$log" | head -n 20)
    [ -n "$excerpt" ] || excerpt=$(tail -n 15 "$log")
    printf '%s\n' "$excerpt" | sed 's/^/  /' >&2
    echo "  (Full log: $log)" >&2
  fi
  exit 1
fi
[ -n "${JOBSMITH_INSTALL_LOG:-}" ] || rm -f "$log"
bin=$(uv tool dir --bin 2>/dev/null) && export PATH="$bin:$PATH"
jobsmith doctor || true
echo
if (PATH="$start_path"; command -v jobsmith >/dev/null 2>&1); then
  echo "Done. Run:  jobsmith"
else
  echo "Done. Open a new terminal window, then run:  jobsmith"
  echo "(If it says 'command not found' there, run:  uv tool update-shell  and open another window.)"
fi
