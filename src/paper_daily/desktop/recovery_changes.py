"""Progressive old-device change review and explicit native note-copy action."""

from contextlib import closing
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from paper_daily import research_generation as generation
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_note_copy as note_copy
from paper_daily import sync_recovery_target as target
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.workspace_service import Cancelled, SnapshotChanged

TEXT = {
    "en": {
        "choose": "Review changes in a restored workspace…",
        "refresh": "Refresh review",
        "compare": "Compare selected change",
        "copy": "Copy as new note",
        "already": (
            "This recorded change was already copied. Later edits or deletion of that copy "
            "remain unchanged; inspect it in the restored workspace."
        ),
        "retry": "Retry this copy",
        "next": "Next changes",
        "previous": "Previous changes",
        "old": "Old device's recorded content",
        "new": "Restored workspace's current content",
        "initial": (
            "Choose a service backup above, then choose a separately joined restored workspace."
        ),
        "pick": "Choose the restored workspace folder containing papers.db",
        "loaded": (
            "{count} recorded changes outside this backup. Select one to "
            "compare. This is not a full research/file audit."
        ),
        "empty": (
            "No recorded changes outside this backup. Unsaved drafts, "
            "uncaptured work and files are not certified."
        ),
        "unsupported": (
            "This change remains pending. Notes tied to PDF locations need original "
            "verification. Other content or older formats need a separate recovery action."
        ),
        "ready": (
            "Compare both versions, then copy as a distinct note. Existing "
            "notes stay unchanged. This makes no AI call. If destination sync is enabled, "
            "the new note can synchronize."
        ),
        "saved": (
            "Saved a new note in the selected restored workspace. Refresh the"
            " review before another action. Remote acceptance has not been "
            "checked."
        ),
        "saved_changed": (
            "The copy was saved in the selected workspace, but the review "
            "changed. Reopen the review to inspect it."
        ),
        "failed": (
            "Could not finish this step. Existing research is preserved. "
            "Retry the same copy, or refresh after changes."
        ),
        "stale": "The review changed. Refresh before comparing or copying.",
        "stopped": "Stopped. Refresh the review when ready; no workspace was switched.",
        "retired": "Deleted in this workspace",
        "absent": "Not present in this workspace",
        "index": "Checking old device and backup…",
        "target": "Checking restored workspace history…",
        "comparison": "Comparing the selected change…",
        "write": "Saving one new note…",
    },
    "zh-TW": {
        "choose": "到還原工作區審閱變更…",
        "refresh": "重新檢查",
        "compare": "比對選定變更",
        "copy": "另存為新筆記",
        "already": "這筆變更已另存過。副本後續的編輯或刪除保留；請到還原工作區檢視。",
        "retry": "重試這次另存",
        "next": "下一批變更",
        "previous": "上一批變更",
        "old": "舊裝置記錄的內容",
        "new": "還原工作區目前內容",
        "initial": ("先在上方選擇服務備份，再選擇已獨立加入同步的還原工作區。"),
        "pick": "選擇含 papers.db 的還原工作區資料夾",
        "loaded": ("有 {count} 筆不在備份中的變更。選擇一筆比對；這不代表完整研究與附件稽核。"),
        "empty": ("未找到備份以外的已記錄變更；未儲存草稿、未捕捉操作與檔案仍未完整核對。"),
        "unsupported": (
            "這筆變更仍保留待處理。目前可另存未綁原文位置的筆記；其他類型與原文核對需使用各自的復原操作。"
        ),
        "ready": (
            "比對後可另存新筆記，既有內容保留。不呼叫 AI；目標工作區啟用同步時，新筆記會排入同步。"
        ),
        "saved": ("已另存到選定的還原工作區。請重新檢查再處理其他變更；尚未查詢遠端接收狀態。"),
        "saved_changed": ("新筆記已存入選定工作區，但檢查內容已改變；請重新開啟審閱。"),
        "failed": ("這一步未完成，既有研究保留。可重試同一次另存；資料改變時請重新檢查。"),
        "stale": "審閱內容已改變，請重新檢查後再比對或另存。",
        "stopped": "已停止；可稍後重新檢查，工作區未切換。",
        "retired": "此工作區已刪除",
        "absent": "此工作區尚無此內容",
        "index": "核對舊裝置與服務備份…",
        "target": "核對還原工作區歷史…",
        "comparison": "比對選定變更…",
        "write": "儲存一份新筆記…",
    },
}


