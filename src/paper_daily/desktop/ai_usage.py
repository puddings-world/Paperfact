"""Read-only account quota snapshots, separate from local request receipts."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from paper_daily import ai_accounts, ai_choices, ai_usage
from paper_daily.desktop.ask import AskRunner
from paper_daily.desktop.settings_style import apply as style_settings


class UsageSummary(QGroupBox):
    """Compact, read-only view; the account picker's worker owns fetching/lifetime."""

    def __init__(self, parent=None):
        super().__init__("方案與用量", parent)
        self.backend = ""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        self.quota_status = QLabel()
        self.quota_status.setWordWrap(True)
        layout.addWidget(self.quota_status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMaximumHeight(300)
        body = QWidget()
        self.windows = QVBoxLayout(body)
        self.windows.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(body)
        layout.addWidget(self.scroll)
        self.local = QLabel()
        self.local.setProperty("role", "muted")
        self.local.setWordWrap(True)
        layout.addWidget(self.local)
        scope = QLabel("本機紀錄只計此連線在 Paperfact 的呼叫，不代表方案剩餘額度。")
        scope.setProperty("role", "muted")
        scope.setWordWrap(True)
        scope.setToolTip(
            "近 7 天；舊版未標示連線的紀錄不計入。Token 未回報不代表零用量。"
            "使用本機共用連線時，紀錄不區分曾切換的帳號。"
        )
        layout.addWidget(scope)
        row = QHBoxLayout()
        self.link = QPushButton()
        self.link.setAutoDefault(False)
        self.link.clicked.connect(self._open_link)
        row.addWidget(self.link)
        row.addStretch()
        self.refresh_button = QPushButton("重新整理")
        self.refresh_button.setAutoDefault(False)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)

    def _open_link(self):
        if self.backend in ai_usage.USAGE_LINKS:
            QDesktopServices.openUrl(QUrl(ai_usage.USAGE_LINKS[self.backend]))

    def reset(self, cfg):
        self.backend = cfg.backend
        self.link.setText("官方用量查詢" if cfg.backend == "cli" else "官方查詢說明")
        self.link.setEnabled(cfg.backend in ai_usage.USAGE_LINKS)
        while self.windows.count():
            item = self.windows.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.scroll.hide()
        self.quota_status.setText("正在讀取方案用量…")
        self.quota_status.setToolTip("")
        self.local.setText("正在讀取本機紀錄…")
        self.refresh_button.setEnabled(False)

    def show_result(self, quota, local):
        details = [quota["message"]]
        if quota.get("plan"):
            details.append("方案：" + quota["plan"])
        else:
            details.append("方案：官方未提供")
        if self.backend in ("cli", "codex") and quota["windows"]:
            details.append("依官方額度群組顯示；沒有分模型的項目屬共用額度。")
        if quota.get("checked_at"):
            details.append("更新時間：" + quota["checked_at"].replace("T", " "))
        self.quota_status.setText("\n".join(details))
        self.quota_status.setToolTip("查詢時間：" + quota.get("checked_at", "未提供"))
        for window in quota["windows"]:
            label = QLabel(ai_usage.describe_window(window))
            label.setWordWrap(True)
            self.windows.addWidget(label)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(round(window["used"] * 10))
            bar.setFormat(f"已用 {window['used']:g}%")
            # The label above already states the percentage. Keep text off the
            # coloured fill so it stays readable in both light and dark themes.
            bar.setTextVisible(False)
            self.windows.addWidget(bar)
        self.scroll.setVisible(bool(quota["windows"]))
        height = min(260, 80 * len(quota["windows"]) + 10)
        self.scroll.setMinimumHeight(height)
        self.scroll.setMaximumHeight(height)
        if local is None:
            self.local.setText("本機用量紀錄暫時無法讀取。")
        else:
            headline = f"Paperfact 近 7 天 · {local['calls']} 次呼叫（{local['failed']} 次失敗）"
            if not local["calls"]:
                tokens = "尚無此連線的呼叫紀錄。"
            elif local["unknown"] == local["calls"] and not (local["input"] or local["output"]):
                tokens = f"Token 用量未回報（{local['unknown']} 次），總量未知。"
            else:
                tokens = f"已回報 token：輸入 {local['input']:,}／輸出 {local['output']:,}"
                if local["unknown"]:
                    tokens += f"；另有 {local['unknown']} 次未完整回報，總量未知。"
            self.local.setText(headline + "\n" + tokens)
        self.refresh_button.setEnabled(True)

    def failed(self):
        self.quota_status.setText("暫時無法取得方案用量，剩餘量未知；可重新整理。")
        self.local.setText("本機紀錄未更新。")
        self.refresh_button.setEnabled(True)


class AIUsageDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        style_settings(self)
        self.cfg = cfg
        self.runner = AskRunner(self)
        self.setWindowTitle("Paperfact · 帳號用量")
        self.resize(560, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 20)
        title = QLabel(ai_choices.LABELS.get(cfg.backend, cfg.backend) + " · 帳號用量")
        title.setStyleSheet("font-size:20px;font-weight:600;")
        layout.addWidget(title)
        self.account = QLabel("正在確認帳號…")
        self.account.setWordWrap(True)
        layout.addWidget(self.account)
        layout.addWidget(QLabel("方案額度（官方資料）"))
        self.quota_status = QLabel()
        self.quota_status.setWordWrap(True)
        layout.addWidget(self.quota_status)
        body = QWidget()
        self.windows = QVBoxLayout(body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.local = QLabel()
        self.local.setWordWrap(True)
        layout.addWidget(self.local)
        scope = QLabel(
            "本機紀錄僅計入近 7 天 Paperfact 透過此連線執行的工作；"
            "舊版未標示連線的紀錄不計入。Token 未回報不代表零用量，亦不代表方案剩餘額度。"
            "使用本機共用連線時，紀錄不區分曾切換的帳號。"
        )
        scope.setWordWrap(True)
        layout.addWidget(scope)
        footer = QHBoxLayout()
        self.link = QPushButton("官方用量查詢" if cfg.backend == "cli" else "官方查詢說明")
        self.link.setEnabled(cfg.backend in ai_usage.USAGE_LINKS)
        self.link.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(ai_usage.USAGE_LINKS[cfg.backend]))
        )
        footer.addWidget(self.link)
        footer.addStretch()
        self.refresh_button = QPushButton("重新整理")
        self.refresh_button.clicked.connect(self.refresh)
        footer.addWidget(self.refresh_button)
        close = QPushButton("關閉")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        layout.addLayout(footer)
        QTimer.singleShot(0, self.refresh)

    def _clear_windows(self):
        while self.windows.count():
            item = self.windows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def refresh(self):
        if self.runner.busy:
            return
        self.refresh_button.setEnabled(False)
        self._clear_windows()
        self.quota_status.setText("正在讀取官方資料…")
        self.local.setText("正在讀取本機紀錄…")
        cfg = self.cfg

        def fetch(_prompt):
            account, reason = ai_accounts.auth(cfg, "status")
            quota = ai_usage.subscription(cfg)
            try:
                local = ai_usage.local_summary(cfg)
            except OSError:
                local = None
            return json.dumps({"account": account or reason, "quota": quota, "local": local}), "ok"

        def done(value):
            result = json.loads(value)
            self.account.setText(result["account"])
            quota = result["quota"]
            details = [quota["message"]]
            if quota.get("plan"):
                details.append("方案：" + quota["plan"])
            if quota.get("checked_at"):
                details.append("查詢時間：" + quota["checked_at"])
            self.quota_status.setText("\n".join(details))
            for window in quota["windows"]:
                label = QLabel(ai_usage.describe_window(window))
                label.setWordWrap(True)
                self.windows.addWidget(label)
                bar = QProgressBar()
                bar.setRange(0, 1000)
                bar.setValue(round(window["used"] * 10))
                bar.setFormat(f"已用 {window['used']:g}%")
                self.windows.addWidget(bar)
            self.windows.addStretch()
            local = result["local"]
            self.local.setText(
                f"Paperfact 近 7 天 · {local['calls']} 次呼叫（{local['failed']} 次失敗）\n"
                f"已回報 token：輸入 {local['input']:,}／輸出 {local['output']:,}；"
                f"{local['unknown']} 次未完整回報。"
                if local is not None
                else "本機用量紀錄暫時無法讀取。"
            )
            self.refresh_button.setEnabled(True)

        def failed(_reason):
            self.account.setText("帳號資訊暫時無法讀取。")
            self.quota_status.setText("無法取得官方資料；剩餘額度未知，請稍後重新整理。")
            self.local.setText("本機紀錄未更新。")
            self.refresh_button.setEnabled(True)

        self.runner.start("", done, failed, call=fetch)

    def reject(self):
        if self.runner.busy:
            self.quota_status.setText("帳號資料讀取中，請稍候完成再關閉。")
            return
        super().reject()
