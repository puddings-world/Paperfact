"Saved-first workspace Inbox. All persistence/ownership reads stay on a worker."

from datetime import UTC, datetime
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from paper_daily import inbox_content as content
from paper_daily.desktop.research_updates import _Reader

COPY = {
    "en": {
        "context": ("Workspace ownership changed. Close and reopen Inbox; your draft is kept."),
        "title": "Research Inbox",
        "hint": (
            "Save a DOI, URL or short idea for later triag"
            "e. Saving never searches, downloads, opens a "
            "URL or calls AI."
        ),
        "columns": ["Captured text", "Triage", "Saved state"],
        "new": "New capture",
        "save": "Save",
        "delete": "Delete",
        "restore": "Restore",
        "refresh": "Refresh",
        "close": "Close",
        "idea": "Idea",
        "doi": "DOI",
        "url": "URL",
        "state_new": "New",
        "state_kept": "Keep",
        "state_dismissed": "Dismissed",
        "deleted": "Deleted",
        "sync_local": "Local",
        "sync_pending": "Pending upload",
        "sync_awaiting": "Awaiting receipt",
        "sync_deferred": "Apply pending",
        "sync_synced": "Synced",
        "sync_conflict": "Retained conflict",
        "empty": "No saved captures in this page.",
        "ready": "Saved captures; explicit triage changes only.",
        "working": "Working locally...",
        "saved": ("Saved locally. Sync uses your existing connection when you choose it."),
        "conflict": ("A newer version was kept. Your proposal is retained for review."),
        "failed": ("The operation failed. Your draft is kept; retry with the same request."),
        "changed": ("Workspace or records changed. Refresh before saving; your draft is kept."),
        "limit": (
            "Use 1 to 2048 characters, at most 8192 UTF-8 "
            "bytes, with a valid DOI/HTTP(S) URL for that "
            "kind."
        ),
        "draft_title": "Keep your draft",
        "draft": ("This text has not been saved. Keep editing, or explicitly discard it?"),
        "confirm_delete": "Delete this capture? Its saved history is retained.",
        "confirm_restore": "Restore this deleted capture as a new incarnation?",
        "review": "Retained versions",
        "keep_current": "Keep current",
        "use_proposal": "Use proposal",
        "review_ready": (
            "Select a retained proposal. Decisions are explicit; no synchronization is started."
        ),
        "history": "Saved version",
        "proposal": "Retained proposal",
        "resolved": "Decision saved locally.",
        "page": ("Showing at most 256 captures. Use the page buttons for more captures."),
    },
    "zh-TW": {
        "context": ("工作區歸屬已變更。請關閉並重開收件匣；草稿仍保留。"),
        "sync_local": "\u672c\u6a5f",
        "sync_pending": "\u5f85\u4e0a\u50b3",
        "sync_awaiting": "\u7b49\u5f85\u6536\u64da",
        "sync_deferred": "\u5f85\u5957\u7528",
        "sync_synced": "\u5df2\u540c\u6b65",
        "sync_conflict": "\u4fdd\u7559\u885d\u7a81",
        "title": "\u7814\u7a76\u6536\u4ef6\u5323",
        "hint": ("儲存 DOI、網址或短構想，稍後再整理。儲存不會搜尋、下載、開啟網址或呼叫 AI。"),
        "columns": [
            "\u6536\u96c6\u6587\u5b57",
            "\u6574\u7406\u72c0\u614b",
            "\u5132\u5b58\u72c0\u614b",
        ],
        "new": "\u65b0\u6536\u96c6",
        "save": "\u5132\u5b58",
        "delete": "\u522a\u9664",
        "restore": "\u9084\u539f",
        "refresh": "\u91cd\u65b0\u8b80\u53d6",
        "close": "\u95dc\u9589",
        "idea": "\u69cb\u60f3",
        "doi": "DOI",
        "url": "\u7db2\u5740",
        "state_new": "\u5f85\u6574\u7406",
        "state_kept": "\u4fdd\u7559",
        "state_dismissed": "\u7565\u904e",
        "deleted": "\u5df2\u522a\u9664",
        "empty": ("此頁尚無已儲存的收集。"),
        "ready": ("已儲存的收集；只會執行你明確選擇的整理。"),
        "working": "\u6b63\u5728\u672c\u6a5f\u8655\u7406...",
        "saved": ("已儲存於本機。你可明確選擇使用現有連線同步。"),
        "conflict": ("較新版本已保留，你的提案也已保留供審閱。"),
        "failed": ("操作失敗。草稿仍保留，可使用相同請求重試。"),
        "changed": ("工作區或資料已變更。請先重新讀取；草稿仍保留。"),
        "limit": (
            "請輸入 1 至 2048 字，最多 8192 UTF-8 位元組；DOI 或 HTTP(S) 網址須符合所選類型。"
        ),
        "draft_title": "\u4fdd\u7559\u8349\u7a3f",
        "draft": ("這些文字尚未儲存。要繼續編輯，或明確捨棄？"),
        "confirm_delete": ("要刪除這筆收集嗎？已儲存的歷史會保留。"),
        "confirm_restore": ("要以新生命週期還原這筆已刪除的收集嗎？"),
        "review": "\u4fdd\u7559\u7248\u672c",
        "keep_current": "\u4fdd\u7559\u76ee\u524d\u7248\u672c",
        "use_proposal": "\u4f7f\u7528\u63d0\u6848",
        "review_ready": ("選擇保留的提案。每個決定都需明確操作，不會自動同步。"),
        "history": "\u5df2\u5132\u5b58\u7248\u672c",
        "proposal": "\u4fdd\u7559\u63d0\u6848",
        "resolved": "\u6c7a\u5b9a\u5df2\u5132\u5b58\u65bc\u672c\u6a5f\u3002",
        "page": ("每頁最多顯示 256 筆，使用頁面按鈕查看更多。"),
    },
}


