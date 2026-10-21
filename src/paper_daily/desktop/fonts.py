"""Fonts and shortcut labels that read the same way on Windows and macOS.

Each family list starts with the face the app ships (see paper_daily.fonts) and
falls back to the platform's own, so a missing download still gives a readable
Traditional Chinese UI rather than Qt's default.
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont, QFontDatabase, QKeySequence

from paper_daily import fonts

MAC = sys.platform == "darwin"

SANS = ("Noto Sans TC", "PingFang TC", "Microsoft JhengHei UI", "Microsoft JhengHei")
MONO = ("JetBrains Mono", "Menlo", "Consolas", "DejaVu Sans Mono", *SANS)
# Georgia is on both systems; it has no CJK glyphs, so Chinese titles take the sans.
SERIF = ("Georgia", *SANS)


def load() -> None:
    for spec in fonts.FONTS:
        path = fonts.FONT_DIR / spec["file"]
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


# Every size in the app is a pixel size. A point is 1.33 pixels on Windows but one
# pixel on macOS, so sizes given in points drew titles a third smaller there while
# stylesheet sizes, in pixels, stayed put.
UI_PIXELS = 12


def points(size: float) -> int:
    """`size` points as Windows draws them, in pixels, on every platform."""
    return round(size * 96 / 72)


def font(families=SANS, size: float | None = None, weight=None, pixels: int | None = None) -> QFont:
    out = QFont()
    out.setFamilies(list(families))
    if size is not None:
        out.setPixelSize(points(size))
    if pixels is not None:
        out.setPixelSize(pixels)
    if weight is not None:
        out.setWeight(weight)
    return out


def css(families=SANS) -> str:
    generic = "monospace" if families is MONO else "sans-serif"
    return ",".join(f"'{f}'" for f in families) + f",{generic}"


def key(sequence) -> str:
    """A shortcut as this platform writes it: Ctrl+Z on Windows, ⌘Z on macOS."""
    if isinstance(sequence, QKeySequence.StandardKey):
        sequence = QKeySequence.keyBindings(sequence)[0]
    return QKeySequence(sequence).toString(QKeySequence.SequenceFormat.NativeText)


# The modifier Qt reads as ControlModifier: the Command key on macOS.
ZOOM_WHEEL = "⌘＋滾輪" if MAC else "Ctrl＋滾輪"
ALT = "⌥" if MAC else "Alt+"
# The key labelled Delete on a Mac keyboard sends Backspace.
DELETE = "⌫" if MAC else "Delete"
