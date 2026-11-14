"Workspace location, bounded local status and independent recovery actions."

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from paper_daily.workspace_service import (
    Cancelled,
    SnapshotChanged,
    Ticket,
    WorkspaceChanged,
    WorkspaceService,
)

TEXT = {
    "zh-TW": {
        "title": ("工作區與備份"),
        "refresh": ("重新檢查"),
        "folder": ("開啟資料夾"),
        "backup": ("建立完整研究備份…"),
        "inspect": ("檢查備份…"),
        "restore": ("還原到新資料夾…"),
        "close": ("返回閱讀"),
        "cancel": ("取消工作"),
        "loading": ("正在讀取本機狀態…"),
        "snapshot": ("正在建立快照並驗證所有必要附件…"),
        "verify": ("正在驗證備份內容與附件雜湊…"),
        "restore_phase": ("正在新暫存資料夾驗證並重建研究…"),
        "publish": ("驗證完成，正在發布至新位置…"),
        "cancelling": ("已要求取消；目前驗證階段結束後停止，尚未發布的目的地不會建立。"),
        "cancelled": ("已取消；目前工作區未切換。"),
        "changed": ("工作區已變動，請關閉後重新開啟。"),
        "failure": (
            "工作未完成；目的地不會以不完整結果發布。請檢查空間、完整附件及新目的地後重試。"
        ),
        "ready": ("本機資料庫可讀；下列為已提交資料，不包含尚未儲存的編輯。"),
        "local": ("本機模式；未啟用同步。"),
        "unknown_sync": ("同步連線與最後成功時間：目前無可確認資料。"),
        "scope": (
            "完整備份包含研究、歷史與待處理內容；不含 AI／同步登入憑證。舊"
            "式未遷移附件若無法完整驗證，備份會停止。"
        ),
        "restore_note": (
            "還原只建立新的離線工作區；目前資料不覆蓋、不切換，也不啟用舊裝置待傳操作。"
        ),
        "unavailable": (
            "副本與備份僅在本機準備；跨裝置同步需另行設定連線。"
            "尚未提供：搬移使用中的工作區。"
        ),
        "busy": ("請先等候目前背景研究工作完成，再建立備份。"),
        "new_folder": ("新工作區資料夾"),
        "folder_name": ("在選定資料夾內建立的新名稱"),
        "confirm": ("驗證後建立這個新工作區？目前工作區保持不變。"),
        "snapshot_changed": ("研究在備份期間有更新；尚未發布備份，請等候寫入完成後重試。"),
    },
    "en": {
        "title": ("Workspace and recovery"),
        "refresh": ("Refresh"),
        "folder": ("Open folder"),
        "backup": ("Create complete backup…"),
        "inspect": ("Inspect backup…"),
        "restore": ("Restore to new folder…"),
        "close": ("Continue reading"),
        "cancel": ("Cancel task"),
        "loading": ("Reading local status…"),
        "snapshot": ("Taking a snapshot and verifying required attachments…"),
        "verify": ("Verifying backup records and attachment hashes…"),
        "restore_phase": ("Verifying and rebuilding research in a new staging folder…"),
        "publish": ("Verification complete; publishing to the new destination…"),
        "cancelling": (
            "Cancellation requested; waiting "
            "for the current verification sta"
            "ge. Unpublished destinations wil"
            "l not be created."
        ),
        "cancelled": ("Cancelled; the active workspace was not switched."),
        "changed": ("Workspace changed. Close and reopen this window."),
        "failure": (
            "Task did not complete. No partia"
            "l destination is published. Chec"
            "k available space, complete atta"
            "chments and a new destination, t"
            "hen retry."
        ),
        "ready": (
            "Local database is readable. Counts describe committed data, not unsaved editor drafts."
        ),
        "local": ("Local mode; synchronization is not enabled."),
        "unknown_sync": ("Connection and last successful sync: not currently verified."),
        "scope": (
            "Complete backups include researc"
            "h, history and pending work, wit"
            "hout AI or sync credentials. Unm"
            "igrated legacy attachments stop "
            "backup if completeness cannot be"
            " verified."
        ),
        "restore_note": (
            "Restore creates a separate offli"
            "ne workspace. It never overwrite"
            "s or switches the active workspa"
            "ce, or activates the old device'"
            "s outbox."
        ),
        "unavailable": (
            "Copies and backups are prepared locally. Configure a separate connection "
            "for cross-device sync. Not available yet: moving the active workspace."
        ),
        "busy": ("Wait for active background research jobs before creating a backup."),
        "new_folder": ("New workspace folder"),
        "folder_name": ("New folder name inside the selected parent"),
        "confirm": (
            "Create this new workspace after verification? Your active workspace stays unchanged."
        ),
        "snapshot_changed": (
            "Research changed during backup. "
            "Nothing was published; retry aft"
            "er current writes finish."
        ),
    },
}


