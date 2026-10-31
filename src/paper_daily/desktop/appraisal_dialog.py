"""Explicit one-call model appraisal, with local derived-history persistence."""

from __future__ import annotations

import json
import threading

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from paper_daily import ai_choices, audit_appraisal, llm
from paper_daily.appraisal_archive import AppraisalArchive, default_root
from paper_daily.audit_inputs import verify_loaded_source as verify_source
from paper_daily.desktop import activity, ai_style, fonts
from paper_daily.desktop.claim_evidence import ClaimSection, _label
from paper_daily.desktop.flow_layout import FlowLayout
from paper_daily.desktop.settings_style import apply as style_settings

TEXT = {
    "en": {
        "title": ("AI appraisal of claims"),
        "intro": (
            "Select source-pinned claims. Review makes at most one AI call. Locat"
            "ed quotations and model judgments still need your appraisal."
        ),
        "route": ("AI for the next review: "),
        "requested": "Requested model",
        "returned": "Reported model",
        "default_model": "Provider default",
        "unreported_model": "Not reported",
        "settings_unavailable": "AI settings unavailable",
        "settings": ("Account and model..."),
        "review": ("Appraise selected claims"),
        "history": ("Load saved review"),
        "save": ("Retry saving result"),
        "close": ("Back to evidence"),
        "stop": ("Stop"),
        "loading": ("Loading local review history; no AI call..."),
        "working": ("Preparing one captured Audit model call..."),
        "ready": ("Saved model review. Opening or loading it makes no AI call."),
        "failed": ("Review did not finish. Prior findings are retained; retry explicitly."),
        "changed": (
            "Paper, source or saved inputs changed. Reopen this view before starting new work."
        ),
        "empty": ("No saved model review. Choose claims and press Appraise explicitly."),
        "unsaved": (
            "Review completed but could not be saved. Retry saving without another model call."
        ),
        "stale": (
            "Review of the original snapshot is saved; current inputs changed during the call."
        ),
        "cancelled": ("Stopped. A completed model result is retained locally."),
        "selection": "Select claims (1-16)",
        "no_claims": ("Generate source-pinned claim proposals before using model appraisal."),
        "supported": ("Model proposes: supported"),
        "contradicted": ("Model proposes: contradicted"),
        "not_found": ("Model did not find support in the supplied spans"),
        "unverified": ("Proposed evidence could not be located"),
        "source": ("View original passage"),
        "source_failed": ("The exact loaded original is unavailable; no jump occurred."),
        "save_question": ("This completed review has not been saved. Discard it and close?"),
        "budget": (
            "One explicit model call; bounded retrieval is not an exhaustive literature search."
        ),
    },
    "zh-TW": {
        "title": ("AI 核對論點"),
        "intro": ("選擇已綁定原文的論點。每次評閱最多呼叫 1 次 AI；模型判斷與引文仍需研究者核對。"),
        "route": ("下次評閱使用："),
        "requested": "指定模型",
        "returned": "回報模型",
        "default_model": "服務預設",
        "unreported_model": "未回報",
        "settings_unavailable": "目前無法讀取 AI 設定",
        "settings": ("帳號與模型…"),
        "review": ("AI 核對所選論點"),
        "history": ("讀取已存評閱"),
        "save": ("重試儲存結果"),
        "close": ("返回證據檢查"),
        "stop": ("停止"),
        "loading": ("正在讀取本機評閱紀錄，不呼叫 AI…"),
        "working": ("正在準備已選定 AI 的單次評閱…"),
        "ready": ("顯示已儲存的模型評閱，讀取不會呼叫 AI。"),
        "failed": ("評閱未完成；原有結果已保留，請手動重試。"),
        "changed": ("論文、原文或內容已改變，請重新開啟後再開始新評閱。"),
        "empty": ("尚無已存評閱；選擇論點後再按 AI 核對。"),
        "unsaved": ("評閱已完成但尚未存下。可重試儲存，不會再呼叫 AI。"),
        "stale": ("原文快照的評閱已保留；執行期間目前內容已改變。"),
        "cancelled": ("已停止；已完成的模型結果仍會保留於本機。"),
        "selection": "選擇論點（1–16）",
        "no_claims": ("請先產生有原文來源的論點提案。"),
        "supported": ("模型判斷：有支持"),
        "contradicted": ("模型判斷：有矛盾"),
        "not_found": ("模型在提供的片段中未找到支持"),
        "unverified": ("提出的證據未能定位"),
        "source": ("核對原文"),
        "source_failed": ("目前無法核對對應原文，未跳轉。"),
        "save_question": ("這份已完成評閱尚未存下，要放棄並關閉嗎？"),
        "budget": ("每次最多 1 次 AI 呼叫；限量檢索不代表完整文獻調查。"),
    },
}


