"""Explicit, read-only retained-answer review; no provider calls in this dialog."""

from contextlib import closing
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from paper_daily import research_chat, research_chat_review, store


class ChatReviewDialog(QDialog):
    resume_requested = Signal(str)
    applied = Signal()

    def __init__(self, database, parent=None, *, paper_id=None, request_id=None):
        super().__init__(parent)
        self.setWindowTitle("待完成與保留問答")
        self.resize(760, 620)
        self.review = research_chat_review.ChatReview(database)
        self.path = Path(database).resolve()
        self.preview = None
        self.request_id = str(uuid4())
        self.records = self.review.records(paper_id)
        self.list = QListWidget()
        self.body = QTextEdit()
        self.body.setReadOnly(True)
        self.status = QLabel("選擇問題。開啟或檢視不會呼叫 AI。")
        self.status.setWordWrap(True)
        self.target = QComboBox()
        self.target.addItem("選擇要附加問答的論文…", None)
        for item in self.review.targets():
            self.target.addItem(item["title"] + " · " + item["id"], item["id"])
        self.resume = QPushButton("選擇目前 AI 繼續")
        self.apply = QPushButton("套用保留答案")
        self.open = QPushButton("開啟保留答案檔…")
        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addWidget(self.body, 1)
        layout.addWidget(self.target)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        for button in (self.open, self.resume, self.apply):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.resume.clicked.connect(self._resume)
        self.apply.clicked.connect(self._apply)
        self.open.clicked.connect(self._open)
        self.list.currentRowChanged.connect(self._selected)
        self.target.currentIndexChanged.connect(self._target)
        for record in self.records:
            self._add(record)
        self.resume.setEnabled(False)
        self.apply.setEnabled(False)
        selected = next(
            (i for i, row in enumerate(self.records) if row["request_id"] == request_id), -1
        )
        if selected >= 0:
            self.list.setCurrentRow(selected)

    def _add(self, record):
        import json

        data = json.loads(record["context_json"])
        label = "待繼續" if record["status"] == "prepared" else "保留答案"
        self.list.addItem(label + " · " + data["question"][:100])

    def _current(self):
        row = self.list.currentRow()
        return self.records[row] if 0 <= row < len(self.records) else None

    def _check(self):
        if Path(store.DB_PATH).resolve() != self.path:
            raise ValueError("Research workspace changed")
        with closing(self.review._connect()):
            pass

    def _selected(self, _row):
        import json

        self.preview = None
        self.request_id = str(uuid4())
        self.target.blockSignals(True)
        self.target.setCurrentIndex(0)
        self.target.blockSignals(False)
        self.resume.setEnabled(False)
        self.apply.setEnabled(False)
        record = self._current()
        if record is None:
            return
        try:
            self._check()
            data = json.loads(record["context_json"])
            answer = (
                json.loads(record["answer_json"])["body"] if record["answer_json"] else "尚無答案"
            )
            source = data["document"]["sha256"] if data["document"] else "無 PDF 引用"
            self.body.setPlainText(
                "原問題\n"
                + data["question"]
                + "\n\n保留答案\n"
                + answer
                + "\n\n原始來源 SHA256\n"
                + source
            )
            self.resume.setEnabled(record["status"] == "prepared")
            if record["status"] == "candidate":
                self.preview = self.review.preview(record)
                self._describe()
                if self.review.applied_result(record) is not None:
                    self.apply.setEnabled(False)
                    self.status.setText(
                        "此保留答案已套用，原始內容仍保留。另選目標會附加新的問答副本。"
                    )
            else:
                self.status.setText("繼續前會顯示並確認要使用的 AI；保留原問題與來源。")
        except (OSError, ValueError):
            self.status.setText("原工作區或內容已變動。請重新開啟；保留答案檔可另行選擇目標。")

    def _describe(self):
        data = self.preview.data
        target = data["target"]
        self.apply.setEnabled(target is not None)
        if target is None:
            self.status.setText("原論文位置無法沿用。請明確選擇目標論文，再確認附加為新問答。")
        else:
            self.status.setText(
                "目標："
                + target["parent"]["row"]["title"]
                + (
                    "；補上原問題的答案，保留來源版本。"
                    if target["reuse"]
                    else "；將附加為新問答，保留原始來源標記，不假定來源等同目標 PDF。"
                )
            )

    def _target(self, _index):
        target = self.target.currentData()
        if self.preview is None or target is None:
            return
        try:
            self._check()
            self.preview = self.review.target_preview(self.preview, target)
            self.request_id = str(uuid4())
            self._describe()
        except (OSError, ValueError):
            self.apply.setEnabled(False)
            self.status.setText("選定的目標已變動，請重新開啟檢視。")

    def _resume(self):
        record = self._current()
        if record is None or record["status"] != "prepared":
            return
        try:
            self._check()
            research_chat.load_request(self.path, record["request_id"], resolve_document=False)
        except (OSError, ValueError):
            self.status.setText("原問題或來源已變動，無法直接繼續。")
            return
        self.resume.setEnabled(False)
        self.resume_requested.emit(record["request_id"])
        self.accept()

    def _apply(self):
        if self.preview is None or not self.apply.isEnabled():
            return
        self.apply.setEnabled(False)
        try:
            self._check()
            if self.preview.data["confirmation"]:
                title = self.preview.data["target"]["parent"]["row"]["title"]
                if (
                    QMessageBox.question(
                        self,
                        "確認目標論文",
                        "將原問題與保留答案附加至：\n" + title + "\n不會重新呼叫 AI。",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    != QMessageBox.StandardButton.Yes
                ):
                    self.apply.setEnabled(True)
                    return
            self._check()
            self.review.apply(self.preview, request_id=self.request_id, confirm_target=True)
            self.status.setText("答案已儲存。原始候選內容仍保留；未呼叫 AI。")
            self.applied.emit()
        except Exception:
            self.apply.setEnabled(True)
            self.status.setText("套用失敗或檢視後內容已變動；原答案仍保留。請重新檢視後再決定。")

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(self, "開啟保留答案", "", "QA recovery (*.json)")
        if not path:
            return
        try:
            self._check()
            record = research_chat_review.load_record(path)
            if record["status"] != "candidate":
                raise ValueError("Only retained answers can be imported")
            self.records.append(record)
            self._add(record)
            self.list.setCurrentRow(len(self.records) - 1)
        except (OSError, ValueError):
            self.status.setText("這不是有效的保留答案檔，未變更研究資料。")

    def done(self, result):
        self.review.close()
        super().done(result)

    def closeEvent(self, event):
        self.review.close()
        super().closeEvent(event)
