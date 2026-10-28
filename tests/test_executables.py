"""Looking up programs on PATH without freezing the window."""

import threading

from paper_daily import executables


def test_a_program_is_looked_up_once_then_remembered(monkeypatch):
    calls = []
    monkeypatch.setattr(executables.shutil, "which", lambda name: calls.append(name) or "/x")
    assert executables.which("claude") == "/x"
    assert executables.which("claude") == "/x"
    assert calls == ["claude"]
    monkeypatch.setenv("PATH", "elsewhere")
    executables.which("claude")
    assert calls == ["claude", "claude"]


def test_an_old_answer_is_given_at_once_while_a_thread_asks_again(monkeypatch):
    # The tab switch that came 30 seconds after the last lookup was the one that
    # stuttered: a stale answer must not make the caller wait for the walk.
    asked, release = threading.Event(), threading.Event()
    answers = iter(["/old", "/new"])
    calls = []

    def which(name):
        calls.append(name)
        answer = next(answers)
        if answer == "/new":
            asked.set()
            assert release.wait(5)
        return answer

    monkeypatch.setattr(executables.shutil, "which", which)
    assert executables.which("codex") == "/old"
    assert executables.which("codex", recheck=-1) == "/old"
    assert asked.wait(5)
    # Still waiting on the walk, and a second stale question starts no second walk.
    assert executables.which("codex", recheck=-1) == "/old"
    release.set()
    for _ in range(500):
        if executables.which("codex") == "/new":
            break
        threading.Event().wait(0.01)
    assert executables.which("codex") == "/new"
    assert calls == ["codex", "codex"]
