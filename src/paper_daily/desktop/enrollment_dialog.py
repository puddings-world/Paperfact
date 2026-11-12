"""Reviewed local enrollment copies, never in-place adoption or remote issuance."""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from paper_daily.document_reader import from_workspace
from paper_daily.workspace_enrollment import (
    MAX_FILES,
    MAX_ROWS,
    EnrollmentBlocked,
    EnrollmentService,
)
from paper_daily.workspace_service import (
    Cancelled,
    SnapshotChanged,
    Ticket,
    WorkspaceChanged,
    _binding,
    _safe_path,
    _tables,
)

COPY = {
    "en": {
        "title": "Prepare a workspace copy",
        "intro": (
            "Check what can be transferred, then prepare a separate verified copy and"
            " backup. Your current workspace and open drafts stay here."
        ),
        "scope": (
            "This prepares local files for review. It does not connect, upload, issue"
            " service credentials or switch this reader to another workspace."
        ),
        "source": "Current workspace",
        "coverage": "1. Preview coverage",
        "check": "Check content",
        "outputs": "2. Choose new destinations",
        "workspace": "New workspace folder",
        "backup": "Independent backup (.zip)",
        "choose": "Choose...",
        "name": "New folder name",
        "prepare": "Prepare verified copy",
        "open": "Open copy in new window",
        "close": "Continue reading",
        "cancel": "Stop",
        "idle": "Start with a coverage check. Nothing will be changed.",
        "checking": "Checking saved research and current PDFs...",
        "working": "Preparing a verified copy...",
        "copying": "Coverage checked; copying research...",
        "pdf": "Verifying current PDFs...",
        "archive": "Creating and verifying the independent backup...",
        "publishing": "Publishing verified outputs...",
        "supported": "Coverage is supported. Choose two new destinations.",
        "blocked": "Preparation is blocked. Resolve the items below, then check again.",
        "failure": (
            "The operation did not complete. Check the coverage and new output paths,"
            " then retry. Your source workspace was not replaced."
        ),
        "changed": "The current workspace changed. Close this window and start again.",
        "snapshot_changed": (
            "Saved research or files changed during preparation. Check the coverage again."
        ),
        "cancelled": "Stopped. Your current workspace was not switched.",
        "stopping": "Stopping at a safe work boundary...",
        "busy": "Wait for current research jobs to finish, then try again.",
        "prepared": (
            "Verified copy and independent backup prepared. Review or open the copy "
            "explicitly; this reader remains on the original workspace."
        ),
        "opened": "Opening the copy in a separate window. This reader and its drafts stay open.",
        "unopened": (
            "Could not open the copy. The prepared files and backup remain available;"
            " retry opening."
        ),
        "paths": "Choose a new absolute workspace path and a separate new backup path.",
        "papers": "Papers",
        "lists": "Lists",
        "notes": "Notes",
        "manual_decks": "Additional saved local decks",
        "retained_decks": "Retained research decks (review before applying)",
        "qa_reviews": "Q&A review history",
        "review_decisions": "Review decision history",
        "pdfs": "Current PDFs",
        "originals": "Retained original PDFs",
        "receipts": "Archived source receipts",
        "excluded": "Private settings excluded",
        "mapping": "PDFs found by the current reader",
        "none": "No current PDFs were found. Any unrepresented files will block preparation.",
        "unsupported": "Items requiring review",
        "review": "Preparation rechecks the current saved data; this is a coverage preview.",
    },
    "zh-TW": {
        "title": "準備工作區副本",
        "intro": "先檢查哪些資料能完整移轉，再建立獨立副本與備份。目前工作區與未存草稿會保留。",
        "scope": "這個流程只準備本機檔案供檢視，不會連線、上傳、核發服務憑證或切換目前閱讀視窗。",
        "source": "目前工作區",
        "coverage": "1. 檢查移轉範圍",
        "check": "檢查內容",
        "outputs": "2. 選擇新的儲存位置",
        "workspace": "新工作區資料夾",
        "backup": "獨立備份 (.zip)",
        "choose": "選擇...",
        "name": "新資料夾名稱",
        "prepare": "建立驗證副本",
        "open": "在新視窗開啟副本",
        "close": "繼續閱讀",
        "cancel": "停止",
        "idle": "先檢查內容，不會改動目前資料。",
        "checking": "正在檢查已存研究資料與 PDF...",
        "working": "正在準備驗證副本...",
        "copying": "範圍已檢查，正在複製研究資料...",
        "pdf": "正在驗證現行 PDF...",
        "archive": "正在建立並驗證獨立備份...",
        "publishing": "正在儲存已驗證的副本...",
        "supported": "目前範圍可完整處理，請選擇兩個新位置。",
        "blocked": "目前無法建立完整副本，請先處理下列項目後重新檢查。",
        "failure": "作業未完成。請檢查移轉範圍與新的儲存路徑後重試；原工作區不會被取代。",
        "changed": "目前工作區已改變，請關閉此視窗後重新開啟。",
        "snapshot_changed": "準備期間的研究資料或檔案已更新，請重新檢查移轉範圍。",
        "cancelled": "已停止，目前工作區並未切換。",
        "stopping": "正在安全作業節點停止...",
        "busy": "請等目前研究作業結束後再試。",
        "prepared": "驗證副本與獨立備份已建立。可自行檢視或開啟副本；此視窗仍使用原工作區。",
        "opened": "正在另一個視窗開啟副本，此閱讀視窗與草稿會保留。",
        "unopened": "副本未能開啟；已建立的副本與備份仍保留，可重試開啟。",
        "paths": "請選擇新的絕對工作區路徑與另一個新備份路徑。",
        "papers": "論文",
        "lists": "清單",
        "notes": "筆記",
        "manual_decks": "另含已存本機簡報",
        "retained_decks": "保留研究簡報（需核對後套用）",
        "qa_reviews": "問答審閱歷史",
        "review_decisions": "審閱決策歷史",
        "pdfs": "現行 PDF",
        "originals": "保留版本原文",
        "receipts": "原文歸檔紀錄",
        "excluded": "排除的私人設定",
        "mapping": "目前閱讀器找到的 PDF",
        "none": "未找到現行 PDF；任何無法表達的檔案都會阻止副本建立。",
        "unsupported": "需要處理的項目",
        "review": "建立前會重新檢查現行已存資料；此處為範圍預覽。",
    },
}


