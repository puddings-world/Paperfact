"""清單綜覽: a reading list read as one field, opened from the list page.

The survey itself is written by survey.py in a separate process, since one call
over forty papers runs for several minutes; the dialog shows what is stored, starts
a rewrite, and lets the reader edit the result like a note.
"""

from __future__ import annotations

from PySide6.QtCore import QProcess, QProcessEnvironment
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from paper_daily import runtime, survey
from paper_daily.desktop import ai_style, md
from paper_daily.desktop.note_editor import NoteEditor
from paper_daily.store import connect

ROOT = runtime.bundle_root()


class SurveyDialog(QDialog):
    def __init__(self, list_id: str, list_name: str, palette: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.list_id = list_id
        self.pal = palette
        self.job: QProcess | None = None
        self.setWindowTitle(f"清單綜覽 · {list_name}")
        self.resize(1000, 820)
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{palette['muted']};font-size:12px;")
        top.addWidget(self.status, 1)
        self.edit_btn = QPushButton("編輯")
        self.edit_btn.clicked.connect(self._edit)
        top.addWidget(self.edit_btn)
        self.run_btn = QPushButton("")
        self.run_btn.setToolTip(
            "讀過清單裡每一篇的講解(一句話結論、前導導讀、證據、限制、後續研究),"
            "寫成一份跨論文的領域綜覽。一次模型呼叫,約五到十分鐘。"
        )
        ai_style.mark(self.run_btn, palette, primary=True)
        self.run_btn.clicked.connect(self._run)
        top.addWidget(self.run_btn)
        layout.addLayout(top)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setStyleSheet(
            f"QTextBrowser{{background:{palette['surface']};color:{palette['ink']};"
            f"border:1px solid {palette['border']};padding:18px;font-size:14px;}}"
        )
        layout.addWidget(self.view, 1)
        self._load()

    def _load(self) -> None:
        with connect() as conn:
            stored = survey.get(conn, self.list_id)
            count = conn.execute(
                "SELECT COUNT(*) FROM list_papers WHERE list_id=?", (self.list_id,)
            ).fetchone()[0]
            undived = conn.execute(
                "SELECT COUNT(*) FROM list_papers lp LEFT JOIN dives d ON d.paper_id = "
                "lp.paper_id WHERE lp.list_id=? AND d.paper_id IS NULL",
                (self.list_id,),
            ).fetchone()[0]
        running = self.job is not None
        self.run_btn.setEnabled(not running)
        self.run_btn.setText(
            "撰寫中…" if running else ("重新撰寫綜覽" if stored else "撰寫清單綜覽")
        )
        self.edit_btn.setVisible(bool(stored) and not running)
        # A survey is only as good as the dives under it; say when it rests on
        # abstracts, or on a list that has grown since.
        gaps = f" · {undived} 篇還沒有講解,只能依摘要" if undived else ""
        if stored:
            grown = (
                f" · 撰寫後清單多了 {count - stored['papers']} 篇"
                if stored["papers"] and count > stored["papers"]
                else ""
            )
            self.status.setText(
                f"依清單 {stored['papers']} 篇撰寫於 {stored['written_at'][:16].replace('T', ' ')}"
                + (" · 已手動修改" if stored["edited"] else "")
                + grown
                + gaps
            )
            self.view.setHtml(md.to_html(stored["body"], self.pal))
        else:
            self.status.setText(f"清單共 {count} 篇{gaps}。")
            self.view.setHtml(
                md.to_html(
                    "還沒有綜覽。\n\n綜覽會把清單裡的論文當成一個研究領域來讀:研究脈絡與階段、"
                    "各條研究路線與代表作、資料集與評測、目前的進展、面對的挑戰、"
                    "還沒解決的問題與可以做的題目,以及建議的閱讀順序。"
                    "它以每一篇的深度講解(特別是前導導讀)為材料,所以先把清單分析完,"
                    "綜覽會準確得多。",
                    self.pal,
                )
            )
        if running:
            self.status.setText("正在撰寫綜覽…一次讀完整份清單,約五到十分鐘。")

    def _run(self) -> None:
        from paper_daily.desktop.ai_access import requires_ai

        requires_ai("survey")(type(self)._run_ready)(self)

    def _run_ready(self) -> None:
        if self.job is not None:
            return
        with connect() as conn:
            stored = survey.get(conn, self.list_id)
        args = ["survey", self.list_id]
        if stored and stored["edited"]:
            answer = QMessageBox.question(
                self, "重新撰寫綜覽", "這份綜覽手動修改過,重新撰寫會取代你的修改。要繼續嗎?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            args.append("--force")
        # Owned by the window behind the dialog, so closing the dialog does not kill
        # a survey that is minutes into being written; reopening shows it.
        self.job = QProcess(self.parent() or self)
        self.job.setProcessEnvironment(QProcessEnvironment.systemEnvironment())
        self.job.setWorkingDirectory(str(ROOT))
        self.job.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.job.finished.connect(self._done)
        self.job.errorOccurred.connect(self._error)
        self._load()
        program, *rest = runtime.cli_command(*args)
        self.job.start(program, rest)

    def _done(self, code: int, _status) -> None:
        output = bytes(self.job.readAll()).decode("utf-8", "replace").strip()
        self.job = None
        if not self.isVisible():
            return
        self._load()
        if code:
            self.status.setText(f"沒有寫成:{output.splitlines()[-1] if output else code}")

    def _error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart and self.job is not None:
            job, self.job = self.job, None
            job.deleteLater()
            self._load()
            self.status.setText("無法啟動清單綜覽；請確認安裝後重試。")

    def _edit(self) -> None:
        with connect() as conn:
            stored = survey.get(conn, self.list_id)
        if not stored:
            return
        editor = NoteEditor(
            stored["body"], self.pal, "Markdown。修改過的綜覽重新撰寫時會先確認。", self
        )
        editor.setWindowTitle("編輯清單綜覽")
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        body = editor.text().strip()
        if body and body != stored["body"].strip():
            survey.edit(self.list_id, body)
            self._load()
