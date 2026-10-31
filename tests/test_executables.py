"""Display discovery is bounded, context-specific and independent of account state."""

import threading
import time

import pytest

from paper_daily import diagnostics, executables


def idle():
    deadline = time.monotonic() + 8
    while True:
        with executables._lock:
            if not executables._rechecking:
                return
        assert time.monotonic() < deadline, "Fixture executable refresh did not finish"
        threading.Event().wait(0.005)


@pytest.fixture(autouse=True)
def clean_cache():
    idle()
    with executables._lock:
        executables._found.clear()
    yield
    idle()


def test_cached_found_and_missing_answers_do_not_repeat_walk(monkeypatch):
    calls = []
    monkeypatch.setattr(
        executables.shutil,
        "which",
        lambda name: calls.append(name) or ("/fixture/program" if name == "present" else None),
    )
    for _ in range(3):
        assert executables.which("present") == "/fixture/program"
        assert executables.which("missing") is None
    assert calls == ["present", "missing"]


@pytest.mark.parametrize("context", ["PATH", "PATHEXT", "cwd", "lookup"])
def test_lookup_context_changes_are_not_answered_from_another_context(
    monkeypatch, tmp_path, context
):
    calls = []
    monkeypatch.setattr(executables.shutil, "which", lambda name: calls.append(name) or "/old")
    assert executables.which("program") == "/old"
    if context in {"PATH", "PATHEXT"}:
        monkeypatch.setenv(context, "changed-fixture-value")
    elif context == "cwd":
        monkeypatch.chdir(tmp_path)
    else:
        monkeypatch.setattr(executables.shutil, "which", lambda name: calls.append("new") or "/new")
    result = executables.which("program")
    assert len(calls) == 2
    assert result == ("/new" if context == "lookup" else "/old")


def test_stale_answers_return_while_one_refresh_is_held(monkeypatch):
    entered, release, calls = threading.Event(), threading.Event(), []

    def lookup(name):
        calls.append(name)
        if len(calls) > 1:
            entered.set()
            assert release.wait(8)
            return "/new"
        return "/old"

    monkeypatch.setattr(executables.shutil, "which", lookup)
    assert executables.which("program") == "/old"
    try:
        assert executables.which("program", recheck=-1) == "/old"
        assert entered.wait(8)
        for _ in range(30):
            assert executables.which("program", recheck=-1) == "/old"
        assert calls == ["program", "program"]
    finally:
        release.set()
    idle()
    assert executables.which("program") == "/new"


def test_late_refresh_cannot_overwrite_new_environment_answer(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def lookup(name):
        calls.append(1)
        if len(calls) == 1:
            return "/old"
        if len(calls) == 2:
            entered.set()
            assert release.wait(8)
            return "/late-old-context"
        return "/new-context"

    monkeypatch.setattr(executables.shutil, "which", lookup)
    assert executables.which("program") == "/old"
    try:
        assert executables.which("program", recheck=-1) == "/old"
        assert entered.wait(8)
        monkeypatch.setenv("PATH", "new-fixture-context")
        assert executables.which("program") == "/new-context"
    finally:
        release.set()
    idle()
    assert executables.which("program") == "/new-context" and len(calls) == 3
    with executables._lock:
        assert len(executables._found) == 1


def test_failed_refresh_and_failed_thread_start_remain_retryable(monkeypatch):
    calls = []

    def lookup(name):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("synthetic inaccessible PATH")
        return "/fixture"

    monkeypatch.setattr(executables.shutil, "which", lookup)
    assert executables.which("program") == "/fixture"
    assert executables.which("program", recheck=-1) == "/fixture"
    idle()
    assert len(calls) == 2
    original = executables.threading.Thread.start
    with monkeypatch.context() as patch:
        patch.setattr(
            executables.threading.Thread, "start", lambda _: (_ for _ in ()).throw(RuntimeError())
        )
        assert executables.which("program", recheck=-1) == "/fixture"
        assert not executables._rechecking
    assert executables.threading.Thread.start is original
    assert executables.which("program", recheck=-1) == "/fixture"
    idle()
    assert len(calls) == 3


def test_cache_and_background_concurrency_are_bounded(monkeypatch):
    entered, release, started = threading.Event(), threading.Event(), []
    blocked = [False]

    def lookup(name):
        if blocked[0]:
            started.append(name)
            if len(started) == executables.MAX_REFRESHES:
                entered.set()
            assert release.wait(8)
        return "/fixture"

    monkeypatch.setattr(executables.shutil, "which", lookup)
    for index in range(executables.MAX_CACHED + 10):
        executables.which(f"program-{index}")
    assert len(executables._found) == executables.MAX_CACHED
    blocked[0] = True
    try:
        for index in range(20, 40):
            assert executables.which(f"program-{index}", recheck=-1) == "/fixture"
        assert entered.wait(8)
        assert len(started) == executables.MAX_REFRESHES
    finally:
        release.set()
    idle()


def test_diagnostics_reuses_boolean_presence_without_exporting_paths(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        executables.shutil, "which", lambda name: calls.append(name) or "/private/fixture"
    )
    first, second = diagnostics.collect(tmp_path), diagnostics.collect(tmp_path)
    assert (
        first["agent_commands_found"]
        == second["agent_commands_found"]
        == {"claude": True, "codex": True, "gemini": True}
    )
    assert calls == ["claude", "codex", "gemini"]
    assert "/private/fixture" not in diagnostics.render(second)
