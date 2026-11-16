"""Saved list-report reading and original-page inspection, separate from editing."""

from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from paper_daily import survey_audit, survey_jobs, survey_reader, survey_result_review
from paper_daily.desktop.note_source_dialog import PagePreview

TEXT = {
    "en": dict(
        tab="Report & sources",
        legacy="Editable overview",
        refresh="Current report",
        audit="Check all sources",
        audit_busy="Checking saved originals and recorded quote locations...",
        audit_done=("Originals verified: {verified}/{total}; located quotes checked: {quotes}; "
                    "unlocated quotes: {unlocated}. Scientific support was not checked."),
        results="Completed AI results",
        results_loading="Reading completed AI results...",
        results_empty="No completed AI results are retained for this list.",
        result_label="{started} | {model} | {request}",
        result_scope=("Read-only retained result. Viewing it does not change the current list. "
                      "Open original checks the captured PDF, not today's replacement. "
                      "Use this report requires a separate confirmation."),
        finish="Finish saved report",
        finish_scope="Use report files already saved here. No AI call or download.",
        finish_busy="Finishing the locally saved report...",
        finish_failed=("Could not finish the saved report. Its pending version is kept. "
                       "Refresh Current report and check required files before retrying."),
        apply="Use this report...",
        apply_title="Use this retained report?",
        apply_question=("Make this the current report? Previous versions are kept. "
                        "Its captured goal and sources remain historical metadata; "
                        "your current list goal is unchanged."),
        apply_busy="Checking and applying retained report...",
        apply_failed=("Could not complete application. Your retained result is kept. "
                      "Check Current report before retrying."),
        apply_stopped="Stopped. Check Current report; completed writes may already be saved.",
        recorded="Recorded location",
        loading="Reading saved report...",
        inspecting="Verifying original and opening page...",
        empty="No source-aware report is saved for this list. Your editable overview is separate.",
        scope=(
            "Saved quotation locations; original bytes are checked when opened. "
            "Scientific support has not been assessed."
        ),
        ready="Saved report",
        goal="Research goal for this report",
        goal_empty="No research goal was provided.",
        goal_unknown="This older report did not record a research goal.",
        checked="Original checked | page {page} of {pages}",
        cancel="Cancel",
        cancelled="Stopped. Existing research is unchanged.",
        inventory="Source inventory",
        no_passage="No original passage is recorded for this statement.",
        pending=("Saved report files are waiting for local completion. "
                 "Showing the available version."),
        failed=(
            "Could not read the report or original. Refresh to retry; "
            "existing research is unchanged."
        ),
        missing="Original unavailable",
        source="Open original",
        unknown="Location not recorded",
        page="Page",
        closing="Cancelling source inspection...",
        stale="The report or workspace changed. Refresh before continuing.",
        reported="Reported statement",
        inferred="Interpretation",
        unavailable="unavailable",
        captured="captured version",
        not_selected="not selected",
    ),
    "zh-TW": {
        "finish_scope": (
            "\u4f7f\u7528\u5df2\u5132\u5b58\u65bc\u672c\u6a5f\u7684\u5831\u544a\u6a94"
            "\u6848\uff0c\u4e0d\u547c\u53eb AI \u6216\u4e0b\u8f09\u3002"
        ),
        "finish": (
            "\u5b8c\u6210\u5831\u544a\u8f09\u5165"
        ),
        "finish_busy": (
            "\u6b63\u5728\u5b8c\u6210\u5df2\u5132\u5b58\u7684\u672c\u6a5f\u5831\u544a"
            "..."
        ),
        "finish_failed": (
            "\u672a\u80fd\u5b8c\u6210\u5831\u544a\u8f09\u5165\uff0c\u5f85\u5b8c\u6210"
            "\u7248\u672c\u4ecd\u4fdd\u7559\u3002\u8acb\u91cd\u65b0\u6574\u7406\u76ee"
            "\u524d\u5831\u544a\u4e26\u6aa2\u67e5\u6240\u9700\u6a94\u6848\u5f8c\u518d"
            "\u91cd\u8a66\u3002"
        ),

        "apply": (
            "\u5957\u7528\u9019\u4efd\u5831\u544a..."
        ),
        "apply_title": (
            "\u5957\u7528\u4fdd\u7559\u5831\u544a\uff1f"
        ),
        "apply_question": (
            "\u5c07\u9019\u4efd\u5831\u544a\u8a2d\u70ba\u76ee\u524d\u7248\u672c\uff1f"
            "\u820a\u7248\u6703\u4fdd\u7559\u3002\u539f\u7814\u7a76\u76ee\u6a19\u8207"
            "\u4f86\u6e90\u4ecd\u70ba\u6b77\u53f2\u7d00\u9304\uff0c\u4e0d\u6703\u66f4"
            "\u6539\u76ee\u524d\u6e05\u55ae\u7684\u7814\u7a76\u76ee\u6a19\u3002"
        ),
        "apply_busy": (
            "\u6b63\u5728\u6838\u5c0d\u8207\u5957\u7528\u4fdd\u7559\u5831\u544a..."
        ),
        "apply_failed": (
            "\u672a\u80fd\u5b8c\u6210\u5957\u7528\u3002\u4fdd\u7559\u7d50\u679c\u4ecd"
            "\u5728\uff0c\u8acb\u5148\u67e5\u770b\u76ee\u524d\u5831\u544a\u518d\u91cd"
            "\u8a66\u3002"
        ),
        "apply_stopped": (
            "\u5df2\u505c\u6b62\u3002\u8acb\u67e5\u770b\u76ee\u524d\u5831\u544a\uff1b"
            "\u5df2\u5b8c\u6210\u7684\u5beb\u5165\u53ef\u80fd\u5df2\u5132\u5b58\u3002"
        ),

        "results": "\u5df2\u5b8c\u6210\u7684 AI \u7d50\u679c",
        "results_loading": "\u6b63\u5728\u8b80\u53d6\u5df2\u5b8c\u6210\u7684 AI \u7d50\u679c...",
        "results_empty": "\u6b64\u6e05\u55ae\u5c1a\u7121\u4fdd\u7559\u7684 AI \u7d50\u679c\u3002",
        "result_label": "{started} | {model} | {request}",
        "result_scope": (
            "\u4fdd\u7559\u7d50\u679c\uff1a\u6aa2\u8996\u4e0d\u6703\u66f4\u6539\u76ee"
            "\u524d\u6e05\u55ae\u3002\u958b\u555f\u539f\u6587\u6703\u6838\u5c0d\u7576"
            "\u6642\u7684 PDF\uff1b\u5957\u7528\u9019\u4efd\u5831\u544a\u9700\u8981"
            "\u53e6\u884c\u78ba\u8a8d\u3002"
        ),
        "audit": "\u6838\u5c0d\u5168\u90e8\u4f86\u6e90",
        "audit_busy": ("\u6b63\u5728\u6838\u5c0d\u5df2\u5b58\u539f\u6587"
                       "\u8207\u5f15\u7528\u4f4d\u7f6e..."),
        "audit_done": (
            "\u539f\u6587\u5df2\u6838\u5c0d {verified}/{total}\uff1b"
            "\u5df2\u6838\u5c0d\u5b9a\u4f4d\u5f15\u7528 {quotes}\uff1b"
            "\u672a\u5b9a\u4f4d\u5f15\u7528 {unlocated}\u3002"
            "\u5c1a\u672a\u5224\u5b9a\u5b78\u8853\u8ad6\u9ede\u662f\u5426\u6210\u7acb\u3002"
        ),
        "recorded": "\u5df2\u8a18\u9304\u7684\u4f4d\u7f6e",
        "goal": "\u9019\u4efd\u5831\u544a\u7684\u7814\u7a76\u76ee\u6a19",
        "goal_empty": "\u7576\u6642\u672a\u63d0\u4f9b\u7814\u7a76\u76ee\u6a19\u3002",
        "goal_unknown": (
            "\u9019\u4efd\u820a\u5831\u544a\u672a\u8a18\u9304\u7576\u6642"
            "\u7684\u7814\u7a76\u76ee\u6a19\u3002"
        ),
        "checked": "\u539f\u6587\u5df2\u6838\u5c0d | {page} / {pages} \u9801",
        "cancel": "\u53d6\u6d88",
        "cancelled": (
            "\u5df2\u505c\u6b62\u3002\u65e2\u6709\u7814\u7a76\u4e0d\u6703\u6539\u8b8a\u3002"
        ),
        "inventory": "\u4f86\u6e90\u6e05\u55ae",
        "no_passage": "\u6b64\u6558\u8ff0\u5c1a\u672a\u8a18\u9304\u539f\u6587\u6bb5\u843d\u3002",
        "tab": "\u5831\u544a\u8207\u4f86\u6e90",
        "legacy": "\u53ef\u7de8\u8f2f\u6458\u8981",
        "refresh": "\u76ee\u524d\u5831\u544a",
        "loading": "\u6b63\u5728\u8b80\u53d6\u5831\u544a...",
        "inspecting": "\u6b63\u5728\u9a57\u8b49\u539f\u6587\u4e26\u958b\u555f\u9801\u9762...",
        "empty": (
            "\u6b64\u6e05\u55ae\u5c1a\u7121\u9644\u4f86\u6e90\u7684\u5831"
            "\u544a\u3002\u53ef\u7de8\u8f2f\u6458\u8981\u6703\u5206\u958b"
            "\u4fdd\u7559\u3002"
        ),
        "scope": (
            "\u4fdd\u7559\u7684\u5f15\u7528\u4f4d\u7f6e\uff0c\u958b\u555f"
            "\u6642\u624d\u6838\u5c0d\u539f\u6587\u6a94\u6848\u3002\u5c1a"
            "\u672a\u5224\u65b7\u6558\u8ff0\u662f\u5426\u7372\u5f97\u5b78"
            "\u8853\u8b49\u64da\u652f\u6301\u3002"
        ),
        "ready": "\u5df2\u5132\u5b58\u5831\u544a",
        "pending": (
            "\u5831\u544a\u6a94\u6848\u7b49\u5f85\u5b8c\u6210\u672c\u6a5f\u8f09\u5165"
            "\uff0c\u76ee\u524d\u986f\u793a\u53ef\u7528\u7248\u672c\u3002"
        ),
        "failed": (
            "\u7121\u6cd5\u8b80\u53d6\u5831\u544a\u6216\u539f\u6587\u3002"
            "\u8acb\u91cd\u65b0\u6574\u7406\u5f8c\u518d\u8a66\uff0c\u65e2"
            "\u6709\u7814\u7a76\u4e0d\u6703\u6539\u8b8a\u3002"
        ),
        "missing": "\u539f\u6587\u5c1a\u672a\u5099\u59a5",
        "source": "\u958b\u555f\u539f\u6587",
        "unknown": "\u672a\u8a18\u9304\u5f15\u7528\u4f4d\u7f6e",
        "page": "\u9801",
        "closing": "\u6b63\u5728\u53d6\u6d88\u539f\u6587\u6aa2\u8996...",
        "stale": (
            "\u5831\u544a\u6216\u5de5\u4f5c\u5340\u5df2\u8b8a\u52d5\uff0c"
            "\u8acb\u5148\u91cd\u65b0\u6574\u7406\u3002"
        ),
        "reported": "\u8ad6\u6587\u9673\u8ff0",
        "inferred": "\u63a8\u8ad6",
        "unavailable": "\u5c1a\u7121\u539f\u6587",
        "captured": "\u4fdd\u7559\u7684\u539f\u6587\u7248\u672c",
        "not_selected": "\u672a\u9078\u5165\u539f\u6587",
    },
}


