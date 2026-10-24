"""The one-line installers install the latest release tag, fall back to main only when there's no release (404),
and stop on any other failure, so an unreleased main never reaches a new install. They install GitHub's source
archive rather than git+https, because a new Mac or Windows PC has no working git. GitHub, uv and jobsmith are
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


def _archive(ref: str) -> str:
    kind = "heads" if ref == "main" else "tags"
    return f"https://github.com/rawcache/Jobsmith/archive/refs/{kind}/{ref}.tar.gz"


def _run_sh(tmp_path: Path, code: str, body: str, curl_exit: int, bin_on_path: bool = False, install_fails: bool = False):
    """install.sh with stand-ins: curl answers like GitHub; uv logs installs and puts a jobsmith command in its
    tool folder (like `uv tool install`), which is on the starting PATH only if bin_on_path."""
    log, bin_ = tmp_path / "uv.log", tmp_path / "toolbin"
    _stub(tmp_path / "curl", f"printf '%s\\n%s' '{body}' '{code}'\nexit {curl_exit}\n")
    _stub(tmp_path / "uv", f'''case "$1 $2" in
  "tool dir") echo "{bin_}" ;;
  "tool install") echo "$*" >> "{log}"; {"echo 'error: build failed' >&2; exit 2" if install_fails else ":"}; mkdir -p "{bin_}"
    printf '#!/bin/sh\\necho "$*" >> "{tmp_path}/jobsmith.log"\\n' > "{bin_}/jobsmith"; chmod +x "{bin_}/jobsmith" ;;
esac
''')
    if bin_on_path:
        bin_.mkdir()
    path = (f"{bin_}:" if bin_on_path else "") + f"{tmp_path}:/usr/bin:/bin"
    r = subprocess.run(["sh", str(ROOT / "install.sh")], env={"PATH": path, "HOME": str(tmp_path)},
                       capture_output=True, text=True, timeout=30)
    return r, log


@pytest.mark.skipif(os.name == "nt" or not shutil.which("sh"), reason="install.sh is for macOS and Linux")
@pytest.mark.parametrize("case", CASES)
def test_install_sh_picks_the_release(tmp_path, case):
    code, body, want, *curl_exit = CASES[case]
    curl_exit = curl_exit[0] if curl_exit else 7 if code == "000" else 0
    r, log = _run_sh(tmp_path, code, body, curl_exit)
    if want is None:
        assert r.returncode != 0 and not log.exists(), (r.stdout, r.stderr)
        assert "Nothing was installed" in r.stderr or "Try again" in r.stderr
    else:
        assert r.returncode == 0, r.stderr
        assert log.read_text().split() == ["tool", "install", "--force", "--python", "3.13", _archive(want)]


@pytest.mark.skipif(os.name == "nt" or not shutil.which("sh"), reason="install.sh is for macOS and Linux")
@pytest.mark.parametrize("on_path", [False, True])
def test_install_sh_says_how_to_start_it(tmp_path, on_path):
    """Pasted into a terminal whose PATH lacks uv's tool folder, `jobsmith` won't be found in that window: say to
    open a new one. Either way the installer itself can run `jobsmith doctor`."""
    r, _ = _run_sh(tmp_path, "200", '{"tag_name": "v0.4.0"}', 0, bin_on_path=on_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "jobsmith.log").read_text().split() == ["doctor"]
    if on_path:
        assert "Done. Run:  jobsmith" in r.stdout and "new terminal" not in r.stdout
    else:
        assert "Open a new terminal window, then run:  jobsmith" in r.stdout and "uv tool update-shell" in r.stdout


@pytest.mark.skipif(os.name == "nt" or not shutil.which("sh"), reason="install.sh is for macOS and Linux")
def test_install_sh_stops_when_the_install_fails(tmp_path):
    r, _ = _run_sh(tmp_path, "200", '{"tag_name": "v0.4.0"}', 0, install_fails=True)
    assert r.returncode != 0 and "Done" not in r.stdout
    assert not (tmp_path / "jobsmith.log").exists()                  # no doctor run against an old copy


@pytest.mark.skipif(not shutil.which("powershell"), reason="install.ps1 needs Windows PowerShell")
def test_install_ps1_stops_when_the_install_fails(tmp_path):
    script = ("function Invoke-RestMethod { return ('{\"tag_name\": \"v0.4.0\"}' | ConvertFrom-Json) }\n"
              f"function uv {{ if ($args[0] -eq 'tool' -and $args[1] -eq 'dir') {{ return '{tmp_path}' }}; $global:LASTEXITCODE = 2 }}\n"
              f"function jobsmith {{ Set-Content -Path '{tmp_path / 'doctor.ran'}' -Value 1 }}\n"
              f"& '{ROOT / 'install.ps1'}'\n")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "wasn't installed" in r.stdout and "Done" not in r.stdout, (r.stdout, r.stderr)
    assert not (tmp_path / "doctor.ran").exists()


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
              f"function uv {{ if ($args[0] -eq 'tool' -and $args[1] -eq 'dir') {{ return '{tmp_path}' }}; "
              f"Add-Content -Path '{log}' -Value ($args -join ' '); $global:LASTEXITCODE = 0 }}\n"   # a real uv sets it
              "function jobsmith { }\n"
              f"& '{ROOT / 'install.ps1'}'\n")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, timeout=60)
    if want is None:
        assert r.returncode != 0 and not log.exists(), (r.stdout, r.stderr)
    else:
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert log.read_text().split() == ["tool", "install", "--force", "--python", "3.13", _archive(want)]
        assert "Done. Run:  jobsmith" in r.stdout       # jobsmith (a function here) is found in this window
