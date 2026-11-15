"""Saved list-report reading and original-page inspection, separate from editing."""

from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from paper_daily import survey_reader
from paper_daily.desktop.note_source_dialog import PagePreview

TEXT = {
    "en": dict(
        tab="Report & sources",
        legacy="Editable overview",
        refresh="Refresh",
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
        pending="An updated report is pending. Showing the retained version.",
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
        "refresh": "\u91cd\u65b0\u6574\u7406",
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
            "\u65b0\u7248\u5831\u544a\u5c1a\u672a\u5099\u59a5\uff0c\u76ee"
            "\u524d\u986f\u793a\u4fdd\u7559\u7684\u7248\u672c\u3002"
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


def render(data, words):
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
    drained = Signal()

    def __init__(self, database, list_id, palette, *, current, language="en", parent=None):
        super().__init__(parent)
        self.database, self.list_id, self.current = database, list_id, current
        self.words = TEXT.get(language, TEXT["en"])
        self.cancelled = Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="saved-survey-read")
        self.future = None
        self.saved = self.selection = None
        self.closing = self.disposed = False
        self._refresh_available = False
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
        top.addWidget(self.stop)
        layout.addLayout(top)
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
        self.reload()

    def _controls(self):
        idle = self.future is None and not self.closing and not self.disposed and self.current()
        self.refresh.setEnabled(idle)
        self.stop.setVisible(self.future is not None)
        self.stop.setEnabled(self.future is not None and not self.cancelled.is_set())
        self.page.setEnabled(idle and self.selection is not None)
        self.progress.setVisible(self.future is not None)

    def _start(self, call, callback, message):
        if self.future is not None or self.closing or self.disposed:
            return
        self.status.setText(message)
        self.future = (self.executor.submit(call), callback)
        self._controls()

    def reload(self):
        if not self.current():
            self._stale()
            return
        if self.future is not None or self.closing or self.disposed:
            return
        self.saved = self.selection = None
        self.source_panel.hide()
        self.view.clear()
        database, list_id, cancel = self.database, self.list_id, self.cancelled.is_set
        self._start(
            lambda: survey_reader.read(database, list_id, cancelled=cancel),
            self._loaded,
            self.words["loading"],
        )

    def _loaded(self, result):
        if not result.current():
            self.status.setText(self.words["stale"])
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
        self.status.setText(status)

    def _poll(self):
        if self.future is None or not self.future[0].done():
            return
        future, callback = self.future
        self.future = None
        try:
            result = future.result()
            if not self.closing and self.cancelled.is_set():
                self.status.setText(self.words["cancelled"])
            elif not self.closing and self.current():
                callback(result)
            elif not self.closing:
                self._stale()
        except Exception:
            if not self.closing:
                self.status.setText(
                    self.words["cancelled"] if self.cancelled.is_set() else self.words["failed"]
                )
        if not self.closing:
            self.cancelled.clear()
        self._controls()
        if self.closing:
            self.dispose()
            self.drained.emit()

    def _stop(self):
        if self.future is not None:
            self.cancelled.set()
            self.status.setText(self.words["closing"])
            self._controls()

    def _stale(self):
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
        self.cancelled.set()
        self.poll.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
