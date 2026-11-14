"""Progressive old-device change review and explicit native note-copy action."""

from contextlib import closing
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from paper_daily import research_generation as generation
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_choices as choices
from paper_daily import sync_recovery_claim_group as claim_group
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
            "This change remains pending. Copying needs verified parent mappings and, "
            "for positioned notes, the exact original PDF. Other content or older "
            "formats need a separate recovery action."
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
            "Retry the same action, or refresh after changes."
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
            "這筆變更仍保留待處理。另存筆記需要核實父項對應；綁定 "
            "PDF 位置的筆記也需核實原文。其他類型需使用各自的復原操作。"
        ),
        "ready": (
            "比對後可另存新筆記，既有內容保留。不呼叫 AI；目標工作區啟用同步時，新筆記會排入同步。"
        ),
        "saved": ("已另存到選定的還原工作區。請重新檢查再處理其他變更；尚未查詢遠端接收狀態。"),
        "saved_changed": ("新筆記已存入選定工作區，但檢查內容已改變；請重新開啟審閱。"),
        "failed": ("這一步未完成，既有研究保留。可重試同一次操作；資料改變時請重新檢查。"),
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


TEXT["en"].update({
    "claim_group": "Use old complete claim group",
    "group_blocked": "This complete group needs further review: ",
    "ready_claim_group": (
        "Review the claims and both exact analysis inputs together. Confirmation replaces "
        "this group and includes its verified PDF; manual notes and the active PDF are preserved."
    ),
    "confirm_claim_group": (
        "Use this old claim set, deep explanation and close reading together, with its exact PDF? "
        "Different/deleted group members are replaced/restored; earlier history and manual notes "
        "are retained. This does not certify the research judgments or call AI."
    ),
    "group_dive": "Deep explanation", "group_close_reading": "Close reading",
    "group_claims": "Claims", "group_judgment": "Proposed judgment",
    "copy_original": "Copy note and original",
    "ready_original": (
        "This note needs its original PDF. Copy the note and verified original together; "
        "existing notes and the active PDF stay unchanged. Destination sync can upload both."
    ),
    "confirm_original": (
        "Copy this note and its verified original PDF into the selected restored workspace? "
        "Both are queued for destination sync. Existing notes and the active PDF stay unchanged."
    ),
    "action": "Action", "review": "Compare only", "keep": "Keep current content",
    "add": "Add old content", "replace": "Use old version", "restore": "Restore old content",
    "apply": "Apply selected action", "retry_action": "Retry selected action",
    "ready_action": "This change remains pending. Select an action after comparing both versions.",
    "already_action": "This action was already recorded. Later edits remain unchanged.",
    "decision_saved": (
        "Decision saved locally. Refresh to insp"
        "ect it; remote acceptance is unchecked."
    ),
    "kept": "Kept current content. Decision recorded locally; no research operation was created.",
    "decision_changed": (
        "Decision recorded, but the review cha"
        "nged. Reopen it to inspect the result."
    ),
    "confirm_title": "Apply the reviewed version?",
    "confirm_body": "{action}? This writes a new version in the selected restored workspace. "
                    "Earlier history is retained. Check both content panes before continuing.",
})
TEXT["zh-TW"].update({
    "claim_group": "使用舊版整組主張研究",
    "group_blocked": "這整組研究仍需核對：",
    "ready_claim_group": (
        "請一起比對主張與兩份原始分析。確認後會替換這整組內容並帶入核實的 PDF；"
        "手動筆記與目前 PDF 保留。"
    ),
    "confirm_claim_group": (
        "確定一起使用舊版主張、深入分析、逐段講解與對應 PDF？"
        "差異或已刪除的組內項目將被替換或復原；舊歷史與手動筆記保留。"
        "不會呼叫 AI，也不代表已核實研究判斷。"
    ),
    "group_dive": "深入分析", "group_close_reading": "逐段講解",
    "group_claims": "主張", "group_judgment": "研究判斷（待核實）",
    "copy_original": "另存筆記與原文",
    "ready_original": (
        "這筆筆記需要原文 PDF。可一起另存筆記與核實的原文；"
        "既有筆記與目前 PDF 保持不變。目標工作區可同步兩者。"
    ),
    "confirm_original": (
        "確定將這筆筆記與核實的原文 PDF 一起另存到選定的還原工作區？"
        "兩者都會排入目標工作區同步；既有筆記與目前 PDF 保持不變。"
    ),
    "action": "處理方式", "review": "只比較",
    "keep": "保留目前內容", "add": "新增舊內容",
    "replace": "使用舊版本", "restore": "還原舊內容",
    "apply": "套用所選方式", "retry_action": "重試所選操作",
    "ready_action": "此項變更仍待處理。比較兩版內容後，再選擇處理方式。",
    "already_action": "此操作已記錄，後續編輯保持不變。",
    "decision_saved": (
        "決定已存在本機，請重新檢查"
        "結果；尚未確認遠端接受狀態。"
    ),
    "kept": "已保留目前內容並記錄決定，沒有建立研究資料變更。",
    "decision_changed": (
        "決定已記錄，但檢查內容已"
        "變動；請重新開啟查看結果。"
    ),
    "confirm_title": "確定套用比較後的版本？",
    "confirm_body": (
        "{action}？這會在所選還原工作區寫入"
        "新版本，先前歷史仍會保留。請先核對兩側內容。"
    ),
})


