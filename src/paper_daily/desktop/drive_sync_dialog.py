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
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QToolButton,
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
        self.login = QToolButton()
        self.login.setText(
            self.tr(
                "Sign in / switch Google account",
                "登入／切換 Google 帳號",
            )
        )
        self.login.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = QMenu(self.login)
        self.restore_login = menu.addAction(
            self.tr("Reconnect saved library", "重新連接已記住的清單帳號"))
        self.save_login = menu.addAction(self.tr("Remember list sign-in on this device",
                                                 "在這台裝置記住清單登入"))
        self.remove_login = menu.addAction(self.tr("Forget saved list sign-in on this device",
                                                   "移除這台裝置記住的清單登入"))
        self.restore_login.triggered.connect(
            lambda: self._start("restore", self.service.reconnect_library))
        self.save_login.triggered.connect(lambda: self._start(
            "remember", lambda ticket, progress: self.service.remember_library(ticket)))
        self.remove_login.triggered.connect(lambda: self._start(
            "forget", lambda ticket, progress: self.service.forget_library(ticket)))
        self.startup_sync = menu.addAction(self.tr("Sync selected lists when Paperfact starts",
                                                   "啟動 Paperfact 時同步已勾選清單"))
        self.startup_sync.setCheckable(True)
        read_startup = getattr(self.service, "library_startup_record", lambda: None)
        self.startup_sync.setChecked(bool(read_startup()))
        self.startup_sync.triggered.connect(self._toggle_library_startup)
        self.login.setMenu(menu)
        self.login.clicked.connect(self.sign_in)
        layout.addWidget(self.login)
        self.directory_lists = QListWidget()
        self.directory_lists.setAccessibleName(self.tr("Lists on this device", "這台裝置的清單"))
        self.directory_lists.setVisible(False)
        layout.addWidget(self.directory_lists)
        self._membership_conflicts = {}
        self.membership_detail = QLabel()
        self.membership_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.membership_detail.setWordWrap(True)
        self.membership_detail.hide()
        layout.addWidget(self.membership_detail)
        self.accept_removal = QPushButton(self.tr("Confirm removal from this list",
                                                 "確認此篇已從清單移除"))
        self.accept_removal.clicked.connect(self._accept_removal)
        layout.addWidget(self.accept_removal)
        self.keep_member = QPushButton(self.tr("Keep in this list…", "保留在此清單…"))
        self.keep_member.hide()
        self.keep_member.clicked.connect(lambda: self._accept_removal(keep=True))
        layout.addWidget(self.keep_member)
        self.save_selection = QPushButton(
            self.tr("Save this device's list selection", "儲存這台裝置的清單選擇")
        )
        self.save_selection.setVisible(False)
        self.save_selection.clicked.connect(self._save_selection)
        self.refresh_lists = QPushButton(self.tr("Refresh list names", "重新讀取清單"))
        self.refresh_lists.hide()
        self.refresh_lists.clicked.connect(lambda: self._start("refresh", self.service.overview))
        selection_row = QHBoxLayout()
        selection_row.addWidget(self.save_selection)
        selection_row.addWidget(self.refresh_lists)
        layout.addLayout(selection_row)
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
        self._pdf_review_titles = {}
        self.pdf_review_label = QLabel(self.tr(
            "Different PDFs at last sync (both originals retained)",
            "上次同步發現以下論文的 PDF 不同，兩邊均已保留原檔",
        ))
        self.pdf_reviews = QListWidget()
        self.pdf_reviews.setAccessibleName(self.pdf_review_label.text())
        self.pdf_reviews.setMaximumHeight(100)
        layout.addWidget(self.pdf_review_label)
        layout.addWidget(self.pdf_reviews)
        self.pdf_toggle = QPushButton(self.tr("Allow PDF sync for this list",
                                              "允許同步這份清單的 PDF"))
        self.pdf_toggle.setCheckable(True)
        self.pdf_toggle.clicked.connect(self._choose_pdfs)
        self._reading_lists = set()
        self.reading_toggle = QPushButton(self.tr("Sync reading progress", "同步閱讀進度"))
        self.reading_toggle.setCheckable(True)
        self.reading_toggle.clicked.connect(self._choose_reading)
        self._dive_lists = set()
        self.dive_toggle = QPushButton(self.tr("Sync saved explanations", "同步已儲存的深度講解"))
        self.dive_toggle.setCheckable(True)
        self.dive_toggle.clicked.connect(self._choose_dives)
        content_row = QHBoxLayout()
        content_row.addWidget(self.reading_toggle)
        content_row.addWidget(self.pdf_toggle)
        content_row.addWidget(self.dive_toggle)
        layout.addLayout(content_row)
        self._membership_upgrades = {}
        self.upgrade_removals = QPushButton(self.tr("Sync paper removals…", "同步論文移除…"))
        self.upgrade_removals.clicked.connect(self._adopt_removals)
        layout.addWidget(self.upgrade_removals)
        self.compare_list = QPushButton(self.tr("Compare list details", "比較清單名稱與說明"))
        self.compare_list.clicked.connect(lambda: self._review_notes(feature="list"))
        layout.addWidget(self.compare_list)
        self.compare_notes = QPushButton(self.tr("Compare conflicting notes", "比較衝突筆記"))
        self.compare_notes.clicked.connect(self._review_notes)
        layout.addWidget(self.compare_notes)
        self.compare_dives = QPushButton(self.tr("Compare conflicting guides", "比較衝突講解"))
        self.compare_dives.clicked.connect(lambda: self._review_notes(feature="dive"))
        layout.addWidget(self.compare_dives)
        self.compare_reading = QPushButton(self.tr("Compare reading progress", "比較閱讀進度"))
        self.compare_reading.clicked.connect(lambda: self._review_notes(feature="reading"))
        layout.addWidget(self.compare_reading)
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
                and active.files is not None and active.binding.current()
                and active.files is self.background.files):
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
        self.restore_login.setEnabled(idle and self.service.files is None)
        self.remove_login.setEnabled(idle)
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
        if kind in {"login", "restore", "create", "join", "toggle"} and self.background.service:
            self.background.stop()
        if kind not in {"login", "restore", "remember", "forget", "refresh", "toggle", "selection",
                        "sync_saved", "notes", "startup_on", "startup_off",
                        "compare", "resolve", "pdfs", "dives", "reading"}:
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
        if kind == "login":
            self.startup_sync.setChecked(False)
            self._pdf_review_titles = {}
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
        self._membership_conflicts = library.get("membership_conflicts", {})
        self._membership_upgrades = library.get("membership_upgrades", {})
        self._note_lists = set(library.get("note_lists", ()))
        self._pdf_lists = set(library.get("pdf_lists", ()))
        self._pdf_review_titles = library.get("pdf_review_titles", {})
        self._shown_pdf_titles = None
        self._reading_lists = set(library.get("reading_lists", ()))
        self._dive_lists = set(library.get("dive_lists", ()))
        self.directory_lists.clear()
        for row in library["items"]:
            reason = library.get("reviews", {}).get(row["id"])
            label = row["name"]
            if (reason or row["id"] in self._pdf_review_titles
                    or row["id"] in self._membership_conflicts):
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
        self.refresh_lists.show()
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
        self.refresh_lists.setEnabled(checked == self._saved_ids and self.service.files is not None
                                      and not self.busy and self.background.worker is None)
        self.sync_lists.setEnabled(
            bool(self._saved_ids) and checked == self._saved_ids and self.service.files is not None
            and not self._closing and not self.busy and self.background.worker is None
        )
        self.save_login.setEnabled(self._ordinary_library and self.sync_lists.isEnabled())
        self.startup_sync.setEnabled(
            self.login.isEnabled()
            and (self.startup_sync.isChecked() or self.save_login.isEnabled())
        )
        current = self.directory_lists.currentItem()
        list_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.notes_toggle.setVisible(self._ordinary_library and list_id in self._saved_ids)
        self.notes_toggle.setChecked(list_id in self._note_lists)
        self.notes_toggle.setEnabled(self.sync_lists.isEnabled())
        titles = self._pdf_review_titles.get(list_id, ())
        if titles is not getattr(self, "_shown_pdf_titles", None):
            self.pdf_reviews.clear()
            self.pdf_reviews.addItems(titles)
            self._shown_pdf_titles = titles
        self.pdf_review_label.setVisible(bool(titles))
        self.pdf_reviews.setVisible(bool(titles))
        self.pdf_toggle.setVisible(self._ordinary_library and list_id in self._saved_ids)
        self.pdf_toggle.setChecked(list_id in self._pdf_lists)
        self.pdf_toggle.setEnabled(self.sync_lists.isEnabled())
        self.reading_toggle.setVisible(self._ordinary_library and list_id in self._saved_ids)
        self.reading_toggle.setChecked(list_id in self._reading_lists)
        self.reading_toggle.setEnabled(self.sync_lists.isEnabled())
        self.dive_toggle.setVisible(self._ordinary_library and list_id in self._saved_ids)
        self.dive_toggle.setChecked(list_id in self._dive_lists)
        self.dive_toggle.setEnabled(self.sync_lists.isEnabled())
        conflict = self._membership_conflicts.get(list_id) if self._ordinary_library else None
        self.membership_detail.setVisible(bool(conflict))
        self.accept_removal.setVisible(bool(conflict and conflict.get("observation")))
        present = conflict and conflict["kind"] != "absent"
        self.accept_removal.setText(
            self.tr("Remove from this list…", "從此清單移除…") if present
            else self.tr("Confirm removal from this list", "確認此篇已從清單移除"))
        self.accept_removal.setEnabled(self.sync_lists.isEnabled())
        observation = (conflict or {}).get("observation") or {}
        self.keep_member.setVisible(bool(present and observation.get("token")))
        self.keep_member.setEnabled(self.sync_lists.isEnabled())
        if conflict:
            explanations = {
                "replaced": self.tr("This paper was added again on this device.",
                                    "這台裝置曾重新加入這篇論文。"),
                "unverified": self.tr("The original list entry could not be verified.",
                                      "無法核對本機最初加入清單的紀錄。"),
                "absent": self.tr("This device also removed a paper, but the entries could differ.",
                                  "這台裝置也移除了論文，但無法核對為同一次加入。"),
                "changed": self.tr("The local list entry has changed.", "本機清單項目已變更。"),
                "edited": self.tr("The local position, pin or reading history needs review.",
                                  "需核對本機的排序、釘選或閱讀紀錄。"),
            }
            self.membership_detail.setText(
                conflict["title"] + "\n" + self.tr("Removed from this list on Drive. ",
                                                    "Drive 已從這份清單移除此篇。")
                + explanations[conflict["kind"]])
        else:
            self.membership_detail.clear()
        self.upgrade_removals.setVisible(
            self._ordinary_library and list_id in self._membership_upgrades)
        self.upgrade_removals.setEnabled(self.sync_lists.isEnabled())
        self.compare_list.setVisible(self._ordinary_library and list_id in self._saved_ids)
        self.compare_list.setEnabled(self.sync_lists.isEnabled())
        self.compare_notes.setVisible(self._ordinary_library and list_id in self._note_lists)
        self.compare_notes.setEnabled(self.sync_lists.isEnabled())
        self.compare_dives.setVisible(self._ordinary_library and list_id in self._dive_lists)
        self.compare_dives.setEnabled(self.sync_lists.isEnabled())
        self.compare_reading.setVisible(self._ordinary_library and list_id in self._reading_lists)
        self.compare_reading.setEnabled(self.sync_lists.isEnabled())
        active = self.background.service is not None
        self.keep_syncing.setVisible(active or self._ordinary_library)
        self.keep_syncing.setChecked(active)
        self.keep_syncing.setEnabled(
            active or (self._ordinary_library and self.sync_lists.isEnabled())
        )

    def _accept_removal(self, *, keep=False):
        item = self.directory_lists.currentItem()
        if not item or not self.sync_lists.isEnabled():
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        detail = self._membership_conflicts.get(key)
        if detail and detail.get("observation"):
            if keep:
                if not detail["observation"].get("token") or QMessageBox.question(
                    self, self.windowTitle(), self.tr(
                        f"Keep {detail['title']} in this list on your synced devices? "
                        "Update Paperfact on all devices first to sync the restored entry.",
                        f"要在同步此清單的裝置上保留《{detail['title']}》嗎？"
                        "請先更新每台裝置上的 Paperfact，讓它們能讀取恢復後的項目。"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                ) != QMessageBox.StandardButton.Yes:
                    return
            elif detail["kind"] != "absent" and QMessageBox.question(
                self, self.windowTitle(), self.tr(
                    f"Remove {detail['title']} from this list on this device? Its list position, "
                    "pin and reading status will be removed. The paper, PDF and notes stay.",
                    f"要在這台裝置從此清單移除《{detail['title']}》嗎？此清單中的排序、釘選與閱讀狀態"
                    "將會移除。論文、PDF 和筆記會保留。"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
            self._start("sync_saved", lambda ticket, progress:
                        self.service.accept_membership_removal(
                            key, detail, ticket, progress, keep=keep))

    def _adopt_removals(self):
        item = self.directory_lists.currentItem()
        if not item or not self.sync_lists.isEnabled():
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        proposal = self._membership_upgrades.get(key)
        if not proposal:
            return
        count = len(proposal["ids"])
        if QMessageBox.question(
            self, self.windowTitle(),
            self.tr(f"Sync {count} paper removal(s) from this list? This upgrades your whole "
                    "Drive library. Update Paperfact on every device first. Older versions "
                    "will stop syncing. Papers and notes stay in your library.",
                    f"同步這份清單的 {count} 筆移除？這會升級整個 Drive 研究資料庫。"
                    "請先更新每台裝置上的 Paperfact，舊版將無法同步。論文及筆記會保留。"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            self._start("sync_saved", lambda ticket, progress:
                        self.service.adopt_membership_sync(key, proposal, ticket, progress))

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

    def _choose_reading(self, checked):
        item = self.directory_lists.currentItem()
        if item is None or not self.reading_toggle.isEnabled():
            self._list_buttons()
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if checked and QMessageBox.question(
            self, self.windowTitle(),
            self.tr("Exchange reading status and timestamps for this list? Update both devices "
                    "first. Publishing progress upgrades the private directory to v7.",
                    "同步這份清單的已讀、待讀等狀態與時間？請先更新兩台裝置，"
                    "首次傳送進度會將私人目錄升級至 v7。"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            self._list_buttons()
            return
        self._start("reading", lambda ticket, progress:
                    self.service.choose_reading_sync(key, checked, ticket, progress))

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

    def _toggle_library_startup(self, checked):
        self.startup_sync.setChecked(not checked)
        if checked:
            self._start("startup_on", lambda t, _: self.service.remember_library(t, startup=True))
        else:
            self._start("startup_off", lambda t, _: self.service.disable_library_startup(t))

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
            elif self.background.state == "list_conflict":
                self.status.setText(self.tr(
                    "Select the list and choose Compare list details. Other lists still sync.",
                    "選取有衝突的清單，按「比較清單名稱與說明」。其他清單持續同步。",
                ))
            elif self.background.state == "dive_conflict":
                self.status.setText(self.tr("Guides differ. Other content keeps syncing.",
                                            "講解版本需核對，其他內容持續同步。"))
            elif self.background.state in ("pdf_conflict", "mixed_conflict", "reading_conflict"):
                self.status.setText(self.tr(
                    "Conflicting versions retained. Sync saved lists now to see affected lists.",
                    "已保留有差異的版本。按「立即同步已勾選清單」可查看受影響的清單。",
                ))
            elif self.background.state == "format":
                self.status.setText(self.tr("Update Paperfact on this device, then reconnect.",
                                            "請更新這台裝置的 Paperfact，再重新連線。"))
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
            if kind in {"login", "restore", "refresh"}:
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
            elif kind in {"startup_on", "startup_off"}:
                enabled = kind == "startup_on"
                self.startup_sync.setChecked(enabled)
                if enabled:
                    self.background.enable(self.service)
                elif self.background.service is self.service:
                    self.background.stop()
                self.status.setText(self.tr("Startup sync enabled.", "已啟用開機同步。") if enabled
                                    else self.tr("Startup sync disabled.", "已關閉開機同步。"))
            elif kind == "remember":
                self.status.setText(self.tr("Saved list sign-in in the system credential store.",
                                            "已將清單登入儲存在系統憑證庫。"))
            elif kind == "forget":
                self.startup_sync.setChecked(False)
                self.status.setText(self.tr("Removed the saved list sign-in from this device.",
                                            "已移除這台裝置記住的清單登入。"))
            elif kind == "compare":
                self._show_note_review(result)
            elif kind == "resolve":
                self.status.setText(self.tr("Choice saved. Sync to exchange the selected version.",
                                            "已儲存選擇，下次同步時會交換選定的版本。"))
            elif kind == "reading":
                self._show_directory(result)
                self.status.setText(self.tr("Reading progress preference saved.",
                                            "已儲存閱讀進度同步設定。"))
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
                self.refresh_lists.hide()
                self.lists.clear()
                self.lists.hide()
                self.scope_label.hide()
                self.workspaces.clear()
                self.account.setText(self.tr("Not connected to Google", "尚未連接 Google"))
            if kind not in {"restore", "remember", "forget", "refresh", "compare", "resolve",
                            "startup_on", "startup_off"}:
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
        if current and worker.error == "format":
            self.status.setText(self.tr("Update Paperfact on this device, then reconnect.",
                                        "請更新這台裝置的 Paperfact，再重新連線。"))
        if current and kind == "restore" and worker.error == "authorization":
            self.status.setText(self.tr("Sign in to Google to reconnect this library.",
                                        "請登入 Google 以重新連接清單。"))
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
