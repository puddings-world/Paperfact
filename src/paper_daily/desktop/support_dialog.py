"""Explicit local support export, separate from optional usage feedback."""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from paper_daily import build_identity, diagnostics

ISSUE_URL = "https://github.com/puddings-world/Paperfact/issues/new?template=bug_report.yml"
REPO_URL = "https://github.com/puddings-world/Paperfact"
ORG_URL = "https://github.com/puddings-world"


class SupportDialog(QDialog):
    def __init__(self, parent=None, *, directory=None):
        super().__init__(parent)
        self.setWindowTitle("診斷與回報")
        self.resize(740, 600)
        self.directory = Path(directory) if directory is not None else diagnostics.location()
        self._busy = False
        self._exported = False
        self._opened = set()
        self.report = None
        layout = QVBoxLayout(self)
        notice = QLabel(
            "先預覽，再匯出。報告包含版本、系統、套件版本與錯誤類型／程式位置；"
            "不包含原始錯誤訊息、帳號、問答或論文。\n"
            "不會自動上傳。GitHub 回報是公開的；分享前請確認內容。"
            "這份報告不等於保證完全匿名。"
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("將匯出的診斷 JSON")
        layout.addWidget(self.preview, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.copy_button = QPushButton("複製版本資訊")
        self.copy_button.clicked.connect(self.copy_version)
        self.refresh_button = QPushButton("重新讀取")
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button = QPushButton("匯出診斷包…")
        self.export_button.clicked.connect(self.export_report)
        self.issue_button = QPushButton("開啟 GitHub 回報表單")
        self.issue_button.clicked.connect(lambda: self.open_link(ISSUE_URL))
        for button in (self.copy_button, self.refresh_button,
                       self.export_button, self.issue_button):
            row.addWidget(button)
        layout.addLayout(row)
        support = QHBoxLayout()
        support.addWidget(QLabel("支持開發（自由選擇）："))
        self.repo_button = QPushButton("在 GitHub 查看／Star 專案")
        self.repo_button.clicked.connect(lambda: self.open_link(REPO_URL))
        self.org_button = QPushButton("追蹤作者組織／其他專案")
        self.org_button.clicked.connect(lambda: self.open_link(ORG_URL))
        support.addWidget(self.repo_button)
        support.addWidget(self.org_button)
        layout.addLayout(support)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)
        self.refresh()

    def copy_version(self):
        if self.report is not None:
            QApplication.clipboard().setText(build_identity.describe(self.report["build"]))
            self.status.setText("已複製版本與建置資訊，可貼到回報表單。")

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        try:
            report = diagnostics.collect(self.directory)
            preview = diagnostics.render(report)
        except (OSError, ValueError):
            self.report = None
            self.preview.clear()
            self.status.setText("無法讀取診斷資料。請稍後重新讀取；研究內容不受影響。")
            self.export_button.setEnabled(False)
        else:
            self.report = report
            self.preview.setPlainText(preview)
            self._exported = False
            self.export_button.setEnabled(True)
            self.status.setText("這是將匯出的完整 JSON。沒有錯誤紀錄不代表功能一定正常。")
        finally:
            self._busy = False

    def export_report(self):
        if self._busy or self._exported or self.report is None:
            return
        self._busy = True
        self.export_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, "儲存診斷資料包", "Paperfact-diagnostics.zip", "ZIP (*.zip)"
            )
            if not path or not self.isVisible():
                return
            diagnostics.export(self.report, path)
            self._exported = True
            self.status.setText("已儲存診斷包，沒有上傳。可在回報表單中自行附上。")
        except (OSError, ValueError):
            self.status.setText("匯出失敗。請選擇本機可寫入資料夾及未使用的檔名，再試一次。")
        finally:
            self._busy = False
            self.refresh_button.setEnabled(True)
            self.export_button.setEnabled(not self._exported and self.report is not None)

    def open_link(self, url):
        if self._busy or url in self._opened:
            return
        self._opened.add(url)
        if not QDesktopServices.openUrl(QUrl(url)):
            self._opened.discard(url)
            self.status.setText("無法開啟瀏覽器，可重試或自行開啟：" + url)
        elif url == ISSUE_URL:
            self.status.setText("已開啟公開回報表單。診斷包尚未上傳，請自行檢查並附加。")
        else:
            self.status.setText("已開啟專案頁面。是否登入、追蹤或 Star，由你自行決定。")
