"""The left half of the reader: the paper as it actually looks.

Two implementations, picked at import time:

* Qt's own `QPdfView`, when `pyside6-addons` is installed. Native scrolling, text
  selection and search come for free.
* Otherwise PyMuPDF, which is already a dependency, rendering pages to images. The
  page looks identical; what is lost is text selection.

The fallback is not hypothetical: `pyside6-addons` is a ~1 GB download that a fresh
clone may not have, and a reader that refuses to show a paper until it finishes is
worse than one that shows a picture of it.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView

    from paper_daily.desktop.pdfselect import PageMap, SelectionOverlay

    HAVE_QTPDF = True
except ImportError:  # pyside6-addons absent
    HAVE_QTPDF = False

ZOOM_STEPS = (0.6, 0.75, 0.9, 1.0, 1.15, 1.35, 1.6, 2.0)
# The Qt view zooms continuously: a wheel notch multiplies by this, and a trackpad's
# fraction of a notch by its share of it, so a pinch-like scroll is smooth.
ZOOM_NOTCH = 1.12
ZOOM_RANGE = (0.35, 4.0)
BASE_DPI = 130
# Pages kept as pixmaps at once. A letter page at 130 dpi is ~5 MB of RGB, so a
# 47-page paper rendered eagerly would hold ~230 MB -- hence a window, not the lot.
RESIDENT_PAGES = 8


class _QtPdfPane(QWidget):
    """Native Qt PDF view, with selection built on top of it."""

    def __init__(self, parent: QWidget | None = None, palette: dict | None = None) -> None:
        super().__init__(parent)
        self._doc = QPdfDocument(self)
        self._view = QPdfView(self)
        self._view.setDocument(self._doc)
        self._view.setPageMode(QPdfView.PageMode.MultiPage)
        self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)
        self._map = PageMap(self._view)

        self.selection = SelectionOverlay(self._view, palette or {}) if palette else None
        self._view.viewport().installEventFilter(self)
        if self.selection is not None:
            self.selection.installEventFilter(self)

    def eventFilter(self, obj, event):
        """Ctrl+wheel zooms about the pointer, as every other reader does."""
        if (
            event.type() == event.Type.Wheel
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            notches = event.angleDelta().y() / 120
            if notches:
                self.zoom_by(ZOOM_NOTCH ** notches, event.position().toPoint())
            return True
        return False

    def _current_zoom(self) -> float:
        """The zoom on screen as a custom factor, FitToWidth included."""
        if self._view.zoomMode() == QPdfView.ZoomMode.Custom:
            return self._view.zoomFactor()
        pages = self._map.pages()
        if not pages:
            return 1.0
        page = min(max(self.current_page(), 0), len(pages) - 1)
        return pages[page][4] / self._map._res()

    def zoom_by(self, factor: float, at: QPoint | None = None) -> str:
        """Zoom by `factor`, keeping the point under `at` where it is on screen.

        Going from FitToWidth to a custom zoom starts from the factor the fit had
        chosen rather than from 100%, which used to jump the page on the first notch.
        """
        viewport = self._view.viewport()
        if at is None:
            at = QPoint(viewport.width() // 2, viewport.height() // 2)
        spot = self._map.at(at)
        new = min(max(self._current_zoom() * factor, ZOOM_RANGE[0]), ZOOM_RANGE[1])
        self._view.setZoomMode(QPdfView.ZoomMode.Custom)
        self._view.setZoomFactor(new)

        def hold() -> None:
            if spot is not None:
                page, x, y = spot
                v, h = self._view.verticalScrollBar(), self._view.horizontalScrollBar()
                v.setValue(self._map.doc_y(page, y) - at.y())
                h.setValue(self._map.doc_x(page, x) - at.x())
            if self.selection is not None:
                self.selection.update()

        # The view relays out at once, but its scroll range can settle a turn later.
        hold()
        QTimer.singleShot(0, hold)
        return f"{_round_pct(new)}%"

    def load(self, path: Path) -> bool:
        self._doc.load(str(path))
        if self.selection is not None:
            self.selection.set_document(path)
        return self._doc.status() == QPdfDocument.Status.Ready

    def page_count(self) -> int:
        return max(self._doc.pageCount(), 0)

    def zoom(self, direction: int) -> str:
        """The − and + buttons: two notches, about the middle of the view."""
        return self.zoom_by(ZOOM_NOTCH ** (2 * direction))

    def fit_width(self) -> str:
        self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        return "fit"

    def current_page(self) -> int:
        return self._view.pageNavigator().currentPage()

    def page_text(self, page: int) -> str:
        """Text of one page. QPdfView exposes no mouse selection, so asking about
        the page you are looking at is the closest thing to asking about a passage."""
        if not 0 <= page < self.page_count():
            return ""
        return self._doc.getAllText(page).text()


def _round_pct(zoom: float) -> int:
    return int(zoom * 100 + 0.5)


class _PixmapPdfPane(QScrollArea):
    """PyMuPDF fallback. Pages are placeholders until they come near the viewport."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(14, 14, 14, 14)
        self._layout.setSpacing(14)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.setWidget(self._inner)

        self._path: Path | None = None
        self._doc = None
        self._labels: list[QLabel] = []
        self._resident: list[int] = []
        self._zoom_index = ZOOM_STEPS.index(1.0)
        self.verticalScrollBar().valueChanged.connect(lambda _: self._render_visible())

    # ---- lifecycle -------------------------------------------------------
    def load(self, path: Path) -> bool:
        self._close()
        if not path.exists():
            return False
        try:
            import pymupdf

            self._doc = pymupdf.open(path)
        except Exception:
            self._doc = None
            return False
        self._path = path
        self._build_placeholders()
        self._render_visible()
        return self.page_count() > 0

    def _close(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._labels.clear()
        self._resident.clear()
        if self._doc is not None:
            with contextlib.suppress(Exception):
                self._doc.close()
            self._doc = None

    def _scale(self) -> float:
        return ZOOM_STEPS[self._zoom_index] * BASE_DPI / 72

    def _build_placeholders(self) -> None:
        """One fixed-size label per page, so the scrollbar is correct from the start."""
        assert self._doc is not None
        scale = self._scale()
        for page in self._doc:
            rect = page.rect
            label = QLabel()
            label.setFixedSize(int(rect.width * scale), int(rect.height * scale))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("background:#ffffff;")
            self._layout.addWidget(label)
            self._labels.append(label)
        self._layout.addStretch(1)

    # ---- rendering -------------------------------------------------------
    def _render_visible(self) -> None:
        if self._doc is None or not self._labels:
            return
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()

        wanted: list[int] = []
        for index, label in enumerate(self._labels):
            y = label.y()
            if y + label.height() >= top - 200 and y <= bottom + 200:
                wanted.append(index)
        if not wanted:
            wanted = [0]

        for index in wanted:
            if index not in self._resident:
                self._paint(index)

        # Drop pages that scrolled away, oldest first.
        while len(self._resident) > RESIDENT_PAGES:
            stale = next((i for i in self._resident if i not in wanted), None)
            if stale is None:
                break
            self._resident.remove(stale)
            self._labels[stale].clear()

    def _paint(self, index: int) -> None:
        import pymupdf

        try:
            page = self._doc[index]
            scale = self._scale()
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
            image = QImage(
                pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888
            ).copy()
        except Exception:
            return
        self._labels[index].setPixmap(QPixmap.fromImage(image))
        self._resident.append(index)

    # ---- public API ------------------------------------------------------
    def page_count(self) -> int:
        return len(self._labels)

    def zoom(self, direction: int) -> str:
        new_index = max(0, min(len(ZOOM_STEPS) - 1, self._zoom_index + direction))
        if new_index == self._zoom_index or self._path is None:
            return f"{int(ZOOM_STEPS[self._zoom_index] * 100)}%"
        self._zoom_index = new_index
        path = self._path
        self.load(path)
        return f"{int(ZOOM_STEPS[self._zoom_index] * 100)}%"

    def current_page(self) -> int:
        """The page filling most of the viewport right now."""
        if not self._labels:
            return 0
        middle = self.verticalScrollBar().value() + self.viewport().height() // 2
        for index, label in enumerate(self._labels):
            if label.y() <= middle <= label.y() + label.height():
                return index
        return 0

    def page_text(self, page: int) -> str:
        if self._doc is None or not 0 <= page < self.page_count():
            return ""
        try:
            return self._doc[page].get_text()
        except Exception:
            return ""

    def fit_width(self) -> str:
        """Pick the zoom step whose rendered width best fits the viewport."""
        if self._doc is None or not self._labels:
            return ""
        try:
            width_pt = self._doc[0].rect.width
        except Exception:
            return ""
        target = max(self.viewport().width() - 40, 200)
        best = min(
            range(len(ZOOM_STEPS)),
            key=lambda i: abs(width_pt * ZOOM_STEPS[i] * BASE_DPI / 72 - target),
        )
        if best != self._zoom_index:
            self._zoom_index = best
            self.load(self._path)
        return f"{int(ZOOM_STEPS[self._zoom_index] * 100)}%"


def make_pdf_pane(parent: QWidget | None = None, palette: dict | None = None):
    """The best PDF pane this installation can manage."""
    return _QtPdfPane(parent, palette) if HAVE_QTPDF else _PixmapPdfPane(parent)


def backend_name() -> str:
    return "Qt PDF" if HAVE_QTPDF else "PyMuPDF"
