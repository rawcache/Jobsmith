# Install Jobsmith on Windows (PowerShell):
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/rawcache/Jobsmith/main/install.ps1 | iex"
$ErrorActionPreference = "Stop"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
# Install the latest release, not whatever is on main. Only "no release yet" (404) falls back to main;
# any other failure (offline, rate limit, timeout) stops, so an unreleased main never ships by accident.
try {
  $ref = (Invoke-RestMethod -Uri "https://api.github.com/repos/rawcache/Jobsmith/releases/latest" `
    -Headers @{ "User-Agent" = "jobsmith-installer" } -TimeoutSec 15).tag_name
  if ($ref -notmatch '^v\d+\.\d+\.\d+$') {
    Write-Host "The latest Jobsmith release has an unexpected tag ('$ref'). Nothing was installed."
    exit 1
  }
} catch {
  $status = $_.Exception.Response.StatusCode
  if ($status -and [int]$status -eq 404) {
    $ref = "main"
  } else {
    Write-Host "Couldn't reach GitHub to find the latest Jobsmith release. Try again in a minute."
    exit 1
  }
}
Write-Host "Installing Jobsmith $ref"
uv tool install --force "git+https://github.com/rawcache/Jobsmith@$ref"
jobsmith doctor
Write-Host ""
Write-Host "Done. Run:  jobsmith"
