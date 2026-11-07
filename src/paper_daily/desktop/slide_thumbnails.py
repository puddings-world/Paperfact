"""Revocable GUI draws with bounded per-pane reuse of asset-free text icons."""

import hashlib
import json
import weakref
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from paper_daily import store
from paper_daily.desktop import fonts
from paper_daily.desktop.window_workspace import current_for
from paper_daily.slide_layout import elements_for

SIZE = (288, 162)
MAX_TEXT_ICONS = 64
MAX_KEY_BYTES = 64 * 1024
COPY = {
    "en": (
        "Thumbnail preparing; slides remain available.",
        "Thumbnail unavailable. Click this page to retry.",
    ),
    "zh-TW": ("縮圖準備中；仍可切換投影片。", "縮圖尚未完成；點選這頁重試。"),
}


def draw(pane, deck, index):
    """Keep the existing source-aware SlideCanvas and all Qt painting on GUI."""
    pane._thumbnail_canvas.load(deck, index)
    image = QPixmap(*SIZE)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    try:
        pane._thumbnail_canvas.scene.render(painter, QRectF(0, 0, *SIZE), QRectF(0, 0, 1200, 675))
    finally:
        painter.end()
    return image


def _text_key(pane, deck, index):
    """Only actual asset-free canvas objects can reuse a visual; never a figure."""
    try:
        if not current_for(pane.window()):
            return None
        objects = elements_for(deck.slides[index])
        if any(obj.get("kind") not in ("text", "table") for obj in objects):
            return None
        # This local key grants no research/source authority. A native workspace
        # replacement or location change must still end even text-image reuse.
        database = Path(store.DB_PATH).resolve()
        try:
            info = database.stat()
            native = (info.st_dev, info.st_ino)
        except FileNotFoundError:
            native = None
        slide = deck.slides[index]
        labels = [
            (sid, next((str(item.get("label", sid)) for item in deck.sources
                        if item["id"] == sid), sid))
            for sid in slide.sources
        ]
        visual = [deck.paper_id, deck.mode, index, len(deck.slides), objects, labels,
                  QApplication.palette().cacheKey(), QApplication.font().key(),
                  fonts.font().key(), pane.outline.iconSize().width(),
                  pane.outline.iconSize().height(), pane.devicePixelRatioF()]
        chunks, size = [], 0
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False,
                                      sort_keys=True).iterencode(visual):
            data = chunk.encode("utf-8")
            size += len(data)
            if size > MAX_KEY_BYTES:
                return None
            chunks.append(data)
        return str(database), native, hashlib.sha256(b"".join(chunks)).digest()
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None


