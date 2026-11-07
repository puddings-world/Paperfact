"""Which panel of the reader a click or a key belongs to.

The window nests panels -- the PDF, the analysis tabs, and inside 簡報 the slide
list, the views and the materials -- and keyboard focus alone did not say which one
you were in: a click on a panel's background focused nothing, and nothing on screen
showed where keys would go. A panel registered here takes focus on any click inside
it, the innermost one wins. Keys go to the innermost panel first and then outward,
so every panel on that path is live: the innermost is framed strongly, the ones
around it faintly, and the path with the inner panel's keys shows for a moment on
arrival. Panel-level shortcuts ask `within()`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QGradient, QLinearGradient, QPainter, QPen, QRegion
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QWidget
from shiboken6 import isValid

from paper_daily.desktop import window_events

TAG_MS = 1800
# After its moment on arrival the tag stays, faint, so the keys remain findable.
TAG_RESTING_OPACITY = 0.45
# The active panel's outline: a cyan band that drifts once around in FRAME_CYCLE_MS.
FOCUS_DEEP = "#13a4c4"
FOCUS_LIGHT = "#9be8f7"
FRAME_TICK_MS = 50
FRAME_CYCLE_MS = 2600
# The band drifts on arrival and then rests. Drifting for as long as the panel had
# the keys repainted the window twenty times a second for hours: seven percent of a
# core on an untouched reader, and on a Mac the whole window recomposited each time.
FRAME_DRIFT_MS = 2 * FRAME_CYCLE_MS
# Clear of a vertical scroll bar at the panel's right edge.
TAG_INSET = 22


@dataclass(eq=False)
class Region:
    widget: QWidget
    name: str
    keys: str
    target: Callable[[], QWidget | None]


class _Frame(QWidget):
    """The panel's outline. The panel with the keys gets a light-to-deep cyan band
    drifting slowly around it, so it reads as "keys go here" rather than as an error;
    the panels around it a faint still line. The band moves for a moment on arrival,
    then stays still."""

    def __init__(self, parent: QWidget, inner: bool) -> None:
        super().__init__(parent)
        self.width_px = 2 if inner else 1
        self.inner = inner
        self.phase = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(parent.rect())
        self._ticks_left = FRAME_DRIFT_MS // FRAME_TICK_MS
        if inner:
            self._timer = QTimer(self)
            self._timer.setInterval(FRAME_TICK_MS)
            self._timer.timeout.connect(self._advance)
            self._timer.start()

    def resizeEvent(self, _event) -> None:
        # Only the ring is this widget's: each animation step then repaints a
        # two-pixel outline, not the PDF or slides underneath it.
        whole = QRegion(self.rect())
        self.setMask(whole.subtracted(QRegion(self.rect().adjusted(3, 3, -3, -3))))

    def _advance(self) -> None:
        if not self.window().isActiveWindow():
            return
        self._ticks_left -= 1
        if self._ticks_left <= 0:
            self._timer.stop()
        self.phase = (self.phase + FRAME_TICK_MS / FRAME_CYCLE_MS) % 1.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        if self.inner:
            span = max(self.width(), self.height(), 1)
            start = self.phase * span
            band = QLinearGradient(start, 0, start + span, span)
            band.setSpread(QGradient.Spread.RepeatSpread)
            band.setColorAt(0.0, QColor(FOCUS_DEEP))
            band.setColorAt(0.5, QColor(FOCUS_LIGHT))
            band.setColorAt(1.0, QColor(FOCUS_DEEP))
            pen = QPen(QBrush(band), self.width_px)
        else:
            faint = QColor(FOCUS_DEEP)
            faint.setAlpha(70)
            pen = QPen(faint, self.width_px)
        painter.setPen(pen)
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))


class FocusScopes(QObject):
    def __init__(self, accent: str) -> None:
        super().__init__(QApplication.instance())
        self.accent = accent
        self.regions: list[Region] = []
        self.active: Region | None = None
        self._frames: dict[QWidget, _Frame] = {}
        self._tag: QLabel | None = None
        self._tag_timer = QTimer(self)
        self._tag_timer.setSingleShot(True)
        self._tag_timer.setInterval(TAG_MS)
        self._tag_timer.timeout.connect(self._hide_tag)
        self._last_press = None
        window_events.watch(self)
        QApplication.instance().focusChanged.connect(self._focus_changed)

    def add(self, widget: QWidget, name: str, keys: str = "", target=None) -> Region:
        region = Region(widget, name, keys, target or (lambda: widget))
        self.regions.append(region)
        # A panel can outlive this registry; a Python closure is not automatically
        # disconnected when the QObject it captures is destroyed.
        widget.destroyed.connect(lambda *_: self._forget(region) if isValid(self) else None)
        # A press the clicked widget ignores (a label, a background) bubbles up to
        # the panel; the panel's own resizes keep its frame fitted.
        widget.installEventFilter(self)
        return region

    def step_out(self, window: QWidget) -> bool:
        """Move the keys to the panel around the active one; whether there was one.

        Esc does this first, so the way out of a nested panel is the same key
        that later leaves the page."""
        if self.active is None or self.active.widget.window() is not window:
            return False
        path = self.path(self.active)
        if len(path) < 2:
            return False
        outer = path[-2]
        target = outer.target()
        if target is None:
            return False
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        self._activate(outer)
        return True

    def within(self, widget: QWidget) -> bool:
        """Whether the active panel is `widget` or nested inside it."""
        if self.active is None:
            return False
        inner = self.active.widget
        return inner is widget or widget.isAncestorOf(inner)

    def region_of(self, widget: QWidget | None) -> Region | None:
        if widget is None:
            return None
        found = None
        for region in self.regions:
            contains = region.widget is widget or region.widget.isAncestorOf(widget)
            # The innermost of the nested panels containing the widget.
            if contains and (found is None or found.widget.isAncestorOf(region.widget)):
                found = region
        return found

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress:
            # The same press reaches the window, then bubbles up through the panels;
            # the first to see it says where it landed, and only that one counts.
            stamp = (event.timestamp(), event.globalPosition().toPoint())
            widget = (
                watched
                if isinstance(watched, QWidget)
                else QApplication.widgetAt(event.globalPosition().toPoint())
            )
            if stamp != self._last_press and widget is not None:
                self._last_press = stamp
                region = self.region_of(widget)
                if region is not None:
                    QTimer.singleShot(0, lambda: self._settle(region))
                elif self.active is not None and widget.window() is self.active.widget.window():
                    QTimer.singleShot(0, self._settle_outside)
        elif kind == QEvent.Type.Resize and watched in self._frames:
            self._frames[watched].setGeometry(watched.rect())
            self._place_tag()
        return False

    def _settle(self, region: Region) -> None:
        """After the click: if the widget clicked did not take focus (a background,
        a label), give it to the panel, so keys go where you clicked."""
        if region not in self.regions:
            return
        focus = QApplication.focusWidget()
        if self.region_of(focus) is not region:
            target = region.target()
            if target is not None:
                target.setFocus(Qt.FocusReason.MouseFocusReason)
        self._activate(region)

    def _settle_outside(self) -> None:
        """A click outside every panel (the top bar): the frame follows the keys,
        so it goes only if focus left the panels too."""
        if self.region_of(QApplication.focusWidget()) is None:
            self._clear()

    def _focus_changed(self, _old, new) -> None:
        self._follow(new)

    def _follow(self, widget) -> None:
        region = self.region_of(widget)
        if region is not None:
            self._activate(region)

    def _activate(self, region: Region) -> None:
        if region is self.active:
            return
        self._clear()
        self.active = region
        path = self.path(region)
        for each in path:
            frame = _Frame(each.widget, inner=each is region)
            frame.show()
            frame.raise_()
            self._frames[each.widget] = frame
        text = " › ".join(r.name for r in path) + (f" · {region.keys}" if region.keys else "")
        self._tag = QLabel(text, region.widget)
        self._tag.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._tag.setStyleSheet(
            f"background:{self.accent};color:white;padding:3px 10px;font-size:11px;"
            "border-radius:9px;"
        )
        self._tag.adjustSize()
        self._place_tag()
        self._tag.show()
        self._tag.raise_()
        self._tag_timer.start()

    def path(self, region: Region) -> list[Region]:
        """The panels a key passes through, outermost first."""
        # isAncestorOf counts a widget as its own ancestor.
        chain = [
            r for r in self.regions if r is not region and r.widget.isAncestorOf(region.widget)
        ]
        # Depth counted against the full registry: a key reading `chain` while
        # `chain.sort` runs would see it empty.
        chain.sort(key=lambda r: sum(o.widget.isAncestorOf(r.widget) for o in self.regions))
        return [*chain, region]

    def _place_tag(self) -> None:
        # The bottom corner, clear of the scroll bar: along the top it sat on the
        # panel's own toolbar and hid its buttons.
        if self._tag is not None and self.active is not None:
            panel = self.active.widget
            self._tag.move(
                max(0, panel.width() - self._tag.width() - TAG_INSET),
                max(0, panel.height() - self._tag.height() - TAG_INSET),
            )

    def _hide_tag(self) -> None:
        """Fade the tag to its resting look; `_drop_tag` removes it."""
        if self._tag is not None:
            fade = QGraphicsOpacityEffect(self._tag)
            fade.setOpacity(TAG_RESTING_OPACITY)
            self._tag.setGraphicsEffect(fade)

    def _drop_tag(self) -> None:
        if self._tag is not None:
            self._tag.hide()
            self._tag.deleteLater()
            self._tag = None

    def _clear(self) -> None:
        self._tag_timer.stop()
        self._drop_tag()
        for frame in self._frames.values():
            frame.hide()
            frame.deleteLater()
        self._frames = {}
        self.active = None

    def _forget(self, region: Region) -> None:
        if region in self.regions:
            self.regions.remove(region)
        if self.active is None:
            return
        # By `destroyed` the panel's C++ side may be gone already, so ancestry can
        # no longer be asked; a dead panel on either side ends the active path.
        if (
            self.active is region
            or not isValid(region.widget)
            or not isValid(self.active.widget)
            or region.widget.isAncestorOf(self.active.widget)
        ):
            # Frames and tag that died with their panel are dropped, not hidden.
            self._frames = {w: f for w, f in self._frames.items() if isValid(f)}
            if self._tag is not None and not isValid(self._tag):
                self._tag = None
            self._clear()


_scopes: FocusScopes | None = None


def scopes(accent: str = "#2f5bd8") -> FocusScopes:
    """The one registry for the application; the first caller sets the accent."""
    global _scopes
    if _scopes is None or _scopes.parent() is not QApplication.instance():
        _scopes = FocusScopes(accent)
    return _scopes
