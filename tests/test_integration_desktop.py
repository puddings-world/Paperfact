import json
import os
import threading
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paper_daily import local_operations as ops
from paper_daily import store
from paper_daily.desktop.integration_dialog import IntegrationDialog
from paper_daily.desktop.workspace_changes import WorkspaceChanges

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    return app


def settle(app, dialog):
    deadline = time.monotonic() + 5
    while dialog._worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert dialog._worker is None
    app.processEvents()


def fill(dialog):
    dialog.input.setPlainText(
        json.dumps(
            {
                "name": "UI List",
                "papers": [{"title": "One", "doi": "10.1234/one"}, {"title": "Two"}],
            }
        )
    )
    dialog.propose()


def test_preview_selection_and_repeated_commit_save_once(workspace):
    dialog = IntegrationDialog()
    fill(dialog)
    settle(workspace, dialog)
    assert dialog.items.count() == 2 and ops.list_collections()["total"] == 0
    dialog.items.item(1).setCheckState(Qt.CheckState.Unchecked)
    for _ in range(20):
        dialog.commit()
    settle(workspace, dialog)
    assert dialog.saved["added"] == 1
    assert ops.read_collection(dialog.saved["list_id"])["papers"][0]["title"] == "One"
    assert "已儲存 1 篇" in dialog.status.text()
    assert not dialog.save_button.isEnabled() and not dialog.input.isEnabled()
    dialog.commit()
    assert ops.list_collections()["total"] == 1
    dialog.reject()


def test_empty_selection_failure_retry_and_cancel(workspace):
    dialog = IntegrationDialog()
    dialog.input.setPlainText("broken")
    dialog.propose()
    assert "JSON" in dialog.status.text() and not dialog.save_button.isEnabled()
    fill(dialog)
    settle(workspace, dialog)
    for i in range(dialog.items.count()):
        dialog.items.item(i).setCheckState(Qt.CheckState.Unchecked)
    dialog.commit()
    settle(workspace, dialog)
    assert not dialog.saved and ops.list_collections()["total"] == 0
    assert dialog.save_button.isEnabled()
    dialog.items.item(0).setCheckState(Qt.CheckState.Checked)
    dialog.commit()
    settle(workspace, dialog)
    assert dialog.saved["added"] == 1
    dialog.reject()
    other = IntegrationDialog()
    fill(other)
    settle(workspace, other)
    preview_id = other.preview_id
    other.reject()
    assert not ops.dispatch(
        "imports.commit", dict(preview_id=preview_id, operation_id="cancelled", selected=["0"])
    )["ok"]
    assert ops.list_collections()["total"] == 1


def test_edit_invalidates_preview_and_config_contains_no_credentials(workspace):
    dialog = IntegrationDialog()
    config = json.loads(dialog.config.toPlainText())["mcpServers"]["paperfact"]
    assert set(config) == {"command", "args"}
    assert "mcp" in config["args"] and "--workspace" in config["args"]
    fill(dialog)
    settle(workspace, dialog)
    dialog.input.setPlainText('{"name":"Changed","papers":[{"title":"Changed"}]}')
    assert not dialog.save_button.isEnabled() and dialog.preview_id is None
    dialog.commit()
    assert ops.list_collections()["total"] == 0
    dialog.reject()


def test_pending_worker_blocks_repeated_activation_and_close(workspace, monkeypatch):
    from paper_daily.desktop import integration_dialog

    entered, release = threading.Event(), threading.Event()
    real = integration_dialog.dispatch
    calls = []

    def slow(operation, args):
        if operation == "imports.propose":
            calls.append(operation)
            entered.set()
            release.wait(3)
        return real(operation, args)

    monkeypatch.setattr(integration_dialog, "dispatch", slow)
    dialog = IntegrationDialog()
    dialog.show()
    fill(dialog)
    try:
        assert entered.wait(2)
        for _ in range(10):
            dialog.propose()
            dialog.commit()
        dialog.close()
        assert dialog.isVisible() and not dialog.input.isEnabled()
        assert "完成" in dialog.status.text()
    finally:
        release.set()
        settle(workspace, dialog)
    assert calls == ["imports.propose"]
    dialog.reject()
    assert not dialog.isVisible() and ops.list_collections()["total"] == 0


