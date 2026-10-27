"""One pressable look for ordinary buttons.

Flat buttons gave no sign that a click registered until its result appeared,
which made a slow result feel like a missed click. These are lit from above,
sit on a heavier lower edge, and sink a pixel while pressed.
"""

from __future__ import annotations

from PySide6.QtGui import QColor


def pressable(pal: dict[str, str], selector: str = "QPushButton", pad=(6, 12)) -> str:
    vertical, side = pad
    edge = QColor(pal["firm"]).darker(118).name()
    accent_edge = QColor(pal["accent"]).darker(125).name()
    # The pressed and disabled states trade a pixel of lower edge for a pixel of
    # top padding, so the label moves down while the button keeps its height.
    sunk = f"padding:{vertical + 1}px {side}px {vertical - 1}px {side}px;"
    return (
        f"{selector}{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {pal['surface']},stop:1 {pal['sunk']});color:{pal['ink']};"
        f"border:1px solid {pal['firm']};border-bottom:2px solid {edge};border-radius:6px;"
        f"padding:{vertical}px {side}px {vertical - 1}px {side}px;}}"
        f"{selector}:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"stop:0 {pal['surface']},stop:1 {pal['accentSoft']});border-color:{pal['accent']};"
        f"border-bottom-color:{accent_edge};color:{pal['accent']};}}"
        f"{selector}:pressed{{background:{pal['accentSoft']};border-bottom-width:1px;{sunk}}}"
        f"{selector}:focus{{border-color:{pal['accent']};}}"
        f"{selector}:disabled{{color:{pal['faint']};background:{pal['sunk']};"
        f"border-color:{pal['border']};border-bottom-width:1px;{sunk}}}"
    )


def pressable_accent(pal: dict[str, str], selector: str, pad=(6, 18)) -> str:
    """The same shape for the one filled, accent-coloured action on a view."""
    vertical, side = pad
    edge = QColor(pal["accent"]).darker(125).name()
    return (
        f"{selector}{{background:{pal['accent']};color:#ffffff;font-weight:600;"
        f"border:1px solid {pal['accent']};border-bottom:2px solid {edge};border-radius:6px;"
        f"padding:{vertical}px {side}px {vertical - 1}px {side}px;}}"
        f"{selector}:hover{{background:{edge};color:#ffffff;}}"
        f"{selector}:pressed{{border-bottom-width:1px;"
        f"padding:{vertical + 1}px {side}px {vertical - 1}px {side}px;}}"
    )
