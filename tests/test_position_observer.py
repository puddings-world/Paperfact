"""Actual Qt PDF and image fallback input; rendering alone never saves a page."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from test_reading_positions import bound as bound_fixture
from test_reading_positions import loaded as loaded_fixture

from paper_daily import reading_position_ops as operations
from paper_daily.desktop import pdfpane
from paper_daily.desktop.position_observer import (
    NativePositionObserver,
    ObservationBuffer,
    ObservedPage,
)

loaded = loaded_fixture
bound = bound_fixture


def settle(app):
    for _ in range(8):
        app.processEvents()


@pytest.fixture(params=["pixmap", "qt"] if pdfpane.HAVE_QTPDF else ["pixmap"])
def native_pane(request, loaded):
    app = QApplication.instance() or QApplication([])
    client, path, highlight = loaded
    pane = pdfpane._QtPdfPane() if request.param == "qt" else pdfpane._PixmapPdfPane()
    pane.resize(560, 450)
    pane.show()
    assert pane.load(path)
    settle(app)
    snapshot = operations.capture(highlight)
    observer = NativePositionObserver(pane)
    epoch = object()
    observer.bind(snapshot, epoch)
    events = []
    observer.observed.connect(events.append)
    yield pane, observer, events, snapshot, epoch, app
    if isValid(pane):
        observer.clear()
        pane.unload()
        pane.close()
        pane.deleteLater()
    settle(app)


def test_load_render_resize_and_programmatic_scroll_do_not_create_observations(native_pane):
    pane, observer, events, _snapshot, _epoch, app = native_pane
    pane.resize(580, 470)
    observer.bar.setValue(observer.bar.maximum())
    settle(app)
    assert not events
    assert pane.position_identity()[1] is not None


def test_actual_native_keyboard_navigation_reports_the_visible_one_based_page(native_pane):
    pane, observer, events, _snapshot, epoch, app = native_pane
    observer.bar.setFocus()
    QTest.keyClick(observer.bar, Qt.Key.Key_End)
    settle(app)
    assert observer.bar.value() == observer.bar.maximum() > 0
    assert len(events) == 1
    assert events[0].epoch is epoch
    assert events[0].page == pane.current_page() + 1 > 1
    attempt = operations.prepare(
        _snapshot, events[0].page, method="observed", observation=events[0].evidence
    )
    result = operations.save(attempt)
    assert result["position"]["method"] == "observed"
    assert result["position"]["page"] == pane.current_page() + 1


@pytest.mark.parametrize("change", ["unload", "reload", "suppress", "clear", "close"])
def test_pending_native_input_cannot_survive_source_view_or_navigation_change(native_pane, change):
    pane, observer, events, snapshot, _epoch, app = native_pane
    observer.bar.setFocus()
    QTest.keyClick(observer.bar, Qt.Key.Key_End)
    if change == "unload":
        pane.unload()
    elif change == "reload":
        assert pane.load(snapshot.highlight.path)
    elif change == "suppress":
        observer.suppress()
    elif change == "close":
        pane.close()
    else:
        observer.clear()
    settle(app)
    assert events == []


def test_failed_native_replacement_preserves_existing_view_without_inventing_activity(
    native_pane, tmp_path
):
    pane, _observer, events, _snapshot, _epoch, app = native_pane
    before = pane.position_identity()
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"not a PDF")
    assert not pane.load(invalid)
    settle(app)
    assert pane.position_identity() == before
    assert not events


def test_native_proof_cannot_bind_another_loaded_path(native_pane, tmp_path):
    pane, observer, _events, snapshot, epoch, _app = native_pane
    replacement = tmp_path / "other.pdf"
    replacement.write_bytes(snapshot.highlight.path.read_bytes())
    assert pane.load(replacement)
    with pytest.raises(ValueError, match="differs"):
        observer.bind(snapshot, epoch)


def test_buffer_coalesces_rapid_backward_reading_and_has_one_active_save():
    queue = ObservationBuffer()
    epoch = object()
    queue.bind(epoch)
    for sequence, page in enumerate([1, 4, 3, 2], 1):
        assert queue.offer(ObservedPage(page, epoch, sequence))
    active = queue.take()
    assert active.page == 2 and queue.take() is None
    assert queue.offer(ObservedPage(1, epoch, 5))
    assert queue.take() is None
    assert queue.complete(active)
    assert queue.take().page == 1
    assert not queue.offer(ObservedPage(4, epoch, 4))
    queue.cancel()
    assert queue.take() is None and not queue.complete(active)
    assert not queue.offer(ObservedPage(3, epoch, 6))


def test_switched_context_rejects_late_completion_without_consuming_new_work():
    queue = ObservationBuffer()
    old, current = object(), object()
    queue.bind(old)
    queue.offer(ObservedPage(2, old, 1))
    active = queue.take()
    queue.bind(current)
    assert queue.offer(ObservedPage(3, current, 1))
    assert not queue.complete(active)
    assert queue.take().page == 3
