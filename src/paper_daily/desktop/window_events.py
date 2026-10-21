"""Event filters on the app's own windows and focused widget, never on the
application object.

A filter on QApplication sees every event of every object, and PySide makes a
Python object of each receiver to hand it over. On Linux some of Qt WebEngine's
internal objects crash that step: with any such filter installed, resizing a
window that shows a web view killed the app (a segfault inside PySide, whatever
the filter did). Keyboard, mouse and drag input reaches a top-level window before
the widget it is for, and shortcut checks and keys reach the focused widget, so
filters there see the input the app's handlers need and nothing internal.
"""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

_filters: list[QObject] = []
_hooked: QApplication | None = None


def watch(handler: QObject) -> None:
    """Give `handler.eventFilter` the input of the focused window and widget."""
    global _hooked
    app = QApplication.instance()
    if _hooked is not app:
        _filters.clear()
        app.focusWindowChanged.connect(_attach)
        app.focusChanged.connect(_focus_moved)
        _hooked = app
    if not any(f is handler for f in _filters):
        _filters.append(handler)
    _attach(app.focusWindow())
    focus = app.focusWidget()
    if focus is not None:
        focus.installEventFilter(handler)


def _live() -> list[QObject]:
    _filters[:] = [f for f in _filters if isValid(f)]
    return _filters


# Only the window and widget Qt just named: walking every top-level widget also
# reaches ones being destroyed, and touching those crashed on macOS.
def _attach(window: QWindow | None) -> None:
    if window is not None and isValid(window):
        for handler in _live():
            window.installEventFilter(handler)


def _focus_moved(_old: QWidget | None, new: QWidget | None) -> None:
    # Left on widgets that lose focus: installing again later is a no-op, and a
    # handler can have installed itself on the same widget for its own reasons.
    if new is not None and isValid(new):
        for handler in _live():
            new.installEventFilter(handler)
        _attach(new.window().windowHandle())
