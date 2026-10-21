"""The 講稿 view: the speaker script as a page you write on.

A bare full-width text box read as a log field, not as something to edit: lines ran
the whole window and nothing said how long the script would take to say. Here the
text sits on a centred page of reading width with document spacing, and the line
above it gives the length in characters and speaking time against the deck's
per-slide budget.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget

from paper_daily.desktop import fonts

PAGE_WIDTH = 720
# Typical presenting pace: Mandarin about 250 characters a minute, English about
# 150 words.
CJK_PER_MINUTE = 250
WORDS_PER_MINUTE = 150
_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_WORD = re.compile(r"[A-Za-z0-9]+(?:['.\-][A-Za-z0-9]+)*")


def speaking_seconds(text: str) -> int:
    cjk = len(_CJK.findall(text))
    words = len(_WORD.findall(text))
    return round(cjk * 60 / CJK_PER_MINUTE + words * 60 / WORDS_PER_MINUTE)


def _duration(seconds: int) -> str:
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} 分 {rest} 秒" if minutes else f"{rest} 秒"


def length_label(text: str, budget: int | None = None) -> str:
    """'412 字 · 約 1 分 39 秒 · 每頁目標 1 分 0 秒'; budget is seconds per slide."""
    count = len(_CJK.findall(text)) + len(_WORD.findall(text))
    label = f"{count} 字 · 約 {_duration(speaking_seconds(text))}"
    if budget:
        label += f" · 每頁目標 {_duration(budget)}"
    return label


class ScriptEditor(QTextEdit):
    """Plain text in, plain text out; only the presentation is a document's."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("script")
        self.setAcceptRichText(False)
        self.setFont(fonts.font(fonts.SANS, pixels=16))
        self.document().setDocumentMargin(44)
        self.setStyleSheet("QTextEdit#script { background: #e9edf3; border: none; }")
        self.viewport().setStyleSheet("background: #ffffff;")
        self.textChanged.connect(self._space_new_blocks)

    def setPlainText(self, text: str) -> None:
        super().setPlainText(text)
        self._space(QTextCursor(self.document()), whole=True)
        # Spacing a loaded script is not an edit the reader can undo.
        self.document().clearUndoRedoStacks()

    def _space(self, cursor: QTextCursor, whole: bool = False) -> None:
        block = QTextBlockFormat()
        block.setLineHeight(155, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        block.setBottomMargin(10)
        if whole:
            cursor.select(QTextCursor.SelectionType.Document)
        self.blockSignals(True)
        cursor.mergeBlockFormat(block)
        self.blockSignals(False)

    def _space_new_blocks(self) -> None:
        # Pasted paragraphs arrive without the page's spacing.
        if any(b.blockFormat().lineHeight() != 155 for b in _blocks(self.document())):
            self._space(QTextCursor(self.document()), whole=True)

    def resizeEvent(self, event) -> None:
        side = max(0, (self.width() - PAGE_WIDTH) // 2)
        self.setViewportMargins(side, 12, side, 0)
        super().resizeEvent(event)


def _blocks(document):
    block = document.begin()
    while block.isValid():
        yield block
        block = block.next()


class ScriptPage(QWidget):
    """The editor with its length line; focus goes straight to the text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("scriptPage")
        self.setStyleSheet(
            "#scriptPage { background: #e9edf3; } #scriptPage QLabel { color: #52657d; }"
        )
        self.editor = ScriptEditor()
        self.meta = QLabel()
        self.meta.setContentsMargins(0, 8, 0, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.meta, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.editor, 1)
        self.setFocusProxy(self.editor)
