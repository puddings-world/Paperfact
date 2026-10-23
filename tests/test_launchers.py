"""Run the launchers in isolated checkouts; never install tools or call an AI."""

import json
import os
import shutil
import subprocess
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def shell(name):
    found = shutil.which(name)
    if found:
        return found
    pytest.skip(f"{name} is unavailable on this platform")


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout with spaces"
    (root / "scripts").mkdir(parents=True)
    for name in ("dev.ps1", "dev.sh", "setup.ps1"):
        shutil.copyfile(ROOT / "scripts" / name, root / "scripts" / name)
    return root


def run_ps(path, env):
    executable = shutil.which("powershell") or shell("pwsh")
    return subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-File", str(path)],
        cwd=path.parent.parent.parent, env=env, capture_output=True,
        encoding="utf-8", errors="replace", timeout=30,
    )


@pytest.fixture
def python_checkout(checkout):
    if os.name != "nt":
        pytest.skip("Windows launcher uses the Windows venv layout")
    venv.EnvBuilder(with_pip=False).create(checkout / ".venv")
    package = checkout / "paper_daily"
    package.mkdir()
    (package / "__init__.py").touch()
    script = '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
phase = args[0] if args else ""
with Path(os.environ["TRACE"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(args, ensure_ascii=False) + "\\n")
print(json.dumps(args, ensure_ascii=False))
sys.exit(9 if os.environ.get("FAIL_STEP") == phase else int(os.environ.get("EXIT_CODE", "0")))
'''
    (package / "__main__.py").write_text(script, encoding="utf-8")
    (checkout / "scripts" / "make_icon.py").write_text(
        script.replace('args = sys.argv[1:]', 'args = ["icon"]'), encoding="utf-8")
    return checkout


@pytest.mark.parametrize("code", [0, 7])
def test_windows_launcher_preserves_arguments_cwd_and_exit_code(python_checkout, code):
    root = python_checkout
    harness = root / "scripts" / "run.ps1"
    harness.write_text(
        '& "$PSScriptRoot/dev.ps1" list-add "a list" "a citation with spaces"\n'
        'exit $LASTEXITCODE\n', encoding="utf-8")
    trace = root / "trace.jsonl"
    result = run_ps(harness, {**os.environ, "TRACE": str(trace), "EXIT_CODE": str(code)})
    assert result.returncode == code, result.stdout + result.stderr
    assert json.loads(trace.read_text(encoding="utf-8")) == [
        "list-add", "a list", "a citation with spaces"]


def test_windows_launcher_missing_environment_explains_setup(checkout):
    result = run_ps(checkout / "scripts" / "dev.ps1", os.environ.copy())
    assert result.returncode != 0
    assert "setup.ps1" in result.stderr


@pytest.mark.parametrize("failure", ["", "sync", "fonts", "web-assets", "icon"])
def test_windows_setup_stops_on_native_failure_before_printing_done(python_checkout, failure):
    root = python_checkout
    harness = root / "scripts" / "setup-test.ps1"
    harness.write_text('''function global:uv {
    $global:LASTEXITCODE = 0
    if ($env:FAIL_STEP -eq $args[0]) { $global:LASTEXITCODE = 9 }
}
& "$PSScriptRoot/setup.ps1"
''', encoding="utf-8")
    trace = root / "trace.jsonl"
    result = run_ps(harness, {**os.environ, "TRACE": str(trace), "FAIL_STEP": failure})
    assert (result.returncode == 0) == (not failure), result.stdout + result.stderr
    assert ("Done. Next:" in result.stdout) == (not failure)
    phases = [json.loads(line)[0] for line in trace.read_text(encoding="utf-8").splitlines()
              ] if trace.exists() else []
    expected = ["fonts", "web-assets", "icon"]
    if failure == "sync":
        expected = []
    elif failure:
        expected = expected[:expected.index(failure) + 1]
    assert phases == expected


def bash_executable():
    # Git Bash runs these shell semantics on Windows; it is not a macOS/Linux GUI test.
    git_bash = Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/bin/bash.exe"
    return str(git_bash) if os.name == "nt" and git_bash.exists() else shell("bash")


@pytest.mark.parametrize("code", [0, 7])
def test_bash_launcher_preserves_arguments_cwd_and_exit_code(checkout, code):
    python = checkout / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text('#!/usr/bin/env bash\nprintf "%s\\0" "$@" > "$TRACE"\n'
                      'exit "$EXIT_CODE"\n', encoding="utf-8", newline="\n")
    python.chmod(0o755)
    trace = checkout / "trace"
    result = subprocess.run(
        [bash_executable(), (checkout / "scripts/dev.sh").as_posix(),
         "list-add", "a list", "a citation with spaces", "--doi", "10.1234/test"],
        cwd=checkout.parent, env={**os.environ, "TRACE": trace.as_posix(), "EXIT_CODE": str(code)},
        capture_output=True, timeout=20,
    )
    assert result.returncode == code, result.stderr
    assert trace.read_bytes().decode().split("\0")[:-1] == [
        "-m", "paper_daily", "list-add", "a list", "a citation with spaces",
        "--doi", "10.1234/test"]


def test_bash_launcher_missing_environment_explains_setup(checkout):
    result = subprocess.run([bash_executable(), (checkout / "scripts/dev.sh").as_posix()],
                            cwd=checkout.parent, capture_output=True, timeout=20)
    assert result.returncode != 0 and b"setup.sh" in result.stderr
