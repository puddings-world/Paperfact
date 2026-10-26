"""Visible input and window placement, independent of inactive editor sizes."""

import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QMargins, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from paper_daily.desktop.reading_layout import (
    ReadingTabs,
    fit_to_work_area,
    schedule_startup_fit,
)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_hidden_tall_editor_does_not_push_active_question_offscreen(app):
    window = QWidget()
    layout = QVBoxLayout(window)
    tabs = ReadingTabs()
    layout.addWidget(tabs)
    question = QWidget()
    form = QVBoxLayout(question)
    form.addStretch()
    composer = QLineEdit()
    form.addWidget(composer)
    tall = QWidget()
    tall.setMinimumHeight(900)
    tabs.addTab(question, "Questions")
    tabs.addTab(tall, "Slides")
    try:
        window.resize(800, 400)
        window.show()
        app.processEvents()
        assert window.height() <= 400
        assert composer.isVisible()
        assert window.rect().contains(composer.mapTo(window, composer.rect().bottomRight()))
        tabs.setCurrentWidget(tall)
        app.processEvents()
        assert tabs.minimumSizeHint().height() >= 900
        tabs.setCurrentWidget(question)
        app.processEvents()
        window.resize(800, 400)
        app.processEvents()
        assert window.height() <= 400
        assert composer.isVisible()
    finally:
        window.close()
        window.deleteLater()


@pytest.mark.parametrize("available", [QRect(0, 0, 1280, 580), QRect(-1280, 40, 1280, 580)])
def test_restored_oversized_window_fits_work_area_including_frame(app, available):
    window = QWidget()
    window.resize(1500, 950)
    window.move(1600, 800)
    window.show()
    app.processEvents()
    try:
        fit_to_work_area(window, available)
        app.processEvents()
        assert available.contains(window.frameGeometry())
        before = window.geometry()
        fit_to_work_area(window, available)
        assert window.geometry() == before
    finally:
        window.close()
        window.deleteLater()


def test_fit_preserves_normal_in_bounds_window_and_maximized_state(app):
    window = QWidget()
    window.resize(400, 300)
    window.move(100, 100)
    window.show()
    app.processEvents()
    try:
        before = window.geometry()
        fit_to_work_area(window, QRect(0, 0, 1280, 800))
        assert window.geometry() == before
        window.showMaximized()
        app.processEvents()
        fit_to_work_area(window, QRect(0, 0, 1280, 500))
        assert window.isMaximized()
    finally:
        window.close()
        window.deleteLater()


class NativeFrameFixture(QWidget):
    """Model the observed Windows restore race without touching a real window."""

    def __init__(self, *, ignores_resize=0, late_frame=False):
        super().__init__()
        self.client = QRect(1, 25, 1918, 1274)
        self.actual_margins = QMargins(1, 1, 1, 1) if late_frame else QMargins(8, 31, 8, 8)
        self.ignores_resize = ignores_resize
        self.requests = []
        self.area = QRect(0, 0, 1920, 1040)
        self.handle = SimpleNamespace(
            frameMargins=lambda: self.actual_margins,
            setFramePosition=self.place_frame,
        )

    def place_frame(self, point):
        self.client.moveTopLeft(
            point + QPoint(self.actual_margins.left(), self.actual_margins.top())
        )

    def windowHandle(self):
        return self.handle

    def screen(self):
        return SimpleNamespace(availableGeometry=lambda: self.area)

    def geometry(self):
        return QRect(self.client)

    def frameGeometry(self):
        # QWidget's early cached margins disagree with the native QWindow.
        return self.client.adjusted(-1, -1, 1, 1)

    def width(self):
        return self.client.width()

    def height(self):
        return self.client.height()

    def size(self):
        return self.client.size()

    def resize(self, size):
        self.requests.append(QSize(size))
        if self.ignores_resize:
            self.ignores_resize -= 1
        else:
            self.client.setSize(size)

    def actual_frame(self):
        margin = self.actual_margins
        return self.client.adjusted(-margin.left(), -margin.top(), margin.right(), margin.bottom())


def settle(app, seconds=1.1):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        app.processEvents()
        time.sleep(0.005)


def test_authoritative_native_frame_overrides_stale_widget_frame(app):
    window = NativeFrameFixture()
    try:
        fit_to_work_area(window, window.area)
        assert window.requests == [QSize(1904, 1001)]
        assert window.area.contains(window.actual_frame())
    finally:
        window.deleteLater()


@pytest.mark.parametrize("late_frame", [False, True])
def test_startup_fit_retries_native_restore_and_late_frame_metrics(app, late_frame):
    window = NativeFrameFixture(ignores_resize=1, late_frame=late_frame)
    window.show()
    controller = schedule_startup_fit(window)
    try:
        assert schedule_startup_fit(window) is controller
        if late_frame:
            QTimer.singleShot(50, lambda: setattr(window, "actual_margins", QMargins(8, 31, 8, 8)))
        settle(app)
        assert window.area.contains(window.actual_frame())
        assert window.client.width() <= 1904 and window.client.height() <= 1001
        assert 2 <= len(window.requests) <= 5
        assert not controller.active
    finally:
        window.close()
        window.deleteLater()


def test_startup_fit_stops_after_bounded_native_rejections(app):
    window = NativeFrameFixture(ignores_resize=100)
    window.show()
    controller = schedule_startup_fit(window)
    try:
        settle(app)
        assert len(window.requests) == 5
        assert not controller.active
        settle(app, 0.1)
        assert len(window.requests) == 5
    finally:
        window.close()
        window.deleteLater()


@pytest.mark.parametrize(
    "event", ["typing", "pointer", "minimize", "maximize", "fullscreen", "close"]
)
def test_user_input_or_window_state_stops_pending_fit(app, event):
    window = QWidget()
    layout = QVBoxLayout(window)
    composer = QLineEdit()
    layout.addWidget(composer)
    window.resize(400, 300)
    window.show()
    window.activateWindow()
    app.processEvents()
    composer.setFocus()
    controller = schedule_startup_fit(window)
    before = window.geometry()
    try:
        if event == "typing":
            QApplication.sendEvent(composer, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                                                       Qt.KeyboardModifier.NoModifier, "a"))
            assert composer.text() == "a" and composer.hasFocus()
        elif event == "pointer":
            QTest.mouseClick(composer, Qt.MouseButton.LeftButton)
        elif event == "minimize":
            window.showMinimized()
        elif event == "maximize":
            window.showMaximized()
        elif event == "fullscreen":
            window.showFullScreen()
        else:
            window.close()
        assert not controller.active
        settle(app, 0.1)
        if event in ("typing", "pointer"):
            assert window.geometry() == before
            assert composer.hasFocus()
    finally:
        window.close()
        window.deleteLater()


def test_delayed_fit_keeps_existing_composer_focus_and_draft(app):
    window = QWidget()
    layout = QVBoxLayout(window)
    composer = QLineEdit("Unsent draft")
    layout.addWidget(composer)
    available = app.primaryScreen().availableGeometry()
    window.resize(available.width() + 200, available.height() + 200)
    window.show()
    window.activateWindow()
    app.processEvents()
    composer.setFocus()
    try:
        schedule_startup_fit(window)
        settle(app)
        assert available.contains(window.frameGeometry())
        assert composer.hasFocus() and composer.text() == "Unsent draft"
    finally:
        window.close()
        window.deleteLater()
