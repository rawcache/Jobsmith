# Install Jobsmith on Windows (PowerShell):
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/rawcache/Jobsmith/main/install.ps1 | iex"
$ErrorActionPreference = "Stop"
$startPath = $env:Path    # the Path this window has, to tell you whether `jobsmith` works in it right away
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
if ($ref -eq "main") { $url = "https://github.com/rawcache/Jobsmith/archive/refs/heads/main.tar.gz" }
else { $url = "https://github.com/rawcache/Jobsmith/archive/refs/tags/$ref.tar.gz" }
Write-Host "Installing Jobsmith $ref"
# GitHub's source archive, not git+https: most Windows PCs don't have git.
# Python 3.13, the version CI tests (.python-version); left to choose, uv may download any version 3.11-3.13.
uv tool install --force --python 3.13 "$url"
if ($LASTEXITCODE -ne 0) {   # PowerShell doesn't stop on a failed program by itself
  Write-Host "Jobsmith wasn't installed. See the error above, then try again."
  exit 1
}
$bin = uv tool dir --bin
if ($bin) { $env:Path = "$bin;$env:Path" }
jobsmith doctor
Write-Host ""
$now = $env:Path; $env:Path = $startPath
$ready = [bool](Get-Command jobsmith -ErrorAction SilentlyContinue)
$env:Path = $now
if ($ready) { Write-Host "Done. Run:  jobsmith" }
else {
  Write-Host "Done. Open a new PowerShell window, then run:  jobsmith"
  Write-Host "(If it says 'not recognized' there, run:  uv tool update-shell  and open another window.)"
}
