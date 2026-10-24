"""The one-line installers install the latest release tag, fall back to main only when there's no release (404),
and stop on any other failure, so an unreleased main never reaches a new install. A release's ready-built wheel is
installed with --no-build, so nothing is ever compiled; without one they use GitHub's source archive (no git needed)
and still refuse to build the packages with compiled parts. GitHub, PyPI, uv and jobsmith are stand-ins here:
nothing is downloaded or installed."""
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/rawcache/Jobsmith"
WHEEL = f"{REPO}/releases/download/v0.4.2/jobsmith-0.4.2-py3-none-any.whl"


def _release(tag: str, *assets: str) -> str:
    urls = ", ".join(f'{{"name": "{a.rsplit("/", 1)[-1]}", "browser_download_url": "{a}"}}' for a in assets)
    return f'{{"tag_name": "{tag}", "name": "{tag}", "assets": [{urls}]}}'


# (what GitHub answers, what uv must be given: a wheel URL, a source ref, or None if the installer must stop)
CASES = {
    "release_with_wheel": ("200", _release("v0.4.2", f"{REPO}/releases/download/v0.4.2/jobsmith-extension-0.4.2.zip",
                                           WHEEL), ("wheel", WHEEL)),
    "release_without_wheel": ("200", _release("v0.4.0"), ("source", "v0.4.0")),
    # a wheel from anywhere but this repo's download folder for that tag is never installed
    "wheel_elsewhere": ("200", _release("v0.4.2", "https://example.com/jobsmith-0.4.2-py3-none-any.whl",
                                        f"{REPO}/releases/download/v0.4.1/jobsmith-0.4.1-py3-none-any.whl"),
                        ("source", "v0.4.2")),
    "no_release": ("404", '{"message": "Not Found"}', ("source", "main")),
    "rate_limited": ("403", '{"message": "API rate limit exceeded"}', None),
    "server_error": ("502", "", None),
    "offline": ("000", "", None),
    "bad_tag": ("200", '{"tag_name": "v1garbage"}', None),
    "no_tag": ("200", '{"name": "v0.4.0"}', None),
    # curl gets the status, then times out mid-body (exit 28): never trust what arrived
    "timeout_after_200": ("200", '{"tag_name": "v0.4.0"', None, 28),
    "timeout_after_404": ("404", "", None, 28),
}

NATIVE_SH = re.search(r'^native="([^"]+)"', (ROOT / "install.sh").read_text(), re.M).group(1).split()
NATIVE_PS1 = re.search(r'^\$native = "([^"]+)"', (ROOT / "install.ps1").read_text(), re.M).group(1).split()


def _expected(want: tuple[str, str]) -> list[str]:
    kind, what = want
    if kind == "wheel":
        return ["--no-build", what]
    branch = "heads" if what == "main" else "tags"
    return [f"{REPO}/archive/refs/{branch}/{what}.tar.gz"]


def _source_args(args: list[str]) -> tuple[set[str], list[str]]:
    """Split uv's arguments after --python 3.13 into the packages it may not build and the rest."""
    rest, no_build = [], set()
    it = iter(args)
    for a in it:
        if a == "--no-build-package":
            no_build.add(next(it))
        else:
            rest.append(a)
    return no_build, rest