def render(data, words, *, source_links=True):
    report = data["report"]
    titles = {source["source_id"]: source["title"] for source in data["sources"]}
    states = {s["id"]: s["state"] for s in report["sources"]}
    titles.update(
        {
            s["id"]: titles.get(
                s["id"],
                next(
                    m["title"]
                    for m in report["inputs"]["members"]
                    if m["paper_id"] == s["paper_id"]
                ),
            )
            for s in report["sources"]
        }
    )

    def escape(value):
        return html.escape(value).replace("\n", "<br>")

    inputs = report["inputs"]
    goal = (inputs["goal"] or words["goal_empty"]) if "goal" in inputs else words["goal_unknown"]
    parts = ["<h3>" + escape(words["goal"]) + "</h3><p>" + escape(goal) + "</p>"]
    for si, section in enumerate(report["sections"]):
        parts.append("<h2>" + escape(section["heading"]) + "</h2>")
        for ti, statement in enumerate(section["statements"]):
            parts.append(
                "<p><small>"
                + escape(words.get(statement["interpretation"], statement["interpretation"]))
                + "</small><br>"
                + escape(statement["text"])
                + "</p>"
            )
            if not statement["passages"]:
                parts.append("<p><small>" + escape(words["no_passage"]) + "</small></p>")
            for qi, passage in enumerate(statement["passages"]):
                label = titles[passage["source_id"]]
                location = passage["location"]
                page = (
                    str(location["page"])
                    if location and location["state"] == "located"
                    else words["unknown"]
                )
                link = (
                    f'<a href="paperfact-source:{si}/{ti}/{qi}">' + escape(words["source"]) + "</a>"
                    if states[passage["source_id"]] == "captured"
                    else escape(words["missing"])
                )
                if not source_links:
                    link = escape(words["recorded"])
                parts.append(
                    "<blockquote>"
                    + escape(passage["quote"])
                    + "<br><small>"
                    + escape(label)
                    + " | "
                    + escape(page)
                    + " | "
                    + link
                    + "</small></blockquote>"
                )
    parts.append("<h3>" + escape(words["inventory"]) + "</h3><ul>")
    for source in report["sources"]:
        parts.append(
            "<li>" + escape(titles[source["id"]]) + " | " + escape(words[source["state"]]) + "</li>"
        )
    parts.append("</ul>")
    return "".join(parts)


