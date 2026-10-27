import sqlite3
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
from test_reader_chat import reader as reader_fixture
from test_research_chat import legacy as legacy_fixture
from test_sync_recovery import research as research_fixture

from paper_daily import sync_recovery
from paper_daily.desktop.workspace_dialog import WorkspaceDialog

reader = reader_fixture
legacy = legacy_fixture


research = research_fixture


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def wait(app, condition, timeout=8):
    end = time.monotonic() + timeout
    while not condition():
        app.processEvents()
        if time.monotonic() >= end:
            raise AssertionError("Fixture worker did not finish")
        time.sleep(0.005)
    app.processEvents()


@pytest.fixture
def dialog(app, research):
    view = WorkspaceDialog(research[0], language="en")
    view.show()
    wait(app, lambda: view._ready and not view.busy)
    yield view
    if view.busy:
        view.cancel()
        wait(app, lambda: not view.busy)
    view.close()


def test_visible_status_location_and_no_fake_sync(dialog, research):
    assert dialog.location.text() == str(research[0].parent)
    assert "pending:" in dialog.summary.text()
    assert "not currently verified" in dialog.summary.text()
    assert dialog.backup_button.isEnabled()
    assert not dialog.restore_button.isEnabled()
    assert "Not available yet" in "\n".join(
        label.text() for label in dialog.findChildren(type(dialog.summary))
    )
    assert "Up to date" not in dialog.summary.text()


def test_actual_backup_preview_restore_buttons_preserve_research(
    dialog, app, tmp_path, monkeypatch
):
    package, destination = tmp_path / "backup.zip", tmp_path / "restored"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(package), ""))
    dialog.backup_button.click()
    wait(app, lambda: not dialog.busy)
    assert package.is_file() and "Complete backup created" in dialog.status.text()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(package), ""))
    dialog.inspect_button.click()
    wait(app, lambda: not dialog.busy)
    assert dialog.restore_button.isEnabled() and "Verified" in dialog.preview_label.text()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (destination.name, True))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog.restore_button.click()
    wait(app, lambda: not dialog.busy)
    assert "active workspace unchanged" in dialog.status.text()
    with sqlite3.connect(destination / "papers.db") as conn:
        assert conn.execute("SELECT body FROM notes").fetchall() == [("Saved research",)]
    assert dialog.service.path.is_file()


