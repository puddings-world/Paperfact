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

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from paper_daily.desktop import figure_loading
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
        self.setStyleSheet(f"QScrollArea{{background:{palette['ground']};border:0;}}")
        self._thread: QThread | None = None
        self._running = None
        self._worker = None
        self._disposed = False
        self._context = None
        self._frame = None
        self._pending_scroll = None
        self._lease_pending = self._lease_failed = False
        self._lease_label = None
        self._watch = QTimer(self)
        self._watch.setInterval(50)
        self._watch.timeout.connect(self._check_context)
        self._lifetime = {"worker": None}

        def destroyed(_object=None, state=self._lifetime):
            worker, state["worker"] = state["worker"], None
            if worker is not None:
                worker.cancel()

        self.destroyed.connect(destroyed)
        self._paper_id: str | None = None
        self._requested = None
        self._generation = 0
        self.loaded_document_hash = None
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
    @property
    def busy(self):
        return self._running is not None or self._requested is not None

    def load(self, paper_id: str, pdf_path: Path, has_pdf: bool, *, context=None) -> None:
        if self._disposed:
            return
        key = (paper_id, Path(pdf_path), has_pdf, context)
        if self.busy and key == getattr(self, "_active_key", None):
            return
        self._generation += 1
        self._paper_id, self._context = paper_id, context
        self._frame = self._requested = None
        self._clear()
        self._message("Preparing figures..." if has_pdf else "A local PDF is required for figures.")
        if self._running is not None:
            self._running.cancel()
            if has_pdf:
                self._requested = key
            return
        if has_pdf:
            self._start(key)

    def _start(self, request):
        paper_id, path, has_pdf, context = request
        if self._disposed or (context is not None and not context.current()):
            return
        self._active_key = request
        worker = figure_loading.Worker(paper_id, path, self._generation, context, extract)
        self._launch(worker)

    def _launch(self, worker):
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = self._running = self._worker = worker
        self._lifetime["worker"] = worker
        import weakref

        worker.owner_ref = weakref.ref(self)
        worker.begun.connect(self._begin_owned)
        worker.entry.connect(self._queue_entry)
        worker.finished.connect(self._next_request)
        self._watch.start()
        worker.start()

    def _valid(self, worker):
        try:
            return (
                not self._disposed
                and self._running is worker
                and not worker.stopped.is_set()
                and worker.generation == self._generation
                and worker.paper_id == self._paper_id
                and (worker.context is None or worker.context.current())
            )
        except (OSError, RuntimeError, ValueError):
            return False

    def _begin_owned(self, worker):
        if not self._valid(worker):
            worker.cancel()
            return
        pending = self._pending_scroll
        self._clear()
        self._pending_scroll = pending
        found = worker.figures
        if worker.source is not None:
            digest = worker.source.view.fingerprint
            if any(f.meta.get("document_hash") != digest for f in found):
                worker.cancel()
                self._message("Figure source differs from the open PDF.")
                return
        if not found:
            self._message("No numbered figures or tables were found in this PDF.")
            return
        if worker.source is not None:
            self.loaded_document_hash = worker.source.view.fingerprint
        count = QLabel(
            f"{sum(f.kind == 'figure' for f in found)} figures / "
            f"{sum(f.kind == 'table' for f in found)} tables"
        )
        count.setStyleSheet(f"color:{self.pal['faint']};font-size:11px;")
        self._layout.addWidget(count)
        self._layout.addStretch(1)
        self._entries = [None] * len(found)
        self._toc.setText(toc_html(found, self.pal))
        self._toc.show()
        self._place_toc()

    def _queue_entry(self, row):
        QTimer.singleShot(0, self, lambda: self._insert_entry(row))

    def _insert_entry(self, row):
        worker = row.worker
        try:
            if not self._valid(worker):
                worker.cancel()
                return
            if worker.context is not None and not figure_loading.figures.lease_metadata_current(
                row.proof
            ):
                row.recheck = True
                self._lease_pending = True
                self._notice("Checking the original source...")
                return
            self._lease_pending = False
            self._notice("")
            try:
                asset_current = figure_loading.version(row.figure.path) == row.version
            except (OSError, ValueError):
                asset_current = False
            if not asset_current:
                worker.failed = True
                worker.cancel()
                return
            if row.index >= len(self._entries) or self._entries[row.index] is not None:
                return
            entry = self._entry(row.figure, row.image)
            if not self._valid(worker):
                entry.deleteLater()
                worker.cancel()
                return
            self._entries[row.index] = entry
            self._layout.insertWidget(
                1
                + int(self._lease_label is not None)
                + sum(e is not None for e in self._entries[: row.index]),
                entry,
            )
            entry.show()
            if self._pending_scroll == row.index:
                self._pending_scroll = None
                self.scroll_to(row.index)
        finally:
            row.ack.set()

    def _publish_initial(self, frame):
        if (
            not frame.ready_emitted
            and frame.figures
            and frame.success
            and frame.generation == self._generation
            and (
                frame.context is None
                or (
                    frame.context.current()
                    and figure_loading.figures.lease_metadata_current(frame.proof)
                )
            )
        ):
            frame.ready_emitted = True
            self.ready.emit(frame.paper_id)

    def _notice(self, text, *, retry=False):
        if self._lease_label is None and text:
            self._lease_label = QLabel(self._inner)
            self._lease_label.setWordWrap(True)
            self._lease_label.setStyleSheet(f"color:{self.pal['muted']};font-size:12px;")
            token = self._generation
            self._lease_label.linkActivated.connect(
                lambda _link: self.recheck_source() if token == self._generation else None
            )
            self._layout.insertWidget(0, self._lease_label)
        if self._lease_label is not None:
            self._lease_label.setText(
                text + (" <a href='retry'>Retry source check</a>" if retry else "")
            )
            self._lease_label.setVisible(bool(text))

    def recheck_source(self):
        """Explicit retry or one automatic drift check, on the existing worker lane."""
        frame = self._frame
        if (
            self._disposed
            or self.busy
            or frame is None
            or frame.lease is None
            or frame.generation != self._generation
            or not frame.context.current()
        ):
            return False
        self._lease_failed = False
        self._lease_pending = True
        self._notice("Checking the original source...")
        worker = figure_loading.Worker(
            frame.paper_id, frame.path, self._generation, frame.context, extract, lease=frame.lease
        )
        worker.target_frame = frame
        self._launch(worker)
        return True

    def _next_request(self):
        worker = self._running
        if worker is None:
            return
        if not worker.wait(0):
            QTimer.singleShot(10, self, self._next_request)
            return
        worker._release()
        valid = self._valid(worker)
        self._running = self._worker = None
        self._lifetime["worker"] = None
        need_check = False
        if valid and worker.mode == "check":
            frame = self._frame
            if frame is worker.target_frame and worker.success:
                if figure_loading.figures.lease_metadata_current(worker.proof):
                    frame.proof = worker.proof
                    self._lease_pending = self._lease_failed = False
                    self._notice("")
                    # Only a still-unpublished ORIGINAL extraction can become ready.
                    self._publish_initial(frame)
                else:
                    self._lease_failed = self._lease_pending = True
                    self._notice(
                        "Source verification remained unstable; figures are read-only.", retry=True
                    )
            elif worker.revoked:
                self._frame = None
                self._clear()
                self._message("The original owner or source changed. Open the PDF again.")
            else:
                self._lease_failed = self._lease_pending = True
                self._notice(
                    "Unable to verify the original source; figures are read-only.", retry=True
                )
        elif valid and worker.mode == "extract" and worker.success:
            self._frame = worker
            if worker.context is None or figure_loading.figures.lease_metadata_current(
                worker.proof
            ):
                self._lease_pending = self._lease_failed = False
                self._notice("")
                self._publish_initial(worker)
            else:
                self._lease_pending = True
                need_check = True
        elif not self._disposed and worker.generation == self._generation:
            if worker.revoked or not valid:
                self._frame = None
                self._clear()
                if worker.failed and not worker.revoked:
                    try:
                        current = worker.context is None or worker.context.current()
                    except (OSError, RuntimeError, ValueError):
                        current = False
                    if current:
                        self._message("Unable to prepare figures. Reopen this tab to retry.")
            elif worker.lease is not None and any(e is not None for e in self._entries):
                self._frame = worker
                self._lease_failed = self._lease_pending = True
                self._notice("Preparation stopped; retained figures are read-only.", retry=True)
            else:
                self._clear()
                if worker.failed:
                    self._message("Unable to prepare figures. Reopen this tab to retry.")
        worker.source = None
        if self._requested is not None and not self._disposed:
            request, self._requested = self._requested, None
            self._start(request)
        elif need_check and self._frame is worker and not self._disposed:
            self.recheck_source()
        elif self._frame is None and self._running is None:
            self._watch.stop()

    def invalidate(self):
        self._generation += 1
        self._requested = self._frame = None
        if self._running is not None:
            self._running.cancel()
        self._clear()

    def _check_context(self):
        worker = self._running or self._frame
        if worker is None:
            return
        if self._requested is not None:
            context = self._requested[3]
        elif worker.generation != self._generation and worker.stopped.is_set():
            self._watch.stop()
            return
        else:
            context = worker.context
        try:
            valid = not self._disposed and (context is None or context.current())
        except (OSError, RuntimeError, ValueError):
            valid = False
        if not valid:
            self.invalidate()
            self._watch.stop()
            return
        if context is None or self._requested is not None:
            return
        proof = worker.proof
        if figure_loading.figures.lease_metadata_current(proof):
            if not self._lease_failed:
                self._lease_pending = False
            return
        self._lease_pending = True
        if not self._lease_failed:
            self._notice("Checking the original source...")
            if self._running is None and self._frame is not None:
                self.recheck_source()

    def request_close(self):
        if self.busy:
            self.invalidate()
            return False
        return True

    def dispose(self, *args):
        if self._disposed:
            return
        self._disposed = True
        self._watch.stop()
        self._requested = self._frame = None
        if self._running is not None:
            self._running.cancel()
        elif self._thread is not None:
            self._thread.deleteLater()

    def closeEvent(self, event):
        if not self.request_close():
            event.ignore()
            return
        self.dispose()
        super().closeEvent(event)

    def _clear(self) -> None:
        self.loaded_document_hash = None
        self._entries = []
        self._pending_scroll = None
        self._lease_pending = self._lease_failed = False
        self._lease_label = None
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

    def _show_result(self, paper_id, generation, figures):
        if generation == self._generation:
            self._show(paper_id, figures)

    def _show(self, paper_id: str, figures: list[Figure]) -> None:
        # The reader may have moved on while the extraction was running.
        if paper_id != self._paper_id:
            return
        self._clear()
        from paper_daily.document_reader import document_status

        status = document_status(paper_id)
        if status.status == "ambiguous":
            figures = []
        if status.managed:
            figures = [
                figure
                for figure in figures
                if status.available and figure.meta.get("document_hash") == status.sha256
            ]
            if figures:
                self.loaded_document_hash = status.sha256
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
        if not 0 <= index < len(self._entries):
            worker = self._running
            # Extraction may have finished before its queued GUI initialization.
            # Retain only a selection for this still-current worker's real figures.
            if (not self._entries and worker is not None and worker.mode == "extract"
                    and self._valid(worker) and 0 <= index < len(worker.figures)):
                self._pending_scroll = index
                worker.priority = index
            return
        if self._entries[index] is None:
            self._pending_scroll = index
            if self._running is not None:
                self._running.priority = index
            return
        self._layout.activate()
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

    def _jump(self, figure):
        if self._context is not None:
            try:
                if self._disposed or not self._context.current():
                    return
                worker = self._frame or self._running
                if (
                    self._lease_pending
                    or self._lease_failed
                    or not figure_loading.figures.lease_metadata_current(
                        getattr(worker, "proof", None)
                    )
                ):
                    return
                if (
                    worker is None
                    or worker.generation != self._generation
                    or worker.context is not self._context
                    or worker.stopped.is_set()
                    or not any(item is figure for item in worker.figures)
                ):
                    return
            except (OSError, RuntimeError, ValueError):
                return
        # Navigation targets the PDF actually rendered by the parent reader. A
        # newly desired version must not invalidate the user's still-open version.
        self.loaded_document_hash = figure.meta.get("document_hash")
        self.jump.emit(figure.page, figure.caption)

    def _entry(self, fig: Figure, decoded=None) -> QWidget:
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
        head.linkActivated.connect(lambda _=None, f=fig: self._jump(f))
        layout.addWidget(head)

        image = _ClickableImage()
        image.setCursor(Qt.CursorShape.PointingHandCursor)
        image.setToolTip("點圖跳到原文中的位置")
        image.clicked.connect(lambda f=fig: self._jump(f))
        if decoded is None:
            pixmap = QPixmap(str(fig.path))
            if not pixmap.isNull() and pixmap.width() > MAX_WIDTH:
                pixmap = pixmap.scaledToWidth(MAX_WIDTH, Qt.TransformationMode.SmoothTransformation)
        else:
            pixmap = QPixmap.fromImage(decoded)
        if not pixmap.isNull():
            image.setPixmap(pixmap)
        elif decoded is not None:
            image.setText("Image unavailable; the original caption is preserved.")
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
