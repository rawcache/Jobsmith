#!/usr/bin/env bash
# Install Jobsmith on macOS or Linux:
#   curl -LsSf https://raw.githubusercontent.com/rawcache/Jobsmith/main/install.sh | sh
set -eu
start_path="$PATH"      # the PATH your terminal has, to tell you whether `jobsmith` works in it right away
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
# Install the latest release, not whatever is on main. Only "no release yet" (404) falls back to main;
# any other failure (offline, rate limit, timeout) stops, so an unreleased main never ships by accident.
# A curl failure (even after a 200 or 404 header arrived, e.g. a timeout mid-body) counts as unreachable.
resp=$(curl -sS --max-time 15 -w '\n%{http_code}' https://api.github.com/repos/rawcache/Jobsmith/releases/latest 2>/dev/null) || resp="000"
code=$(printf '%s\n' "$resp" | tail -n 1)
if [ "$code" = "404" ]; then
  ref="main"
elif [ "$code" = "200" ]; then
  ref=$(printf '%s\n' "$resp" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)
  if ! printf '%s' "$ref" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "The latest Jobsmith release has an unexpected tag ('$ref'). Nothing was installed." >&2
    exit 1
  fi
else
  echo "Couldn't reach GitHub to find the latest Jobsmith release (HTTP ${code:-none}). Try again in a minute." >&2
  exit 1
fi
if [ "$ref" = "main" ]; then url="https://github.com/rawcache/Jobsmith/archive/refs/heads/main.tar.gz"
else url="https://github.com/rawcache/Jobsmith/archive/refs/tags/$ref.tar.gz"; fi
echo "Installing Jobsmith $ref"
# GitHub's source archive, not git+https: a new Mac has no working git (it asks to install developer tools).
# Python 3.13, the version CI tests (.python-version); left to choose, uv may download any version 3.11-3.13.
uv tool install --force --python 3.13 "$url"
bin=$(uv tool dir --bin 2>/dev/null) && export PATH="$bin:$PATH"
jobsmith doctor || true
echo
if (PATH="$start_path"; command -v jobsmith >/dev/null 2>&1); then
  echo "Done. Run:  jobsmith"
else
  echo "Done. Open a new terminal window, then run:  jobsmith"
  echo "(If it says 'command not found' there, run:  uv tool update-shell  and open another window.)"
fi
