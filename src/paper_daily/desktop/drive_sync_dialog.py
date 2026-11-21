"""Simple personal Drive enrollment, with the existing server dialog under Advanced."""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from paper_daily.drive_sync_setup import DriveSetup
from paper_daily.workspace_open import WorkspaceDestination, open_workspace


class DriveSyncDialog(QDialog):
    def __init__(
        self,
        session,
        parent=None,
        *,
        language="zh-TW",
        automatic=None,
        writers_busy=lambda: False,
        open_workspace=open_workspace,
        service_factory=DriveSetup,
        owner=None,
    ):
        super().__init__(parent)
        self.session, self.automatic = session, automatic
        self.owner = owner or (automatic.parent() if automatic is not None else parent)
        from paper_daily.desktop.saved_list_sync import for_window

        self.background = for_window(self.owner or self)
        self.writers_busy, self.open_workspace = writers_busy, open_workspace
        self.service = service_factory(
            session.workspace.path, current_path=session.workspace.current_path
        )
        self.disposed = self._closing = False
        self._worker = None
        self._resume_pending = False
        self.zh = language == "zh-TW"
        self.language = language
        self.setWindowTitle(self.tr("Personal Drive sync", "個人 Drive 同步"))
        self.resize(540, 440)
        layout = QVBoxLayout(self)
        intro = QLabel(
            self.tr(
                "Use the same Google account on your desktop and laptop. "
                "Research stays on each device; "
                "Enable sync to keep a private copy in your own Drive. "
                "Sharing lists is separate.",
                "桌機與筆電登入同一個 Google 帳號。啟用同步"
                "後，研究資料會保存在各裝置與你自己的私人 Driv"
                "e；分享清單是另一個操作。",
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.account = QLabel(self.tr("Not connected to Google", "尚未連接 Google"))
        layout.addWidget(self.account)
        self.login = QPushButton(
            self.tr(
                "Sign in / switch Google account",
                "登入／切換 Google 帳號",
            )
        )
        self.login.clicked.connect(self.sign_in)
        layout.addWidget(self.login)
        self.directory_lists = QListWidget()
        self.directory_lists.setAccessibleName(self.tr("Lists on this device", "這台裝置的清單"))
        self.directory_lists.setVisible(False)
        layout.addWidget(self.directory_lists)
        self.save_selection = QPushButton(
            self.tr("Save this device's list selection", "儲存這台裝置的清單選擇")
        )
        self.save_selection.setVisible(False)
        self.save_selection.clicked.connect(self._save_selection)
        layout.addWidget(self.save_selection)
        self._saved_ids = set()
        self.sync_lists = QPushButton(self.tr("Sync saved lists now", "立即同步已勾選清單"))
        self.sync_lists.hide()
        self.sync_lists.clicked.connect(self._sync_saved)
        self.directory_lists.itemChanged.connect(self._list_buttons)
        layout.addWidget(self.sync_lists)
        self.keep_syncing = QPushButton(
            self.tr("Sync saved lists while Paperfact is open", "本次開啟期間自動同步已勾選清單")
        )
        self.keep_syncing.setCheckable(True)
        self.keep_syncing.clicked.connect(self._background_clicked)
        layout.addWidget(self.keep_syncing)
        self._ordinary_library = False
        self._note_lists = set()
        self.notes_toggle = QPushButton(self.tr("Sync notes for this list", "同步這份清單的筆記"))
        self.notes_toggle.setCheckable(True)
        self.notes_toggle.clicked.connect(self._choose_notes)
        layout.addWidget(self.notes_toggle)
        self._pdf_lists = set()
        self.pdf_toggle = QPushButton(self.tr("Allow PDF sync for this list",
                                              "允許同步這份清單的 PDF"))
        self.pdf_toggle.setCheckable(True)
        self.pdf_toggle.clicked.connect(self._choose_pdfs)
        self._dive_lists = set()
        self.dive_toggle = QPushButton(self.tr("Sync saved explanations", "同步已儲存的深度講解"))
        self.dive_toggle.setCheckable(True)
        self.dive_toggle.clicked.connect(self._choose_dives)
        content_row = QHBoxLayout()
        content_row.addWidget(self.pdf_toggle)
        content_row.addWidget(self.dive_toggle)
        layout.addLayout(content_row)
        self.compare_notes = QPushButton(self.tr("Compare conflicting notes", "比較衝突筆記"))
        self.compare_notes.clicked.connect(self._review_notes)
        layout.addWidget(self.compare_notes)
        self.compare_dives = QPushButton(self.tr("Compare conflicting guides", "比較衝突講解"))
        self.compare_dives.clicked.connect(lambda: self._review_notes(feature="dive"))
        layout.addWidget(self.compare_dives)
        self.directory_lists.currentRowChanged.connect(self._list_buttons)
        self.background.changed.connect(self._background_changed)
        self.pilot = QPushButton(self.tr("Existing workspace sync", "既有工作區同步"))
        self.pilot.setCheckable(True)
        self.pilot.hide()
        self.pilot.toggled.connect(self._show_pilot)
        layout.addWidget(self.pilot)
        self.name = QLineEdit(self.tr("My research", "我的研究"))
        self.name.setMaxLength(200)
        layout.addWidget(self.name)
        self.scope_label = QLabel(self.tr("Lists for the new sync copy", "選擇要同步的清單"))
        self.scope_label.setVisible(False)
        layout.addWidget(self.scope_label)
        self.lists = QListWidget()
        self.lists.setMaximumHeight(112)
        self.lists.setVisible(False)
        layout.addWidget(self.lists)
        self.create = QPushButton(self.tr("Sync this workspace", "同步這個工作區"))
        self.create.setProperty("role", "primary")
        self.create.clicked.connect(self.create_workspace)
        layout.addWidget(self.create)
        self.workspaces = QComboBox()
        layout.addWidget(self.workspaces)
        self.join = QPushButton(
            self.tr(
                "Open selected Drive workspace",
                "開啟選取的 Drive 工作區",
            )
        )
        self.join.clicked.connect(self.join_workspace)
        layout.addWidget(self.join)
        self.auto = QPushButton(self.tr("Automatic sync", "自動同步"))
        self.auto.setCheckable(True)
        self.auto.setChecked(bool(automatic and automatic.enabled))
        self.auto.clicked.connect(self.toggle_automatic)
        layout.addWidget(self.auto)
        self.status = QLabel(
            self.tr(
                "Sign in to create or open a workspace.",
                "登入後即可建立或開啟同步工作區。",
            )
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        self.advanced = QPushButton(self.tr("Advanced: self-hosted service", "進階：自架服務"))
        self.advanced.clicked.connect(self.open_advanced)
        row.addWidget(self.advanced)
        self.stop = QPushButton(self.tr("Stop", "停止"))
        self.stop.clicked.connect(self.cancel)
        row.addWidget(self.stop)
        self.done_button = QPushButton(self.tr("Continue reading", "繼續閱讀"))
        self.done_button.clicked.connect(self.close)
        row.addWidget(self.done_button)
        layout.addLayout(row)
        factory = getattr(session, "_factory", None)
        authority = getattr(factory, "authority", None)
        if authority is not None:
            self.service.files = authority.files
            self.service.account = authority.account
            self.account.setText(authority.account["email"])
        active = self.background.service
        if (authority is None and active is not None
                and active.workspace.path == session.workspace.path
                and active.workspace.identity == session.workspace.identity
                and active.binding.current() and active.files is self.background.files):
            self.service = active
            self.account.setText(active.account["email"])
            self._resume_pending = True
            QTimer.singleShot(0, self._resume_directory)
        if self.automatic is not None:
            self.automatic.changed.connect(self._automatic_changed)
        self._buttons()

    def _resume_directory(self):
        if not self._resume_pending or self.disposed or self._closing:
            return
        if self.background.worker is not None:
            return
        self._resume_pending = False
        if (self.background.service is self.service and self.service.binding.current()
                and self.background.files is self.service.files):
            self._start("refresh", self.service.overview)

    def _automatic_changed(self, value):
        if self.disposed or self._closing or self.busy:
            return
        self.auto.setChecked(bool(value["enabled"]))
        self._buttons()

    def tr(self, en, zh):
        return zh if self.zh else en

    @property
    def busy(self):
        child = getattr(self, "_advanced_dialog", None)
        return self._worker is not None or (child is not None and not child.disposed and child.busy)

    def _buttons(self):
        idle = not self.busy and not self._closing and self.background.worker is None
        self.login.setEnabled(idle)
        self.create.setEnabled(idle and self.service.files is not None)
        self.join.setEnabled(idle and self.workspaces.count() > 0)
        self.auto.setEnabled(idle and self.session.summary()["authenticated"])
        self.advanced.setEnabled(idle)
        self.name.setEnabled(idle)
        self.workspaces.setEnabled(idle)
        self.lists.setEnabled(idle)
        self.directory_lists.setEnabled(idle)
        self.save_selection.setEnabled(idle and self.service.files is not None)
        self._list_buttons()
        self.stop.setEnabled(self.busy)
        self.progress.setVisible(self.busy)
        self.progress.setRange(0, 0 if self.busy else 1)

    def _start(self, kind, task):
        if self.busy or self._closing or self.disposed:
            return False
        from paper_daily.desktop.sync_connection_dialog import SyncWorker

        try:
            self.service.binding._check()
        except (OSError, ValueError):
            return False
        if self.background.worker is not None:
            return False
        self._resume_pending = False
        if kind in {"login", "create", "join", "toggle"} and self.background.service is not None:
            self.background.stop()
        if kind not in {"login", "refresh", "toggle", "selection", "sync_saved", "notes",
                        "compare", "resolve", "pdfs", "dives"}:
            if self.writers_busy():
                self.status.setText(
                    self.tr(
                        "Wait for the current research job to finish.",
                        "請先等目前的研究工作完成。",
                    )
                )
                return False
            if self.automatic:
                self.automatic.stop()
                if self.automatic.busy:
                    return False
        worker = SyncWorker(task, self)
        self._worker = worker
        worker.progress.connect(self._progress)
        worker.finished.connect(lambda: self._finished(worker, kind))
        self.status.setText(
            self.tr(
                "Working; you can stop safely.",
                "正在處理，可安全停止。",
            )
        )
        self._buttons()
        worker.start()
        return True

    def _progress(self, value):
        if self._closing:
            return
        if isinstance(value, dict) and value.get("stage") == "selected_lists":
            current, total = value["completed"] + 1, value["total"]
            self.status.setText(self.tr(f"Syncing list {current} of {total}…",
                                        f"正在同步第 {current} 份清單，共 {total} 份…"))
        elif isinstance(value, dict) and "received" in value:
            self.status.setText(
                self.tr(
                    "Receiving research records: ",
                    "正在接收研究紀錄：",
                )
                + str(value.get("cursor", value["received"]))
            )
        else:
            self.status.setText(
                self.tr(
                    "Connecting / preparing saved research and files...",
                    "正在連接或準備已儲存的研究與檔案…",
                )
            )

    def _show_pilot(self, expanded):
        for widget in (self.name, self.create, self.workspaces, self.join):
            widget.setVisible(expanded)
        show_scope = expanded and self.lists.count() > 0
        self.scope_label.setVisible(show_scope)
        self.lists.setVisible(show_scope)

    def _show_directory(self, library):
        previous = self.directory_lists.currentItem()
        current_id = previous.data(Qt.ItemDataRole.UserRole) if previous else None
        self._ordinary_library = library.get("ordinary", False)
        self._note_lists = set(library.get("note_lists", ()))
        self._pdf_lists = set(library.get("pdf_lists", ()))
        self._dive_lists = set(library.get("dive_lists", ()))
        self.directory_lists.clear()
        for row in library["items"]:
            reason = library.get("reviews", {}).get(row["id"])
            label = row["name"]
            if reason:
                label += self.tr(" — needs review", " — 需核對")
            item = QListWidgetItem(label)
            if reason:
                item.setToolTip(reason)
                item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, reason)
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            item.setCheckState(
                Qt.CheckState.Checked if row["selected"] else Qt.CheckState.Unchecked
            )
            self.directory_lists.addItem(item)
            if row["id"] == current_id:
                self.directory_lists.setCurrentItem(item)
        if self.directory_lists.currentRow() < 0 and self.directory_lists.count():
            self.directory_lists.setCurrentRow(0)
        self.directory_lists.setVisible(True)
        self.save_selection.setVisible(True)
        self._saved_ids = {row["id"] for row in library["items"] if row["selected"]}
        self.sync_lists.setVisible(True)
        self._list_buttons()

    def _list_buttons(self):
        if self.disposed or self._closing:
            return
        checked = {
            self.directory_lists.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.directory_lists.count())
            if self.directory_lists.item(i).checkState() == Qt.CheckState.Checked
        }
        self.sync_lists.setEnabled(
            bool(self._saved_ids) and checked == self._saved_ids and self.service.files is not None
            and not self._closing and not self.busy and self.background.worker is None
        )
        current = self.directory_lists.currentItem()
        list_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.notes_toggle.setVisible(self._ordinary_library and list_id in self._saved_ids)
        self.notes_toggle.setChecked(list_id in self._note_lists)
        self.notes_toggle.setEnabled(self.sync_lists.isEnabled())
        self.pdf_toggle.setVisible(self._ordinary_library and list_id in self._saved_ids)
        self.pdf_toggle.setChecked(list_id in self._pdf_lists)
        self.pdf_toggle.setEnabled(self.sync_lists.isEnabled())
        self.dive_toggle.setVisible(self._ordinary_library and list_id in self._saved_ids)
        self.dive_toggle.setChecked(list_id in self._dive_lists)
        self.dive_toggle.setEnabled(self.sync_lists.isEnabled())
        self.compare_notes.setVisible(self._ordinary_library and list_id in self._note_lists)
        self.compare_notes.setEnabled(self.sync_lists.isEnabled())
        self.compare_dives.setVisible(self._ordinary_library and list_id in self._dive_lists)
        self.compare_dives.setEnabled(self.sync_lists.isEnabled())
        active = self.background.service is not None
        self.keep_syncing.setVisible(active or self._ordinary_library)
        self.keep_syncing.setChecked(active)
        self.keep_syncing.setEnabled(
            active or (self._ordinary_library and self.sync_lists.isEnabled())
        )

    def _review_notes(self, *, feature="note"):
        item = self.directory_lists.currentItem()
        if item is None or not self.sync_lists.isEnabled():
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        self._start("compare", lambda ticket, progress: self.service.review_notes(
            key, ticket, progress, feature=feature))

    def _show_note_review(self, cards):
        if not cards:
            self.status.setText(self.tr("No conflicting edits in this list.",
                                        "這份清單目前沒有需要比對的版本。"))
            return
        from paper_daily.desktop.drive_note_compare import NoteComparison

        dialog = NoteComparison(cards, self)
        try:
            if dialog.exec() and dialog.decision:
                card, choice = dialog.decision
                self._start("resolve", lambda ticket, progress: self.service.review_notes(
                    card["list_id"], ticket, progress, decision=(card, choice),
                    feature=card.get("feature", "note")))
            else:
                self.status.setText(self.tr("Both versions retained.", "已保留兩個版本。"))
        finally:
            dialog.deleteLater()

    def _choose_dives(self, checked):
        item = self.directory_lists.currentItem()
        if item is None or not self.dive_toggle.isEnabled():
            self._list_buttons()
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if checked and QMessageBox.question(
            self, self.windowTitle(),
            self.tr("Exchange saved explanation text through private Drive? Update all devices "
                    "before the first transfer upgrades the directory to v6.",
                    "透過私人 Drive 同步這份清單已儲存的深度講解文字？"
                    "首次傳送會升級目錄至 v6，請先更新所有裝置。"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            self._list_buttons()
            return
        self._start("dives", lambda ticket, progress:
                    self.service.choose_dive_sync(key, checked, ticket, progress))

    def _choose_pdfs(self, checked):
        item = self.directory_lists.currentItem()
        if item is None or not self.pdf_toggle.isEnabled():
            self._list_buttons()
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if checked and QMessageBox.question(
            self, self.windowTitle(),
            self.tr("Allow this device to upload and download originals for this list through "
                    "your private Drive? Update both devices before enabling PDF sync.",
                    "允許透過私人 Drive 同步這份清單的原文？"
                    "請先將兩台裝置更新到支援 PDF 同步的版本。"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            self._list_buttons()
            return
        self._start("pdfs", lambda ticket, progress:
                    self.service.choose_pdf_sync(key, checked, ticket, progress))

    def _choose_notes(self, checked):
        item = self.directory_lists.currentItem()
        if item is None or not self.notes_toggle.isEnabled():
            self._list_buttons()
            return
        list_id = item.data(Qt.ItemDataRole.UserRole)
        if checked and QMessageBox.question(
            self, self.windowTitle(),
            self.tr("Sync new and edited paper notes for this list through your private Drive? "
                    "Enable it on both devices. Older builds cannot read the upgraded directory.",
                    "透過私人 Drive 同步這份清單新增與修改的論文筆記？請在兩台裝置啟用。"
                    "首次傳送筆記後，舊版無法讀取升級後的清單目錄。"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            self._list_buttons()
            return
        self._start("notes", lambda ticket, progress:
                    self.service.choose_note_sync(list_id, checked, ticket, progress))

    def _background_clicked(self, checked):
        if checked:
            self.background.enable(self.service)
        else:
            self.background.stop()
        self._buttons()

    def _background_changed(self):
        if not self.disposed:
            self._resume_directory()
            self._buttons()
            if self.background.state == "note_conflict":
                self.status.setText(self.tr("Some notes need review. Other notes continue syncing.",
                                            "部分筆記需核對，其他筆記會繼續同步。"))
            elif self.background.state == "dive_conflict":
                self.status.setText(self.tr("Guides differ. Other content keeps syncing.",
                                            "講解版本需核對，其他內容持續同步。"))
            elif self.background.state == "review":
                self.status.setText(self.tr(
                    "Sync paused. Check the connection and sync saved lists to review.",
                    "同步已暫停。請檢查連線並立即同步以核對清單。",
                ))

    def _sync_saved(self):
        if self.sync_lists.isEnabled() and self.sync_lists.isVisible():
            self._start("sync_saved", self.service.sync_saved_library)

    def _save_selection(self):
        if self.busy or self.service.files is None or not self.directory_lists.isVisible():
            return False
        selected = [
            self.directory_lists.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.directory_lists.count())
            if self.directory_lists.item(i).checkState() == Qt.CheckState.Checked
        ]
        consent = QMessageBox.question(
            self,
            self.windowTitle(),
            self.tr(
                "Publish local list names to your private Drive and save this device's selection?",
                "要將本機清單名稱發佈到私人 Drive，並儲存這台裝置的勾選嗎？",
            ) + ("\n\n" + self.tr(
                "Selected lists exchange their bibliography and list details. For notes, PDFs "
                "and saved explanations, enable each type for the list on both devices.",
                "已勾選的清單會交換書目與清單資訊。若要同步筆記、PDF 或深度講解，"
                "請在兩台裝置上為該清單開啟對應選項。",
            ) if self._ordinary_library else ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if consent != QMessageBox.StandardButton.Yes:
            return False
        return self._start(
            "selection",
            lambda ticket, progress: self.service.apply_library(selected, ticket, progress),
        )

    def sign_in(self):
        return self._start("login", self.service.sign_in)

    def _confirm(self):
        return (
            QMessageBox.question(
                self,
                self.windowTitle(),
                self.tr(
                    "Enable continuous sync to this account's private Drive? "
                    "On this device, the app will "
                    "remember Google authorization in the system credential store "
                    "and reconnect on launch. "
                    "Existing research is copied with a backup if it needs first enrollment.",
                    "啟用此帳號的私人 Drive 持續同步？此裝置會將"
                    " Google 授權存在系統憑證庫，並在開啟 ap"
                    "p 時重新連線。首次啟用的既有資料會先建立副本與備"
                    "份。",
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def create_workspace(self):
        if self.busy or self.service.files is None or not self.name.text().strip():
            return False
        name = self.name.text().strip()
        selected = [
            self.lists.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.lists.count())
            if self.lists.item(i).checkState() == Qt.CheckState.Checked
        ]
        if self.lists.count() and not selected:
            self.status.setText(self.tr("Select at least one list.", "請至少選擇一個清單。"))
            return False

        if not self._confirm():
            return False

        def create(ticket, progress):
            from paper_daily.desktop.enrollment_dialog import current_pdfs

            pdfs = None if selected else current_pdfs(self.session.workspace.path, ticket, progress)
            return self.service.create(name, ticket, progress, pdfs=pdfs, list_ids=selected or None)

        return self._start("create", create)

    def join_workspace(self):
        spec = self.workspaces.currentData()
        if self.busy or spec is None or not self._confirm():
            return False
        return self._start(
            "join", lambda ticket, progress: self.service.join(spec, ticket, progress)
        )

    def _finished(self, worker, kind):
        if worker is not self._worker:
            return
        self._worker = None
        current = (
            self.service.binding.current() and not self._closing and not worker.ticket.cancelled
        )
        if current and not worker.error:
            result = worker.result
            if kind in {"login", "refresh"}:
                self.account.setText(result["account"]["email"])
                if "library" in result:
                    self._show_directory(result["library"])
                self.workspaces.clear()
                self.lists.clear()
                available = result.get("lists", [])
                active = getattr(self.owner, "active_list", None)
                for index, row in enumerate(available):
                    item = QListWidgetItem(row["name"])
                    item.setData(Qt.ItemDataRole.UserRole, row["id"])
                    item.setCheckState(
                        Qt.CheckState.Checked
                        if row["id"] == active or (active is None and index == 0)
                        else Qt.CheckState.Unchecked
                    )
                    self.lists.addItem(item)
                from paper_daily.workspace_sync import local_binding

                show_scope = bool(available) and local_binding(self.session.workspace.path) is None
                self.lists.setVisible(show_scope)
                self.scope_label.setVisible(show_scope)
                if not show_scope:
                    self.lists.clear()
                for spec in result["workspaces"]:
                    self.workspaces.addItem(spec["name"], spec)
                if "library" in result:
                    self.pilot.show()
                    self._show_pilot(self.pilot.isChecked())
                self.status.setText(
                    self.tr(
                        "Select the lists for this device and save your selection.",
                        "勾選要在這台裝置同步的清單，再儲存選擇。",
                    ) if self._ordinary_library else self.tr(
                        "Choose this workspace or open one from Drive.",
                        "可同步目前工作區，或開啟 Drive 上的工作區。",
                    )
                )
            elif kind == "compare":
                self._show_note_review(result)
            elif kind == "resolve":
                self.status.setText(self.tr("Choice saved. Sync to exchange the selected version.",
                                            "已儲存選擇，下次同步時會交換選定的版本。"))
            elif kind == "dives":
                self._show_directory(result)
                self.status.setText(self.tr("Explanation sync preference saved.",
                                            "已儲存深度講解同步設定。"))
            elif kind == "pdfs":
                self._show_directory(result)
                self.status.setText(self.tr("PDF preference saved for the next list sync.",
                                            "已儲存 PDF 設定，下次同步清單時生效。"))
            elif kind == "notes":
                self._show_directory(result)
                self.status.setText(self.tr("Note preference saved for the next sync.",
                                            "已儲存筆記設定，下次同步時生效。"))
            elif kind == "sync_saved":
                self._show_directory(result)
                self.status.setText(
                    self.tr("Review the marked lists.", "請核對標示的清單。")
                    if result.get("reviews")
                    else self.tr("Saved lists synced.", "已同步勾選的清單。")
                )
            elif kind == "selection":
                self._show_directory(result)
                if not self._saved_ids and self.background.service is self.service:
                    self.background.stop()
                self.status.setText(
                    self.tr(
                        "Device selection saved.", "已儲存這台裝置的清單選擇。"
                    )
                )
                if result.get("reviews"):
                    self.status.setText(self.tr(
                        "Selection saved. Review the marked lists.",
                        "已儲存勾選。請核對標示的清單。",
                    ))
            elif kind == "toggle":
                enabled = result["enabled"]
                if enabled:
                    self.automatic.enable()
                self.auto.setChecked(enabled)
                self.status.setText("Automatic Drive sync " + ("on" if enabled else "off"))
            elif result["copied"]:
                from paper_daily.workspace_preferences import remember_workspace

                database = Path(result["database"])
                try:
                    remember_workspace(database.parent)
                except (OSError, ValueError):
                    self.status.setText("Workspace prepared; open " + str(database.parent))
                    worker.deleteLater()
                    self._buttons()
                    return
                try:
                    self.open_workspace(WorkspaceDestination(database.parent, database))
                except (OSError, ValueError):
                    self.status.setText("Workspace prepared; open " + str(database.parent))
                    worker.deleteLater()
                    self._buttons()
                    return
                self.status.setText(
                    self.tr(
                        "Opened the separate sync workspace. Sync resumes there.",
                        "已開啟獨立同步工作區，會在新視窗繼續同步。",
                    )
                )
            else:
                from paper_daily.desktop.continuous_sync import controller_for
                from paper_daily.desktop.sync_connection_dialog import _background_busy

                self.session = result["session"]
                self.owner._workspace_sync_session = self.session
                self.automatic = controller_for(
                    self.owner, self.session, blocked=lambda: _background_busy(self.owner)
                )
                self.automatic.changed.connect(self._automatic_changed)
                self.auto.setChecked(self.automatic.enable())
                self.status.setText(
                    self.tr(
                        "Automatic Drive sync is on. Offline edits stay local until connected.",
                        "Drive 自動同步已啟用；離線修改會保留在本機，連線後補傳。",
                    )
                )
        else:
            if kind == "login":
                self.pilot.setChecked(False)
                self.pilot.hide()
                self._show_pilot(True)
                self.directory_lists.clear()
                self._ordinary_library = False
                self.directory_lists.hide()
                self.save_selection.hide()
                self.lists.clear()
                self.lists.hide()
                self.scope_label.hide()
                self.workspaces.clear()
                self.account.setText(self.tr("Not connected to Google", "尚未連接 Google"))
            if kind not in {"refresh", "compare", "resolve"}:
                self.service.rollback_consent()
            self.status.setText(
                self.tr("Stopped or could not finish: ", "停止")
                + str(worker.error or "cancelled")
                + self.tr(
                    ". Saved work and setup progress are retained; "
                    "retry after checking the connection.",
                    "。已保留資料與準備進度，可確認連線後重試。",
                )
            )
        if current and kind == "resolve" and worker.error == "incompatible":
            self.status.setText(self.tr("The review is out of date. Compare the versions again.",
                                        "版本或同步設定已變更，請重新比較。"))
        worker.deleteLater()
        self._buttons()
        if self._closing:
            QTimer.singleShot(0, self.close)

    def toggle_automatic(self, checked):
        if self.automatic is None:
            self.auto.setChecked(False)
            return
        from paper_daily.connection_vault import ConnectionVault

        if checked and (self.automatic.busy or not self.session.summary()["authenticated"]):
            self.auto.setChecked(False)
            return False
        if not checked:
            self.automatic.stop()
        session, enabled = self.session, checked
        return self._start(
            "toggle",
            lambda ticket, _: (
                ConnectionVault(session.workspace).set_startup(session, enabled, ticket),
                {"copied": False, "session": session, "enabled": enabled},
            )[1],
        )

    def open_advanced(self):
        from paper_daily.desktop.sync_connection_dialog import SyncConnectionDialog

        if self.busy or self._closing:
            return
        existing = getattr(self, "_advanced_dialog", None)
        if existing is not None and not existing.disposed:
            existing.show()
            existing.raise_()
            return
        dialog = SyncConnectionDialog(
            self.session,
            self,
            language=self.language,
            writers_busy=self.writers_busy,
            automatic=self.automatic,
        )
        self._advanced_dialog = dialog
        dialog.finished.connect(
            lambda _: QTimer.singleShot(0, self.close) if self._closing else None
        )
        dialog.open()

    def cancel(self):
        if self._worker:
            self._worker.ticket.cancel()

    def reject(self):
        self.close()

    def closeEvent(self, event):
        child = getattr(self, "_advanced_dialog", None)
        if child is not None and not child.disposed and not child.close():
            self._closing = True
            event.ignore()
            return
        if self.busy:
            self._closing = True
            self.cancel()
            self._buttons()
            event.ignore()
            return
        self.disposed = True
        self.done(QDialog.DialogCode.Rejected)
        event.accept()
