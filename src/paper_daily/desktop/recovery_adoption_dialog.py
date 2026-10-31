"""Explicit inspected recovery copies; source, reader and drafts stay in place."""

from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from paper_daily.desktop.enrollment_dialog import EnrollmentWorker
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.workspace_service import Ticket, WorkspaceChanged, _safe_path

COPY = {
    "en": {
        "title": "Make recovered research editable",
        "intro": "Inspect a restored workspace, then create a separate editable copy and backup.",
        "source": "Restored database",
        "choose": "Choose…",
        "inspect": "Inspect saved content",
        "content": "1 · Inspect the restored research",
        "destinations": "2 · Choose two new destinations",
        "workspace": "Editable workspace folder",
        "backup": "Independent backup (.zip)",
        "folder": "New workspace folder name",
        "prepare": "Create editable copy…",
        "confirm": "Create the inspected research copy and independent backup at these locations?",
        "open": "Open copy in a new window…",
        "confirm_open": "Open the prepared copy in a separate window?",
        "close": "Continue reading",
        "cancel": "Stop",
        "empty": (
            "Choose a database from an already restored backup. Inspection does not modify it."
        ),
        "selected": "Ready to inspect the selected restored database.",
        "checking": "Inspecting research, retained history and exact attachment bytes…",
        "working": "Preparing the independent copy…",
        "files": "Verifying current files and retained original versions…",
        "archive": "Creating and inspecting the independent backup…",
        "publish": "Publishing the verified copy and backup…",
        "stopping": "Stopping at a safe work boundary…",
        "cancelled": "Stopped. You can retry with the selected paths.",
        "supported": "The inspected snapshot can be copied. It is checked again before creation.",
        "next": "Choose two new destinations, then create the copy.",
        "blocked": "This snapshot needs a supported migration before it can become editable.",
        "failure": "The task did not finish. Check the selected source and new paths, then retry.",
        "snapshot_changed": (
            "Saved research changed. Inspect it again; your destination paths remain."
        ),
        "changed": (
            "The selected workspace or reader context changed. Close this window and reopen it."
        ),
        "paths": "Choose two separate, new absolute paths outside the restored workspace.",
        "prepared": (
            "Editable copy and independent backup created. Opening the copy is a separate action."
        ),
        "opening": "Checking and opening the prepared copy in a separate window…",
        "opened": "Requested a new window. This reader and its drafts remain here.",
        "policy": (
            "Your restored source and unsent drafts stay here. "
            "Open the prepared copy only when you choose."
        ),
        "cancel_action": "Cancel",
        "yes": "Create copy",
        "open_yes": "Open new window",
    },
    "zh-TW": {
        "title": "將還原研究建立為可編輯副本",
        "intro": "先檢查已還原的工作區，再建立獨立的可編輯副本與備份。",
        "source": "還原後的資料庫",
        "choose": "選擇…",
        "inspect": "檢查已儲存內容",
        "content": "1 · 檢查還原的研究資料",
        "destinations": "2 · 選擇兩個新位置",
        "workspace": "可編輯工作區資料夾",
        "backup": "獨立備份（.zip）",
        "folder": "新工作區資料夾名稱",
        "prepare": "建立可編輯副本…",
        "confirm": "要在下列位置建立已檢查的研究副本與獨立備份嗎？",
        "open": "在新視窗開啟副本…",
        "confirm_open": "要另外開啟已建立的副本嗎？",
        "close": "返回閱讀",
        "cancel": "停止工作",
        "empty": "請選擇已從備份還原的資料庫。檢查不會修改該資料庫。",
        "selected": "已選擇還原資料庫，可以開始檢查。",
        "checking": "正在檢查研究、保留歷史與附件實體內容…",
        "working": "正在準備獨立副本…",
        "files": "正在驗證現行檔案與保留版本原文…",
        "archive": "正在建立並檢查獨立備份…",
        "publish": "正在發布已驗證的副本與備份…",
        "stopping": "將在安全的工作邊界停止…",
        "cancelled": "已停止，可以沿用選定的位置重試。",
        "supported": "此快照可以完整建立副本。建立前會再次核對內容。",
        "next": "請選擇兩個新位置，再建立副本。",
        "blocked": "此快照仍需要支援的遷移方式，暫時無法建立可編輯副本。",
        "failure": "工作未完成，請檢查來源與新位置後重試。",
        "snapshot_changed": "已儲存的研究內容有變動，請重新檢查。目的地欄位會保留。",
        "changed": "選定工作區或目前閱讀視窗的資料位置已變動，請關閉後重新開啟。",
        "paths": "請選擇兩個新的絕對路徑，且與還原工作區及彼此分開。",
        "prepared": "可編輯副本與獨立備份已建立。開啟副本是另一個獨立操作。",
        "opening": "正在檢查副本並另開視窗…",
        "opened": "已要求開啟新視窗。目前閱讀畫面與草稿會保留。",
        "policy": "還原來源與未送出的草稿會保留。副本完成後，可自行選擇另開閱讀視窗。",
        "cancel_action": "取消",
        "yes": "建立副本",
        "open_yes": "開啟新視窗",
    },
}


