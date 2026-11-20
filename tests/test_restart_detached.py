"""`app --restart` reopens the reader in a process no terminal owns."""

import subprocess

import pytest

from paper_daily import workspace_open as opening


def recorder(refuse_breakaway=False):
    calls = []

    def launch(command, **kwargs):
        flags = kwargs.get("creationflags", 0)
        calls.append((command, kwargs))
        if refuse_breakaway and flags & subprocess.CREATE_BREAKAWAY_FROM_JOB:
            raise PermissionError("Access is denied")

    return calls, launch


@pytest.mark.skipif(not hasattr(subprocess, "CREATE_NO_WINDOW"), reason="Windows flags")
def test_the_new_reader_has_no_console_and_leaves_the_callers_job():
    calls, launch = recorder()
    opening.relaunch_detached(launch=launch, executable="py", frozen=False, environ={"A": "1"})
    [(command, kwargs)] = calls
    assert command == ["py", "-m", "paper_daily", "app"]  # Not --restart again.
    flags = kwargs["creationflags"]
    assert flags & subprocess.CREATE_NO_WINDOW and flags & subprocess.CREATE_BREAKAWAY_FROM_JOB
    assert kwargs["stdin"] is kwargs["stdout"] is kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["env"] == {"A": "1"}


@pytest.mark.skipif(not hasattr(subprocess, "CREATE_NO_WINDOW"), reason="Windows flags")
def test_a_job_that_forbids_breaking_away_still_gets_a_reader_without_a_console():
    calls, launch = recorder(refuse_breakaway=True)
    opening.relaunch_detached(launch=launch, executable="py", frozen=False, environ={})
    assert len(calls) == 2
    flags = calls[-1][1]["creationflags"]
    assert flags & subprocess.CREATE_NO_WINDOW and not flags & subprocess.CREATE_BREAKAWAY_FROM_JOB


def test_the_packaged_app_is_started_as_itself():
    calls, launch = recorder()
    opening.relaunch_detached(launch=launch, executable="Paperfact.exe", frozen=True, environ={})
    assert calls[0][0] == ["Paperfact.exe"]


def test_restart_hands_the_reader_to_a_detached_process(monkeypatch):
    from paper_daily.desktop import main

    for name in ("ensure_dirs", "init_db", "_install_error_log"):
        monkeypatch.setattr(main, name, lambda: None)
    monkeypatch.setattr(main.rich_view, "prepare", lambda: None)
    monkeypatch.setattr(main.runtime, "adopt_login_path", lambda: None)
    monkeypatch.setattr("paper_daily.ai_profiles.recheck_claude", lambda: None)
    monkeypatch.setattr(main, "_hand_off_to_running_instance", lambda *a: False)
    started = []
    monkeypatch.setattr(opening, "relaunch_detached", lambda: started.append(True))
    monkeypatch.setattr(main, "MainWindow", lambda *a, **k: pytest.fail("built a window here"))
    assert main.run(restart=True) == 0
    assert started == [True]
