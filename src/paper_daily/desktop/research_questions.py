"""Saved paper-specific questions; selecting one prepares a draft, never sends it."""

import json

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from paper_daily import research_questions
from paper_daily.desktop.ask import AskRunner


class ResearchQuestions(QWidget):
    chosen = Signal(str)
    source_requested = Signal(dict)

    def __init__(self, parent=None, *, palette=None):
        super().__init__(parent)
        self.paper_id = None
        self.runner = AskRunner(self)
        self.runner.activity_label = "整理研究問題"
        self._attempted = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("本文研究問題 · 根據原文與深入分析"))
        row = QHBoxLayout()
        self.picker = QComboBox()
        self.picker.setMinimumContentsLength(25)
        self.picker.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.picker.currentIndexChanged.connect(self._selected)
        row.addWidget(self.picker, 1)
        self.insert = QPushButton("帶入提問")
        self.insert.clicked.connect(self._insert)
        row.addWidget(self.insert)
        self.refresh_button = QPushButton("AI 更新問題")
        if palette:
            from paper_daily.desktop import ai_style

            ai_style.mark(self.refresh_button, palette)
        self.refresh_button.clicked.connect(lambda: self.generate(force=True))
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.source = QPushButton("核對原文依據")
        self.source.clicked.connect(self._source)
        layout.addWidget(self.source)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def load(self, paper_id):
        self.paper_id = paper_id
        self._fill(research_questions.cached(paper_id).get("items", []))
        self.status.setText(
            "已保存的本文問題" if self.picker.count() else "深入分析完成後自動準備候選問題。"
        )
        if self.isVisible():
            QTimer.singleShot(0, self.generate)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.generate)

    def _fill(self, items):
        self.picker.clear()
        for item in items:
            self.picker.addItem(item["question"], item)
        self._selected()

    def _selected(self, _index=0):
        item = self.picker.currentData()
        self.insert.setEnabled(bool(item))
        self.source.setVisible(bool(item and item.get("page")))
        self.detail.setText(f"{item['question']}\n值得問：{item['why']}" if item else "")
        self.detail.setToolTip(item["evidence"] if item else "")

    def _insert(self):
        item = self.picker.currentData()
        if item:
            self.chosen.emit(item["question"])

    def _source(self):
        item = self.picker.currentData()
        if item:
            self.source_requested.emit(
                dict(kind="original", page=item["page"], text=item["evidence"])
            )

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
            self.status.setText(
                "本文研究問題已保存；帶入後可編輯，再按「問」。" if value else reason
            )

        self.runner.start(
            "", lambda value: finish(value=value), lambda why: finish(reason=why), call=call
        )
