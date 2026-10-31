"""Small selected saved-deck evidence view; all SQL, bytes and hashes stay on a worker."""

from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QThread, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)
from shiboken6 import isValid

from paper_daily.audit_decks import DeckAuditReader
from paper_daily.workspace_service import Ticket

COPY = {
    "en": {
        "unverified": "Recorded original could not be checked",
        "saved_version": "Saved version",
        "entry": "Saved evidence",
        "title": "Evidence in this saved deck",
        "hint": "Check the selected saved deck and recorded original versions. No AI.",
        "intro": "Quotation and number occurrences do not establish semantic support. "
        "Images and source jumps are outside this check.",
        "refresh": "Check again",
        "close": "Back to slides",
        "working": "Checking saved deck and recorded originals...",
        "stopping": "Stopping the local check...",
        "failed": "Could not finish. Saved slides and drafts are unchanged.",
        "changed": "The workspace, selected deck, source or draft changed. Reopen this check.",
        "draft": "Save or finish the current deck edits before checking its saved evidence.",
        "unavailable": "This check needs an actual selected typed saved deck.",
        "ready": "Originals available for {done}/{total} cited sources. Semantic "
        "support is not checked.",
        "empty": "This saved deck has no cited source rows; zero source coverage.",
        "version": "Recorded original version",
        "owner": "Recorded paper",
        "historical": "Retained original; current primary is a different version.",
        "current": "Current primary has the same recorded version.",
        "unknown_current": "Current primary match is unknown.",
        "available": "Owned original verified",
        "source_unknown": "Original version not recorded",
        "source_owner_unrecorded": "This original has no recorded paper association",
        "source_owner_ambiguous": "This original matches several recorded papers; none selected",
        "document_scope_unavailable": "Recorded document ownership is unavailable",
        "source_parent_replaced": "The recorded paper was replaced; the old original "
        "is not reassigned",
        "original_unavailable": "Recorded owned original is unavailable locally",
        "located": "Quotation located; support unchecked",
        "missing": "Quotation not found",
        "ambiguous": "Quotation has several possible locations",
        "invalid_page": "Page is outside this original",
        "invalid_anchor": "Anchor is unresolved",
        "source_mismatch": "Different original version",
        "observed": "Number/unit occurs; interpretation unchecked",
        "not_observed": "Number/unit not observed; may be derived or image-only",
        "quote": "Declared source text",
        "page": "Original page",
        "slide": "Slide",
        "source": "Saved source text",
        "no_checks": "No declared quotation or number check for this text.",
        "figure": "Saved figure caption",
        "coverage": "Recorded coverage notes",
    },
    "zh-TW": {
        "unverified": "未能檢查記錄的原文",
        "saved_version": "已存版本",
        "entry": "已存證據",
        "title": "檢查這份已存簡報",
        "hint": "檢查選取的已存簡報與紀錄的原文版本，不使用 AI。",
        "intro": "找到引文或數字不代表語意支持。此檢查不判讀圖像，也不跳轉原文。",
        "refresh": "再檢查",
        "close": "回到簡報",
        "working": "正在檢查已存簡報與原文...",
        "stopping": "正在停止本機檢查...",
        "failed": "檢查未完成；已存簡報與草稿未改變。",
        "changed": "工作區、選取簡報、原文或草稿已變更，請重開檢查。",
        "draft": "請先儲存或完成目前簡報編輯。",
        "unavailable": "請選取具有型別歸屬的已存簡報。",
        "ready": "{done}/{total} 個引用來源的原文可用；語意支持未檢核。",
        "empty": "此簡報沒有引用來源，來源涵蓋數為零。",
        "version": "記錄的原文版本",
        "owner": "記錄的論文",
        "historical": "保留的原文；目前主 PDF 是其他版本。",
        "current": "目前主 PDF 與記錄版本相同。",
        "unknown_current": "不知目前主 PDF 是否相同。",
        "available": "已核對歸屬原文",
        "source_unknown": "原文版本未記錄",
        "source_owner_unrecorded": "原文尚未連結到記錄的論文",
        "source_owner_ambiguous": "原文對應多筆論文紀錄，尚未選定",
        "document_scope_unavailable": "記錄的文件歸屬不可用",
        "source_parent_replaced": "記錄的論文已被替換，未重新歸屬舊原文",
        "original_unavailable": "記錄且具歸屬的原文本機不可用",
        "located": "已定位引文；支持性未檢核",
        "missing": "未找到引文",
        "ambiguous": "引文有多個可能位置",
        "invalid_page": "頁碼超出原文",
        "invalid_anchor": "定位未解析",
        "source_mismatch": "不同原文版本",
        "observed": "原文出現數字單位；解讀未檢核",
        "not_observed": "原文未見數字單位，可能是推導或圖像內容",
        "quote": "宣告的原文文字",
        "page": "原文頁",
        "slide": "投影片",
        "source": "已存來源文字",
        "no_checks": "此文字沒有宣告引文或數字檢查。",
        "figure": "已存圖片說明",
        "coverage": "記錄的範圍說明",
    },
}
_LIVE = set()


