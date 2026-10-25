# Install Jobsmith on Windows (PowerShell):
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/rawcache/Jobsmith/main/install.ps1 | iex"
$ErrorActionPreference = "Stop"
$repo = "https://github.com/rawcache/Jobsmith"
$issues = "$repo/issues/new"
$startPath = $env:Path    # the Path this window has, to tell you whether `jobsmith` works in it right away
# uv's 30 s default gives up on a slow connection partway through a big download (Playwright is ~40 MB)
if (-not $env:UV_HTTP_TIMEOUT) { $env:UV_HTTP_TIMEOUT = "120" }
if (-not $env:UV_HTTP_RETRIES) { $env:UV_HTTP_RETRIES = "5" }
# Packages with compiled parts. Never build them here: a PC without a wheel for the newest version (Windows on ARM
# for cryptography 50) would need Rust or a C compiler. uv then picks the newest version that has a wheel.
# Only used for a source install; a release wheel installs with --no-build, which covers every package.
# tests/test_install.py checks this list against uv.lock.
$native = "cffi cryptography fonttools greenlet httptools pillow playwright psutil pydantic-core pywin32 pyyaml rpds-py uvloop watchfiles websockets" -split " "
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

function Get-Latest {
  # Two tries: one slow answer shouldn't stop the install
  $headers = @{ "User-Agent" = "jobsmith-installer" }
  # CI's shared runners use up GitHub's 60 anonymous lookups an hour, so CI passes its own token (never set otherwise)
  if ($env:JOBSMITH_GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:JOBSMITH_GITHUB_TOKEN" }
  for ($try = 1; ; $try++) {
    try {
      return Invoke-RestMethod -Uri "https://api.github.com/repos/rawcache/Jobsmith/releases/latest" `
        -Headers $headers -TimeoutSec 30
    } catch {
      $status = $_.Exception.Response.StatusCode
      if (($status -and [int]$status -eq 404) -or $try -ge 2) { throw }
      Start-Sleep -Seconds 3
    }
  }
}

# Install the latest release, not whatever is on main. Only "no release yet" (404) falls back to main;
# any other failure (offline, rate limit, timeout) stops, so an unreleased main never ships by accident.
# JOBSMITH_WHEEL (a wheel file) skips the lookup: CI uses it to run this script on the commit it tests.
$wheel = $env:JOBSMITH_WHEEL
if ($wheel) {
  $ref = "from $wheel"
} else {
  try {
    $release = Get-Latest
    $ref = $release.tag_name
    if ($ref -notmatch '^v\d+\.\d+\.\d+$') {
      Write-Host "The latest Jobsmith release has an unexpected tag ('$ref'). Nothing was installed."
      exit 1
    }
    # The release's ready-built wheel (pure Python), only from this repo's own download folder for that tag
    $wheel = @($release.assets | ForEach-Object { $_.browser_download_url } |
      Where-Object { $_ -match "^$([regex]::Escape("$repo/releases/download/$ref/"))jobsmith-[0-9.]+-py3-none-any\.whl$" })[0]
  } catch {
    $status = $_.Exception.Response.StatusCode
    if ($status -and [int]$status -eq 404) {
      $ref = "main"
    } else {
      Write-Host "Couldn't reach GitHub to find the latest Jobsmith release. Try again in a minute."
      exit 1
    }
  }
}
# Say so now, rather than after a minute of uv retrying. A mirror set up for uv (UV_DEFAULT_INDEX) skips the check.
if (-not ($env:UV_DEFAULT_INDEX -or $env:UV_INDEX_URL)) {
  try { Invoke-WebRequest -Uri "https://pypi.org/simple/" -Method Head -UseBasicParsing -TimeoutSec 30 | Out-Null }
  catch {
    Write-Host "Couldn't reach pypi.org, where Jobsmith downloads its parts from. Check your internet connection"
    Write-Host "(on a school or work network, pypi.org may be blocked) and try again. Nothing was installed."
    exit 1
  }
}
if ($wheel) {
  $src = @("--no-build", $wheel)
} else {
  # GitHub's source archive, not git+https: most Windows PCs don't have git
  if ($ref -eq "main") { $url = "$repo/archive/refs/heads/main.tar.gz" } else { $url = "$repo/archive/refs/tags/$ref.tar.gz" }
  $src = @($native | ForEach-Object { "--no-build-package"; $_ }) + $url
}
Write-Host "Installing Jobsmith $ref (this can take a minute or two)"
# The full output goes to a log, so a failure shows a short message instead of pages of build output. A new file of
# its own, never a fixed name; kept only on failure. CI names its own (JOBSMITH_INSTALL_LOG).
$log = $env:JOBSMITH_INSTALL_LOG
if (-not $log) { $log = [System.IO.Path]::GetTempFileName() }
function Install-Tool {
  # Python 3.13, the version CI tests (.python-version); left to choose, uv may download any version 3.11-3.13.
  # uv writes progress to stderr; with "Stop", Windows PowerShell would treat the first line as a fatal error.
  $ErrorActionPreference = "Continue"
  # -Value, not the pipeline: an install that prints nothing still leaves a (empty) log behind
  Set-Content -Path $log -Value @(uv tool install --force --python 3.13 @src 2>&1 | ForEach-Object { "$_" })
  return ($LASTEXITCODE -eq 0)    # PowerShell doesn't stop on a failed program by itself
}
function Test-NetworkError {
  return [bool](Select-String -Path $log -Pattern 'failed to fetch|error sending request|timed out|dns error|connection (reset|refused|closed)|tcp connect' -Quiet)
}
$ok = Install-Tool
if (-not $ok -and (Test-NetworkError)) {
  Write-Host "The connection dropped while downloading. Trying once more..."
  Start-Sleep -Seconds 5
  $ok = Install-Tool
}
if (-not $ok) {
  Write-Host ""
  if (Test-NetworkError) {
    Write-Host "Jobsmith couldn't download everything it needs: the connection to pypi.org keeps dropping."
    Write-Host "Try again on a steadier connection. Nothing was installed. (Full log: $log)"
  } else {
    Write-Host "Jobsmith couldn't install a package for this computer. Please open an issue with this output:"
    Write-Host "  $issues"
    Write-Host ""
    Write-Host "  Windows $([Environment]::OSVersion.Version) $env:PROCESSOR_ARCHITECTURE, Jobsmith $ref, $(uv --version)"
    # uv's own error (from the first "error" or "x" (U+00D7) line), not the build output that follows it.
    # The script stays ASCII: Windows PowerShell reads a saved .ps1 without a BOM as the local code page.
    $lines = @(Get-Content -Path $log)
    $first = 0..($lines.Count - 1) | Where-Object { $lines[$_] -match "^\s*(error|$([char]0xD7))" } | Select-Object -First 1
    if ($null -ne $first) { $excerpt = $lines[$first..($lines.Count - 1)] | Select-Object -First 20 }
    else { $excerpt = $lines | Select-Object -Last 15 }
    $excerpt | ForEach-Object { Write-Host "  $_" }
    Write-Host "  (Full log: $log)"
  }
  exit 1
}
if (-not $env:JOBSMITH_INSTALL_LOG) { Remove-Item -Path $log -ErrorAction SilentlyContinue }
$bin = uv tool dir --bin
if ($bin) { $env:Path = "$bin;$env:Path" }
# Chrome or Edge if you have one, else download Chromium now rather than on your first application.
# Silent unless it downloads; the full check is `jobsmith doctor`.
jobsmith doctor --browser
$version = "$(jobsmith --version)" -replace '^jobsmith\s*', ''
Write-Host ""
if ($version) { Write-Host "Installed Jobsmith $version." } else { Write-Host "Installed Jobsmith." }
$now = $env:Path; $env:Path = $startPath
$ready = [bool](Get-Command jobsmith -ErrorAction SilentlyContinue)
$env:Path = $now
if (-not $ready) {
  Write-Host "Open a new PowerShell window first. (If 'jobsmith' is 'not recognized' there, run:  uv tool update-shell)"
}
Write-Host ""
Write-Host "  Try it with made-up data:  jobsmith demo"
Write-Host "  Set it up for real:        jobsmith"
Write-Host ""
Write-Host "An AI is optional. You can add one during setup or any time later."