class SourceGuard:
    def __init__(self, database, current_path):
        self.path = _safe_path(database)
        info = self.path.stat()
        self.identity = (info.st_dev, info.st_ino)
        self.current_path = current_path or (lambda: self.path)

    def path_check(self):
        info = _safe_path(self.path).stat()
        if (
            Path(self.current_path()).resolve() != self.path
            or (info.st_dev, info.st_ino) != self.identity
        ):
            raise WorkspaceChanged("The selected research workspace changed")

    def binding(self):
        self.path_check()
        with closing(
            sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=0.025)
        ) as conn:
            return _binding(conn, _tables(conn))

    def check(self, expected):
        if self.binding() != expected:
            raise WorkspaceChanged("The selected research workspace binding changed")


class EnrollmentTicket(Ticket):
    def __init__(self, guard):
        super().__init__()
        self.guard = guard

    def publish(self, action):
        def guarded():
            self.guard()
            action()

        super().publish(guarded)


def current_pdfs(database, ticket, progress):
    """Resolve existing current reader paths in a worker; never guess by title."""
    root = Path(database).parent
    with closing(sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True)) as conn:
        if _tables(conn) & {
            "paperfact_sync_identity",
            "research_sync_binding",
            "research_capture_binding",
        }:
            return {}  # Coverage reports enrollment blockers without materializing source caches.
    reader = from_workspace(database, legacy_root=root / "pdf")
    selected = {}
    last_progress = 0.0
    try:
        with closing(sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True)) as conn:
            rows = conn.execute("SELECT id FROM papers ORDER BY id LIMIT ?", (MAX_ROWS + 1,))
            for index, (paper_id,) in enumerate(rows):
                ticket.check()
                if index >= MAX_ROWS:
                    raise ValueError("Paper inventory exceeds its bounded selection")
                document = reader.resolve(paper_id)
                if document.available and document.path is not None:
                    selected[paper_id] = document.path
                    if len(selected) > MAX_FILES:
                        raise ValueError("PDF inventory exceeds its bounded selection")
                current = time.monotonic()
                if current - last_progress >= 0.1:
                    progress("pdf" if selected else "checking")
                    last_progress = current
        ticket.check()
        return selected
    finally:
        reader.close()