def test_packages_with_compiled_parts_are_never_built():
    """Every locked package that ships platform wheels is on both installers' never-build list. When `uv lock`
    brings in a new one (or a new version that drops a platform), this fails until the lists name it."""
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    native = {p["name"] for p in lock["package"]
              if any(not w["url"].endswith("-none-any.whl") for w in p.get("wheels", []))}
    assert native, "uv.lock has no packages with platform wheels: the check above is broken"
    assert native <= set(NATIVE_SH), sorted(native - set(NATIVE_SH))
    assert NATIVE_SH == NATIVE_PS1


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def _run_sh(tmp_path: Path, code: str, body: str, curl_exit: int = 0, bin_on_path: bool = False,
            install_fails: str = "", pypi_down: bool = False, env: dict | None = None):
    """install.sh with stand-ins: curl answers like GitHub (and pypi.org is up unless pypi_down); uv logs
    installs and puts a jobsmith command in its tool folder (like `uv tool install`), which is on the starting
    PATH only if bin_on_path. install_fails is "build" (every try fails to build), "network" (the first try
    loses the connection, the next works) or "network-always"."""
    log, bin_ = tmp_path / "uv.log", tmp_path / "toolbin"
    _stub(tmp_path / "curl", f'''case "$*" in *pypi.org*) exit {7 if pypi_down else 0} ;; esac
printf '%s\\n%s' '{body}' '{code}'
exit {curl_exit}
''')
    fail = {
        "": ":",
        "build": "printf 'Resolved 59 packages\\n  × Failed to build `cryptography==50.0.2`\\n' >&2; "
                 "i=0; while [ $i -lt 300 ]; do echo \"   Compiling openssl-sys $i\" >&2; i=$((i+1)); done; exit 1",
        "network": f'if [ ! -e "{tmp_path}/tried" ]; then : > "{tmp_path}/tried"; '
                   "echo 'error: Failed to fetch: https://files.pythonhosted.org/x.whl (operation timed out)' >&2; exit 2; fi",
        "network-always": "echo 'error: Failed to fetch: https://pypi.org/simple/x/ (dns error)' >&2; exit 2",
    }[install_fails]
    _stub(tmp_path / "uv", f'''case "$1 $2" in
  "tool dir") echo "{bin_}" ;;
  "tool install") echo "$*" >> "{log}"; {fail}; mkdir -p "{bin_}"
    printf '#!/bin/sh\\necho "$*" >> "{tmp_path}/jobsmith.log"\\n' > "{bin_}/jobsmith"; chmod +x "{bin_}/jobsmith" ;;
  *) echo "uv 0.0.0" ;;
esac
''')
    _stub(tmp_path / "sleep", ":")          # the retry waits; the test doesn't need to
    if bin_on_path:
        bin_.mkdir()
    path = (f"{bin_}:" if bin_on_path else "") + f"{tmp_path}:/usr/bin:/bin"
    r = subprocess.run(["sh", str(ROOT / "install.sh")],
                       env={"PATH": path, "HOME": str(tmp_path), "TMPDIR": str(tmp_path), **(env or {})},
                       capture_output=True, text=True, timeout=30)
    return r, log


def _installs(log: Path) -> list[list[str]]:
    """Each `uv tool install` call's arguments after `tool install --force --python 3.13`."""
    calls = [line.split() for line in log.read_text().splitlines()]
    for c in calls:
        assert c[:5] == ["tool", "install", "--force", "--python", "3.13"], c
    return [c[5:] for c in calls]


sh_only = pytest.mark.skipif(os.name == "nt" or not shutil.which("sh"), reason="install.sh is for macOS and Linux")
ps_only = pytest.mark.skipif(not shutil.which("powershell"), reason="install.ps1 needs Windows PowerShell")


@sh_only
@pytest.mark.parametrize("case", CASES)
def test_install_sh_picks_the_release(tmp_path, case):
    code, body, want, *curl_exit = CASES[case]
    curl_exit = curl_exit[0] if curl_exit else 7 if code == "000" else 0
    r, log = _run_sh(tmp_path, code, body, curl_exit)
    if want is None:
        assert r.returncode != 0 and not log.exists(), (r.stdout, r.stderr)
        assert "Nothing was installed" in r.stderr or "Try again" in r.stderr
        return
    assert r.returncode == 0, r.stderr
    [args] = _installs(log)
    no_build, rest = _source_args(args)
    assert rest == _expected(want)
    # a wheel needs no list: --no-build covers every package; a source install never builds the compiled ones
    assert no_build == (set() if want[0] == "wheel" else set(NATIVE_SH))


