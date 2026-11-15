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
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
)
from shiboken6 import isValid

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


SURVEY_EVIDENCE_TEXT = {
    "en": {
        "roadmap": "Recorded workflow: topic-search roadmap.",
        "survey": "Recorded workflow: overview from saved analyses or abstracts.",
        "unknown": "The original input workflow is not recorded.",
        "edited": "Includes manual edits.",
        "unverified": (
            "Claim-level original sources are not recorded or verified here. "
            "The paper count is not a count of verified originals; "
            "inspect the relevant papers before relying on a statement."
        ),
    },
    "zh-TW": {
        "roadmap": (
            "\u7d00\u9304\u7684\u7522\u751f\u65b9\u5f0f\uff1a"
            "\u4e3b\u984c\u6aa2\u7d22\u8def\u7dda\u3002"
        ),
        "survey": (
            "\u7d00\u9304\u7684\u7522\u751f\u65b9\u5f0f\uff1a"
            "\u6574\u7406\u5df2\u5b58\u5206\u6790\u6216\u6458\u8981\u3002"
        ),
        "unknown": "\u672a\u7d00\u9304\u539f\u59cb\u8f38\u5165\u65b9\u5f0f\u3002",
        "edited": "\u542b\u624b\u52d5\u7de8\u8f2f\u3002",
        "unverified": (
            "\u6b64\u8655\u5c1a\u672a\u7d00\u9304\u6216\u6838\u5c0d\u9010\u9805\u539f\u6587\u4f86\u6e90\u3002"
            "\u7bc7\u6578\u4e0d\u4ee3\u8868\u5df2\u9a57\u8b49\u539f\u6587\u6578\uff1b"
            "\u63a1\u7528\u6558\u8ff0\u524d\u8acb\u56de\u5230\u76f8\u95dc\u8ad6\u6587\u6838\u5c0d\u3002"
        ),
    },
}


def _evidence_notice(stored, language):
    """Describe the recorded workflow, never infer sources from today's list/PDFs."""
    if stored is None:
        return ""
    copy = SURVEY_EVIDENCE_TEXT.get(language, SURVEY_EVIDENCE_TEXT["en"])
    key = ("roadmap" if stored["spec"] == survey.ROADMAP_SPEC
           else "survey" if stored["spec"] == survey.SURVEY_SPEC else "unknown")
    parts = [copy[key], *([copy["edited"]] if stored["edited"] else []), copy["unverified"]]
    return " ".join(parts)



