"""Voluntary local collection with review before manual sharing."""

import json
import sqlite3
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)

from paper_daily import feedback, feedback_report
from paper_daily.desktop.settings_style import apply as style_settings


class FeedbackDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        style_settings(self)
        self.setWindowTitle("Paperfact · 使用資料與回饋")
        self.resize(620, 620)
        layout = QVBoxLayout(self)
        info = QLabel(feedback.CONSENT_TEXT)
        info.setWordWrap(True)
        layout.addWidget(info)
        self.enabled = QCheckBox("同意上述內容，啟用本機改善紀錄")
        try:
            self.enabled.setChecked(bool(feedback.consent()))
        except (OSError, sqlite3.Error):
            self.enabled.setChecked(False)
        layout.addWidget(self.enabled)
        self.save = QPushButton("儲存選擇（取消勾選會撤回並清除紀錄）")
        self.save.clicked.connect(self.apply)
        layout.addWidget(self.save)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.report_tabs = QTabWidget()
        self.report_tabs.addTab(self.summary, "統計摘要")
        self.report_tabs.addTab(self.preview, "匯出內容")
        layout.addWidget(self.report_tabs, 1)
        self._reviewed_consent = None
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.refresh = QPushButton("預覽最新資料")
        self.refresh.clicked.connect(self.reload)
        row.addWidget(self.refresh)
        self.export = QPushButton("匯出這份預覽…")
        self.export.clicked.connect(self.export_preview)
        row.addWidget(self.export)
        close = QPushButton("關閉")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        layout.addLayout(row)
        self.reload()

    def reload(self):
        try:
            self._reviewed_consent = feedback.consent()
            report = feedback.export_payload()
            self.preview.setPlainText(
                json.dumps(report, ensure_ascii=False, indent=2)
            )
            self.summary.setPlainText(feedback_report.summary(report))
            self.status.clear()
            self.export.setEnabled(bool(self._reviewed_consent))
        except (OSError, sqlite3.Error, ValueError):
            self.preview.clear()
            self.summary.clear()
            self._reviewed_consent = None
            self.export.setEnabled(False)
            self.status.setText("無法讀取本機紀錄，可稍後重試。")

    def apply(self):
        try:
            feedback.set_consent(self.enabled.isChecked())
        except (OSError, sqlite3.Error):
            self.status.setText("選擇未儲存，請稍後重試。")
            return
        self.reload()

    def export_preview(self):
        try:
            reviewed = self.preview.toPlainText()
            if not self._reviewed_consent or self._reviewed_consent != feedback.consent():
                self.reload()
                self.status.setText("同意狀態已變更，請重新確認預覽。")
                return
        except (OSError, sqlite3.Error, ValueError):
            self.status.setText("無法確認分享設定，未匯出。")
            return
        name, _ = QFileDialog.getSaveFileName(
            self, "匯出改善資料（自行決定是否分享）", "Paperfact-feedback.json", "JSON (*.json)"
        )
        if not name:
            return
        try:
            # Only the reviewed snapshot, never unseen events arriving during export.
            # A native file chooser can stay open while consent is withdrawn elsewhere.
            if self._reviewed_consent != feedback.consent():
                self.reload()
                self.status.setText("同意狀態已變更，未匯出。")
                return
            Path(name).write_text(reviewed, encoding="utf-8")
            self.status.setText("已匯出，尚未傳送。可自行分享這份檔案給開發者。")
        except (OSError, sqlite3.Error):
            self.status.setText("匯出失敗，請選擇可寫入的位置重試。")


class FeedbackConsentDialog(QDialog):
    """Optional invitation, separate from AI login and research-bundle sharing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        style_settings(self)
        self.setWindowTitle("Paperfact · 是否協助改善使用體驗？")
        self.resize(600, 540)
        layout = QVBoxLayout(self)
        heading = QLabel("這是自願選擇，不參與也能使用全部功能。")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.notice = QPlainTextEdit(f"說明版本：{feedback.POLICY}\n\n{feedback.CONSENT_TEXT}")
        self.notice.setReadOnly(True)
        self.notice.setAccessibleName("使用資料告知與同意說明")
        layout.addWidget(self.notice, 1)
        self.enabled = QCheckBox("我已閱讀，並同意啟用上述本機改善紀錄")
        layout.addWidget(self.enabled)
        self.dont_ask = QCheckBox("不再詢問這一版說明（不代表同意）")
        layout.addWidget(self.dont_ask)
        hint = QLabel(
            "尚無自動回傳服務；目前只會保存在你的電腦。\n"
            "可從「使用資料與回饋」隨時撤回、查看或自行匯出。\n"
            "若未選不再詢問，暫不參與後至少 30 天才會再次提醒。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.skip = QPushButton("暫不參與，繼續使用")
        self.skip.clicked.connect(self.reject)
        row.addWidget(self.skip)
        self.agree = QPushButton("同意並繼續")
        self.agree.setEnabled(False)
        self.agree.setProperty("role", "primary")
        self.enabled.toggled.connect(self.agree.setEnabled)
        self.agree.clicked.connect(self.accept)
        row.addWidget(self.agree)
        layout.addLayout(row)
        self._saved = False

    def accept(self):
        if not self.enabled.isChecked() or self._saved:
            return
        try:
            feedback.set_consent(True, dont_ask=self.dont_ask.isChecked())
        except (OSError, sqlite3.Error):
            self.status.setText("同意未儲存，尚未啟用紀錄。可重試，或選暫不參與。")
            return
        self._saved = True
        super().accept()

    def reject(self):
        if not self._saved:
            # A read-only/full disk must not prevent using the reader.
            with suppress(OSError, sqlite3.Error):
                feedback.set_consent(False, dont_ask=self.dont_ask.isChecked())
            self._saved = True
        super().reject()


class FeedbackInvitation(QObject):
    """Application-lifecycle prompt: never starts from a reusable widget constructor."""

    def __init__(self, window):
        super().__init__(window)
        self.dialog = None
        self._shown = False
        QTimer.singleShot(0, self, self.show_if_needed)

    def show_if_needed(self):
        if self._shown or not self.parent().isVisible():
            return
        self._shown = True
        try:
            due = feedback.should_ask()
        except (OSError, sqlite3.Error, ValueError):
            return
        if not due:
            return
        self.dialog = FeedbackConsentDialog(self.parent())
        self.dialog.finished.connect(self._finished)
        self.dialog.open()

    def _finished(self, _result):
        dialog, self.dialog = self.dialog, None
        if dialog is not None:
            dialog.deleteLater()