def test_watcher_emits_once_only_after_commit_and_tolerates_unavailable_db(workspace, monkeypatch):
    watcher = WorkspaceChanges()
    notifications = []
    watcher.changed.connect(lambda: notifications.append(True))
    staged = ops.propose("New", [{"title": "One"}])
    watcher.poll()
    assert not notifications
    ops.commit(staged["preview_id"], "watch", ["0"])
    watcher.poll()
    watcher.poll()
    assert notifications == [True]
    original = store.DB_PATH
    monkeypatch.setattr(store, "DB_PATH", original.with_name("missing.db"))
    watcher.poll()
    assert not store.DB_PATH.exists()
    monkeypatch.setattr(store, "DB_PATH", original)
    watcher.poll()
    assert notifications == [True]
    watcher.timer.stop()


def test_external_refresh_preserves_overview_selection_and_reader_draft(workspace, monkeypatch):
    from paper_daily.desktop.main import MainWindow

    first = ops.commit(ops.propose("First", [{"title": "A"}])["preview_id"], "a", ["0"])
    second = ops.commit(ops.propose("Second", [{"title": "B"}])["preview_id"], "b", ["0"])
    window = MainWindow()
    monkeypatch.setattr(window, "top_up_dives", lambda: None)
    window.active_list = first["list_id"]
    window.refresh_lists()
    window.show_lists()
    view = window.lists_page.view
    for i in range(view.count()):
        if view.item(i).data(Qt.ItemDataRole.UserRole) == second["list_id"]:
            view.setCurrentRow(i)
    window.queue_page.search.setText("keep my filter")
    ops.commit(ops.propose("Third", [{"title": "C"}])["preview_id"], "c", ["0"])
    window._poll_external_lists()
    assert view.count() == 3
    assert view.currentItem().data(Qt.ItemDataRole.UserRole) == second["list_id"]
    assert window.active_list == first["list_id"]
    assert window.queue_page.search.text() == "keep my filter"
    window.stack.setCurrentWidget(window.reader_page)
    window.reader_page.note_edit.setPlainText("Unsaved explanation")
    window.reader_page.ask_box.setText("Question in progress")
    window._external_lists_changed()
    assert window.stack.currentWidget() is window.reader_page
    assert window.reader_page.note_edit.toPlainText() == "Unsaved explanation"
    assert window.reader_page.ask_box.text() == "Question in progress"
    window.close()
    window.deleteLater()


def test_parent_window_cannot_close_while_import_worker_is_active(workspace, monkeypatch):
    from PySide6.QtGui import QCloseEvent

    from paper_daily.desktop import integration_dialog
    from paper_daily.desktop.main import MainWindow

    release = threading.Event()
    entered = threading.Event()
    real = integration_dialog.dispatch

    def held(operation, arguments):
        entered.set()
        release.wait(3)
        return real(operation, arguments)

    monkeypatch.setattr(integration_dialog, "dispatch", held)
    window = MainWindow()
    dialog = IntegrationDialog(window)
    fill(dialog)
    try:
        assert entered.wait(2)
        event = QCloseEvent()
        window.closeEvent(event)
        assert not event.isAccepted()
    finally:
        release.set()
        settle(workspace, dialog)
    dialog.reject()
    window.close()
    window.deleteLater()


def test_background_watch_reports_a_commit_without_reading_on_the_gui_thread(
    workspace, monkeypatch
):
    watcher = WorkspaceChanges()
    watcher.timer.stop()
    notifications, readers = [], []
    original = watcher._revision

    def revision():
        readers.append(threading.current_thread() is threading.main_thread())
        return original()

    monkeypatch.setattr(watcher, "_revision", revision)
    watcher.changed.connect(lambda: notifications.append(True))
    staged = ops.propose("New", [{"title": "One"}])
    ops.commit(staged["preview_id"], "watch", ["0"])
    watcher.poll_in_background()
    watcher.poll_in_background()  # still reading: not started twice
    deadline = time.monotonic() + 5
    while not notifications and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert notifications == [True] and readers == [False]


def test_the_window_polls_for_list_changes_off_the_gui_thread(workspace, monkeypatch):
    from paper_daily.desktop.main import MainWindow

    window = MainWindow()
    try:
        watcher = window.workspace_changes
        calls = []
        monkeypatch.setattr(watcher, "poll", lambda: calls.append("gui"))
        monkeypatch.setattr(watcher, "poll_in_background", lambda: calls.append("background"))
        watcher.timer.timeout.emit()
        assert calls == ["background"]
    finally:
        window.close()
        window.deleteLater()