class Worker(QThread):
    progress = Signal(str)

    def __init__(self, call, parent):
        super().__init__(parent)
        self.call = call
        self.cancelled = threading.Event()
        self.result = self.error = None

    def run(self):
        try:
            self.result = self.call(self.cancelled.is_set, self.progress.emit)
        except Exception as error:
            self.error = getattr(error, "code", type(error).__name__)


class AppraisalDialog(QDialog):
    def __init__(
        self,
        capture,
        *,
        owner=None,
        current_view=None,
        source_callback=None,
        archive_root=None,
        language="zh-TW",
        parent=None,
        paper_title=None,
        job_factory=audit_appraisal.AppraisalJob.prepare,
        archive_factory=AppraisalArchive,
    ):
        super().__init__(parent)
        style_settings(self)
        from paper_daily.desktop.main import palette

        colors = palette()
        self.setStyleSheet(
            self.styleSheet()
            + f"""
            QToolButton {{ color:{colors["ink"]}; background:{colors["sunk"]};
                border:1px solid {colors["border"]}; border-radius:6px;
                padding:6px 10px; text-align:left; }}
            QToolButton:hover {{ border-color:{colors["accent"]}; }}
            QToolButton:focus {{ border:2px solid {colors["accent"]}; }}
            QToolButton:checked {{ background:{colors["accentSoft"]}; }}
        """
        )
        self.setFont(fonts.font(pixels=13))
        self.capture, self.owner = capture, owner
        self.current_view = current_view
        self.view = current_view() if current_view else None
        self.source_callback = source_callback
        self.job_factory = job_factory
        self.archive = archive_factory(
            archive_root if archive_root is not None else default_root(), capture
        )
        self.t = TEXT.get(language, TEXT["en"])
        self.disposed = self._closing = False
        self._worker = None
        self._handle = activity.Handle()
        self.report = self.job = None
        self.unsaved = None
        self.checks = {}
        self.source_buttons = []
        self._invalid = False
        self.setWindowTitle(self.t["title"])
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(720, 720)
        self.items = {
            item["id"]: item
            for item in json.loads(capture._items_json)
            if item["feature"] == "claims"
            and item["document_hash"] == capture.snapshot.source["document_hash"]
        }
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        heading = _label(self.t["title"])
        heading.setStyleSheet("font-size:22px;font-weight:600;")
        layout.addWidget(heading)
        layout.addWidget(
            _label(
                (paper_title or capture.paper_id)
                + " / "
                + capture.snapshot.source["document_hash"][:10]
            )
        )
        layout.addWidget(_label(self.t["intro"]))
        row = QHBoxLayout()
        self.route = _label("")
        row.addWidget(self.route, 1)
        self.settings_button = QPushButton(self.t["settings"])
        self.settings_button.clicked.connect(self.settings)
        row.addWidget(self.settings_button)
        layout.addLayout(row)
        self.selection = ClaimSection(self.t["selection"], expanded=True)
        choices_body = QWidget()
        choices_layout = QVBoxLayout(choices_body)
        choices_layout.setContentsMargins(0, 0, 8, 0)
        choices_scroll = QScrollArea()
        choices_scroll.setWidgetResizable(True)
        choices_scroll.setWidget(choices_body)
        choices_scroll.setMaximumHeight(180)
        self.selection.content.addWidget(choices_scroll)
        for index, (identity, item) in enumerate(self.items.items()):
            check = QCheckBox(str(index + 1))
            check.setChecked(index < 16)
            self.checks[identity] = check
            selected_row = QHBoxLayout()
            selected_row.addWidget(check, 0, Qt.AlignmentFlag.AlignTop)
            selected_row.addWidget(_label(item["text"]), 1)
            choices_layout.addLayout(selected_row)
            check.toggled.connect(self._controls)
        if not self.items:
            self.selection.content.addWidget(_label(self.t["no_claims"]))
        self.selection.setMaximumHeight(230)
        layout.addWidget(self.selection)
        actions = FlowLayout()
        self.review_button = QPushButton(self.t["review"])
        self.review_button.clicked.connect(self.review)
        ai_style.mark(self.review_button)
        self.history_button = QPushButton(self.t["history"])
        self.history_button.clicked.connect(self.load)
        self.save_button = QPushButton(self.t["save"])
        self.save_button.clicked.connect(self.save)
        for b in (self.review_button, self.history_button, self.save_button):
            actions.addWidget(b)
            b.setAutoDefault(False)
        layout.addLayout(actions)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll, 1)
        self.status = _label(self.t["loading"])
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(5)
        layout.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.stop_button = QPushButton(self.t["stop"])
        self.stop_button.clicked.connect(self.cancel)
        close = QPushButton(self.t["close"])
        close.clicked.connect(self.close)
        bottom.addWidget(self.stop_button)
        bottom.addStretch()
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self.poll = QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self._tick)
        self.poll.start()
        self._route()
        self._controls()
        QTimer.singleShot(0, self.load)

    @property
    def busy(self):
        return self._worker is not None

    def _same(self):
        try:
            return not self.disposed and (
                self.current_view is None or self.current_view() == self.view
            )
        except (OSError, ValueError, RuntimeError):
            return False

    def _tick(self):
        if self.disposed:
            return
        if not self._same() or not self.capture.current():
            self._invalid = True
            if self.busy:
                self.cancel()
            elif self.unsaved is None:
                self.status.setText(self.t["changed"])
        self._controls()

    def _controls(self, *_args):
        current = self._same() and not self._invalid and self.capture.current()
        count = sum(check.isChecked() for check in self.checks.values())
        self.review_button.setEnabled(
            current and not self.busy and 1 <= count <= 16 and self.unsaved is None
        )
        self.history_button.setEnabled(current and not self.busy and self.unsaved is None)
        self.settings_button.setEnabled(current and not self.busy)
        self.save_button.setVisible(self.unsaved is not None)
        self.save_button.setEnabled(not self.busy and self.unsaved is not None)
        self.progress.setVisible(self.busy)
        self.stop_button.setVisible(self.busy)
        for check in self.checks.values():
            check.setEnabled(current and not self.busy)
        for button in self.source_buttons:
            button.setEnabled(current and not self.busy)

    def _route(self):
        try:
            self.route.setText(
                self.t["route"] + ai_choices.connection_label(llm.settings(task="audit"))
            )
        except (ValueError, OSError):
            self.route.setText(self.t["route"] + self.t["settings_unavailable"])

    def settings(self):
        if self.busy or not self._same() or self._invalid:
            return
        from paper_daily.desktop.ai_picker import AIPickerDialog

        dialog = AIPickerDialog(self, task="audit")
        dialog.exec()
        dialog.deleteLater()
        self._route()

    def _start(self, kind, call, *, allow_stale=False):
        if self.busy or self.disposed or not allow_stale and (not self._same() or self._invalid):
            return False
        self._kind = kind
        worker = Worker(call, self)
        self._worker = worker
        worker.progress.connect(self._progress)
        worker.finished.connect(self._finished)
        self._handle = activity.begin(
            self, self.t["title"], task="audit", key=f"appraisal:{id(self)}"
        )
        self._controls()
        worker.start()
        return True

    def _progress(self, message):
        stages = (
            {
                "retrieval": "Retrieving original-source passages...",
                "model": "Waiting for the captured model appraisal...",
                "verification": "Locating the proposed quotations in the original...",
                "saving": "Saving this review locally...",
            }
            if self.t is TEXT["en"]
            else {
                "retrieval": "正在檢索原文片段…",
                "model": "等待已選定模型的評閱…",
                "verification": "正在原文定位模型提出的引文…",
                "saving": "正在儲存本機評閱…",
            }
        )
        message = stages.get(message, message)
        if self._same() and not self._closing:
            self.status.setText(message)
            self._handle.stage(message)

    def load(self):
        if self.unsaved is not None:
            return False
        self.status.setText(self.t["loading"])
        return self._start("load", lambda cancelled, progress: self.archive.current(self.capture))

    def review(self):
        if self.busy or self._invalid or not self._same() or self.unsaved is not None:
            return False
        selected = [key for key, check in self.checks.items() if check.isChecked()]
        if not 1 <= len(selected) <= 16:
            return False
        connections = llm.capture_connections()
        capture = self.capture
        self.status.setText(self.t["working"])

        def call(cancelled, progress):
            if cancelled():
                raise ValueError("Cancelled before appraisal")
            task = self.job_factory(capture, selected, connections=connections, max_calls=1)
            report = task.run(cancelled=cancelled, progress=progress)
            saved = False
            try:
                progress("saving")
                self.archive.save(report)
                saved = True
            except (OSError, ValueError):
                pass
            return dict(job=task, report=report, saved=saved)

        return self._start("review", call)

    def save(self):
        if self.unsaved is None:
            return False
        report = self.unsaved
        return self._start(
            "save", lambda cancelled, progress: self.archive.save(report), allow_stale=True
        )

    def _finished(self):
        worker = self._worker
        if worker is None:
            return
        self._worker = None
        if not worker.error and self._kind == "review":
            self.job = worker.result["job"]
            self.report = worker.result["report"]
            self.unsaved = None if worker.result["saved"] else self.report
            self._render()
        if worker.error:
            self.status.setText(self.t["unsaved"] if self.unsaved else self.t["failed"])
        elif self._kind == "load":
            if self._same() and self.capture.current() and not self._invalid:
                self.report = worker.result[0]["report"] if worker.result else None
                self._render()
                self.status.setText(self.t["ready"] if self.report else self.t["empty"])
            else:
                self.status.setText(self.t["changed"])
        elif self._kind == "save":
            self.unsaved = None
            self.status.setText(self.t["ready"])
        elif self._kind == "source":
            self.status.setText(
                self.t["source"]
                if worker.result
                and self._same()
                and self.capture.current()
                and not self._invalid
                and self.source_callback is not None
                and self.source_callback(self._source)
                else self.t["source_failed"]
            )
        elif self.unsaved is not None:
            self.status.setText(self.t["unsaved"])
        elif not self._same() or self._invalid or not self.report["inputs_current"]:
            self.status.setText(self.t["stale"])
        elif worker.cancelled.is_set():
            self.status.setText(self.t["cancelled"])
        else:
            self.status.setText(self.t["ready"])
        self._handle.finish(ok=worker.error is None, message=self.status.text())
        worker.deleteLater()
        self._controls()
        if self._closing:
            if self.unsaved is None:
                self.close()
            else:
                self._closing = False

    def _render(self):
        self.source_buttons = []
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        if self.report is not None:
            generation = self.report["generation"]
            model = (
                self.t["requested"]
                + ": "
                + (generation["requested_model"] or self.t["default_model"])
                + " / "
                + self.t["returned"]
                + ": "
                + (generation["returned_model"] or self.t["unreported_model"])
            )
            layout.addWidget(_label(generation["backend"] + " / " + model))
            layout.addWidget(_label(self.t["budget"]))
            for index, finding in enumerate(self.report["findings"]):
                section = ClaimSection(
                    str(index + 1) + " / " + self.t[finding["proposed_status"]], expanded=True
                )
                item = self.items.get(finding["item_id"])
                if item:
                    section.content.addWidget(_label(item["text"]))
                section.content.addWidget(_label(finding["reason"]))
                if finding["state"] == "evidence_unverified":
                    section.content.addWidget(_label(self.t["unverified"]))
                for passage in finding["evidence"]:
                    section.content.addWidget(_label(passage["quote"]))
                    if (
                        passage["state"] == "located"
                        and self.owner is not None
                        and self.source_callback is not None
                    ):
                        button = QPushButton(self.t["source"])
                        button.clicked.connect(
                            lambda _checked=False, p=passage: self.open_source(p)
                        )
                        self.source_buttons.append(button)
                        section.content.addWidget(button)
                layout.addWidget(section)
        layout.addStretch()
        old = self.scroll.takeWidget()
        self.scroll.setWidget(body)
        if old is not None:
            old.deleteLater()
        self._controls()

    def open_source(self, passage):
        if (
            self.busy
            or self._invalid
            or not self._same()
            or not self.capture.current()
            or self.report is None
            or passage["state"] != "located"
            or self.owner is None
            or not any(passage == p for f in self.report["findings"] for p in f["evidence"])
        ):
            return False
        digest = self.report["source"]["document_hash"]
        self._source = dict(
            kind="audit",
            document_hash=digest,
            anchor=passage["anchor"],
            page=passage["page"],
            text=passage["quote"],
        )
        return self._start(
            "source",
            lambda cancelled, progress: verify_source(
                self.owner, self.capture.snapshot._origin, digest, cancelled
            ),
        )

    def cancel(self):
        if self._worker:
            self._worker.cancelled.set()
            message = (
                "Stopping safely; an in-flight model call may still finish."
                if self.t is TEXT["en"]
                else (
                    "\u6b63\u5728\u5b89\u5168\u505c\u6b62\uff1b"
                    "\u57f7\u884c\u4e2d\u7684\u6a21\u578b\u547c\u53eb\u4ecd\u53ef\u80fd\u5b8c\u6210\u3002"
                )
            )
            self.status.setText(message)
            self._handle.stage(message)

    def reject(self):
        # Escape must preserve the same active-worker/unsaved-result guards.
        self.close()

    def closeEvent(self, event):
        if self.busy:
            self._closing = True
            self.cancel()
            event.ignore()
            return
        if self.unsaved is not None:
            choice = QMessageBox.question(
                self,
                self.t["title"],
                self.t["save_question"],
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if choice != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        self.disposed = True
        # Retain the small result/history, not a closed view's entire PDF snapshot.
        self.capture = self.job = None
        self.poll.stop()
        self._handle.finish()
        QDialog.reject(self)
        event.accept()