class SavedSurveyPane(QWidget):
    available = Signal()
    state_changed = Signal()
    drained = Signal()

    def __init__(self, database, list_id, palette, *, current, language="en", parent=None,
                 autoload=True):
        super().__init__(parent)
        self.database, self.list_id, self.current = database, list_id, current
        self.words = TEXT.get(language, TEXT["en"])
        self.cancelled = Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="saved-survey-read")
        self.future = None
        self.saved = self.selection = None
        self._retained = []
        self._review = None
        self.closing = self.disposed = False
        self._refresh_available = False
        self._reload_queued = False
        self._read_retries = 0
        self._read_retry_pending = False
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.status = QLabel(self.words["loading"])
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.refresh = QPushButton(self.words["refresh"])
        self.refresh.setAutoDefault(False)
        self.stop = QPushButton(self.words["cancel"])
        self.stop.setAutoDefault(False)
        self.stop.clicked.connect(self._stop)
        self.refresh.clicked.connect(self.reload)
        top.addWidget(self.status, 1)
        top.addWidget(self.refresh)
        self.audit_sources = QPushButton(self.words["audit"])
        self.audit_sources.setAutoDefault(False)
        self.audit_sources.clicked.connect(self.check_sources)
        top.addWidget(self.audit_sources)
        self.finish = QPushButton(self.words["finish"])
        self.finish.setAutoDefault(False)
        self.finish.setToolTip(self.words["finish_scope"])
        self.finish.clicked.connect(self.finish_pending)
        top.addWidget(self.finish)
        self.results = QPushButton(self.words["results"])
        self.results.setAutoDefault(False)
        self.results.clicked.connect(self.load_results)
        top.addWidget(self.results)
        self.apply_result = QPushButton(self.words["apply"])
        self.apply_result.setAutoDefault(False)
        self.apply_result.clicked.connect(self.review_result)
        top.addWidget(self.apply_result)
        top.addWidget(self.stop)
        layout.addLayout(top)
        self.result_selector = QComboBox()
        self.result_selector.setAccessibleName(self.words["results"])
        self.result_selector.currentIndexChanged.connect(self._select_result)
        self.result_selector.hide()
        layout.addWidget(self.result_selector)
        notice = QLabel(self.words["scope"])
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumHeight(5)
        layout.addWidget(self.progress)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        self.view.setStyleSheet(
            f"QTextBrowser{{background:{palette['surface']};color:{palette['ink']};"
            f"border:1px solid {palette['border']};padding:16px;font-size:14px;}}"
        )
        split.addWidget(self.view)
        self.source_panel = QWidget()
        source_layout = QVBoxLayout(self.source_panel)
        self.source_title = QLabel()
        self.source_title.setTextFormat(Qt.TextFormat.PlainText)
        self.source_title.setWordWrap(True)
        source_layout.addWidget(self.source_title)
        row = QHBoxLayout()
        row.addWidget(QLabel(self.words["page"]))
        self.page = QSpinBox()
        self.page.setRange(1, 1)
        self.page.valueChanged.connect(self._page)
        row.addWidget(self.page)
        row.addStretch(1)
        source_layout.addLayout(row)
        self.quote = QLabel()
        self.quote.setTextFormat(Qt.TextFormat.PlainText)
        self.quote.setWordWrap(True)
        self.quote.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        source_layout.addWidget(self.quote)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.image = PagePreview()
        scroll.setWidget(self.image)
        source_layout.addWidget(scroll, 1)
        split.addWidget(self.source_panel)
        split.setSizes([650, 450])
        self.source_panel.hide()
        layout.addWidget(split, 1)
        self.poll = QTimer(self)
        self.poll.setInterval(40)
        self.poll.timeout.connect(self._poll)
        self.poll.start()
        cancelled, executor = self.cancelled, self.executor
        self.destroyed.connect(
            lambda: (cancelled.set(), executor.shutdown(wait=False, cancel_futures=True))
        )
        if autoload:
            self.reload()

    def _controls(self):
        idle = self.future is None and not self.closing and not self.disposed and self.current()
        self.refresh.setEnabled(idle and self._review is None)
        self.audit_sources.setEnabled(
            idle and self._review is None and self.saved is not None
            and self.saved.data["kind"] != "none" and self.saved.current())
        self.results.setEnabled(idle and self._review is None)
        archive = self.saved is not None and self.saved.data["kind"] == "retained"
        pending = (self.saved is not None and self.saved.data["kind"] == "native"
                   and self.saved.data["update_pending"])
        self.finish.setVisible(pending)
        self.finish.setEnabled(idle and pending and self._review is None)
        self.apply_result.setVisible(archive)
        self.apply_result.setEnabled(idle and archive and self._review is None)
        self.result_selector.setEnabled(idle and self._review is None)
        self.stop.setVisible(self.future is not None)
        self.stop.setEnabled(self.future is not None and not self.cancelled.is_set())
        self.page.setEnabled(idle and self.selection is not None)
        self.progress.setVisible(self.future is not None)
        self.state_changed.emit()

    def _start(self, call, callback, message):
        if (self.future is not None or self.closing or self.disposed
                or self._review is not None and callback != self._applied):
            return
        self.status.setText(message)
        self.future = (self.executor.submit(call), callback)
        self._controls()

    def check_sources(self):
        saved = self.saved
        if not self.current() or saved is None or not saved.current():
            self._stale()
            self._controls()
            return
        if saved.data["kind"] == "none":
            return
        cancel = self.cancelled.is_set
        self._start(lambda: (saved, survey_audit.audit(saved, cancelled=cancel)),
                    self._sources_checked, self.words["audit_busy"])

    def _sources_checked(self, value):
        saved, result = value
        if self.saved is not saved or not saved.current():
            self._stale()
            return
        self.status.setText(self.words["audit_done"].format(
            verified=result["originals_verified"], total=result["originals_total"],
            quotes=result["verified_located_passages"], unlocated=result["unlocated_passages"]))

    def load_results(self):
        if not self.current():
            self._stale()
            self._controls()
            return
        database, list_id, cancel = self.database, self.list_id, self.cancelled.is_set
        self._start(
            lambda: survey_jobs.list_retained(database, list_id, cancelled=cancel),
            self._results_loaded,
            self.words["results_loading"],
        )

    def _results_loaded(self, results):
        self._retained = results
        self.result_selector.blockSignals(True)
        self.result_selector.clear()
        for item in results:
            generation = item["report"]["generation"]
            self.result_selector.addItem(self.words["result_label"].format(
                started=item["started_at"],
                model=generation["returned_model"] or generation["requested_model"] or "?",
                request=item["request_id"][:12]))
        self.result_selector.blockSignals(False)
        self.result_selector.setVisible(bool(results))
        if results:
            self._select_result(0)
        else:
            self.status.setText(self.words["results_empty"])

    def _select_result(self, index):
        if not self.current():
            self._stale()
            self._controls()
            return
        if (not 0 <= index < len(self._retained) or self.closing or self.disposed
                or self.future is not None):
            return
        self.saved = self.selection = None
        self.source_panel.hide()
        self.image.clear()
        report = self._retained[index]["report"]
        self.view.setHtml(render(dict(report=report, sources=[]), self.words, source_links=False))
        self.status.setText(self.words["result_scope"])
        request_id = self._retained[index]["request_id"]
        database, list_id, cancel = self.database, self.list_id, self.cancelled.is_set
        self._start(
            lambda: survey_reader.read_retained(database, list_id, request_id, cancelled=cancel),
            self._retained_loaded,
            self.words["results_loading"],
        )

    def _retained_loaded(self, result):
        index = self.result_selector.currentIndex()
        if (not result.current() or not 0 <= index < len(self._retained)
                or self._retained[index]["request_id"] != result.data["request_id"]):
            self.status.setText(self.words["stale"])
            return
        self.saved = result
        self.view.setHtml(render(result.data, self.words))
        self.status.setText(self.words["result_scope"])

    def finish_pending(self):
        if (self.future is not None or self._review is not None or self.saved is None
                or not self.current() or self.saved.data["kind"] != "native"
                or not self.saved.data["update_pending"]):
            return
        saved, cancel = self.saved, self.cancelled.is_set
        self._start(lambda: survey_reader.complete_pending(saved, cancelled=cancel),
                    self._finished_pending, self.words["finish_busy"])

    def _finished_pending(self, _operation):
        self.reload()

    def review_result(self):
        if (self.future is not None or self._review is not None or self.saved is None
                or self.saved.data["kind"] != "retained" or not self.current()):
            return
        saved, cancel = self.saved, self.cancelled.is_set
        self._start(lambda: survey_result_review.prepare(saved, cancelled=cancel),
                    self._review_ready, self.words["apply_busy"])

    def _release_review(self):
        value, self._review = self._review, None
        if value is not None:
            value.close()

    def _review_ready(self, value):
        self._review = value
        self._controls()
        summary = value.summary()
        box = QMessageBox(self)
        box.setWindowTitle(self.words["apply_title"])
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(self.words["apply_question"])
        model = summary["generation"]
        goal = (summary["goal"] or self.words["goal_empty"]
                if "goal" in value.original.data["report"]["inputs"]
                else self.words["goal_unknown"])
        box.setDetailedText(
            self.words["goal"] + "\n" + goal
            + "\n\n" + model["backend"] + " / " + (model["requested_model"] or "-")
            + " \u2192 " + (model["returned_model"] or "-")
            + "\n" + self.words["inventory"] + ": " + str(summary["sources"]))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        answer = box.exec()
        if (answer != QMessageBox.StandardButton.Yes or not self.current()
                or self.closing or self.disposed):
            self._release_review()
            self.status.setText(self.words["cancelled"])
            return
        cancel = self.cancelled.is_set
        self._start(lambda: survey_result_review.apply(value, cancelled=cancel),
                    self._applied, self.words["apply_busy"])

    def _applied(self, _result):
        self._release_review()
        self.reload()

    def reload_after_job(self):
        if self.closing or self.disposed or not self.current():
            return
        if self.future is not None:
            self._reload_queued = True
        else:
            self.reload()

    def reload(self, _retry=False):
        if not _retry:
            self._read_retries = 0
        if not self.current():
            self._stale()
            return
        if self.future is not None or self.closing or self.disposed:
            return
        self.saved = self.selection = None
        self._retained = []
        self.result_selector.hide()
        self.source_panel.hide()
        self.view.clear()
        database, list_id, cancel = self.database, self.list_id, self.cancelled.is_set
        self._start(
            lambda: survey_reader.read(database, list_id, cancelled=cancel),
            self._loaded,
            self.words["loading"],
        )

    def _queue_read_retry(self):
        if self._read_retries < 1 and not self.closing and self.current():
            self._read_retries += 1
            self._read_retry_pending = True

    def _loaded(self, result):
        if not result.current():
            self.status.setText(self.words["stale"])
            self._queue_read_retry()
            return
        self.saved = result
        data = result.data
        if data["kind"] == "none":
            self.status.setText(self.words["empty"])
            return
        self.view.setHtml(render(data, self.words))
        self.status.setText(
            self.words["pending"] if data["update_pending"] else self.words["ready"]
        )
        if not self._refresh_available:
            self._refresh_available = True
            self.available.emit()

    def _link(self, url):
        match = re.fullmatch(r"paperfact-source:(\d{1,4})/(\d{1,4})/(\d{1,4})", url.toString())
        if not match or self.future is not None or self.saved is None:
            return
        self.selection = tuple(int(value) for value in match.groups())
        self._inspect()

    def _page(self, value):
        if self.selection is not None:
            self._inspect(page=value)

    def _inspect(self, *, page=None):
        if not self.current():
            self._stale()
            self._controls()
            return
        if self.future is not None or self.saved is None or self.selection is None:
            return
        saved, selection, cancel = self.saved, self.selection, self.cancelled.is_set
        self.source_panel.hide()
        self.image.clear()
        self._start(
            lambda: survey_reader.inspect(saved, *selection, page=page, cancelled=cancel),
            self._inspected,
            self.words["inspecting"],
        )

    def _inspected(self, result):
        if self.saved is None or not self.saved.current():
            self.status.setText(self.words["stale"])
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(result["image"]):
            raise ValueError("Invalid source page image")
        self.source_title.setText(result["title"] + " | " + result["document_hash"][:12])
        self.quote.setText(result["quote"])
        self.page.blockSignals(True)
        self.page.setRange(1, result["pages"])
        self.page.setValue(result["page"])
        self.page.blockSignals(False)
        self.image.set_source(pixmap)
        self.source_panel.show()
        status = (
            self.words["checked"].format(page=result["page"], pages=result["pages"])
            if result["located"]
            else self.words["unknown"]
        )
        if self.saved.data["update_pending"]:
            status += " | " + self.words["pending"]
        if self.saved.data["kind"] == "retained":
            status += " | " + self.words["result_scope"]
        self.status.setText(status)

    def _poll(self):
        if self.future is None or not self.future[0].done():
            return
        future, callback = self.future
        self.future = None
        result, delivered = None, False
        applying = callback in (self._applied, self._finished_pending)
        try:
            result = future.result()
            if not self.closing and self.cancelled.is_set():
                self.status.setText(self.words["apply_stopped" if applying else "cancelled"])
            elif not self.closing and self.current():
                callback(result)
                delivered = True
            elif not self.closing:
                self._stale()
        except survey_reader.ReadChanged:
            if not self.closing:
                self.status.setText(self.words["stale"])
                if callback == self._loaded:
                    self._queue_read_retry()
        except Exception:
            if not self.closing:
                self.status.setText(
                    self.words["apply_stopped" if applying else "cancelled"]
                    if self.cancelled.is_set() else self.words[
                        "finish_failed" if callback == self._finished_pending
                        else "apply_failed" if applying or callback == self._review_ready
                        else "failed"]
                )
        finally:
            if isinstance(result, survey_result_review.Review) and not delivered:
                if self._review is result:
                    self._release_review()
                else:
                    result.close()
            if applying and self._review is not None:
                self._release_review()
        if not self.closing:
            self.cancelled.clear()
        self._controls()
        retry = self._read_retry_pending
        self._read_retry_pending = False
        if self._reload_queued and not self.closing and self.current():
            self._reload_queued = False
            self.reload()
        elif retry and not self.closing and self.current():
            self.reload(_retry=True)
        if self.closing:
            self.dispose()
            self.drained.emit()

    def _stop(self):
        if self.future is not None:
            self.cancelled.set()
            self.status.setText(self.words["closing"])
            self._controls()

    def _stale(self):
        self._retained = []
        self.result_selector.hide()
        self.saved = self.selection = None
        self.view.clear()
        self.source_panel.hide()
        self.status.setText(self.words["stale"])

    def request_close(self):
        if self.future is not None:
            self.closing = True
            self.cancelled.set()
            self.status.setText(self.words["closing"])
            self._controls()
            return False
        self.dispose()
        return True

    def reopen(self):
        if not self.disposed or not self.current():
            return
        self.cancelled = Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="saved-survey-read")
        cancelled, executor = self.cancelled, self.executor
        self.destroyed.connect(
            lambda: (cancelled.set(), executor.shutdown(wait=False, cancel_futures=True))
        )
        self.disposed = self.closing = False
        self.poll.start()
        self.reload()

    def dispose(self):
        if self.disposed:
            return
        self.disposed = True
        if self.future is None:
            self._release_review()
        self.cancelled.set()
        self.poll.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
