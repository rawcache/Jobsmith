"""The one-line installers install the latest release tag, fall back to main only when there's no release (404),
and stop on any other failure, so an unreleased main never reaches a new install. GitHub, uv and jobsmith are
stand-ins here: nothing is downloaded or installed."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# (what GitHub answers, expected ref passed to uv or None if the installer must stop)
CASES = {
    "release": ("200", '{"tag_name": "v0.4.0", "name": "v0.4.0"}', "v0.4.0"),
    "no_release": ("404", '{"message": "Not Found"}', "main"),
    "rate_limited": ("403", '{"message": "API rate limit exceeded"}', None),
    "server_error": ("502", "", None),
    "offline": ("000", "", None),
    "bad_tag": ("200", '{"tag_name": "v1garbage"}', None),
    "no_tag": ("200", '{"name": "v0.4.0"}', None),
    # curl gets the status, then times out mid-body (exit 28): never trust what arrived
    "timeout_after_200": ("200", '{"tag_name": "v0.4.0"', None, 28),
    "timeout_after_404": ("404", "", None, 28),
}


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


@pytest.mark.skipif(os.name == "nt" or not shutil.which("sh"), reason="install.sh is for macOS and Linux")
@pytest.mark.parametrize("case", CASES)
def test_install_sh_picks_the_release(tmp_path, case):
    code, body, want, *curl_exit = CASES[case]
    curl_exit = curl_exit[0] if curl_exit else 7 if code == "000" else 0
    log = tmp_path / "uv.log"
    # curl -w '\n%{http_code}' prints the body, then the status; on a network failure, just "000" and exit 7
    _stub(tmp_path / "curl", f"printf '%s\\n%s' '{body}' '{code}'\nexit {curl_exit}\n")
    _stub(tmp_path / "uv", f'echo "$*" >> "{log}"\n')
    _stub(tmp_path / "jobsmith", "exit 0\n")
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run(["sh", str(ROOT / "install.sh")], env=env, capture_output=True, text=True, timeout=30)
    if want is None:
        assert r.returncode != 0 and not log.exists(), (r.stdout, r.stderr)
        assert "Nothing was installed" in r.stderr or "Try again" in r.stderr
    else:
        assert r.returncode == 0, r.stderr
        assert log.read_text().split() == ["tool", "install", "--force", f"git+https://github.com/rawcache/Jobsmith@{want}"]


@pytest.mark.skipif(not shutil.which("powershell"), reason="install.ps1 needs Windows PowerShell")
@pytest.mark.parametrize("case", CASES)
def test_install_ps1_picks_the_release(tmp_path, case):
    code, body, want, *curl_exit = CASES[case]
    if curl_exit:
        pytest.skip("a timeout mid-body is a curl case; Invoke-RestMethod throws without a usable answer")
    log = tmp_path / "uv.log"
    if code == "200":
        fake = f"return ('{body}' | ConvertFrom-Json)"
    else:   # Invoke-RestMethod throws; an HTTP error carries Response.StatusCode, a network failure doesn't
        status = "" if code == "000" else f"Add-Member -InputObject $e -NotePropertyName Response -NotePropertyValue ([pscustomobject]@{{StatusCode={code}}});"
        fake = f"$e = [System.Exception]::new('fake {code}'); {status} throw $e"
    script = (f"function Invoke-RestMethod {{ {fake} }}\n"
              f"function uv {{ Add-Content -Path '{log}' -Value ($args -join ' ') }}\n"
              "function jobsmith { }\n"
              f"& '{ROOT / 'install.ps1'}'\n")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, timeout=60)
    if want is None:
        assert r.returncode != 0 and not log.exists(), (r.stdout, r.stderr)
    else:
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert log.read_text().split() == ["tool", "install", "--force", f"git+https://github.com/rawcache/Jobsmith@{want}"]
