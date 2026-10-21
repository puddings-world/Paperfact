"""Generate assets/paper-daily.ico for the desktop shortcut, or (with --iconset DIR)
the PNG set macOS's iconutil turns into the .app icon.

Drawn rather than shipped as a binary so the repo stays text, and so the icon can be
changed by editing a few numbers. Kept deliberately blunt: at 16 px a Windows
shortcut icon is a silhouette and a colour, nothing more -- a blue tile with a pale
page on it, and one amber mark for the oral/spotlight accent the app uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter

ACCENT = QColor("#2f5bd8")
PAGE = QColor("#f7f8fc")
RULE = QColor("#b9c4e6")
AWARD = QColor("#e8934f")

SIZES = (256, 128, 64, 48, 32, 16)
# The names iconutil requires: each size at 1x and 2x.
ICONSET = (16, 32, 128, 256, 512)


def draw(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256  # everything below is in 256-space, scaled once

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(ACCENT))
    p.drawRoundedRect(QRectF(0, 0, 256 * s, 256 * s), 56 * s, 56 * s)

    # The page, inset and slightly tall, so the silhouette reads as a document.
    p.setBrush(QBrush(PAGE))
    p.drawRoundedRect(QRectF(66 * s, 46 * s, 124 * s, 164 * s), 10 * s, 10 * s)

    # Text rules. Skipped below 32 px, where they turn into mud.
    if size >= 32:
        p.setBrush(QBrush(RULE))
        for i, width in enumerate((86, 86, 64, 86, 48)):
            y = 78 + i * 26
            p.drawRoundedRect(QRectF(86 * s, y * s, width * s, 10 * s), 5 * s, 5 * s)

    # One amber mark: the award signal that drives the ranking.
    p.setBrush(QBrush(AWARD))
    p.drawEllipse(QRectF(170 * s, 168 * s, 44 * s, 44 * s))

    p.end()
    return image


def main() -> int:
    QGuiApplication(sys.argv)  # QPainter on QImage still needs a GUI application
    if "--iconset" in sys.argv:
        folder = Path(sys.argv[sys.argv.index("--iconset") + 1])
        folder.mkdir(parents=True, exist_ok=True)
        for size in ICONSET:
            draw(size).save(str(folder / f"icon_{size}x{size}.png"))
            draw(size * 2).save(str(folder / f"icon_{size}x{size}@2x.png"))
        return 0
    dest = Path(__file__).resolve().parents[1] / "assets" / "paper-daily.ico"
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Qt's ICO writer takes a single image and produces the standard size set from
    # it, so hand it the largest and let it downscale.
    if not draw(max(SIZES)).save(str(dest), "ICO"):
        print("could not write", dest)
        return 1
    print(dest, f"({dest.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
