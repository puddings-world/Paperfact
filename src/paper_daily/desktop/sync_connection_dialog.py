"Explicit self-host connection, manual sync and safe new-directory joining."

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from paper_daily import sync_bootstrap
from paper_daily.workspace_service import Cancelled, Ticket
from paper_daily.workspace_sync import EnrollmentRequired, SyncStopped, local_binding

COPY = {
    "zh-TW": {
        "title": "工作區同步連線",
        "intro": (
            "連接你信任的自架／參考同步服務。需要管理端核發的工作區 ID、裝"
            "置 ID 與裝置憑證；這不是 AI 或 Google 帳號登入。"
        ),
        "privacy": (
            "憑證只保留於這次 App 程序的記憶體；不寫入研究資料、備份或設定檔。"
            "重開 App 後需重新連接。"
        ),
        "server": "服務網址",
        "workspace": "工作區 ID",
        "device": "裝置 ID",
        "token": "裝置憑證",
        "connect": "驗證並連接",
        "disconnect": "中斷連線",
        "sync": "立即同步",
        "join": "加入到新工作區…",
        "close": "返回工作區",
        "cancel": "停止目前工作",
        "new": "新的工作區資料夾",
        "name": "新資料夾名稱",
        "choose": "選擇父資料夾",
        "confirm": "將逐段下載研究記錄到新的工作區；不會覆蓋或切換目前資料。附件完整性另外判定。",
        "first": (
            "目前資料尚未完成可同步的啟用程序。連接憑證不會自動匯出或合併這些研究；"
            "可以另外加入到新的資料夾。"
        ),
        "gates": (
            "仍待完成：現有資料的首次完整啟用、受保護的記住登入、裝置核發／撤"
            "銷介面。新工作區可另外開啟；未支援的記錄會停止接收，不會跳過"
            "。"
        ),
        "checking": "正在確認服務回覆的工作區與裝置身分…",
        "connected": "已確認裝置身分；尚未傳送研究內容。",
        "working": "工作進行中；關閉或停止會在安全邊界保留已完成進度。",
        "cancelled": "已停止；已提交的研究與加入進度保留，可明確重試。",
        "authorization": "憑證遭拒或身分不符；請重新連接。研究資料未清除。",
        "offline": "服務暫時無法連線；本機研究與待同步內容保留，可重試。",
        "incompatible": "設定、協定或研究記錄不相容；未跳過記錄或重設進度。請核對設定與版本。",
        "storage": "儲存未完成；原工作區不受影響。請確認空間與新目的地後重試。",
        "destination": "目的地已存在，且不是這次加入的完成結果。請選擇新的資料夾。",
        "enrollment": "目前資料尚未符合完整啟用條件，未自動進行遷移。",
        "failed": "工作未完成；研究與待處理內容保留。請重新檢查後重試。",
        "changed": "目前工作區已變動，請關閉後重新開啟。",
        "empty": "請填寫服務網址、工作區 ID、裝置 ID 與憑證。",
    },
    "en": {
        "title": "Workspace sync connection",
        "intro": (
            "Connect to a reference or self-h"
            "osted service you trust using it"
            "s administrator-issued workspace"
            " ID, device ID and device creden"
            "tial. This is separate from AI o"
            "r Google login."
        ),
        "privacy": (
            "Credentials stay in this app pro"
            "cess's memory, outside research,"
            " backups and settings. Reconnect"
            " after restarting the app."
        ),
        "server": "Service URL",
        "workspace": "Workspace ID",
        "device": "Device ID",
        "token": "Device credential",
        "connect": "Verify and connect",
        "disconnect": "Disconnect",
        "sync": "Sync now",
        "join": "Join in new folder…",
        "close": "Back to workspace",
        "cancel": "Stop current task",
        "new": "New workspace folder",
        "name": "New folder name",
        "choose": "Choose parent folder",
        "confirm": (
            "Replay research into a new works"
            "pace without overwriting or swit"
            "ching your active data. Attachme"
            "nt availability is separate."
        ),
        "first": (
            "This local research has not comp"
            "leted sync enrollment. Connectin"
            "g does not export or merge it. Y"
            "ou can join separately in a new "
            "directory."
        ),
        "gates": (
            "Still required: complete first e"
            "nrollment of existing research, "
            "secure remembered login, device "
            "issuance/revocation UI. Unsup"
            "ported records stop receive; the"
            "y are never skipped."
        ),
        "checking": ("Checking the service's authenticated workspace/device identity…"),
        "connected": ("Device identity verified; no research has been sent."),
        "working": ("Working. Stop or close preserves completed progress at a safe boundary."),
        "cancelled": (
            "Stopped; committed research and join progress are preserved for explicit retry."
        ),
        "authorization": (
            "Credential rejected or identity mismatch. Reconnect; local research is retained."
        ),
        "offline": (
            "Service unavailable. Local resea"
            "rch and pending changes are reta"
            "ined; retry when ready."
        ),
        "incompatible": (
            "Settings, protocol or research r"
            "ecords are incompatible. No reco"
            "rds were skipped or cursor reset"
            ". Check settings and versions."
        ),
        "storage": (
            "Storage operation did not comple"
            "te. Active data is unchanged; ch"
            "eck space and destination, then "
            "retry."
        ),
        "destination": (
            "Destination already exists and i"
            "s not this join's completed resu"
            "lt. Choose a new directory."
        ),
        "enrollment": (
            "This workspace does not meet enr"
            "ollment requirements. No automat"
            "ic migration was attempted."
        ),
        "failed": (
            "Task did not complete. Research and pending work are retained; check and retry."
        ),
        "changed": ("Active workspace changed. Close and reopen this window."),
        "empty": ("Enter the service URL, workspace ID, device ID and credential."),
    },
}