SOURCE_TEXT = {
    "en": dict(
        generate="Generate with sources", confirm_title="Generate a new report?",
        confirm=("Use the current research goal and originals to create a new report version. "
                 "Previous versions and your editable overview are kept."),
        busy="Generating a report from original sources...",
    ),
    "zh-TW": dict(
        generate="\u6839\u64da\u539f\u6587\u7522\u751f\u5831\u544a",
        confirm_title="\u7522\u751f\u65b0\u7248\u5831\u544a\uff1f",
        confirm=("\u6839\u64da\u76ee\u524d\u7814\u7a76\u76ee\u6a19\u8207"
                 "\u539f\u6587\u5efa\u7acb\u65b0\u7248\u5831\u544a\u3002"
                 "\u820a\u7248\u8207\u53ef\u7de8\u8f2f\u6458\u8981\u6703"
                 "\u4fdd\u7559\u3002"),
        busy="\u6b63\u5728\u6839\u64da\u539f\u6587\u7522\u751f\u5831\u544a...",
    ),
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
        self._source_job = False
        self._source_text = SOURCE_TEXT.get(language, SOURCE_TEXT["en"])
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
        self.source_btn = QPushButton(self._source_text["generate"])
        self.source_btn.setAutoDefault(False)
        self.source_btn.clicked.connect(self._run_sources)
        ai_style.mark(self.source_btn, palette, primary=True)
        top.addWidget(self.source_btn)
        layout.addLayout(top)
        self.evidence_notice = QLabel()
        self.evidence_notice.setWordWrap(True)
        self.evidence_notice.setStyleSheet(f"color:{palette['muted']};font-size:12px;")
        layout.addWidget(self.evidence_notice)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setStyleSheet(
            f"QTextBrowser{{background:{palette['surface']};color:{palette['ink']};"
            f"border:1px solid {palette['border']};padding:18px;font-size:14px;}}"
        )
        from paper_daily.desktop.survey_evidence import TEXT, SavedSurveyPane

        words = TEXT.get(language, TEXT["en"])
        self.report_tabs = QTabWidget()
        self.report_tabs.addTab(self.view, words["legacy"])
        self.saved_report = SavedSurveyPane(
            self._database, list_id, palette,
            current=lambda: self._workspace_matches() and self.list_id == list_id,
            language=language, parent=self, autoload=False)
        self.report_tabs.addTab(self.saved_report, words["tab"].replace("&", "&&"))
        self._report_tab_touched = False
        self.report_tabs.currentChanged.connect(self._report_tab_changed)
        self.report_tabs.tabBarClicked.connect(
            lambda _index: setattr(self, "_report_tab_touched", True))
        self.saved_report.available.connect(self._report_available)
        self.saved_report.state_changed.connect(self._sync_source_button)
        self.saved_report.drained.connect(self.reject)
        layout.addWidget(self.report_tabs, 1)
        if self._hub is not None:
            self._hub.changed.connect(self._hub_changed)
        self._load()
        self.saved_report.reload()

    def _report_available(self):
        if (not self._report_tab_touched and not self._editing and self._workspace_matches()
                and not self._running() and not self._waiting()):
            self.report_tabs.setCurrentIndex(1)

    def _report_tab_changed(self, _index):
        self._sync_source_button()
        self._report_tab_touched = True
        legacy = self.report_tabs.currentIndex() == 0
        self.status.setVisible(legacy)
        self.run_btn.setVisible(legacy)
        self.run_btn.setEnabled(legacy and not self._running() and self._workspace_matches())
        self.edit_btn.setVisible(legacy and bool(self._stored) and not self._running())
        self.evidence_notice.setVisible(legacy and self._stored is not None)

    def reject(self):
        pane = getattr(self, "saved_report", None)
        if pane is None or pane.request_close():
            super().reject()

    def closeEvent(self, event):
        if self.saved_report.request_close():
            super().closeEvent(event)
        else:
            event.ignore()

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
        self._sync_source_button()
        if not self._workspace_matches():
            self.saved_report._stale()
            self.evidence_notice.clear()
            self.evidence_notice.hide()
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
        self.evidence_notice.setText(_evidence_notice(stored, self._language))
        self.evidence_notice.setVisible(stored is not None)
        waiting = self._waiting()
        running = self._running() or waiting
        self._shown_running = running
        self.run_btn.setEnabled(not running)
        self.run_btn.setText(
            "排隊中…" if waiting else "撰寫中…" if running
            else ("重新撰寫綜覽" if stored else "撰寫清單綜覽")
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
        if self.report_tabs.currentIndex() != 0:
            self.run_btn.setEnabled(False)
            self.edit_btn.hide()
            self.evidence_notice.hide()
        if running:
            self.status.setText("正在撰寫綜覽…一次讀完整份清單,約五到十分鐘。")


    def _sync_source_button(self):
        source = self.report_tabs.currentIndex() == 1
        self.source_btn.setVisible(source)
        self.source_btn.setEnabled(
            source and self._workspace_matches() and not self._running() and not self._waiting()
            and self.saved_report.future is None
            and (self.saved_report.saved is None
                 or self.saved_report.saved.data["kind"] != "retained")
        )

    def _run_sources(self):
        if self.report_tabs.currentIndex() != 1:
            return
        saved = self.saved_report.saved
        if saved is not None and saved.data["kind"] == "retained":
            self.saved_report.status.setText(self.saved_report.words["result_scope"])
            return
        from paper_daily.desktop.ai_access import requires_ai

        requires_ai("survey")(type(self)._run_sources_ready)(self)

    def _run_sources_ready(self):
        if (self.report_tabs.currentIndex() != 1 or not self._workspace_matches()
                or self._running() or self._waiting()):
            return
        pane = self.saved_report
        saved = pane.saved
        if saved is None or pane.future is not None:
            pane.status.setText(pane.words["loading"])
            return
        if not saved.current():
            pane._stale()
            return
        data = saved.data
        if data["kind"] == "retained":
            pane.status.setText(pane.words["result_scope"])
            return
        if data.get("update_pending"):
            pane.status.setText(pane.words["pending"])
            return
        identity = data["report"]["id"] if data["kind"] != "none" else "none"
        args = ["survey", self.list_id, "--sources", "--expected-report", identity]
        if identity != "none":
            if QMessageBox.question(
                self, self._source_text["confirm_title"], self._source_text["confirm"]
            ) != QMessageBox.StandardButton.Yes:
                return
            if not saved.current():
                pane._stale()
                return
            args.append("--force")
        from paper_daily.desktop.activity import begin, when_ready

        handle = begin(self, self._source_text["generate"], key=f"survey:{self.list_id}",
                       result=self._show_result, cancel=self._stop,
                       retry=self._run_sources_ready, queued=True)
        self._activity = handle
        if not handle.accepted:
            return
        pane.status.setText(self._source_text["busy"])
        self._sync_source_button()
        when_ready(handle, lambda: self._launch(handle, args))

    def _run(self) -> None:
        if self.report_tabs.currentIndex() != 0:
            return
        from paper_daily.desktop.ai_access import requires_ai

        requires_ai("survey")(type(self)._run_ready)(self)

    def _run_ready(self) -> None:
        if self.report_tabs.currentIndex() != 0:
            return
        if not self._workspace_matches():
            self.status.setText(self._edit_text["workspace"])
            return
        if self._running() or self._waiting():
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
        from paper_daily.desktop.activity import begin, when_ready

        self._activity = begin(self, "撰寫清單綜覽", key=f"survey:{self.list_id}",
                               result=self._show_result, cancel=self._stop,
                               retry=self._run_ready, queued=True)
        if not self._activity.accepted:
            self.status.setText("這份清單的綜覽正在撰寫，請查看進度布告。")
            return
        handle = self._activity
        when_ready(handle, lambda: isValid(self) and self._launch(handle, args))
        if getattr(handle, "waiting", False):
            self._load()
            self.status.setText("已排入工作佇列；前面的分析結束後就會開始撰寫。")
            if handle.hub is not None and not getattr(self, "_watching_queue", False):
                self._watching_queue = True
                handle.hub.changed.connect(self._queue_changed)

    def _queue_changed(self) -> None:
        # Leaving the line from the job panel must not leave 排隊中 on the button.
        if (isValid(self) and self.job is None and not self._waiting()
                and self.run_btn.text() == "排隊中…"):
            self._load()

    def _waiting(self) -> bool:
        activity = getattr(self, "_activity", None)
        return bool(getattr(activity, "waiting", False))

    def _launch(self, handle, args) -> None:
        if self.job is not None or not self._workspace_matches():
            handle.finish(cancelled=True)
            return
        from paper_daily.desktop.activity import process_environment

        self._activity = handle
        self._source_job = "--sources" in args
        self._stopping = False
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

    def _stop(self):
        if self._waiting():
            self._activity.finish(cancelled=True)
            self._load()
            return
        if self.job is not None:
            self._stopping = True
            self.job.kill()

    def _show_result(self):
        self.report_tabs.setCurrentIndex(1 if self._source_job else 0)
        self._load()
        self.saved_report.reopen()
        if self._source_job:
            self.saved_report.reload_after_job()
        self.show()
        self.raise_()
        (self.saved_report.view if self._source_job else self.view).setFocus()

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
        self._activity.finish(code == 0, cancelled=self._stopping)
        if self._stopping:
            self._stopping = False
            if self.isVisible():
                self._load()
                self.status.setText("已停止撰寫；原本的綜覽沒有改動。")
            return
        if not self.isVisible():
            return
        self._load()
        if self._source_job:
            if self._workspace_matches():
                if code == 0:
                    self.saved_report.reload_after_job()
                else:
                    self.saved_report.status.setText(output[-800:] or "Report generation failed.")
            return
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
        if self._editing or self._running() or self.report_tabs.currentIndex() != 0:
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
