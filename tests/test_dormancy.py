"""A window left in the background stops its checks and catches up when used again."""

import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from paper_daily import ui_stalls  # noqa: E402
from paper_daily.desktop import focus_scope  # noqa: E402
from paper_daily.desktop.dormancy import Dormancy  # noqa: E402


def _send(widget, kind):
    QApplication.sendEvent(widget, QEvent(kind))


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    win = QWidget()
    yield win
    win.deleteLater()
    app.processEvents()


def test_checks_stop_after_a_while_in_the_background_and_catch_up_once_on_return(window):
    dormancy = Dormancy(window, idle_ms=30)
    poll, idle_only = QTimer(window), QTimer(window)
    poll.setInterval(2000)
    poll.start()
    caught_up, woke = [], []
    dormancy.pause_with(poll, lambda: caught_up.append(1))
    dormancy.pause_with(idle_only, lambda: caught_up.append("never started"))
    dormancy.woke.connect(lambda: woke.append(1))

    _send(window, QEvent.Type.WindowDeactivate)
    QTest.qWait(80)
    assert dormancy.asleep and not poll.isActive()

    _send(window, QEvent.Type.WindowActivate)
    # Only what was running is restarted, and each catch-up runs once.
    assert not dormancy.asleep and poll.isActive() and not idle_only.isActive()
    assert caught_up == [1] and woke == [1]
    _send(window, QEvent.Type.WindowActivate)
    assert caught_up == [1] and woke == [1]


def test_a_short_trip_to_another_window_does_not_put_it_to_sleep(window):
    dormancy = Dormancy(window, idle_ms=200)
    poll = QTimer(window)
    poll.setInterval(2000)
    poll.start()
    dormancy.pause_with(poll)
    _send(window, QEvent.Type.WindowDeactivate)
    QTest.qWait(20)
    _send(window, QEvent.Type.WindowActivate)
    QTest.qWait(250)
    assert not dormancy.asleep and poll.isActive()


def test_the_freeze_watcher_rests_while_asleep_and_does_not_report_the_sleep(tmp_path, window):
    watch = ui_stalls.install(tmp_path, window)
    try:
        watch.pause()
        assert not watch.timer.isActive() and not watch.awake.is_set()
        time.sleep(ui_stalls.THRESHOLD + 0.1)  # No beats: a stall if it were awake.
        watch.resume()
        assert watch.timer.isActive() and watch.awake.is_set()
        QTest.qWait(60)
        assert not (tmp_path / "ui-stalls.log").exists()
    finally:
        watch.stop()


def test_the_focus_band_only_animates_while_the_app_is_in_front(window):
    frame = focus_scope._Frame(window, inner=True)
    frame._app_state(Qt.ApplicationState.ApplicationInactive)
    assert not frame._timer.isActive()
    frame._app_state(Qt.ApplicationState.ApplicationActive)
    assert frame._timer.isActive()


def test_the_moving_focus_band_never_repaints_the_panel_under_it(window):
    painted = []

    class Panel(QWidget):
        def paintEvent(self, _event):
            painted.append(1)

    window.resize(300, 200)
    panel = Panel(window)
    panel.resize(300, 200)
    frame = focus_scope._Frame(panel, inner=True)
    window.show()
    QTest.qWait(50)
    painted.clear()
    for _ in range(5):
        frame.phase += 0.1
        frame.update()
        QTest.qWait(20)
    assert painted == []


def test_the_watcher_thread_waits_instead_of_spinning_while_paused(tmp_path):
    watch = ui_stalls.Watchdog(tmp_path / "log")
    checks = []
    watch.check = lambda: checks.append(1)
    watch.pause()
    watch.start()
    time.sleep(0.2)
    assert checks == []
    watch.resume()
    deadline = time.monotonic() + 2
    while not checks and time.monotonic() < deadline:
        time.sleep(0.02)
    watch.stop()
    assert checks


def test_returning_to_the_window_gives_the_keys_back_to_the_list(window):
    from PySide6.QtWidgets import (
        QLineEdit,
        QListView,
        QPushButton,
        QStackedWidget,
        QVBoxLayout,
    )

    from paper_daily.desktop.dormancy import keys_home

    layout = QVBoxLayout(window)
    window.stack = QStackedWidget()
    page = QWidget()
    page.view = QListView(page)
    window.stack.addWidget(page)
    button, search = QPushButton("查看結果"), QLineEdit()
    for widget in (window.stack, button, search):
        layout.addWidget(widget)
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window, 1000)

    button.setFocus()
    keys_home(window)
    assert QApplication.focusWidget() is page.view

    # Typing in a search box is left alone.
    search.setFocus()
    keys_home(window)
    assert QApplication.focusWidget() is search
