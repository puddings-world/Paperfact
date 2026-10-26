"""Download to a temporary file, then use the existing research preview/import."""

import threading
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout

from paper_daily import bundle_links, research_service
from paper_daily.desktop.ask import AskRunner


class BundleLinkDialog(QDialog):
    progress = Signal(str)

    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        self.source = None
        self.target = folder / "shared.paperfact.zip"
        self.cancelled = threading.Event()
        self._closing = False
        self.runner = AskRunner(self)
        self.runner.activity_label = "下載分享研究包"
        self.setWindowTitle("從分享網址匯入")
        self.resize(580, 230)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "貼上研究包的 HTTPS 下載網址，下載後會先顯示清單預覽。\n"
            "不需 AI 登入；確認匯入後才會修改你的研究資料。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://…/research.paperfact.zip")
        self.url.setMaxLength(8192)
        layout.addWidget(self.url)
        self.status = QLabel("需要雲端登入或只能預覽的連結，請先用瀏覽器下載 ZIP 再匯入。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress.connect(self.status.setText)
        self.progress.connect(self.runner.report)
        self.go = QPushButton("下載並預覽")
        self.go.clicked.connect(self._start)
        layout.addWidget(self.go)
        self.cancel = QPushButton("取消")
        self.cancel.clicked.connect(self.reject)
        layout.addWidget(self.cancel)

    def _start(self):
        if self.runner.busy or self._closing:
            return
        requested = self.url.text().strip()
        try:
            bundle_links.parse_link(requested)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.cancelled.clear()
        self.go.setEnabled(False)
        self.url.setEnabled(False)
        self.status.setText("正在連線並下載研究資料包…")

        def progress(done, total):
            size = f"{done / 1024**2:.1f} MB"
            if total:
                size = f"{min(100, done * 100 // total)}% · {size} / {total / 1024**2:.1f} MB"
            self.progress.emit("下載研究包：" + size)

        def call(_):
            try:
                path = research_service.download_bundle(
                    requested, self.target, progress=progress, cancelled=self.cancelled.is_set
                )
                return str(path), "ok"
            except (ValueError, OSError) as exc:
                return None, str(exc)

        def done(value):
            if self._closing:
                self._finish(False)
            elif self.url.text().strip() != requested:
                self._failed("網址已變更，請重新下載。")
            else:
                self.source = Path(value)
                self._finish(True)

        self.runner.start("", done, self._failed, call=call)

    def _failed(self, reason):
        if self._closing:
            self._finish(False)
            return
        self.status.setText("未完成：" + reason)
        self.go.setEnabled(True)
        self.url.setEnabled(True)

    def _finish(self, accepted):
        # Keep the dialog/worker alive until QThread has actually stopped.
        if self.runner.busy:
            QTimer.singleShot(25, self, lambda: self._finish(accepted))
            return
        if accepted and not self._closing:
            self.accept()
        else:
            super().reject()

    def reject(self):
        if self.runner.busy:
            self._closing = True
            self.cancelled.set()
            self.go.setEnabled(False)
            self.cancel.setEnabled(False)
            self.status.setText("正在取消下載；清理完成後關閉。")
            return
        super().reject()

    def closeEvent(self, event):
        if self.runner.busy:
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)