@sh_only
def test_install_sh_installs_a_given_wheel_without_asking_github(tmp_path):
    """CI runs the real installer on the commit it tests through JOBSMITH_WHEEL."""
    r, log = _run_sh(tmp_path, "000", "", 7, env={"JOBSMITH_WHEEL": "/build/jobsmith-0.4.2-py3-none-any.whl"})
    assert r.returncode == 0, r.stderr
    assert _installs(log) == [["--no-build", "/build/jobsmith-0.4.2-py3-none-any.whl"]]


@sh_only
def test_install_sh_says_when_pypi_is_unreachable(tmp_path):
    r, log = _run_sh(tmp_path, "200", _release("v0.4.2", WHEEL), pypi_down=True)
    assert r.returncode != 0 and not log.exists()
    assert "Couldn't reach pypi.org" in r.stderr and "Nothing was installed" in r.stderr


@sh_only
def test_install_sh_tries_again_when_the_connection_drops(tmp_path):
    r, log = _run_sh(tmp_path, "200", _release("v0.4.2", WHEEL), install_fails="network")
    assert r.returncode == 0, r.stderr
    assert len(_installs(log)) == 2 and "Trying once more" in r.stdout


@sh_only
def test_install_sh_gives_up_on_a_connection_that_keeps_dropping(tmp_path):
    r, log = _run_sh(tmp_path, "200", _release("v0.4.2", WHEEL), install_fails="network-always")
    assert r.returncode != 0 and len(_installs(log)) == 2
    assert "connection to pypi.org keeps dropping" in r.stderr and "open an issue" not in r.stderr


@sh_only
def test_install_sh_shows_a_short_message_when_a_package_wont_install(tmp_path):
    """Not hundreds of lines of Rust: what failed, on what computer, and where to report it."""
    r, log = _run_sh(tmp_path, "200", _release("v0.4.2", WHEEL), install_fails="build")
    assert r.returncode != 0 and "Done" not in r.stdout
    assert len(_installs(log)) == 1                                   # a build failure isn't retried
    assert "Jobsmith couldn't install a package for this computer" in r.stderr
    assert f"{REPO}/issues/new" in r.stderr and "Failed to build `cryptography==50.0.2`" in r.stderr
    assert len(r.stderr.splitlines()) < 35 and (tmp_path / "jobsmith-install.log").exists()
    assert not (tmp_path / "jobsmith.log").exists()                  # no doctor run against an old copy


@sh_only
@pytest.mark.parametrize("on_path", [False, True])
def test_install_sh_says_how_to_start_it(tmp_path, on_path):
    """Pasted into a terminal whose PATH lacks uv's tool folder, `jobsmith` won't be found in that window: say to
    open a new one. Either way the installer itself can run `jobsmith doctor`."""
    r, _ = _run_sh(tmp_path, "200", _release("v0.4.2", WHEEL), bin_on_path=on_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "jobsmith.log").read_text().split() == ["doctor"]
    if on_path:
        assert "Done. Run:  jobsmith" in r.stdout and "new terminal" not in r.stdout
    else:
        assert "Open a new terminal window, then run:  jobsmith" in r.stdout and "uv tool update-shell" in r.stdout


def _run_ps1(tmp_path: Path, fake_rest: str, uv_body: str, pypi_up: bool = True, env: dict | None = None):
    """install.ps1 with stand-ins: Invoke-RestMethod answers like GitHub, Invoke-WebRequest like pypi.org, uv is
    a function that logs installs (uv_body decides its exit code), jobsmith marks that doctor ran."""
    log = tmp_path / "uv.log"
    web = "" if pypi_up else "throw [System.Exception]::new('fake: no route to pypi.org')"
    script = (f"function Invoke-RestMethod {{ {fake_rest} }}\n"
              f"function Invoke-WebRequest {{ {web} }}\n"
              "function Start-Sleep { }\n"
              f"function uv {{ if ($args[0] -eq 'tool' -and $args[1] -eq 'dir') {{ return '{tmp_path}' }}; "
              "if ($args[0] -eq '--version') { return 'uv 0.0.0' }; "
              f"Add-Content -Path '{log}' -Value ($args -join ' '); {uv_body} }}\n"
              f"function jobsmith {{ Set-Content -Path '{tmp_path / 'doctor.ran'}' -Value 1 }}\n"
              f"& '{ROOT / 'install.ps1'}'\n")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ, "TEMP": str(tmp_path), **(env or {})})
    return r, log


