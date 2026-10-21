"""First-use acknowledgement with a separate, unchecked analytics choice."""

import sqlite3

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from paper_daily import feedback, onboarding
from paper_daily.desktop.settings_style import apply as style_settings


class UsageDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        style_settings(self)
        self.setWindowTitle("歡迎使用 Paperfact")
        self.resize(620, 680)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("開始之前，請確認使用說明"))
        self.notice = QPlainTextEdit(onboarding.TEXT)
        self.notice.setReadOnly(True)
        layout.addWidget(self.notice)
        self.required = QCheckBox("我已閱讀並同意使用說明（必要）")
        layout.addWidget(self.required)
        info = QLabel(feedback.CONSENT_TEXT)
        info.setWordWrap(True)
        layout.addWidget(info)
        self.analytics = QCheckBox("願意提供改善統計（選填，可隨時撤回）")
        layout.addWidget(self.analytics)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        leave = QPushButton("離開")
        leave.clicked.connect(self.reject)
        buttons.addWidget(leave)
        self.start = QPushButton("開始使用")
        self.start.setProperty("role", "primary")
        self.start.setEnabled(False)
        self.required.toggled.connect(self.start.setEnabled)
        self.start.clicked.connect(self.accept)
        buttons.addWidget(self.start)
        layout.addLayout(buttons)
        self._saved = False

    def accept(self):
        if not self.required.isChecked() or self._saved:
            return
        try:
            onboarding.accept(analytics=self.analytics.isChecked())
        except (OSError, sqlite3.Error):
            self.status.setText("選擇未儲存，請確認資料夾可寫入後重試。")
            return
        self._saved = True
        super().accept()


def ensure_accepted(show=None):
    try:
        if onboarding.accepted():
            return True
    except (OSError, sqlite3.Error):
        pass
    dialog = UsageDialog()
    if show is not None:
        QTimer.singleShot(0, dialog, lambda: show(dialog))
    return dialog.exec() == QDialog.DialogCode.Accepted
