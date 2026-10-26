"""Keep inactive editor layouts from pushing reading controls off the screen."""

from PySide6.QtCore import QEvent, QMargins, QObject, QPoint, QRect, QSize, QTimer
from PySide6.QtWidgets import QStackedWidget, QTabWidget, QWidget


class ReadingTabs(QTabWidget):
    """Reserve the active page's height, rather than the tallest hidden editor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        page = self.currentWidget()
        stack = self.findChild(QStackedWidget, "qt_tabwidget_stackedwidget")
        if page is None or stack is None:
            return hint
        # Qt still supplies the style-dependent tab bar/frame dimensions. Keep
        # its horizontal minimum, but do not inherit a hidden slide editor's
        # minimum height when the user is reading or asking a question.
        chrome = max(0, hint.height() - stack.minimumSizeHint().height())
        height = max(0, page.minimumSizeHint().height(), page.minimumHeight())
        return QSize(hint.width(), chrome + height)


def _largest_margins(first, second):
    return QMargins(
        max(first.left(), second.left()),
        max(first.top(), second.top()),
        max(first.right(), second.right()),
        max(first.bottom(), second.bottom()),
    )


def _frame_margins(window):
    frame, client = window.frameGeometry(), window.geometry()
    observed = QMargins(
        max(0, client.left() - frame.left()),
        max(0, client.top() - frame.top()),
        max(0, frame.right() - client.right()),
        max(0, frame.bottom() - client.bottom()),
    )
    handle = window.windowHandle()
    # Windows can report stale QWidget frameGeometry during restore/show, while
    # QWindow already knows the actual non-client border and title-bar sizes.
    return _largest_margins(observed, handle.frameMargins()) if handle else observed


def _outer_geometry(window, margins):
    client = window.geometry()
    return QRect(
        client.x() - margins.left(),
        client.y() - margins.top(),
        window.width() + margins.left() + margins.right(),
        window.height() + margins.top() + margins.bottom(),
    )


def fit_to_work_area(window, available=None, *, margins=None):
    """Fit a restored normal window, including its frame, inside its screen."""
    if window.isMinimized() or window.isMaximized() or window.isFullScreen():
        return
    screen = window.screen()
    if available is None:
        if screen is None:
            return
        available = screen.availableGeometry()
    if not available.isValid():
        return
    margins = _largest_margins(margins or QMargins(), _frame_margins(window))
    target = QSize(
        min(window.width(), max(1, available.width() - margins.left() - margins.right())),
        min(window.height(), max(1, available.height() - margins.top() - margins.bottom())),
    )
    if target != window.size():
        window.resize(target)
    margins = _largest_margins(margins, _frame_margins(window))
    frame = _outer_geometry(window, margins)
    x = max(available.left(), min(frame.left(), available.right() - frame.width() + 1))
    y = max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1))
    if frame.topLeft() != QPoint(x, y):
        handle = window.windowHandle()
        if handle is not None:
            handle.setFramePosition(QPoint(x, y))
        else:
            window.move(x, y)


class _StartupFit(QObject):
    # Total settling window is under one second; this is not an ongoing resize
    # policy. Never fight the user's window placement after startup.
    _DELAYS = (0, 80, 160, 320, 400)
    _INPUT = {
        QEvent.Type.KeyPress,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.NonClientAreaMouseButtonPress,
        QEvent.Type.Wheel,
        QEvent.Type.TouchBegin,
    }

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.active = True
        self._attempt = 0
        self._margins = QMargins()
        self._last_geometry = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._tick)
        from paper_daily.desktop import window_events

        # The existing scoped watcher avoids WebEngine internal-object crashes
        # caused by Python filters installed on QApplication (especially Linux).
        window.installEventFilter(self)
        window_events.watch(self)
        self.timer.start(self._DELAYS[0])

    def stop(self):
        if self.active:
            self.active = False
            self.timer.stop()
            self.window.removeEventFilter(self)

    def eventFilter(self, watched, event):
        if not self.active:
            return False
        window = self.window
        belongs = (
            watched is window
            or watched is window.windowHandle()
            or isinstance(watched, QWidget) and watched.window() is window
        )
        user_input = belongs and event.type() in self._INPUT
        hidden = watched is window and event.type() in (QEvent.Type.Hide, QEvent.Type.Close)
        state_changed = (
            watched is window
            and event.type() == QEvent.Type.WindowStateChange
            and (window.isMinimized() or window.isMaximized() or window.isFullScreen())
        )
        if user_input or hidden or state_changed:
            self.stop()
        return False

    def _tick(self):
        window = self.window
        if not self.active:
            return
        if (
            not window.isVisible()
            or window.isMinimized()
            or window.isMaximized()
            or window.isFullScreen()
        ):
            self.stop()
            return
        layout = window.layout()
        if layout is not None:
            layout.activate()
        screen = window.screen()
        if screen is None:
            self.stop()
            return
        available = screen.availableGeometry()
        self._margins = _largest_margins(self._margins, _frame_margins(window))
        fit_to_work_area(window, available, margins=self._margins)
        self._margins = _largest_margins(self._margins, _frame_margins(window))
        geometry = _outer_geometry(window, self._margins)
        settled = available.contains(geometry) and geometry == self._last_geometry
        self._last_geometry = geometry
        self._attempt += 1
        if self._attempt >= len(self._DELAYS) or (self._attempt >= 4 and settled):
            self.stop()
        else:
            self.timer.start(self._DELAYS[self._attempt])


def schedule_startup_fit(window):
    """Fit after native restoration settles, unless the user takes control."""
    previous = getattr(window, "_startup_fit", None)
    if previous is not None:
        return previous
    window._startup_fit = _StartupFit(window)
    return window._startup_fit