def _rest_release(body: str) -> str:
    return f"return ('{body}' | ConvertFrom-Json)"


@ps_only
@pytest.mark.parametrize("case", CASES)
def test_install_ps1_picks_the_release(tmp_path, case):
    code, body, want, *curl_exit = CASES[case]
    if curl_exit:
        pytest.skip("a timeout mid-body is a curl case; Invoke-RestMethod throws without a usable answer")
    if code == "200":
        fake = _rest_release(body)
    else:   # Invoke-RestMethod throws; an HTTP error carries Response.StatusCode, a network failure doesn't
        status = "" if code == "000" else f"Add-Member -InputObject $e -NotePropertyName Response -NotePropertyValue ([pscustomobject]@{{StatusCode={code}}});"
        fake = f"$e = [System.Exception]::new('fake {code}'); {status} throw $e"
    r, log = _run_ps1(tmp_path, fake, "$global:LASTEXITCODE = 0")    # a real uv sets it
    if want is None:
        assert r.returncode != 0 and not log.exists(), (r.stdout, r.stderr)
        return
    assert r.returncode == 0, (r.stdout, r.stderr)
    [args] = _installs(log)
    no_build, rest = _source_args(args)
    assert rest == _expected(want)
    assert no_build == (set() if want[0] == "wheel" else set(NATIVE_PS1))
    assert "Done. Run:  jobsmith" in r.stdout       # jobsmith (a function here) is found in this window


@ps_only
def test_install_ps1_installs_a_given_wheel_without_asking_github(tmp_path):
    r, log = _run_ps1(tmp_path, "throw [System.Exception]::new('offline')", "$global:LASTEXITCODE = 0",
                      env={"JOBSMITH_WHEEL": r"C:\build\jobsmith-0.4.2-py3-none-any.whl"})
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _installs(log) == [["--no-build", r"C:\build\jobsmith-0.4.2-py3-none-any.whl"]]


@ps_only
def test_install_ps1_says_when_pypi_is_unreachable(tmp_path):
    r, log = _run_ps1(tmp_path, _rest_release(_release("v0.4.2", WHEEL)), "$global:LASTEXITCODE = 0", pypi_up=False)
    assert r.returncode != 0 and not log.exists()
    assert "Couldn't reach pypi.org" in r.stdout


@ps_only
def test_install_ps1_tries_again_when_the_connection_drops(tmp_path):
    flag = tmp_path / "tried"
    body = (f"if (-not (Test-Path '{flag}')) {{ Set-Content -Path '{flag}' -Value 1; "
            "Write-Error 'error: Failed to fetch: https://files.pythonhosted.org/x.whl (operation timed out)'; "
            "$global:LASTEXITCODE = 2 } else { $global:LASTEXITCODE = 0 }")
    r, log = _run_ps1(tmp_path, _rest_release(_release("v0.4.2", WHEEL)), body)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert len(_installs(log)) == 2 and "Trying once more" in r.stdout


@ps_only
def test_install_ps1_shows_a_short_message_when_a_package_wont_install(tmp_path):
    body = ("Write-Error 'error: Failed to build `cryptography==50.0.2`'; "
            "1..300 | ForEach-Object { Write-Error \"   Compiling openssl-sys $_\" }; $global:LASTEXITCODE = 1")
    r, log = _run_ps1(tmp_path, _rest_release(_release("v0.4.2", WHEEL)), body)
    assert r.returncode != 0 and "Done" not in r.stdout, (r.stdout, r.stderr)
    assert len(_installs(log)) == 1
    assert "Jobsmith couldn't install a package for this computer" in r.stdout
    assert f"{REPO}/issues/new" in r.stdout and "cryptography==50.0.2" in r.stdout
    assert len(r.stdout.splitlines()) < 35
    assert not (tmp_path / "doctor.ran").exists()
