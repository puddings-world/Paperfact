"""The figures tab: the paper's own graphics, with their captions.

A deep dive keeps saying "Figure 5 shows ..." and the reader has to go hunting for
Figure 5 in a 44-page PDF. These are the authors' own explanatory graphics, which
beats any diagram generated *about* the paper, and having them in a list beside the
explanation is the difference between reading about the evidence and seeing it.

Extraction is a few seconds of PDF work, so it runs on a worker thread the first
time a paper is opened and is cached on disk afterwards.

A figure is also a place in the paper. Clicking one puts the PDF on its page with the
caption highlighted, so the text that discusses it is a scroll away rather than a
search.
"""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from paper_daily.figures import Figure, extract

MAX_WIDTH = 720


def toc_html(figures: list[Figure], pal: dict[str, str]) -> str:
    """One link per figure and table, in the paper's order; the href is its index."""
    links = "&nbsp;&nbsp;·&nbsp;&nbsp;".join(
        f"<a href='{i}' style='color:{pal['accent']};text-decoration:none;'>"
        f"{html.escape(fig.label)}</a>"
        for i, fig in enumerate(figures)
    )
    return f"跳到&nbsp;&nbsp;{links}"


class _ExtractWorker(QObject):
    finished = Signal(str, list)

    def __init__(self, paper_id: str, pdf_path: Path) -> None:
        super().__init__()
        self._paper_id = paper_id
        self._pdf_path = pdf_path

    def run(self) -> None:
        try:
            figures = extract(self._paper_id, self._pdf_path)
        except Exception:
            figures = []
        self.finished.emit(self._paper_id, figures)


class _ClickableImage(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class FigurePane(QScrollArea):
    jump = Signal(int, str)  # 1-based page, caption
    ready = Signal(str)

    def __init__(self, palette: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pal = palette
        self.setWidgetResizable(True)
        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(18, 16, 18, 24)
        self._layout.setSpacing(10)
        self.setWidget(self._inner)
        self.setStyleSheet(
            f"QScrollArea{{background:{palette['ground']};border:0;}}"
        )
        self._thread: QThread | None = None
        self._worker: _ExtractWorker | None = None
        self._paper_id: str | None = None
        self._requested = None
        # The paper's figures by label, pinned above the scrolling list: a paper with
        # twenty of them was a long scroll to find the one the explanation named.
        self._entries: list[QWidget] = []
        self._toc = QLabel(self)
        self._toc.setTextFormat(Qt.TextFormat.RichText)
        self._toc.setWordWrap(True)
        self._toc.setContentsMargins(18, 8, 18, 8)
        self._toc.setStyleSheet(
            f"QLabel{{background:{palette['surface']};color:{palette['faint']};"
            f"border-bottom:1px solid {palette['border']};font-size:12px;}}"
        )
        self._toc.linkActivated.connect(lambda index: self.scroll_to(int(index)))
        self._toc.hide()

    # ---- loading ---------------------------------------------------------
    def load(self, paper_id: str, pdf_path: Path, has_pdf: bool) -> None:
        self._paper_id = paper_id
        self._requested = None
        self._clear()
        if not has_pdf or not pdf_path.exists():
            self._message(
                "需要本機的 PDF 才能抽圖。開啟這篇時會自動下載,抓到之後回到這個分頁就會出現。"
            )
            return
        self._message("正在從 PDF 抽出圖表…")
        if self._thread is not None and self._thread.isRunning():
            self._requested = (paper_id, pdf_path, has_pdf)
            return
        if self._thread is not None:
            # finished can be delivered before native thread-local cleanup ends.
            self._thread.wait()
        self._thread = QThread()
        self._worker = _ExtractWorker(paper_id, pdf_path)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._show)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._next_request)
        self._thread.start()

    def _next_request(self):
        if self._requested:
            self.load(*self._requested)

    def _clear(self) -> None:
        self._entries = []
        self._toc.hide()
        self.setViewportMargins(0, 0, 0, 0)
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _message(self, text: str) -> None:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color:{self.pal['muted']};font-size:13px;")
        self._layout.addWidget(label)
        self._layout.addStretch(1)

    def _show(self, paper_id: str, figures: list[Figure]) -> None:
        # The reader may have moved on while the extraction was running.
        if paper_id != self._paper_id:
            return
        self._clear()
        if not figures:
            self._message(
                "這篇的 PDF 裡找不到帶標號的圖或表。抽圖是靠 "
                "「Figure N:」「Table N:」這種圖說定位的,排版不照這個慣例就抓不到。"
            )
            return

        count = QLabel(
            f"{sum(1 for f in figures if f.kind == 'figure')} 張圖 · "
            f"{sum(1 for f in figures if f.kind == 'table')} 個表 · 直接取自原文"
        )
        count.setStyleSheet(f"color:{self.pal['faint']};font-size:11px;")
        self._layout.addWidget(count)

        for fig in figures:
            entry = self._entry(fig)
            self._entries.append(entry)
            self._layout.addWidget(entry)
        self._layout.addStretch(1)
        self._toc.setText(toc_html(figures, self.pal))
        self._toc.show()
        self._place_toc()
        self.ready.emit(paper_id)

    def scroll_to(self, index: int) -> None:
        """Bring entry `index` to the top of the list, under the contents line."""
        self.verticalScrollBar().setValue(self._entries[index].y())

    def _place_toc(self) -> None:
        if self._toc.isHidden():
            return
        height = self._toc.heightForWidth(self.width())
        self.setViewportMargins(0, height, 0, 0)
        self._toc.setGeometry(0, 0, self.width(), height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_toc()

    def _entry(self, fig: Figure) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(6)

        head = QLabel(
            f"<b>{fig.label}</b>&nbsp;&nbsp;"
            f"<a href='jump' style='color:{self.pal['accent']};text-decoration:none;"
            f"font-weight:400;'>↩ 原文第 {fig.page} 頁</a>"
        )
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setStyleSheet(f"color:{self.pal['accent']};font-size:12px;")
        head.linkActivated.connect(lambda _=None, f=fig: self.jump.emit(f.page, f.caption))
        layout.addWidget(head)

        image = _ClickableImage()
        image.setCursor(Qt.CursorShape.PointingHandCursor)
        image.setToolTip("點圖跳到原文中的位置")
        image.clicked.connect(lambda f=fig: self.jump.emit(f.page, f.caption))
        pixmap = QPixmap(str(fig.path))
        if not pixmap.isNull():
            if pixmap.width() > MAX_WIDTH:
                pixmap = pixmap.scaledToWidth(
                    MAX_WIDTH, Qt.TransformationMode.SmoothTransformation
                )
            image.setPixmap(pixmap)
        image.setStyleSheet("background:#ffffff;")
        image.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(image)

        caption = QLabel(fig.caption)
        caption.setWordWrap(True)
        caption.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        caption.setStyleSheet(f"color:{self.pal['muted']};font-size:12px;")
        layout.addWidget(caption)

        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setStyleSheet(f"color:{self.pal['border']};")
        layout.addWidget(rule)
        return box
