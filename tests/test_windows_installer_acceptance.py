"""Installer orchestration with synthetic files; no native installer is executed."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from test_built_app_verification import verify

from paper_daily import __version__


@pytest.fixture
def ci_build(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "ROOT", tmp_path)
    monkeypatch.setattr(verify.sys, "platform", "win32")
    for key, value in {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "puddings-world/Paperfact",
        "GITHUB_WORKSPACE": str(tmp_path), "GITHUB_SHA": "a" * 40,
    }.items():
        monkeypatch.setenv(key, value)
    built = tmp_path / "dist/Paperfact"
    (built / "_internal").mkdir(parents=True)
    (built / "_internal/build-info.json").write_text(
        json.dumps(dict(commit="a" * 40, dirty=False)), encoding="utf-8",
    )
    for name in ("Paperfact.exe", "paperfact-cli.exe"):
        (built / name).write_bytes(b"synthetic executable")
    installer = tmp_path / "dist" / f"Paperfact-{__version__}-windows-x64-setup.exe"
    installer.write_bytes(b"synthetic installer")
    out = tmp_path / "build/acceptance"
    out.mkdir(parents=True)
    return built, out, installer


def test_preflight_refuses_unowned_builds_and_existing_destination(ci_build, monkeypatch):
    built, out, installer = ci_build
    # Refusal must happen before creating a destination or executing any child.
    def forbidden(*args, **kwargs):
        pytest.fail("Preflight launched a child process")

    monkeypatch.setattr(verify.subprocess, "run", forbidden)
    for key, value in (("GITHUB_ACTIONS", "false"),
                       ("GITHUB_REPOSITORY", "foreign/repo"),
                       ("GITHUB_SHA", "b" * 40)):
        with monkeypatch.context() as patch:
            patch.setenv(key, value)
            with pytest.raises(ValueError, match="matching clean Windows CI"):
                verify._installer_input(built, out, installer)
        assert not (out / "installed-app").exists()
    with pytest.raises(ValueError, match="expected CI artifact paths"):
        verify._installer_input(built, out, installer.with_name("other.exe"))
    destination = out / "installed-app"
    destination.mkdir()
    sentinel = destination / "preserve.txt"
    sentinel.write_bytes(b"existing installation")
    with pytest.raises(FileExistsError):
        verify._installer_input(built, out, installer)
    assert sentinel.read_bytes() == b"existing installation"


@pytest.mark.parametrize("fault", [None, "research", "version", "uninstall"])
def test_installer_preserves_data_and_records_exact_failure(ci_build, fault):
    built, out, installer = ci_build
    plan = verify._installer_input(built, out, installer)
    recipient = verify.isolated_env(out / "recipient")
    research = Path(recipient["PAPERFACT_DATA"])
    research.mkdir(parents=True, exist_ok=True)
    paper = research / "original.pdf"
    paper.write_bytes(b"synthetic original")
    before = verify._data_hash(out / "recipient")
    acceptance = verify.Acceptance(built, out)
    acceptance.report["build"]["version"] = __version__
    seen = []
    installed = plan["installed"]

    def run(label, command, env, *, before=None, after=None):
        def execute():
            if before is not None:
                before()
            seen.append((label, list(map(str, command))))
            assert env is recipient
            assert acceptance.report["active_check"] == label
            if label in {"windows-install", "windows-reinstall"}:
                for name in ("Paperfact.exe", "paperfact-cli.exe", "_internal/build-info.json"):
                    target = installed / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(built / name, target)
                (installed / "unins000.exe").write_bytes(b"synthetic uninstaller")
                if fault == "research" and label == "windows-reinstall":
                    paper.write_bytes(b"unexpected mutation")
            if label == "windows-uninstall" and fault != "uninstall":
                # Exact synthetic files only: no recursive cleanup or wildcard deletion.
                for name in ("Paperfact.exe", "paperfact-cli.exe", "unins000.exe",
                             "_internal/build-info.json"):
                    (installed / name).unlink()
            stdout = ("paperfact " + ("0.0.0" if fault == "version" else __version__)).encode()
            if after is not None:
                after(stdout)
            return stdout
        return acceptance.call(label, execute)

    def integration(command, workspace, env):
        assert command == [installed / "paperfact-cli.exe"]
        assert workspace == out / "installed-integration"
        assert env == {"isolated": "yes"}
        return dict(retry_preserved=True, restart_recovery=True)

    def perform():
        return verify._windows_install(
            plan, out, recipient, {"isolated": "yes"}, run, acceptance, integration,
        )

    if fault:
        with pytest.raises(ValueError) as failure:
            perform()
        acceptance.failed(failure.value)
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        stage = {"research": "windows-reinstall", "version": "windows-installed-version",
                 "uninstall": "windows-uninstall"}[fault]
        assert report["status"] == "failed" and not report["passed"]
        assert report["active_check"] == stage
        assert stage not in report["completed_checks"]
        if fault != "uninstall":
            assert "windows-uninstall" not in [label for label, _ in seen]
        assert installed.exists()  # Failed evidence is retained, never auto-cleaned.
        return
    result = perform()
    assert result["installed"] and result["reinstalled"] and result["uninstalled"]
    assert result["research_preserved"] and result["integration"]["restart_recovery"]
    assert result["installer_sha256"] == hashlib.sha256(installer.read_bytes()).hexdigest()
    assert not result["older_release_upgrade_checked"] and not result["registry_shortcuts_checked"]
    assert verify._data_hash(out / "recipient") == before
    assert paper.read_bytes() == b"synthetic original"
    assert [label for label, _ in seen] == [
        "windows-install", "windows-installed-version", "windows-installed-reader",
        "windows-reinstall", "windows-uninstall",
    ]
    for label, command in seen:
        if label in {"windows-install", "windows-reinstall", "windows-uninstall"}:
            assert "/NORESTART" in command and "/VERYSILENT" in command
            assert "/LOG=" + str(out / (label + "-inno.log")) in command
        if label in {"windows-install", "windows-reinstall"}:
            assert "/ACCEPTANCETEST=1" in command
            assert "/DIR=" + str(installed) in command
            assert "/NOCLOSEAPPLICATIONS" in command and "/NORESTARTAPPLICATIONS" in command
    # A changed installer is rejected before a subsequent native action.
    installer.write_bytes(b"changed installer")
    seen.clear()
    with pytest.raises(ValueError, match="changed since preflight"):
        perform()
    assert not seen
    assert acceptance.report["active_check"] == "windows-install"
