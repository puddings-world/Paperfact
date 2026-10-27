"""Version comparison and explicit maintenance actions, without account access."""

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from paper_daily import build_identity


class VersionDialog(QDialog):
    def __init__(self, parent, banner, info, support):
        super().__init__(parent)
        self.setWindowTitle("版本與更新")
        self.resize(520, 280)
        layout = QVBoxLayout(self)
        self.details = QPlainTextEdit(build_identity.describe(info))
        self.details.setReadOnly(True)
        layout.addWidget(self.details)
        self.status = QLabel("更新會顯示在上方公告；儲存完成後才會重啟安裝。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.copy_button = QPushButton("複製版本資訊")
        self.copy_button.clicked.connect(self.copy_info)
        self.check_button = QPushButton("立即檢查更新")
        self.check_button.clicked.connect(lambda: banner.check_in_background(force=True))
        self.support_button = QPushButton("診斷與回報")
        self.support_button.clicked.connect(lambda: (self.close(), support()))
        for button in (self.copy_button, self.check_button, self.support_button):
            row.addWidget(button)
        layout.addLayout(row)
        banner.check_status.connect(self.checked)
        self.check_button.setEnabled(not banner._checking)

    def copy_info(self):
        QApplication.clipboard().setText(self.details.toPlainText())
        self.status.setText("已複製版本與建置資訊，可貼到錯誤回報。")

    def checked(self, busy, message):
        self.check_button.setEnabled(not busy)
        self.status.setText(message)
