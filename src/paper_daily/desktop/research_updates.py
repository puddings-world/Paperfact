"""A bounded local activity view. No accounts, transport, or model work."""

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from paper_daily.workspace_service import Cancelled, Ticket, WorkspaceChanged

COPY = {
    "en": {
        "title": "Research activity",
        "continue": "Continue reading",
        "recent": "Recent changes",
        "coverage": "Recorded reading and note updates, in received order. "
        "This is not your last opened paper or PDF page.",
        "echo": "Accepted changes from this device are hidden in Recent changes; "
        "retained conflicts remain visible. File metadata is not a download.",
        "columns": ["Paper", "Recorded change", "State"],
        "refresh": "Refresh",
        "open": "Open paper",
        "locate": "Locate saved passage",
        "close": "Close",
        "source_hint": "A saved passage needs its matching PDF already open. "
        "Opening a paper never schedules a later page jump.",
        "ready": "Showing a bounded window of received activity.",
        "empty": "No recorded activity in this window.",
        "unavailable": "Received activity is not available for this local workspace yet.",
        "working": "Reading local records…",
        "cancelled": "Stopped; research is unchanged.",
        "failed": "Activity could not be read. Refresh to try again.",
        "changed": "Workspace or record changed. Refresh before opening it.",
        "context": "Workspace changed. Close and reopen activity.",
        "drafts": "Finish the active task or save your draft first. Your draft is kept.",
        "source": "Open the matching current PDF first; no passage was moved.",
        "missing": "This item cannot be opened in the current reader.",
        "opened": "Paper opened.",
        "located": "Saved passage located.",
        "hidden": "Unavailable in this context",
        "paper_only": "Paper only",
        "saved_passage": "Saved passage",
        "applied": "Applied locally",
        "accepted_history": "Accepted history",
        "accepted_pending": "Accepted; local apply pending",
        "conflict_retained": "Retained conflict",
        "resolved": "Resolution recorded",
        "manifest_waiting": "Metadata applied; verified files pending",
        "binding_recorded": "File binding recorded; availability checked when opened",
        "note": "Note",
        "reading_state": "Reading state",
        "paper_document": "PDF metadata",
        "research_file": "Research files",
        "paper": "Paper",
        "other": "Research update",
    },
    "zh-TW": {
        "title": "研究動態",
        "continue": "繼續閱讀",
        "recent": "最近變更",
        "coverage": "依接收順序顯示已記錄的閱讀與筆記更新，不代表最後開啟的論文或 PDF 頁碼。",
        "echo": "最近變更會隱藏此裝置已接受的回傳紀錄，但仍顯示保留的衝突。檔案資訊不代表已下載。",
        "columns": ["論文", "已記錄的變更", "狀態"],
        "refresh": "重新整理",
        "open": "開啟論文",
        "locate": "定位已儲存的段落",
        "close": "關閉",
        "source_hint": "定位段落需要先開啟相符的 PDF。開啟論文不會安排稍後自動跳頁。",
        "ready": "顯示範圍有限的接收紀錄。",
        "empty": "目前範圍沒有已記錄的動態。",
        "unavailable": "這個本機工作區尚無可用的接收動態。",
        "working": "讀取本機紀錄中…",
        "cancelled": "已停止，研究內容未變更。",
        "failed": "無法讀取動態，請重新整理後再試。",
        "changed": "工作區或紀錄已變更，請重新整理後再開啟。",
        "context": "工作區已變更，請關閉並重新開啟動態。",
        "drafts": "請先完成目前工作或儲存草稿，草稿仍保留。",
        "source": "請先開啟相符的目前 PDF，尚未移動段落。",
        "missing": "目前閱讀器無法開啟這筆紀錄。",
        "opened": "已開啟論文。",
        "located": "已定位儲存的段落。",
        "hidden": "目前內容已不可用",
        "paper_only": "僅開啟論文",
        "saved_passage": "已儲存的段落",
        "applied": "已套用至本機",
        "accepted_history": "已接受的歷史紀錄",
        "accepted_pending": "已接受，等待本機套用",
        "conflict_retained": "已保留的衝突",
        "resolved": "已記錄解決方式",
        "manifest_waiting": "已套用檔案資訊，等待驗證檔案",
        "binding_recorded": "已記錄檔案綁定，開啟時仍會檢查可用性",
        "note": "筆記",
        "reading_state": "閱讀狀態",
        "paper_document": "PDF 資訊",
        "research_file": "研究檔案",
        "paper": "論文",
        "other": "研究更新",
    },
}