class RecoveryChanges(QWidget):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.t = TEXT["zh-TW" if self.owner.zh else "en"]
        self.snapshot = self.destination = self.observed = self.page = self.plan = None
        self.failed_copy = False
        self.offset = 0
        self.previous_button = QPushButton(self.t["previous"])
        self.choose_button = QPushButton(self.t["choose"])
        self.refresh_button = QPushButton(self.t["refresh"])
        self.next_button = QPushButton(self.t["next"])
        self.compare_button = QPushButton(self.t["compare"])
        self.copy_button = QPushButton(self.t["copy"])
        self.copy_button.setProperty("role", "primary")
        for button in self.buttons:
            button.setAutoDefault(False)
        self.choose_button.clicked.connect(self.choose)
        self.refresh_button.clicked.connect(self.reload)
        self.next_button.clicked.connect(self.next_page)
        self.previous_button.clicked.connect(self.previous_page)
        self.compare_button.clicked.connect(self.compare)
        self.copy_button.clicked.connect(self.copy)
        self.location, self.notice = QLabel(), QLabel(self.t["initial"])
        for label in (self.location, self.notice):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.rows = QListWidget()
        self.rows.setAccessibleName("Recovery changes" if not self.owner.zh else "待復原變更")
        self.rows.currentRowChanged.connect(self.selection_changed)
        self.rows.itemActivated.connect(lambda _item: self.compare())
        self.old, self.current = QPlainTextEdit(), QPlainTextEdit()
        previews = QSplitter(Qt.Orientation.Horizontal)
        for field, caption in ((self.old, self.t["old"]), (self.current, self.t["new"])):
            field.setReadOnly(True)
            field.setAccessibleName(caption)
            group = QWidget()
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.addWidget(QLabel(caption))
            group_layout.addWidget(field)
            previews.addWidget(group)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.rows)
        self.splitter.addWidget(previews)
        self.splitter.setSizes([140, 240])
        self.splitter.setMinimumHeight(260)
        top, actions = QHBoxLayout(), QHBoxLayout()
        top.addWidget(self.choose_button)
        top.addWidget(self.refresh_button)
        actions.addWidget(self.previous_button)
        actions.addWidget(self.next_button)
        actions.addStretch()
        actions.addWidget(self.compare_button)
        actions.addWidget(self.copy_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self.location)
        layout.addWidget(self.notice)
        layout.addWidget(self.splitter)
        layout.addLayout(actions)
        self.splitter.hide()
        self.controls(False)

    @property
    def owner(self):
        return self.panel.owner

    @property
    def buttons(self):
        return (
            self.choose_button,
            self.refresh_button,
            self.next_button,
            self.previous_button,
            self.compare_button,
            self.copy_button,
        )

    def reset_source(self, selected):
        self.snapshot = selected
        self.offset = 0
        self.destination = self.observed = self.page = self.plan = None
        self.rows.clear()
        self.location.clear()
        self.splitter.hide()
        self.notice.setText(self.t["initial"])

    def controls(self, active):
        active = bool(active and self.snapshot and self.owner._adoption_context_current())
        self.choose_button.setEnabled(active)
        self.refresh_button.setEnabled(bool(active and self.destination))
        self.next_button.setEnabled(
            bool(active and self.page and self.observed and self.page["next_offset"] is not None)
        )
        self.previous_button.setEnabled(bool(active and self.observed and self.offset))
        self.rows.setEnabled(bool(active and self.observed))
        self.compare_button.setEnabled(bool(active and self.observed and self.selected()))
        self.copy_button.setEnabled(bool(active and self.plan))
        self.copy_button.setText(self.t["retry" if self.failed_copy else "copy"])

    def selected(self):
        item = self.rows.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def selection_changed(self, _row):
        self.plan, self.failed_copy = None, False
        self.old.clear()
        self.current.clear()
        self.controls(not self.owner.busy and not self.owner._invalid)

    def choose(self):
        if not self.choose_button.isEnabled():
            return False
        selected = QFileDialog.getExistingDirectory(self, self.t["pick"])
        return self.load(selected) if selected else False

    def reload(self):
        if not self.refresh_button.isEnabled():
            return False
        return self.load(self.destination)

    def _cancelled(self, ticket):
        service = self.owner.service
        return (
            ticket.cancelled
            or Path(service.current_path()).resolve() != service.path
            or tuple(generation._identity(service.path)) != service.identity
        )

    def _start(self, kind, work):
        def run(ticket, progress):
            ticket.check()
            self.owner.service.check()
            try:
                return work(ticket, progress)
            except backup.BackupCancelled:
                raise Cancelled() from None
            except ValueError:
                if kind in {"compare", "copy", "page"}:
                    raise SnapshotChanged() from None
                raise

        return self.owner._start("device_changes_" + kind, run)

    def load(self, folder):
        if (
            not folder
            or not self.snapshot
            or self.owner.busy
            or not self.owner._adoption_context_current()
        ):
            return False
        source, snapshot = self.owner.service.path, self.snapshot
        folder = Path(folder)
        self.observed = self.page = self.plan = None
        self.rows.clear()
        self.splitter.hide()
        self.destination = folder
        self.location.setText(str(folder))

        def run(ticket, progress):
            from paper_daily.workspace_sync import local_binding

            progress("device_changes:index")
            binding = local_binding(source)
            if binding is None:
                raise ValueError("Old device requires an existing sync journal")
            index = candidates.prepare(
                source, snapshot, binding["workspace_id"], cancelled=lambda: self._cancelled(ticket)
            )
            progress("device_changes:target")
            observed = target.observe(
                index, folder / "papers.db", cancelled=lambda: self._cancelled(ticket)
            )
            return observed, observed.source.page(cancelled=lambda: self._cancelled(ticket)), 0

        return self._start("load", run)

    def next_page(self):
        if not self.next_button.isEnabled():
            return False
        return self._page_at(self.page["next_offset"])

    def previous_page(self):
        if not self.previous_button.isEnabled():
            return False
        return self._page_at(max(0, self.offset - 20))

    def _page_at(self, offset):
        observed = self.observed
        self.plan = None

        def run(ticket, _progress):
            observed._check(lambda: ticket.check())
            page = observed.source.page(after=offset, cancelled=lambda: self._cancelled(ticket))
            return observed, page, offset

        return self._start("page", run)

    def compare(self):
        if not self.compare_button.isEnabled():
            return False
        observed, selected = self.observed, self.selected()
        self.plan, self.failed_copy = None, False

        def run(ticket, progress):
            progress("device_changes:comparison")

            def stopped():
                return self._cancelled(ticket)

            comparison = observed.compare(selected, cancelled=stopped)
            operation = comparison["source"]["operation"]
            blockers = set(comparison["blocking_reasons"]) - {
                "target_restore_requires_confirmation",
                "target_entity_lifetime_changed",
            }
            supported = (
                operation["version"] == 2
                and operation["entity_type"] == "note"
                and operation["action"] == "put"
                and operation["payload"].get("page") is None
                and operation["payload"].get("anchor") is None
                and not blockers
            )
            plan, already = None, False
            if supported:
                request_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        "paperfact:recovery-copy-ui:v1:"
                        + candidates._json(
                            [
                                observed.binding,
                                operation["workspace_id"],
                                operation["device_id"],
                                operation["operation_id"],
                                candidates._fingerprint(operation),
                            ]
                        ),
                    )
                )
                plan = note_copy.prepare(observed, selected, request_id, cancelled=stopped)
                with closing(_readonly_connection(observed.database)) as conn:
                    already = (
                        conn.execute(
                            "SELECT 1 FROM paperfact_sync_operations WHERE operation_id=?",
                            (request_id,),
                        ).fetchone()
                        is not None
                    )
            return observed, selected, comparison, plan, already

        return self._start("compare", run)

    def copy(self):
        if not self.copy_button.isEnabled():
            return False
        plan = self.plan

        def run(ticket, progress):
            progress("device_changes:write")
            receipt = plan.apply(cancelled=lambda: self._cancelled(ticket))
            # A post-commit observation failure cannot turn a successful save into
            # a false "nothing saved" error. Delivery validates this cheap fence.
            try:
                from paper_daily.workspace_sync import local_binding

                observed = plan.observed
                if local_binding(observed.database, require_capture=True) != observed.binding:
                    raise ValueError("Saved target was rebound")
                fence = (
                    tuple(generation._identity(observed.database)),
                    candidates.review._version(observed.database),
                )
            except (OSError, ValueError):
                fence = None
            return receipt, fence

        return self._start("copy", run)

    def stage(self, stage):
        key = stage.removeprefix("device_changes:")
        if key in ("index", "target", "comparison", "write"):
            self.notice.setText(self.t[key])
            self.owner.status.setText(self.t[key])

    def finish(self, worker, kind):
        owner = self.owner
        copied = kind == "device_changes_copy" and worker.result is not None and not worker.error
        current = owner._adoption_context_current() and not owner._closing
        if not current or worker.error == "changed":
            if worker.error == "changed":
                owner._invalid = True
            self.observed = self.page = self.plan = None
            self.rows.clear()
            self.splitter.hide()
            owner.status.setText(self.t["saved_changed"] if copied else self.t["stale"])
            return
        if copied:
            try:
                observed = self.plan.observed
                observed.source._check(lambda: None)
                native, versions = worker.result[1]
                stable = (
                    native == observed.identity
                    and tuple(generation._identity(observed.database)) == native
                    and candidates.review._version(observed.database) == versions
                )
            except (OSError, ValueError, TypeError, AttributeError):
                stable = False
            self.observed = self.page = self.plan = None
            self.failed_copy = False
            message = self.t["saved" if stable else "saved_changed"]
            self.notice.setText(message)
            owner.status.setText(message)
            self.old.clear()
            self.current.clear()
            return
        if worker.error == "snapshot_changed":
            self.observed = self.page = self.plan = None
            self.rows.clear()
            self.splitter.hide()
            self.notice.setText(self.t["stale"])
            owner.status.setText(self.t["stale"])
            return
        if worker.error or worker.ticket.cancelled or worker.result is None:
            self.failed_copy = kind == "device_changes_copy" and self.plan is not None
            self.notice.setText(self.t["stopped"] if worker.ticket.cancelled else self.t["failed"])
            owner.status.setText(self.notice.text())
            return
        try:
            observed = worker.result[0]
            observed._check(lambda: None)  # Bounded identities/versions, no SQL or PDF reads.
            if kind in ("device_changes_load", "device_changes_page"):
                self.observed, self.page, self.offset = worker.result
                self.rows.clear()
                for position, row in enumerate(self.page["items"], start=self.offset + 1):
                    item = QListWidgetItem(self._row_label(row, position))
                    item.setData(Qt.ItemDataRole.UserRole, row["change_id"])
                    item.setToolTip(self._row_tooltip(row))
                    self.rows.addItem(item)
                self.rows.setCurrentRow(0 if self.rows.count() else -1)
                self.splitter.setVisible(bool(self.rows.count()))
                self.notice.setText(
                    self.t["loaded"].format(count=self.page["change_count"])
                    if self.rows.count()
                    else self.t["empty"]
                )
                if self.rows.count():
                    self.rows.setFocus()
            else:
                _observed, selected, comparison, plan, already = worker.result
                if observed is not self.observed or selected != self.selected():
                    raise ValueError("Selected recovery change changed")
                source = comparison["source"]["operation"]
                effective = comparison["target"]["effective_operation"]
                self.old.setPlainText(self._content(source))
                self.current.setPlainText(self._content(effective))
                self.plan = None if already else plan
                self.notice.setText(
                    self.t["already" if already else "ready" if plan is not None else "unsupported"]
                )
                self.old.setFocus()
            owner.status.setText(self.notice.text())
        except (OSError, ValueError, TypeError):
            self.observed = self.page = self.plan = None
            self.rows.clear()
            self.splitter.hide()
            self.notice.setText(self.t["stale"])
            owner.status.setText(self.t["stale"])

    def _domain(self, kind):
        labels = {
            "note": ("Note", "筆記"),
            "list": ("List", "清單"),
            "paper": ("Paper", "論文"),
            "membership": ("List membership", "清單收錄"),
            "reading_state": ("Reading progress", "閱讀進度"),
            "paper_document": ("Paper PDF", "論文 PDF"),
            "research_content": ("Research content", "研究內容"),
            "research_file": ("Research file", "研究檔案"),
            "list_order": ("Paper order", "論文排序"),
            "workspace_list_order": ("List order", "清單排序"),
            "inbox_item": ("Research inbox", "研究收件匣"),
        }
        return labels.get(kind, ("Other change", "其他變更"))[self.owner.zh]

    def _row_label(self, row, position):
        action = (
            ("Deleted", "刪除變更") if row["action"] == "delete" else ("Saved change", "儲存變更")
        )[self.owner.zh]
        return f"{position}. {self._domain(row['entity_type'])} · {action}"

    def _row_tooltip(self, row):
        labels = {
            "unconfirmed_not_in_backup": ("Awaiting confirmation", "尚待確認"),
            "acknowledged_after_backup": ("Confirmed after backup", "備份之後已確認"),
            "received_after_backup": ("Received after backup", "備份之後已收到"),
        }
        state = labels.get(row["category"], ("Recorded change", "已記錄變更"))[self.owner.zh]
        reference = "參考識別碼" if self.owner.zh else "Reference"
        return f"{state}\n{reference}: {row['entity_id']}"

    def _content(self, operation):
        if operation is None:
            return self.t["absent"]
        if operation["action"] == "delete":
            return self.t["retired"]
        payload = operation["payload"]
        if operation["entity_type"] == "note":
            return payload["body"]
        import json

        return json.dumps(payload, ensure_ascii=False, indent=2)
