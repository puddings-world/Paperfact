"""Shortcut badges on tabs while the modifier is held.

The tab keys existed but nothing on screen said so, and a tooltip only shows after
hovering one tab. Holding the modifier for a moment shows every tab's key at once,
as Office's KeyTips do; the delay keeps Ctrl+C or a Ctrl-click from flashing them.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QTabBar

from paper_daily.desktop import window_events

DELAY_MS = 350
_MODIFIER_KEYS = {
    Qt.KeyboardModifier.ControlModifier: Qt.Key.Key_Control,
    Qt.KeyboardModifier.AltModifier: Qt.Key.Key_Alt,
}


class KeyHints(QObject):
    """`labels()` gives one badge text per tab (None for no badge); `active()` says
    whether the keys would act right now, so badges never promise a dead key."""

    def __init__(
        self,
        bar: QTabBar,
        modifier: Qt.KeyboardModifier,
        labels: Callable[[], list[str | None]],
        active: Callable[[], bool],
        accent: str = "#2f5bd8",
    ) -> None:
        super().__init__(bar)
        self.bar = bar
        self.modifier = modifier
        self.labels = labels
        self.active = active
        self.accent = accent
        self.badges: list[QLabel] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DELAY_MS)
        self._timer.timeout.connect(self._show)
        window_events.watch(self)
        # Leaving the app or the window ends the hold.
        app = QApplication.instance()
        app.applicationStateChanged.connect(self.hide)
        app.focusWindowChanged.connect(self.hide)

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.KeyPress:
            if (
                event.key() == _MODIFIER_KEYS[self.modifier]
                # Windows reports the press of Ctrl itself without ControlModifier.
                and event.modifiers() in (self.modifier, Qt.KeyboardModifier.NoModifier)
                and not event.isAutoRepeat()
            ):
                self._timer.start()
            else:
                self.hide()
        elif kind == QEvent.Type.KeyRelease:
            if event.key() == _MODIFIER_KEYS[self.modifier]:
                self.hide()
        elif kind == QEvent.Type.MouseButtonPress:
            self.hide()
        return False

    def _show(self) -> None:
        # Release, another key or a click has stopped the timer by now, so the
        # modifier is still the only key held.
        if not self.active():
            return
        self.hide()
        for index, text in enumerate(self.labels()):
            if not text or index >= self.bar.count():
                continue
            # Hung below the tab on the window, not inside the bar, so the badge
            # does not cover the tab's own name.
            badge = QLabel(text, self.bar.window())
            badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            badge.setStyleSheet(
                f"background:{self.accent};color:white;border-radius:3px;"
                "padding:1px 5px;font-size:11px;font-weight:bold;"
            )
            badge.adjustSize()
            rect = self.bar.tabRect(index)
            badge.move(
                self.bar.mapTo(
                    self.bar.window(),
                    QPoint(rect.center().x() - badge.width() // 2, rect.bottom() - 2),
                )
            )
            badge.show()
            badge.raise_()
            self.badges.append(badge)

    @Slot()
    def hide(self) -> None:
        self._timer.stop()
        for badge in self.badges:
            badge.hide()
            badge.deleteLater()
        self.badges = []


def keycap(text: str, size: int = 18) -> QIcon:
    """A small key drawn on a button, for single-key shortcuts that no modifier
    badge announces. Its own light face reads on a checked (blue) button too."""
    ratio = QApplication.instance().devicePixelRatio()
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#8a9ab0"))
    painter.setBrush(QColor("#f7f9fc"))
    painter.drawRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), 3, 3)
    font = painter.font()
    font.setPixelSize(size - 7)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#2b3a4f"))
    painter.drawText(QRectF(0, 0, size, size - 1), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)
