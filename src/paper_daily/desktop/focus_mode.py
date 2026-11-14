"""Reading with nothing on screen but the page.

Every bar, header and side panel is hidden and the window fills the screen; leaving
puts back exactly what was showing, so focus mode never rearranges anyone's layout.
Nothing animates, which also keeps it quiet for people who ask for reduced motion.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLabel

from paper_daily.desktop import fonts, ui_state
from paper_daily.store import connect

HINT = "專注閱讀 · R 閱讀尺 · Esc 離開"


class FocusMode:
    def __init__(self, win):
        self.win = win
        self._saved: tuple[Qt.WindowState, dict] | None = None
        self.hint = QLabel(HINT, win)
        self.hint.setStyleSheet(
            f"background:{win.pal['surface']};color:{win.pal['muted']};"
            f"border:1px solid {win.pal['border']};border-radius:6px;padding:6px 10px;"
        )
        self.hint.hide()
        self._hint_timer = QTimer(win, singleShot=True, interval=2500)
        self._hint_timer.timeout.connect(self.hint.hide)
        toggle = QShortcut(fonts.shortcut(QKeySequence.StandardKey.FullScreen), win)
        toggle.activated.connect(self.toggle)
        self.escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), win)
        self.escape.setEnabled(False)
        self.escape.activated.connect(self.leave)
        self.ruler_key = QShortcut(QKeySequence(Qt.Key.Key_R), win)
        self.ruler_key.setEnabled(False)
        self.ruler_key.activated.connect(self.toggle_ruler)
        self.ruler = False
        win.stack.currentChanged.connect(lambda _i: self.active and self._off_reader())

    @property
    def active(self) -> bool:
        return self._saved is not None

    def _chrome(self) -> list:
        reader = self.win.reader_page
        return [
            self.win.top_toolbar,
            self.win.compact_header,
            reader.paper_header,
            reader.pdf_bar,
            reader.tabs,
        ]

    def _overlay(self):
        return getattr(self.win.reader_page.pdf, "selection", None)

    def toggle_ruler(self) -> None:
        self.ruler = not self.ruler
        self.win.remember("focus_ruler", "1" if self.ruler else "0")
        overlay = self._overlay()
        if overlay is not None:
            overlay.set_ruler(self.ruler)

    def _off_reader(self) -> None:
        if self.win.stack.currentWidget() is not self.win.reader_page:
            self.leave()

    def toggle(self) -> None:
        self.leave() if self.active else self.enter()

    def enter(self) -> bool:
        if self.active or self.win.stack.currentWidget() is not self.win.reader_page:
            return False
        chrome = self._chrome()
        self._saved = (self.win.windowState(), {w: w.isVisibleTo(self.win) for w in chrome})
        for widget in chrome:
            widget.hide()
        self.win.setWindowState(self.win.windowState() | Qt.WindowState.WindowFullScreen)
        self.escape.setEnabled(True)
        self.ruler_key.setEnabled(True)
        with connect() as conn:
            self.ruler = ui_state.read(conn, "ui.focus_ruler") == "1"
        overlay = self._overlay()
        if overlay is not None:
            overlay.set_ruler(self.ruler)
        self.hint.adjustSize()
        self.hint.move(self.win.width() - self.hint.width() - 16, 16)
        self.hint.raise_()
        self.hint.show()
        self._hint_timer.start()
        return True

    def leave(self) -> None:
        if not self.active:
            return
        state, shown = self._saved
        self._saved = None
        self.escape.setEnabled(False)
        self.ruler_key.setEnabled(False)
        overlay = self._overlay()
        if overlay is not None:
            overlay.set_ruler(False)
        self.hint.hide()
        for widget, visible in shown.items():
            widget.setVisible(visible)
        self.win.setWindowState(state)
