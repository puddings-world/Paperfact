"""Keyboard-accessible retained-work review; plain text, no model or HTML execution."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from paper_daily.research_review import COMPOUND_ORIGINS, FILE_ORIGINS, ResearchReview

LABELS = {
    "en": {
        "title": "Review changes",
        "archived_draft": "Saved historical draft",
        "archived_reason": (
            "Original draft preserved. Continue editing to choose and verify a current target."
        ),
        "resume": "Continue editing…",
        "typed_resume": "This content needs its typed recovery flow. You can copy or export it.",
        "revise_claims": "Revise claims…",
        "revise_highlights": "Revise highlights…",
        "highlight_reason": "Edit quotations and reasons, then verify and confirm the group.",
        "highlight_workspace": "Create an editable workspace copy before revising highlights.",
        "claim_reason": "Edit assertions and quotations, then verify and confirm in Revise claims.",
        "claim_workspace": "Create a managed editable workspace copy before revising these claims.",
        "verify_draft": "Verify draft sources",
        "map_note": "Confirm original and position…",
        "recorded_note": "Old draft recorded: {source}",
        "unknown_source": "unknown",
        "chosen_note": "This reviewed note: PDF {source}, page {page}",
        "current_pdf": "Currently selected PDF",
        "legacy_note_position": (
            "Legacy position has no saved passage text. "
            "Use Confirm original and position to record the selected words."
        ),
        "current_note_source": "Current note: page {page} · PDF {source}",
        "retained_note_source": "Reviewed note: page {page} · PDF {source}",
        "current": "Current",
        "original": "Original",
        "retained": "Retained result / draft",
        "apply": "Apply reviewed draft",
        "verified_slides": "Slides and images verified. Compare the versions before applying.",
        "deleted_slides": (
            "These slides were deleted. Review and confirm restoration as a new version."
        ),
        "restore_slides": "Restore reviewed slides",
        "confirm_restore_slides": "Restore these deleted slides as a new editable version?",
        "apply_slides": "Apply reviewed slides",
        "verify_slides": "Verify retained slides",
        "confirm_slides": "Replace the current slides with this reviewed retained version?",
        "retained_slides": "Retained slides",
        "local_slides": "Local retained presentation; verify it before applying.",
        "enrolled_slides": "Retained presentation; verify the content and sources before applying.",
        "evidence": "Sources and images",
        "pdf_mismatch": "This proposal cites another PDF version; the current PDF stays selected.",
        "decision_applied": "applied locally",
        "decision_kept": "kept current locally",
        "decision_help": "Local review decision; not confirmation of synchronization.",
        "decision_retry": "Decision status unavailable; Review latest version to retry.",
        "saved_local": "Saved locally",
        "apply_group": "Apply reviewed group",
        "retained_group": "Retained group",
        "keep": "Keep current",
        "copy": "Copy",
        "export": "Export text…",
        "close": "Close",
        "more": "Load more",
        "refresh": "Review latest version",
        "loading": "Loading preview…",
        "saving": "Saving reviewed decision…",
        "empty": "No retained work in this workspace",
        "absent": "Absent or unavailable",
        "saved": "Saved locally; synchronization follows the workspace policy",
        "kept": "Kept current. The retained result remains available.",
        "copied": "Research text copied",
        "exported": "Research text exported",
        "draft": "Draft waiting to be saved locally",
        "draft_saved": "Draft saved locally",
        "draft_failed": "Draft not saved. This window remains open: ",
        "draft_copy": "Save a separate draft",
        "drafts": "Drafts…",
        "open": "Open selected draft",
        "source": "Source PDF SHA-256",
        "target": "Choose target…",
        "confirm": (
            "Apply this retained result to the selected target? This is an explicit reattachment."
        ),
    },
    "zh-TW": {
        "title": "審閱保留內容",
        "archived_draft": "已存歷史草稿",
        "archived_reason": "已保留原稿；按「繼續編輯」選擇目前目標，核對原文後再套用。",
        "resume": "繼續編輯…",
        "typed_resume": "這類內容仍需專用恢復流程；可先複製或匯出原稿。",
        "revise_claims": "修訂研究主張…",
        "revise_highlights": "修訂原文重點…",
        "highlight_reason": "修訂引句與理由，核對原文後確認套用完整重點。",
        "highlight_workspace": "請先建立受管理的可編輯工作區副本，再修訂重點。",
        "claim_reason": "按「修訂研究主張」編輯主張與引句，再核對原文並確認套用。",
        "claim_workspace": "請先建立受管理的可編輯工作區副本，再修訂這些主張。",
        "verify_draft": "核對草稿原文",
        "map_note": "確認原文與位置…",
        "recorded_note": "舊稿當時記錄：{source}",
        "unknown_source": "未知",
        "chosen_note": "這次審閱筆記：PDF {source}，第 {page} 頁",
        "current_pdf": "目前選用 PDF",
        "legacy_note_position": "舊版位置沒有保存原文文字；可用「確認原文與位置」重新選取段落。",
        "current_note_source": "目前筆記：第 {page} 頁 · PDF {source}",
        "retained_note_source": "審閱筆記：第 {page} 頁 · PDF {source}",
        "current": "目前版本",
        "original": "原始版本",
        "retained": "保留結果／編輯草稿",
        "apply": "套用已審閱草稿",
        "verified_slides": "已核對簡報與原圖，請比對各版本後再確認套用。",
        "deleted_slides": "這份簡報已刪除，請核對保留稿，確認後恢復為新版本。",
        "restore_slides": "恢復已審閱簡報",
        "confirm_restore_slides": "確定將這份已刪除的簡報恢復為新的可編輯版本？",
        "apply_slides": "套用已審閱簡報",
        "verify_slides": "核對保留簡報",
        "confirm_slides": "確定以這份已審閱的保留稿取代目前簡報？",
        "retained_slides": "保留簡報",
        "local_slides": "本機保留簡報；請先核對內容，再確認套用。",
        "enrolled_slides": "保留簡報；請先核對內容與來源，再確認套用。",
        "evidence": "來源與素材",
        "pdf_mismatch": "這份簡報引用另一版原文，目前選用的 PDF 不會被替換。",
        "decision_applied": "已在本機套用",
        "decision_kept": "已在本機保留目前版本",
        "decision_help": "本機審閱決定，不代表已完成同步。",
        "decision_retry": "決定狀態尚未更新；可按「重新審閱最新版本」重試。",
        "saved_local": "已儲存於本機",
        "apply_group": "套用已審閱資料組",
        "retained_group": "保留資料組",
        "keep": "保留目前版本",
        "copy": "複製",
        "export": "匯出文字…",
        "close": "關閉",
        "more": "載入更多",
        "refresh": "重新審閱最新版本",
        "loading": "正在載入預覽…",
        "saving": "正在儲存審閱決定…",
        "empty": "此工作區沒有待審閱的保留內容",
        "absent": "不存在或無法取得",
        "saved": "已儲存於本機；後續依工作區設定同步",
        "kept": "已保留目前版本，候選結果仍可再次查看。",
        "copied": "已複製研究文字",
        "exported": "已匯出研究文字",
        "draft": "草稿等待儲存於本機",
        "draft_saved": "草稿已儲存於本機",
        "draft_failed": "草稿尚未儲存，視窗會保持開啟：",
        "draft_copy": "另存一份草稿",
        "drafts": "已存草稿…",
        "open": "開啟所選草稿",
        "source": "來源 PDF SHA-256",
        "target": "選擇套用對象…",
        "confirm": "確定將此保留結果套用至所選對象？這會明確建立新的內容歸屬。",
    },
}


def body_text(value):
    if isinstance(value, dict):
        if isinstance(value.get("body"), str):
            return value["body"]
        if isinstance(value.get("summary"), str):
            return value["summary"]
        if isinstance(value.get("data"), dict):
            return body_text(value["data"])
    return None


def preview_text(value, absent):
    if value is None:
        return absent
    body = body_text(value)
    if body is not None:
        return body
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)


class ReviewDialog(QDialog):
    """Own one pinned workspace session; asynchronous results cannot cross selections.

    The host must call close() when switching workspaces. No global database or
    account lookup occurs here. Drafts survive selection changes and failed writes.
    """

    def __init__(self, database=None, parent=None, *, service=None, language="en"):
        super().__init__(parent)
        self.service = service or ResearchReview(database)
        self.claim_editor = None
        self._decision_pending = set()
        self._claim_closing_result = None
        self.words = LABELS.get(language, LABELS["en"])
        self.setWindowTitle(self.words["title"])
        self.resize(1000, 680)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="paperfact-review")
        self.jobs = []
        self.generation = 0
        self.disposed = False
        self.busy = False
        self.cursor = None
        self.preview = None
        self.drafts = {}
        self.persisted = {}
        self.dirty = {}
        self.draft_errors = {}
        self.corrupt_text = None
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(500)
        self.autosave.timeout.connect(self._save_pending)
        self.request = None
        self.selection_key = None
        self.list = QListWidget()
        self.list.setAccessibleName(self.words["title"])
        self.list.setMinimumWidth(170)
        self.list.currentItemChanged.connect(self._select)
        self.more = QPushButton(self.words["more"])
        self.more.clicked.connect(self.load_page)
        navigation = QWidget()
        nav = QVBoxLayout(navigation)
        nav.addWidget(self.list)
        nav.addWidget(self.more)
        self.tabs = QTabWidget()
        self.original = QPlainTextEdit()
        self.current = QPlainTextEdit()
        self.draft = QPlainTextEdit()
        for key, editor in (
            ("current", self.current),
            ("original", self.original),
            ("retained", self.draft),
        ):
            editor.setAccessibleName(self.words[key])
            editor.setReadOnly(True)
            self.tabs.addTab(editor, self.words[key])
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setAccessibleName(self.words["evidence"])
        self.evidence_index = self.tabs.addTab(self.evidence, self.words["evidence"])
        self.tabs.setTabVisible(self.evidence_index, False)
        self.tabs.setCurrentWidget(self.draft)
        self.draft.textChanged.connect(self._edited)
        self.split = QSplitter()
        self.split.addWidget(navigation)
        self.split.addWidget(self.tabs)
        self.split.setSizes([230, 770])
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.source = QLabel()
        self.source.setTextFormat(Qt.TextFormat.PlainText)
        self.source.setWordWrap(True)
        from paper_daily.desktop.retained_original_ui import RetainedOriginalControl

        self.originals = RetainedOriginalControl(self, language)
        self.apply = QPushButton(self.words["apply"])
        self.keep = QPushButton(self.words["keep"])
        self.copy = QPushButton(self.words["copy"])
        self.export_button = QPushButton(self.words["export"])
        self.resume_button = QPushButton(self.words["resume"])
        self.resume_button.setAutoDefault(False)
        self.resume_button.clicked.connect(self._resume_historical)
        self.resume_button.hide()
        self.claim_button = self.resume_button
        self.map_note_button = QPushButton(self.words["map_note"])
        self.map_note_button.setAutoDefault(False)
        self.map_note_button.clicked.connect(self._map_note_source)
        self.map_note_button.hide()
        self.target_button = QPushButton(self.words["target"])
        self.target_button.clicked.connect(self._choose_target)
        self.refresh = QPushButton(self.words["refresh"])
        self.draft_history = QPushButton(self.words["drafts"])
        self.draft_history.clicked.connect(self._choose_draft)
        self.draft_history.setEnabled(False)
        self.draft_copy = QPushButton(self.words["draft_copy"])
        self.draft_copy.clicked.connect(self._save_separate)
        self.draft_copy.hide()
        self.close_button = QPushButton(self.words["close"])
        self.apply.clicked.connect(lambda: self._decide(False))
        self.keep.clicked.connect(lambda: self._decide(True))
        self.copy.clicked.connect(self._copy)
        self.export_button.clicked.connect(self._export)
        self.refresh.clicked.connect(self._refresh)
        self.close_button.clicked.connect(self.reject)
        for button in (
            self.apply,
            self.keep,
            self.copy,
            self.export_button,
            self.refresh,
            self.target_button,
        ):
            button.setAutoDefault(False)
            button.setEnabled(False)
        # Two short rows keep every action reachable at narrow desktop widths.
        actions = QHBoxLayout()
        for button in (self.apply, self.keep, self.refresh):
            actions.addWidget(button)
        secondary = QHBoxLayout()
        secondary.addWidget(self.copy)
        secondary.addWidget(self.export_button)
        secondary.addWidget(self.target_button)
        secondary.addWidget(self.resume_button)
        secondary.addWidget(self.draft_history)
        secondary.addWidget(self.draft_copy)
        secondary.addStretch()
        secondary.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.split, 1)
        layout.addWidget(self.source)
        layout.addWidget(self.originals.widget)
        layout.addWidget(self.map_note_button)
        layout.addWidget(self.status)
        layout.addLayout(actions)
        layout.addLayout(secondary)
        self.poll = QTimer(self)
        self.poll.setInterval(25)
        self.poll.timeout.connect(self._poll)
        self.poll.start()
        self.load_page()

    def _submit(self, kind, call, callback, on_error=None):
        self.jobs.append((self.executor.submit(call), self.generation, kind, callback, on_error))

    def _poll(self):
        for job in self.jobs[:]:
            future, generation, kind, callback, on_error = job
            if not future.done():
                continue
            self.jobs.remove(job)
            if self.disposed or (kind in {"preview", "original"} and generation != self.generation):
                continue
            try:
                callback(future.result())
            except Exception as error:
                if on_error is not None:
                    on_error(error)
                self.status.setText(str(error))
                if kind == "save":
                    self.busy = False
                self._buttons()
                if kind == "page":
                    self.more.setEnabled(True)

    def load_page(self):
        if not self.more.isEnabled() or self.disposed:
            return
        self.more.setEnabled(False)
        cursor = self.cursor
        self._submit("page", lambda: self.service.page(after=cursor), self._page)

    def _row_label(self, row):
        label = row.get("summary") or f"{row['origin']} · {row['id'][:38]}"
        if row["origin"] == "archived_draft":
            label = self.words["archived_draft"] + " · " + label
        replacements = (
            {
                "close_readings": "逐段精讀",
                "list_surveys": "清單文獻調查",
                "dives": "深度分析",
                "paper_context": "研究脈絡",
                "citations": "引用資料組",
                "fetch": "後續文獻蒐集",
                "judge": "後續文獻分析",
                "resources": "研究資源組",
                "edit_reference": "引用編輯",
                "edit_followup": "後續文獻編輯",
            }
            if self.words is LABELS["zh-TW"]
            else {
                "close_readings": "Close reading",
                "list_surveys": "List survey",
                "dives": "Deep analysis",
                "paper_context": "Research context",
                "citations": "Citation group",
                "fetch": "Followup collection",
                "judge": "Followup analysis",
                "resources": "Resource group",
                "edit_reference": "Reference edit",
                "edit_followup": "Followup edit",
            }
        )
        for name, title in replacements.items():
            if label.startswith(name + " · "):
                label = title + label[len(name) :]
        if row["origin"] in FILE_ORIGINS:
            label = self.words["retained_slides"] + " · " + (row.get("summary") or row["id"][:12])
        if row["decision"]:
            label += " · " + self.words["decision_" + row["decision"]]
        return label

    def _page(self, page):
        for row in page["items"]:
            label = self._row_label(row)
            item = QListWidgetItem(label)
            item.setToolTip(row["origin"] + " · " + row["id"])
            item.setData(Qt.ItemDataRole.UserRole, (row["origin"], row["id"]))
            item.setData(Qt.ItemDataRole.UserRole + 1, dict(row))
            self.list.addItem(item)
        self.cursor = page["next"]
        self.more.setEnabled(self.cursor is not None)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        if not self.list.count():
            self.status.setText(self.words["empty"])

    def _remember(self):
        if self.preview and self.selection_key:
            self.drafts[self.selection_key] = (
                self.preview,
                self.draft.toPlainText(),
                self.request,
                self.draft.textCursor().position(),
                self.draft.verticalScrollBar().value(),
            )

    def _select(self, item, _previous=None):
        self.originals.invalidate()
        self._remember()
        self.generation += 1
        self.preview = None
        self.corrupt_text = None
        self.selection_key = tuple(item.data(Qt.ItemDataRole.UserRole)) if item else None
        self._buttons()
        if item is None:
            return
        cached = self.drafts.get(self.selection_key)
        if cached:
            self._display(cached[0], cached=cached)
            return
        self.status.setText(self.words["loading"])
        origin, identity = self.selection_key
        self._submit("preview", lambda: self._load_selection(origin, identity), self._loaded)

    def _load_selection(self, origin, identity):
        saved = None
        if origin == "archived_draft":
            for kind in ("archived_note_resume", "archived_resume"):
                saved = self.service.load_draft(kind, identity)
                if saved is not None:
                    break
        saved = saved or self.service.load_draft(origin, identity)
        if saved is not None:
            return saved.get("preview"), saved
        return self.service.preview(origin, identity), None

    def _loaded(self, result):
        preview, saved = result
        if saved and saved["state"] == "corrupt":
            self.preview = None
            self.corrupt_text = saved.get("body")
            self.original.clear()
            self.current.clear()
            self.draft.blockSignals(True)
            self.draft.setPlainText(self.corrupt_text or "")
            self.draft.blockSignals(False)
            self.source.clear()
            self.status.setText(saved["reason"])
            self._buttons()
            return
        self._display(preview)
        if saved:
            self.persisted[self.selection_key] = {
                "draft_id": saved["draft_id"],
                "revision": saved["revision"],
            }
            self.request = saved["request_id"]
            self.draft.blockSignals(True)
            self.draft.setPlainText(saved["body"])
            self.draft.blockSignals(False)
            self.status.setText(saved["reason"])
            self._remember()
            self._buttons()

    def _display(self, preview, *, cached=None):
        self.preview = preview
        data = preview.data
        self.request = cached[2] if cached else str(uuid4())
        grouped = data["origin"] in COMPOUND_ORIGINS
        from paper_daily.desktop.claim_draft_dialog import LABELS as CLAIM_LABELS
        from paper_daily.desktop.claim_fields import is_claim, readable

        claim_mode = is_claim(data)
        from paper_daily.desktop.highlight_draft_dialog import LABELS as HIGHLIGHT_LABELS
        from paper_daily.desktop.highlight_fields import (
            is_highlight,
        )
        from paper_daily.desktop.highlight_fields import (
            readable as highlight_readable,
        )

        highlight_mode = is_highlight(data)
        highlight_words = {
            key: pair[self.words is LABELS["zh-TW"]] for key, pair in HIGHLIGHT_LABELS.items()
        }

        claim_words = {
            key: pair[self.words is LABELS["zh-TW"]] for key, pair in CLAIM_LABELS.items()
        }

        def render(value):
            if claim_mode:
                return readable(value, claim_words)
            if highlight_mode:
                return highlight_readable(value, highlight_words)
            if data["origin"] in FILE_ORIGINS:
                from paper_daily.desktop.review_deck_text import deck_text

                return deck_text(value, chinese=self.words is LABELS["zh-TW"])
            if grouped:
                from paper_daily.desktop.review_compound_text import group_text

                return group_text(value, chinese=self.words is LABELS["zh-TW"])
            return preview_text(value, self.words["absent"])

        self.tabs.setTabText(2, self.words["retained_group" if grouped else "retained"])
        has_evidence = data["origin"] in {"local_deck", "enrolled_deck"}
        self.tabs.setTabVisible(self.evidence_index, has_evidence)
        if has_evidence:
            from paper_daily.desktop.review_deck_text import evidence_text

            self.evidence.setPlainText(evidence_text(data, chinese=self.words is LABELS["zh-TW"]))
        else:
            self.evidence.clear()
        self.original.setPlainText(render(data["original"]))
        self.current.setPlainText(render(data["current"]))
        self.draft.blockSignals(True)
        self.draft.setPlainText(cached[1] if cached else render(data["retained"]))
        self.draft.blockSignals(False)
        editable = data["editable"] and body_text(data["retained"]) is not None
        self.draft.setReadOnly(not editable)
        if cached:
            cursor = self.draft.textCursor()
            cursor.setPosition(cached[3])
            self.draft.setTextCursor(cursor)
            self.draft.verticalScrollBar().setValue(cached[4])
        self.source.setText(
            f"{self.words['source']}: {data['source_hash']}" if data["source_hash"] else ""
        )
        target = data.get("target")
        if target:
            self.source.setText(self.source.text() + "\n" + target["title"] + " · " + target["id"])
        if data["origin"] == "enrolled_deck":
            document = ((data.get("expected") or {}).get("observation") or {}).get(
                "applied_document"
            )
            if document and data["source_hash"] and document["sha256"] != data["source_hash"]:
                self.source.setText(self.source.text() + "\n" + self.words["pdf_mismatch"])
        if data["origin"] in {"archived_resume", "archived_note_resume"}:
            from paper_daily.review_draft_resumption import source_intent

            document = source_intent(data).document
            current_hash = document["sha256"] if document else self.words["absent"]
            self.source.setText(
                self.source.text() + "\n" + self.words["current_pdf"] + ": " + current_hash
            )
        if data["origin"] == "archived_note_resume":
            from paper_daily.enrollment_history import _value

            lines = []
            for name, key in (
                ("current", "current_note_source"),
                ("retained", "retained_note_source"),
            ):
                note = data[name]
                anchor = note["anchor"]
                if isinstance(anchor, str):
                    anchor = _value(anchor)
                sha = anchor.get("document_hash") if anchor else None
                lines.append(
                    self.words[key].format(
                        page=note["page"] if note["page"] is not None else self.words["absent"],
                        source=sha or self.words["absent"],
                    )
                )
            note = data["retained"]
            if (note["page"] is not None or note["anchor"] is not None) and not (
                isinstance(note["anchor"], dict) and "selection" in note["anchor"]
            ):
                lines.append(self.words["legacy_note_position"])
            choice = data["expected"].get("source_choice")
            if choice:
                lines.append(
                    self.words["recorded_note"].format(
                        source=choice["recorded_source"] or self.words["unknown_source"]
                    )
                )
                if choice["anchor"] is not None:
                    lines.append(choice["anchor"]["selection"]["quote"][:300])
            self.source.setText(self.source.text() + "\n" + "\n".join(lines))
        reason = data["reason"]
        if data["origin"] == "archived_draft":
            reason = self.words[
                "archived_reason" if data.get("resume_supported") else "typed_resume"
            ]
        if data["origin"] in {"local_deck", "enrolled_deck"} and not data["apply"]:
            reason = self.words[
                "local_slides" if data["origin"] == "local_deck" else "enrolled_slides"
            ]
        if data["origin"] in FILE_ORIGINS and data["apply"]:
            reason = self.words[
                "deleted_slides" if data["target"].get("restoring") else "verified_slides"
            ]
        if claim_mode:
            reason = self.words[
                "claim_reason"
                if self.service.binding and not self.service.recovery
                else "claim_workspace"
            ]
        if highlight_mode:
            reason = self.words[
                "highlight_reason"
                if self.service.binding and not self.service.recovery
                else "highlight_workspace"
            ]
        self.status.setText(reason)
        if self.selection_key in self.draft_errors:
            self.status.setText(self.words["draft_failed"] + self.draft_errors[self.selection_key])
        self.draft_copy.setVisible(self.selection_key in self.draft_errors)
        self.originals.display(data)
        self._buttons()

    def _buttons(self):
        self.originals.controls()
        loaded = self.preview is not None and not self.busy
        self.list.setEnabled(not self.busy)
        self.draft_history.setVisible(
            not loaded
            or self.preview.data["origin"]
            not in {*COMPOUND_ORIGINS, *FILE_ORIGINS, "archived_draft"}
        )
        self.draft_history.setEnabled(not self.busy and self.selection_key is not None)
        editable = (
            loaded
            and self.preview.data["editable"]
            and body_text(self.preview.data["retained"]) is not None
        )
        self.draft.setReadOnly(not editable)
        resumed = self.preview.data.get("resume_state", "ready") if loaded else None
        is_file = loaded and self.preview.data["origin"] in FILE_ORIGINS
        is_resume = loaded and self.preview.data["origin"] in {
            "archived_resume",
            "archived_note_resume",
        }
        self.refresh.setText(
            self.words["verify_draft" if is_resume else "verify_slides" if is_file else "refresh"]
        )
        self.map_note_button.setVisible(
            loaded and self.preview.data["origin"] == "archived_note_resume"
        )
        self.map_note_button.setEnabled(
            loaded
            and self.preview.data["origin"] == "archived_note_resume"
            and resumed in {"ready", "verification_required"}
        )
        from paper_daily.desktop.claim_fields import is_claim
        from paper_daily.desktop.highlight_fields import is_highlight

        claim_mode = loaded and is_claim(self.preview.data)
        highlight_mode = loaded and is_highlight(self.preview.data)
        structured_mode = claim_mode or highlight_mode
        self.resume_button.setText(
            self.words[
                "revise_highlights"
                if highlight_mode
                else "revise_claims"
                if claim_mode
                else "resume"
            ]
        )
        self.resume_button.setToolTip(
            self.words["highlight_workspace" if highlight_mode else "claim_workspace"]
            if structured_mode and (not self.service.binding or self.service.recovery)
            else ""
        )
        self.resume_button.setVisible(
            loaded and (structured_mode or self.preview.data["origin"] == "archived_draft")
        )
        self.resume_button.setEnabled(
            loaded
            and (
                bool(self.service.binding) and not self.service.recovery
                if structured_mode
                else bool(self.preview.data.get("resume_supported"))
            )
        )
        self.apply.setText(
            self.words[
                "restore_slides"
                if (self.preview.data.get("target") or {}).get("restoring")
                else "apply_slides"
            ]
            if is_file
            else self.words["apply_group"]
            if loaded and self.preview.data["origin"] in COMPOUND_ORIGINS
            else self.words["apply"]
        )
        self.apply.setEnabled(loaded and self.preview.data["apply"] and resumed == "ready")
        if resumed == "foreign":
            self.draft.setReadOnly(True)
        for button in (self.keep, self.copy, self.export_button, self.refresh, self.target_button):
            button.setEnabled(loaded)
        from paper_daily.research_annotation_review import remote_group

        self.target_button.setEnabled(
            loaded
            and (
                self.preview.data["origin"]
                in {
                    "generation",
                    "sidecar",
                    "archived_resume",
                    "archived_note_resume",
                    *COMPOUND_ORIGINS,
                }
                or remote_group(self.preview.data)
            )
        )
        if resumed == "foreign" or (loaded and self.preview.data["origin"] == "archived_draft"):
            self.keep.setEnabled(False)
        if self.corrupt_text is not None:
            self.copy.setEnabled(True)
            self.export_button.setEnabled(True)

    def _edited(self):
        if self.preview:
            self.request = str(uuid4())
            self.status.setText(self.words["draft"])
            self._remember()
            self._mark_dirty()

    def _body(self):
        return (
            self.draft.toPlainText()
            if self.preview is not None and body_text(self.preview.data["retained"]) is not None
            else None
        )

    def _mark_dirty(self):
        body = self._body()
        if (
            self.preview is None
            or body is None
            or self.preview.data.get("resume_state") == "foreign"
        ):
            return
        self.dirty[self.selection_key] = (self.preview, body, self.request)
        self.autosave.start()

    def _save_pending(self, *, all_items=False):
        if self.busy and not all_items:
            self.autosave.start()
            return False
        entries = list(self.dirty.items())
        if not all_items:
            entries = entries[:1]
        for key, (preview, body, request) in entries:
            try:
                saved = self.service.save_draft(
                    preview, body, request, **self.persisted.get(key, {})
                )
            except Exception as error:
                self.draft_errors[key] = str(error)
                self.status.setText(self.words["draft_failed"] + str(error))
                self.draft_copy.setVisible(key == self.selection_key)
                return False
            self.persisted[key] = saved
            self.dirty.pop(key, None)
            self.draft_errors.pop(key, None)
            if key == self.selection_key:
                self.status.setText(self.words["draft_saved"])
                self.draft_copy.hide()
        if self.dirty:
            self.autosave.start()
        return True

    def _save_separate(self):
        if not self.preview or self.busy:
            return
        key = self.selection_key
        previous = self.persisted.pop(key, None)
        self._mark_dirty()
        if not self._save_pending(all_items=True) and previous:
            self.persisted[key] = previous

    def _decide(self, keep):
        if self.busy or self.preview is None:
            return
        confirm = False
        if not keep and self.preview.data.get("requires_confirmation"):
            target = self.preview.data["target"]
            confirmation = "confirm"
            if self.preview.data["origin"] in FILE_ORIGINS:
                confirmation = (
                    "confirm_restore_slides" if target.get("restoring") else "confirm_slides"
                )
            message = self.words[confirmation] + "\n\n" + target["title"] + "\n" + target["id"]
            if self.preview.data["origin"] == "archived_note_resume":
                data = self.preview.data
                note = data["retained"]
                message += "\n\n" + self.words["chosen_note"].format(
                    source=data["source_hash"] or self.words["absent"],
                    page=note["page"] if note["page"] is not None else self.words["absent"],
                )
                if isinstance(note["anchor"], dict) and "selection" in note["anchor"]:
                    message += "\n" + note["anchor"]["selection"]["quote"][:300]
                elif note["page"] is not None or note["anchor"] is not None:
                    message += "\n" + self.words["legacy_note_position"]
            answer = QMessageBox.question(
                self,
                self.words["target"],
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            confirm = True
        self._remember()
        self._mark_dirty()
        if not self._save_pending(all_items=True):
            return
        preview, body, identity = self.preview, self._body(), self.request
        self.busy = True
        self._buttons()
        self.status.setText(self.words["saving"])
        self._submit(
            "save",
            lambda: self.service.decide(
                preview, keep=keep, body=body, request_id=identity, confirm_target=confirm
            ),
            self._saved,
        )

    def _saved(self, result):
        self.busy = False
        self._buttons()
        self.apply.setEnabled(False)
        self.keep.setEnabled(False)
        self.status.setText(
            self.words["kept"]
            if result["decision"] == "kept"
            else self.words[
                "saved_local"
                if self.selection_key and self.selection_key[0] == "local_deck"
                else "saved"
            ]
        )

    def _refresh(self):
        if not self.preview or self.busy:
            return
        self._queue_decision(self.selection_key)
        self.originals.invalidate()
        self._remember()
        draft = self._body()
        observed = self.preview
        self.generation += 1
        origin, identity = self.selection_key
        self.status.setText(self.words["loading"])
        self.preview = None
        self._buttons()

        def refresh():
            if observed.data["origin"] in {"archived_resume", "archived_note_resume"}:
                return self.service.verify_resumed_draft(observed)
            preview = self.service.preview(origin, identity)
            if origin in FILE_ORIGINS:
                return self.service.prepare_file(preview)
            if observed.data.get("requires_confirmation"):
                return self.service.target_preview(preview, observed.data["target"]["id"])
            return preview

        def loaded(preview):
            self._display(preview)
            if draft is not None:
                self.draft.blockSignals(True)
                self.draft.setPlainText(draft)
                self.draft.blockSignals(False)
                self._remember()
                self._mark_dirty()

        def failed(_error):
            self.preview = (
                self.service.require_draft_verification(observed)
                if observed.data["origin"] in {"archived_resume", "archived_note_resume"}
                else observed
            )

        self._submit("preview", refresh, loaded, failed)

    def _choose_target(self):
        if not self.preview or self.busy:
            return
        chooser = TargetDialog(self.service, self.preview, self.words, self)
        if chooser.exec() != QDialog.DialogCode.Accepted or not chooser.identity:
            return
        draft = self._body()
        observed = self.preview
        identity = chooser.identity
        self.generation += 1
        self.preview = None
        self._buttons()
        self.status.setText(self.words["loading"])

        def selected(preview):
            if observed.data.get("resume_state") == "foreign":
                self.persisted.pop(self.selection_key, None)
            self._display(preview)
            if draft is not None:
                self.draft.setPlainText(draft)
            self._mark_dirty()

        def failed(_error):
            self.preview = observed

        def prepare():
            preview = self.service.target_preview(observed, identity)
            if preview.data["origin"] in {"archived_resume", "archived_note_resume"}:
                return self.service.verify_resumed_draft(preview)
            return preview

        self._submit("preview", prepare, selected, failed)

    def _map_note_source(self):
        if (
            self.preview is None
            or self.busy
            or self.preview.data["origin"] != "archived_note_resume"
        ):
            return
        from paper_daily.desktop.note_source_dialog import NoteSourceDialog

        observed = self.preview
        body, request = self._body(), self.request
        cursor = self.draft.textCursor().position()
        scroll = self.draft.verticalScrollBar().value()
        dialog = NoteSourceDialog(
            self.service,
            observed,
            self,
            language="zh-TW" if self.words is LABELS["zh-TW"] else "en",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result_preview is None:
            return
        if self.disposed or self.preview != observed:
            return
        self.originals.invalidate()
        self.generation += 1
        chosen = dialog.result_preview
        self._display(chosen, cached=(chosen, body, request, cursor, scroll))
        self._remember()
        self._mark_dirty()
        if self._save_pending(all_items=True):
            self._refresh()

    def _open_claim_editor(self):
        from paper_daily.desktop.claim_draft_dialog import ClaimDraftDialog

        if self.claim_editor is not None and not self.claim_editor.disposed:
            self.claim_editor.show()
            self.claim_editor.raise_()
            return
        origin, identity = self.selection_key
        language = "zh-TW" if self.words is LABELS["zh-TW"] else "en"
        from paper_daily.desktop.highlight_draft_dialog import HighlightDraftDialog
        from paper_daily.desktop.highlight_fields import is_highlight

        editor_type = HighlightDraftDialog if is_highlight(self.preview.data) else ClaimDraftDialog
        self.claim_editor = editor_type(
            self.service.path, origin, identity, self, language=language
        )
        editor, key = self.claim_editor, self.selection_key
        editor.finished.connect(lambda _result: self._claim_closed(editor, key))
        editor.show()

    def _claim_closed(self, editor, key):
        if self.disposed or editor is not self.claim_editor:
            return
        result, self._claim_closing_result = self._claim_closing_result, None
        if result is not None:
            QTimer.singleShot(0, lambda: self.done(result) if not self.disposed else None)
        else:
            self._queue_decision(key)

    def _queue_decision(self, key, *, retry=True):
        from paper_daily import review_decisions

        if self.disposed or key is None or key in self._decision_pending:
            return
        self._decision_pending.add(key)

        def read():
            try:
                return review_decisions.capture(self.service, *key)
            except (ValueError, OSError, sqlite3.Error):
                return None

        def received(snapshot):
            self._decision_pending.discard(key)
            if self.disposed:
                return
            if snapshot is not None and not review_decisions.current(snapshot):
                if retry:
                    self._queue_decision(key, retry=False)
                    return
                snapshot = None
            item = next(
                (
                    self.list.item(i)
                    for i in range(self.list.count())
                    if tuple(self.list.item(i).data(Qt.ItemDataRole.UserRole)) == key
                ),
                None,
            )
            if item is None:
                return
            if snapshot is None or snapshot.service is not self.service or snapshot.key != key:
                item.setToolTip(key[0] + " · " + key[1] + "\n" + self.words["decision_retry"])
                return
            row = item.data(Qt.ItemDataRole.UserRole + 1)
            if not isinstance(row, dict):
                return
            row["decision"] = snapshot.decision
            scroll = self.list.verticalScrollBar().value()
            item.setText(self._row_label(row))
            item.setData(Qt.ItemDataRole.UserRole + 1, row)
            item.setToolTip(
                key[0]
                + " · "
                + key[1]
                + ("\n" + self.words["decision_help"] if snapshot.decision else "")
            )
            self.list.verticalScrollBar().setValue(scroll)

        self._submit("decision", read, received)

    def _resume_historical(self):
        from paper_daily.desktop.claim_fields import is_claim
        from paper_daily.desktop.highlight_fields import is_highlight

        if (
            self.preview is not None
            and not self.busy
            and (is_claim(self.preview.data) or is_highlight(self.preview.data))
        ):
            self._open_claim_editor()
            return
        if self.preview is None or self.busy or self.preview.data["origin"] != "archived_draft":
            return
        chooser = TargetDialog(self.service, self.preview, self.words, self)
        if chooser.exec() != QDialog.DialogCode.Accepted or not chooser.identity:
            return
        observed = self.preview
        identity = chooser.identity
        self.generation += 1
        self.preview = None
        self._buttons()
        self.status.setText(self.words["loading"])

        def prepare():
            preview = self.service.resume_draft(observed, identity)
            try:
                return self.service.verify_resumed_draft(preview), None
            except ValueError as error:
                if self.service.closed or preview.data["origin"] != "archived_note_resume":
                    raise
                # Keep the explicitly selected note available for source repair.
                # A failed automatic verification never grants Apply permission.
                return self.service.require_draft_verification(preview), str(error)

        def selected(result):
            preview, error = result
            self.persisted.pop(self.selection_key, None)
            self._display(preview)
            self._remember()
            self._mark_dirty()
            if error:
                self.status.setText(error + " · " + self.words["map_note"])

        def failed(_error):
            self.preview = observed

        self._submit("preview", prepare, selected, failed)

    def _choose_draft(self):
        if self.selection_key is None or self.busy:
            return
        if not self._save_pending(all_items=True):
            return
        origin, identity = self.selection_key
        if self.preview and self.preview.data["origin"] in {
            "archived_resume",
            "archived_note_resume",
        }:
            origin = self.preview.data["origin"]
        chooser = SavedDraftDialog(self.service, origin, identity, self.words, self)
        if chooser.exec() != QDialog.DialogCode.Accepted or chooser.identity is None:
            return
        self.generation += 1
        self.preview = None
        self.corrupt_text = None
        self._buttons()

        def load():
            saved = self.service.load_draft(origin, identity, draft_id=chooser.identity)
            if saved is None:
                raise ValueError("Selected draft is no longer available")
            return saved.get("preview"), saved

        self._submit("preview", load, self._loaded)

    def _copy(self):
        if self.corrupt_text is not None:
            QApplication.clipboard().setText(self.corrupt_text)
            self.status.setText(self.words["copied"])
            return
        if self.preview:
            try:
                QApplication.clipboard().setText(
                    self.service.export_text(self.preview, body=self._body())
                )
                self.status.setText(self.words["copied"])
            except (ValueError, OSError) as error:
                self.status.setText(str(error))

    def _export(self):
        if not self.preview and self.corrupt_text is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self.words["export"], "review.txt", "Text (*.txt)"
        )
        if not path:
            return
        try:
            if self.corrupt_text is not None:
                from pathlib import Path

                with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(self.corrupt_text)
            else:
                self.service.export(self.preview, path, body=self._body())
            self.status.setText(self.words["exported"])
        except (ValueError, OSError) as error:
            self.status.setText(str(error))

    def done(self, result):
        if self.disposed:
            return
        if self.claim_editor is not None and not self.claim_editor.disposed:
            self._claim_closing_result = result
            self.claim_editor.done(result)
            if not self.claim_editor.disposed:
                return
        if not self.disposed and not self.originals.request_close(result):
            return
        if not self.disposed:
            self._remember()
            self.autosave.stop()
            if not self._save_pending(all_items=True):
                return
            self.disposed = True
            self.generation += 1
            self.poll.stop()
            self.service.close()
            self.executor.shutdown(wait=False, cancel_futures=True)
        super().done(result)
        self.deleteLater()

    def close(self):
        return True if self.disposed else super().close()

    def isVisible(self):
        # Hosts may retain the Python handle after native retirement.
        return False if self.disposed else super().isVisible()

    def deleteLater(self):
        # Close and host cleanup may both retire the same owned window.
        if isValid(self):
            super().deleteLater()

    def reject(self):
        self.done(QDialog.DialogCode.Rejected)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "split"):
            self.split.setOrientation(
                Qt.Orientation.Vertical if self.width() < 720 else Qt.Orientation.Horizontal
            )


class TargetDialog(QDialog):
    """Explicit bounded target selection; entering this dialog never applies work."""

    def __init__(self, service, preview, words, parent=None):
        super().__init__(parent)
        self.setWindowTitle(words["target"])
        self.resize(560, 420)
        self.service, self.preview = service, preview
        self.identity = None
        self.cursor = ""
        self.list = QListWidget()
        self.more = QPushButton(words["more"])
        self.select = QPushButton(words["target"])
        self.cancel = QPushButton(words["close"])
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.select.setEnabled(False)
        self.list.currentItemChanged.connect(
            lambda item, _old: self.select.setEnabled(item is not None)
        )
        self.more.clicked.connect(self.load)
        self.select.clicked.connect(self.choose)
        self.cancel.clicked.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        for button in (self.more, self.select, self.cancel):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.load()

    def load(self):
        try:
            page = self.service.targets(self.preview, after=self.cursor)
            for target in page["items"]:
                item = QListWidgetItem(target["title"] + "\n" + target["id"])
                item.setData(Qt.ItemDataRole.UserRole, target["id"])
                self.list.addItem(item)
            self.cursor = page["next"]
            self.more.setEnabled(self.cursor is not None)
            if self.list.currentRow() < 0 and self.list.count():
                self.list.setCurrentRow(0)
        except (ValueError, OSError) as error:
            self.status.setText(str(error))

    def choose(self):
        item = self.list.currentItem()
        if item is not None:
            self.identity = item.data(Qt.ItemDataRole.UserRole)
            self.accept()


class SavedDraftDialog(QDialog):
    """Choose a durable variant without overwriting or rebasing another draft."""

    def __init__(self, service, origin, identity, words, parent=None):
        super().__init__(parent)
        self.service, self.origin, self.target = service, origin, identity
        self.identity = None
        self.cursor = None
        self.setWindowTitle(words["drafts"])
        self.resize(560, 420)
        self.list = QListWidget()
        self.more = QPushButton(words["more"])
        self.open_button = QPushButton(words["open"])
        self.close_button = QPushButton(words["close"])
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.open_button.setEnabled(False)
        self.list.currentItemChanged.connect(
            lambda item, _old: self.open_button.setEnabled(item is not None)
        )
        self.more.clicked.connect(self.load)
        self.open_button.clicked.connect(self.choose)
        self.close_button.clicked.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        for button in (self.more, self.open_button, self.close_button):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.load()

    def load(self):
        try:
            page = self.service.list_drafts(self.origin, self.target, before=self.cursor)
            for row in page["items"]:
                label = f"{row['updated_at']} · v{row['revision']}\n" + " ".join(
                    row["excerpt"].split()
                )
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, row["draft_id"])
                self.list.addItem(item)
            self.cursor = page["next"]
            self.more.setEnabled(self.cursor is not None)
            if self.list.currentRow() < 0 and self.list.count():
                self.list.setCurrentRow(0)
        except Exception as error:
            self.status.setText(str(error))

    def choose(self):
        item = self.list.currentItem()
        if item is not None:
            self.identity = item.data(Qt.ItemDataRole.UserRole)
            self.accept()