class SyncWorker(QThread):
    progress = Signal(object)

    def __init__(self, task, parent):
        super().__init__(parent)
        self.task, self.ticket = task, Ticket()
        self.result = self.error = None

    def run(self):
        try:
            self.result = self.task(self.ticket, self.progress.emit)
        except Exception as error:
            self.error = (
                "cancelled"
                if isinstance(error, (Cancelled, SyncStopped))
                else "enrollment"
                if isinstance(error, EnrollmentRequired)
                else "authorization"
                if isinstance(error, PermissionError)
                else "offline"
                if isinstance(error, (TimeoutError, ConnectionError))
                else "destination"
                if isinstance(error, FileExistsError)
                else "incompatible"
                if isinstance(error, ValueError)
                else "storage"
                if isinstance(error, OSError)
                else "failed"
            )


class SyncConnectionDialog(QDialog):
    def __init__(
        self,
        session,
        parent=None,
        *,
        language="zh-TW",
        writers_busy=lambda: False,
        open_workspace=None,
    ):
        super().__init__(parent)
        from paper_daily.workspace_open import open_workspace as launch_workspace

        self._open_workspace = open_workspace or launch_workspace
        self.created_destination = None
        self._opened = False
        self.session, self.writers_busy = session, writers_busy
        self.zh = language == "zh-TW"
        self.t = COPY.get(language, COPY["en"])
        self._worker = None
        self._closing = self.disposed = self._invalid = self._setting = False
        self.binding, self.eligible = None, False
        self.join_destination = None
        self.setWindowTitle(self.t["title"])
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(680, 690)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        for text in (str(session.workspace.path.parent), self.t["intro"], self.t["privacy"]):
            label = QLabel(text)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(label)
        form = QFormLayout()
        self.endpoint, self.workspace_id, self.device_id, self.credential = (
            QLineEdit() for _ in range(4)
        )
        self.endpoint.setPlaceholderText("https://sync.example.org")
        self.credential.setEchoMode(QLineEdit.EchoMode.Password)
        for key, field in (
            ("server", self.endpoint),
            ("workspace", self.workspace_id),
            ("device", self.device_id),
            ("token", self.credential),
        ):
            field.setMaxLength(4096 if key == "token" else 2048 if key == "server" else 128)
            field.textChanged.connect(self._edited)
            form.addRow(self.t[key], field)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.connect_button = QPushButton(self.t["connect"])
        self.connect_button.clicked.connect(self.connect_session)
        self.disconnect_button = QPushButton(self.t["disconnect"])
        self.disconnect_button.clicked.connect(self.disconnect)
        row.addWidget(self.connect_button)
        row.addWidget(self.disconnect_button)
        layout.addLayout(row)
        self.identity_label = QLabel()
        self.identity_label.setWordWrap(True)
        layout.addWidget(self.identity_label)
        self.enrollment_label = QLabel(self.t["first"])
        self.enrollment_label.setWordWrap(True)
        layout.addWidget(self.enrollment_label)
        self.sync_button = QPushButton(self.t["sync"])
        self.sync_button.clicked.connect(self.sync_now)
        layout.addWidget(self.sync_button)
        self.join_button = QPushButton(self.t["join"])
        self.join_button.clicked.connect(self.choose_join)
        layout.addWidget(self.join_button)
        self.open_created_button = QPushButton(
            "開啟新工作區視窗" if self.zh else "Open created workspace"
        )
        self.open_created_button.clicked.connect(self.open_created)
        layout.addWidget(self.open_created_button)
        self.destination_label = QLabel()
        self.destination_label.setWordWrap(True)
        self.destination_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.destination_label)
        gates = QLabel(self.t["gates"])
        gates.setWordWrap(True)
        layout.addWidget(gates)
        layout.addStretch()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Sync status")
        outer.addWidget(self.status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        outer.addWidget(self.progress_bar)
        bottom = QHBoxLayout()
        self.stop_button = QPushButton(self.t["cancel"])
        self.stop_button.clicked.connect(self.cancel)
        self.close_button = QPushButton(self.t["close"])
        self.close_button.clicked.connect(self.close)
        bottom.addWidget(self.stop_button)
        bottom.addStretch()
        bottom.addWidget(self.close_button)
        outer.addLayout(bottom)
        self._setting = True
        summary = session.summary()
        if summary["endpoint"]:
            self.endpoint.setText(summary["endpoint"])
        if summary["identity"]:
            self.workspace_id.setText(summary["identity"]["workspace_id"])
            self.device_id.setText(summary["identity"]["device_id"])
        self._setting = False
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._check_workspace)
        self._poll.start()
        self._buttons()
        QTimer.singleShot(0, self.probe)

    @property
    def busy(self):
        return self._worker is not None

    def _edited(self):
        if not self._setting:
            self.session.disconnect()
            self._buttons()

    def _buttons(self):
        summary = self.session.summary()
        live = summary.get("authenticated", False)
        available = not self.busy and not self.disposed and not self._invalid
        for field in (self.endpoint, self.workspace_id, self.device_id, self.credential):
            field.setEnabled(available)
        self.connect_button.setEnabled(available)
        self.disconnect_button.setEnabled(live and not self.disposed)
        self.sync_button.setEnabled(
            available and live and self.eligible and self.binding == summary["identity"]
        )
        self.join_button.setEnabled(available and live and self.binding != summary["identity"])
        self.open_created_button.setEnabled(
            available and self.created_destination is not None and not self._opened
        )
        self.stop_button.setEnabled(self.busy)
        self.progress_bar.setVisible(self.busy)
        mismatch = self.eligible and live and self.binding != summary["identity"]
        self.enrollment_label.setVisible(not self.eligible or mismatch)
        self.enrollment_label.setText(
            (
                "目前資料屬於另一個工作區／裝置；請加入新的資料夾，不會自動合併。"
                if self.zh
                else (
                    "Current data belongs to another "
                    "workspace/device. Join in a new "
                    "directory; it will not be merged"
                    "."
                )
            )
            if mismatch
            else self.t["first"]
        )
        labels = {
            "disconnected": "未連接",
            "checking": "確認身分中",
            "connected": "已連接",
            "syncing": "同步中",
            "offline": "暫時無法連線",
            "reconnect": "請重新連接",
            "failed": "上次操作未完成",
        }
        state = labels.get(summary["state"], summary["state"]) if self.zh else summary["state"]
        self.identity_label.setText(
            (("連線狀態：" if self.zh else "Connection state: ") + state)
            + (
                ("\n上次手動同步：" if self.zh else "\nLast manual sync: ")
                + summary["last_success"]
                if summary["last_success"]
                else ""
            )
        )

    def _start(self, kind, task):
        if self.busy or self.disposed or self._invalid:
            return False
        worker = SyncWorker(task, self)
        self._worker = worker
        worker.progress.connect(self._progress)
        worker.finished.connect(lambda: self._finished(worker, kind))
        self.status.setText(self.t["checking"] if kind == "connect" else self.t["working"])
        self._buttons()
        worker.start()
        return True

    def probe(self):
        def run(_ticket, _progress):
            binding = local_binding(self.session.workspace.path)
            try:
                local_binding(self.session.workspace.path, require_capture=True)
                eligible = True
            except EnrollmentRequired:
                eligible = False
            return {"binding": binding, "eligible": eligible}

        return self._start("probe", run)

    def connect_session(self):
        if self.busy:
            return False
        values = tuple(
            field.text().strip()
            for field in (self.endpoint, self.workspace_id, self.device_id, self.credential)
        )
        if not all(values):
            self.status.setText(self.t["empty"])
            return False
        return self._start(
            "connect", lambda ticket, _progress: self.session.connect(*values, ticket)
        )

    def sync_now(self):
        if self.busy or not self.sync_button.isEnabled():
            return False
        if self.writers_busy():
            self.status.setText(
                "請等候背景研究工作結束。"
                if self.zh
                else "Wait for background research jobs to finish."
            )
            return False
        return self._start("sync", self.session.sync)

    def choose_join(self):
        if self.busy or not self.join_button.isEnabled():
            return
        parent = QFileDialog.getExistingDirectory(self, self.t["choose"])
        if not parent:
            return
        name, accepted = QInputDialog.getText(
            self, self.t["new"], self.t["name"], text="Paperfact-workspace"
        )
        if not accepted or not name.strip():
            return
        if name in {".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
            self.status.setText(self.t["destination"])
            return
        destination = Path(parent) / name
        if (
            QMessageBox.question(
                self,
                self.t["new"],
                self.t["confirm"] + "\n" + str(destination),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.start_join(destination)

    def start_join(self, destination):
        if (
            self.busy
            or not self.join_button.isEnabled()
            or not isinstance(destination, (str, Path))
            or not str(destination).strip()
        ):
            return False
        destination = Path(destination)
        self.join_destination = destination
        self.destination_label.setText(str(self.join_destination))
        return self._start(
            "join",
            lambda ticket, progress: sync_bootstrap.join(
                self.session, destination, ticket, progress
            ),
        )

    def _progress(self, value):
        if self._closing or self._invalid or not self._worker or self._worker.ticket.cancelled:
            return
        if value.get("stage") == "attachments":
            text = (
                f"附件傳輸步驟：{value['steps']}"
                if self.zh
                else f"Attachment steps: {value['steps']}"
            )
            if "offset" in value and "size" in value:
                text += f" · {value['offset']:,} / {value['size']:,} bytes"
        else:
            text = (
                (
                    f"已傳送 {value.get('pushed', 0)}、接收 {value.get('received', 0)}；"
                    f"進度序號 {value.get('cursor', 0)}"
                )
                if self.zh
                else (
                    f"Sent {value.get('pushed', 0)}, received {value.get('received', 0)}; "
                    f"cursor {value.get('cursor', 0)}"
                )
            )
        self.status.setText(text)

    def _finished(self, worker, kind):
        if self._worker is not worker:
            return
        self._worker = None
        self._check_workspace()
        if not self._invalid and not self._closing:
            if worker.error:
                self.status.setText(self.t[worker.error])
            elif worker.ticket.cancelled:
                self.status.setText(self.t["cancelled"])
            elif kind == "probe":
                self.binding, self.eligible = worker.result["binding"], worker.result["eligible"]
                if self.binding and not self.workspace_id.text() and not self.device_id.text():
                    self._setting = True
                    self.workspace_id.setText(self.binding["workspace_id"])
                    self.device_id.setText(self.binding["device_id"])
                    self._setting = False
                self.status.clear()
            elif kind == "connect":
                self._setting = True
                self.credential.clear()
                self._setting = False
                self.status.setText(self.t["connected"])
            elif kind == "sync":
                result = worker.result
                self._progress({**result, "stage": "metadata"})
                text = (
                    (
                        f"本次傳送 {result['pushed']}、接收 {result['received']}；"
                        f"待傳 {result['pending']}、待確認 {result['awaiting_receipts']}，"
                        f"衝突 {result['conflicts']}。"
                    )
                    if self.zh
                    else (
                        f"Sent {result['pushed']}, received {result['received']}; "
                        f"pending {result['pending']}, "
                        f"awaiting receipts {result['awaiting_receipts']}, "
                        f"conflicts {result['conflicts']}."
                    )
                )
                files = result["attachments"]
                text += (
                    f"\n附件待處理 {files['pending']}，失敗 {files['failed']}；未宣稱整體可離線。"
                    if self.zh
                    else (
                        f"\nAttachments pending {files['pending']}, failed {files['failed']}; "
                        "whole-workspace offline status is not verified."
                    )
                )
                if not result["caught_up"]:
                    text += (
                        "\n尚有記錄，請繼續同步。"
                        if self.zh
                        else "\nMore records remain; continue syncing."
                    )
                self.status.setText(text)
            elif kind == "join":
                result = worker.result
                if result["state"] == "catching_up":
                    text = (
                        "加入進度已保留，請以相同資料夾繼續；尚未發布新工作區。"
                        if self.zh
                        else (
                            "Join progress saved. Continue wi"
                            "th the same destination; workspa"
                            "ce not yet published."
                        )
                    )
                else:
                    text = (
                        "研究記錄工作區已建立；附件仍須取得。可按「開啟新工作區視窗」繼續；目前視窗保持原狀。"
                        if self.zh
                        else (
                            "Metadata workspace created; atta"
                            "chments still need downloading. "
                            "Active workspace unchanged. "
                            "Use Open created workspace to c"
                            "ontinue in a separate window."
                        )
                    )
                self.status.setText(text + "\n" + result["path"])
                if result["state"] == "metadata_ready":
                    from paper_daily.workspace_open import WorkspaceDestination

                    folder = Path(result["path"])
                    self.created_destination = WorkspaceDestination(folder, folder / "papers.db")
                    self._opened = False
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
            self.status.setText(self.t["failed"])
            self._buttons()
            return False
        self.status.setText(
            "已要求開啟新視窗；此視窗與編輯內容保留。"
            if self.zh
            else "Opening the created workspace; this window and its drafts stay open."
        )
        return True

    def cancel(self):
        if self._worker:
            self._worker.ticket.cancel()
            self.session.cancel()
            self.status.setText(self.t["working"])

    def disconnect(self):
        self.session.disconnect()
        if self._worker:
            self._worker.ticket.cancel()
        self._setting = True
        self.credential.clear()
        self._setting = False
        self._buttons()

    def _check_workspace(self):
        try:
            path = self.session.workspace.path
            info = path.stat()
            changed = (info.st_dev, info.st_ino) != self.session.workspace.identity or Path(
                self.session.workspace.current_path()
            ).resolve() != path
        except OSError:
            changed = True
        if changed:
            self._invalid = True
            self.disconnect()
            self.status.setText(self.t["changed"])

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
        self._setting = True
        self.credential.clear()
        self.done(QDialog.DialogCode.Rejected)
        event.accept()
