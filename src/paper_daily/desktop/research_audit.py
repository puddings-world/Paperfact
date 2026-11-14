"""Saved-output audit cards: explicit refresh, local computation, no model calls."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from paper_daily import audit_inputs
from paper_daily.audit_inputs import verify_loaded_source as verify_source
from paper_daily.desktop import activity, fonts
from paper_daily.desktop.claim_evidence import ClaimSection, _label
from paper_daily.desktop.flow_layout import FlowLayout

TEXT = {
    "en": {
        "title": ("Check saved evidence"),
        "heading": ("Evidence checks"),
        "refresh": ("Check again"),
        "intro": (
            "Checks saved quotations, source versions, number occurrences and cit"
            "ation metadata. These are findings to review, not an assessment of s"
            "cientific validity. No AI call."
        ),
        "working": ("Reading saved analysis and the owned original snapshot..."),
        "ready": ("Checked {items} saved items; {checks} checks. Semantic support is not checked."),
        "empty": ("No saved content to check. Read or analyze this paper first."),
        "failed": (
            "Check could not finish. Saved research is unchanged; reopen the original or retry."
        ),
        "changed": (
            "Paper, source or saved research changed. Reopen this check before navigating."
        ),
        "stop": ("Stop"),
        "stopping": ("Stopping after the current local check..."),
        "close": ("Return to reading"),
        "source": ("View original passage"),
        "source_failed": ("The exact loaded original is unavailable. No jump occurred."),
        "source_working": ("Verifying the loaded original before navigating..."),
        "attention": ("Only items needing review"),
        "all": ("Show all saved items"),
        "count": ("Showing {shown} of {total} saved items; {checks} local checks. "
                  "Semantic support is not checked."),
        "filtered_empty": ("No technical findings match this filter. "
                           "{total} saved items are hidden. "
                           "This does not assess scientific validity."),
        "unknown": ("Source version not recorded; no source check is claimed."),
        "no_checks": ("No supported deterministic checks in this item."),
        "limits": (
            "Not checked: semantic support, image-only text, scientific interpret"
            "ation, author identity, full reference resolution, decks, list surve"
            "ys and other originals referenced by lineage. Only the loaded original is checked."
        ),
        "linked_analysis_missing": (
            'Linked highlight record is unavailable; no qu'
            'otation borrowed.'
        ),
        "linked_analysis_changed": (
            "Explanation or highlight content changed, or the old link cannot be verified. "
            "Saved text is preserved; review this link again."
        ),
        "linked_source_mismatch": (
            'Linked highlight belongs to a different origi'
            'nal; no quotation borrowed.'
        ),
        "linked_quote_unavailable": (
            'Recorded quote index is unavailable in the li'
            'nked highlights.'
        ),
        "located": ("Quote located"),
        "missing": ("Quote not found"),
        "ambiguous": ("Several possible locations"),
        "invalid_page": ("Page outside this document"),
        "invalid_anchor": ("Recorded anchor does not resolve"),
        "source_unknown": ("Source version unknown"),
        "source_mismatch": ("Another original or version; inspect its recorded source"),
        "observed": ("Number/unit occurs in the original; interpretation unchecked"),
        "not_observed": ("Number/unit not observed; may be derived or present only in an image"),
        "doi_mismatch": ("DOI identities differ"),
        "title_similar": ("Titles look similar; identity remains unchecked"),
        "title_mismatch_candidate": ("Titles differ; inspect the resolved paper"),
        "identity_not_checked": ("Reference identity unresolved"),
        "title_only": ("Title-only evidence"),
        "citing_context_missing": ("No citing passage recorded"),
        "context_requires_appraisal": ("Citing context needs appraisal"),
    },
    "zh-TW": {
        "count": "顯示 {shown}／{total} 筆已存項目；{checks} 項本機檢查。語意支持尚未檢核。",
        "filtered_empty": ("此篩選沒有符合的技術檢查結果，已隱藏 {total} 筆已存項目；"
                           "不代表科學有效性。"),
        'linked_analysis_missing': (
            '\u9023\u7d50\u7684\u91cd\u9ede\u7d00\u9304\u4e0d'
            '\u53ef\u7528\uff1b\u672a\u501f\u7528\u5176\u4ed6'
            '\u5f15\u6587\u3002'
        ),
        'linked_analysis_changed': (
            "講解或重點內容已變更，或舊連結無法核實。內容已保留，請重新核對連結。"
        ),
        'linked_source_mismatch': (
            '\u9023\u7d50\u7684\u91cd\u9ede\u5c6c\u65bc\u4e0d'
            '\u540c\u539f\u6587\uff1b\u672a\u501f\u7528\u5176'
            '\u4ed6\u5f15\u6587\u3002'
        ),
        'linked_quote_unavailable': (
            '\u9023\u7d50\u91cd\u9ede\u4e2d\u627e\u4e0d\u5230'
            '\u8a18\u9304\u7684\u5f15\u6587\u7d22\u5f15\u3002'
        ),
        "title": ("檢查已儲存的證據"),
        "heading": ("證據檢查"),
        "refresh": ("重新檢查"),
        "intro": (
            "核對引文、原文版本、數字與引用資訊。結果供人工審閱，不代表科學結論已驗證。不呼叫 AI。"
        ),
        "working": ("正在讀取已存分析與原文快照…"),
        "ready": ("已檢查 {items} 項內容，共 {checks} 項檢查結果。語意支持關係仍需核對。"),
        "empty": ("尚無可檢查的儲存內容。"),
        "failed": ("檢查未完成；既有研究已保留。請重新開啟原文或重試。"),
        "changed": ("論文、原文或已存內容已變更，請重新開啟檢查。"),
        "stop": ("停止"),
        "stopping": ("完成目前本機檢查後停止…"),
        "close": ("返回閱讀"),
        "source": ("核對原文"),
        "source_failed": ("目前無法核對對應原文，未跳轉。"),
        "source_working": ("正在核對已載入原文…"),
        "attention": ("只看待核對項目"),
        "all": ("顯示所有內容"),
        "unknown": ("未記錄原文版本，不宣稱已完成原文核對。"),
        "no_checks": ("此項內容沒有支援的確定性檢查。"),
        "limits": (
            "未檢查：語意支持、圖片內文字、科學詮釋、作者身分、完整引用解析、簡報、清"
            "單綜述與研究脈絡引用的其他原文。僅核對目前開啟的原文。"
        ),
        "located": ("已定位引文"),
        "missing": ("找不到引文"),
        "ambiguous": ("引文有多個可能位置"),
        "invalid_page": ("頁碼超出原文"),
        "invalid_anchor": ("已存位置無法對應引文"),
        "source_unknown": ("原文版本未知"),
        "source_mismatch": ("對應其他原文或版本，請開啟該來源核對"),
        "observed": ("原文有相同數字與單位；詮釋仍待核對"),
        "not_observed": ("原文文字未見此數值，可能是推導或圖內資料"),
        "doi_mismatch": ("DOI 身分不一致"),
        "title_similar": ("標題相似，論文身分仍待核對"),
        "title_mismatch_candidate": ("標題不同，請檢查解析到的論文"),
        "identity_not_checked": ("引用身分尚未解析"),
        "title_only": ("只有標題依據"),
        "citing_context_missing": ("未記錄引用句"),
        "context_requires_appraisal": ("引用語境仍需人工判讀"),
    },
}
TEXT["en"]["source_owner_mismatch"] = (
    "Recorded source belongs to another paper; equal PDF bytes do not verify that owner."
)
TEXT["zh-TW"]["source_owner_mismatch"] = (
    "記錄的來源屬於另一篇論文；即使 PDF 內容相同，也不代表已核實該來源。"
)


FEATURE_TEXT = {
    "en": {
        "reading_links": "Explanation link (semantic support unchecked)",
        "research_questions": "Research question and rationale",
        "paper_context": "Research context / reading recommendation",
        "dive": "Deep explanation",
        "close_reading": "Close reading",
        "answer": "Answer",
        "note": "Research note",
        "claims": "Claim",
        "highlights": "Original passage",
        "citations": "Reference",
        "followups": "Later work",
        "lineage": "Research lineage",
    },
    "zh-TW": {
        "reading_links": (
            '\u89e3\u91cb\u9023\u7d50\uff08\u8a9e\u610f\u652f'
            '\u6301\u672a\u6aa2\u6838\uff09'
        ),
        "research_questions": "\u7814\u7a76\u554f\u984c\u8207\u7406\u7531",
        "paper_context": "\u7814\u7a76\u8108\u7d61 / \u95b1\u8b80\u5efa\u8b70",
        "dive": "\u6df1\u5ea6\u8b1b\u89e3",
        "close_reading": "\u9010\u7bc0\u7cbe\u8b80",
        "answer": "\u554f\u7b54",
        "note": "\u7814\u7a76\u7b46\u8a18",
        "claims": "\u8ad6\u9ede",
        "highlights": "\u539f\u6587\u91cd\u9ede",
        "citations": "\u53c3\u8003\u6587\u737b",
        "followups": "\u5f8c\u7e8c\u7814\u7a76",
        "lineage": "\u7814\u7a76\u8108\u7d61",
    },
}
SAFE_STATES = {"located", "observed"}


class Worker(QThread):
    progress = Signal(object)

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


class AuditDialog(QDialog):
    def __init__(
        self,
        database,
        paper_id,
        *,
        document,
        owner=None,
        current_view=None,
        source_callback=None,
        language="zh-TW",
        parent=None,
        paper_title=None,
        capture=audit_inputs.AuditCapture.capture,
    ):
        super().__init__(parent)
        self.path, self.paper_id = Path(database).resolve(strict=True), paper_id
        self.document, self.owner = document, owner
        self.paper_title = paper_title or paper_id
        self._appraisal_dialog = None
        self._source_fact_dialog = None
        self.current_view = current_view
        self.view = current_view() if current_view else None
        self.capture = capture
        self.source_callback = source_callback
        self.t = TEXT.get(language, TEXT["en"])
        self.features = FEATURE_TEXT.get(language, FEATURE_TEXT["en"])
        self.report = self.captured = None
        self._worker = None
        self.disposed = self._closing = False
        self.source_buttons = []
        self.sections = []
        self._handle = activity.Handle()
        self.setWindowTitle(self.t["title"])
        self.setFont(fonts.font(pixels=13))
        self.resize(740, 660)
        from paper_daily.desktop.main import palette

        p = palette()
        self.setStyleSheet(f"""
            QDialog {{background:{p["ground"]};color:{p["ink"]};}}
            QLabel {{color:{p["ink"]};background:transparent;}}
            QLabel[role=muted] {{color:{p["muted"]};font-size:12px;}}
            QLabel[role=title] {{font-size:22px;font-weight:600;}}
            QFrame[role=card] {{background:{p["surface"]};border:1px solid {p["border"]};
                border-radius:8px;}}
            QScrollArea {{border:0;background:{p["ground"]};}}
            QPushButton {{padding:6px 12px;border:1px solid {p["firm"]};border-radius:6px;
                background:{p["surface"]};color:{p["ink"]};}}
            QPushButton:hover {{border-color:{p["accent"]};background:{p["accentSoft"]};}}
            QPushButton:pressed {{background:{p["sunk"]};}}
            QPushButton:focus,QToolButton:focus {{border:2px solid {p["accent"]};}}
            QPushButton:disabled {{color:{p["faint"]};border-color:{p["border"]};}}
            QToolButton {{color:{p["ink"]};text-align:left;background:transparent;
                border:1px solid transparent;}}
            QToolButton:hover {{background:{p["sunk"]};}}
            QProgressBar {{max-height:5px;border:0;background:{p["sunk"]};}}
            QProgressBar::chunk {{background:{p["accent"]};}}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        title = _label(self.t["heading"])
        title.setProperty("role", "title")
        layout.addWidget(title)
        intro = _label(self.t["intro"])
        intro.setProperty("role", "muted")
        layout.addWidget(intro)
        top = FlowLayout()
        self.refresh_button = QPushButton(self.t["refresh"])
        self.refresh_button.clicked.connect(self.refresh)
        self.filter = QCheckBox(self.t["attention"])
        self.filter.setChecked(True)
        self.filter.toggled.connect(self._render)
        top.addWidget(self.refresh_button)
        self.appraisal_button = QPushButton(
            "AI \u6838\u5c0d\u8ad6\u9ede\u2026" if language == "zh-TW" else "AI appraise claims..."
        )
        self.appraisal_button.clicked.connect(self.open_appraisal)
        top.addWidget(self.appraisal_button)
        self.compare_button = QPushButton(
            "比對陳述…" if language == "zh-TW" else "Compare statements…"
        )
        self.compare_button.setObjectName("compareStatements")
        self.compare_button.setAutoDefault(False)
        self.compare_button.clicked.connect(self.open_source_facts)
        top.addWidget(self.compare_button)
        top.addWidget(self.filter)
        layout.addLayout(top)
        self.visible_count = _label("")
        self.visible_count.setObjectName("auditVisibleCount")
        self.visible_count.setProperty("role", "muted")
        layout.addWidget(self.visible_count)
        self.show_all_button = None
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll, 1)
        self.status = _label(self.t["working"])
        self.status.setProperty("role", "muted")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
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
        for button in (self.refresh_button, self.stop_button, close):
            button.setAutoDefault(False)
        self._controls()
        self.poll = QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self._tick)
        self.poll.start()
        QTimer.singleShot(0, self.refresh)

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

    def open_appraisal(self):
        if self.busy or not self._same() or self.captured is None or not self.captured.current():
            return None
        existing = self._appraisal_dialog
        if existing is not None and not existing.disposed:
            existing.show()
            existing.raise_()
            return existing
        from paper_daily.desktop.appraisal_dialog import AppraisalDialog

        self._appraisal_dialog = AppraisalDialog(
            self.captured,
            owner=self.owner,
            current_view=self.current_view,
            source_callback=self.source_callback,
            paper_title=self.paper_title,
            language="zh-TW" if self.t is TEXT["zh-TW"] else "en",
            parent=self,
        )
        self._appraisal_dialog.open()
        return self._appraisal_dialog

    def _tick(self):
        if self.disposed:
            return
        children = (self._appraisal_dialog, self._source_fact_dialog)
        if self._closing and not self.busy and all(c is None or c.disposed for c in children):
            self.close()
            return
        if not self._same():
            self.cancel()
            self.status.setText(self.t["changed"])
        elif self.captured is not None and not self.captured.current() and not self.busy:
            self.status.setText(self.t["changed"])
        self._controls()

    def _controls(self):
        same = self._same()
        self.refresh_button.setEnabled(same and not self.busy)
        self.compare_button.setEnabled(
            same and not self.busy and self.captured is not None and bool(self.report["items"])
        )
        eligible = bool(
            self.report
            and any(
                item["feature"] == "claims"
                and item["document_hash"] == self.report["source"]["document_hash"]
                for item in self.report["items"]
            )
        )
        self.appraisal_button.setEnabled(
            same
            and not self.busy
            and eligible
            and self.captured is not None
            and self.captured.current()
        )
        self.filter.setEnabled(not self.busy)
        if self.show_all_button is not None:
            self.show_all_button.setEnabled(same and not self.busy)
        self.progress.setVisible(self.busy)
        self.stop_button.setVisible(self.busy)
        source_current = self.captured is not None and self.captured.current()
        for button in self.source_buttons:
            button.setEnabled(same and source_current and not self.busy and self.owner is not None)

    def _start(self, kind, call):
        if self.busy or not self._same():
            return False
        self._kind = kind
        worker = Worker(call, self)
        self._worker = worker
        worker.progress.connect(self._progress)
        worker.finished.connect(self._finished)
        self._handle = activity.begin(
            self, self.t["heading"], task="audit", key=f"{id(self)}:audit", paper_id=self.paper_id
        )
        self.progress.setRange(0, 0)
        self._controls()
        worker.start()
        return True

    def _progress(self, value):
        if not self.disposed and self._same() and not self._closing:
            done, total = value
            self.status.setText(f"{done} / {total}")
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(done)
            self._handle.update(dict(stage=self.status.text(), completed=done, total=total))

    def refresh(self):
        if self.busy or not self._same():
            return False
        self.status.setText(self.t["working"])
        database, paper, document, owner = self.path, self.paper_id, self.document, self.owner

        def run(cancelled, progress):
            captured = self.capture(database, paper, document=document, owner=owner)
            report = captured.run(cancelled=cancelled, progress=lambda d, t: progress((d, t)))
            return captured, report

        return self._start("audit", run)

    def _finished(self):
        worker = self._worker
        if worker is None:
            return
        self._worker = None
        if self._closing:
            self._handle.finish()
            worker.deleteLater()
            self.close()
            return
        if not self._same():
            self.status.setText(self.t["changed"])
        elif worker.error or worker.cancelled.is_set():
            self.status.setText(self.t["failed"])
        elif self._kind == "audit":
            captured, report = worker.result
            if not captured.current():
                self.status.setText(self.t["changed"])
            else:
                self.captured, self.report = captured, report
                self._render()
                self.status.setText(
                    self.t["ready"].format(items=len(report["items"]), checks=len(report["checks"]))
                    if report["items"]
                    else self.t["empty"]
                )
        elif (
            worker.result
            and self.captured
            and self.captured.current()
            and self.source_callback is not None
        ):
            self.status.setText(
                self.t["source"] if self.source_callback(self._source) else self.t["source_failed"]
            )
        else:
            self.status.setText(self.t["source_failed"])
        self._handle.finish()
        worker.deleteLater()
        self._controls()

    def _render(self, *_args):
        self.source_buttons = []
        self.sections = []
        self.show_all_button = None
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        if self.report:
            groups = {item["id"]: [] for item in self.report["items"]}
            for check in self.report["checks"]:
                groups[check["item_id"]].append(check)
            ordinals = {}
            for item in self.report["items"]:
                ordinals[item["feature"]] = ordinals.get(item["feature"], 0) + 1
                checks = groups[item["id"]]
                attention = not checks or any(c["state"] not in SAFE_STATES for c in checks)
                if self.filter.isChecked() and not attention:
                    continue
                frame = QFrame()
                frame.setProperty("role", "card")
                card = QVBoxLayout(frame)
                label = (
                    self.features.get(item["feature"], item["feature"])
                    + f"  {ordinals[item['feature']]}"
                )
                section = ClaimSection(label, expanded=True)
                self.sections.append(section)
                text = item["text"]
                section.content.addWidget(_label(text))
                if item["document_hash"] is None:
                    note = _label(self.t["unknown"])
                    note.setProperty("role", "muted")
                    section.content.addWidget(note)
                for check in checks:
                    state = check["state"]
                    text = self.t.get(state, state)
                    if "quantity" in check:
                        q = check["quantity"]
                        text = q["value"] + q["unit"] + "  /  " + text
                    section.content.addWidget(_label(text))
                    if check.get("quote"):
                        section.content.addWidget(_label(check["quote"]))
                    if (
                        state == "located"
                        and self.owner is not None
                        and self.source_callback is not None
                    ):
                        button = QPushButton(self.t["source"])
                        button.setAutoDefault(False)
                        button.clicked.connect(lambda _checked=False, c=check: self.open_source(c))
                        self.source_buttons.append(button)
                        section.content.addWidget(button)
                if not checks:
                    section.content.addWidget(_label(self.t["no_checks"]))
                card.addWidget(section)
                layout.addWidget(frame)
        total = len(self.report["items"]) if self.report else 0
        shown = len(self.sections)
        self.visible_count.setText(self.t["count"].format(
            shown=shown, total=total, checks=len(self.report["checks"]) if self.report else 0
        ))
        if total and not shown:
            empty = _label(self.t["filtered_empty"].format(total=total))
            empty.setObjectName("auditFilteredEmpty")
            layout.addWidget(empty)
            self.show_all_button = QPushButton(self.t["all"])
            self.show_all_button.setObjectName("auditShowAll")
            self.show_all_button.setAutoDefault(False)
            self.show_all_button.clicked.connect(lambda: self.filter.setChecked(False))
            layout.addWidget(self.show_all_button)
        limits = _label(self.t["limits"])
        limits.setProperty("role", "muted")
        layout.addWidget(limits)
        layout.addStretch()
        old = self.scroll.takeWidget()
        self.scroll.setWidget(body)
        if old is not None:
            old.deleteLater()
        self._controls()

    def open_source(self, check):
        if (
            self.busy
            or not self._same()
            or not self.captured
            or not self.captured.current()
            or not self.report
            or check not in self.report["checks"]
            or check["state"] != "located"
            or self.owner is None
        ):
            return False
        digest = self.report["source"]["document_hash"]
        self._source = dict(
            kind="audit",
            document_hash=digest,
            anchor=check["location"]["anchor"],
            page=check["location"]["page"],
            text=check["quote"],
        )
        self.status.setText(self.t["source_working"])
        return self._start(
            "source",
            lambda cancel, progress: verify_source(self.owner, self.document, digest, cancel),
        )

    def cancel(self):
        if self._worker is not None:
            self._worker.cancelled.set()
            self.status.setText(self.t["stopping"])

    def reject(self):
        # Escape must preserve the same active-worker/unsaved-result guards.
        self.close()

    def closeEvent(self, event):
        draining = False
        for child in (self._appraisal_dialog, self._source_fact_dialog):
            if child is not None and not child.disposed and not child.close():
                draining = True
        if draining:
            self._closing = True
            event.ignore()
            return
        if self.busy:
            self._closing = True
            self.cancel()
            event.ignore()
            return
        self.disposed = True
        self.captured = None
        self.poll.stop()
        self._handle.finish()
        QDialog.reject(self)
        event.accept()

    def open_source_facts(self):
        if self.busy or not self._same() or self.captured is None:
            return None
        existing = self._source_fact_dialog
        if existing is not None and not existing.disposed:
            existing.show()
            existing.raise_()
            return existing
        from paper_daily.desktop.source_fact_dialog import SourceFactDialog

        self._source_fact_dialog = SourceFactDialog(
            self.captured, owner=self.owner, current_view=self.current_view,
            source_callback=self.source_callback, paper_title=self.paper_title,
            language="zh-TW" if self.t is TEXT["zh-TW"] else "en", parent=self,
        )
        self._source_fact_dialog.setWindowModality(Qt.WindowModality.NonModal)
        self._source_fact_dialog.show()
        return self._source_fact_dialog


