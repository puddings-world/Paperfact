"""Native input evidence only; render/load/programmatic page changes emit nothing.

No persistence or PDF I/O lives here. A controller must bind an independently
verified PositionView and run its saves off-thread. This module alone enables no
automatic tracking and never resumes a reader after load.
"""

from __future__ import annotations

from dataclasses import dataclass
from weakref import WeakSet

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from shiboken6 import isValid

from paper_daily.reading_position_ops import PositionView, _native_observation


@dataclass(frozen=True)
class ObservedPage:
    page: int
    epoch: object
    sequence: int
    evidence: object = None


class NativePositionObserver(QObject):
    observed = Signal(object)

    def __init__(self, pane):
        super().__init__(pane)
        pane.destroyed.connect(self.clear)
        self.pane = pane
        self.view = None
        self.epoch = None
        self._native = None
        self._armed = None
        self._drag_page = None
        self._sequence = 0
        self._scheduled = False
        native = getattr(pane, "_view", pane)
        self.bar = native.verticalScrollBar()
        targets = [pane, native, native.viewport(), self.bar]
        selection = getattr(pane, "selection", None)
        if selection is not None:
            targets.append(selection)
        self._base_targets = set(targets)
        self._render_targets = WeakSet()
        for target in self._base_targets:
            target.installEventFilter(self)

    def _bind_render_targets(self):
        # Image labels receive the original spontaneous wheel event before Qt
        # forwards it to the scroll area. These are only this pane's current
        # renderer children, never an application-wide input observer.
        current = set(getattr(self.pane, "_labels", ()))
        inner = getattr(self.pane, "_inner", None)
        if inner is not None:
            current.add(inner)
        previous = set(self._render_targets)
        for target in previous - current:
            if isValid(target):
                target.removeEventFilter(self)
        for target in current - previous:
            target.installEventFilter(self)
        self._render_targets = WeakSet(current)

    def _identity(self):
        return self.pane.position_identity()

    @property
    def pending_input(self):
        return self._armed is not None or self._drag_page is not None

    def bind(self, view, epoch):
        self.clear()
        if not isValid(self.pane) or not isinstance(view, PositionView):
            raise ValueError("Observation requires a verified loaded source")
        native = self._identity()
        if (
            native[1] != view.highlight.path
            or self.pane.page_count() != view.page_count
            or self.pane.position_source_version() != view.original_version
        ):
            raise ValueError("Native reader differs from the verified original")
        self.view, self.epoch, self._native = view, epoch, native
        self._bind_render_targets()

    def clear(self):
        self.view = self.epoch = self._native = self._armed = None
        self._drag_page = None

    def suppress(self):
        """Explicit navigation/load/received-suggestion boundaries discard input evidence."""
        self._armed = None
        self._drag_page = None

    def eventFilter(self, target, event):
        if target not in self._base_targets and target not in self._render_targets:
            return False
        if self.view is None or self._identity() != self._native:
            self.clear()
            return False
        # An ordinary setValue, navigator signal, timer, or rendered suggestion is
        # insufficient. Native OS input (QTest simulates it in fixtures) is required.
        if not event.spontaneous():
            return False
        kind = event.type()
        if (
            kind == QEvent.Type.MouseButtonPress
            and target is self.bar
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._drag_page = self.pane.current_page()
            return False
        navigation = (
            (
                kind == QEvent.Type.Wheel
                and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
            )
            or (
                kind == QEvent.Type.KeyPress
                and event.key()
                in (
                    Qt.Key.Key_Up,
                    Qt.Key.Key_Down,
                    Qt.Key.Key_PageUp,
                    Qt.Key.Key_PageDown,
                    Qt.Key.Key_Home,
                    Qt.Key.Key_End,
                    Qt.Key.Key_Space,
                )
                and not event.modifiers()
                & (
                    Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.AltModifier
                    | Qt.KeyboardModifier.MetaModifier
                )
            )
            or (
                kind == QEvent.Type.MouseButtonRelease
                and target is self.bar
                and event.button() == Qt.MouseButton.LeftButton
            )
        )
        if navigation:
            before = self.pane.current_page()
            if kind == QEvent.Type.MouseButtonRelease:
                before, self._drag_page = self._drag_page, None
                if before is None:
                    return False
            self._sequence += 1
            self._armed = (self._sequence, before)
            if not self._scheduled:
                self._scheduled = True
                QTimer.singleShot(0, self._after_input)
        return False

    def _after_input(self):
        self._scheduled = False
        evidence, self._armed = self._armed, None
        if (
            evidence is None
            or self.view is None
            or not isValid(self.pane)
            or self._identity() != self._native
            or not self.pane.isVisible()
            or self.pane.page_count() != self.view.page_count
            or self.pane.position_source_version() != self.view.original_version
        ):
            return
        sequence, before = evidence
        page = self.pane.current_page()
        if type(page) is int and 0 <= page < self.view.page_count and page != before:
            proof = _native_observation(self.view, page + 1)
            self.observed.emit(ObservedPage(page + 1, self.epoch, sequence, proof))


class ObservationBuffer:
    """Bounded latest-per-view coalescing; a renderer is never a source of input."""

    def __init__(self):
        self.epoch = None
        self.pending = None
        self.active = None
        self.last_sequence = 0

    def bind(self, epoch):
        self.epoch, self.pending, self.active, self.last_sequence = epoch, None, None, 0

    def offer(self, observation):
        if (
            not isinstance(observation, ObservedPage)
            or observation.epoch is not self.epoch
            or observation.sequence <= self.last_sequence
        ):
            return False
        self.last_sequence = observation.sequence
        self.pending = observation
        return True

    def take(self):
        if self.active is not None or self.pending is None:
            return None
        self.active, self.pending = self.pending, None
        return self.active

    def complete(self, observation):
        if self.active is observation and observation.epoch is self.epoch:
            self.active = None
            return True
        return False

    def cancel(self):
        self.bind(None)
