"""Profile display discovery preserves scope and never waits for a stale refresh."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_daily import ai_profiles, executables


def idle():
    deadline = time.monotonic() + 8
    while executables._rechecking:
        assert time.monotonic() < deadline
        threading.Event().wait(0.005)


@pytest.fixture(autouse=True)
def actual_isolated_source():
    assert Path(ai_profiles.__file__).resolve() == (
        Path(__file__).resolve().parents[1] / "src/paper_daily/ai_profiles.py"
    )
    idle()
    executables._found.clear()
    if hasattr(ai_profiles, "_claude_found"):
        ai_profiles._claude_found.clear()
    yield
    idle()


def test_profile_stale_presence_returns_before_actual_refresh_finishes(monkeypatch):
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    calls, values, errors = [], [], []
    clock = [0.0]
    controlled = SimpleNamespace(monotonic=lambda: clock[0])
    monkeypatch.setattr(ai_profiles, "time", controlled, raising=False)
    monkeypatch.setattr(executables, "time", controlled)

    def lookup(name):
        calls.append(name)
        if len(calls) > 1:
            entered.set()
            assert release.wait(20)
        return "/fixture/claude"

    monkeypatch.setattr(executables.shutil, "which", lookup)
    monkeypatch.setattr(ai_profiles, "CLAUDE_RECHECK", 30)
    assert ai_profiles._claude_on_path()
    clock[0] = 31.0

    def ask():
        try:
            values.append(ai_profiles._claude_on_path())
        except Exception as error:
            errors.append(error)
        finally:
            returned.set()

    requester = threading.Thread(target=ask)
    try:
        requester.start()
        assert entered.wait(8)
        assert returned.wait(8), "Profile display waited for the stale PATH refresh"
        assert not errors and values == [True]
        assert all(ai_profiles._claude_on_path() for _ in range(20))
        assert calls == ["claude", "claude"]
    finally:
        release.set()
        requester.join(8)
        assert not requester.is_alive()
        idle()


def test_profile_presence_inherits_pathex_scope(monkeypatch):
    calls = []
    monkeypatch.setenv("PATHEXT", "fixture-first")

    def lookup(name):
        calls.append(name)
        return (
            "/fixture/claude"
            if __import__("os").environ["PATHEXT"] == "fixture-first"
            else None
        )

    monkeypatch.setattr(executables.shutil, "which", lookup)
    assert ai_profiles._claude_on_path()
    monkeypatch.setenv("PATHEXT", "fixture-second")
    assert not ai_profiles._claude_on_path()
    assert calls == ["claude", "claude"]


def test_explicit_negative_recheck_keeps_existing_uncached_behavior(monkeypatch):
    answers = iter(["/fixture/claude", None])
    monkeypatch.setattr(executables.shutil, "which", lambda name: next(answers))
    monkeypatch.setattr(ai_profiles, "CLAUDE_RECHECK", -1)
    assert ai_profiles._claude_on_path()
    assert not ai_profiles._claude_on_path()
