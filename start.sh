#!/usr/bin/env bash
# Run Jobsmith from a source checkout on macOS or Linux: ./start.sh   (Windows: .\start.ps1)
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (Python package manager)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv sync --quiet

# Rebuild the dashboard only if you've edited it and have Node installed.
if command -v npm >/dev/null 2>&1 && [ -n "$(find web/src -newer jobsmith/web_dist/index.html 2>/dev/null)" ]; then
  (cd web && npm install --silent && npm run build)
fi

uv run jobsmith doctor || true        # also downloads a browser if you don't have Chrome or Edge
echo "Starting Jobsmith at http://127.0.0.1:8765 (Ctrl+C to stop). In another terminal, run: uv run jobsmith"
exec uv run jobsmith serve "$@"
