"""Offline research bundle transfer, independent of AI connections."""

import json
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from paper_daily import research_service
from paper_daily.desktop.ask import AskRunner


class BundleDialog(QDialog):
    progress = Signal(str)

    def __init__(self, parent=None, *, source=None, list_id=None, list_name=""):
        super().__init__(parent)
        self.source = Path(source) if source else None
        self.list_id = list_id
        self.list_name = list_name
        self.result_data = None
        self.preview_ready = False
        self.runner = AskRunner(self)
        self.setWindowTitle("匯入研究資料包" if source else "匯出研究資料包")
        self.resize(560, 360)
        layout = QVBoxLayout(self)
        self.summary = QLabel(
            "正在核對資料包…"
            if source
            else (
                f"分享清單：{list_name}\n匯出當前已儲存內容；未儲存的編輯請先儲存。\n"
                "包含所有已下載 PDF、分析、圖表、簡報及研究問題。\n"
                "尚未下載的原文會列為缺少；匯出不呼叫 AI，也不連網重找版本。"
            )
        )
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.notes = QCheckBox("包含我的筆記、問答紀錄與手動畫線")
        self.notes.setChecked(True)
        self.notes.setVisible(not source)
        layout.addWidget(self.notes)
        self.replace = QCheckBox("以資料包取代已有的分析、素材與 PDF")
        self.replace.setVisible(bool(source))
        layout.addWidget(self.replace)
        self.status = QLabel(
            "預設保留本機已有內容；不同版本的 PDF 與對應分析會一起保留。" if source else ""
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress.connect(self.status.setText)
        self.go = QPushButton("匯入" if source else "選擇儲存位置並匯出")
        self.go.clicked.connect(self._start)
        self.go.setEnabled(not source)
        layout.addWidget(self.go)
        self.close_button = QPushButton("關閉")
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.close_button)
        if source:
            QTimer.singleShot(0, self, self._preview)

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
        if self.runner.busy:
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
        notes = self.notes.isChecked()
        self.go.setEnabled(False)
        self.replace.setEnabled(False)
        self.notes.setEnabled(False)
        self.status.setText("正在匯入並核對原文…" if self.source else "正在打包原文與研究成果…")

        def call(_):
            try:
                result = (
                    research_service.import_bundle(self.source, replace=replace,
                                                   log=self.progress.emit)
                    if self.source
                    else research_service.export_bundle(
                        self.list_id,
                        Path(destination),
                        notes=notes,
                        with_pdfs=True,
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
        self.go.setText("完成")
        self.go.setEnabled(True)

    def _failed(self, reason):
        self.status.setText("未完成：" + reason)
        self.go.setEnabled(not self.source or self.preview_ready)
        self.replace.setEnabled(True)
        self.notes.setEnabled(True)

    def reject(self):
        if self.runner.busy:
            self.status.setText("正在處理資料包，請等候完成後關閉。")
            return
        super().reject()

    def closeEvent(self, event):
        if self.runner.busy:
            event.ignore()
        else:
            super().closeEvent(event)
