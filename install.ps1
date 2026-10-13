# Install Jobsmith on Windows (PowerShell):
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/rawcache/Jobsmith/main/install.ps1 | iex"
$ErrorActionPreference = "Stop"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
uv tool install --force git+https://github.com/rawcache/Jobsmith
jobsmith doctor
Write-Host ""
Write-Host "Done. Run:  jobsmith"
