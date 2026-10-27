"""Offline research bundle transfer, independent of AI connections."""

import json
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from paper_daily import drive_share, google_slides, research_service
from paper_daily.desktop.ask import AskRunner


class BundleDialog(QDialog):
    progress = Signal(str)
    uploaded = Signal(int, int)

    def __init__(self, parent=None, *, source=None, list_id=None, list_name="",
                 download_missing=True):
        super().__init__(parent)
        self.source = Path(source) if source else None
        self.download_missing = download_missing
        self.list_id = list_id
        self.list_name = list_name
        self.result_data = None
        self.preview_ready = False
        self.runner = AskRunner(self)
        self.cancel_upload = threading.Event()
        self.drive_link = None
        self.uploading = False
        self.setWindowTitle("匯入研究資料包" if source else "匯出研究資料包")
        self.resize(560, 440)
        layout = QVBoxLayout(self)
        self.summary = QLabel(
            "正在核對資料包…"
            if source
            else (
                f"分享清單：{list_name}\n匯出當前已儲存內容；未儲存的編輯請先儲存。\n"
                "包含分析、圖表、簡報、研究問題及已下載的 PDF。\n"
                "尚未下載的原文會列為缺少；匯出不呼叫 AI，也不連網重找版本。"
            )
        )
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.notes = QCheckBox("包含我的筆記、問答紀錄與手動畫線")
        self.notes.setChecked(True)
        self.notes.setVisible(not source)
        layout.addWidget(self.notes)
        self.pdfs = QCheckBox("附上原文 PDF（對方不必再自行下載）")
        self.pdfs.setChecked(True)
        self.pdfs.setVisible(not source)
        layout.addWidget(self.pdfs)
        self.drive_box = QGroupBox("分享到 Google Drive")
        drive = QVBoxLayout(self.drive_box)
        self.emails = QLineEdit()
        self.emails.setPlaceholderText("對方的 Google 帳號 email，多位以逗號分隔")
        drive.addWidget(self.emails)
        self.anyone = QCheckBox("知道連結的任何人都能下載（對方可直接在 Paperfact 貼上連結匯入）")
        drive.addWidget(self.anyone)
        self.drive_button = QPushButton("上傳到我的 Google Drive 並複製連結")
        self.drive_button.setDefault(True)
        self.drive_button.clicked.connect(self._drive_share)
        drive.addWidget(self.drive_button)
        self.upload_bar = QProgressBar()
        self.upload_bar.setVisible(False)
        drive.addWidget(self.upload_bar)
        self.drive_open = QPushButton("在 Google Drive 開啟")
        self.drive_open.setVisible(False)
        self.drive_open.clicked.connect(self._drive_open)
        drive.addWidget(self.drive_open)
        self.drive_box.setVisible(not source)
        layout.addWidget(self.drive_box)
        self.uploaded.connect(self._upload_progress)
        self.replace = QCheckBox("以資料包取代已有的分析、素材與 PDF")
        self.replace.setVisible(bool(source))
        layout.addWidget(self.replace)
        self.status = QLabel(
            "預設保留本機已有內容；不同版本的 PDF 與對應分析會一起保留。" if source else ""
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress.connect(self.status.setText)
        self.progress.connect(self.runner.report)
        self.go = QPushButton("匯入" if source else "改為存成檔案…")
        self.go.clicked.connect(self._start)
        self.go.setEnabled(not source)
        layout.addWidget(self.go)
        self.share_button = QPushButton("製作並複製分享連結…")
        self.share_button.setVisible(False)
        self.share_button.clicked.connect(self._share_link)
        layout.addWidget(self.share_button)
        self.close_button = QPushButton("關閉")
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.close_button)
        if source:
            QTimer.singleShot(0, self, self._preview)
        else:
            self._recall_share()

    def _preview(self):
        def call(_):
            try:
                return json.dumps(research_service.inspect_bundle(self.source),
                                  ensure_ascii=False), "ok"
            except (ValueError, OSError) as exc:
                return None, str(exc)

        def done(value):
            info = json.loads(value)
            self.preview_ready = True
            self.summary.setText(
                f"{info['name']}\n{info['papers']} 篇論文 · {info['pdfs']} 份 PDF 實體檔\n"
                f"{info['analyses']} 份分析 · {info['notes']} 則筆記 · {info['chats']} 則問答\n"
                f"{info['missing_pdfs']} 篇未附原文 PDF。\n"
                f"{info['conflicts']} 篇已在本機；同名 ID 的清單會合併新增文章。\n"
                "匯入不需 AI 登入，不會重新生成分析。"
            )
            self.go.setEnabled(True)

        self.runner.start("", done, self._failed, call=call)

    def _start(self):
        if self.runner.busy or (self.source and not self.preview_ready):
            return
        if self.result_data is not None:
            self.accept()
            return
        replace = self.replace.isChecked()
        if (
            self.source
            and replace
            and QMessageBox.question(
                self,
                "確認取代本機研究內容",
                "將取代資料包內同篇論文的既有分析、素材與 PDF。確定繼續？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        destination = None
        if not self.source:
            destination, _filter = QFileDialog.getSaveFileName(
                self,
                "匯出研究資料包",
                f"{self.list_id}.paperfact.zip",
                "Paperfact 研究資料包 (*.zip)",
            )
            if not destination:
                return
            if not destination.lower().endswith(".zip"):
                destination += ".zip"
        notes, with_pdfs = self.notes.isChecked(), self.pdfs.isChecked()
        self._lock(True)
        self.status.setText("正在匯入並核對原文…" if self.source else "正在打包原文與研究成果…")

        def call(_):
            try:
                result = (
                    research_service.import_bundle(self.source, replace=replace,
                                                   pdfs=self.download_missing,
                                                   log=self.progress.emit)
                    if self.source
                    else research_service.export_bundle(
                        self.list_id,
                        Path(destination),
                        notes=notes,
                        with_pdfs=with_pdfs,
                        log=self.progress.emit,
                    )
                )
                return json.dumps(result, ensure_ascii=False, default=str), "ok"
            except (ValueError, OSError) as exc:
                return None, str(exc)

        self.runner.start("", self._done, self._failed, call=call)

    def _done(self, value):
        self.result_data = json.loads(value)
        result = self.result_data
        if self.source:
            conflicts = len(result.get("pdf_conflicts", []))
            missing = len(result.get("pdf_needed", []))
            message = f"已匯入「{result['name']}」。{conflicts} 篇原文版本衝突已保留本機內容。"
            if missing:
                message += f" {missing} 篇仍需原分享者提供相同版本 PDF。"
        else:
            message = (
                f"已匯出 {result['papers']} 篇論文、{result['pdf_packed']} 份原文。\n"
                f"{len(result['pdf_missing'])} 篇尚無本機 PDF。\n{result['out']}"
            )
        self.status.setText(message)
        self.share_button.setVisible(not self.source)
        self.go.setText("完成")
        self.go.setEnabled(True)

    def _failed(self, reason):
        self.status.setText("未完成：" + reason)
        self.uploading = False
        self._lock(False)
        self.go.setEnabled(not self.source or self.preview_ready)
        self.upload_bar.setVisible(False)

    def _lock(self, busy):
        for widget in (
            self.go,
            self.replace,
            self.notes,
            self.pdfs,
            self.emails,
            self.anyone,
            self.drive_button,
        ):
            widget.setEnabled(not busy)

    def _recall_share(self):
        before = drive_share.previous(self.list_id)
        if before:
            self.anyone.setChecked(bool(before.get("anyone")))
            self.drive_button.setText("更新 Google Drive 上的分享（連結不變）")
            self.drive_link = before["file_id"]
            self.drive_open.setVisible(True)

    def _drive_share(self):
        if self.runner.busy or self.source:
            return
        try:
            emails = drive_share.parse_emails(self.emails.text())
            google_slides.read_client()
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        anyone = self.anyone.isChecked()
        # Updating an earlier share may add no one: its readers keep their access.
        if not emails and not anyone and not drive_share.previous(self.list_id):
            self.status.setText("請輸入對方的 Google 帳號 email，或勾選「知道連結的任何人」。")
            return
        notes, with_pdfs = self.notes.isChecked(), self.pdfs.isChecked()
        self.cancel_upload.clear()
        self.uploading = True
        self._lock(True)
        self.upload_bar.setRange(0, 0)
        self.upload_bar.setVisible(True)
        self.status.setText("正在打包…第一次分享會開啟瀏覽器登入 Google。")
        name = f"{self.list_name or self.list_id}.paperfact.zip"

        def call(_):
            try:
                with TemporaryDirectory(prefix="paperfact-drive-") as folder:
                    out = Path(folder) / "package.zip"
                    research_service.export_bundle(
                        self.list_id, out, notes=notes, with_pdfs=with_pdfs, log=self.progress.emit
                    )
                    self.progress.emit("正在上傳到你的 Google Drive…")
                    result = drive_share.publish(
                        self.list_id,
                        out,
                        drive_share.session(),
                        name=name,
                        emails=emails,
                        anyone=anyone,
                        progress=self.uploaded.emit,
                        cancelled=self.cancel_upload.is_set,
                    )
                return json.dumps(result, ensure_ascii=False), "ok"
            except (ValueError, OSError) as exc:
                return None, str(exc)
            except Exception as exc:  # noqa: BLE001 - a dropped connection must end the worker
                return None, f"Google 連線失敗：{type(exc).__name__}"

        self.runner.start("", self._drive_done, self._failed, call=call)

    def _upload_progress(self, done, total):
        self.upload_bar.setRange(0, max(total, 1))
        self.upload_bar.setValue(done)

    def _drive_done(self, value):
        result = json.loads(value)
        self.uploading = False
        QGuiApplication.clipboard().setText(result["link"])
        self.drive_link = result["file_id"]
        self._lock(False)
        self.drive_open.setVisible(True)
        self.drive_button.setText("更新 Google Drive 上的分享（連結不變）")
        public = self.anyone.isChecked()
        who = "知道連結的任何人" if public else "、".join(result["emails"])
        done = (
            "已更新 Drive 上的資料包，原連結不變。"
            if result["replaced"]
            else "已上傳到你的 Google Drive。"
        )
        self.status.setText(
            done
            + f"\n連結已複製到剪貼簿。可下載的人：{who}。"
            + ("" if public else "\n對方登入該 Google 帳號後，在瀏覽器下載 ZIP 再匯入。")
        )

    def _drive_open(self):
        if self.drive_link:
            QDesktopServices.openUrl(QUrl(drive_share.view_url(self.drive_link)))

    def _share_link(self):
        if self.runner.busy or self.source or not self.result_data:
            return
        url, accepted = QInputDialog.getText(
            self, "製作研究包分享連結",
            "先將剛匯出的 ZIP 上傳到你選擇的檔案空間，再貼上 HTTPS 直接下載網址。\n"
            "Paperfact 不會代為上傳或變更分享權限。接收者可用『網址匯入』載入。",
        )
        if not accepted:
            return
        from paper_daily.bundle_links import parse_link

        try:
            parse_link(url)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        path = Path(self.result_data["out"])
        self.share_button.setEnabled(False)

        def call(_):
            try:
                return research_service.make_share_link(url, path), "ok"
            except (ValueError, OSError) as exc:
                return None, str(exc)

        def done(link):
            QGuiApplication.clipboard().setText(link)
            self.status.setText("分享連結已複製，含這份研究包的校驗碼。\n"
                                "接收者可從『研究資料 → 從分享網址匯入』貼上。")
            self.share_button.setEnabled(True)

        def failed(reason):
            self.status.setText("無法製作分享連結：" + reason)
            self.share_button.setEnabled(True)

        self.runner.start("", done, failed, call=call)

    def reject(self):
        if self.runner.busy:
            if self.uploading:
                self.cancel_upload.set()
                self.status.setText("正在取消上傳…")
                return
            self.status.setText("正在處理資料包，請等候完成後關閉。")
            return
        super().reject()

    def closeEvent(self, event):
        if self.runner.busy:
            event.ignore()
        else:
            super().closeEvent(event)
