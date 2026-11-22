"""Window-owned polling of an explicitly selected, signed-in personal library."""

from datetime import datetime

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal, Slot

from paper_daily.desktop.sync_connection_dialog import SyncWorker, _background_busy

READING_INTERVAL_MS = 30_000
MINIMIZED_INTERVAL_MS = 120_000


class SavedListSync(QObject):
    changed = Signal()
    activity = Signal(object)

    def __init__(self, owner):
        super().__init__(owner)
        self.service = self.files = self.worker = None
        self.startup_stamp = None
        self.position_scopes = {}
        self.state = "off"
        self.detail = None
        self.coverage = {}
        self.failures = 0
        self.last_checked = ""
        self.deferred = ""
        self.closing = False
        self.changed.connect(self._display)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.tick)
        owner.installEventFilter(self)

    def update_position_scopes(self, service, library):
        """Keep only local reader bindings after a manual or background exchange."""
        self.position_scopes.clear()
        allowed = library.get("position_lists")
        if not allowed or not library.get("ordinary"):
            return
        files, store, selection, directory, *_ = service._library_view
        if (directory is None or files is not service.files or not service.account
                or store.owner_id != service.account["id"]):
            return
        self.position_scopes = {
            key: (store, directory.folder, directory.head, key, selection.revision)
            for key in allowed if key in selection.selected
        }

    def _display(self):
        button = getattr(self.parent(), "sync_status_btn", None)
        if button is None:
            return
        labels = {
            "off": "自動同步已關閉", "waiting": "自動同步已開啟，等待檢查 Drive",
            "working": "正在連接 Google 帳號" if self.files is None else "正在核對 Drive 清單目錄",
            "offline": f"無法連上 Drive，將自動重試（間隔 {self.timer.interval() // 1000} 秒）",
            "changed": "工作區已切換，請重新啟用同步", "review": "清單同步已暫停，請核對",
        }
        labels["list_conflict"] = "清單名稱或說明需核對，其他清單持續同步"
        labels["format"] = "同步已暫停，請更新 Paperfact 以讀取此資料庫格式"
        labels["reading_conflict"] = "閱讀進度不同，已保留兩端狀態"
        labels["note_conflict"] = "部分筆記需核對，其他內容持續同步"
        labels["chat_conflict"] = "部分問答需核對，其他內容持續同步"
        labels["dive_conflict"] = "講解版本需核對，其他內容持續同步"
        labels["pdf_conflict"] = "PDF 版本不同，已保留原檔；其他內容持續同步"
        labels["mixed_conflict"] = "多種內容版本不同，請查看清單；其他內容持續同步"
        from paper_daily.drive_transfer_progress import describe

        if self.state == "waiting":
            if self.deferred:
                labels["waiting"] = self.deferred
            elif self.last_checked:
                labels["waiting"] = f"{self.last_checked} 已核對 · 等待下次檢查 Drive"
        detail = describe(self.detail) if self.state == "working" else ""
        compact = button.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideMiddle, 520)
        button.setText(compact or labels[self.state])
        button.setToolTip(detail or labels[self.state])
        button.setAccessibleName(detail or labels[self.state])

    def enable(self, service):
        if self.worker or self.closing or service.files is None or not service.binding.current():
            return False
        self.startup_stamp = None
        self.last_checked = self.deferred = ""
        self.detail = None
        self.coverage.clear()
        self.service, self.files = service, service.files
        self.failures = 0
        self.state = "waiting"
        self.timer.start(1000)
        self.changed.emit()
        return True

    def resume(self, service, stamp):
        if self.worker or self.service or self.closing or stamp is None:
            return False
        self.startup_stamp, self.service = stamp, service
        self.state = "waiting"
        self.timer.start(1000)
        self.changed.emit()
        return True

    def stop(self, state="off"):
        self.timer.stop()
        self.last_checked = self.deferred = ""
        self.startup_stamp = None
        self.service = self.files = self.detail = None
        self.coverage.clear()
        if self.worker:
            self.worker.ticket.cancel()
        self.state = state
        if state != "off":
            self.position_scopes.clear()
        self.changed.emit()

    def tick(self):
        if self.worker or self.service is None:
            return
        if self.files is not self.service.files or not self.service.binding.current():
            self.stop("changed")
            return
        from paper_daily.desktop.drive_sync_dialog import DriveSyncDialog

        # Keep the exact directory snapshot that the visible checklist is reviewing.
        owner = self.parent()
        reviewing = any(view.isVisible() for view in owner.findChildren(DriveSyncDialog))
        if reviewing or _background_busy(owner):
            self.deferred = ("等待關閉同步設定，再檢查 Drive" if reviewing
                             else "等待目前工作完成，再檢查 Drive")
            self.timer.start(5000)
            self._display()
            return
        self.deferred = ""
        if self.startup_stamp and self.service.library_startup_record() != self.startup_stamp:
            self.position_scopes.clear()
            self.stop()
            return
        service, stamp = self.service, self.startup_stamp
        if stamp and self.files is None:
            def task(ticket, progress):
                return service.reconnect_library(ticket, progress, startup_record=stamp)
        else:
            task = service.sync_saved_library
        self.worker = SyncWorker(task, self)
        self.detail = None
        self.worker.progress.connect(self._progress)
        if stamp and self.files is None:
            self.worker.progress.connect(self._startup_progress)
        self.worker.finished.connect(self._finished)
        self.state = "working"
        self.changed.emit()
        self.worker.start()

    @Slot(object)
    def _progress(self, value):
        if (self.sender() is self.worker and self.worker and self.state == "working"
                and not self.worker.ticket.cancelled and isinstance(value, dict)
                and value.get("stage") == "transfer"):
            self.detail = value
            if value.get("coverage") and value.get("list_id"):
                self.coverage[value["list_id"]] = value["coverage"]
            self._display()
            self.activity.emit(value)

    @Slot(object)
    def _startup_progress(self, update):
        if (self.sender() is self.worker and self.worker and not self.worker.ticket.cancelled
                and self.service and self.startup_stamp and isinstance(update, dict)
                and update.get("stage") == "local_page_scopes"
                and update["stamp"] == self.startup_stamp == self.service.library_startup_record()):
            self.position_scopes = update["scopes"]

    def _finished(self):
        worker, self.worker = self.worker, None
        if self.service is not None and not worker.ticket.cancelled:
            if self.startup_stamp and self.service.library_startup_record() != self.startup_stamp:
                self.position_scopes.clear()
                self.stop()
            elif self.startup_stamp and self.files is None and not worker.error:
                self.files = self.service.files
                if self.files and any(row["selected"] for row in worker.result["library"]["items"]):
                    self.failures = 0
                    self.state = "waiting"
                    self.update_position_scopes(self.service, worker.result["library"])
                    self.timer.start(1000)
                else:
                    self.stop()
            elif self.files is not self.service.files or not self.service.binding.current():
                self.stop("changed")
            elif worker.error == "format":
                self.stop("format")
            elif worker.error == "offline":
                self.failures += 1
                self.state = "offline"
                self.timer.start(min(300, 10 * 2 ** min(5, self.failures - 1)) * 1000)
            elif worker.error or (worker.result.get("reviews", {}).keys()
                                  - set(worker.result.get("list_conflicts", ()))
                                  - set(worker.result.get("note_conflicts", ()))
                                  - set(worker.result.get("chat_conflicts", ()))
                                  - set(worker.result.get("dive_conflicts", ()))
                                  - set(worker.result.get("reading_conflicts", ()))
                                  - set(worker.result.get("pdf_conflicts", ()))):
                self.stop("review")
            elif not any(item["selected"] for item in worker.result["items"]):
                self.position_scopes.clear()
                self.stop()
            else:
                self.failures = 0
                self.update_position_scopes(self.service, worker.result)
                self.last_checked = datetime.now().strftime("%H:%M:%S")
                conflicts = [kind for kind in ("list", "note", "chat", "dive", "pdf", "reading")
                             if worker.result.get(kind + "_conflicts")]
                self.state = "waiting"
                if conflicts:
                    self.state = (conflicts[0] if len(conflicts) == 1 else "mixed") + "_conflict"
                self.timer.start(MINIMIZED_INTERVAL_MS if self.parent().isMinimized()
                                 else READING_INTERVAL_MS)
        worker.deleteLater()
        self.changed.emit()
        if self.closing:
            QTimer.singleShot(0, self.parent().close)

    def eventFilter(self, obj, event):
        if (obj is self.parent() and event.type() == QEvent.Type.WindowStateChange
                and not obj.isMinimized() and self.timer.isActive()
                and self.timer.interval() == MINIMIZED_INTERVAL_MS
                and self.timer.remainingTime() > 1000):
            self.timer.start(1000)
        if (obj is self.parent() and event.type() == QEvent.Type.Close
                and (self.worker is not None or self.service is not None)):
            self.closing = self.worker is not None
            self.stop()
            if self.closing:
                event.ignore()
                return True
        return False


def resume_on_open(owner, database, *, current_path, factory=None):
    import sqlite3

    from paper_daily.drive_sync_setup import DriveSetup

    try:
        service = (factory or DriveSetup)(database, current_path=current_path)
        stamp = service.library_startup_record()
        if stamp:
            return for_window(owner).resume(service, stamp)
    except (OSError, ValueError, sqlite3.Error):
        pass
    return False


def for_window(owner):
    controller = getattr(owner, "_saved_list_sync", None)
    if controller is None:
        controller = owner._saved_list_sync = SavedListSync(owner)
    return controller