class InboxDialog(QDialog):
    def __init__(self, service, parent=None, *, language="en"):
        super().__init__(parent)
        self.service, self.t = service, COPY.get(language, COPY["en"])
        self._worker = self._view = self._review = None
        self.disposed = self._closing = self._stale = self._dirty = self._filling = False
        self._editor_epoch = 0
        self._item = None
        self._request = self._identity = None
        self._stamp = None
        self._intent = self._decision_intent = None
        self._offset = 0
        self.setWindowTitle(self.t["title"])
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(760, 640)
        outer = QVBoxLayout(self)
        hint = QLabel(self.t["hint"])
        hint.setWordWrap(True)
        outer.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(self.t["columns"])
        self.tree.setRootIsDecorated(False)
        self.tree.currentItemChanged.connect(self._selected)
        outer.addWidget(self.tree, 1)
        options = QHBoxLayout()
        self.kind, self.state = QComboBox(), QComboBox()
        for key in ("idea", "doi", "url"):
            self.kind.addItem(self.t[key], key)
        for key in ("new", "kept", "dismissed"):
            self.state.addItem(self.t["state_" + key], key)
        options.addWidget(self.kind)
        options.addWidget(self.state)
        outer.addLayout(options)
        self.editor = QPlainTextEdit()
        self.editor.setAccessibleName(self.t["title"])
        outer.addWidget(self.editor, 1)
        self.editor.textChanged.connect(self._edited)
        self.kind.currentIndexChanged.connect(self._edited)
        self.state.currentIndexChanged.connect(self._edited)
        actions = QHBoxLayout()
        self.buttons = {}
        for key, callback in (
            ("new", self.new_capture),
            ("save", self.save),
            ("delete", self.delete),
            ("restore", self.restore),
            ("refresh", self.refresh),
            ("review", self.review),
            ("close", self.close),
        ):
            button = QPushButton(self.t[key])
            button.setAutoDefault(False)
            button.clicked.connect(callback)
            actions.addWidget(button)
            self.buttons[key] = button
        outer.addLayout(actions)
        pages = QHBoxLayout()
        self.previous_button = QPushButton("<")
        self.next_button = QPushButton(">")
        self.previous_button.setAccessibleName(self.t["refresh"] + " - 1")
        self.next_button.setAccessibleName(self.t["refresh"] + " + 1")
        self.previous_button.clicked.connect(lambda: self.page(-1))
        self.next_button.clicked.connect(lambda: self.page(1))
        pages.addWidget(self.previous_button)
        pages.addWidget(self.next_button)
        outer.addLayout(pages)
        self.review_tree = QTreeWidget()
        self.review_tree.setHeaderLabels([self.t["review"], self.t["title"]])
        self.review_tree.currentItemChanged.connect(self._review_selected)
        self.review_tree.hide()
        outer.addWidget(self.review_tree)
        review_actions = QHBoxLayout()
        for key, choice in (("keep_current", "canonical"), ("use_proposal", "incoming")):
            button = QPushButton(self.t[key])
            button.clicked.connect(lambda _checked=False, value=choice: self.decide(value))
            button.hide()
            self.buttons[key] = button
            review_actions.addWidget(button)
        outer.addLayout(review_actions)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.hide()
        outer.addWidget(self.preview)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._check)
        self._poll.start()
        self._new()
        self._buttons()
        QTimer.singleShot(0, self.refresh)

    @property
    def busy(self):
        return self._worker is not None

    def _buttons(self):
        ready = not (self.busy or self.disposed or self._closing)
        bound = ready and self._view is not None and not self._stale
        for key in ("new", "refresh"):
            self.buttons[key].setEnabled(ready)
        self.buttons["save"].setEnabled(
            bound and self._dirty and (self._item is None or self._item["active"] == 1)
        )
        self.buttons["delete"].setEnabled(
            bound and self._item is not None and self._item["active"] == 1
        )
        self.buttons["restore"].setEnabled(
            bound and self._item is not None and self._item["active"] == 0
        )
        self.buttons["review"].setEnabled(bound)
        self.previous_button.setEnabled(ready and self._offset > 0)
        self.next_button.setEnabled(bound and self._view.data["has_more"])
        self.tree.setEnabled(ready)
        for widget in (self.kind, self.state, self.editor):
            widget.setEnabled(ready)
        chosen = self.review_tree.currentItem()
        for key in ("keep_current", "use_proposal"):
            self.buttons[key].setEnabled(
                bool(
                    bound
                    and self._review is not None
                    and self.service.current(self._review)
                    and not self._dirty
                    and chosen
                    and chosen.data(0, Qt.ItemDataRole.UserRole)
                )
            )

    def _check(self):
        try:
            self.service._path_check()
            if self._view is not None and not self.busy and not self.service.current(self._view):
                self._stale = True
                self.status.setText(self.t["changed"])
        except (OSError, ValueError):
            self._stale = True
            if self._worker:
                self._worker.ticket.cancel()
            self.status.setText(self.t["changed"])
        self._buttons()

    def _edited(self, *_args):
        if not self._filling:
            self._dirty = True
            self._editor_epoch += 1
            self._request = str(uuid4())
            self._stamp = datetime.now(UTC).isoformat(timespec="milliseconds")
        self._buttons()

    def _new(self):
        self._filling = True
        self._intent = None
        self._item = None
        self._identity, self._request = str(uuid4()), str(uuid4())
        self._stamp = datetime.now(UTC).isoformat(timespec="milliseconds")
        self.editor.clear()
        self.kind.setCurrentIndex(0)
        self.state.setCurrentIndex(0)
        self._filling = False
        self._dirty = False
        self._editor_epoch += 1

    def _may_replace(self):
        if not self._dirty:
            return True
        return (
            QMessageBox.question(
                self,
                self.t["draft_title"],
                self.t["draft"],
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Discard
        )

    def new_capture(self):
        if self.busy or self.disposed or not self._may_replace():
            return False
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        self.tree.setCurrentItem(None)
        self.tree.blockSignals(False)
        self._new()
        self._buttons()
        return True

    def _selected(self, current, _previous):
        if current is None or self._filling:
            return
        row = current.data(0, Qt.ItemDataRole.UserRole)
        if self._item is not None and self._item["id"] == row["id"]:
            return
        if not self._may_replace():
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(_previous)
            self.tree.blockSignals(False)
            return
        self._filling = True
        self._item, self._identity, self._request = row, row["id"], str(uuid4())
        data = row["payload"] or dict(kind="idea", text="", state="new")
        self.editor.setPlainText(data["text"])
        self.kind.setCurrentIndex(self.kind.findData(data["kind"]))
        self.state.setCurrentIndex(self.state.findData(data["state"]))
        self._stamp = datetime.now(UTC).isoformat(timespec="milliseconds")
        self._dirty = self._filling = False
        self._editor_epoch += 1
        self._buttons()

    def _payload(self):
        created = (
            self._item["payload"]["created_at"]
            if self._item and self._item["payload"]
            else self._stamp
        )
        return dict(
            kind=self.kind.currentData(),
            text=self.editor.toPlainText(),
            state=self.state.currentData(),
            created_at=created,
            updated_at=self._stamp,
        )

    def _start(self, kind, task):
        if self.busy or self.disposed or self._closing:
            return False
        worker = _Reader(task, self)
        worker.kind, worker.epoch, worker.identity = kind, self._editor_epoch, self._identity
        self._worker = worker
        worker.finished.connect(self._finished)
        self.status.setText(self.t["working"])
        self._buttons()
        try:
            worker.start()
        except RuntimeError:
            self._worker = None
            worker.deleteLater()
            self.status.setText(self.t["failed"])
            self._buttons()
            return False
        return True

    def refresh(self):
        return self._start(
            "read",
            lambda ticket: self.service.read(ticket, offset=self._offset, include_deleted=True),
        )

    def page(self, direction):
        if self.busy or direction not in (-1, 1):
            return False
        if direction == 1 and (self._view is None or not self._view.data["has_more"]):
            return False
        self._offset = max(0, self._offset + direction * content.PAGE_SIZE)
        return self.refresh()

    def _write(self, action="put", restore=False):
        if self.busy or self.disposed or self._view is None or self._stale:
            return False
        if action == "put" and not restore and not self._dirty:
            return False
        data = self._payload() if action == "put" else None
        try:
            if data is not None:
                content.validate(data)
        except ValueError:
            self.status.setText(self.t["limit"])
            return False
        view, identity = self._view, self._identity
        observed = self.service.observe(self._item)
        intent = content.encode(
            dict(action=action, restore=restore, payload=data, observed=observed, id=identity)
        )
        if intent != self._intent:
            self._intent, self._request = intent, str(uuid4())
        request = self._request

        def task(ticket):
            result = self.service.save(
                view,
                request_id=request,
                item_id=identity,
                payload=data,
                observed=observed,
                action=action,
                restore=restore,
                ticket=ticket,
            )
            try:
                fresh = self.service.read(ticket, offset=self._offset, include_deleted=True)
            except (OSError, ValueError):
                fresh = None
            return result, fresh

        return self._start("write", task)

    def save(self):
        return self._write()

    def delete(self):
        if self.busy or self._item is None or self._item["active"] != 1 or self._dirty:
            return False
        if (
            QMessageBox.question(
                self,
                self.t["delete"],
                self.t["confirm_delete"],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return False
        return self._write("delete")

    def restore(self):
        if self.busy or self._item is None or self._item["active"] != 0:
            return False
        if (
            QMessageBox.question(
                self,
                self.t["restore"],
                self.t["confirm_restore"],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return False
        return self._write(restore=True)

    def review(self):
        if self.busy or self._view is None or self._stale:
            return False
        view, identity = self._view, self._item["id"] if self._item else None
        return self._start(
            "review", lambda ticket: self.service.retained(view, ticket, item_id=identity)
        )

    def _review_selected(self, *_args):
        item = self.review_tree.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole + 1) if item else None
        self.preview.setPlainText(data or "")
        self._buttons()

    def decide(self, choice):
        selected = self.review_tree.currentItem()
        if (
            self.busy
            or self._stale
            or self._review is None
            or not selected
            or self._dirty
            or not self.service.current(self._review)
        ):
            return False
        record = selected.data(0, Qt.ItemDataRole.UserRole)
        if not record:
            return False
        restore = False
        if choice == "incoming" and record["action"] == "put":
            current = next(
                (row for row in self._view.data["items"] if row["id"] == record["item_id"]), None
            )
            if current is not None and not current["active"]:
                restore = (
                    QMessageBox.question(
                        self,
                        self.t["restore"],
                        self.t["confirm_restore"],
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Cancel,
                    )
                    == QMessageBox.StandardButton.Yes
                )
                if not restore:
                    return False
        view = self._review
        intent = content.encode(dict(record=record, choice=choice, restore=restore))
        if self._decision_intent is None or self._decision_intent[0] != intent:
            self._decision_intent = intent, str(uuid4())
        request = self._decision_intent[1]

        def task(ticket):
            result = self.service.resolve(
                view,
                record["id"],
                choice=choice,
                request_id=request,
                restore=restore,
                ticket=ticket,
            )
            try:
                fresh = self.service.read(ticket, offset=self._offset, include_deleted=True)
            except (OSError, ValueError):
                fresh = None
            return result, fresh

        return self._start("decision", task)

    def _render(self, view):
        self._view, self._stale = view, False
        self.tree.blockSignals(True)
        self.tree.clear()
        for row in view.data["items"]:
            text = row["payload"]["text"] if row["payload"] else self.t["deleted"]
            state = (
                self.t["state_" + row["payload"]["state"]] if row["active"] else self.t["deleted"]
            )
            item = QTreeWidgetItem(
                self.tree, [text[:160], state, self.t["sync_" + row["sync_state"]]]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            if self._item and row["id"] == self._item["id"]:
                self.tree.setCurrentItem(item)
                if not self._dirty:
                    self._item = row
        self.tree.blockSignals(False)
        self.status.setText(
            self.t["page"]
            if view.data["has_more"]
            else self.t["ready"]
            if view.data["items"]
            else self.t["empty"]
        )

    def _render_review(self, view):
        self._review = view
        self.review_tree.clear()
        for row in view.data["retained"]:
            text = row["payload"]["text"] if row["payload"] else self.t["delete"]
            item = QTreeWidgetItem(self.review_tree, [self.t["proposal"], text[:160]])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, text)
        for row in view.data["history"]:
            text = row["payload"]["text"] if row["payload"] else self.t["deleted"]
            item = QTreeWidgetItem(self.review_tree, [self.t["history"], text[:160]])
            item.setData(0, Qt.ItemDataRole.UserRole + 1, text)
        self.review_tree.show()
        self.preview.show()
        for key in ("keep_current", "use_proposal"):
            self.buttons[key].show()
        self.status.setText(self.t["review_ready"])

    def _finished(self):
        worker, self._worker = self._worker, None
        if worker is None:
            return
        try:
            if self.disposed:
                return
            self.service._path_check()
            if worker.error or (worker.ticket.cancelled and not worker.ticket.published):
                self.status.setText(
                    self.t[
                        ("context" if self.service.needs_reopen else "changed")
                        if worker.error == "changed"
                        else "failed"
                    ]
                )
            elif worker.kind in ("read", "review"):
                if not self.service.current(worker.result):
                    self._stale = True
                    self.status.setText(self.t["changed"])
                elif not self._closing:
                    (self._render if worker.kind == "read" else self._render_review)(worker.result)
            else:
                result, fresh = worker.result
                if fresh is None or not self.service.current(fresh):
                    self._stale = True
                    self.status.setText(self.t["changed"])
                else:
                    if (
                        result["status"] in ("saved", "resolved")
                        and worker.epoch == self._editor_epoch
                        and worker.identity == self._identity
                    ):
                        self._dirty = False
                        self._item = next(
                            (row for row in fresh.data["items"] if row["id"] == self._identity),
                            self._item,
                        )
                    if not self._closing:
                        self._render(fresh)
                        self.status.setText(self.t[result["status"]])
        except (OSError, ValueError):
            self._stale = True
            self.status.setText(self.t["changed"])
        finally:
            worker.deleteLater()
            closing, self._closing = self._closing, False
            self._buttons()
            if closing:
                self.close()

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if self._worker:
            self._closing = True
            self._worker.ticket.cancel()
            self._buttons()
            event.ignore()
            return
        if not self._may_replace():
            event.ignore()
            return
        self.disposed = True
        self._poll.stop()
        QDialog.reject(self)
        event.accept()