def open_report(reader):
    from paper_daily import store

    paper = reader.paper
    if paper is None:
        return None
    host = getattr(reader, "win", reader.window())
    existing = getattr(host, "_audit_dialog", None)
    if existing is not None and not existing.disposed:
        if (
            existing.path == Path(store.DB_PATH).resolve()
            and existing.paper_id == paper.id
            and existing.document is getattr(reader, "_active_document", None)
            and existing._same()
            and not existing._closing
        ):
            existing.show()
            existing.raise_()
            return existing
        if not existing.close():
            existing.raise_()
            return existing

    def current():
        return (
            Path(store.DB_PATH).resolve(),
            reader.paper.id if reader.paper else None,
            getattr(reader, "_qa_epoch", None),
            getattr(reader, "_active_document", None),
            getattr(reader, "_pdf_fingerprint", None),
        )

    def focus(source):
        from paper_daily.desktop.research_source_navigation import focus as focus_source

        return focus_source(
            reader,
            source,
            document=dialog.document,
            current=lambda: current() == dialog.view,
        )

    try:
        dialog = AuditDialog(
            store.DB_PATH,
            paper.id,
            document=getattr(reader, "_active_document", None),
            paper_title=paper.title,
            owner=getattr(reader, "_highlight_owner", None),
            current_view=current,
            source_callback=focus,
            parent=reader,
        )
    except (OSError, ValueError):
        reader.ask_status.setText(TEXT["zh-TW"]["failed"])
        return None
    host._audit_dialog = dialog
    dialog.setWindowModality(Qt.WindowModality.NonModal)
    dialog.show()
    return dialog
