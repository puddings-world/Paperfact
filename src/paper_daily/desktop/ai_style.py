"""One look for every button that starts AI work.

Pressing one of these spends minutes and a model call, unlike opening a tab or
ticking a paper, and they were styled like everything else: blue in one place,
plain grey in the next. They now share a violet face and a spark, so "this asks
the AI" reads at a glance across the reader, the lists and the slides.

`primary` is for the one action a view is waiting on (深入分析 on an unanalysed
paper); the rest are the outlined form, which still reads as AI but does not
compete with it.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QAbstractButton, QApplication

TOOLTIP_NOTE = "（使用 AI）"


def spark(colour: str, size: int = 14) -> QIcon:
    """A four-pointed star, the mark the button carries."""
    ratio = QApplication.instance().devicePixelRatio()
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    c, r, w = size / 2, size / 2 - 0.5, size * 0.13
    path = QPainterPath(QPointF(c, c - r))
    for x, y in ((c + w, c - w), (c + r, c), (c + w, c + w), (c, c + r),
                 (c - w, c + w), (c - r, c), (c - w, c - w)):
        path.lineTo(x, y)
    path.closeSubpath()
    painter.fillPath(path, QColor(colour))
    painter.end()
    return QIcon(pixmap)


def css(pal: dict[str, str], primary: bool = False) -> str:
    # The same pressable shape as other buttons: a heavier lower edge that the
    # press flattens.
    edge = QColor(pal["ai"]).darker(135).name()
    if primary:
        return (
            f"QPushButton{{background:{pal['ai']};color:{pal['onAi']};"
            f"border:1px solid {pal['ai']};border-bottom:2px solid {edge};border-radius:6px;"
            f"padding:5px 14px 4px 14px;font-weight:600;font-size:12px;}}"
            f"QPushButton:hover{{background:{pal['aiStrong']};border-color:{pal['aiStrong']};}}"
            f"QPushButton:pressed{{border-bottom-width:1px;padding:6px 14px 4px 14px;}}"
            f"QPushButton:disabled{{background:{pal['sunk']};color:{pal['faint']};"
            f"border-color:{pal['border']};}}"
        )
    return (
        f"QPushButton{{background:{pal['aiSoft']};color:{pal['ai']};"
        f"border:1px solid {pal['ai']};border-bottom:2px solid {edge};border-radius:6px;"
        f"padding:4px 11px 3px 11px;font-weight:600;font-size:12px;}}"
        f"QPushButton:hover{{background:{pal['surface']};}}"
        f"QPushButton:pressed{{border-bottom-width:1px;padding:5px 11px 3px 11px;}}"
        f"QPushButton:disabled{{background:{pal['sunk']};color:{pal['faint']};"
        f"border-color:{pal['border']};}}"
    )


def mark(
    button: QAbstractButton, pal: dict[str, str] | None = None, primary: bool = False
) -> QAbstractButton:
    """Give an existing button the AI look. Returns it, for chaining.

    Panels built without the window's palette (the slide editor, the materials
    list) take the current one."""
    if pal is None:
        from paper_daily.desktop.main import palette

        pal = palette()
    button.setStyleSheet(css(pal, primary))
    button.setIcon(spark(pal["onAi"] if primary else pal["ai"]))
    button.setIconSize(QSize(13, 13))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    tip = button.toolTip()
    if "AI" not in tip:
        button.setToolTip(tip + TOOLTIP_NOTE if tip else "按下會呼叫 AI。")
    button.setProperty("ai", "primary" if primary else "secondary")
    return button