class _Reader(QThread):
    def __init__(self, task, parent):
        super().__init__(parent)
        self.task, self.ticket = task, Ticket()
        self.result = self.error = None

    def run(self):
        try:
            self.result = self.task(self.ticket)
        except Cancelled:
            self.error = "cancelled"
        except (WorkspaceChanged, FileNotFoundError):
            self.error = "changed"
        except Exception:
            self.error = "failed"


class ResearchUpdatesDialog(QDialog):
    def __init__(
        self,
        service,
        parent=None,
        *,
        language="en",
        activate=None,
        prepare=None,
        can_locate=lambda _row: False,
        blocked=lambda: False,
    ):
        super().__init__(parent)
        self.service, self.activate, self.prepare = service, activate, prepare
        self.can_locate, self.blocked = can_locate, blocked
        self.t = COPY.get(language, COPY["en"])
        self._worker = None
        self.disposed = self._closing = self._invalid = False
        self._stale = False
        self.setWindowTitle(self.t["title"])
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(760, 500)
        self.setMinimumSize(440, 340)
        outer = QVBoxLayout(self)
        for key in ("coverage", "echo"):
            label = QLabel(self.t[key])
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            outer.addWidget(label)
        self.tabs = QTabWidget()
        self.trees = []
        for key in ("continue", "recent"):
            tree = QTreeWidget()
            tree.setHeaderLabels(self.t["columns"])
            tree.setAccessibleName(self.t[key])
            tree.setRootIsDecorated(False)
            tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            tree.itemSelectionChanged.connect(self._buttons)
            tree.itemActivated.connect(lambda _item, _column: self.open_selected())
            # On macOS a tree takes Return as "edit" and never emits itemActivated.
            for name in ("Return", "Enter"):
                shortcut = QShortcut(QKeySequence(name), tree, self.open_selected)
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            self.tabs.addTab(tree, self.t[key])
            self.trees.append(tree)
        self.tabs.currentChanged.connect(self._buttons)
        outer.addWidget(self.tabs, 1)
        hint = QLabel(self.t["source_hint"])
        hint.setWordWrap(True)
        outer.addWidget(hint)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton(self.t["refresh"])
        self.open_button = QPushButton(self.t["open"])
        self.locate_button = QPushButton(self.t["locate"])
        self.close_button = QPushButton(self.t["close"])
        for button in (
            self.refresh_button,
            self.open_button,
            self.locate_button,
            self.close_button,
        ):
            button.setAutoDefault(False)
            actions.addWidget(button)
        self.refresh_button.clicked.connect(self.refresh)
        self.open_button.clicked.connect(self.open_selected)
        self.locate_button.clicked.connect(lambda: self.open_selected(locate=True))
        self.close_button.clicked.connect(self.close)
        outer.addLayout(actions)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._check)
        self._poll.start()
        self._buttons()
        QTimer.singleShot(0, self.refresh)

    @property
    def busy(self):
        return self._worker is not None

    def _row(self):
        item = self.trees[self.tabs.currentIndex()].currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def _buttons(self):
        ready = not (self.busy or self.disposed or self._closing or self._invalid)
        row = self._row()
        self.refresh_button.setEnabled(ready)
        allowed = (
            ready
            and not self._stale
            and row is not None
            and row["paper_id"] is not None
            and not self.blocked()
        )
        self.open_button.setEnabled(allowed and self.activate is not None)
        self.locate_button.setEnabled(bool(allowed and row["resume"] and self.can_locate(row)))
        self.tabs.setEnabled(ready)

    def _check(self):
        if not self._invalid:
            try:
                self.service._path_check()
                if not self.busy and not self.service.current():
                    self._stale = True
                    self.status.setText(self.t["changed"])
            except (WorkspaceChanged, OSError):
                self._invalid = True
                if self._worker:
                    self._worker.ticket.cancel()
                self.status.setText(self.t["context"])
        self._buttons()

    def _start(self, task, *, row=None, locate=False):
        if self.busy or self.disposed or self._closing or self._invalid:
            return False
        worker = _Reader(task, self)
        worker.row, worker.locate = row, locate
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
        return self._start(lambda ticket: self.service.snapshot(ticket))

    def open_selected(self, _checked=False, *, locate=False):
        if self.busy or self.disposed or self._closing or self._invalid:
            return False
        row = self._row()
        if not row or row["paper_id"] is None or self.activate is None:
            return False
        if self._stale:
            return False
        if self.blocked():
            self.status.setText(self.t["drafts"])
            return False
        if locate and (not row["resume"] or not self.can_locate(row)):
            self.status.setText(self.t["source"])
            return False
        try:
            task = (
                self.prepare(row, locate)
                if self.prepare is not None
                else lambda ticket: self.service.resolve(row, locate=locate, ticket=ticket)
            )
        except (OSError, ValueError):
            self.status.setText(self.t["source"])
            return False
        return self._start(task, row=row, locate=locate)

    def _render(self, result):
        self._stale = False
        for tree, key in zip(self.trees, ("continue", "recent"), strict=True):
            tree.clear()
            for row in result[key]:
                item = QTreeWidgetItem(tree)
                item.setData(0, Qt.ItemDataRole.UserRole, row)
                kind = self.t.get(row["entity_type"], self.t["other"])
                status = (
                    self.t["saved_passage" if row["resume"] else "paper_only"]
                    if key == "continue"
                    else self.t[row["status"]]
                )
                if row["resolved"]:
                    status += " · " + self.t["resolved"]
                for column, value in enumerate(
                    (row["title"] or self.t["hidden"], f"{kind} · #{row['sequence']}", status)
                ):
                    item.setText(column, value)
                    item.setToolTip(column, value)
        self.status.setText(
            self.t["unavailable"]
            if not result.get("available")
            else self.t["ready"]
            if result["recent"] or result["continue"]
            else self.t["empty"]
        )

    def _finished(self):
        worker, self._worker = self._worker, None
        if worker is None:
            return
        try:
            if self._closing or self.disposed:
                return
            self.service._path_check()
            if worker.error or worker.ticket.cancelled:
                self._stale = True
                self._invalid = bool(getattr(self.service, "needs_reopen", False))
                self.status.setText(
                    self.t["context" if self._invalid else worker.error or "cancelled"]
                )
            elif worker.row is None:
                self.service.check(worker.result)
                self._render(worker.result)
            elif self.blocked():
                self.status.setText(self.t["drafts"])
            else:
                proof = worker.result.proof if self.prepare is not None else worker.result
                self.service.check(proof)
                message = self.activate(
                    worker.result if self.prepare is not None else worker.result["row"],
                    worker.locate,
                )
                self.status.setText(self.t.get(message, self.t["failed"]))
                if message in ("opened", "located"):
                    self.close()
        except (WorkspaceChanged, FileNotFoundError):
            self._stale = True
            try:
                self.service._path_check()
            except (WorkspaceChanged, FileNotFoundError):
                self._invalid = True
            self.status.setText(self.t["context" if self._invalid else "changed"])
        except Exception:
            self.status.setText(self.t["failed"])
        finally:
            worker.deleteLater()
            self._buttons()
            if self._closing:
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
        self.disposed = True
        self._poll.stop()
        # Calling the base closeEvent would re-enter our cancellation-aware reject.
        QDialog.reject(self)
        event.accept()
