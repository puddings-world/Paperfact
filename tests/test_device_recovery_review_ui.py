"""Actual Qt recovery review with held workers and isolated device journals."""

import sqlite3
from contextlib import closing
from threading import Event

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QFileDialog
from test_sync_device_recovery import prepared as prepared
from test_workspace_dialog import app as app
from test_workspace_dialog import wait

from paper_daily import sync_device_recovery
from paper_daily.desktop.workspace_dialog import WorkspaceDialog


@pytest.fixture
def view(prepared, app):
    dialog = WorkspaceDialog(prepared[0].journal.path, language="en")
    dialog.show()
    wait(app, lambda: dialog._ready and not dialog.busy)
    dialog.task_tabs.setCurrentIndex(2)
    app.processEvents()
    yield dialog
    if dialog.busy:
        dialog.cancel()
        wait(app, lambda: not dialog.busy)
    dialog.close()


def test_visible_point_in_time_counts_and_cancelled_picker_do_not_mutate(
    view, app, prepared, monkeypatch
):
    panel = view.device_review
    assert not panel.content.isVisible() and panel.button.isEnabled()
    panel.disclosure.click()
    assert panel.content.isVisible() and panel.disclosure.isChecked()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: "")
    assert not panel.choose() and not view.busy
    before = prepared[0].journal.path.read_bytes()
    assert panel.inspect(prepared[3])
    assert not panel.inspect(prepared[3])
    wait(app, lambda: not view.busy)
    assert "Local operations already in backup: 1" in panel.label.text()
    assert "not a full research/file audit" in panel.label.text()
    assert "Point-in-time" in panel.label.text()
    assert prepared[0].journal.path.read_bytes() == before
    assert panel.button.isEnabled()


def test_failure_keeps_research_and_allows_explicit_retry(view, app, prepared, tmp_path):
    assert view.device_review.inspect(tmp_path / "missing")
    wait(app, lambda: not view.busy)
    assert view.status.text() == view.t["failure"]
    assert "Local operations already" not in view.device_review.label.text()
    assert view.device_review.inspect(prepared[3])
    wait(app, lambda: not view.busy)
    assert "review finished" in view.status.text()


@pytest.mark.parametrize("action", ["cancel", "close", "switch", "rebind"])
def test_held_worker_cannot_publish_after_lifetime_or_binding_changes(
    view, app, prepared, monkeypatch, tmp_path, action
):
    entered, release = Event(), Event()
    original = sync_device_recovery.review

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(sync_device_recovery, "review", held)
    assert view.device_review.inspect(prepared[3])
    assert entered.wait(3)
    assert not view.device_review.inspect(prepared[3])
    try:
        if action == "cancel":
            view.cancel()
        elif action == "close":
            assert not view.close()
        elif action == "switch":
            view.service.current_path = lambda: tmp_path / "other.sqlite"
        else:
            with closing(sqlite3.connect(prepared[0].journal.path)) as conn, conn:
                conn.execute("UPDATE paperfact_sync_identity SET workspace='different'")
    finally:
        release.set()
    wait(app, lambda: not view.busy)
    assert "Local operations already" not in view.device_review.label.text()
    if action == "close":
        assert view.disposed
    elif action == "cancel":
        assert view.status.text() == view.t["cancelled"]
    else:
        assert view._invalid or view.status.text() == view.t["failure"]


def test_same_file_binding_change_at_delivery_is_rechecked(view, app, prepared, monkeypatch):
    deliveries = []
    original = view._finished

    def observe(worker, kind):
        deliveries.append(QThread.currentThread() == app.thread())
        return original(worker, kind)

    monkeypatch.setattr(view, "_finished", observe)
    assert view.device_review.inspect(prepared[3])
    worker = view._worker
    assert worker.wait(6000)
    assert not deliveries, f"Delivery ran before GUI events; GUI thread flags: {deliveries}"
    # The worker has finished; its queued GUI delivery has not run yet.
    with closing(sqlite3.connect(prepared[0].journal.path)) as conn, conn:
        conn.execute("UPDATE paperfact_sync_identity SET workspace='changed-at-delivery'")
    wait(app, lambda: not view.busy)
    assert deliveries == [True]
    assert view._invalid and view.status.text() == view.t["changed"]
    assert "Local operations already" not in view.device_review.label.text()


def test_chinese_labels_are_utf8_and_unenrolled_workspace_action_is_disabled(app, tmp_path):
    database = tmp_path / "local.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("CREATE TABLE local_data(value TEXT)")
    dialog = WorkspaceDialog(database, language="zh-TW")
    try:
        dialog.show()
        wait(app, lambda: dialog._ready and not dialog.busy)
        assert dialog.device_review.disclosure.text() == "同步服務備份比對（進階）"
        assert "不是研究清單 ZIP" in dialog.device_review.label.text()
        assert not dialog.device_review.button.isEnabled()
    finally:
        dialog.close()
