"""PDF pages rendered from the same native scene as the editor."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QMarginsF, QObject, QRectF, QSizeF, QTimer, Signal
from PySide6.QtGui import QPageSize, QPainter, QPdfWriter

from paper_daily.desktop.slide_canvas import SlideCanvas
from paper_daily.slide_layout import HEIGHT, WIDTH


class PdfExport(QObject):
    finished = Signal(str)
    failed = Signal(str)
    progress = Signal(int, int)

    def start(self, deck, dest: Path):
        self.deck, self.dest = deck, dest
        self.index = 0
        self.progress.emit(0, len(deck.slides))
        self.canvas = SlideCanvas()
        self.painter = QPainter()
        self.tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", dir=dest.parent, delete=False) as f:
                self.tmp = Path(f.name)
            self.writer = QPdfWriter(str(self.tmp))
            self.writer.setPageSize(QPageSize(QSizeF(320, 180), QPageSize.Unit.Millimeter))
            self.writer.setPageMargins(QMarginsF(0, 0, 0, 0))
            self.writer.setResolution(96)
            self.writer.setTitle(deck.title)
            if not self.painter.begin(self.writer):
                raise OSError("無法建立 PDF")
            QTimer.singleShot(0, self._page)
        except (ValueError, OSError) as exc:
            self._finish(str(exc))

    def _page(self):
        try:
            if self.index and not self.writer.newPage():
                raise OSError("無法新增 PDF 頁面")
            self.canvas.load(self.deck, self.index)
            self.canvas.scene.render(
                self.painter,
                QRectF(0, 0, self.writer.width(), self.writer.height()),
                QRectF(0, 0, WIDTH, HEIGHT),
            )
            self.index += 1
            self.progress.emit(self.index, len(self.deck.slides))
            if self.index < len(self.deck.slides):
                QTimer.singleShot(0, self._page)
            else:
                self._finish()
        except Exception as exc:  # noqa: BLE001 - close the painter before reporting failure
            self._finish(f"PDF 匯出失敗：{type(exc).__name__}")

    def _finish(self, error=None):
        if self.painter.isActive():
            self.painter.end()
        self.writer = None
        self.canvas.deleteLater()
        try:
            if not error:
                self.tmp.replace(self.dest)
        except OSError as exc:
            error = str(exc)
        finally:
            if self.tmp:
                self.tmp.unlink(missing_ok=True)
        if error:
            self.failed.emit(error)
        else:
            self.finished.emit(str(self.dest))
