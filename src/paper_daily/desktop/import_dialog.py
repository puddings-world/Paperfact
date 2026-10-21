"""Create a list without exposing command-line tools or connection details."""

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from paper_daily import list_create
from paper_daily.desktop.ai_access import requires_ai
from paper_daily.desktop.ask import AskRunner


class ImportListDialog(QDialog):
    progress = Signal(str)

    def __init__(self, palette, repo_root, parent=None):
        super().__init__(parent)
        self.imported = False
        self.list_id = None
        self.runner = AskRunner(self)
        self.setWindowTitle("建立閱讀清單")
        self.resize(700, 520)
        layout = QVBoxLayout(self)
        self.mode = QComboBox()
        for text, key in (
            ("貼上參考文獻", "references"),
            ("描述研究主題", "topic"),
            ("建立空白清單", "empty"),
        ):
            self.mode.addItem(text, key)
        layout.addWidget(self.mode)
        self.name = QLineEdit()
        self.name.setPlaceholderText("清單名稱")
        layout.addWidget(self.name)
        self.body = QPlainTextEdit()
        layout.addWidget(self.body, 1)
        self.help = QLabel("AI 建立需要登入帳號；空白清單與匯入研究資料包不需要 AI。")
        self.help.setWordWrap(True)
        layout.addWidget(self.help)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress.connect(self.status.setText)
        self.go = QPushButton("建立清單")
        self.go.clicked.connect(self._start)
        layout.addWidget(self.go)
        self.close_btn = QPushButton("關閉")
        self.close_btn.clicked.connect(self.reject)
        layout.addWidget(self.close_btn)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def _mode_changed(self):
        mode = self.mode.currentData()
        self.body.setVisible(mode != "empty")
        self.body.setPlaceholderText(
            "例如：我研究臨床手術影片理解，想先讀基礎方法，再看近三年的評測與限制。"
            if mode == "topic"
            else "直接貼上參考文獻、論文名稱或從 PDF 複製的清單，不必整理格式。"
        )

    def _start(self):
        if self.runner.busy:
            return
        if self.imported:
            self.accept()
            return
        if not self.name.text().strip():
            self.status.setText("請先輸入清單名稱。")
            return
        if self.mode.currentData() != "empty" and not self.body.toPlainText().strip():
            self.status.setText("請輸入研究主題或參考文獻。")
            return
        if self.mode.currentData() == "empty":
            self._create()
        else:
            self._create_ai()

    @requires_ai("list_parse")
    def _create_ai(self):
        self._create()

    def _create(self):
        name, raw, mode = self.name.text(), self.body.toPlainText(), self.mode.currentData()
        self.go.setEnabled(False)
        self.mode.setEnabled(False)
        self.status.setText("正在建立清單…")

        def call(_):
            try:
                result = list_create.create(name, raw, mode, self.progress.emit)
                return json.dumps(result), "ok"
            except (ValueError, OSError) as exc:
                return None, str(exc)

        def done(text):
            result = json.loads(text)
            self.list_id, self.imported = result["id"], True
            self.status.setText(
                f"已建立清單，共 {result['added']} 篇。選擇文章後可下載原文或深入分析。"
            )
            self.go.setEnabled(True)
            self.go.setText("開啟清單")

        def failed(reason):
            self.go.setEnabled(True)
            self.mode.setEnabled(True)
            self.status.setText("未完成：" + reason)

        self.runner.start("", done, failed, call=call, task="list_parse")

    def reject(self):
        if self.runner.busy:
            self.status.setText("清單正在建立，完成後即可關閉。")
            return
        super().reject()

    def closeEvent(self, event):
        if self.runner.busy:
            event.ignore()
        else:
            super().closeEvent(event)


def run_import(palette, repo_root, parent=None):
    dialog = ImportListDialog(palette, repo_root, parent)
    dialog.exec()
    return dialog.list_id if dialog.imported else None