class WorkspaceWorker(QThread):
    stage = Signal(str)

    def __init__(self, task, ticket, parent):
        super().__init__(parent)
        self.task, self.ticket = task, ticket
        self.result = self.error = None

    def run(self):
        try:
            self.result = self.task(self.ticket, self.stage.emit)
        except Exception as error:
            # No raw provider, path or research exception is sent to the UI.
            self.error = (
                "cancelled"
                if isinstance(error, Cancelled)
                else "snapshot_changed"
                if isinstance(error, SnapshotChanged)
                else "changed"
                if isinstance(error, WorkspaceChanged)
                else "failure"
            )


def _number(value):
    return f"{value['value']:,}" + ("+" if value["capped"] else "")


def _size(value):
    return f"{value / (1024**2):,.1f} MiB"


class WorkspaceDialog(QDialog):
    def __init__(
        self,
        database,
        parent=None,
        *,
        language="zh-TW",
        current_path=None,
        writers_busy=lambda: False,
        open_workspace=None,
        migration_source=None,
    ):
        super().__init__(parent)
        self.t = TEXT.get(language, TEXT["en"])
        self.zh = language == "zh-TW"
        from paper_daily.workspace_primary_migration import MigrationSource, PrimaryMigration

        if migration_source is not None and (
            not isinstance(migration_source, MigrationSource)
            or migration_source.database != Path(database).resolve()
            or not migration_source.workspace_current()
            or (
                getattr(parent, "_workspace_owner", migration_source.owner)
                is not migration_source.owner
            )
        ):
            raise WorkspaceChanged("Original workspace window changed")
        self.service = WorkspaceService(database, current_path=current_path)
        self._primary_controller = (
            PrimaryMigration(self.service, migration_source)
            if migration_source is not None else None
        )
        self._primary_kind = None
        from paper_daily.workspace_open import open_workspace as launch_workspace

        self._open_workspace = open_workspace or launch_workspace
        self.created_destination = None
        self._opened = False
        self.writers_busy = writers_busy
        self._worker = None
        self._closing = self.disposed = self._invalid = False
        self._ready = False
        self.preview = self.package = None
        self.setWindowTitle(self.t["title"])
        self.resize(670, 680)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        outer = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)
        self.location = QLineEdit(str(self.service.path.parent))
        self.location.setReadOnly(True)
        self.location.setAccessibleName("Workspace location")
        layout.addWidget(self.location)
        self.policy = QLabel()
        self.policy.setWordWrap(True)
        layout.addWidget(self.policy)
        actions = QHBoxLayout()
        self.folder_button = QPushButton(self.t["folder"])
        self.folder_button.clicked.connect(self.open_folder)
        self.refresh_button = QPushButton(self.t["refresh"])
        self.refresh_button.clicked.connect(self.refresh)
        actions.addWidget(self.folder_button)
        actions.addWidget(self.refresh_button)
        self.sync_connection_button = QPushButton("同步連線…" if self.zh else "Sync connection…")
        self.sync_connection_button.clicked.connect(self._sync_settings)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addWidget(self.sync_connection_button)
        self.enrollment_button = QPushButton(
            "\u6e96\u5099\u5de5\u4f5c\u5340\u526f\u672c..."
            if self.zh else "Prepare workspace copy..."
        )
        self.enrollment_button.clicked.connect(self._enrollment_settings)
        layout.addWidget(self.enrollment_button)
        self.summary = QLabel(self.t["loading"])
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.summary)
        recovery = QGroupBox("備份與復原" if self.zh else "Backup and recovery")
        group = QVBoxLayout(recovery)
        for key in ("scope", "restore_note"):
            label = QLabel(self.t[key])
            label.setWordWrap(True)
            group.addWidget(label)
        row = QVBoxLayout()
        self.backup_button = QPushButton(self.t["backup"])
        self.backup_button.clicked.connect(self.choose_backup)
        self.inspect_button = QPushButton(self.t["inspect"])
        self.inspect_button.clicked.connect(self.choose_package)
        row.addWidget(self.backup_button)
        row.addWidget(self.inspect_button)
        group.addLayout(row)
        from paper_daily.desktop.primary_migration_review import PrimaryMigrationReview

        self.primary_migration = PrimaryMigrationReview(self, zh=self.zh)
        self.primary_migration.review_requested.connect(self._review_primary)
        self.primary_migration.stage_requested.connect(self._stage_primary)
        self.primary_migration.commit_requested.connect(self._commit_primary)
        group.addWidget(self.primary_migration)
        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        group.addWidget(self.preview_label)
        self.restore_button = QPushButton(self.t["restore"])
        self.restore_button.clicked.connect(self.choose_restore)
        group.addWidget(self.restore_button)
        self.recovery_copy_button = QPushButton(
            "建立可編輯副本…" if self.zh else "Create editable copy…"
        )
        self.recovery_copy_button.setToolTip(
            "選擇已還原的資料庫，檢查後建立獨立副本與備份。"
            if self.zh else "Inspect restored research, then create a separate copy and backup."
        )
        self.recovery_copy_button.clicked.connect(self._recovery_adoption_settings)
        group.addWidget(self.recovery_copy_button)
        from paper_daily.desktop.device_recovery_review import DeviceRecoveryReview

        self.device_review = DeviceRecoveryReview(self)
        group.addWidget(self.device_review)
        self.open_created_button = QPushButton(
            "開啟新工作區視窗" if self.zh else "Open created workspace"
        )
        self.open_created_button.clicked.connect(self.open_created)
        group.addWidget(self.open_created_button)
        layout.addWidget(recovery)
        unavailable = QLabel(self.t["unavailable"])
        unavailable.setWordWrap(True)
        layout.addWidget(unavailable)
        from paper_daily.desktop.workspace_navigation import arrange

        arrange(self, layout, actions, recovery, unavailable)
        self.status = QLabel(self.t["loading"])
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Workspace operation status")
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
        self._poll.timeout.connect(self._check_workspace)
        self._poll.start()
        self._buttons()
        QTimer.singleShot(0, self.refresh)

    @property
    def busy(self):
        child = getattr(self, "_recovery_adoption_dialog", None)
        return self._worker is not None or bool(child and not child.disposed and child.busy)

    def _buttons(self):
        active = not self.busy and not self._invalid and not self.disposed
        self.refresh_button.setEnabled(active)
        self.folder_button.setEnabled(active)
        self.sync_connection_button.setEnabled(active and self._ready)
        self.enrollment_button.setEnabled(active and self._ready)
        self.backup_button.setEnabled(active and self._ready)
        self.inspect_button.setEnabled(active and self._ready)
        self.restore_button.setEnabled(active and self._ready and self.preview is not None)
        self.recovery_copy_button.setEnabled(active and self._ready)
        self.device_review.set_active(active and self._ready)
        self.open_created_button.setEnabled(
            active and self.created_destination is not None and not self._opened
        )
        self.cancel_button.setEnabled(self.busy)
        self.progress.setVisible(self.busy)
        controller = self._primary_controller
        self.primary_migration.set_active(
            bool(active and self._ready and controller is not None and controller.current())
        )
        if self.primary_migration.plan is not None:
            self.backup_button.setEnabled(False)

    def _start(self, kind, task):
        if self.busy or self.disposed or self._invalid:
            return False
        worker = WorkspaceWorker(task, Ticket(), self)
        self._worker = worker
        self.status.setText(self.t["loading"] if kind == "status" else self.t["verify"])
        worker.stage.connect(self._stage)
        worker.finished.connect(lambda: self._finished(worker, kind))
        self._buttons()
        worker.start()
        return True

    def _stage(self, stage):
        if (
            not self._closing
            and not self._invalid
            and self._worker
            and not self._worker.ticket.cancelled
        ):
            self.status.setText(
                self.t.get("restore_phase" if stage == "restore" else stage, self.t["loading"])
            )

    def _finished(self, worker, kind):
        if self._worker is not worker:
            return
        if kind.startswith("primary_"):
            self._finished_primary(worker, kind)
            return
        self._worker = None
        self._check_workspace()
        if not self._invalid and not self._closing:
            if worker.error:
                self.status.setText(self.t[worker.error])
                if worker.error == "changed":
                    self._invalid = True
            elif worker.ticket.cancelled:
                self.status.setText(self.t["cancelled"])
            elif kind == "status":
                self._show_status(worker.result)
            elif kind == "device_review":
                try:
                    self.device_review.deliver(worker.result)
                except (OSError, ValueError):
                    self.status.setText(self.t["changed"])
                    self._invalid = True
            elif kind == "inspect":
                self.preview = worker.result
                self.package = self._inspecting
                rows = sum(item["count"] for item in self.preview["tables"])
                files = len(self.preview["blobs"])
                size = sum(item["size"] for item in self.preview["blobs"])
                self.preview_label.setText(
                    f"{self.package.name}\n"
                    + (
                        f"已驗證 {rows:,} 筆記錄、{files:,} 個附件（{_size(size)}）。"
                        if self.zh
                        else f"Verified {rows:,} records and {files:,} attachments ({_size(size)})."
                    )
                )
                self.status.setText(
                    "可選擇新的還原目的地。" if self.zh else "Choose a new restore destination."
                )
            else:
                message = (
                    "完整備份已建立" if kind == "backup" else "新離線工作區已建立；目前工作區未變更"
                )
                if not self.zh:
                    message = (
                        "Complete backup created"
                        if kind == "backup"
                        else ("New offline workspace created; active workspace unchanged")
                    )
                self.status.setText(message + "\n" + worker.result["path"])
                if kind == "restore":
                    from paper_daily.workspace_open import WorkspaceDestination

                    folder = Path(worker.result["path"])
                    self.created_destination = WorkspaceDestination(folder, folder / "papers.db")
                    self._opened = False
        worker.deleteLater()
        self._buttons()
        if self._closing:
            self.close()

    def _primary_notice(self):
        return (
            "檢查內容已改變；請先重新檢查。尚未建立備份。"
            if self.zh else (
                "Reviewed inputs changed. Refresh before reviewing local PDFs again. "
                "Backup not created."
            )
        )

    def _start_primary(self, kind, task, *, reset=False):
        controller = self._primary_controller
        if self.busy or self.disposed or self._invalid or controller is None:
            return False
        if not controller.current():
            self.status.setText(self._primary_notice())
            return False
        if kind in {"primary_stage", "primary_commit"} and self.writers_busy():
            self.status.setText(self.t["busy"])
            return False
        if reset:
            controller.reset()
        self._primary_kind = kind
        if kind == "primary_ready":
            self._ready = False
        started = self._start(kind, lambda _ticket, _progress: task())
        if not started:
            self._primary_kind = None
        else:
            if kind != "primary_ready":
                self.task_tabs.setCurrentIndex(1)
            labels = {
                "primary_catalog": ("讀取本機 PDF 狀態...", "Reading local PDF status..."),
                "primary_stage": ("檢查並暫存本機 PDF...", "Checking and staging local PDFs..."),
                "primary_commit": ("準備所選 PDF...", "Preparing selected PDFs..."),
                "primary_ready": ("檢查備份準備狀態...", "Reviewing backup readiness..."),
            }
            self.status.setText(labels[kind][0 if self.zh else 1])
        return started

    def _review_primary(self, after=""):
        controller = self._primary_controller
        if controller is None:
            return False
        return self._start_primary(
            "primary_catalog", lambda: controller.catalog(after=after), reset=True
        )

    def _stage_primary(self, selected):
        controller = self._primary_controller
        catalog = self.primary_migration.catalog
        if controller is None or not controller.catalog_current(catalog):
            self.status.setText(self._primary_notice())
            return False
        return self._start_primary(
            "primary_stage", lambda: controller.stage(catalog, selected), reset=True
        )

    def _commit_primary(self):
        if self.busy:
            return False
        controller = self._primary_controller
        plan = self.primary_migration.plan
        if controller is None or not controller.plan_current(plan):
            if controller is not None:
                controller.reset()
                self.primary_migration.clear_plan()
                self._ready = not controller.needs_refresh
                self._buttons()
            self.status.setText(self._primary_notice())
            return False
        return self._start_primary("primary_commit", lambda: controller.commit(plan))

    def _finished_primary(self, worker, kind):
        controller = self._primary_controller
        try:
            self._check_workspace()
            if self._invalid or self._closing:
                return
            if not controller.current():
                self.primary_migration.clear_plan()
                self.status.setText(self._primary_notice())
                return
            if worker.error:
                self.primary_migration.clear_plan()
                self.status.setText(
                    self._primary_notice() if worker.error in {"changed", "snapshot_changed"}
                    else self.t[worker.error]
                )
                if controller.needs_refresh:
                    self._ready = False
            elif kind == "primary_catalog":
                if controller.catalog_current(worker.result):
                    self.primary_migration.show_catalog(worker.result)
                    self.status.setText(
                        "請選擇本機 PDF；不會下載或呼叫 AI。"
                        if self.zh else (
                            "Select local PDFs. This does not download files or call AI."
                        )
                    )
                else:
                    self.status.setText(self._primary_notice())
            elif kind == "primary_stage":
                if controller.plan_current(worker.result):
                    self.primary_migration.show_plan(worker.result)
                    self.status.setText(
                        "請檢閱暫存檔案後確認；尚未建立備份。"
                        if self.zh else "Review staged files, then confirm. Backup not created."
                    )
                else:
                    controller.cancel()
                    self.primary_migration.clear_plan()
                    self._ready = False
                    self.status.setText(self._primary_notice())
            elif kind == "primary_commit":
                self.primary_migration.show_result(worker.result)
                self._ready = False
                self.status.setText(self.primary_migration.summary.text())
            elif kind == "primary_ready":
                self.service, status = worker.result
                self.primary_migration.clear_review()
                self._show_status(status)
        finally:
            # Keep parent busy until the actual queued install/discard drains.
            self._worker = None
            self._primary_kind = None
            worker.deleteLater()
            self._buttons()
            if self._closing:
                self.close()

    def open_created(self):
        if self.busy or self.disposed or self._invalid or self._opened:
            return False
        if self.created_destination is None:
            return False
        self._opened = True
        self._buttons()
        try:
            self._open_workspace(self.created_destination)
        except (OSError, ValueError):
            self._opened = False
            self.status.setText(self.t["failure"])
            self._buttons()
            return False
        self.status.setText(
            "已要求開啟新視窗；此視窗與編輯內容保留。" if self.zh
            else "Opening the created workspace; this window and its drafts stay open."
        )
        return True

    def _adoption_context_current(self):
        if self.disposed or self._invalid or self._closing:
            return False
        try:
            info = self.service.path.stat()
            return (
                Path(self.service.current_path()).resolve() == self.service.path
                and (info.st_dev, info.st_ino) == self.service.identity
            )
        except (OSError, ValueError, TypeError):
            return False

    def _recovery_adoption_settings(self):
        from paper_daily.desktop.recovery_adoption_dialog import RecoveryAdoptionDialog

        existing = getattr(self, "_recovery_adoption_dialog", None)
        if existing is not None and not existing.disposed:
            existing.show()
            existing.raise_()
            return existing
        if self.busy or not self._ready or not self._adoption_context_current():
            return None
        source = self.created_destination.database_path if self.created_destination else None
        dialog = RecoveryAdoptionDialog(
            source, self, language="zh-TW" if self.zh else "en",
            context_current=self._adoption_context_current,
            open_workspace=self._open_workspace,
        )
        self._recovery_adoption_dialog = dialog
        dialog.finished.connect(self._sync_closed)
        dialog.open()
        return dialog

    def _enrollment_settings(self):
        from paper_daily.desktop.enrollment_dialog import EnrollmentDialog

        if self.busy or self.disposed or self._invalid:
            return
        existing = getattr(self, "_enrollment_dialog", None)
        if existing is not None and not existing.disposed:
            existing.show()
            existing.raise_()
            return
        try:
            dialog = EnrollmentDialog(
                self.service.path, self, language="zh-TW" if self.zh else "en",
                current_path=self.service.current_path, writers_busy=self.writers_busy,
                open_workspace=self._open_workspace,
            )
        except (OSError, ValueError):
            self.status.setText(self.t["changed"])
            return
        self._enrollment_dialog = dialog
        dialog.finished.connect(self._sync_closed)
        dialog.open()

    def _sync_settings(self):
        from paper_daily.desktop.sync_connection_dialog import SyncConnectionDialog
        from paper_daily.workspace_sync import SyncSession

        if self.busy or self.disposed or self._invalid:
            return
        existing = getattr(self, "_sync_dialog", None)
        if existing is not None and not existing.disposed:
            existing.show()
            existing.raise_()
            return
        owner = self.parent() or self
        session = getattr(owner, "_workspace_sync_session", None)
        if (session is None or session.workspace.path != self.service.path
                or session.workspace.identity != self.service.identity):
            if session is not None:
                session.disconnect()
            session = SyncSession(self.service.path, current_path=self.service.current_path)
            owner._workspace_sync_session = session
        from paper_daily.desktop.continuous_sync import controller_for
        from paper_daily.desktop.sync_connection_dialog import _background_busy

        automatic = controller_for(owner, session, blocked=lambda: _background_busy(owner))
        dialog = SyncConnectionDialog(session, self, language="zh-TW" if self.zh else "en",
                                      writers_busy=self.writers_busy,
                                      open_workspace=self._open_workspace, automatic=automatic)
        self._sync_dialog = dialog
        dialog.finished.connect(self._sync_closed)
        dialog.open()

    def _sync_closed(self, _result):
        if self._closing:
            QTimer.singleShot(0, self.close)
        elif not self.disposed and not self.busy:
            self.refresh()

    def _show_status(self, result):
        self._ready = True
        policies = {
            "PAPERFACT_DATA": "PAPERFACT_DATA",
            "PAPER_DAILY_DATA": "PAPER_DAILY_DATA (legacy)",
            "installed-default": "安裝版預設" if self.zh else "Installed app default",
            "source-default": "原始碼版 data/" if self.zh else "Source checkout data/",
            "explicit": "明確指定的位置" if self.zh else "Explicit location",
        }
        self.policy.setText(
            ("位置來源：" if self.zh else "Location policy: ") + policies[result["policy"]]
        )
        counts = result["counts"]
        parts = [self.t["ready"]]
        for key, label in (("lists", "清單"), ("papers", "論文"), ("notes", "筆記")):
            if counts[key] is not None:
                parts.append(f"{label if self.zh else key}: {_number(counts[key])}")
        sync = result["sync"]
        self.device_review.enrolled = sync is not None
        if sync is None:
            parts.append(self.t["local"])
        else:
            for key, label in (
                ("pending", "待傳變更"),
                ("awaiting", "已傳送，等待回執"),
                ("conflicts", "待審閱衝突"),
            ):
                parts.append(f"{label if self.zh else key}: {_number(sync[key])}")
            parts.append(self.t["unknown_sync"])
        files = result["files"]
        if files["registered"]:
            checked, verified = files["checked"], _size(files["verified_bytes"])
            unavailable = files["unavailable"]
            if unavailable is None:
                parts.append(
                    "附件儲存區無法驗證；不代表附件已遺失。"
                    if self.zh
                    else ("Attachment storage could not be verified; availability is unknown.")
                )
            else:
                parts.append(
                    (
                        f"本次檢查 {checked} 個管理物件：驗證 {verified}，未就緒 {unavailable}。"
                        if self.zh
                        else f"Managed objects checked: {checked}; verified {verified}; "
                        f"unavailable {unavailable}."
                    )
                    + (
                        ("（部分檢查）" if self.zh else " (partial check)")
                        if files["partial"]
                        else ""
                    )
                )
            parts.append(
                "這不是整個工作區可離線使用的保證。"
                if self.zh
                else ("This is not a whole-workspace offline availability guarantee.")
            )
        else:
            parts.append(
                "尚未登記可驗證的附件儲存區；現有 PDF 是否完整未判定。"
                if self.zh
                else ("No managed attachment store registered; legacy PDF completeness is unknown.")
            )
        parts.append(
            ("可用磁碟空間：" if self.zh else "Free disk space: ") + _size(result["free_bytes"])
        )
        self.summary.setText("\n".join(parts))
        self.status.setText("本機狀態已更新。" if self.zh else "Local status refreshed.")

    def refresh(self):
        controller = self._primary_controller
        if controller is not None and controller.needs_refresh:
            return self._start_primary("primary_ready", controller.refresh_readiness, reset=True)
        return self._start("status", lambda ticket, _progress: self.service.status(ticket))

    def open_folder(self):
        if not self.busy and not self._invalid:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.path.parent)))

    def choose_backup(self):
        if not self._ready or self.busy:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, self.t["backup"], "Paperfact-research-backup.zip", "Research backup (*.zip)"
        )
        if filename:
            self.start_backup(filename)

    def start_backup(self, filename):
        if not self._ready or self.busy or not filename:
            return False
        if self.writers_busy():
            self.status.setText(self.t["busy"])
            return False
        return self._start(
            "backup", lambda ticket, progress: self.service.backup(filename, ticket, progress)
        )

    def choose_package(self):
        if not self._ready or self.busy:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, self.t["inspect"], "", "Research backup (*.zip)"
        )
        if filename:
            self.inspect_package(filename)

    def inspect_package(self, filename):
        if not self._ready or self.busy or not filename:
            return False
        self.preview = self.package = None
        self.preview_label.clear()
        self._inspecting = Path(filename)
        return self._start(
            "inspect", lambda ticket, progress: self.service.inspect(filename, ticket, progress)
        )

    def choose_restore(self):
        if self.preview is None or self.busy:
            return
        parent = QFileDialog.getExistingDirectory(self, self.t["new_folder"])
        if not parent:
            return
        from PySide6.QtWidgets import QInputDialog

        name, accepted = QInputDialog.getText(
            self, self.t["new_folder"], self.t["folder_name"], text="Paperfact-restored"
        )
        if not accepted or not name.strip():
            return
        if name in {".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
            self.status.setText(self.t["failure"])
            return
        destination = Path(parent) / name
        if (
            QMessageBox.question(
                self,
                self.t["new_folder"],
                self.t["confirm"] + "\n" + str(destination),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.start_restore(destination)

    def start_restore(self, destination):
        if (
            self.preview is None
            or self.package is None
            or self.busy
            or not str(destination).strip()
        ):
            return False
        backup_id, package = self.preview["backup_id"], self.package
        return self._start(
            "restore",
            lambda ticket, progress: self.service.restore(
                package, destination, backup_id, ticket, progress
            ),
        )

    def cancel(self):
        if self._worker:
            if self._primary_kind is not None and self._primary_controller is not None:
                self._primary_controller.cancel()
            else:
                self._worker.ticket.cancel()
            self.status.setText(self.t["cancelling"])

    def _check_workspace(self):
        try:
            path = Path(self.service.current_path()).resolve()
            info = self.service.path.stat()
            changed = (
                path != self.service.path or (info.st_dev, info.st_ino) != self.service.identity
            )
        except OSError:
            changed = True
        if changed:
            self._invalid = True
            if self._worker:
                if self._primary_kind is not None and self._primary_controller is not None:
                    self._primary_controller.cancel()
                else:
                    self._worker.ticket.cancel()
            self.status.setText(self.t["changed"])
            self._buttons()

    def reject(self):
        self.close()

    def closeEvent(self, event):
        recovery = getattr(self, "_recovery_adoption_dialog", None)
        if recovery is not None and not recovery.disposed:
            self._closing = True
            if not recovery.close():
                event.ignore()
                return
        connection = getattr(self, "_sync_dialog", None)
        if connection is not None and not connection.disposed:
            self._closing = True
            if not connection.close():
                event.ignore()
                return
        enrollment = getattr(self, "_enrollment_dialog", None)
        if enrollment is not None and not enrollment.disposed:
            self._closing = True
            if not enrollment.close():
                event.ignore()
                return
        if self.busy:
            self._closing = True
            self.cancel()
            event.ignore()
            return
        if self._primary_controller is not None:
            self._primary_controller.dispose()
            self.primary_migration.clear_plan()
        self.disposed = True
        self._poll.stop()
        self.done(QDialog.DialogCode.Rejected)
        event.accept()
