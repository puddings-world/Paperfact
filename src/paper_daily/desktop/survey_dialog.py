"""清單綜覽: a reading list read as one field, opened from the list page.

The survey itself is written by survey.py in a separate process, since one call
over forty papers runs for several minutes; the dialog shows what is stored, starts
a rewrite, and lets the reader edit the result like a note.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from paper_daily import runtime, store, survey
from paper_daily.desktop import ai_style, md
from paper_daily.desktop.note_editor import NoteEditor
from paper_daily.store import connect

ROOT = runtime.bundle_root()
SURVEY_EDIT_TEXT = {
    "zh-TW": {
        "empty": "請保留綜覽內容；空白內容尚未儲存。",
        "failed": "尚未儲存，草稿仍在這裡。請確認清單或工作區是否已變更，再重試或複製草稿。",
        "stale": "綜覽已在別處更新。這份修改已保留為待核對版本，草稿仍在這裡。",
        "changed": "綜覽已在別處變更，請先重新整理並確認新版內容。",
        "workspace": "目前工作區已變更。請關閉此視窗，從原清單重新開啟。",
    },
    "en": {
        "empty": "Keep some survey text; an empty survey has not been saved.",
        "failed": (
            "Not saved. Your draft remains here. "
            "Check the list and workspace, then retry or copy it."
        ),
        "stale": (
            "The survey changed elsewhere. Your revision was retained for review; "
            "the draft is still here."
        ),
        "changed": "The survey changed elsewhere. Refresh and review its current version first.",
        "workspace": (
            "The active workspace changed. "
            "Close this window and reopen the original list."
        ),
    },
}


class SurveyDialog(QDialog):
    def __init__(
        self, list_id: str, list_name: str, palette: dict[str, str], parent=None,
        *, language="zh-TW",
    ) -> None:
        super().__init__(parent)
        self.list_id = list_id
        self._database = Path(store.DB_PATH).resolve()
        self._language = language
        self._edit_text = SURVEY_EDIT_TEXT.get(language, SURVEY_EDIT_TEXT["en"])
        self._stored = None
        self._editing = False
        self.pal = palette
        self.job: QProcess | None = None

        from paper_daily.desktop.activity import hub_for
        from paper_daily.desktop.window_workspace import WindowWorkspace

        self._workspace_owner = WindowWorkspace.capture()
        self._hub = hub_for(self)
        self._shown_running = False
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
        if self._hub is not None:
            self._hub.changed.connect(self._hub_changed)
        self._load()

    def _workspace_matches(self) -> bool:
        return self._workspace_owner.current() and Path(store.DB_PATH).resolve() == self._database

    def _running(self) -> bool:
        from shiboken6 import isValid

        from paper_daily.desktop.window_workspace import current_for

        if self.job is not None:
            return True
        hub = self._hub
        return bool(
            self._workspace_matches() and hub is not None and isValid(hub)
            and current_for(hub.window)
            and any(job.key == f"survey:{self.list_id}" and job.state == "running"
                    for job in hub.jobs.values())
        )

    def _hub_changed(self) -> None:
        from shiboken6 import isValid

        if isValid(self) and (not self._workspace_matches()
                             or self._running() != self._shown_running):
            self._load()

    def _load(self) -> None:
        if not self._workspace_matches():
            self.status.setText(self._edit_text["workspace"])
            self.run_btn.setEnabled(False)
            self.edit_btn.setEnabled(False)
            return
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
        self._stored = stored
        running = self._running()
        self._shown_running = running
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
        if not self._workspace_matches():
            self.status.setText(self._edit_text["workspace"])
            return
        if self._running():
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
        elif stored and stored["spec"] == survey.ROADMAP_SPEC:
            answer = QMessageBox.question(
                self,
                "重新撰寫綜覽",
                "目前的綜覽是建立清單時的研究路線(選入理由與搜尋紀錄),"
                "重新撰寫會取代它。要繼續嗎?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            args.append("--force")
        # The confirmation may run an event loop while other edits arrive.
        if not self._workspace_matches():
            self.status.setText(self._edit_text["workspace"])
            return
        with connect() as conn:
            if survey.get(conn, self.list_id) != stored:
                self.status.setText(self._edit_text["changed"])
                return
        from paper_daily.desktop.activity import begin, process_environment

        self._activity = begin(self, "撰寫清單綜覽", key=f"survey:{self.list_id}",
                               result=self._show_result)
        if not self._activity.accepted:
            self.status.setText("這份清單的綜覽正在撰寫，請查看進度布告。")
            return
        self._activity_pending = self._output_tail = ""
        # Owned by the window behind the dialog, so closing the dialog does not kill
        # a survey that is minutes into being written; reopening shows it.
        self.job = QProcess(self.parent() or self)
        process_environment(self.job)
        environment = self.job.processEnvironment()
        environment.insert("PAPERFACT_DATA", str(self._database.parent))
        self.job.setProcessEnvironment(environment)
        job = self.job
        job.readyReadStandardOutput.connect(lambda: self._output(expected=job))
        self.job.setWorkingDirectory(str(ROOT))
        self.job.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        job.finished.connect(
            lambda code, status: self._done(code, status, expected=job)
        )
        job.errorOccurred.connect(lambda error: self._error(error, expected=job))
        self._load()
        from paper_daily.desktop.cli_job import prepare

        try:
            program, *rest = prepare(job, args, ("survey",))
        except (OSError, ValueError):
            job.deleteLater()
            self.job = None
            self._activity.finish(False)
            self._load()
            self.status.setText("AI job startup failed; please retry.")
            return
        self.job.start(program, rest)

    def _show_result(self):
        self._load()
        self.show()
        self.raise_()
        self.view.setFocus()

    def _output(self, *, expected=None):
        if self.job is None or expected is not None and self.job is not expected:
            return
        from paper_daily.desktop.activity import consume

        raw = bytes(self.job.readAllStandardOutput())
        handoff = getattr(self.job, "_ai_job_handoff", None)
        if handoff is not None:
            raw = handoff.filter_output(raw)
        chunk = raw.decode("utf-8", "replace")
        self._activity_pending = consume(self._activity, chunk, self._activity_pending)
        self._output_tail = (self._output_tail + chunk)[-4096:]

    def _done(self, code: int, _status, *, expected=None) -> None:
        if self.job is None or expected is not None and self.job is not expected:
            return
        self._output()
        output = self._output_tail.strip()
        handoff = getattr(self.job, "_ai_job_handoff", None)
        if handoff is not None:
            code = handoff.complete(code)
        self.job.deleteLater()
        self.job = None
        self._activity.finish(code == 0)
        if not self.isVisible():
            return
        self._load()
        if code:
            self.status.setText(f"沒有寫成:{output.splitlines()[-1] if output else code}")

    def _error(self, error, *, expected=None) -> None:
        if expected is not None and self.job is not expected:
            return
        if error == QProcess.ProcessError.FailedToStart and self.job is not None:
            job, self.job = self.job, None
            job.deleteLater()
            self._activity.finish(False)
            self._load()
            self.status.setText("無法啟動清單綜覽；請確認安裝後重試。")

    def _edit(self) -> None:
        if self._editing or self._running():
            return
        if not self._workspace_matches():
            self.status.setText(self._edit_text["workspace"])
            return
        original_list = self.list_id
        with connect() as conn:
            expected = survey.edit_snapshot(conn, original_list)
        stored = expected.target
        if not stored or stored != self._stored:
            self.status.setText(self._edit_text["changed"])
            return

        def save(body):
            if self.list_id != original_list or not self._workspace_matches():
                raise ValueError("The survey editor's workspace or list changed")
            if body == stored["body"].strip():
                return
            survey.edit(original_list, body, expected=expected)

        self._editing = True
        self.edit_btn.setEnabled(False)
        try:
            editor = NoteEditor(
                stored["body"], self.pal,
                "Markdown。儲存前會核對版本；變更衝突時保留草稿。", self,
                save=save, language=self._language, save_messages=self._edit_text,
            )
            editor.setWindowTitle("編輯清單綜覽")
            if editor.exec() == QDialog.DialogCode.Accepted:
                self._load()
        finally:
            self._editing = False
            self.edit_btn.setEnabled(self._workspace_matches())
