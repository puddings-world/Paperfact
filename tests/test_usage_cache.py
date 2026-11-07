import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from paper_daily import ai_choices, ai_usage, llm, usage_cache
from paper_daily.ai_types import Completion, Settings


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(ai_usage, "local_summary", lambda cfg: None)
    cache = usage_cache.UsageCache()
    monkeypatch.setattr(usage_cache, "cache", cache)
    return cache


def test_cache_is_account_scoped_and_only_completed_account_is_invalidated(setup, monkeypatch):
    calls = []
    monkeypatch.setattr(ai_usage, "subscription", lambda cfg: (
        calls.append(cfg.account_id) or {"windows": [], "message": cfg.account_id}
    ))
    a, b = Settings("cli", account_id="a"), Settings("codex", account_id="b")
    first = setup.read(a)
    setup.read(b)
    assert setup.read(a) == first and calls == ["a", "b"]
    usage_cache.invalidate(a)
    assert setup.read(a)["version"] != first["version"]
    setup.read(b)
    assert calls == ["a", "b", "a"]


def test_parallel_refresh_shares_one_query_and_closure_cannot_destroy_worker(setup, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def subscription(cfg):
        calls.append(cfg.backend)
        entered.set()
        assert release.wait(3)
        return {"windows": [], "message": "fixture"}

    monkeypatch.setattr(ai_usage, "subscription", subscription)
    cfg = Settings("cli")
    setup.refresh_background(cfg)
    assert entered.wait(2)
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = [pool.submit(setup.read, cfg) for _ in range(8)]
        for _ in range(50):
            setup.refresh_background(cfg)
        release.set()
        snapshots = [future.result(3) for future in pending]
    assert calls == ["cli"] and len({item["version"] for item in snapshots}) == 1
    assert setup.peek(cfg) == snapshots[0]


def test_call_during_fetch_is_not_swallowed_and_failure_can_retry(setup, monkeypatch):
    cfg = Settings("cli")

    def during_fetch(chosen):
        usage_cache.invalidate(chosen)
        return {"windows": [], "message": "first"}

    monkeypatch.setattr(ai_usage, "subscription", during_fetch)
    first = setup.read(cfg)
    monkeypatch.setattr(ai_usage, "subscription", lambda cfg: {"windows": [], "message": "new"})
    assert setup.read(cfg)["version"] != first["version"]

    def fail(cfg):
        raise RuntimeError("secret")

    monkeypatch.setattr(ai_usage, "subscription", fail)
    assert "未知" in setup.read(cfg, force=True)["quota"]["message"]
    monkeypatch.setattr(ai_usage, "subscription", lambda cfg: {"windows": [], "message": "retry"})
    assert setup.read(cfg, force=True)["quota"]["message"] == "retry"


def test_llm_receipt_marks_only_used_connection_even_on_failed_answer(setup, monkeypatch):
    class Provider:
        def complete(self, request, cfg, post):
            return Completion(None, "fixture failure")

    monkeypatch.setitem(llm._PROVIDERS, "cli", Provider())
    cfg = Settings("cli", account_id="a")
    llm.complete_result("private", cfg=cfg)
    assert usage_cache.marker(cfg).exists()
    assert not usage_cache.marker(Settings("cli", account_id="b")).exists()


def test_desktop_startup_monitor_checks_connections_without_opening_picker(setup, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget

    from paper_daily.desktop.usage_monitor import UsageMonitor

    app = QApplication.instance() or QApplication([])
    cfg = Settings("cli", account_id="a")
    monkeypatch.setattr(ai_choices, "accounts", lambda: [cfg])
    monkeypatch.setattr(ai_choices, "choices", lambda backend: [])
    ready = threading.Event()
    monkeypatch.setattr(ai_usage, "subscription", lambda cfg: (
        ready.set() or {"windows": [], "message": "ready"}
    ))
    owner = QWidget()
    monitor = UsageMonitor(owner)
    app.processEvents()
    assert ready.wait(2)
    for _ in range(100):
        if setup.peek(cfg):
            break
        QTest.qWait(5)
    assert setup.peek(cfg)["quota"]["message"] == "ready"
    monitor.timer.stop()
    owner.deleteLater()


def test_monitor_prefetches_unsaved_terminal_accounts_once_per_identity(setup, monkeypatch):
    from PySide6.QtWidgets import QApplication, QWidget

    from paper_daily.desktop.usage_monitor import UsageMonitor

    app = QApplication.instance() or QApplication([])
    saved = Settings("cli", account_id="saved")
    monkeypatch.setattr(ai_choices, "accounts", lambda: [saved])
    monkeypatch.setattr(ai_choices, "choices", lambda backend: (
        [saved] if backend == "cli" else [Settings(backend, isolated=True)]
    ))
    requested = []
    monkeypatch.setattr(setup, "refresh_background", lambda cfg: requested.append(
        ai_choices.account_key(cfg)
    ))
    owner = QWidget()
    monitor = UsageMonitor(owner)
    app.processEvents()
    assert monitor._reads.wait()
    assert requested == [("cli", "saved"), ("codex", "local"), ("gemini", "local")]
    monitor.timer.stop()
    owner.deleteLater()


def test_the_monitor_reads_settings_off_the_windows_thread(setup, monkeypatch):
    # Read on the window's thread every two seconds, the settings files froze it
    # for up to two seconds whenever the disk was busy, for as long as it was open.
    from PySide6.QtWidgets import QApplication, QWidget

    from paper_daily.desktop.usage_monitor import UsageMonitor

    app = QApplication.instance() or QApplication([])
    saved = Settings("cli", account_id="saved")
    on_main = []

    def accounts():
        on_main.append(threading.current_thread() is threading.main_thread())
        return [saved]

    monkeypatch.setattr(ai_choices, "accounts", accounts)
    monkeypatch.setattr(ai_choices, "choices", lambda backend: [])
    monkeypatch.setattr(setup, "refresh_background", lambda cfg: None)
    owner = QWidget()
    monitor = UsageMonitor(owner)
    monitor.timer.stop()
    app.processEvents()
    monitor.tick_in_background()
    assert monitor._reads.wait()
    app.processEvents()
    assert on_main and not any(on_main)
    owner.deleteLater()
