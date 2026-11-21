"""One AI settings window: the default, each feature's AI, and agent hosts."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from paper_daily.desktop.settings_style import apply as style_settings

DEFAULT, FEATURES, HOSTS = range(3)


class AgentHostPanel(QWidget):
    """How an agent host reaches Paperfact. It is not a source for the app's buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from paper_daily.config import DATA_DIR
        from paper_daily.integration_config import host_config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        title = QLabel("連接外部 agent")
        title.setStyleSheet("font-size:22px;font-weight:600;")
        layout.addWidget(title)
        for text, muted in (
            (
                "Paperfact 裡的按鈕只使用前兩頁設定的 Claude、Codex 或 API 端點。"
                "這一頁是另一種用法：你在 agy、Claude Code、Codex 等 agent 裡工作時，"
                "讓它讀取你的清單與論文，並用它自己的帳號完成分析後存回 Paperfact。",
                False,
            ),
            (
                "agent 可以做的事：讀清單與論文、加入論文、深入分析、引用分析、回答論文問題、"
                "整理筆記與重點。回答由 agent 自己的模型產生，計入它自己的方案；"
                "Gemini 訂閱只能這樣使用（在 agy 裡）。",
                True,
            ),
            (
                "存回的結果會出現在已開啟的論文中：頁面上方會提示有更新，按「載入已存更新」即可看到。"
                "這裡沒有任何設定會把 app 內的按鈕改由 agent 回答。",
                True,
            ),
        ):
            label = QLabel(text)
            label.setWordWrap(True)
            if muted:
                label.setProperty("role", "muted")
            layout.addWidget(label)
        step = QLabel(
            "連接方式：把下方設定加入 agent 的 MCP 設定（mcpServers 格式；"
            "其他格式使用相同的 command 與 args），然後重新開啟該 agent。"
            "由 agent 啟動本機程序，不開公開連接埠，也不需要一直開著 Paperfact。"
        )
        step.setWordWrap(True)
        layout.addWidget(step)
        self.config = QPlainTextEdit(json.dumps(host_config(), ensure_ascii=False, indent=2))
        self.config.setReadOnly(True)
        self.config.setMinimumHeight(170)
        layout.addWidget(self.config, 1)
        row = QHBoxLayout()
        self.copy_button = QPushButton("複製 MCP 連線設定")
        self.copy_button.clicked.connect(self._copy)
        row.addWidget(self.copy_button)
        self.copied = QLabel()
        self.copied.setProperty("role", "muted")
        row.addWidget(self.copied, 1)
        layout.addLayout(row)
        workspace = QLabel("資料夾：" + str(DATA_DIR.resolve()))
        workspace.setWordWrap(True)
        workspace.setProperty("role", "muted")
        workspace.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(workspace)

    def _copy(self):
        QApplication.clipboard().setText(self.config.toPlainText())
        self.copied.setText("已複製。")


class AISettingsPage(QDialog):
    def __init__(self, parent=None, *, tab=DEFAULT):
        super().__init__(parent)
        from paper_daily.desktop.ai_picker import AIPickerDialog
        from paper_daily.desktop.ai_tasks import AITasksDialog
        from paper_daily.desktop.main import palette

        style_settings(self)
        p = palette()
        self.setStyleSheet(
            self.styleSheet()
            + f"""
            QTabWidget::pane {{ border:1px solid {p["border"]}; border-radius:8px;
                background:{p["ground"]}; top:-1px; }}
            QTabBar::tab {{ color:{p["muted"]}; background:transparent; padding:9px 18px;
                border:0; border-bottom:2px solid transparent; font-size:14px; }}
            QTabBar::tab:selected {{ color:{p["ink"]}; font-weight:600;
                border-bottom:2px solid {p["accent"]}; }}
            QTabBar::tab:hover {{ color:{p["ink"]}; }}
        """
        )
        self.setWindowTitle("Paperfact · AI 設定")
        self.resize(940, 820)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.default = AIPickerDialog(self, show_advanced=False, embedded=True)
        self.features = AITasksDialog(self, embedded=True)
        self.hosts = AgentHostPanel(self)
        self.tabs.addTab(self.default, "全域預設")
        self.tabs.addTab(self.features, "各功能的 AI")
        self.tabs.addTab(self.hosts, "連接外部 agent")
        self.default.saved.connect(self.features.default_changed)
        self.features.default_requested.connect(lambda: self.tabs.setCurrentIndex(DEFAULT))
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.close_button = QPushButton("關閉")
        self.close_button.setMinimumHeight(34)
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.reject)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
        self.tabs.setCurrentIndex(tab)

    def _keep_changes(self):
        """Ask about unsaved feature choices; False means stay open."""
        if not self.features.dirty:
            return True
        self.tabs.setCurrentIndex(FEATURES)
        box = QMessageBox(self)
        box.setWindowTitle("各功能的 AI")
        box.setText("各功能的 AI 有尚未儲存的變更。")
        save = box.addButton("儲存分配", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("不儲存", QMessageBox.ButtonRole.DestructiveRole)
        stay = box.addButton("繼續編輯", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is stay:
            return False
        return box.clickedButton() is not save or self.features.save()

    def reject(self):
        if self.default.auth_runner.busy:
            self.tabs.setCurrentIndex(DEFAULT)
            self.default.notice.setText("正在完成帳號登入，請稍候。")
            return
        if not self._keep_changes():
            return
        self.default.shutdown()
        self.features.shutdown()
        super().reject()
