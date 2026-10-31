"""Real ReaderPage/MainWindow hooks preserve the watcher, drafts and close lifetime."""

from threading import Event

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_manual_highlight_ui import loaded as managed_loaded_fixture
from test_manual_highlight_ui import workspace as research_workspace_fixture
from test_reading_position_controller import idle, until
from test_reading_positions import pdf_bytes, records, view
from test_window_fits import reader as window_reader_fixture

from paper_daily import reading_position_ops as operations
from paper_daily import reading_positions as positions
from paper_daily import store

managed_loaded = managed_loaded_fixture
window_reader = window_reader_fixture
research_workspace = research_workspace_fixture


@pytest.fixture
def workspace(research_workspace):
    # The maintained research fixture deliberately starts from bare store.SCHEMA.
    # The new optional capability is installed explicitly, before ReaderPage.load;
    # passive verification must never repair that fixture's schema itself.
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if not positions.ready(connection):
            positions.initialize(connection)
    return research_workspace


def test_actual_reader_load_activates_remember_after_verification_without_AI(managed_loaded):
    loaded = managed_loaded
    reader = loaded.widget
    controller = reader.reading_positions
    until(loaded.app, lambda: controller.view is not None and not controller.busy)
    assert controller.view is not None and controller.suggestion is None
    assert records(loaded.database, positions.TABLE) == []
    reader.ask_box.setText("preserve this question")
    reader.note_edit.setPlainText("preserve this note")
    QTest.mouseClick(controller.remember_button, Qt.MouseButton.LeftButton)
    idle(loaded.app, controller)
    (row,) = records(loaded.database, positions.TABLE)
    assert row[:3] == ("paper", loaded.document.sha256, 1)
    assert row[4] == "entered"
    assert reader.ask_box.text() == "preserve this question"
    assert reader.note_edit.toPlainText() == "preserve this note"


def test_real_window_rejected_close_cancels_position_worker_without_disposing_watcher(
    window_reader, monkeypatch
):
    window, app = window_reader
    reader = window.reader_page
    database = store.DB_PATH
    path = database.parent / "actual.pdf"
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
    assert controller.view is not None
    entered, release = Event(), Event()
    original = operations.prepare

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(20)
        return original(*args, **kwargs)

    monkeypatch.setattr(operations, "prepare", held)
    try:
        assert controller.remember()
        until(app, entered.is_set)
        window.close()
        assert window.isVisible()
        assert not window.workspace_changes.disposed
        assert window.workspace_changes.timer.isActive()
    finally:
        release.set()
        idle(app, controller)
    assert window.isVisible()  # No completion-driven retry of close.
    assert records(database, positions.TABLE) == []
    window.close()
    assert window.workspace_changes.disposed
    assert controller._disposed and not controller.poll.isActive()


@pytest.mark.parametrize("legacy", ["missing", "none"])
def test_legacy_reader_without_optional_position_controller_still_closes(window_reader, legacy):
    window, app = window_reader
    reader = window.reader_page
    # Legacy adapters have no active position capability. Stop the real fixture
    # controller before exposing that older interface; do not hide a running job.
    reader.reading_positions.close()
    if legacy == "missing":
        del reader.reading_positions
    else:
        reader.reading_positions = None
    window.close()
    app.processEvents()
    assert not window.isVisible()
    assert window.workspace_changes.disposed
