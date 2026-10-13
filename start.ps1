# Run Jobsmith from a source checkout on Windows:  powershell -ExecutionPolicy Bypass -File .\start.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "Installing uv (Python package manager)..."
  powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
uv sync --quiet
uv run jobsmith doctor
Write-Host "Starting Jobsmith at http://127.0.0.1:8765 (Ctrl+C to stop). In another terminal, run: uv run jobsmith"
uv run jobsmith serve @args
