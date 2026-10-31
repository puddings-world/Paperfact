"""One explicit, temporary Audit extraction; source/SQL work belongs to workers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from paper_daily import (
    ai_choices,
    audit_input_recheck,
    audit_inputs,
    file_change,
    llm,
    research_audit,
)
from paper_daily.audit_fact_extraction import ExtractionJob
from paper_daily.desktop import activity, ai_style, fonts
from paper_daily.desktop.claim_evidence import ClaimSection, _label
from paper_daily.desktop.flow_layout import FlowLayout
from paper_daily.desktop.translation_scope import _routing_revision
from paper_daily.document_reader import document_current

TOKENS = 4000
TEXT = {
    "en": {
        "title": "Compare statements",
        "selection": "Captured saved outputs (choose 1–8)",
        "intro": "Proposed facts and explicit value differences, not scientific truth. "
        "Temporary and copyable; nothing is saved or overwritten.",
        "route": "Next Audit call: ",
        "loading": "Reading captured outputs and AI intent locally…",
        "budget": (
            "Output budget setting: {tokens} tokens; "
            "actual limits depend on the AI service. One Paperfact request; no automatic retry."
        ),
        "unsupported": (
            "Choose an Audit account, model and supported output budget before generating."
        ),
        "settings": "Account and model…",
        "generate": "Generate comparison",
        "copy": "Copy report",
        "stop": "Stop",
        "back": "Back to evidence",
        "empty": "No saved outputs to compare.",
        "choose": "Choose 1–8 outputs; oversized selections are refused, never truncated.",
        "working": "Preparing one captured Audit call…",
        "retrieval": "Finding bounded source passages…",
        "model": "Waiting for the selected model…",
        "verification": "Checking exact source locations…",
        "ready": "Temporary proposals ready. Quotations located does not mean semantic support.",
        "failed": "Comparison did not finish. The prior report is retained; retry explicitly.",
        "changed": "Inputs changed. Any displayed report is an earlier temporary result. "
        "Reopen evidence checks before starting new work.",
        "route_changed": ("AI selection changed; a pending comparison cannot replace "
                          "the prior report."),
        "stopping": "Stopping safely; an admitted model call may still finish.",
        "stopped": "Stopped. The prior temporary report remains unchanged.",
        "source": "View original passage",
        "source_failed": "Exact original unavailable; no jump occurred.",
        "temporary": "Temporary comparison — researcher-review proposals",
        "limits": "Text-only bounded material; no semantic certification, proof validation, "
        "quality score or complete-paper absence claim.",
        "requested": "Requested model",
        "reported": "Reported model",
        "unreported": "Not reported",
        "default": "Provider default",
        "facts": "Proposed facts",
        "pairs": "Value comparisons",
        "original": "Captured original",
        "output": "Saved output",
        "location": "characters",
        "binding": "Recorded original binding",
        "scope": "Proposed scope",
        "value": "Proposed value",
        "rounded": "Rounded places",
        "derived": "Derived; not recomputed",
        "unknown": "Unknown",
        "too_long": "Too long for this bounded selection",
        "copied": "Temporary report copied.",
        "previous": "The earlier temporary report remains unchanged.",
        "no_facts": "No supported fact proposals from the selected material; "
        "this is not a paper-wide absence claim.",
    },
    "zh-TW": {
        "title": "比對陳述",
        "selection": "已擷取的儲存內容（選擇 1–8 項）",
        "intro": ("整理事實提案與明確數值差異，不代表科學真偽。"
                  "結果暫存於此，可複製；不儲存或覆寫研究。"),
        "route": "下次 Audit 呼叫：",
        "loading": "正在本機讀取已擷取內容與 AI 設定…",
        "budget": (
            "輸出預算設定：{tokens} tokens；"
            "實際上限依 AI 服務而定。每次 1 項 Paperfact 請求，不會自動重試。"
        ),
        "unsupported": "請先選擇 Audit 帳號、模型與可支援的輸出額度，再產生比對。",
        "settings": "帳號與模型…",
        "generate": "產生比對",
        "copy": "複製報告",
        "stop": "停止",
        "back": "返回證據檢查",
        "empty": "沒有可比對的已存內容。",
        "choose": "選擇 1–8 項；超過內容上限會拒絕，不會截斷後送出。",
        "working": "正在準備已擷取設定的單次 Audit 呼叫…",
        "retrieval": "正在檢索限量原文片段…",
        "model": "正在等待所選模型…",
        "verification": "正在核對確切原文位置…",
        "ready": "暫存提案已就緒。引文已定位不代表語意支持已核實。",
        "failed": "比對未完成；先前報告保持不變，請明確操作重試。",
        "changed": "輸入已改變；目前報告是較早的暫存結果。請重新開啟證據檢查，再開始新工作。",
        "route_changed": "AI 設定已改變；待完成比對不會取代先前報告。",
        "stopping": "正在安全停止；已開始的模型呼叫可能仍會完成。",
        "stopped": "已停止；先前暫存報告保持不變。",
        "source": "核對原文片段",
        "source_failed": "無法核對相同原文，未跳轉。",
        "temporary": "暫存比對 — 仍需研究者檢查的提案",
        "limits": "僅限量文字材料；不代表語意認證、證明驗證、品質分數或全文未報告某事實。",
        "requested": "指定模型",
        "reported": "回報模型",
        "unreported": "未回報",
        "default": "服務預設",
        "facts": "事實提案",
        "pairs": "數值比對",
        "original": "已擷取原文",
        "output": "已存內容",
        "location": "字元位置",
        "binding": "已記錄原文綁定",
        "scope": "提案適用範圍",
        "value": "提案值",
        "rounded": "四捨五入位數",
        "derived": "衍生值；未重新計算",
        "unknown": "未知",
        "too_long": "超過此次選取的內容上限",
        "copied": "已複製暫存報告。",
        "previous": "先前的暫存報告保持不變。",
        "no_facts": "所選材料沒有可用事實提案；不代表全文未報告相關事實。",
    },
}
STATES = {
    "en": {
        "numeric_disagreement": "Proposed numeric values differ — review required",
        "rounding_compatible": "Compatible with declared rounding — not exact equality",
        "rounding_disagreement": "Outside declared rounding intervals — review required",
        "derived_value": "Derived value — not recomputed",
        "not_comparable": "Not comparable",
        "same_value": "Same explicit value",
        "same_text": "Same literal text",
        "text_difference": "Literal text differs — meaning not adjudicated",
    },
    "zh-TW": {
        "numeric_disagreement": "提案數值不同 — 需核對",
        "rounding_compatible": "與已宣告捨入相容 — 不代表精確相等",
        "rounding_disagreement": "超出已宣告捨入區間 — 需核對",
        "derived_value": "衍生值 — 未重新計算",
        "not_comparable": "無法直接比較",
        "same_value": "明確值相同",
        "same_text": "文字完全相同",
        "text_difference": "文字不同 — 未判定語意",
    },
}


REPORT_LABELS = {
    "en": {
        "fields": {
            "hash": "Original file SHA-256", "provider": "Provider", "category": "Category",
            "origin": "Attribution", "quote": "Quote location",
            "left": "First statement", "right": "Second statement",
        },
        "categories": {
            "design": "Study design", "assumptions": "Assumptions",
            "sample": "Participants / sample", "materials": "Materials / sources",
            "method": "Method", "outcome": "Outcome", "comparator": "Comparison / alternative",
            "units": "Units / scale", "uncertainty": "Uncertainty", "limitations": "Limitations",
        },
        "origins": {
            "author_stated": "Attributed to authors (proposed)",
            "reviewer_inferred": "Reviewer inference (proposed)",
            "not_reported": "Not reported (proposed)",
            "not_applicable": "Not applicable (proposed)", "unknown": "Attribution unknown",
        },
        "scope": {
            "construct": "Concept / measure", "outcome": "Outcome", "comparator": "Comparison",
            "population": "Population / material", "time": "Time / stage", "unit": "Unit",
            "statistic": "Statistic", "conditions": "Conditions",
        },
        "bindings": {
            "exact": "Matches the captured original",
            "unknown": "Original version not recorded for this output",
            "different_original": "Recorded against a different original version",
        },
        "features": {
            "dive": "Deep reading", "close_reading": "Close reading", "answer": "Answer",
            "note": "Note", "slides": "Slides", "highlights": "Highlights",
            "claims": "Claim evidence", "citations": "References", "followups": "Follow-up works",
            "lineage": "Research lineage", "list_survey": "Reading-list synthesis",
            "reading_links": "Reading connections", "research_questions": "Research questions",
            "paper_context": "Paper context",
        },
        "quote_states": {
            "located": "Passage located; semantic support not checked",
            "missing": "Quote not found in the captured original",
            "ambiguous": "Several matching passages; no unique location",
            "invalid_page": "Requested page could not be verified",
            "invalid_anchor": "Recorded passage selection could not be verified",
        },
        "reasons": {
            "study_type_unknown": "Study type is unknown",
            "source_unknown": "The saved output does not record its original version",
            "source_different_original": "The saved output refers to another original version",
            "reviewer_inferred": "Attributed to reviewer inference, not an author statement",
            "not_reported": "A value was proposed as not reported",
            "not_applicable": "A value was proposed as not applicable",
            "unknown": "Attribution is unknown",
            "evidence_unverified": "Not all cited passages have a verified location",
            "different_category": "The proposed facts have different categories",
            "scope_unknown": "Some comparison scope is unknown",
            "different_scope": "The proposed facts describe different scopes",
            "different_value_kind": "The proposed values have different types",
            "derivation_not_verified": "The derivation has not been verified or recomputed",
            "page_out_of_range": "The requested page is outside the captured original",
            "anchor_out_of_range_or_page_mismatch": (
                "The selection is outside the page or mismatched"
            ),
            "anchor_does_not_bound_unique_quote": "The selection does not identify a unique quote",
            "multiple_quote_locations": "The quote occurs at more than one location",
            "quote_not_found": "The quote was not found in the captured original",
        },
    },
    "zh-TW": {
        "fields": {
            "hash": "原始檔 SHA-256", "provider": "服務提供者", "category": "類別",
            "origin": "陳述歸屬", "quote": "引文位置", "left": "第一項陳述", "right": "第二項陳述",
        },
        "categories": {
            "design": "研究設計", "assumptions": "假設", "sample": "參與者／樣本",
            "materials": "材料／來源", "method": "方法", "outcome": "結果",
            "comparator": "比較對象／替代方案", "units": "單位／尺度",
            "uncertainty": "不確定性", "limitations": "限制",
        },
        "origins": {
            "author_stated": "歸屬於作者的陳述（提案）",
            "reviewer_inferred": "審閱者推論（提案）", "not_reported": "未報告（提案）",
            "not_applicable": "不適用（提案）", "unknown": "陳述歸屬未知",
        },
        "scope": {
            "construct": "概念／量測", "outcome": "結果", "comparator": "比較對象",
            "population": "母群體／材料", "time": "時間／階段", "unit": "單位",
            "statistic": "統計量", "conditions": "條件",
        },
        "bindings": {
            "exact": "與已擷取原文版本相符", "unknown": "此內容未記錄原文版本",
            "different_original": "此內容記錄的是另一原文版本",
        },
        "features": {
            "dive": "深度閱讀", "close_reading": "逐段精讀", "answer": "問答",
            "note": "筆記", "slides": "投影片", "highlights": "重點標記",
            "claims": "主張與證據", "citations": "參考文獻", "followups": "後續研究",
            "lineage": "研究脈絡", "list_survey": "閱讀清單綜整", "reading_links": "閱讀連結",
            "research_questions": "研究問題", "paper_context": "論文背景",
        },
        "quote_states": {
            "located": "已定位引文；未檢查語意支持", "missing": "在已擷取原文中找不到引文",
            "ambiguous": "找到多處相符段落，無法確定唯一位置", "invalid_page": "無法核對指定頁面",
            "invalid_anchor": "無法核對已記錄的引文範圍",
        },
        "reasons": {
            "study_type_unknown": "研究類型未知", "source_unknown": "已存內容未記錄原文版本",
            "source_different_original": "已存內容指向另一原文版本",
            "reviewer_inferred": "歸屬於審閱者推論，非作者陳述",
            "not_reported": "此值的提案為未報告", "not_applicable": "此值的提案為不適用",
            "unknown": "陳述歸屬未知", "evidence_unverified": "並非所有引文段落都已核對位置",
            "different_category": "事實提案的類別不同", "scope_unknown": "部分比較範圍未知",
            "different_scope": "事實提案描述的適用範圍不同",
            "different_value_kind": "提案值的類型不同",
            "derivation_not_verified": "尚未核實或重新計算推導過程",
            "page_out_of_range": "指定頁碼超出已擷取原文的範圍",
            "anchor_out_of_range_or_page_mismatch": "選取範圍超出頁面或與頁面不符",
            "anchor_does_not_bound_unique_quote": "選取範圍無法識別唯一引文",
            "multiple_quote_locations": "引文出現在多個位置",
            "quote_not_found": "在已擷取原文中找不到引文",
        },
    },
}


def _metadata(capture):
    return audit_inputs._versions(capture.database), file_change.version(
        capture.snapshot._origin.path
    )


def _view_equal(left, right):
    if isinstance(left, tuple) and isinstance(right, tuple):
        return len(left) == len(right) and all(
            _view_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    if type(left) is not type(right):
        return False
    return left == right if isinstance(left, (str, int, bool, type(None), Path)) else left is right


@dataclass
class Lease:
    capture: object = field(repr=False)
    proof: object = field(repr=False)
    route: object = field(default=None, repr=False)
    allow_reading: bool = False
    stopped: Event = field(default_factory=Event, repr=False)

    def current(self):
        try:
            return (
                not self.stopped.is_set()
                and (
                    _metadata(self.capture) == self.proof
                    or self.allow_reading and self._same_original_files()
                )
                and (self.route is None or _routing_revision() == self.route)
            )
        except (OSError, ValueError, RuntimeError):
            return False

    def _same_original_files(self):
        # Interference is not scientific equality. Only the worker can renew it.
        observed = _metadata(self.capture)
        original_database = self.capture._versions[0][1]
        current_database = observed[0][0][1]
        return (
            original_database is not None and current_database is not None
            and original_database[:2] == current_database[:2]
            and observed[1] == self.capture.snapshot._origin._identity
        )


class Worker(QThread):
    progress = Signal(str)

    def __init__(self, call, parent, lease):
        super().__init__(parent)
        self.call, self.lease = call, lease
        self.cancelled = Event()
        self.result = self.error = None

    def run(self):
        try:
            self.result = self.call(self.cancelled.is_set, self.progress.emit)
        except Exception as error:
            self.error = getattr(error, "code", "operation_failed")


def _probe(capture, t, *, owner=None, cancelled=lambda: False, current=lambda: True):
    if owner is not None and not capture.current():
        capture = audit_input_recheck.recheck(
            capture, document=capture.snapshot._origin, owner=owner,
            current=current, cancelled=cancelled,
        )
    proof = _metadata(capture)
    if not capture.current() or not document_current(capture.snapshot._origin):
        raise ValueError("stale source capture")
    items = research_audit.validate(json.loads(capture._items_json))
    revision = _routing_revision()
    try:
        connections = llm.capture_connections()
        with llm.connection_scope(connections):
            cfg = llm.settings(task="audit")
        route = ai_choices.connection_label(cfg)
        supported = (
            cfg.backend != "none" and type(cfg.max_tokens) is int and cfg.max_tokens >= TOKENS
        )
    except (OSError, ValueError):
        route, supported = t["unsupported"], False
    if revision != _routing_revision() or proof != _metadata(capture) or not capture.current():
        raise ValueError("changed while reading local intent")
    return dict(items=items, route=route, supported=supported, revision=revision, proof=proof,
                capture=capture)


def _render(result, items, t, language):
    sheet, execution, consistency = result.sheet.report, result.execution, result.consistency
    labels = REPORT_LABELS[language]
    lookup = {item["id"]: item for item in items}
    lines = [
        t["temporary"],
        t["limits"],
        "",
        labels["fields"]["hash"] + ": " + sheet["source"]["document_hash"],
        labels["fields"]["provider"] + ": " + execution["backend"]
        + " / "
        + t["requested"]
        + ": "
        + (execution["requested_model"] or t["default"])
        + " / "
        + t["reported"]
        + ": "
        + (execution["reported_model"] or t["unreported"]),
        t["budget"].format(tokens=execution["max_tokens"]),
        "",
        t["facts"],
    ]
    sources = []

    def location(where):
        if where["kind"] == "source":
            return t["original"]
        item = lookup[where["item_id"]]
        return (
            t["output"]
            + " "
            + labels["features"][item["feature"]]
            + " ("
            + item["id"]
            + ") / "
            + t["location"]
            + f" {where['start']}–{where['end']}\n"
            + item["text"][where["start"] : where["end"]]
        )

    facts = {fact["id"]: fact for fact in sheet["facts"]}
    if not facts:
        lines += [t["no_facts"], execution["empty_reason"] or t["empty"]]
    for number, fact in enumerate(facts.values(), 1):
        value = fact["value"]
        display = (
            t["unknown"]
            if value is None
            else (value["text"] if value["kind"] == "text" else value["decimal"])
        )
        lines += [
            f"{number}. {fact['statement']}",
            labels["fields"]["category"] + ": " + labels["categories"][fact["category"]],
            labels["fields"]["origin"] + ": " + labels["origins"][fact["origin"]],
            location(fact["location"]),
            t["binding"] + ": " + labels["bindings"][fact["source_binding"]],
            t["value"] + ": " + display,
            t["scope"]
            + ": "
            + "; ".join(
                labels["scope"][key] + ": " + (value if value is not None else t["unknown"])
                for key, value in fact["scope"].items()
            ),
        ]
        if value is not None and value["kind"] == "number":
            if value["rounded_places"] is not None:
                lines.append(t["rounded"] + ": " + str(value["rounded_places"]))
            if value["derived"]:
                lines.append(t["derived"])
        for evidence in fact["evidence"]:
            where = evidence["location"]
            lines += [
                evidence["quote"],
                labels["fields"]["quote"] + ": " + labels["quote_states"][where["state"]],
            ]
            if where["reason"] is not None:
                lines.append(labels["reasons"][where["reason"]])
            if where["state"] == "located":
                sources.append(
                    dict(
                        kind="audit",
                        document_hash=sheet["source"]["document_hash"],
                        anchor=where["anchor"],
                        page=where["page"],
                        text=evidence["quote"],
                        number=number,
                    )
                )
        lines.append("")
    lines += [t["pairs"]]
    for pair in consistency["comparisons"]:
        lines += [
            STATES[language][pair["state"]]
            + (" / " + labels["reasons"][pair["reason"]] if pair["reason"] else "")
        ]
        for side in ("left", "right"):
            fact = facts[pair[side]["fact_id"]]
            lines += [
                labels["fields"][side] + ": " + fact["statement"],
                location(pair[side]["location"]),
            ]
        lines.append("")
    return dict(result=result, execution=execution, text="\n".join(lines), sources=sources)


class SourceFactDialog(QDialog):
    def __init__(
        self,
        capture,
        *,
        owner=None,
        current_view=None,
        source_callback=None,
        language="zh-TW",
        parent=None,
        paper_title=None,
        job_factory=ExtractionJob.prepare,
    ):
        super().__init__(parent)
        self.capture, self.owner = capture, owner
        self._execution_capture = capture
        self.current_view = current_view
        self.view = current_view() if current_view else None
        hub = activity.hub_for(self)
        self._window = hub.window if hub is not None else None
        self._outer_owner = getattr(self._window, "_workspace_owner", None)
        self.source_callback, self.job_factory = source_callback, job_factory
        self.language = language if language in TEXT else "en"
        self.t = TEXT[self.language]
        self.report = self.accepted = None
        self._proof = self._route_revision = None
        self._supported = self._invalid = self.disposed = self._closing = False
        self._settings_open = False
        self._worker = None
        self._handle = activity.Handle()
        self.items, self.checks, self.source_buttons = [], {}, []
        self.setWindowTitle(self.t["title"])
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setFont(fonts.font(pixels=13))
        self.resize(740, 740)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        heading = _label(paper_title or capture.paper_id)
        heading.setStyleSheet("font-size:20px;font-weight:600;")
        layout.addWidget(heading)
        layout.addWidget(_label(self.t["intro"]))
        route_row = QHBoxLayout()
        self.route = _label(self.t["loading"])
        route_row.addWidget(self.route, 1)
        self.settings_button = QPushButton(self.t["settings"])
        self.settings_button.clicked.connect(self.settings)
        route_row.addWidget(self.settings_button)
        layout.addLayout(route_row)
        self.budget = _label(self.t["budget"].format(tokens=TOKENS))
        layout.addWidget(self.budget)
        self.selection = ClaimSection(self.t["selection"], expanded=True)
        self.selection_area = QScrollArea()
        self.selection_area.setWidgetResizable(True)
        self.selection_area.setMaximumHeight(180)
        self.selection.content.addWidget(self.selection_area)
        layout.addWidget(self.selection)
        actions = FlowLayout()
        self.generate_button = QPushButton(self.t["generate"])
        ai_style.mark(self.generate_button, primary=True)
        self.generate_button.clicked.connect(self.generate)
        self.copy_button = QPushButton(self.t["copy"])
        self.copy_button.clicked.connect(self.copy_report)
        for button in (self.generate_button, self.copy_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)
        self.source_row = FlowLayout()
        layout.addLayout(self.source_row)
        self.status = _label(self.t["loading"])
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.stop_button = QPushButton(self.t["stop"])
        self.stop_button.clicked.connect(self.cancel)
        close = QPushButton(self.t["back"])
        close.clicked.connect(self.close)
        bottom.addWidget(self.stop_button)
        bottom.addStretch()
        bottom.addWidget(close)
        layout.addLayout(bottom)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.poll = QTimer(self)
        self.poll.setInterval(250)
        self.poll.timeout.connect(self._tick)
        self.poll.start()
        self._controls()
        QTimer.singleShot(0, self._probe)

    @property
    def busy(self):
        return self._worker is not None

    def _same(self):
        try:
            parent = self.parent()
            return (
                isValid(self)
                and not self.disposed
                and not self._closing
                and not getattr(parent, "disposed", False)
                and not getattr(parent, "_closing", False)
                and getattr(parent, "captured", self.capture) is self.capture
                and (self.current_view is None or _view_equal(self.current_view(), self.view))
                and getattr(self._window, "_workspace_owner", None) is self._outer_owner
                and (self._outer_owner is None or self._outer_owner.current())
            )
        except (OSError, ValueError, RuntimeError):
            return False

    def _source_current(self, proof):
        try:
            return self._same() and proof is not None and _metadata(self.capture) == proof
        except (OSError, ValueError, RuntimeError):
            return False

    def _controls(self, *_args):
        current = self._source_current(self._proof) and not self._invalid
        count = sum(check.isChecked() for check in self.checks.values())
        self.generate_button.setEnabled(
            current and self._supported and not self.busy and 1 <= count <= 8
        )
        self.settings_button.setEnabled(self._same() and not self.busy and not self._settings_open)
        self.copy_button.setEnabled(self.report is not None)
        self.stop_button.setVisible(self.busy)
        self.progress.setVisible(self.busy)
        for check in self.checks.values():
            check.setEnabled(current and not self.busy and check.property("withinBound"))
        source_current = self.accepted is not None and self._source_current(self.accepted["proof"])
        for button in self.source_buttons:
            button.setEnabled(
                source_current
                and not self.busy
                and self.owner is not None
                and self.source_callback is not None
            )

    def _tick(self):
        if self.disposed:
            return
        pending_recheck = (
            self.busy and self._kind == "generate"
            and self._worker.lease.allow_reading and self._worker.lease.current()
        )
        if not self._same() or (
            self._proof is not None and not self._source_current(self._proof)
            and not pending_recheck
        ):
            self._invalid = True
            if self.busy:
                self._worker.lease.stopped.set()
            self.status.setText(self.t["changed"])
        elif self._route_revision is not None and self._route_revision != _routing_revision():
            if self.busy and self._kind == "generate":
                self._worker.lease.stopped.set()
                self.status.setText(self.t["route_changed"])
            elif not self.busy:
                self._probe()
        self._controls()

    def _start(self, kind, call, lease):
        if self.busy or not self._same() or self._invalid:
            return False
        handle = activity.begin(
            self,
            self.t["title"],
            task="audit",
            key=f"source-facts:{id(self)}",
            paper_id=self.capture.paper_id,
        )
        if not handle.accepted:
            return False
        self._handle, self._kind = handle, kind
        worker = Worker(call, self, lease)
        self._worker = worker
        worker.progress.connect(self._progress)
        worker.finished.connect(self._finished)
        self._controls()
        worker.start()
        return True

    def _progress(self, stage):
        if self._same():
            self.status.setText(self.t.get(stage, self.t["working"]))
            self._handle.stage(self.status.text())

    def _probe(self):
        capture, text, owner = self._execution_capture, self.t, self.owner
        lease = Lease(capture, self._proof, allow_reading=owner is not None)
        return self._start(
            "probe", lambda cancel, progress: _probe(
                capture, text, owner=owner, cancelled=cancel, current=lease.current
            ), lease,
        )

    def settings(self):
        if self.busy or self._settings_open or not self._same():
            return False
        from paper_daily.desktop.ai_picker import AIPickerDialog

        self._settings_open = True
        self._controls()
        dialog, failed = None, False
        try:
            dialog = AIPickerDialog(self, task="audit")
            dialog.exec()
        except (OSError, ValueError, RuntimeError):
            failed = True
        finally:
            if dialog is not None and isValid(dialog):
                dialog.deleteLater()
            self._settings_open = False
        if isValid(self) and self._same():
            if failed:
                self.status.setText(self.t["failed"])
                self._controls()
            else:
                self._probe()
        return True

    def generate(self):
        if (
            self.busy
            or self._invalid
            or not self._source_current(self._proof)
            or not self._supported
        ):
            return False
        selected = tuple(key for key, check in self.checks.items() if check.isChecked())
        if not 1 <= len(selected) <= 8:
            self.status.setText(self.t["choose"])
            return False
        if _routing_revision() != self._route_revision:
            self._probe()
            return False
        capture, factory, owner = self._execution_capture, self.job_factory, self.owner
        items, text, language = self.items, self.t, self.language
        lease = Lease(
            capture, self._proof, self._route_revision, allow_reading=owner is not None
        )

        def run(cancelled, progress):
            if not lease.current():
                raise ValueError("stale connection")
            connections = llm.capture_connections()
            job = factory(
                capture,
                selected,
                connections=connections,
                max_calls=1,
                max_tokens=TOKENS,
                route_current=lease.current,
                **({"reading_owner": owner} if owner is not None else {}),
            )
            result = job.run(cancelled=cancelled, current=lease.current, progress=progress)
            if cancelled() or not result.current() or not lease.current():
                raise ValueError("stale result")
            view = _render(result, items, text, language)
            view["proof"] = _metadata(result.sheet._capture)
            view["capture"] = result.sheet._capture
            return view

        self.status.setText(self.t["working"])
        return self._start("generate", run, lease)

    def _finished(self):
        worker = self._worker
        if worker is None:
            return
        if not worker.wait(0):
            QTimer.singleShot(1, self._finished)
            return
        valid = self._same() and not self._invalid and not worker.cancelled.is_set()
        self._worker = None
        if valid and not worker.error and self._kind == "probe":
            info = worker.result
            if self._source_current(info["proof"]) and info["revision"] == _routing_revision():
                self._proof, self._route_revision = info["proof"], info["revision"]
                self._execution_capture = info["capture"]
                self._supported = info["supported"]
                self.route.setText(self.t["route"] + info["route"])
                self.items = info["items"]
                self._choices()
                self.status.setText(
                    self.t["choose"] if info["supported"] else self.t["unsupported"]
                )
                if self.report is not None:
                    self.status.setText(self.status.text() + " " + self.t["previous"])
        elif (
            valid
            and not worker.error
            and self._kind == "generate"
            and worker.lease.current()
            and self._source_current(worker.result["proof"])
        ):
            self.accepted, self.report = worker.result, worker.result["result"]
            self._execution_capture, self._proof = worker.result["capture"], worker.result["proof"]
            self.output.setPlainText(worker.result["text"])
            self._sources(worker.result["sources"])
            self.status.setText(
                self.t["no_facts"]
                if worker.result["execution"]["outcome"] == "no_supported_facts"
                else self.t["ready"]
            )
        elif valid and not worker.error and self._kind == "source":
            ok, proof = worker.result
            success = (
                ok
                and self._source_current(proof)
                and self.source_callback is not None
                and self.source_callback(self._source) is not False
            )
            self.status.setText(self.t["source"] if success else self.t["source_failed"])
        else:
            self.status.setText(
                self.t["stopped"]
                if worker.cancelled.is_set()
                else self.t["unsupported"]
                if worker.error
                in {"invalid_token_budget", "audit_route_unavailable", "unsupported_audit_route"}
                else self.t["changed"]
                if not valid
                else self.t["failed"]
            )
        self._handle.finish(ok=not worker.error, cancelled=worker.cancelled.is_set())
        worker.deleteLater()
        self._controls()
        if self._closing:
            self.close()

    def _choices(self):
        initial = not self.checks
        selected = {key for key, check in self.checks.items() if check.isChecked()}
        body, layout = QWidget(), QVBoxLayout()
        self.checks = {}
        for index, item in enumerate(self.items):
            check = QCheckBox(item["feature"] + f" {index + 1}: " + item["text"][:240])
            within = len(item["text"]) <= 8000
            check.setProperty("withinBound", within)
            check.setChecked(within and (index < 8 if initial else item["id"] in selected))
            check.setToolTip(item["text"] if within else self.t["too_long"])
            check.toggled.connect(self._controls)
            self.checks[item["id"]] = check
            layout.addWidget(check)
        if not self.items:
            layout.addWidget(_label(self.t["empty"]))
        body.setLayout(layout)
        old = self.selection_area.takeWidget()
        self.selection_area.setWidget(body)
        if old is not None:
            old.deleteLater()

    def _sources(self, sources):
        while self.source_row.count():
            item = self.source_row.takeAt(0)
            item.widget().deleteLater()
        self.source_buttons = []
        for source in sources:
            button = QPushButton(self.t["source"] + f" {source['number']} · {source['page']}")
            button.setAutoDefault(False)
            button.clicked.connect(lambda _checked=False, item=source: self.open_source(item))
            self.source_row.addWidget(button)
            self.source_buttons.append(button)

    def open_source(self, source):
        if (
            self.busy
            or self.accepted is None
            or self.owner is None
            or not self._source_current(self.accepted["proof"])
            or source not in self.accepted["sources"]
        ):
            return False
        capture, report, owner = self.capture, self.report, self.owner
        proof = self.accepted["proof"]
        lease = Lease(capture, proof)
        self._source = {key: value for key, value in source.items() if key != "number"}
        digest = source["document_hash"]

        def verify(cancelled, progress):
            ok = report.sheet.current() and audit_inputs.verify_loaded_source(
                owner, capture.snapshot._origin, digest, cancelled
            )
            return ok, _metadata(capture)

        return self._start("source", verify, lease)

    def copy_report(self):
        if self.report is not None:
            QApplication.clipboard().setText(self.output.toPlainText())
            self.status.setText(self.t["copied"])

    def cancel(self):
        if self._worker is not None:
            self._worker.cancelled.set()
            self._worker.lease.stopped.set()
            self.status.setText(self.t["stopping"])

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if self.busy:
            self._closing = True
            self.cancel()
            event.ignore()
            return
        self.disposed = True
        self.poll.stop()
        self._handle.finish()
        self.capture = self.report = self.accepted = self._execution_capture = None
        self._proof = self._route_revision = None
        self.view = self.current_view = self.source_callback = self.job_factory = None
        self.owner = self._outer_owner = self._window = None
        self.items = []
        self._source = None
        self._controls()
        QDialog.reject(self)
        event.accept()
