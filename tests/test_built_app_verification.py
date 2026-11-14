import hashlib
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
import types
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify", ROOT / "scripts/verify_built_app.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def test_verification_does_not_inherit_developer_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'private')
    monkeypatch.setenv('CODEX_HOME', '/private/codex')
    monkeypatch.setenv('PAPERFACT_DATA', '/private/research')
    env = verify.isolated_env(tmp_path)
    assert 'ANTHROPIC_API_KEY' not in env and 'CODEX_HOME' not in env
    assert Path(env['PAPERFACT_DATA']).is_relative_to(tmp_path)
    assert Path(env['HOME']).is_relative_to(tmp_path)


def test_frozen_roundtrip_checks_pdf_bytes_not_just_counts(tmp_path):
    first, second = tmp_path / 'a.zip', tmp_path / 'b.zip'
    for target in (first, second):
        with zipfile.ZipFile(target, 'w') as archive:
            archive.writestr('files/pdf/demo.pdf', b'original bytes')
    assert verify.compare_files(first, second) == 1
    with zipfile.ZipFile(second, 'w') as archive:
        archive.writestr('files/pdf/demo.pdf', b'changed bytes')
    with pytest.raises(ValueError, match='changed'):
        verify.compare_files(first, second)


def test_zero_exit_does_not_hide_a_background_traceback():
    result = subprocess.CompletedProcess([], 0, b'Checks complete',
                                         b'Traceback (most recent call last):\nworker failed')
    with pytest.raises(RuntimeError, match='doctor failed'):
        verify.check_process(result, 'doctor')
    verify.check_process(subprocess.CompletedProcess([], 0, b'Checks complete', b''), 'doctor')


@pytest.mark.parametrize("failure", ["exit", "traceback", "timeout", "missing", "interrupt"])
def test_failed_acceptance_reports_exact_stage_without_private_text(tmp_path, monkeypatch, failure):
    built, out = tmp_path / "built", tmp_path / "acceptance"
    metadata = built / "_internal" / "build-info.json"
    metadata.parent.mkdir(parents=True)
    secret = "private-account@example.invalid /private/research token=do-not-export"
    metadata.write_text(
        json.dumps(dict(commit="b" * 40, dirty=False, account=secret)), encoding="utf-8"
    )
    monkeypatch.setattr(verify, "host_architecture", lambda: secret)

    def fake(command, **kwargs):
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, b"paperfact 0.4.8\n", b"")
        if failure == "exit":
            return subprocess.CompletedProcess(command, 7, secret.encode(), secret.encode())
        if failure == "traceback":
            return subprocess.CompletedProcess(
                command, 0, b"", b"Traceback (most recent call last):" + secret.encode()
            )
        if failure == "timeout":
            raise subprocess.TimeoutExpired(secret, 90, output=secret.encode(), stderr=b"partial")
        if failure == "missing":
            raise FileNotFoundError(secret)
        raise KeyboardInterrupt(secret)

    monkeypatch.setattr(verify.subprocess, "run", fake)
    with pytest.raises(
        (RuntimeError, subprocess.TimeoutExpired, FileNotFoundError, KeyboardInterrupt)
    ):
        verify.verify(built, out)
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    codes = dict(
        exit="process_failed",
        traceback="background_traceback",
        timeout="timeout",
        missing="missing_file",
        interrupt="interrupted",
    )
    assert report["format"] == verify.FORMAT and report["passed"] is False
    assert report["status"] == ("interrupted" if failure == "interrupt" else "failed")
    assert report["active_check"] == "doctor"
    assert report["completed_checks"] == ["isolation", "version"]
    assert report["build"] == dict(commit="b" * 40, dirty=False, version="0.4.8")
    assert report["host"]["architecture"] == "other"
    assert report["failure"] == dict(
        code=codes[failure],
        returncode=7 if failure == "exit" else 0 if failure == "traceback" else None,
    )
    encoded = (out / "report.json").read_bytes()
    assert secret.encode() not in encoded and str(tmp_path).encode() not in encoded
    assert len(encoded) < 4096
    if failure in {"exit", "traceback", "timeout"}:
        assert secret.encode() in (out / "doctor.log").read_bytes()
    with pytest.raises(FileExistsError):
        verify.verify(built, out)
    assert (out / "report.json").read_bytes() == encoded


