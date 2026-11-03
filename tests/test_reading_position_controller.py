"""Actual native page input, bounded workers and explicit source-checked resume."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QPlainTextEdit,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)
from test_reading_position_packages import workspace
from test_reading_positions import pdf_bytes, prepared, records, view

from paper_daily import reading_position_ops as operations
from paper_daily import reading_positions as positions
from paper_daily import source_snapshots, store
from paper_daily.desktop import pdfpane
from paper_daily.desktop.flow_layout import FlowLayout
from paper_daily.desktop.reading_position_controller import ReadingPositionController, message


def until(app, predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "fixture worker did not become idle"
        app.processEvents()
        QTest.qWait(5)
    app.processEvents()


def idle(app, controller):
    until(app, lambda: not controller.busy and not controller.timer.isActive())


@pytest.fixture(params=["pixmap", "qt"] if pdfpane.HAVE_QTPDF else ["pixmap"])
def reader(request, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    database = workspace(tmp_path / "workspace", monkeypatch, existing=True)
    path = database.parent / "pdf/local-paper.pdf"
    path.write_bytes(pdf_bytes())
    native = view(database, path)
    widget = QWidget()
    layout = QVBoxLayout(widget)
    controls = QWidget()
    bar = FlowLayout()
    controls.setLayout(bar)
    layout.addWidget(controls)
    widget.pdf = pdfpane._QtPdfPane() if request.param == "qt" else pdfpane._PixmapPdfPane()
    layout.addWidget(widget.pdf, 1)
    widget.ask_box, widget.note_edit = QLineEdit(), QPlainTextEdit()
    layout.addWidget(widget.ask_box)
    layout.addWidget(widget.note_edit)
    widget.note_edit.setMaximumHeight(80)
    widget.paper = SimpleNamespace(id="local-paper")
    widget._highlight_view = native
    widget._active_document = None
    widget._pdf_fingerprint, widget._qa_epoch = native.fingerprint, 0
    assert widget.pdf.load(path)
    controller = ReadingPositionController(widget, bar, locale="en", debounce_ms=40)
    widget.resize(760, 780)
    widget.show()
    app.processEvents()
    assert controller.bind()
    idle(app, controller)
    assert controller.view is not None, controller.status.text()
    gates = []
    yield app, widget, controller, database, path, gates
    for event in gates:
        event.set()
    controller.cancel()
    idle(app, controller)
    controller.close()
    widget.pdf.unload()
    widget.close()
    widget.deleteLater()
    app.processEvents()


def gate(monkeypatch, reader, name):
    app, _widget, _controller, _db, _path, gates = reader
    entered, release = Event(), Event()
    gates.append(release)
    original = getattr(operations, name)

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(20), "fixture release was not sent"
        return original(*args, **kwargs)

    monkeypatch.setattr(operations, name, blocked)
    return entered, release


def keyboard_end(app, widget, controller):
    controller.observer.bar.setFocus()
    QTest.keyClick(controller.observer.bar, Qt.Key.Key_End)
    app.processEvents()
    assert widget.pdf.current_page() + 1 > 1


def wheel_target(app, widget):
    viewport = getattr(widget.pdf, "_view", widget.pdf).viewport()
    widget.activateWindow()
    viewport.setFocus()
    QTest.mouseMove(viewport, viewport.rect().center())
    app.processEvents()
    return viewport.mapTo(widget, viewport.rect().center())


def test_load_render_resize_programmatic_navigation_and_checks_never_save(reader):
    app, widget, controller, database, _path, _gates = reader
    assert "No recorded page" in controller.status.text()
    widget.resize(600, 700)
    assert widget.pdf.go_to_position(4)
    app.processEvents()
    controller.check()
    idle(app, controller)
    assert records(database, positions.TABLE) == []
    assert records(database, positions.RECEIPTS) == []
    assert source_snapshots.list_owned(database) == []


def test_genuine_navigation_debounces_latest_page_and_same_page_input_is_not_new_data(reader):
    app, widget, controller, database, _path, _gates = reader
    keyboard_end(app, widget, controller)
    QTest.keyClick(controller.observer.bar, Qt.Key.Key_Home)
    app.processEvents()
    QTest.keyClick(controller.observer.bar, Qt.Key.Key_End)
    app.processEvents()
    idle(app, controller)
    (row,) = records(database, positions.TABLE)
    assert row[2:] == (widget.pdf.current_page() + 1, row[3], "observed")
    assert len(records(database, positions.RECEIPTS)) == 1
    QTest.keyClick(controller.observer.bar, Qt.Key.Key_End)
    app.processEvents()
    idle(app, controller)
    assert len(records(database, positions.RECEIPTS)) == 1


@pytest.mark.parametrize("input_kind", ["End", "wheel"])
def test_programmatic_jump_then_unchanged_native_input_never_records_progress(reader, input_kind):
    app, widget, controller, database, _path, _gates = reader
    assert widget.pdf.go_to_position(4)
    app.processEvents()
    before = widget.pdf.current_page()
    if input_kind == "End":
        controller.observer.bar.setFocus()
        QTest.keyClick(controller.observer.bar, Qt.Key.Key_End)
    else:
        point = wheel_target(app, widget)
        pixel_before = controller.observer.bar.value()
        QTest.wheelEvent(widget.windowHandle(), point, QPoint(0, -120))
    app.processEvents()
    assert widget.pdf.current_page() == before == 3
    if input_kind == "wheel":
        assert controller.observer.bar.value() > pixel_before  # Real input, same PDF page.
    idle(app, controller)
    assert records(database, positions.TABLE) == []
    assert records(database, positions.RECEIPTS) == []
    assert "No recorded page" in controller.status.text()


def test_real_native_wheel_page_change_records_only_its_actual_result(reader):
    app, widget, controller, database, _path, _gates = reader
    point = wheel_target(app, widget)
    before = widget.pdf.current_page()
    # Send normal hardware notches; Qt intentionally caps a single large angle.
    for _ in range(32):
        QTest.wheelEvent(widget.windowHandle(), point, QPoint(0, -120))
        app.processEvents()
    after = widget.pdf.current_page()
    assert after != before
    idle(app, controller)
    (row,) = records(database, positions.TABLE)
    assert row[2] == after + 1 and row[4] == "observed"
    assert f"Recorded page {after + 1}" in controller.status.text()


def test_real_scrollbar_drag_records_press_to_release_page_change(reader):
    app, widget, controller, database, _path, _gates = reader
    widget.activateWindow()
    bar = controller.observer.bar
    option = QStyleOptionSlider()
    option.initFrom(bar)
    option.orientation = Qt.Orientation.Vertical
    option.minimum, option.maximum = bar.minimum(), bar.maximum()
    option.sliderPosition, option.sliderValue = bar.value(), bar.value()
    option.pageStep, option.singleStep = bar.pageStep(), bar.singleStep()
    thumb = bar.style().subControlRect(
        QStyle.ComplexControl.CC_ScrollBar,
        option,
        QStyle.SubControl.SC_ScrollBarSlider,
        bar,
    )
    before = widget.pdf.current_page()
    end = QPoint(thumb.center().x(), bar.height() - 35)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=thumb.center())
    assert not controller.check()  # A periodic read cannot replace this input's captured base.
    QTest.mouseMove(bar, end)
    app.processEvents()
    assert widget.pdf.current_page() != before
    assert records(database, positions.TABLE) == []  # No guessed progress before release.
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=end)
    app.processEvents()
    idle(app, controller)
    (row,) = records(database, positions.TABLE)
    assert row[2] == widget.pdf.current_page() + 1 and row[4] == "observed"


def test_scrollbar_release_from_prior_epoch_cannot_create_position(reader):
    app, widget, controller, database, _path, _gates = reader
    bar = controller.observer.bar
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(bar.width() // 2, 20))
    controller.invalidate()
    widget._qa_epoch += 1
    QTest.mouseRelease(
        bar, Qt.MouseButton.LeftButton, pos=QPoint(bar.width() // 2, bar.height() - 35)
    )
    app.processEvents()
    idle(app, controller)
    assert records(database, positions.TABLE) == []


def test_remember_is_keyboard_reachable_and_duplicate_clicks_never_start_second_job(
    reader, monkeypatch
):
    app, widget, controller, database, _path, _gates = reader
    widget.pdf.go_to_position(3)
    entered, release = gate(monkeypatch, reader, "prepare")
    controller.remember_button.setFocus()
    QTest.keyClick(controller.remember_button, Qt.Key.Key_Space)
    until(app, entered.is_set)
    for _ in range(15):
        QTest.mouseClick(controller.remember_button, Qt.MouseButton.LeftButton)
        assert not controller.remember()
    assert not controller.remember_button.isEnabled()
    release.set()
    idle(app, controller)
    (row,) = records(database, positions.TABLE)
    assert row[2] == 3 and row[4] == "entered"
    assert len(records(database, positions.RECEIPTS)) == 1
    assert not controller.remember()
    assert len(records(database, positions.RECEIPTS)) == 1


@pytest.mark.parametrize("change", ["cancel", "close", "paper", "workspace", "source", "parent"])
def test_pending_remember_cannot_publish_in_replacement_context(
    reader, monkeypatch, tmp_path, change
):
    app, widget, controller, database, path, _gates = reader
    entered, release = gate(monkeypatch, reader, "prepare")
    assert controller.remember()
    until(app, entered.is_set)
    if change == "cancel":
        controller.cancel()
    elif change == "close":
        assert not controller.request_close()
    elif change == "paper":
        controller.invalidate()
        widget.paper = SimpleNamespace(id="another-paper")
        widget._qa_epoch += 1
    elif change == "workspace":
        monkeypatch.setattr(store, "DB_PATH", tmp_path / "another.sqlite")
    elif change == "source":
        path.write_bytes(pdf_bytes(2, "B"))
    else:
        with store.connect() as conn:
            conn.execute("DELETE FROM papers WHERE id='local-paper'")
    release.set()
    idle(app, controller)
    assert records(database, positions.TABLE) == []
    assert records(database, positions.RECEIPTS) == []
    if change == "close":
        assert widget.isVisible()  # Completion never retries close automatically.
        assert controller.request_close()


def test_failed_save_retry_preserves_drafts_and_uses_a_new_explicit_intent(reader, monkeypatch):
    app, widget, controller, database, _path, _gates = reader
    original = operations.prepare

    def failed(*_args, **_kwargs):
        raise OSError("fixture preparation failure")

    monkeypatch.setattr(operations, "prepare", failed)
    widget.note_edit.setPlainText("keep my note")
    widget.ask_box.setText("unsent question")
    assert controller.remember()
    idle(app, controller)
    assert "failed" in controller.status.text()
    assert not records(database, positions.TABLE)
    monkeypatch.setattr(operations, "prepare", original)
    assert controller.check()
    idle(app, controller)
    assert controller.remember()
    idle(app, controller)
    assert records(database, positions.TABLE)[0][2] == 1
    assert widget.note_edit.toPlainText() == "keep my note"
    assert widget.ask_box.text() == "unsent question"


def recorded(reader, page=4):
    app, widget, controller, database, _path, _gates = reader
    widget.pdf.go_to_position(page)
    assert controller.remember()
    idle(app, controller)
    widget.pdf.go_to_position(1)
    controller.observer.suppress()
    app.processEvents()
    assert widget.pdf.current_page() == 0
    return records(database, positions.RECEIPTS)


def test_resume_is_explicit_source_checked_and_never_echo_saves(reader):
    app, widget, controller, database, _path, _gates = reader
    before = recorded(reader)
    widget.ask_box.setText("unsent")
    assert not controller.resume()
    assert "draft" in controller.status.text()
    widget.ask_box.clear()
    assert controller.resume()
    for _ in range(8):
        assert not controller.resume()
    idle(app, controller)
    assert widget.pdf.current_page() + 1 == 4
    assert records(database, positions.RECEIPTS) == before
    assert records(database, positions.TABLE)[0][2] == 4


@pytest.mark.parametrize(
    "change", ["draft", "page", "epoch", "source", "parent", "position", "close"]
)
def test_late_resume_never_discards_drafts_or_jumps_after_context_changes(
    reader, monkeypatch, change
):
    app, widget, controller, database, path, _gates = reader
    before = recorded(reader)
    entered, release = gate(monkeypatch, reader, "navigate")
    assert controller.resume()
    until(app, entered.is_set)
    if change == "draft":
        widget.note_edit.setPlainText("a late note draft")
    elif change == "page":
        widget.pdf.go_to_position(2)
    elif change == "epoch":
        widget._qa_epoch += 1
        controller.invalidate()
    elif change == "source":
        path.write_bytes(pdf_bytes(2, "B"))
    elif change == "parent":
        with store.connect() as conn:
            conn.execute("DELETE FROM papers WHERE id='local-paper'")
    elif change == "position":
        operations.save(prepared(view(database, path), 2))
    else:
        assert not controller.request_close()
    release.set()
    idle(app, controller)
    assert widget.pdf.current_page() + 1 == (2 if change == "page" else 1)
    assert len(records(database, positions.RECEIPTS)) == len(before) + (change == "position")
    if change == "draft":
        assert widget.note_edit.toPlainText() == "a late note draft"


def test_real_input_during_active_save_coalesces_over_only_own_committed_predecessor(
    reader, monkeypatch
):
    app, widget, controller, database, _path, _gates = reader
    entered, release = gate(monkeypatch, reader, "prepare")
    keyboard_end(app, widget, controller)
    until(app, entered.is_set)
    QTest.keyClick(controller.observer.bar, Qt.Key.Key_Home)
    app.processEvents()
    release.set()
    idle(app, controller)
    assert records(database, positions.TABLE)[0][2:] == (
        1,
        records(database, positions.TABLE)[0][3],
        "observed",
    )
    assert len(records(database, positions.RECEIPTS)) == 2
    assert not controller._paused


def test_pending_tail_already_satisfied_by_exact_own_commit_creates_no_second_receipt(
    reader, monkeypatch
):
    app, widget, controller, database, _path, _gates = reader
    entered, release = gate(monkeypatch, reader, "prepare")
    keyboard_end(app, widget, controller)
    until(app, entered.is_set)
    QTest.keyClick(controller.observer.bar, Qt.Key.Key_Home)
    app.processEvents()
    QTest.keyClick(controller.observer.bar, Qt.Key.Key_End)
    app.processEvents()
    assert controller._pending is not None and controller._pending.page == 4
    release.set()
    idle(app, controller)
    (row,) = records(database, positions.TABLE)
    (receipt,) = records(database, positions.RECEIPTS)
    assert row[2] == 4 and row[4] == "observed"
    assert controller._previous.result["request_id"] == receipt[0]
    assert "Recorded page 4" in controller.status.text()
    assert controller.remember_button.isEnabled() and not controller.stop_button.isVisible()
    assert not controller.busy and controller._pending is None


def test_concurrent_received_position_retains_latest_native_input_without_overwrite(
    reader, monkeypatch
):
    app, widget, controller, database, path, _gates = reader
    original = operations.prepare
    entered, release = gate(monkeypatch, reader, "prepare")
    keyboard_end(app, widget, controller)
    until(app, entered.is_set)
    QTest.keyClick(controller.observer.bar, Qt.Key.Key_Home)
    app.processEvents()
    remote = original(operations.capture(view(database, path)), 2, method="entered")
    operations.save(remote)
    release.set()
    idle(app, controller)
    assert records(database, positions.TABLE)[0][2] == 2
    assert controller._paused and "Captured page 1 was retained" in controller.status.text()
    assert len(records(database, positions.RECEIPTS)) == 3
    assert controller.remember()  # An explicit choice may replace the received page.
    idle(app, controller)
    assert records(database, positions.TABLE)[0][2] == 1
    assert not controller._paused


def test_source_A_position_never_appears_as_a_suggestion_for_new_loaded_B(reader):
    app, widget, controller, database, path, _gates = reader
    recorded(reader)
    original_hash = widget._pdf_fingerprint
    controller.invalidate()
    path.write_bytes(pdf_bytes(2, "B"))
    widget._highlight_view = view(database, path)
    widget._pdf_fingerprint = widget._highlight_view.fingerprint
    assert widget.pdf.load(path)
    app.processEvents()
    idle(app, controller)
    assert controller.view.page_count == 2
    assert controller.suggestion is None and not controller.resume()
    assert widget.pdf.current_page() == 0
    assert records(database, positions.TABLE)[0][1] == original_hash
    widget.pdf.go_to_position(2)
    assert controller.remember()
    idle(app, controller)
    assert sorted(row[2] for row in records(database, positions.TABLE)) == [2, 4]


def test_final_resume_reservation_excludes_parent_change_through_native_jump(reader, monkeypatch):
    app, widget, controller, database, _path, _gates = reader
    recorded(reader)
    original = widget.pdf.go_to_position
    observed = []

    def guarded(page, **kwargs):
        import sqlite3
        from contextlib import closing

        with (
            closing(sqlite3.connect(database, timeout=0)) as connection,
            pytest.raises(sqlite3.OperationalError, match="locked"),
        ):
            connection.execute("DELETE FROM papers WHERE id='local-paper'")
        observed.append(page)
        return original(page, **kwargs)

    monkeypatch.setattr(widget.pdf, "go_to_position", guarded)
    assert controller.resume()
    idle(app, controller)
    assert observed == [4] and widget.pdf.current_page() + 1 == 4


def test_all_verification_and_storage_seams_are_off_Qt_thread(reader, monkeypatch):
    app, widget, controller, _database, _path, _gates = reader
    seen = []
    for name in ("capture", "refresh", "prepare", "save", "navigate"):
        original = getattr(operations, name)

        def checked(*args, _original=original, _name=name, **kwargs):
            assert QThread.currentThread() is not app.thread()
            seen.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(operations, name, checked)
    controller.invalidate()
    assert controller.bind()
    idle(app, controller)
    recorded(reader)
    assert controller.resume()
    idle(app, controller)
    assert set(seen) == {"capture", "refresh", "prepare", "save", "navigate"}


def test_missing_optional_schema_has_actionable_state_without_read_DDL_and_explicit_retry(reader):
    app, _widget, controller, database, _path, _gates = reader
    controller.invalidate()
    with store.connect() as connection:
        connection.execute("DROP TRIGGER paperfact_reading_position_paper_delete")
        connection.execute("DROP TABLE reading_positions")
    assert controller.bind()
    idle(app, controller)
    assert controller.view is None and controller._schema_required
    assert "explicit reading-page schema update" in controller.status.text()
    assert not controller.remember_button.isEnabled()
    with store.connect() as connection:
        assert not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='reading_positions'"
        ).fetchone()
        connection.execute("BEGIN IMMEDIATE")
        positions.initialize(connection)
    assert controller.check()
    idle(app, controller)
    assert controller.view is not None and not controller._schema_required
    assert records(database, positions.TABLE) == []


@pytest.mark.parametrize("locale", ["zh-TW", "en"])
def test_controls_have_concise_bilingual_labels_and_responsive_geometry(reader, locale):
    app, widget, controller, _database, _path, _gates = reader
    controller.locale = locale
    for button, key in (
        (controller.remember_button, "remember"),
        (controller.resume_button, "resume"),
        (controller.check_button, "check"),
    ):
        button.setText(message(key, locale))
        assert button.text() == message(key, locale)
    for width in (540, 1264, 1800):
        widget.resize(width, 780)
        app.processEvents()
        for button in (
            controller.remember_button,
            controller.resume_button,
            controller.check_button,
        ):
            assert button.geometry().right() <= button.parentWidget().width()
            assert button.minimumSizeHint().width() <= button.width()
    assert message("remember", locale) and message("resume", locale)
    assert "automatically" in message("coverage", "en")


def test_background_check_leaves_the_toolbar_still(reader, monkeypatch):
    """The five-second poll ran visibly: a "checking" line and a stop button came and
    went, the toolbar rewrapped and the PDF below it jumped every few seconds."""
    app, _widget, controller, _database, _path, _gates = reader
    entered, release = gate(monkeypatch, reader, "refresh")
    before = (controller.status.text(), controller.remember_button.isEnabled(),
              controller.check_button.isEnabled())
    assert controller.check(quiet=True)
    assert entered.wait(20)
    app.processEvents()
    assert controller.busy
    assert not controller.stop_button.isVisible()
    assert (controller.status.text(), controller.remember_button.isEnabled(),
            controller.check_button.isEnabled()) == before
    release.set()
    idle(app, controller)
    assert controller.status.text() == before[0]
    assert controller.poll.isActive()


def test_an_asked_check_still_shows_that_it_is_working(reader, monkeypatch):
    app, _widget, controller, _database, _path, _gates = reader
    entered, release = gate(monkeypatch, reader, "refresh")
    assert controller.check()
    assert entered.wait(20)
    app.processEvents()
    assert controller.stop_button.isVisible()
    assert controller.status.text() == message("checking", "en")
    release.set()
    idle(app, controller)
    assert not controller.stop_button.isVisible()