class ScopeTicket(Ticket):
    def __init__(self, guard):
        super().__init__()
        self.guard = guard

    def publish(self, action):
        def guarded():
            self.guard()
            action()

        super().publish(guarded)


class RecoveryAdoptionDialog(QDialog):
    def __init__(
        self,
        database=None,
        parent=None,
        *,
        language="zh-TW",
        context_current=lambda: True,
        service_factory=RecoveryAdoptionService,
        open_workspace=None,
    ):
        super().__init__(parent)
        from paper_daily.desktop.settings_style import apply
        from paper_daily.workspace_open import open_workspace as launch_workspace

        self.t = COPY.get(language, COPY["en"])
        self.zh = language == "zh-TW"
        self.context_current, self.service_factory = context_current, service_factory
        self._open_workspace = open_workspace or launch_workspace
        self._worker = self.service = self.inspection = self.result = None
        self._closing = self.disposed = self._invalid = self._opened = self._blocked = False
        self._generation = 0
        self._request = self._request_paths = None
        self._phase, self._started = "", 0.0
        self.setWindowTitle(self.t["title"])
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(690, 610)
        apply(self)
        from paper_daily.desktop.main import palette

        colors = palette()
        self.setStyleSheet(
            self.styleSheet()
            + f"""
            QLineEdit {{ color:{colors["ink"]}; background:{colors["surface"]};
                border:1px solid {colors["firm"]}; border-radius:6px; padding:7px; }}
            QLineEdit:focus, QPushButton:focus {{ border:2px solid {colors["accent"]}; }}
            QLineEdit:disabled {{ color:{colors["muted"]}; background:{colors["sunk"]}; }}
            QScrollArea#recoveryScroll, QWidget#recoveryBody {{
                background:{colors["ground"]}; border:0;
            }}
        """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("recoveryScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("recoveryBody")
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)
        self.scroll.setWidget(body)
        layout.addWidget(self.scroll, 1)
        title = QLabel(self.t["title"])
        title.setProperty("role", "title")
        title.setWordWrap(True)
        content.addWidget(title)
        intro = self._label(self.t["intro"])
        intro.setProperty("role", "muted")
        content.addWidget(intro)
        source = QGroupBox(self.t["content"])
        source_layout = QVBoxLayout(source)
        row = QHBoxLayout()
        self.source_field = QLineEdit()
        self.source_field.setReadOnly(True)
        self.source_field.setAccessibleName(self.t["source"])
        self.source_button = QPushButton(self.t["choose"])
        self.source_button.clicked.connect(self.choose_source)
        row.addWidget(self.source_field, 1)
        row.addWidget(self.source_button)
        source_layout.addLayout(row)
        self.inspect_button = QPushButton(self.t["inspect"])
        self.inspect_button.clicked.connect(self.start_inspection)
        source_layout.addWidget(self.inspect_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.report = self._label(self.t["empty"])
        self.report.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.report.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        source_layout.addWidget(self.report)
        content.addWidget(source)
        destinations = QGroupBox(self.t["destinations"])
        form = QFormLayout(destinations)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.workspace_field, self.backup_field = QLineEdit(), QLineEdit()
        self.workspace_button, self.backup_button = (
            QPushButton(self.t["choose"]),
            QPushButton(self.t["choose"]),
        )
        self.workspace_button.clicked.connect(self.choose_workspace)
        self.backup_button.clicked.connect(self.choose_backup)
        for label, field, button in (
            (self.t["workspace"], self.workspace_field, self.workspace_button),
            (self.t["backup"], self.backup_field, self.backup_button),
        ):
            field.setAccessibleName(label)
            controls = QHBoxLayout()
            controls.addWidget(field, 1)
            controls.addWidget(button)
            form.addRow(label, controls)
            field.textChanged.connect(self._buttons)
        content.addWidget(destinations)
        content.addWidget(self._label(self.t["policy"]))
        content.addStretch()
        self.status = self._label(self.t["empty"])
        self.status.setAccessibleName("Recovery preparation status")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        self.cancel_button = QPushButton(self.t["cancel"])
        self.cancel_button.clicked.connect(self.cancel)
        self.prepare_button = QPushButton(self.t["prepare"])
        self.prepare_button.setProperty("role", "primary")
        self.prepare_button.clicked.connect(self.confirm_prepare)
        self.open_button = QPushButton(self.t["open"])
        self.open_button.clicked.connect(self.confirm_open)
        self.close_button = QPushButton(self.t["close"])
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        actions.addWidget(self.prepare_button)
        actions.addWidget(self.open_button)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        # Layout ownership must be established before enumerating the footer
        # buttons; unparented buttons are not yet returned by findChildren().
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.close_button.setDefault(True)
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._check_context)
        self._poll.start()
        self._elapsed = QTimer(self)
        self._elapsed.setInterval(1000)
        self._elapsed.timeout.connect(self._show_elapsed)
        if database is not None:
            self.set_source(database)
        self._buttons()
        self.source_button.setFocus()

    @staticmethod
    def _label(text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    @property
    def busy(self):
        return self._worker is not None

    def _guard(self, service=None):
        if not self.context_current():
            raise WorkspaceChanged("Reader context changed")
        if service is not None:
            service._check()

    def _check_context(self):
        if self.disposed or self._invalid:
            return False
        try:
            self._guard(self.service)
        except (OSError, ValueError):
            self._invalid = True
            if self._worker:
                self._worker.ticket.cancel()
            self.inspection = self.result = None
            self.status.setText(self.t["changed"])
            self._buttons()
            return False
        return True

    def _buttons(self):
        active = not self.busy and not self.disposed and not self._closing and not self._invalid
        self.source_button.setEnabled(active)
        self.inspect_button.setEnabled(active and self.service is not None and self.result is None)
        for field in (self.workspace_field, self.backup_field):
            field.setEnabled(active and self.result is None)
        for button in (self.workspace_button, self.backup_button):
            button.setEnabled(active and self.result is None)
        self.prepare_button.setEnabled(
            bool(
                active
                and not self._blocked
                and self.result is None
                and self.inspection
                and self.inspection.report.get("supported")
                and self.workspace_field.text().strip()
                and self.backup_field.text().strip()
            )
        )
        self.prepare_button.setVisible(self.result is None)
        self.open_button.setVisible(self.result is not None)
        self.open_button.setEnabled(active and self.result is not None and not self._opened)
        self.cancel_button.setVisible(self.busy)
        self.cancel_button.setEnabled(self.busy and not self._closing)
        self.progress.setVisible(self.busy)

    def choose_source(self):
        if self.busy or self.disposed or self._invalid:
            return False
        name, _ = QFileDialog.getOpenFileName(
            self, self.t["source"], "", "Paperfact database (*.db)"
        )
        return self.set_source(name) if name else False

    def set_source(self, database):
        if (
            self.busy
            or self.disposed
            or self._invalid
            or not isinstance(database, (str, Path))
            or not str(database).strip()
        ):
            return False
        try:
            self._guard()
            path = _safe_path(database)
            service = self.service_factory(path, current_path=lambda: path)
        except (OSError, ValueError):
            self.status.setText(self.t["failure"])
            return False
        self._generation += 1
        self.service, self.inspection, self.result = service, None, None
        self._request = self._request_paths = None
        self._opened = False
        self._blocked = False
        self.source_field.setText(str(path))
        self.report.setText(self.t["selected"])
        self.status.setText(self.t["selected"])
        self._buttons()
        return True

    def _start(self, kind, task):
        if self.busy or self.disposed or self._closing or not self._check_context():
            return False
        service, generation = self.service, self._generation

        def guard():
            if service is not self.service or generation != self._generation:
                raise WorkspaceChanged("Recovered selection changed")
            self._guard(service)

        ticket = ScopeTicket(guard)

        def run(current_ticket, progress):
            guard()
            current_ticket.check()

            def stage(message):
                guard()
                current_ticket.check()
                progress(message)

            result = task(current_ticket, stage)
            current_ticket.check()
            guard()
            return result

        worker = EnrollmentWorker(run, ticket, self)
        self._worker = worker
        self._started = time.monotonic()
        self._phase = self.t[
            "checking" if kind == "inspect" else "opening" if kind == "launch" else "working"
        ]
        self.status.setText(self._phase)
        worker.stage.connect(lambda message: self._worker_stage(worker, generation, message))
        worker.finished.connect(lambda: self._finished(worker, kind, service, generation))
        self._buttons()
        self._elapsed.start()
        worker.start()
        return True

    def _worker_stage(self, worker, generation, message):
        if worker is self._worker and generation == self._generation:
            self._stage(message)

    def _stage(self, message):
        if self._closing or self._invalid or not self._worker or self._worker.ticket.cancelled:
            return
        key = (
            "archive"
            if message.startswith("Creating and inspecting independent")
            else "publish"
            if message.startswith("Verified candidate ready")
            else "files"
            if message.startswith("Verifying")
            else "checking"
            if message.startswith("Inspecting")
            else "working"
        )
        self._phase = self.t[key]
        self._show_elapsed()

    def _show_elapsed(self):
        if (
            self.busy
            and not self._closing
            and not self._invalid
            and not self._worker.ticket.cancelled
        ):
            elapsed = max(0, int(time.monotonic() - self._started))
            self.status.setText(f"{self._phase}  ·  {elapsed // 60:02d}:{elapsed % 60:02d}")

    def start_inspection(self):
        if self.service is None or self.result is not None:
            return False
        service = self.service
        return self._start(
            "inspect", lambda ticket, progress: service.inspect(ticket=ticket, progress=progress)
        )

    def _show_report(self):
        report = self.inspection.report
        counts = report.get("research_counts", {})
        details = [
            f"{label}: {counts.get(key, 0):,}"
            for key, label in (
                ("lists", "清單" if self.zh else "Lists"),
                ("papers", "論文" if self.zh else "Papers"),
                ("notes", "筆記" if self.zh else "Notes"),
            )
        ]
        history = sum(report.get("history_counts", {}).values())
        files = [
            f"{label}: {report.get(key, 0):,}"
            for key, label in (
                ("current_pdf_count", "現行 PDF" if self.zh else "Current PDFs"),
                ("current_deck_count", "可編輯簡報" if self.zh else "Editable decks"),
                ("orphan_papers", "清單外論文" if self.zh else "Unlisted papers"),
            )
        ]
        retained = [("保留歷史" if self.zh else "History records") + f": {history:,}"]
        retained.append(
            ("附件" if self.zh else "Attachments") + f": {report.get('retained_blobs', 0):,}"
        )
        retained.append(f"{report.get('retained_bytes', 0) / (1024**2):,.1f} MiB")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        parts = [
            "  ·  ".join(details),
            "  ·  ".join(files),
            "  ·  ".join(retained),
            ("快照檢查時間：" if self.zh else "Snapshot checked: ") + stamp,
            self.t["supported" if report.get("supported") else "blocked"],
        ]
        if report.get("blockers"):
            # The service owns typed blocker messages; cap display independently.
            parts.extend(self._blocker(item) for item in report["blockers"][:3])
        self.report.setText("\n".join(parts))

    def _blocker(self, value):
        if self.zh and value == "legacy queue pins require migration":
            return "舊版閱讀佇列中的釘選尚需遷移，原始資料會保留。"
        return str(value)[:120]

    def _finished(self, worker, kind, service, generation):
        if self._worker is not worker:
            return
        self._worker = None
        self._elapsed.stop()
        current = (
            service is self.service and generation == self._generation and self._check_context()
        )
        if current and not self._closing:
            if worker.error:
                self.status.setText(self.t[worker.error])
                if worker.error == "blocked":
                    self._blocked = True
                    self.report.setText(
                        self.t["blocked"]
                        + "\n"
                        + "\n".join(
                            self._blocker(item)
                            for item in (worker.blocked or {}).get("blockers", [])[:3]
                        )
                    )
                if worker.error == "snapshot_changed":
                    self.inspection = None
                if worker.error == "changed":
                    self._invalid = True
                    self.inspection = self.result = None
            elif worker.ticket.cancelled:
                self.status.setText(self.t["cancelled"])
            elif kind == "inspect":
                self.inspection = worker.result
                self._blocked = False
                self._show_report()
                self.status.setText(
                    self.t["next" if self.inspection.report.get("supported") else "blocked"]
                )
            elif kind == "prepare":
                self.result = worker.result
                self.status.setText(self.t["prepared"])
            elif kind == "launch":
                self._opened = True
                self.status.setText(self.t["opened"])
        worker.deleteLater()
        self._buttons()
        if self._closing:
            self.close()

    def choose_workspace(self):
        if self.busy or self.disposed or self._invalid or self.result is not None:
            return
        parent = QFileDialog.getExistingDirectory(self, self.t["workspace"])
        if not parent:
            return
        name, accepted = QInputDialog.getText(
            self, self.t["folder"], self.t["folder"], text="Paperfact-editable"
        )
        if accepted and name.strip() and Path(name).name == name and name not in {".", ".."}:
            self.workspace_field.setText(str(Path(parent) / name))

    def choose_backup(self):
        if self.busy or self.disposed or self._invalid or self.result is not None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self.t["backup"], "Paperfact-recovered-backup.zip", "Research backup (*.zip)"
        )
        if path:
            self.backup_field.setText(path)

    def _destinations(self):
        workspace, backup = self.workspace_field.text().strip(), self.backup_field.text().strip()
        if (
            not workspace
            or not backup
            or not Path(workspace).is_absolute()
            or not Path(backup).is_absolute()
        ):
            raise ValueError("New absolute paths are required")
        workspace, backup = _safe_path(workspace), _safe_path(backup)
        source = self.service.database.parent
        if (
            workspace.exists()
            or backup.exists()
            or not workspace.parent.is_dir()
            or not backup.parent.is_dir()
            or workspace == backup
            or workspace.is_relative_to(source)
            or source.is_relative_to(workspace)
            or backup.is_relative_to(source)
            or source.is_relative_to(backup)
            or backup.is_relative_to(workspace)
            or workspace.is_relative_to(backup)
        ):
            raise ValueError("Independent new destinations are required")
        return workspace, backup

    def _confirm(self, message, yes):
        box = QMessageBox(
            QMessageBox.Icon.Question,
            self.t["title"],
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            self,
        )
        box.button(QMessageBox.StandardButton.Yes).setText(yes)
        box.button(QMessageBox.StandardButton.Cancel).setText(self.t["cancel_action"])
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)
        box.setTextFormat(Qt.TextFormat.PlainText)
        return box.exec() == QMessageBox.StandardButton.Yes

    def confirm_prepare(self):
        if (
            self.busy
            or self._blocked
            or self.result is not None
            or self.inspection is None
            or not self._check_context()
        ):
            return False
        if not self.inspection.report.get("supported"):
            return False
        try:
            workspace, backup = self._destinations()
        except (OSError, ValueError):
            self.status.setText(self.t["paths"])
            return False
        service, generation, inspection = self.service, self._generation, self.inspection
        if not self._confirm(f"{self.t['confirm']}\n\n{workspace}\n{backup}", self.t["yes"]):
            return False
        if not self._check_context():
            return False
        if (
            service is not self.service
            or generation != self._generation
            or inspection is not self.inspection
        ):
            return False
        try:
            if self._destinations() != (workspace, backup):
                return False
        except (OSError, ValueError):
            self.status.setText(self.t["paths"])
            return False
        paths = (workspace, backup)
        if self._request_paths != paths:
            self._request, self._request_paths = str(uuid4()), paths
        request = self._request
        return self._start(
            "prepare",
            lambda ticket, progress: service.prepare(
                inspection,
                workspace,
                backup_output=backup,
                request_id=request,
                ticket=ticket,
                progress=progress,
            ),
        )

    def confirm_open(self):
        if self.busy or self.result is None or self._opened or not self._check_context():
            return False
        result, service, generation = self.result, self.service, self._generation
        if not self._confirm(self.t["confirm_open"], self.t["open_yes"]):
            return False
        if not self._check_context():
            return False
        if (
            result is not self.result
            or service is not self.service
            or generation != self._generation
        ):
            return False
        from paper_daily.workspace_open import WorkspaceDestination

        destination = WorkspaceDestination(Path(result["destination"]), Path(result["database"]))

        def launch(ticket, _progress):
            checked = destination.checked()
            ticket.publish(lambda: self._open_workspace(checked))
            return True

        return self._start("launch", launch)

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
            self._buttons()
            event.ignore()
            return
        self.disposed = True
        self._poll.stop()
        self._elapsed.stop()
        self.done(QDialog.DialogCode.Rejected)
        event.accept()
