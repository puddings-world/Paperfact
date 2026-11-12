"""Field-based manual claim review over the shared, source-verified operations."""

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)
from shiboken6 import isValid

from paper_daily.desktop.retained_original_ui import RetainedOriginalControl
from paper_daily.research_review import ResearchReview, encode

LABELS = {
    "title": ("Revise research claims", "修訂研究主張"),
    "claims": ("Claims", "研究主張"),
    "assertion": ("Assertion", "主張"),
    "judgment": ("Proposed judgment", "初步判斷"),
    "reason": ("Evidence and limitations", "證據與限制"),
    "quote": ("Original quotation", "原文引句"),
    "passages": ("Passages", "引用段落"),
    "page": ("Page hint", "頁碼提示"),
    "auto_page": ("Find across the original", "在整份原文中尋找"),
    "unresolved": ("Needs appraisal", "待評讀"),
    "inferred": ("Inferred", "推論"),
    "supported": ("Proposed as supported", "初步認為有支持"),
    "auto_location": (
        "Location will be rebuilt from the original quotation.",
        "將依原文引句重新定位。",
    ),
    "saved_location": (
        "Previous position: page {page}. Verification checks it again.",
        "原先位置：第{page}頁；核對時會重新檢查。",
    ),
    "clear_location": ("Find quotation again", "重新尋找引句位置"),
    "citation": ("Optional external reference", "另有引用文獻（選填）"),
    "citation_title": ("Reference title", "引用文獻名稱"),
    "add_claim": ("Add claim", "新增主張"),
    "add_passage": ("Add passage", "新增引句"),
    "remove": ("Remove selected", "移除所選項目"),
    "target": ("Select a target paper…", "選擇套用的論文…"),
    "choose": ("Review this target", "審閱此對象"),
    "more": ("More papers", "更多論文"),
    "save": ("Save draft", "儲存草稿"),
    "separate": ("Save separate draft", "另存一份草稿"),
    "load": ("Open draft", "開啟草稿"),
    "drafts": ("Saved drafts", "已存草稿"),
    "edit": ("Your revision", "這次修訂"),
    "current": ("Target at last review", "上次審閱的目標版本"),
    "original": ("Original baseline", "原始分析"),
    "verification": ("Quotation check", "引句核對"),
    "verify_draft": ("Verify original", "核對原文"),
    "verify_slides": ("Verify original", "核對原文"),
    "apply": ("Confirm and apply…", "確認套用…"),
    "cancel": ("Cancel check", "取消核對"),
    "cancelled": ("Work cancelled; your private draft is retained.", "已取消工作；私人草稿保留。"),
    "close": ("Close", "關閉"),
    "copy": ("Copy revision", "複製修訂內容"),
    "restore": ("Restore the deleted claim set", "恢復已刪除的主張組"),
    "absent": ("Absent", "尚無內容"),
    "more_drafts": ("More saved drafts…", "更多已存草稿…"),
    "current_draft": ("Current draft", "目前草稿"),
    "draft_verification_required": (
        "Draft reopened; verify its original before applying.",
        "已重開草稿，套用前請重新核對原文。",
    ),
    "draft_stale": (
        "Research changed; your old comparison is preserved. Review the target again.",
        "研究已更新；草稿保留舊的比較基準，請重新審閱對象。",
    ),
    "draft_decided": (
        "This draft has already been applied. Its words remain available.",
        "這份草稿已套用，原有文字仍保留。",
    ),
    "review_required": (
        "Use Review this target before checking or applying again. Private edits are retained.",
        "請先按「審閱此對象」，再核對或套用；私人編輯仍保留。",
    ),
    "closed_conflict": (
        "This conflict has been resolved. Keep or copy your private draft; do not apply it again.",
        "此衝突已解決。私稿仍可保留或複製，不能再次套用這筆衝突。",
    ),
    "pending_conflict": (
        "Resolution saved locally. Sync to confirm closure; your private draft is retained.",
        "解決決定已儲存於本機，請同步以確認衝突結束；私稿仍保留。",
    ),
    "draft_foreign": (
        "Workspace identity changed; preserve your words and explicitly choose a target.",
        "工作區身分已變；文字仍保留，請明確重新選擇對象。",
    ),
    "loc_located": ("Found", "已定位"),
    "loc_missing": ("Not found", "未找到"),
    "loc_unverified": ("Not checked", "尚未核對"),
    "citation_unresolved": ("Reference identity unverified", "引用身分尚未核實"),
    "loc_ambiguous": ("Multiple matches", "有多處相同引句"),
    "loading": ("Loading saved research…", "正在載入研究內容…"),
    "saving": ("Saving this private draft…", "正在儲存這份私稿…"),
    "checking": ("Checking quotations against the retained original…", "正在對保留原文核對引句…"),
    "applying": ("Saving the confirmed revision…", "正在儲存已確認的修訂…"),
    "dirty": ("Edits waiting to be saved locally", "編輯等待儲存於本機"),
    "saved": (
        "Draft saved locally; formal research is unchanged.",
        "草稿已儲存於本機，正式研究尚未變更。",
    ),
    "applied": (
        "Revision saved. Review the target again before another application.",
        "修訂已儲存；再次套用前請重新審閱對象。",
    ),
    "closing": ("Finishing admitted work before closing…", "完成已開始的工作後關閉…"),
    "failed": ("Not saved; your text remains here: ", "尚未儲存，文字仍保留在此："),
    "not_semantic": (
        "Locating words does not establish scholarly support.",
        "找到引句位置不代表已確認學術支持。",
    ),
    "confirm": ("Apply this revision to the displayed paper?", "確定將這份修訂套用至顯示的論文？"),
    "source": ("Original A", "引用的原文A"),
    "primary": ("PDF at review", "審閱時選用PDF"),
}