def test_cancelled_file_choosers_do_not_create_jobs(dialog, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    before = dialog.status.text()
    dialog.backup_button.click()
    dialog.inspect_button.click()
    assert not dialog.busy and dialog.status.text() == before


def test_duplicate_activation_and_close_wait_for_safe_cancel(dialog, app, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = sync_recovery.create
    calls = []

    def held(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(sync_recovery, "create", held)
    destination = tmp_path / "cancelled.zip"
    assert dialog.start_backup(destination)
    wait(app, entered.is_set)
    assert not dialog.start_backup(destination)
    assert not dialog.refresh()
    assert not dialog.close() and dialog.busy
    assert "Cancellation requested" in dialog.status.text()
    release.set()
    wait(app, lambda: dialog.disposed)
    assert calls == [1] and not destination.exists()
    assert dialog.service.path.exists()


def test_failure_retry_retains_destination_selection_and_no_raw_error(
    dialog, app, tmp_path, monkeypatch
):
    original = sync_recovery.create
    monkeypatch.setattr(
        sync_recovery,
        "create",
        lambda *a, **k: (_ for _ in ()).throw(OSError("fixture-secret-body")),
    )
    destination = tmp_path / "retry.zip"
    dialog.start_backup(destination)
    wait(app, lambda: not dialog.busy)
    assert not destination.exists()
    assert "fixture-secret" not in dialog.status.text()
    assert dialog.backup_button.isEnabled()
    monkeypatch.setattr(sync_recovery, "create", original)
    dialog.start_backup(destination)
    wait(app, lambda: not dialog.busy)
    assert destination.exists()


def test_workspace_change_drops_late_result(dialog, app, tmp_path, monkeypatch):
    active = [dialog.service.path]
    dialog.service.current_path = lambda: active[0]
    entered, release = threading.Event(), threading.Event()
    original = sync_recovery.create

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(sync_recovery, "create", held)
    target = tmp_path / "wrong.zip"
    dialog.start_backup(target)
    wait(app, entered.is_set)
    active[0] = tmp_path / "another.db"
    dialog._check_workspace()
    release.set()
    wait(app, lambda: not dialog.busy)
    assert not target.exists() and "Workspace changed" in dialog.status.text()
    assert not dialog.backup_button.isEnabled()
    assert not (tmp_path / "another.db").exists()


def test_busy_research_blocks_backup_without_starting_worker(dialog, tmp_path):
    dialog.writers_busy = lambda: True
    assert not dialog.start_backup(tmp_path / "busy.zip")
    assert not dialog.busy and "background research" in dialog.status.text()


def test_corrupt_preview_clears_prior_restore_capability(dialog, app, tmp_path):
    package = tmp_path / "backup.zip"
    dialog.start_backup(package)
    wait(app, lambda: not dialog.busy)
    dialog.inspect_package(package)
    wait(app, lambda: not dialog.busy)
    assert dialog.preview
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a research backup")
    dialog.inspect_package(broken)
    wait(app, lambda: not dialog.busy)
    assert dialog.preview is None and not dialog.restore_button.isEnabled()


def test_open_folder_is_explicit_and_uses_captured_workspace(dialog, monkeypatch):
    from PySide6.QtGui import QDesktopServices

    calls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: calls.append(url.toLocalFile()))
    assert calls == []
    dialog.folder_button.click()
    assert len(calls) == 1 and Path(calls[0]) == dialog.service.path.parent


def test_main_menu_is_real_entry_reuses_dialog_and_blocks_auto_analysis(reader, monkeypatch):
    app, window, _ = reader
    window.workspace_action.trigger()
    dialog = window._workspace_dialog
    wait(app, lambda: dialog._ready and not dialog.busy)
    window.workspace_action.trigger()
    assert window._workspace_dialog is dialog
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *a, **k: pytest.fail("analysis started during workspace settings"),
    )
    window._spawn_job(["analyze", "local-paper"], "local-paper")
    assert dialog.service.path.exists()
    dialog.close()


def test_preview_restore_confirmation_cancel_preserves_source(dialog, app, tmp_path, monkeypatch):
    package = tmp_path / "backup.zip"
    dialog.start_backup(package)
    wait(app, lambda: not dialog.busy)
    dialog.inspect_package(package)
    wait(app, lambda: not dialog.busy)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("restored", True))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    dialog.restore_button.click()
    assert not dialog.busy and not (tmp_path / "restored").exists()


def test_main_close_waits_for_backup_worker_and_no_destination_on_cancel(
    reader, tmp_path, monkeypatch
):
    app, window, _ = reader
    window.workspace_action.trigger()
    dialog = window._workspace_dialog
    wait(app, lambda: dialog._ready and not dialog.busy)
    entered, release = threading.Event(), threading.Event()
    original = sync_recovery.create

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(sync_recovery, "create", held)
    dialog.writers_busy = lambda: False
    output = tmp_path.parent / (tmp_path.name + "-not-published.zip")
    dialog.start_backup(output)
    wait(app, entered.is_set)
    try:
        assert not window.close()
        assert dialog.busy and dialog._closing
    finally:
        release.set()
    wait(app, lambda: dialog.disposed)
    assert not output.exists()


def test_small_window_keeps_cancel_and_reading_actions_reachable(dialog, app):
    dialog.resize(440, 400)
    app.processEvents()
    assert dialog.scroll.verticalScrollBar().maximum() > 0
    assert dialog.scroll.horizontalScrollBar().maximum() == 0
    assert dialog.rect().contains(dialog.close_button.geometry())
    assert dialog.rect().contains(dialog.cancel_button.geometry())
