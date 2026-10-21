"""A row of controls that wraps onto a second line instead of running off the edge.

The PDF toolbar is wider than the PDF side often is -- always on a laptop with the
analysis wide, and on macOS even at the default split -- and clipping it hid the
search box and 問這一頁 behind the divider.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget, QWidgetItem


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        # Hints that give way when the row is short, rather than claim a line.
        self._optional: set[int] = set()
        self.setSpacing(spacing)

    def addWidget(self, widget: QWidget, optional: bool = False) -> None:  # noqa: N802
        self.addChildWidget(widget)
        item = QWidgetItem(widget)
        self._items.append(item)
        if optional:
            self._optional.add(id(item))
        self.invalidate()

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if not 0 <= index < len(self._items):
            return None
        item = self._items.pop(index)
        self._optional.discard(id(item))
        return item

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._place(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            if not item.isEmpty() and id(item) not in self._optional:
                size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _place(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        gap = self.spacing()
        lines: list[list[tuple[QLayoutItem, int, QSize]]] = [[]]
        x = area.x()
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            fits = x == area.x() or x + hint.width() <= area.right() + 1
            if id(item) in self._optional:
                if not fits:
                    if apply:
                        item.setGeometry(QRect())
                    continue
            elif not fits:
                lines.append([])
                x = area.x()
            lines[-1].append((item, x, hint))
            x += hint.width() + gap
        y = area.y()
        for line in lines:
            height = max((hint.height() for _i, _x, hint in line), default=0)
            if apply:
                # Centred on the line, as a horizontal box lays out a checkbox
                # beside taller buttons.
                for item, left, hint in line:
                    top = y + (height - hint.height()) // 2
                    item.setGeometry(QRect(QPoint(left, top), hint))
            y += height + gap
        return y - gap - rect.y() + margins.bottom()