class EnrollmentWorker(QThread):
    stage = Signal(str)

    def __init__(self, task, ticket, parent):
        super().__init__(parent)
        self.task, self.ticket = task, ticket
        self.result = self.error = self.blocked = None

    def run(self):
        try:
            self.result = self.task(self.ticket, self.stage.emit)
        except EnrollmentBlocked as exc:
            self.blocked, self.error = exc.plan, "blocked"
        except Exception as exc:
            self.error = (
                "cancelled"
                if isinstance(exc, Cancelled)
                else "snapshot_changed"
                if isinstance(exc, SnapshotChanged)
                else "changed"
                if isinstance(exc, WorkspaceChanged)
                else "failure"
            )


class EnrollmentDialog(QDialog):
    def __init__(
        self,
        database,
        parent=None,
        *,
        language="zh-TW",
        current_path=None,
        writers_busy=lambda: False,
        open_workspace=None,
        service_factory=EnrollmentService,
        pdf_loader=current_pdfs,
    ):
        super().__init__(parent)
        from paper_daily.workspace_open import open_workspace as launch_workspace

        self.t = COPY.get(language, COPY["en"])
        self.guard = SourceGuard(database, current_path)
        self.service = service_factory(self.guard.path, source_root=self.guard.path.parent)
        self.writers_busy = writers_busy
        self._open_workspace = open_workspace or launch_workspace
        self.pdf_loader = pdf_loader
        self._worker = None
        self._closing = self.disposed = self._invalid = False
        self._binding = self.preview = self.result = None
        self._pdfs = {}
        self._request = self._request_paths = None
        self._opened = False
        self.setWindowTitle(self.t["title"])
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(700, 690)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        for key in ("intro", "scope"):
            label = QLabel(self.t[key])
            label.setWordWrap(True)
            layout.addWidget(label)
        source = QLineEdit(str(self.guard.path.parent))
        source.setReadOnly(True)
        source.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        source.setAccessibleName(self.t["source"])
        layout.addWidget(source)
        coverage = QGroupBox(self.t["coverage"])
        coverage_layout = QVBoxLayout(coverage)
        self.check_button = QPushButton(self.t["check"])
        self.check_button.clicked.connect(self.check_content)
        coverage_layout.addWidget(self.check_button)
        self.coverage = QPlainTextEdit()
        self.coverage.setReadOnly(True)
        self.coverage.setAccessibleName(self.t["coverage"])
        self.coverage.setMinimumHeight(160)
        coverage_layout.addWidget(self.coverage)
        note = QLabel(self.t["review"])
        note.setWordWrap(True)
        coverage_layout.addWidget(note)
        layout.addWidget(coverage)
        outputs = QGroupBox(self.t["outputs"])
        form = QFormLayout(outputs)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.output_path = QLineEdit()
        self.backup_path = QLineEdit()
        self.output_path.setAccessibleName(self.t["workspace"])
        self.backup_path.setAccessibleName(self.t["backup"])
        self.output_button = QPushButton(self.t["choose"])
        self.backup_button = QPushButton(self.t["choose"])
        self.output_button.clicked.connect(self.choose_output)
        self.backup_button.clicked.connect(self.choose_backup)
        for title, edit, button in (
            ("workspace", self.output_path, self.output_button),
            ("backup", self.backup_path, self.backup_button),
        ):
            edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            row.addWidget(button)
            form.addRow(self.t[title], row)
            edit.textChanged.connect(self._paths_changed)
        layout.addWidget(outputs)
        self.prepare_button = QPushButton(self.t["prepare"])
        self.prepare_button.clicked.connect(self.prepare_copy)
        self.open_button = QPushButton(self.t["open"])
        self.open_button.clicked.connect(self.open_copy)
        layout.addWidget(self.prepare_button)
        layout.addWidget(self.open_button)
        layout.addStretch()
        self.status = QLabel(self.t["idle"])
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Enrollment operation status")
        outer.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        outer.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.cancel_button = QPushButton(self.t["cancel"])
        self.cancel_button.clicked.connect(self.cancel)
        self.close_button = QPushButton(self.t["close"])
        self.close_button.clicked.connect(self.close)
        bottom.addWidget(self.cancel_button)
        bottom.addStretch()
        bottom.addWidget(self.close_button)
        outer.addLayout(bottom)
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._check_source)
        self._poll.start()
        self._buttons()

    @property
    def busy(self):
        return self._worker is not None

    def _buttons(self):
        active = not self.busy and not self.disposed and not self._invalid
        self.check_button.setEnabled(active and self.result is None)
        for widget in (self.output_path, self.backup_path, self.output_button, self.backup_button):
            widget.setEnabled(active and self.result is None)
        self.prepare_button.setEnabled(
            active
            and self.result is None
            and bool(self.preview and self.preview["supported"])
            and bool(self.output_path.text().strip() and self.backup_path.text().strip())
        )
        self.open_button.setEnabled(active and self.result is not None and not self._opened)
        self.cancel_button.setEnabled(self.busy)
        self.progress.setVisible(self.busy)

    def _paths_changed(self):
        self._request = self._request_paths = None
        self._buttons()

    def _check_source(self):
        try:
            self.guard.path_check()
            if self._binding is not None:
                self.guard.check(self._binding)
        except (ValueError, OSError, sqlite3.Error):
            self._invalid = True
            if self._worker:
                self._worker.ticket.cancel()
            self.status.setText(self.t["changed"])
            self._buttons()
            return False
        if self.busy and self.writers_busy():
            self._worker.ticket.cancel()
            self.status.setText(self.t["busy"])
        return True

    def _start(self, kind, task):
        if self.busy or self.disposed or self._invalid or not self._check_source():
            return False
        if self.writers_busy():
            self.status.setText(self.t["busy"])
            return False
        try:
            binding = self.guard.binding()
        except (ValueError, OSError, sqlite3.Error):
            self.status.setText(self.t["changed"])
            self._invalid = True
            self._buttons()
            return False
        ticket = EnrollmentTicket(lambda: self.guard.check(binding))

        def run(active, progress):
            self.guard.check(binding)
            result = task(active, progress)
            active.check()
            self.guard.check(binding)
            return result, binding

        worker = EnrollmentWorker(run, ticket, self)
        self._worker = worker
        worker.stage.connect(lambda message, active=worker: self._stage(active, message))
        worker.finished.connect(lambda: self._finished(worker, kind))
        self.status.setText(self.t["checking" if kind == "check" else "working"])
        self._buttons()
        worker.start()
        return True

    def _stage(self, worker, message):
        if (
            self._worker is worker
            and not self._closing
            and not self._invalid
            and not self._worker.ticket.cancelled
        ):
            key = (
                "checking"
                if message == "checking"
                else "pdf"
                if message == "pdf" or message.startswith("Verifying primary PDF")
                else "archive"
                if "backup" in message.lower() or "archive" in message.lower()
                else "publishing"
                if "ready for explicit review" in message
                else "copying"
            )
            self.status.setText(self.t[key])

    def check_content(self):
        if self.busy or self.result is not None:
            return False

        def check(ticket, progress):
            pdfs = self.pdf_loader(self.guard.path, ticket, progress)
            plan = self.service.plan(pdfs=pdfs, ticket=ticket)
            return {"plan": plan, "pdfs": pdfs}

        started = self._start("check", check)
        if started:
            self.preview = None
        return started

    def _show_coverage(self, plan, pdfs):
        counts = plan.get("research_counts", {})
        lines = [f"{self.t[key]}: {counts.get(key, 0):,}" for key in ("papers", "lists", "notes")]
        lines += [
            f"{self.t['pdfs']}: {plan.get('pdf_count', 0):,}",
            f"{self.t['originals']}: {plan.get('original_source_count', 0):,}",
            f"{self.t['receipts']}: {plan.get('archived_source_receipts', 0):,}",
            f"{self.t['excluded']}: {plan.get('excluded_private_kv', 0):,}",
        ]
        archived = plan.get("archived_history_by_protocol", {})
        for label, protocol in (
            ("manual_decks", "research_observed_current_deck_recovery"),
            ("retained_decks", "research_common_deck_proposal_recovery"),
            ("qa_reviews", "research_chat_review_receipts"),
            ("review_decisions", "research_review_receipts"),
        ):
            count = archived.get(protocol, 0)
            if count:
                lines.append(f"{self.t[label]}: {count:,}")
        if plan.get("blockers"):
            lines += ["", self.t["unsupported"], *["- " + item for item in plan["blockers"]]]
        lines += ["", self.t["mapping"]]
        lines += [f"{key}: {Path(value).name}" for key, value in pdfs.items()] or [self.t["none"]]
        self.coverage.setPlainText("\n".join(lines))

    def _finished(self, worker, kind):
        if self._worker is not worker:
            return
        self._worker = None
        if self._check_source() and not self._closing:
            if worker.error:
                if worker.blocked is not None:
                    self.preview = worker.blocked
                    self._show_coverage(self.preview, self._pdfs)
                if worker.error == "snapshot_changed":
                    self.preview = None
                if worker.error == "changed":
                    self._invalid = True
                self.status.setText(self.t[worker.error])
            elif worker.ticket.cancelled:
                self.status.setText(self.t["cancelled"])
            else:
                value, binding = worker.result
                try:
                    self.guard.check(binding)
                except (ValueError, OSError, sqlite3.Error):
                    self._invalid = True
                    self.status.setText(self.t["changed"])
                else:
                    self._binding = binding
                    if kind == "check":
                        self.preview, self._pdfs = value["plan"], value["pdfs"]
                        self._show_coverage(self.preview, self._pdfs)
                        self.status.setText(
                            self.t["supported" if self.preview["supported"] else "blocked"]
                        )
                    else:
                        self.result = value
                        self.status.setText(self.t["prepared"])
        worker.deleteLater()
        self._buttons()
        if self._closing:
            QTimer.singleShot(0, self.close)

    def choose_output(self):
        if self.busy or self.result is not None:
            return
        parent = QFileDialog.getExistingDirectory(self, self.t["workspace"])
        if not parent:
            return
        name, accepted = QInputDialog.getText(
            self, self.t["workspace"], self.t["name"], text="Paperfact-workspace"
        )
        if (
            accepted
            and name
            and name not in {".", ".."}
            and Path(name).name == name
            and "/" not in name
            and "\\" not in name
        ):
            self.output_path.setText(str(Path(parent) / name))
        elif accepted:
            self.status.setText(self.t["paths"])

    def choose_backup(self):
        if self.busy or self.result is not None:
            return
        filename, _filter = QFileDialog.getSaveFileName(
            self, self.t["backup"], "Paperfact-enrollment-backup.zip", "Research backup (*.zip)"
        )
        if filename:
            self.backup_path.setText(filename)

    def prepare_copy(self):
        if (
            self.busy
            or self.result is not None
            or not self.preview
            or not self.preview["supported"]
        ):
            return False
        output, backup = self.output_path.text().strip(), self.backup_path.text().strip()
        if (
            not output
            or not backup
            or not Path(output).is_absolute()
            or not Path(backup).is_absolute()
        ):
            self.status.setText(self.t["paths"])
            return False
        if self._request_paths != (output, backup):
            self._request_paths = (output, backup)
            self._request = str(uuid4())
        request, pdfs = self._request, dict(self._pdfs)
        return self._start(
            "prepare",
            lambda ticket, progress: self.service.prepare(
                output,
                backup_output=backup,
                request_id=request,
                pdfs=pdfs,
                ticket=ticket,
                progress=progress,
            ),
        )

    def open_copy(self):
        if self.busy or self.result is None or self._opened or self._invalid or self.disposed:
            return False
        from paper_daily.workspace_open import WorkspaceDestination

        chosen = WorkspaceDestination(
            Path(self.result["destination"]), Path(self.result["database"])
        )
        self._opened = True
        self._buttons()
        try:
            self._open_workspace(chosen)
        except (OSError, ValueError):
            self._opened = False
            self.status.setText(self.t["unopened"])
            self._buttons()
            return False
        self.status.setText(self.t["opened"])
        return True

    def cancel(self):
        if self._worker:
            self._worker.ticket.cancel()
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
        self._poll.stop()
        self.done(QDialog.DialogCode.Rejected)
        event.accept()