class StructuredDraftDialog(QDialog):
    """Shared private-save/worker/window lifetime; typed modes own content operations."""

    def __init__(self, database, origin, identity, parent=None, *, language="en", mode, labels):
        super().__init__(parent)
        self.mode = mode
        self.words = {key: pair[language == "zh-TW"] for key, pair in labels.items()}
        self.language, self.database = language, database
        self.setWindowTitle(self.words["title"])
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(980, 780)
        self.service, self.preview, self.root_preview = None, None, None
        self.generation, self.disposed, self.busy = 0, False, False
        self.jobs, self.active, self.kind = [], None, None
        self.cancelled = threading.Event()
        self.closing, self.dirty, self.verified, self.applied = None, False, False, False
        self.needs_review, self.conflict_closed, self.remote_decided = False, False, False
        self.persisted, self.request, self.cursor = None, str(uuid4()), None
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="paperfact-" + self.mode.domain
        )
        self.targets, self.variants = QComboBox(), QComboBox()
        self.variant_cursor = None
        self.targets.setMinimumContentsLength(20)
        self.targets.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.targets.setMaxVisibleItems(12)
        self.targets.view().setTextElideMode(Qt.TextElideMode.ElideRight)
        self.variants.currentIndexChanged.connect(self._buttons)
        self.targets.setAccessibleName(self.words["target"])
        self.variants.setAccessibleName(self.words["drafts"])
        self.targets.currentIndexChanged.connect(self._buttons)
        self.choose, self.more = QPushButton(self.words["choose"]), QPushButton(self.words["more"])
        self.choose.clicked.connect(self._choose_target)
        self.more.clicked.connect(self._more_targets)
        target_row = QHBoxLayout()
        target_row.addWidget(self.targets, 1)
        target_row.addWidget(self.choose)
        target_row.addWidget(self.more)
        self.fields = self.mode.fields(self.words)
        self.fields.changed.connect(self._edited)
        self.current, self.original, self.verification = (
            QPlainTextEdit(),
            QPlainTextEdit(),
            QPlainTextEdit(),
        )
        self.tabs = QTabWidget()
        self.tabs.addTab(self.fields, self.words["edit"])
        for editor, key in (
            (self.current, "current"),
            (self.original, "original"),
            (self.verification, "verification"),
        ):
            editor.setReadOnly(True)
            editor.setAccessibleName(self.words[key])
            self.tabs.addTab(editor, self.words[key])
        self.source, self.status, self.review_hint = QLabel(), QLabel(), QLabel()
        for label in (self.source, self.status, self.review_hint):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.restore = QCheckBox(self.words["restore"])
        self.restore.toggled.connect(
            self._invalidate if self.mode.restore_invalidates else self._buttons
        )
        self.originals = RetainedOriginalControl(self, language, **self.mode.reader_options)
        self.save, self.verify, self.apply = [
            QPushButton(self.words[key]) for key in ("save", "verify_draft", "apply")
        ]
        self.cancel, self.close_button = (
            QPushButton(self.words["cancel"]),
            QPushButton(self.words["close"]),
        )
        self.copy, self.separate, self.load = [
            QPushButton(self.words[key]) for key in ("copy", "separate", "load")
        ]
        for button in (
            self.choose,
            self.more,
            self.save,
            self.verify,
            self.apply,
            self.cancel,
            self.close_button,
            self.copy,
            self.separate,
            self.load,
        ):
            button.setAutoDefault(False)
        self.save.clicked.connect(self._save)
        self.verify.clicked.connect(self._verify)
        self.apply.clicked.connect(self._apply)
        self.cancel.clicked.connect(self._cancel_work)
        self.close_button.clicked.connect(self.reject)
        self.copy.clicked.connect(self._copy)
        self.separate.clicked.connect(self._separate)
        self.load.clicked.connect(self._load_variant)
        variants = QHBoxLayout()
        variants.addWidget(self.variants, 1)
        variants.addWidget(self.load)
        variants.addWidget(self.separate)
        actions = QGridLayout()
        for index, button in enumerate(
            (self.save, self.verify, self.apply, self.copy, self.cancel, self.close_button)
        ):
            actions.addWidget(button, index // 3, index % 3)
        layout = QVBoxLayout(self)
        layout.addLayout(target_row)
        layout.addWidget(self.review_hint)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.source)
        layout.addWidget(self.restore)
        layout.addWidget(self.originals.widget)
        layout.addLayout(variants)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName(self.words["checking"])
        layout.addWidget(self.progress)
        layout.addLayout(actions)
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(600)
        self.autosave.timeout.connect(self._save)
        self.poll = QTimer(self)
        self.poll.setInterval(25)
        self.poll.timeout.connect(self._poll)
        self.poll.start()
        QShortcut(QKeySequence.StandardKey.Save, self, activated=self._save)
        self.status.setText(self.words["loading"])
        self._run("load", lambda: self._initial(origin, identity), self._loaded)

    def _initial(self, origin, identity):
        service = ResearchReview(self.database)
        try:
            preview = service.preview(origin, identity)
            reference = identity if origin == "archived_draft" else origin + ":" + identity
            saved = self.mode.load(service, reference)
            page = self.mode.targets(service, preview, limit=100)
            return service, preview, saved, page
        except BaseException:
            service.close()
            raise

    def _original_activity(self, active):
        self.progress.setVisible(self.busy or active)
        self._cancel_controls()

    def _cancel_controls(self):
        running = (
            self.busy
            and (
                self.kind == "verify"
                or (self.kind == "apply" and self.mode.domain == "highlight_resume")
            )
            and not self.cancelled.is_set()
        )
        opening = self.originals.opening and not self.originals.cancelled.is_set()
        self.cancel.setEnabled((running or opening) and self.closing is None)

    def _cancel_work(self):
        self.cancelled.set()
        self.originals.cancelled.set()
        self.status.setText(self.words["cancelled"])
        self._cancel_controls()

    def _submit(self, kind, call, callback, on_error=None):
        future = self.executor.submit(call)
        self.jobs.append((future, self.generation, kind, callback, on_error))
        return future

    def _run(self, kind, call, callback):
        if self.busy or self.disposed:
            return
        self.busy, self.kind = True, kind
        self.cancelled = threading.Event()
        self.active = self._submit(kind, call, callback)
        self._buttons()

    def _poll(self):
        for job in self.jobs[:]:
            future, generation, kind, callback, on_error = job
            if not future.done():
                continue
            self.jobs.remove(job)
            if future is self.active:
                self.busy, self.active, self.kind = False, None, None
            if self.disposed or (kind == "original" and generation != self.generation):
                continue
            try:
                result = future.result()
                if self.closing is None or kind in {"load", "save", "apply"}:
                    callback(result)
            except Exception as error:
                if on_error is not None:
                    on_error(error)
                cancelled = kind in {"verify", "apply"} and self.cancelled.is_set()
                self.status.setText(
                    self.words["cancelled"] if cancelled else self.words["failed"] + str(error)
                )
                if kind == "save":
                    self.closing = None
                if kind == "verify":
                    self._invalidate()
            self._buttons()
        if self.closing is not None and not self.busy:
            self.done(self.closing)

    def _loaded(self, result):
        self.service, self.root_preview, saved, page = result
        root = self.root_preview.data
        self.conflict_closed = (
            root["origin"] == "remote"
            and (root.get("expected") or {}).get("resolved_by") is not None
        )
        self.targets.addItem(self.words["target"], None)
        self._target_page(page)
        if saved and saved["state"] != "corrupt":
            self._show(saved["preview"], saved["body"], saved)
        elif saved:
            self.status.setText(saved["reason"])
        else:
            self.status.setText(self.words["target"])

    def _target_page(self, page):
        for item in page["items"]:
            self.targets.addItem(item["title"], item["id"])
            self.targets.setItemData(
                self.targets.count() - 1, item["title"], Qt.ItemDataRole.ToolTipRole
            )
        self.cursor = page["next"]

    def _more_targets(self):
        if self.busy or not self.cursor:
            return
        cursor = self.cursor
        self._run(
            "targets",
            lambda: self.mode.targets(self.service, self.root_preview, after=cursor, limit=100),
            self._target_page,
        )

    def _body(self):
        return encode(self.fields.draft())

    def _choose_target(self):
        if self.busy or self.targets.currentData() is None:
            return
        if self.dirty:
            self._save(after=self._choose_target)
            return
        target, preview = self.targets.currentData(), self.preview or self.root_preview
        body = self._body() if self.fields.value is not None else None
        self._invalidate()
        self.status.setText(self.words["loading"])
        self._run(
            "select",
            lambda: self.mode.select(self.service, preview, target, body=body),
            lambda result: self._show(*result),
        )

    def _show(self, preview, body, saved=None):
        self.preview = preview
        self.needs_review = bool(saved and saved["state"] in {"stale", "decided", "foreign"})
        self.remote_decided = bool(
            saved and saved["state"] == "decided" and self.mode.remote(preview.data)
        )
        self.fields.set_draft(self.mode.parse(preview.data, body))
        self.current.setPlainText(self.mode.readable(preview.data["current"], self.words))
        self.original.setPlainText(self.mode.readable(preview.data["retained"], self.words))
        self.request = saved["request_id"] if saved else str(uuid4())
        self.persisted = (
            {key: saved[key] for key in ("draft_id", "revision")}
            if saved
            else {"draft_id": str(uuid4())}
        )
        self.verified, self.applied, self.dirty = False, False, saved is None
        self.restore.setChecked(False)
        self.restore.setVisible(self.mode.restoration(preview.data, self.fields.draft()))
        target = preview.data["expected"]["paper_id"]
        self.targets.setCurrentIndex(self.targets.findData(target))
        document = preview.data["expected"]["document"]
        source = preview.data["source_hash"]
        primary = document["sha256"] if document else "—"
        self.source.setText(
            preview.data["target"]["title"]
            + "\n"
            + self.words["source"]
            + ": "
            + source[:12]
            + " · "
            + self.words["primary"]
            + ": "
            + primary[:12]
        )
        self.source.setToolTip(source + "\n" + primary)
        self.originals.display(preview.data)
        self.status.setText(
            self.words.get("draft_" + saved["state"], saved["reason"])
            if saved
            else self.words["dirty"]
        )
        self._variants()
        self._buttons()

    def _invalidate(self, *_args):
        self.verified, self.applied = False, False
        self.generation += 1
        self.originals.invalidate()
        if self.preview is not None:
            self.preview = self.service.require_draft_verification(self.preview)
            self.originals.display(self.preview.data)
        self._buttons()

    def _edited(self):
        if (
            self.preview is None
            or self.closing is not None
            or (self.busy and self.kind not in {"save", "variants"})
        ):
            return
        self._invalidate()
        self.dirty, self.request = True, str(uuid4())
        self.status.setText(self.words["dirty"])
        self.autosave.start()
        self._buttons()

    def _save_pending(self, *, all_items=False):
        if self.busy:
            return False
        if self.dirty:
            self._save()
            return False
        return True

    def _save(self, checked=False, *, after=None):
        if self.disposed or self.preview is None:
            return
        if self.busy:
            if self.dirty and self.closing is None:
                self.autosave.start()
            return
        self.autosave.stop()
        if not self.dirty:
            if after is not None:
                after()
            return
        preview, body, request, persisted = (
            self.preview,
            self._body(),
            self.request,
            dict(self.persisted),
        )
        self.status.setText(self.words["saving"])

        def saved(result):
            self.persisted = result
            self.dirty = self._body() != body or self.request != request
            self.status.setText(self.words["dirty" if self.dirty else "saved"])
            if self.dirty and self.closing is None:
                self.autosave.start()
            if after is not None and self.closing is None:
                after()
            else:
                self._variants()

        self._run(
            "save",
            lambda: self.mode.save(self.service, preview, body, request, **persisted),
            saved,
        )

    def _separate(self):
        if self.busy or self.preview is None:
            return
        if self.dirty:
            self._save(after=self._separate)
            return
        self.persisted, self.dirty = {"draft_id": str(uuid4())}, True
        self._save()

    def _variants(self):
        if self.busy or self.preview is None or self.closing is not None:
            return
        identity = self.preview.data["id"]

        self._run(
            "variants",
            lambda: self.service.list_drafts(self.mode.domain, identity, limit=50),
            lambda page: self._variant_page(page, reset=True),
        )

    def _variant_page(self, page, *, reset=False):
        if reset:
            self.variants.clear()
        sentinel = self.variants.findData("__page__")
        if sentinel >= 0:
            self.variants.removeItem(sentinel)
        for item in page["items"]:
            if self.variants.findData(item["draft_id"]) < 0:
                self.variants.addItem(
                    item["updated_at"][:19] + " · " + str(item["revision"]), item["draft_id"]
                )
        self.variant_cursor = page["next"]
        if reset and self.persisted and self.persisted.get("revision") is not None:
            current = self.persisted["draft_id"]
            if self.variants.findData(current) < 0:
                self.variants.addItem(self.words["current_draft"], current)
            self.variants.setCurrentIndex(self.variants.findData(current))
        if self.variant_cursor is not None:
            self.variants.addItem(self.words["more_drafts"], "__page__")

    def _load_variant(self):
        if self.busy or self.preview is None or self.variants.currentData() is None:
            return
        if self.variants.currentData() == "__page__":
            identity, cursor = self.preview.data["id"], self.variant_cursor
            if cursor is not None:
                self._run(
                    "variants",
                    lambda: self.service.list_drafts(
                        self.mode.domain, identity, before=cursor, limit=50
                    ),
                    self._variant_page,
                )
            return
        if self.dirty:
            self._save(after=self._load_variant)
            return
        identity, draft = self.preview.data["id"], self.variants.currentData()
        self._invalidate()
        self._run(
            "variant",
            lambda: self.mode.load(self.service, identity, draft_id=draft),
            lambda saved: self._show(saved["preview"], saved["body"], saved),
        )

    def _verify(self):
        if (
            self.busy
            or self.preview is None
            or self.needs_review
            or self.conflict_closed
            or self.remote_decided
        ):
            return
        if self.dirty:
            self._save(after=self._verify)
            return
        self._invalidate()
        preview, body, restoring = self.preview, self._body(), self.restore.isChecked()
        self.status.setText(self.words["checking"])
        cancelled = threading.Event()

        def check():
            return self.mode.verify(self.service, preview, body, restoring, cancelled.is_set)

        def checked(result):
            if cancelled.is_set():
                self._invalidate()
                return
            self.preview, report = result
            self.verified = self.mode.checked(self.fields, report)
            self.restore.setVisible(
                self.mode.restoration(self.preview.data, self.fields.draft(), report)
            )
            self.verification.setPlainText(
                self.mode.readable(report, self.words) + "\n" + self.words["not_semantic"]
            )
            self.originals.display(self.preview.data)
            self.status.setText(self.words["not_semantic" if self.verified else "not_located"])
            self._variants()

        self._run("verify", check, checked)
        self.cancelled = cancelled

    def _apply(self):
        if (
            self.busy
            or not self.verified
            or self.preview is None
            or self.needs_review
            or self.conflict_closed
            or self.remote_decided
            or not self.mode.allow_apply(self)
        ):
            return
        message = (
            self.words["confirm"]
            + "\n\n"
            + self.source.text()
            + "\n\n"
            + self.mode.summary(self.fields)
        )
        if (
            QMessageBox.question(
                self,
                self.words["title"],
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        preview, body, request = self.preview, self._body(), self.request
        persisted, restoring = dict(self.persisted), self.restore.isChecked()
        cancelled = threading.Event()
        self.status.setText(self.words["applying"])

        def applied(result):
            self.persisted = self.mode.after_apply(result, self.persisted)
            self.verified, self.applied, self.needs_review = False, True, True
            self.remote_decided = self.mode.remote(preview.data)
            self.status.setText(self.words["applied"])

        self._run(
            "apply",
            lambda: self.mode.apply(
                self.service, preview, body, request, persisted, restoring, cancelled.is_set
            ),
            applied,
        )
        self.cancelled = cancelled

    def _copy(self):
        if self.fields.value is not None:
            QApplication.clipboard().setText(self.mode.copy(self.fields))

    def _buttons(self, *_args):
        ready = not self.disposed and not self.busy and self.closing is None
        loaded = self.preview is not None
        self.targets.setEnabled(ready)
        self.choose.setEnabled(
            ready
            and self.targets.currentData() is not None
            and self.root_preview is not None
            and not self.conflict_closed
            and not self.remote_decided
        )
        self.more.setEnabled(ready and self.cursor is not None)
        can_type = (
            not self.disposed
            and self.closing is None
            and loaded
            and (not self.busy or self.kind in {"save", "variants"})
        )
        self.fields.setEnabled(can_type)
        self.progress.setVisible(self.busy)
        self.restore.setEnabled(ready and loaded)
        self.save.setEnabled(ready and loaded and self.dirty)
        needs_review = self.needs_review or self.conflict_closed or self.remote_decided
        hint = (
            self.words["closed_conflict"]
            if self.conflict_closed
            else self.words["pending_conflict"]
            if self.remote_decided
            else self.words["review_required"]
            if needs_review
            else ""
        )
        self.review_hint.setText(hint)
        self.review_hint.setVisible(bool(hint))
        self.verify.setToolTip(hint)
        self.verify.setEnabled(ready and loaded and not needs_review)
        self.apply.setEnabled(
            ready
            and loaded
            and self.verified
            and not self.dirty
            and not needs_review
            and self.mode.allow_apply(self)
        )
        self._cancel_controls()
        self.separate.setEnabled(ready and loaded)
        self.variants.setEnabled(ready and loaded)
        self.load.setEnabled(ready and self.variants.count() > 0)
        self.load.setText(
            self.words["more_drafts"]
            if self.variants.currentData() == "__page__"
            else self.words["load"]
        )
        self.copy.setEnabled(self.fields.value is not None)
        self.originals.controls()
        if self.closing is not None:
            self.originals.button.setEnabled(False)

    def done(self, result):
        if self.disposed:
            return
        self.closing = result
        self.autosave.stop()
        self.cancelled.set()
        self.originals.cancelled.set()
        if self.busy:
            self.status.setText(self.words["closing"])
            self._buttons()
            return
        if not self.originals.request_close(result):
            return
        if self.dirty:
            self._save()
            return
        if self.jobs:
            return
        self.disposed = True
        self.poll.stop()
        if self.service is not None:
            self.service.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        super().done(result)
        # Retire native widgets on their GUI event loop after owned work drains.
        # Do not leave QObject ownership to a later arbitrary Python collector.
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
        if hasattr(self, "targets"):
            self.targets.view().setMaximumWidth(max(240, self.width() - 48))


class ClaimDraftDialog(StructuredDraftDialog):
    """Compatibility entry for the unchanged typed claim operations."""

    def __init__(self, database, origin, identity, parent=None, *, language="en"):
        from paper_daily.desktop.structured_review_modes import ClaimMode

        super().__init__(
            database, origin, identity, parent, language=language, mode=ClaimMode(), labels=LABELS
        )