class _Worker(QThread):
    def __init__(self, reader):
        super().__init__()
        self.reader, self.ticket = reader, Ticket()
        self.result = self.error = None

    def run(self):
        try:
            self.result = self.reader.prepare(self.ticket)
        except Exception as error:
            self.error = getattr(error, "code", type(error).__name__)


def _release(worker):
    owner = worker.owner_ref() if getattr(worker, "owner_ref", None) else None
    if owner is not None and isValid(owner):
        owner._deck_audit_running = max(0, getattr(owner, "_deck_audit_running", 0) - 1)
    _LIVE.discard(worker)
    worker.deleteLater()


def _label(text):
    from PySide6.QtCore import Qt

    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class DeckAuditDialog(QDialog):
    def __init__(self, reader, *, current=lambda: True, language="en", parent=None):
        super().__init__(parent)
        self.reader, self.current = reader, current
        self.t = COPY.get(language, COPY["en"])
        self.prepared = None
        self._worker = None
        self.disposed = self._closing = False
        self.setWindowTitle(self.t["title"])
        self.resize(740, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(_label(self.t["intro"]))
        self.heading = _label(self.t["title"])
        layout.addWidget(self.heading)
        controls = QHBoxLayout()
        self.refresh_button, self.close_button = (
            QPushButton(self.t["refresh"]),
            QPushButton(self.t["close"]),
        )
        controls.addWidget(self.refresh_button)
        controls.addStretch()
        controls.addWidget(self.close_button)
        layout.addLayout(controls)
        self.status = _label(self.t["working"])
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        self.selector = QComboBox()
        layout.addWidget(self.selector)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        self.refresh_button.clicked.connect(self.refresh)
        self.close_button.clicked.connect(self.close)
        self.selector.currentIndexChanged.connect(self._selected)
        self._parents = []
        if parent is not None:
            self._parents = list({parent, parent.window()})
            for widget in self._parents:
                widget.installEventFilter(self)
        self.poll = QTimer(self)
        self.poll.setInterval(250)
        self.poll.timeout.connect(self._check)
        self.poll.start()
        QTimer.singleShot(0, self, self.refresh)

    @property
    def busy(self):
        return self._worker is not None

    def _same(self):
        return not self.disposed and bool(self.current())

    def _controls(self):
        self.refresh_button.setEnabled(self._same() and not self.busy)
        self.selector.setEnabled(
            self._same()
            and not self.busy
            and self.prepared is not None
            and self.reader.current(self.prepared)
        )
        self.progress.setVisible(self.busy)

    def refresh(self):
        if self.busy or not self._same():
            return False
        self.status.setText(self.t["working"])
        worker = _Worker(self.reader)
        owner = self.parentWidget()
        worker.owner_ref = weakref.ref(owner) if owner is not None else None
        if owner is not None:
            owner._deck_audit_running = getattr(owner, "_deck_audit_running", 0) + 1
        self._worker = worker
        _LIVE.add(worker)
        self.destroyed.connect(lambda _obj=None, ticket=worker.ticket: ticket.cancel())
        worker.finished.connect(self._finished)
        worker.finished.connect(lambda w=worker: _release(w))
        self._controls()
        try:
            worker.start()
        except (OSError, RuntimeError):
            self._worker = None
            _release(worker)
            self.status.setText(self.t["failed"])
            self._controls()
            return False
        return True

    def _check(self):
        if not self._same():
            if self._worker:
                self._worker.ticket.cancel()
            self.status.setText(self.t["changed"])
        elif self.prepared is not None and not self.reader.current(self.prepared):
            self.status.setText(self.t["changed"])
        self._controls()

    def _finished(self):
        worker, self._worker = self._worker, None
        if worker is None:
            return
        if self._closing:
            self.close()
            return
        if not self._same():
            self.status.setText(self.t["changed"])
        elif worker.error or worker.ticket.cancelled:
            self.status.setText(self.t["failed"])
        elif not self.reader.current(worker.result):
            self.status.setText(self.t["changed"])
        else:
            self.prepared = worker.result
            self._render()
        self._controls()

    def _render(self):
        report = self.prepared.report
        self.heading.setText(report["title"] + " - " + self.t["saved_version"])
        self.heading.setToolTip(report["operation_id"] + " / " + report["body_hash"])
        self.selector.blockSignals(True)
        self.selector.clear()
        for row in report["sources"]:
            self.selector.addItem(row["label"] + " - " + self.t[row["state"]])
        self.selector.blockSignals(False)
        self._selected()
        self.status.setText(
            self.t["ready"].format(done=report["covered_sources"], total=len(report["sources"]))
            if report["sources"]
            else self.t["empty"]
        )

    def _selected(self, *_args):
        if self.prepared is None:
            return
        if not self._same() or not self.reader.current(self.prepared):
            self.status.setText(self.t["changed"])
            return
        sources = self.prepared.report["sources"]
        index = self.selector.currentIndex()
        if not 0 <= index < len(sources):
            self.text.clear()
            return
        source = sources[index]
        lines = [source["label"], self.t[source["state"]]]
        if source["recorded_document_hash"]:
            lines += [self.t["version"], source["recorded_document_hash"]]
        if source["owner"]:
            lines += [self.t["owner"], source["paper_title"], source["owner"]["paper_id"]]
            state = source["current_primary_matches"]
            lines.append(
                self.t[
                    "current"
                    if state is True
                    else "historical"
                    if state is False
                    else "unknown_current"
                ]
            )
        coverage = self.prepared.report["coverage_notes"]
        if coverage:
            lines += [self.t["coverage"], *coverage]
        for item in source["report"]["items"]:
            lines += [
                "",
                (self.t["slide"] + " " + item["id"].split(":", 1)[1])
                if item["id"].startswith("slide:")
                else self.t["figure"]
                if item["id"].startswith("figure:")
                else self.t["source"],
                item["text"],
            ]
            checks = [row for row in source["report"]["checks"] if row["item_id"] == item["id"]]
            if not checks:
                lines.append(self.t["no_checks"])
            for check in checks:
                key = (
                    "unverified"
                    if check["state"] == "source_unknown" and source["recorded_document_hash"]
                    else check["state"]
                )
                line = self.t.get(key, key)
                if check.get("quantity"):
                    value = check["quantity"]
                    line = value["value"] + value["unit"] + " - " + line
                lines.append(line)
                if check.get("quote"):
                    lines += [self.t["quote"], check["quote"]]
                if check.get("location") and check["location"]["page"]:
                    lines.append(self.t["page"] + " " + str(check["location"]["page"]))
        self.text.setPlainText("\n".join(lines))

    def eventFilter(self, watched, event):
        if (
            watched in self._parents
            and event.type() == QEvent.Type.Close
            and not self.disposed
            and not self.close()
        ):
            event.ignore()
            return True
        return super().eventFilter(watched, event)

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if self._worker:
            self._closing = True
            self._worker.ticket.cancel()
            self.status.setText(self.t["stopping"])
            event.ignore()
            return
        self.disposed = True
        self.poll.stop()
        for widget in self._parents:
            if isValid(widget):
                widget.removeEventFilter(self)
        QDialog.reject(self)
        event.accept()


def open_selected(pane):
    """Native entry carries the actual loaded deck observation, owner and draft state."""
    from pathlib import Path

    from paper_daily import store
    from paper_daily.sync_files import canonical_json

    language = getattr(pane.window(), "language", "zh-TW")
    text = COPY.get(language, COPY["en"])
    existing = getattr(pane, "_deck_audit_dialog", None)
    if existing is not None and isValid(existing) and not existing.disposed:
        if existing._same() and not existing._closing:
            existing.show()
            existing.raise_()
            return True
        if not existing.close():
            existing.raise_()
            return False
    if pane.busy or pane._dirty or pane._canvas_dirty or pane._layout_reset:
        pane.status.setText(text["draft"])
        return False
    selected = pane.deck
    observation = getattr(selected, "_file_observation", None)
    operation = getattr(selected, "_file_operation", None)
    owner = getattr(pane, "_annotation_owner", None)
    if not selected or not observation or not operation or owner is None:
        pane.status.setText(text["unavailable"])
        return False
    try:
        database = Path(observation["database"]).resolve(strict=True)
        info = database.stat()
        if (
            observation.get("database_identity") != [info.st_dev, info.st_ino]
            or database != Path(store.DB_PATH).resolve()
            or owner.database != database
            or owner.paper_id != pane.paper_id
            or observation["local_id"] != pane.paper_id
            or observation["mode"] != pane._mode
        ):
            raise ValueError("Stale saved deck")
        captured_epoch = pane._annotation_epoch
        operation_json = canonical_json(operation)
        paper, slot = pane.paper_id, pane._mode

        def current():
            return (
                isValid(pane)
                and pane.deck is selected
                and pane.paper_id == paper
                and pane._mode == slot
                and pane._annotation_owner is owner
                and pane._annotation_epoch == captured_epoch
                and Path(store.DB_PATH).resolve() == database
                and not pane._producer_busy
                and not pane._dirty
                and not pane._canvas_dirty
                and not pane._layout_reset
                and canonical_json(getattr(selected, "_file_operation", None)) == operation_json
            )

        service = DeckAuditReader(
            database,
            paper,
            slot,
            operation["operation_id"],
            selected=selected.to_dict(),
            selected_operation=operation,
            owner=owner,
            expected_binding=[observation["workspace_id"], observation["device_id"]],
            current_path=lambda: store.DB_PATH,
        )
        dialog = DeckAuditDialog(service, current=current, language=language, parent=pane)
    except (OSError, ValueError, KeyError, TypeError):
        pane.status.setText(text["unavailable"])
        return False
    pane._deck_audit_dialog = dialog
    dialog.open()
    return True