class SlideThumbnails(QObject):
    def __init__(self, pane):
        super().__init__(pane)
        self._pane = weakref.ref(pane)
        self._deck = None
        self._generation = self._serial = 0
        self._pending = OrderedDict()
        self._images = OrderedDict()
        self._tokens = {}
        self._paused = self._closed = self._disposed = False
        self._drawing = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(0)
        self.timer.timeout.connect(self._next)
        pane.installEventFilter(self)
        pane.destroyed.connect(self.dispose)
        pane.outline.itemClicked.connect(
            lambda item: self.request(pane.outline.row(item), priority=True)
        )
        size_changed = getattr(pane.outline, "iconSizeChanged", None)
        if size_changed is not None:
            size_changed.connect(lambda *_: self.refresh())
        self._blank = None

    @property
    def pending(self):
        return bool(self._pending or self._drawing or self.timer.isActive())

    def reset(self):
        self._generation += 1
        self.timer.stop()
        self._pending.clear()
        self._tokens.clear()
        self._deck = None
        self._blank = None

    def dispose(self, *_args):
        self._disposed = True
        self.clear_images()
        with suppress(RuntimeError):
            self.reset()

    def _placeholder(self):
        if self._blank is None:
            image = QPixmap(*SIZE)
            palette = QApplication.palette()
            image.fill(palette.color(QPalette.ColorRole.Base))
            painter = QPainter(image)
            try:
                painter.setPen(palette.color(QPalette.ColorRole.Mid))
                painter.drawRect(1, 1, SIZE[0] - 3, SIZE[1] - 3)
                for y, width in ((48, 175), (69, 210), (90, 150)):
                    painter.drawLine(28, y, width, y)
            finally:
                painter.end()
            self._blank = QIcon(image)
        return self._blank

    def _enqueue(self, pane, index):
        if not 0 <= index < min(len(self._deck.slides), pane.outline.count()):
            return
        self._serial += 1
        self._tokens[index] = self._serial
        self._pending[index] = self._serial
        item = pane.outline.item(index)
        item.setIcon(self._placeholder())
        language = getattr(pane.window(), "language", "zh-TW")
        item.setToolTip(COPY.get(language, COPY["en"])[0])

    def clear_images(self):
        self._images.clear()

    def _restore(self, pane, index):
        key = _text_key(pane, self._deck, index)
        if key is None or key not in self._images or self._stamp(pane, index) is None:
            return False
        icon = self._images[key]
        self._images.move_to_end(key)
        self._pending.pop(index, None)
        self._tokens.pop(index, None)
        pane.outline.item(index).setIcon(icon)
        pane.outline.item(index).setToolTip("")
        return True

    def request(self, index, *, priority=False):
        pane = self._pane()
        if self._disposed or self._closed or pane is None or not isValid(pane):
            return
        deck = pane.deck
        if deck is None:
            self.reset()
            return
        if not 0 <= index < min(len(deck.slides), pane.outline.count()):
            return
        loading = getattr(pane, "_loading", False)
        if self._deck is not deck:
            self.reset()
            self._deck = deck
            for i in range(min(len(deck.slides), pane.outline.count())):
                if not ((i != index or loading or priority) and self._restore(pane, i)):
                    self._enqueue(pane, i)
        # Explicit redraw requests remain fresh; selecting an already complete
        # text page or restoring its mode can retain its exact current visual.
        if (loading or priority) and self._restore(pane, index):
            return
        self._enqueue(pane, index)
        if priority and index in self._pending:
            self._pending.move_to_end(index, last=False)
        if self._pending and not self._paused and not self._drawing and not self.timer.isActive():
            self.timer.start()

    def render_selected_if_small(self):
        """Refresh at most one small text icon after an explicit successful save."""
        pane = self._pane()
        if (self._drawing or self._paused or pane is None or not isValid(pane)
                or pane._index not in self._pending or self._deck is None):
            return
        if _text_key(pane, self._deck, pane._index) is None:
            return
        objects = elements_for(self._deck.slides[pane._index])
        chars = sum(len(obj.get("text", "")) + sum(len(cell) for row in obj.get("rows", [])
                                                   for cell in row) for obj in objects)
        if len(objects) <= 8 and chars <= 2500:
            self.timer.stop()
            self._next()

    def refresh(self):
        if self._disposed or self._closed or self._paused:
            return
        pane = self._pane()
        if pane is None or not isValid(pane) or pane.deck is None:
            return
        self.clear_images()
        self.reset()
        self._deck = pane.deck
        for i in range(min(len(self._deck.slides), pane.outline.count())):
            self._enqueue(pane, i)
        if (
            self._pending
            and not self._paused
            and not self._closed
            and not self._disposed
            and not self._drawing
        ):
            self.timer.start()

    def _stamp(self, pane, index):
        if (
            self._disposed
            or not isValid(pane)
            or self._closed
            or self._paused
            or self._deck is None
            or pane.deck is not self._deck
            or not current_for(pane.window())
            or not 0 <= index < min(len(self._deck.slides), pane.outline.count())
        ):
            return None
        size = pane.outline.iconSize()
        return (
            self._generation,
            id(self._deck),
            id(self._deck.slides[index]),
            pane.outline.item(index),
            pane.paper_id,
            pane._mode,
            QApplication.palette().cacheKey(),
            QApplication.font().key(),
            size.width(),
            size.height(),
            pane.devicePixelRatioF(),
        )

    def _next(self):
        if self._drawing:
            return
        pane = self._pane()
        if pane is None or not isValid(pane) or not self._pending:
            return
        index = pane._index if pane._index in self._pending else next(iter(self._pending))
        token = self._pending.pop(index)
        stamp = self._stamp(pane, index)
        if stamp is None:
            self.reset()
            return
        visual = _text_key(pane, self._deck, index)
        self._drawing = True
        try:
            image = draw(pane, self._deck, index)
        except Exception:
            if stamp == self._stamp(pane, index) and self._tokens.get(index) == token:
                language = getattr(pane.window(), "language", "zh-TW")
                pane.outline.item(index).setToolTip(COPY.get(language, COPY["en"])[1])
        else:
            if stamp == self._stamp(pane, index) and self._tokens.get(index) == token:
                pane.outline.item(index).setIcon(QIcon(image))
                pane.outline.item(index).setToolTip("")
                if visual is not None and visual == _text_key(pane, self._deck, index):
                    self._images[visual] = QIcon(image)
                    self._images.move_to_end(visual)
                    while len(self._images) > MAX_TEXT_ICONS:
                        self._images.popitem(last=False)
        finally:
            self._drawing = False
        if (
            self._pending
            and not self._paused
            and not self._closed
            and not self._disposed
            and not self.timer.isActive()
        ):
            self.timer.start()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Type.Hide, QEvent.Type.Close):
            self.clear_images()
            self._paused = True
            self._closed = kind == QEvent.Type.Close
            self.reset()
        elif kind == QEvent.Type.Show:
            self._paused = self._closed = False
            self.refresh()
        elif kind in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.FontChange,
            QEvent.Type.ApplicationFontChange,
            QEvent.Type.StyleChange,
        ):
            self.refresh()
        return False
