"""Accepted window close disposes metadata observation; rejected close keeps it live."""

import threading
import time

from PySide6.QtGui import QCloseEvent
from test_integration_desktop import workspace as workspace

from paper_daily.desktop.main import MainWindow


def settle(app, condition, timeout=5):
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert condition()


def test_accepted_parent_close_stops_future_watch_reads_and_rejects_late_delivery(
    workspace, monkeypatch
):
    window = MainWindow()
    watcher = window.workspace_changes
    entered, release = threading.Event(), threading.Event()
    original = watcher._revision
    calls, notifications = [], []

    def held():
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return original()

    monkeypatch.setattr(watcher, "_revision", held)
    watcher.changed.connect(lambda: notifications.append(True))
    watcher.poll_in_background()
    try:
        assert entered.wait(5)
        event = QCloseEvent()
        window.closeEvent(event)
        assert event.isAccepted()
        assert watcher.disposed and not watcher.timer.isActive()
        watcher.timer.timeout.emit()
        watcher.poll_in_background()
        watcher.poll()
    finally:
        release.set()
    settle(workspace, lambda: not watcher._reading)
    assert calls == [True] and not notifications
    window.deleteLater()
    workspace.processEvents()


def test_rejected_parent_close_keeps_watcher_available_until_accepted(workspace, monkeypatch):
    window = MainWindow()
    watcher = window.workspace_changes
    handle = window.activity_hub.begin(window, "Synthetic active work", "watcher-close")
    try:
        event = QCloseEvent()
        window.closeEvent(event)
        assert not event.isAccepted()
        assert not watcher.disposed and watcher.timer.isActive()
    finally:
        handle.finish(cancelled=True)
    window.close()
    assert watcher.disposed and not watcher.timer.isActive()
    window.deleteLater()
    workspace.processEvents()
