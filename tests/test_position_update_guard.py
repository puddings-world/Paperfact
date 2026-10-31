"""A real native position save must drain before restart state or installer launch."""

import json
from threading import Event

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_reading_position_controller import idle, until
from test_reading_positions import pdf_bytes, records, view
from test_window_fits import reader as window_fixture

from paper_daily import reading_position_ops as operations
from paper_daily import reading_positions as positions
from paper_daily import store, updates

window_reader = window_fixture


@pytest.fixture
def native_reader(window_reader):
    window, app = window_reader
    reader = window.reader_page
    database = store.DB_PATH
    path = database.parent / "original.pdf"
    path.write_bytes(pdf_bytes())
    reader._active_document = None
    reader._highlight_view = view(database, path, paper="p")
    reader._pdf_fingerprint = reader._highlight_view.fingerprint
    assert reader.pdf.load(path)
    reader.pdf.show()
    app.processEvents()
    controller = reader.reading_positions
    controller.bind()
    idle(app, controller)
    until(app, lambda: not reader.preparation.busy)
    assert controller.view is not None
    controller.poll.stop()
    reader.ask_box.setText("Unsent question: preserve exactly")
    reader.note_edit.setPlainText("Unfinished note: preserve exactly")
    yield window, app, reader, controller, database


def drafts(reader):
    return reader.ask_box.text(), reader.note_edit.toPlainText()


def restart_state():
    with store.connect() as connection:
        return store.get_kv(connection, "ui.restart")


@pytest.mark.parametrize("action", ["restart", "update", "verified_banner"])
def test_native_save_blocks_restart_and_real_verified_banner_until_drained(
    native_reader, monkeypatch, tmp_path, action
):
    window, app, reader, controller, database = native_reader
    entered, release = Event(), Event()
    original = operations.prepare
    calls, launches, quit_requests, saves, remembered = [], [], [], [], []
    expected_drafts = drafts(reader)
    before_restart = restart_state()
    before_rows = records(database, positions.TABLE)

    def held(*args, **kwargs):
        calls.append(kwargs.get("method"))
        entered.set()
        assert release.wait(20), "fixture position save was not released"
        return original(*args, **kwargs)

    pane = reader.presentation_pane
    original_save, original_remember = pane.save_changes, window.remember

    def save():
        saves.append(True)
        return original_save()

    def remember(key, value):
        remembered.append(key)
        return original_remember(key, value)

    monkeypatch.setattr(operations, "prepare", held)
    monkeypatch.setattr(pane, "save_changes", save)
    monkeypatch.setattr(window, "remember", remember)
    monkeypatch.setattr(updates, "launch_installer", launches.append)
    banner = window.update_banner
    ready = tmp_path / "verified-fixture-installer.exe"
    ready.write_bytes(b"synthetic installer; never executed")
    banner._ready = ready
    banner.quit_for_update.connect(lambda: quit_requests.append(True))

    def activate():
        if action == "verified_banner":
            banner._verified()
            return None
        return window._prepare_restart() if action == "restart" else window._prepare_update()

    try:
        # Native keyboard input, observer debounce and the real QThread save path.
        controller.observer.bar.setFocus()
        QTest.keyClick(controller.observer.bar, Qt.Key.Key_End)
        until(app, entered.is_set)
        assert reader.pdf.current_page() + 1 > 1
        worker = controller._thread
        assert worker is not None and worker.isRunning()
        for _ in range(8):
            result = activate()
            if action != "verified_banner":
                assert result is False
            assert launches == [], "Installer must not start before the position save drains"
            assert quit_requests == []
            assert saves == [] and "restart" not in remembered
            assert restart_state() == before_restart
            assert drafts(reader) == expected_drafts
            assert window.isVisible() and not window.workspace_changes.disposed
            assert controller._thread is worker and not worker.cancelled.is_set()
        assert calls == ["observed"]
        assert records(database, positions.TABLE) == before_rows
        if action == "verified_banner":
            assert banner.install.isEnabled() and banner.later.isEnabled()
            assert "背景工作" in banner.label.text()
            assert not banner._installing and banner._ready == ready
    finally:
        release.set()
        idle(app, controller)

    (row,) = records(database, positions.TABLE)
    assert row[2] == reader.pdf.current_page() + 1 and row[4] == "observed"
    assert len(records(database, positions.RECEIPTS)) == 1
    assert drafts(reader) == expected_drafts
    assert calls == ["observed"]
    assert window.isVisible()  # Completion does not retry restart/install by itself.
    assert launches == [] and restart_state() == before_restart

    result = activate()
    if action == "verified_banner":
        assert launches == [ready] and quit_requests == [True]
        assert not window.isVisible()
        for _ in range(8):
            banner._verified()
        assert launches == [ready] and quit_requests == [True]
    else:
        assert result is True
        assert launches == [] and window.isVisible()
    state = json.loads(restart_state())
    assert (state["question"], state["note"]) == expected_drafts
    assert drafts(reader) == expected_drafts
    assert len(records(database, positions.TABLE)) == 1
    assert len(records(database, positions.RECEIPTS)) == 1


def test_idle_installer_failure_preserves_drafts_and_can_retry_once(
    native_reader, monkeypatch, tmp_path
):
    window, _app, reader, controller, database = native_reader
    expected = drafts(reader)
    attempts, quit_requests = [], []

    def installer(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise OSError("fixture installer unavailable")

    monkeypatch.setattr(updates, "launch_installer", installer)
    banner = window.update_banner
    banner.quit_for_update.connect(lambda: quit_requests.append(True))
    ready = tmp_path / "synthetic-installer.exe"
    banner._ready = ready
    banner._verified()
    assert attempts == [ready] and quit_requests == []
    assert window.isVisible() and not banner._installing
    assert banner.install.isEnabled() and "更新沒有完成" in banner.label.text()
    assert drafts(reader) == expected
    assert not window._closing_with_recovery and not controller._disposed
    assert records(database, positions.TABLE) == []
    banner._ready = ready  # Represents an explicit successful re-download/verification.
    banner._verified()
    banner._verified()
    assert attempts == [ready, ready] and quit_requests == [True]
    assert not window.isVisible() and drafts(reader) == expected
    state = json.loads(restart_state())
    assert (state["question"], state["note"]) == expected