def test_running_then_successful_acceptance_keeps_full_roundtrip_contract(tmp_path, monkeypatch):
    """Script orchestration only; fake child apps are not native package acceptance."""
    out, seen = tmp_path / "acceptance", []

    def fake(command, **kwargs):
        env = kwargs["env"]
        destination = Path(env["HOME"]).parents[1]
        progress = json.loads((destination / "report.json").read_text(encoding="utf-8"))
        seen.append(progress["active_check"])
        assert not progress["passed"] and progress["status"] == "running"
        stdout = b""
        if "--version" in command:
            stdout = b"paperfact 0.5.0.dev\n"
        elif "-c" in command and "demo_workspace" in command[2]:
            with zipfile.ZipFile(command[-1], "w") as archive:
                archive.writestr("files/pdf/demo.pdf", b"synthetic original")
        elif "list-share-link" in command:
            checksum = hashlib.sha256(Path(command[2]).read_bytes()).hexdigest()
            stdout = (command[3] + "#paperfact-sha256=" + checksum).encode()
        elif "list-import" in command:
            workspace = Path(env["PAPERFACT_DATA"])
            workspace.mkdir(exist_ok=True)
            with closing(sqlite3.connect(workspace / "papers.db")) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS list_papers(id TEXT PRIMARY KEY)")
                db.execute("CREATE TABLE IF NOT EXISTS dives(id TEXT PRIMARY KEY,body TEXT)")
                db.execute("INSERT OR IGNORE INTO list_papers VALUES('fixture')")
                db.execute("INSERT OR IGNORE INTO dives VALUES('fixture','saved analysis')")
        elif "list-export" in command:
            shutil.copyfile(destination / "original.zip", command[-1])
        return subprocess.CompletedProcess(command, 0, stdout, b"")

    def integration(command, workspace, env):
        assert "CODEX_HOME" not in env and "ANTHROPIC_API_KEY" not in env
        return dict(retry_preserved=True, restart_recovery=True)

    monkeypatch.setattr(verify.subprocess, "run", fake)
    monkeypatch.setitem(
        sys.modules, "verify_local_integration", types.SimpleNamespace(verify=integration)
    )
    first = verify.verify(tmp_path / "built", out)
    saved = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert first == saved and first["passed"] and first["status"] == "passed"
    assert first["active_check"] is first["failure"] is None
    assert {
        "import",
        "import-again",
        "file-fidelity",
        "research-content",
        "local-integration",
    } <= set(first["completed_checks"])
    assert first["research_files_preserved"] == 1 and first["integration"]["retry_preserved"]
    assert first["build"] == dict(commit=None, dirty=None, version="0.5.0.dev")
    assert "hosted multi-device sync" in first["limitations"]
    assert verify.verify(tmp_path / "built", tmp_path / "retry")["status"] == "passed"
    assert seen.count("version") == 2


def test_main_returns_failure_without_printing_exception_or_old_success(
    tmp_path, monkeypatch, capsys
):
    secret = "private local failure /secret/workspace"

    def failed(*args, **kwargs):
        raise SystemExit(secret)

    monkeypatch.setattr(verify.subprocess, "run", failed)
    out = tmp_path / "acceptance"
    assert verify.main([str(tmp_path / "built"), str(out)]) == 1
    assert secret not in capsys.readouterr().err
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed" and report["failure"]["code"] == "unexpected_error"
    before = (out / "report.json").read_bytes()
    assert verify.main([str(tmp_path / "built"), str(out)]) == 1
    assert "earlier run" in capsys.readouterr().err
    assert (out / "report.json").read_bytes() == before


def test_packaged_metadata_is_bounded_and_does_not_infer_checkout_identity(tmp_path):
    metadata = tmp_path / "Contents" / "Resources" / "build-info.json"
    metadata.parent.mkdir(parents=True)
    for raw in [b"[", b"[]", b"x" * 140000]:
        metadata.write_bytes(raw)
        assert verify.packaged_identity(tmp_path) == dict(commit=None, dirty=None, version=None)
    metadata.write_text(json.dumps(dict(commit="private-account", dirty="true")), encoding="utf-8")
    assert verify.packaged_identity(tmp_path) == dict(commit=None, dirty=None, version=None)


def test_actual_cli_missing_bundle_reports_failure_and_preserves_previous_run(tmp_path):
    built, out = tmp_path / "missing-built-app", tmp_path / "acceptance"
    command = [sys.executable, str(ROOT / "scripts/verify_built_app.py"), str(built), str(out)]
    result = subprocess.run(command, capture_output=True, timeout=30)
    assert result.returncode == 1 and b"Acceptance failed" in result.stderr
    assert b"Traceback" not in result.stderr and str(tmp_path).encode() not in result.stderr
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed" and report["passed"] is False
    assert report["active_check"] == "version" and report["completed_checks"] == ["isolation"]
    assert report["failure"] == dict(code="missing_file", returncode=None)
    before = (out / "report.json").read_bytes()
    result = subprocess.run(command, capture_output=True, timeout=30)
    assert result.returncode == 1 and b"earlier run" in result.stderr
    assert (out / "report.json").read_bytes() == before
