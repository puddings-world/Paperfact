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

    result = CHECK["run_checks"](tmp_path, execute)
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

    assert CHECK["run_checks"](tmp_path, execute) == 0
    assert basetemps and basetemps[0].parent.is_dir()
