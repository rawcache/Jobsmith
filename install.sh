#!/usr/bin/env bash
# Install Jobsmith on macOS or Linux:
#   curl -LsSf https://raw.githubusercontent.com/rawcache/Jobsmith/main/install.sh | sh
set -eu
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv tool install --force git+https://github.com/rawcache/Jobsmith
jobsmith doctor || true
echo
echo "Done. Run:  jobsmith"