class RecoveryChanges(QWidget):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.t = TEXT["zh-TW" if self.owner.zh else "en"]
        self.snapshot = self.destination = self.observed = self.page = self.plan = None
        self.failed_copy = self._confirming = False
        self.action_plans = {}
        self.offset = 0
        self.previous_button = QPushButton(self.t["previous"])
        self.choose_button = QPushButton(self.t["choose"])
        self.refresh_button = QPushButton(self.t["refresh"])
        self.next_button = QPushButton(self.t["next"])
        self.compare_button = QPushButton(self.t["compare"])
        self.copy_button = QPushButton(self.t["copy"])
        self.copy_button.setProperty("role", "primary")
        self.action_select = QComboBox()
        self.action_select.setAccessibleName(self.t["action"])
        self.action_select.currentIndexChanged.connect(self.action_changed)
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
        self.action_row = QWidget()
        action_layout = QHBoxLayout(self.action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.addWidget(QLabel(self.t["action"]))
        action_layout.addWidget(self.action_select, 1)
        action_layout.addWidget(self.copy_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self.location)
        layout.addWidget(self.notice)
        layout.addWidget(self.splitter)
        layout.addLayout(actions)
        layout.addWidget(self.action_row)
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
        active = bool(
            active and not self._confirming and self.snapshot
            and self.owner._adoption_context_current()
        )
        self.choose_button.setEnabled(active)
        self.refresh_button.setEnabled(bool(active and self.destination))
        self.next_button.setEnabled(
            bool(active and self.page and self.observed and self.page["next_offset"] is not None)
        )
        self.previous_button.setEnabled(bool(active and self.observed and self.offset))
        self.rows.setEnabled(bool(active and self.observed))
        self.compare_button.setEnabled(bool(active and self.observed and self.selected()))
        self.copy_button.setEnabled(bool(active and self.observed and self.plan))
        action = self.action_select.currentData()
        key = "retry" if action == "copy" else "retry_action"
        label = "copy_original" if action == "copy" and getattr(
            self.plan, "with_original", False
        ) else action or "apply"
        self.copy_button.setText(self.t[key if self.failed_copy else label])
        self.action_select.setEnabled(bool(active and self.observed and self.action_plans))
        self.action_row.setVisible(bool(self.observed and self.action_plans))

    def selected(self):
        item = self.rows.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def action_changed(self, _index):
        action = self.action_select.currentData()
        plan, already = self.action_plans.get(action, (None, False))
        self.plan, self.failed_copy = (None if already else plan), False
        if action:
            key = ("already" if action == "copy" else "already_action") if already else (
                "ready" if action == "copy" else "ready_action"
            )
            if action == "copy" and not already and getattr(plan, "with_original", False):
                key = "ready_original"
            if action == "claim_group" and not already:
                key = "ready_claim_group"
            self.notice.setText(self.t[key])
        self.controls(not self.owner.busy and not self.owner._invalid)

    def selection_changed(self, _row):
        self.action_plans = {}
        self.action_select.clear()
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
            supported = (
                operation["version"] == 2
                and operation["entity_type"] == "note"
                and operation["action"] == "put"
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
                with closing(_readonly_connection(observed.database)) as conn:
                    already = (
                        conn.execute(
                            "SELECT 1 FROM paperfact_sync_operations WHERE operation_id=?",
                            (request_id,),
                        ).fetchone()
                        is not None
                    )
                try:
                    plan = note_copy.prepare(observed, selected, request_id, cancelled=stopped)
                except (OSError, ValueError):
                    # Missing parent/source proof keeps comparison readable.
                    # A previously saved request must still validate its receipt.
                    observed._check(backup._guard(30, stopped))
                    if already:
                        raise
                    if operation["payload"].get("anchor") is not None:
                        try:
                            plan = note_copy.prepare(
                                observed, selected, request_id, with_original=True,
                                cancelled=stopped,
                            )
                        except (OSError, ValueError):
                            observed._check(backup._guard(30, stopped))
            plans = self._metadata_plans(observed, selected, comparison, stopped)
            return observed, selected, comparison, plan, already, plans

        return self._start("compare", run)

    def _metadata_plans(self, observed, selected, comparison, stopped):
        operation = comparison["source"]["operation"]
        options, current_action = ["keep"], None
        if (
            operation["version"] == 2 and operation["entity_type"] in choices.KINDS
            and operation["action"] == "put"
        ):
            current = comparison["target"]["entity_state"]
            parents = [
                dict(parent["expected"], incarnation=parent["current"]["incarnation"])
                for parent in comparison["target"]["parents"] if parent["current"] is not None
            ]
            current_action = (
                "add" if current is None else
                "restore" if not current["active"] or current["parents"] != parents else "replace"
            )
            options.extend(("add", "replace", "restore"))
        plans = {}
        for action in options:
            request_id = str(uuid5(NAMESPACE_URL, "paperfact:recovery-choice-ui:v1:" +
                candidates._json([
                    observed.binding, operation["workspace_id"], operation["device_id"],
                    operation["operation_id"], candidates._fingerprint(operation), action,
                ])))
            with closing(_readonly_connection(observed.database)) as conn:
                saved = conn.execute(
                    "SELECT 1 FROM integration_operations WHERE id=?", (request_id,)
                ).fetchone() is not None
                native = conn.execute(
                    "SELECT 1 FROM paperfact_sync_operations WHERE operation_id=?", (request_id,)
                ).fetchone() is not None
            if action != "keep" and action != current_action and not (saved or native):
                continue
            try:
                plan = choices.prepare(observed, selected, action, request_id, cancelled=stopped)
            except ValueError:
                if saved or native:
                    raise
                continue
            plans[action] = (plan, saved)
        if operation["entity_type"] == "research_content" and operation["payload"].get(
            "feature"
        ) == "claims":
            request = str(uuid5(NAMESPACE_URL, "paperfact:claim-group-ui:" + candidates._json([
                observed.binding, operation["operation_id"], candidates._fingerprint(operation),
            ])))
            try:
                group = claim_group.prepare(
                    observed, selected, request, replace=True, cancelled=stopped,
                )
            except (OSError, ValueError) as error:
                comparison["claim_group_issue"] = str(error)[:240]
                with closing(_readonly_connection(observed.database)) as conn:
                    if conn.execute("SELECT 1 FROM integration_operations WHERE id=?",
                                    (request,)).fetchone():
                        raise
                observed._check(backup._guard(60, stopped))
            else:
                plans["claim_group"] = (group, group.already)
        return plans

    def _group_text(self, members, side):
        parts = []
        for member in members:
            feature, data = member["feature"], member[side]
            parts.append(self.t["group_" + feature])
            if data is None:
                parts.append(self.t["retired"] if side == "current" and member.get(
                    "state"
                ) == "retired" else self.t["absent"])
            elif feature != "claims":
                parts.append(data["body"])
            else:
                for claim in data["body_json"]["report"]["claims"]:
                    judgment = claim["judgment"]
                    parts.append(claim["text"] + "\n" + self.t["group_judgment"] + ": "
                                 + judgment["status"] + " ? " + judgment["reason"])
                    parts.extend(passage["quote"] for passage in claim["passages"])
        return "\n\n".join(parts)

    def _completion(self, receipt, changed=False):
        if "choice" not in receipt:
            return self.t["saved_changed" if changed else "saved"]
        return self.t["decision_changed" if changed else
                      "kept" if receipt["choice"] == "keep" else "decision_saved"]

    def copy(self):
        if self._confirming or not self.copy_button.isEnabled():
            return False
        plan, action = self.plan, self.action_select.currentData()
        include_original = action == "copy" and getattr(plan, "with_original", False)
        if action in {"replace", "restore", "claim_group"} or include_original:
            self._confirming = True
            self.controls(False)
            try:
                answer = QMessageBox.question(
                    self, self.t["confirm_title"],
                    self.t["confirm_claim_group"] if action == "claim_group" else
                    self.t["confirm_original"] if include_original else
                    self.t["confirm_body"].format(action=self.t[action]),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
            finally:
                self._confirming = False
            if self.owner.disposed or self.owner._closing:
                return False
            self.controls(not self.owner.busy and not self.owner._invalid)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        if (
            plan is not self.plan or self.owner.busy
            or not self.owner._adoption_context_current()
        ):
            return False

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
            owner.status.setText(
                self._completion(worker.result[0], True) if copied else self.t["stale"]
            )
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
            message = self._completion(worker.result[0], not stable)
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
                _observed, selected, comparison, plan, already, plans = worker.result
                if observed is not self.observed or selected != self.selected():
                    raise ValueError("Selected recovery change changed")
                source = comparison["source"]["operation"]
                effective = comparison["target"]["effective_operation"]
                self.old.setPlainText(self._content(source))
                self.current.setPlainText(self._content(effective))
                self.action_plans = dict(plans)
                if plan is not None:
                    self.action_plans["copy"] = (plan, already)
                group = self.action_plans.get("claim_group", (None, False))[0]
                if group is not None and group.comparison:
                    self.old.setPlainText(self._group_text(group.comparison, "source"))
                    self.current.setPlainText(self._group_text(group.comparison, "current"))
                self.action_select.blockSignals(True)
                self.action_select.clear()
                self.action_select.addItem(self.t["review"], "")
                for action in self.action_plans:
                    label = "copy_original" if action == "copy" and getattr(
                        plan, "with_original", False
                    ) else action
                    self.action_select.addItem(self.t[label], action)
                if plan is not None:
                    self.action_select.setCurrentIndex(self.action_select.findData("copy"))
                elif group is not None:
                    self.action_select.setCurrentIndex(self.action_select.findData("claim_group"))
                self.action_select.blockSignals(False)
                self.action_changed(self.action_select.currentIndex())
                self.notice.setText(
                    self.t["already" if already else "ready_original" if getattr(
                        plan, "with_original", False
                    ) else "ready" if plan is not None else
                           "ready_claim_group" if group is not None and not group.already else
                           "already_action" if group is not None else
                           "ready_action" if len(plans) > 1 else "unsupported"]
                )
                if comparison.get("claim_group_issue"):
                    self.notice.setText(self.t["group_blocked"] + comparison["claim_group_issue"])
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
