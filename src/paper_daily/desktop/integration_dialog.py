"""Copy local launch settings or preview and save agent-prepared JSON without AI."""

import json
import uuid

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from paper_daily.config import DATA_DIR
from paper_daily.integration_config import host_config
from paper_daily.local_operations import MAX_BYTES, dispatch


class OperationWorker(QThread):
    def __init__(self, operation, arguments, parent):
        super().__init__(parent)
        self.operation, self.arguments = operation, arguments
        self.response = None

    def run(self):
        try:
            self.response = dispatch(self.operation, self.arguments)
        except Exception:
            self.response = {
                "ok": False,
                "error": {
                    "code": "internal_error",
                    "message": "儲存未完成，請重試；保留同一操作 ID。",
                },
            }


class IntegrationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("本地整合 · 連接專案與 AI agent")
        self.resize(720, 620)
        self.preview_id = None
        self.operation_id = uuid.uuid4().hex
        self.saved = None
        self._worker = None
        layout = QVBoxLayout(self)
        workspace = QLabel("目前資料夾：" + str(DATA_DIR.resolve()))
        workspace.setWordWrap(True)
        workspace.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(workspace)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        connect_page = QWidget()
        connection = QVBoxLayout(connect_page)
        info = QLabel(
            "把下方設定加入支援 mcpServers 格式的 agent。其他客戶端使用相同的 command / args。\n"
            "由 agent 啟動本機程序；不用開公開連接埠，也不用一直開著 Paperfact。\n"
            "可讀取清單與論文標題、加入清單；傳回的資料可能進入你所用 AI 的對話。"
        )
        info.setWordWrap(True)
        connection.addWidget(info)
        self.config = QPlainTextEdit(json.dumps(host_config(), ensure_ascii=False, indent=2))
        self.config.setReadOnly(True)
        connection.addWidget(self.config)
        copy = QPushButton("複製 MCP 連線設定")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.config.toPlainText()))
        connection.addWidget(copy)
        tabs.addTab(connect_page, "連接 agent")
        import_page = QWidget()
        importing = QVBoxLayout(import_page)
        hint = QLabel(
            "貼上其他 agent 整理的 JSON，預覽並勾選後儲存；不使用 AI。\n"
            "這是論文清單匯入；包含 PDF 與筆記的 ZIP 仍從「研究資料」匯入。"
        )
        hint.setWordWrap(True)
        importing.addWidget(hint)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText(
            '{"name":"我的研究清單","papers":[{"title":"論文標題",'
            '"doi":"10.1234/example","url":"https://example.org/paper"}]}'
        )
        self.input.setMaximumHeight(150)
        self.input.textChanged.connect(self.invalidate)
        importing.addWidget(self.input)
        self.items = QListWidget()
        importing.addWidget(self.items)
        actions = QHBoxLayout()
        self.preview_button = QPushButton("預覽 JSON")
        self.preview_button.clicked.connect(self.propose)
        self.save_button = QPushButton("儲存勾選論文")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.commit)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.save_button)
        importing.addLayout(actions)
        tabs.addTab(import_page, "匯入 agent 整理的清單")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close = QPushButton("關閉")
        close.clicked.connect(self.reject)
        layout.addWidget(close)

    def _run(self, operation, arguments, callback):
        if self._worker is not None:
            return
        worker = OperationWorker(operation, arguments, self)
        self._worker = worker
        for widget in (self.preview_button, self.save_button, self.input, self.items):
            widget.setEnabled(False)
        self.status.setText("正在處理本機清單…")

        def finished():
            self._worker = None
            for widget in (self.preview_button, self.input, self.items):
                widget.setEnabled(True)
            self.save_button.setEnabled(bool(self.preview_id))
            callback(worker.response)
            worker.deleteLater()

        worker.finished.connect(finished)
        worker.start()

    def invalidate(self):
        if self.preview_id:
            dispatch("imports.discard", {"preview_id": self.preview_id})
        self.preview_id = None
        self.operation_id = uuid.uuid4().hex
        self.items.clear()
        self.save_button.setEnabled(False)

    def propose(self):
        if self.saved or self._worker is not None:
            return
        self.invalidate()
        try:
            raw = self.input.toPlainText()
            if len(raw.encode("utf-8")) > MAX_BYTES:
                raise ValueError("JSON 太大，請拆成較小清單。")
            args = json.loads(raw)
            self._run("imports.propose", args, self._proposed)
        except ValueError:
            self.status.setText("請貼上有效的 JSON 物件（最多 2 MB）。")
            return

    def _proposed(self, response):
        if not response["ok"]:
            self.status.setText(response["error"]["message"])
            return
        value = response["result"]
        self.preview_id = value["preview_id"]
        for candidate in value["items"]:
            text = candidate["title"]
            if candidate["identity_matches"]:
                text += " · 已有相同 DOI / arXiv"
            if candidate["warning"]:
                warnings = {
                    "Conflicting identities: resolve before saving": "識別碼衝突，請先核對再儲存",
                    "Title match requires explicit reuse": "已有同名論文，未確認身分時會分開儲存",
                    "No identifiers; title is not proof of identity": (
                        "沒有 DOI / arXiv，僅憑標題不會合併"
                    ),
                }
                text += "\n" + warnings.get(candidate["warning"], candidate["warning"])
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, candidate["candidate_id"])
            item.setCheckState(Qt.CheckState.Checked)
            self.items.addItem(item)
        self.save_button.setEnabled(True)
        self.status.setText("請核對候選論文。同名但無識別碼的項目會分開保存；不覆蓋既有筆記。")

    def commit(self):
        if not self.preview_id or self.saved or self._worker is not None:
            return
        selected = [
            self.items.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.items.count())
            if self.items.item(i).checkState() == Qt.CheckState.Checked
        ]
        if not selected:
            self.status.setText("請至少勾選一篇論文；尚未儲存清單。")
            return
        self._run(
            "imports.commit",
            dict(preview_id=self.preview_id, operation_id=self.operation_id, selected=selected),
            self._committed,
        )

    def _committed(self, response):
        if not response["ok"]:
            self.status.setText(response["error"]["message"])
            return
        self.saved = response["result"]
        self.status.setText(f"已儲存 {self.saved['added']} 篇。清單總覽會自動更新。")
        for widget in (self.save_button, self.preview_button, self.input, self.items):
            widget.setEnabled(False)

    def reject(self):
        if self._worker is not None:
            self.status.setText("清單操作即將完成，請完成後再關閉；不會重複儲存。")
            return
        if self.preview_id:
            dispatch("imports.discard", {"preview_id": self.preview_id})
        super().reject()

    def closeEvent(self, event):
        if self._worker is not None:
            event.ignore()
            self.reject()
        else:
            self.reject()
            event.accept()
