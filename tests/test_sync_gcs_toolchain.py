"""Declared operator setup runs in a disposable checkout, with no network installs."""

import ast
import json
import os
import shlex
import shutil
import subprocess
import sys
import sysconfig
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def test_operator_sdk_requirements_are_locked_and_not_desktop_runtime_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    operator = [Requirement(row) for row in project["optional-dependencies"]["gcp"]]
    assert {canonicalize_name(row.name) for row in operator} == {
        "google-cloud-storage",
        "google-crc32c",
    }
    desktop = {
        canonicalize_name(Requirement(row).name)
        for row in project["dependencies"] + project["optional-dependencies"]["app"]
    }
    for requirement in operator:
        assert canonicalize_name(requirement.name) not in desktop
        releases = [
            row
            for row in lock["package"]
            if canonicalize_name(row["name"]) == canonicalize_name(requirement.name)
        ]
        assert releases and all(requirement.specifier.contains(row["version"]) for row in releases)
    tree = ast.parse((ROOT / "packaging/paperfact.spec").read_text(encoding="utf-8"))
    analysis = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Analysis"
    )
    excluded = ast.literal_eval(
        next(item.value for item in analysis.keywords if item.arg == "excludes")
    )
    assert {"google.cloud", "google.auth", "google.api_core", "google_crc32c"} <= set(excluded)


def test_headless_operator_setup_preserves_desktop_environment_and_never_creates_research(tmp_path):
    root = tmp_path / "operator source"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    for name in ("setup-sync-service.ps1", "setup-sync-service.sh"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    desktop = root / ".venv"
    desktop.mkdir()
    sentinel = desktop / "keep-desktop-environment"
    sentinel.write_bytes(b"existing desktop environment")
    driver = tmp_path / "fake_uv.py"
    driver.write_text(
        """import json,os,sys,venv
from pathlib import Path
root=Path(os.environ['UV_PROJECT_ENVIRONMENT'])
assert root == Path.cwd()/'.venv-sync'
assert sys.argv[1:] == ['sync','--locked','--python','3.11','--extra','gcp']
Path(os.environ['TEST_UV_RECORD']).write_text(json.dumps(sys.argv[1:]))
venv.EnvBuilder(with_pip=False).create(root)
""",
        encoding="utf-8",
    )
    record, restored = tmp_path / "uv-record.json", tmp_path / "restored-env.txt"
    prior = str(tmp_path / "prior-operator-environment")
    env = {
        **os.environ,
        "TEST_UV_RECORD": str(record),
        "TEST_ROOT": str(root),
        "TEST_DRIVER": str(driver),
        "TEST_PYTHON": sys.executable,
        "TEST_RESTORED": str(restored),
        "UV_PROJECT_ENVIRONMENT": prior,
        "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), sysconfig.get_paths()["purelib"])),
        "PYTHONUTF8": "1",
        "PAPERFACT_DATA": str(tmp_path / "not-created"),
        "GOOGLE_APPLICATION_CREDENTIALS": str(tmp_path / "not-a-credential.json"),
    }
    if os.name == "nt":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        assert shell, "PowerShell is required to exercise the Windows setup script"
        harness = tmp_path / "invoke.ps1"
        harness.write_text(
            """function uv { & $env:TEST_PYTHON $env:TEST_DRIVER @args }
& (Join-Path $env:TEST_ROOT 'scripts/setup-sync-service.ps1')
[IO.File]::WriteAllText($env:TEST_RESTORED, $env:UV_PROJECT_ENVIRONMENT)
""",
            encoding="utf-8",
        )
        command = [
            shell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
        ]
    else:
        shell = shutil.which("bash")
        assert shell, "Bash is required to exercise the POSIX setup script"
        binaries = tmp_path / "bin"
        binaries.mkdir()
        fake = binaries / "uv"
        fake.write_text(
            "#!/bin/sh\nexec "
            + shlex.quote(sys.executable)
            + " "
            + shlex.quote(str(driver))
            + ' "$@"\n',
            encoding="utf-8",
        )
        fake.chmod(0o700)
        env["PATH"] = str(binaries) + os.pathsep + env.get("PATH", "")
        command = [shell, str(scripts / "setup-sync-service.sh")]
    result = subprocess.run(
        command,
        env=env,
        cwd=tmp_path,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=45,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(record.read_text()) == [
        "sync",
        "--locked",
        "--python",
        "3.11",
        "--extra",
        "gcp",
    ]
    assert "upload-backup" in result.stdout and "No authority, cloud login" in result.stdout
    assert sentinel.read_bytes() == b"existing desktop environment"
    assert not (tmp_path / "not-created").exists()
    if os.name == "nt":
        assert restored.read_text() == prior
    assert not (root / "data").exists()


def test_headless_publication_imports_no_desktop_and_creates_no_default_research(tmp_path):
    program = """import json,sys
from pathlib import Path
from test_sync_gcs_backup import Client
from paper_daily import lineage_dependencies, sync_admin
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_gcs_backup as gcs
root=Path(sys.argv[1])
sync_admin.initialize(root/'authority')
backup.export(root/'authority',root/'snapshot')
result=gcs.publish(root/'snapshot','fixture-private-backups',client=Client())
assert not any(name.startswith(('PySide6','paper_daily.desktop')) for name in sys.modules)
print(json.dumps(result))
"""
    unused = tmp_path / "must-not-create-research"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests"))),
        "PYTHONUTF8": "1",
        "PAPERFACT_DATA": str(unused),
        "GOOGLE_APPLICATION_CREDENTIALS": str(tmp_path / "not-a-credential.json"),
    }
    env.pop("STORAGE_EMULATOR_HOST", None)
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)],
        env=env,
        cwd=tmp_path,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["state"] == "published"
    assert not unused.exists()
