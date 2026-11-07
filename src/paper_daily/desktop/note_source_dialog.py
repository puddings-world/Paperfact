"""Explicit native PDF and passage choice for a preserved rich-note draft."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
)

WORDS = {
    "en": {
        "title": "Confirm original and position",
        "load_reference": "Inspect saved original",
        "recorded_ref": "Original recorded by the draft",
        "reviewed_ref": "Original selected in this review",
        "current_ref": "Original currently open in the reader",
        "pick": "Choose PDF…",
        "recorded": "Original recorded by the old draft: {source}",
        "unknown": "unknown",
        "selected": "Selected PDF: {source}",
        "help": (
            "Choose the original, then select words in the text pane. The note keeps your "
            "interpretation separately from this quoted passage. "
            "The current reader stays unchanged."
        ),
        "page": "Page",
        "use": "Use selected passage",
        "clear": "Make a plain note without position",
        "cancel": "Cancel",
        "busy": "Checking original…",
        "closing": "Cancelling…",
        "quote": "Passage to associate with this note",
        "text": "Select original words",
        "plain": (
            "The note will have no source association or page position; "
            "its old record is preserved."
        ),
    },
    "zh-TW": {
        "title": "確認原文與位置",
        "load_reference": "檢查已保存原文",
        "recorded_ref": "原稿記錄的原文",
        "reviewed_ref": "本次審閱選定的原文",
        "current_ref": "目前閱讀中的原文",
        "pick": "選擇 PDF…",
        "recorded": "舊稿當時記錄的原文：{source}",
        "unknown": "未知",
        "selected": "這次選定的 PDF：{source}",
        "help": (
            "選擇原文後，在文字區選取段落。筆記中的人工解讀與選取的原文分開保存；"
            "目前閱讀中的 PDF 不會被替換。"
        ),
        "page": "頁碼",
        "use": "使用選取段落",
        "clear": "改為無來源位置的手動筆記",
        "cancel": "取消",
        "busy": "正在核對原文…",
        "closing": "正在取消…",
        "quote": "這次要關聯的原文段落",
        "text": "選取原文文字",
        "plain": "筆記將不再關聯來源或頁碼；舊稿及其原始位置仍會保留。",
    },
}


def selectable_text(words):
    """Qt cursor offsets are UTF-16 units; PDF anchors use raw word indices."""
    chunks, spans, offset = [], [], 0
    previous = -1
    for item in words:
        order, text = item["order"], item["text"]
        if type(order) is not int or order <= previous or not isinstance(text, str):
            raise ValueError("Invalid indexed source words")
        previous = order
        if chunks:
            offset += 1
        start = offset
        offset += len(text.encode("utf-16-le")) // 2
        chunks.append(text)
        spans.append((start, offset, order))
    return " ".join(chunks), spans


def selected_words(page, spans, start, end):
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        return None, ""
    selected = [i for i, (left, right, _order) in enumerate(spans) if left < end and right > start]
    if not selected:
        return None, ""
    first, last = selected[0], selected[-1]
    anchor = dict(
        p0=page["page"],
        o0=spans[first][2],
        p1=page["page"],
        o1=spans[last][2],
        document_hash=page["document_hash"],
    )
    quote = " ".join(word["text"] for word in page["words"][first : last + 1])
    return anchor, quote


def rendered_page(inspected, index):
    import pymupdf

    with pymupdf.open(stream=inspected.content, filetype="pdf") as document:
        page = document[index]
        scale = min(2.0, 1100 / max(page.rect.width, page.rect.height))
        return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")


class PagePreview(QLabel):
    """Fit the immutable page width; never center-crop its first words."""

    def __init__(self):
        super().__init__()
        self.original = None
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    def set_source(self, pixmap):
        self.original = pixmap
        self._fit()

    def _fit(self):
        if self.original is not None:
            fitted = self.original.scaledToWidth(
                max(1, self.width()), Qt.TransformationMode.SmoothTransformation
            )
            self.setPixmap(fitted)
            self.setMinimumHeight(fitted.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def clear(self):
        self.original = None
        self.setMinimumHeight(1)
        super().clear()


class NoteSourceDialog(QDialog):
    def __init__(self, service, preview, parent=None, *, language="en"):
        super().__init__(parent)
        self.service, self.preview = service, preview
        self.words = WORDS.get(language, WORDS["en"])
        self.result_preview = self.inspected = self.page_data = self.anchor = None
        self.spans = []
        self.future = None
        self.closing = self.disposed = False
        self.cancelled = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="note-source-choice")
        self.setWindowTitle(self.words["title"])
        self.resize(1060, 730)
        self.setMinimumSize(700, 440)
        layout = QVBoxLayout(self)
        help_text = QLabel(self.words["help"])
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        choice = preview.data["expected"].get("source_choice")
        recorded = choice["recorded_source"] if choice else preview.data["source_hash"]
        self.recorded = QLabel(
            self.words["recorded"].format(source=recorded or self.words["unknown"])
        )
        self.recorded.setTextFormat(Qt.TextFormat.PlainText)
        self.recorded.setWordWrap(True)
        layout.addWidget(self.recorded)
        self.chosen = QLabel()
        self.chosen.setTextFormat(Qt.TextFormat.PlainText)
        self.chosen.setWordWrap(True)
        layout.addWidget(self.chosen)
        saved = QHBoxLayout()
        self.references = QComboBox()
        self.references.setAccessibleName(self.words["load_reference"])
        for item in service.note_source_references(preview):
            ref = {key: item[key] for key in ("kind", "document_hash")}
            self.references.addItem(
                self.words[ref["kind"] + "_ref"] + " · " + ref["document_hash"][:12], ref
            )
        self.load_reference = QPushButton(self.words["load_reference"])
        self.load_reference.setAutoDefault(False)
        self.load_reference.clicked.connect(self._load_reference)
        saved.addWidget(self.references, 1)
        saved.addWidget(self.load_reference)
        layout.addLayout(saved)
        row = QHBoxLayout()
        self.pick = QPushButton(self.words["pick"])
        self.pick.clicked.connect(self._pick)
        row.addWidget(self.pick)
        row.addStretch()
        row.addWidget(QLabel(self.words["page"]))
        self.page = QSpinBox()
        self.page.setRange(1, 1)
        self.page.setAccessibleName(self.words["page"])
        self.page.valueChanged.connect(self._page)
        row.addWidget(self.page)
        layout.addLayout(row)
        self.image = PagePreview()
        scroll = QScrollArea()
        scroll.setWidget(self.image)
        scroll.setWidgetResizable(True)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setAccessibleName(self.words["text"])
        self.text.selectionChanged.connect(self._selection)
        split = QSplitter()
        split.addWidget(scroll)
        split.addWidget(self.text)
        split.setSizes([520, 480])
        layout.addWidget(split, 1)
        self.quote = QPlainTextEdit()
        self.quote.setReadOnly(True)
        self.quote.setAccessibleName(self.words["quote"])
        self.quote.setPlaceholderText(self.words["quote"])
        self.quote.setMaximumHeight(88)
        layout.addWidget(self.quote)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.use = QPushButton(self.words["use"])
        self.use.clicked.connect(self._use)
        self.clear = QPushButton(self.words["clear"])
        self.clear.setToolTip(self.words["plain"])
        self.clear.clicked.connect(self._clear)
        self.cancel = QPushButton(self.words["cancel"])
        self.cancel.clicked.connect(self.reject)
        for button in (self.pick, self.use, self.clear, self.cancel):
            button.setAutoDefault(False)
        for button in (self.use, self.clear, self.cancel):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.poll = QTimer(self)
        self.poll.setInterval(25)
        self.poll.timeout.connect(self._poll)
        self.poll.start()
        self._controls()

    def _controls(self):
        idle = self.future is None and not self.closing and not self.disposed
        self.pick.setEnabled(idle)
        self.references.setEnabled(idle and self.references.count() > 0)
        self.load_reference.setEnabled(idle and self.references.count() > 0)
        self.page.setEnabled(idle and self.inspected is not None)
        self.clear.setEnabled(idle)
        self.use.setEnabled(idle and self.anchor is not None)

    def _start(self, call, callback):
        if self.future is not None or self.closing or self.disposed:
            return
        self.future = (self.executor.submit(call), callback)
        self.status.setText(self.words["busy"])
        self._controls()

    def _poll(self):
        if self.future is None or not self.future[0].done():
            return
        future, callback = self.future
        self.future = None
        try:
            result = future.result()
            if not self.closing:
                callback(result)
        except Exception as error:
            if not self.closing:
                self.status.setText(str(error))
        if self.closing:
            self.done(QDialog.DialogCode.Rejected)
        self._controls()

    def _pick(self):
        if self.future is not None or self.closing:
            return
        filename, _filter = QFileDialog.getOpenFileName(self, self.words["pick"], "", "PDF (*.pdf)")
        if filename:
            self._inspect(
                lambda: self.service.inspect_note_source(
                    self.preview, filename, cancelled=self.cancelled.is_set
                )
            )

    def _load_reference(self):
        if self.future is not None or self.closing or self.references.currentData() is None:
            return
        reference = dict(self.references.currentData())
        self._inspect(
            lambda: self.service.inspect_note_source_reference(
                self.preview, reference, cancelled=self.cancelled.is_set
            )
        )

    def _inspect(self, inspect):
        self.inspected = self.page_data = self.anchor = None
        self.text.clear()
        self.image.clear()
        self.quote.clear()
        self.chosen.clear()

        def prepare():
            source = inspect()
            page = self.service.note_source_page(
                self.preview, source, 0, cancelled=self.cancelled.is_set
            )
            return source, page, rendered_page(source, 0)

        def loaded(result):
            self.inspected, page, image = result
            self.chosen.setText(self.words["selected"].format(source=self.inspected.sha256))
            self.page.blockSignals(True)
            self.page.setRange(1, self.inspected.pages)
            self.page.setValue(1)
            self.page.blockSignals(False)
            self._display(page, image)

        self._start(prepare, loaded)

    def _display(self, page, image):
        self.page_data = page
        self.anchor = None
        text, self.spans = selectable_text(page["words"])
        self.text.setPlainText(text)
        self.quote.clear()
        pixmap = QPixmap()
        if not pixmap.loadFromData(image):
            raise ValueError("The inspected original page could not be displayed")
        # The source image is independently scrollable; text selection remains
        # attached to this exact immutable page rather than a zoomed screen box.
        self.image.set_source(pixmap)
        self.status.clear()

    def _page(self, value):
        if self.inspected is None or self.future is not None:
            return
        source = self.inspected
        self.anchor = self.page_data = None
        self.text.clear()
        self.quote.clear()

        def prepare():
            page = self.service.note_source_page(
                self.preview, source, value - 1, cancelled=self.cancelled.is_set
            )
            return page, rendered_page(source, value - 1)

        self._start(prepare, lambda result: self._display(*result))

    def _selection(self):
        self.anchor = None
        if self.page_data is not None:
            cursor = self.text.textCursor()
            self.anchor, quote = selected_words(
                self.page_data, self.spans, cursor.selectionStart(), cursor.selectionEnd()
            )
            self.quote.setPlainText(quote)
        self._controls()

    def _complete(self, preview):
        self.result_preview = preview
        self.accept()

    def _use(self):
        if self.anchor is None or self.inspected is None:
            return
        source, anchor = self.inspected, dict(self.anchor)
        self._start(
            lambda: self.service.choose_note_source(
                self.preview, source, anchor, cancelled=self.cancelled.is_set
            ),
            self._complete,
        )

    def _clear(self):
        self._start(lambda: self.service.clear_note_position(self.preview), self._complete)

    def done(self, code):
        if self.disposed:
            return
        if self.future is not None:
            self.closing = True
            self.cancelled.set()
            self.status.setText(self.words["closing"])
            self._controls()
            return
        self.disposed = True
        self.poll.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
        super().done(code)

    def closeEvent(self, event):
        self.reject()
        if self.disposed:
            event.accept()
        else:
            event.ignore()
