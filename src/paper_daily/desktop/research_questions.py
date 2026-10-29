"""Browse grounded suggestions separately from the conversation; selection drafts only."""

import json

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from paper_daily import research_questions
from paper_daily.desktop.ask import AskRunner


class _QuestionBrowser(QDialog):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        split = getattr(self, "split", None)
        if split is not None:
            split.setOrientation(Qt.Orientation.Vertical if self.width() < 720
                                 else Qt.Orientation.Horizontal)


class _QuestionStatus(QLabel):
    """Keep diagnostics available without expanding the conversation layout."""

    def __init__(self, text):
        super().__init__(text)
        self.setMaximumHeight(40)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)


class _QuestionDetails(QScrollArea):
    def minimumSizeHint(self):
        return QSize(0, 32)


def _retry_hint(reason, kept=False):
    state = "本文建議未更新，保留先前建議" if kept else "本文建議未產生"
    return f"{state}：{reason.rstrip('。')}。可按「AI 更新建議」重試。"


def question_preview(question):
    """A bounded navigation label; the full question is always in the preview."""
    text = " ".join(question.split())
    return text if len(text) <= 64 else text[:63] + "…"


class ResearchQuestions(QWidget):
    chosen = Signal(str)
    return_to_draft = Signal()
    source_requested = Signal(dict)

    def __init__(self, parent=None, *, palette=None):
        super().__init__(parent)
        self.paper_id = None
        self.runner = AskRunner(self)
        self.runner.activity_label = "整理研究問題"
        self._attempted = set()
        self._browser_paper = None
        self._switching_paper = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.browse = QPushButton("瀏覽本文建議（0）")
        self.browse.setToolTip("根據這篇論文產生的問題；與下方已送出的對話分開。")
        self.browse.clicked.connect(self.open_browser)
        row.addWidget(self.browse)
        self.refresh_button = QPushButton("AI 更新建議")
        if palette:
            from paper_daily.desktop import ai_style
            ai_style.mark(self.refresh_button, palette)
        self.refresh_button.clicked.connect(lambda: self.generate(force=True))
        row.addWidget(self.refresh_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.status = _QuestionStatus("選擇建議只會帶入草稿；按「送出」才會詢問 AI。")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)

        self.browser = _QuestionBrowser(self)
        self.browser.rejected.connect(self._dismissed)
        self.browser.setWindowTitle("本文建議問題 · 選擇後可編輯")
        self.browser.setWindowModality(Qt.WindowModality.WindowModal)
        self.browser.resize(940, 580)
        browser_layout = QVBoxLayout(self.browser)
        hint = QLabel("這些是根據原文產生的提問建議，不是已送出的對話。"
                      "先選題、讀完整內容，再帶入草稿。")
        hint.setWordWrap(True)
        browser_layout.addWidget(hint)
        self.browser.split = QSplitter(Qt.Orientation.Horizontal)
        self.picker = QListWidget()
        self.picker.setAccessibleName("本文建議問題清單")
        self.picker.setWordWrap(True)
        self.picker.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.picker.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.picker.setMinimumWidth(0)
        self.picker.currentRowChanged.connect(self._selected)
        self.browser.split.addWidget(self.picker)
        self.details_scroll = _QuestionDetails()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details_scroll.setAccessibleName("完整問題與提問理由")
        details = QWidget()
        details_layout = QVBoxLayout(details)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                           | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        details_layout.addWidget(self.detail)
        self.source = QPushButton("在原文中查看依據")
        self.source.clicked.connect(self._source)
        details_layout.addWidget(self.source)
        details_layout.addStretch(1)
        self.details_scroll.setWidget(details)
        self.browser.split.addWidget(self.details_scroll)
        self.browser.split.setChildrenCollapsible(False)
        self.browser.split.setSizes([300, 600])
        browser_layout.addWidget(self.browser.split, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel = QPushButton("返回對話")
        self.cancel.clicked.connect(self.browser.reject)
        buttons.addWidget(self.cancel)
        self.insert = QPushButton("帶入提問草稿")
        self.insert.setDefault(True)
        self.insert.clicked.connect(self._insert)
        buttons.addWidget(self.insert)
        browser_layout.addLayout(buttons)
        self._fill([])

    def load(self, paper_id):
        if paper_id != self.paper_id and self.browser.isVisible():
            self._switching_paper = True
            try:
                self.browser.reject()
            finally:
                self._switching_paper = False
        self.paper_id = paper_id
        saved = research_questions.cached(paper_id)
        self._fill(saved.get("items", []))
        if self.picker.count():
            self.status.setText("已保存本文建議；選擇後可編輯，送出才會詢問 AI。")
        elif saved.get("reason"):
            self.status.setText(_retry_hint(saved["reason"]))
        else:
            self.status.setText("完成深入分析後，這裡會提供本文專屬的提問建議。")
        if self.isVisible():
            QTimer.singleShot(0, self.generate)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.generate)

    def open_browser(self):
        if self.browser.isVisible():
            self.browser.raise_()
            return
        self._browser_paper = self.paper_id
        screen = self.screen()
        if screen:
            area = screen.availableGeometry()
            self.browser.resize(min(940, max(320, area.width() - 80)),
                                min(580, max(300, area.height() - 80)))
        self.browser.open()
        self.picker.setFocus()

    def _dismissed(self):
        if not self._switching_paper and self._browser_paper == self.paper_id:
            self.return_to_draft.emit()

    def _item(self):
        item = self.picker.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _fill(self, items):
        selected = self._item()
        self.picker.clear()
        index = 0
        for number, item in enumerate(items):
            entry = QListWidgetItem(f"{number + 1}. {question_preview(item['question'])}")
            entry.setData(Qt.ItemDataRole.UserRole, item)
            entry.setToolTip(item["question"])
            entry.setSizeHint(QSize(240, self.picker.fontMetrics().lineSpacing() * 3 + 16))
            self.picker.addItem(entry)
            if selected and item["question"] == selected["question"]:
                index = number
        self.picker.setCurrentRow(index if items else -1)
        self.browse.setText(f"瀏覽本文建議（{len(items)}）")
        self._selected()

    def _selected(self, _index=0):
        item = self._item()
        self.insert.setEnabled(bool(item))
        self.source.setVisible(bool(item and item.get("page")))
        self.detail.setText(
            f"問題\n{item['question']}\n\n為什麼值得問\n{item['why']}"
            f"\n\n原文依據 · 第 {item.get('page', '?')} 頁\n{item['evidence']}"
            if item else "目前沒有本文建議。你仍可直接在底部輸入自己的問題。"
        )
        self.details_scroll.verticalScrollBar().setValue(0)

    def _insert(self):
        if self.browser.isVisible() and self._browser_paper != self.paper_id:
            self.browser.reject()
            return
        item = self._item()
        if item:
            self.browser.accept()
            self.chosen.emit(item["question"])

    def _source(self):
        item = self._item()
        if item:
            self.browser.accept()
            self.source_requested.emit(dict(kind="original", page=item["page"],
                                            text=item["evidence"]))

    def generate(self, *, force=False):
        pid = self.paper_id
        if not pid or (not force and pid in self._attempted):
            return
        if self.runner.busy:
            QTimer.singleShot(
                200, self, lambda: self.generate(force=force) if self.isVisible() else None
            )
            return
        self._attempted.add(pid)
        self.refresh_button.setEnabled(False)
        self.status.setText("正在準備本文候選問題（使用論文問答的 AI）…")

        def call(_prompt):
            result, reason = research_questions.ensure(pid, force=force)
            return json.dumps(result, ensure_ascii=False) if result else None, reason

        def finish(value=None, reason=""):
            self.refresh_button.setEnabled(True)
            if self.paper_id != pid:
                return
            if value:
                self._fill(json.loads(value)["items"])
                self.status.setText("本文建議已更新；瀏覽並選擇後可編輯，送出才會詢問 AI。")
            elif research_questions.cached(pid).get("reason"):
                # A failure the cache now holds is not retried on its own.
                self.status.setText(_retry_hint(reason, kept=bool(self.picker.count())))
            else:
                self.status.setText(reason)

        self.runner.start(
            "", lambda value: finish(value=value), lambda why: finish(reason=why), call=call
        )
