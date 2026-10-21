import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

CHECK = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "check.py"))


@pytest.mark.parametrize("failure", [None, 0, 1, 2])
def test_full_check_propagates_failure_and_stops_without_reporting_success(
    tmp_path, monkeypatch, capsys, failure
):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: "node")
    observed = []

    def execute(command, **kwargs):
        observed.append((command, kwargs))
        return SimpleNamespace(returncode=7 if len(observed) - 1 == failure else 0)

    result = CHECK["run_checks"](tmp_path, execute, files=[])
    assert result == (0 if failure is None else 7)
    assert len(observed) == (3 if failure is None else failure + 1)
    assert ("All checks passed." in capsys.readouterr().out) == (failure is None)
    assert all(options["env"]["QT_QPA_PLATFORM"] == "offscreen" for _, options in observed)


def test_missing_frontend_runtime_is_a_failure_not_a_silent_skip(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: None)
    assert CHECK["run_checks"](tmp_path, lambda *a, **k: pytest.fail("missing runtime")) == 1
    assert "Node.js is required" in capsys.readouterr().out


def test_a_fresh_clone_gets_a_folder_for_the_test_temp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: "node")
    basetemps = []

    def execute(command, **kwargs):
        if "--basetemp" in command:
            basetemps.append(Path(command[command.index("--basetemp") + 1]))
        return SimpleNamespace(returncode=0)

    assert CHECK["run_checks"](tmp_path, execute, files=[]) == 0
    assert basetemps and basetemps[0].parent.is_dir()


# Built from pieces so that this file does not trip the scan it tests.
FAKE_SECRETS = {
    "Anthropic key": "sk-" + "ant-api03-" + "x" * 40,
    "GitHub token": "gh" + "p_" + "A" * 36,
    "Google OAuth secret": "GOC" + "SPX-" + "a" * 28,
    "private key": "-----BEGIN " + "RSA PRIVATE KEY-----",
}


@pytest.mark.parametrize("kind", FAKE_SECRETS)
def test_a_committable_credential_fails_the_check_before_anything_runs(
    tmp_path, monkeypatch, capsys, kind
):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: "node")
    leak = tmp_path / "config.py"
    leak.write_text(f'TOKEN = "{FAKE_SECRETS[kind]}"\n', encoding="utf-8")
    ran = []
    result = CHECK["run_checks"](tmp_path, lambda *a, **k: ran.append(a), files=[leak])
    out = capsys.readouterr().out
    assert result == 1 and not ran
    assert f"config.py:1: {kind}" in out
    # The report names where, never what: it is safe to paste into an issue.
    assert FAKE_SECRETS[kind] not in out


def test_private_terms_come_from_the_ignored_env_file_and_match_any_case(tmp_path, monkeypatch):
    monkeypatch.delenv("PAPERFACT_PRIVATE_TERMS", raising=False)
    (tmp_path / ".env").write_text(
        "PAPERFACT_PRIVATE_TERMS=someone@example.net, jdoe-laptop\n", encoding="utf-8"
    )
    notes = tmp_path / "notes.md"
    notes.write_text("ok\nContact SomeOne@Example.NET\nbuilt on jdoe-laptop\n", encoding="utf-8")
    terms = CHECK["private_terms"](tmp_path)
    assert CHECK["scan_privacy"](tmp_path, [notes], terms) == [
        "notes.md:2: private term #1",
        "notes.md:3: private term #2",
    ]


def test_binary_files_and_clean_text_pass(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\0\0" + FAKE_SECRETS["GitHub token"].encode())
    readme = tmp_path / "README.md"
    readme.write_text("Set S2_API_KEY in .env; see sk-ant-... in the docs.\n", encoding="utf-8")
    assert CHECK["scan_privacy"](tmp_path, [image, readme], []) == []


def test_outside_a_git_checkout_the_scan_fails_rather_than_passing_blind(tmp_path, monkeypatch):
    failed = SimpleNamespace(returncode=128, stdout=b"")
    monkeypatch.setattr(CHECK["subprocess"], "run", lambda *a, **k: failed)
    assert CHECK["committable_files"](tmp_path) is None

