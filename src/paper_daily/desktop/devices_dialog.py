"""Bounded device controls for the current verified connection; no vault or AI."""

import secrets
import time
from datetime import UTC, datetime

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from paper_daily.sync_device_management import PairingUnavailableError, device_label
from paper_daily.workspace_devices import DeviceClient, DeviceContextChanged
from paper_daily.workspace_service import Cancelled, Ticket
from paper_daily.workspace_sync import EnrollmentRequired, SyncStopped

COPY = {
    "en": {
        "title": "Devices",
        "intro": "Devices connected to this workspace",
        "privacy": "Revoking stops future access. Downloaded copies stay on that device. "
        "Use Disconnect in the connection window to stop this device.",
        "columns": ["Device ID", "Label", "Access"],
        "current": "This device",
        "active": "Active",
        "revoked": "Revoked",
        "refresh": "Refresh",
        "next": "Next page",
        "rename": "Save label",
        "revoke": "Revoke access",
        "label": "Device label (leave empty to clear)",
        "close": "Close",
        "cancel": "Stop task",
        "working": "Working…",
        "ready": "Devices loaded.",
        "empty": "No devices on this page.",
        "renamed": "Device label saved.",
        "revoked_done": "Device access revoked.",
        "confirm": "Revoke this device's future access? Copies already downloaded remain on it.",
        "cancelled": "Task stopped. Refresh to check changes already sent.",
        "changed": "Connection or workspace changed. Close and reopen Devices.",
        "authorization": "Access rejected. Reconnect in the connection window.",
        "offline": "Service unavailable. Your research is unchanged; try again.",
        "invalid": "Enter a single-line label of up to 64 characters, without surrounding spaces.",
        "failed": "Task did not complete. Refresh and try again.",
    },
    "zh-TW": {
        "title": "裝置",
        "intro": "此工作區已連接的裝置",
        "privacy": "撤銷會停止之後的存取；已下載的副本仍留在該裝置。"
        "若要停止本裝置，請在連線視窗使用「中斷連線」。",
        "columns": ["裝置 ID", "名稱", "存取狀態"],
        "current": "本裝置",
        "active": "有效",
        "revoked": "已撤銷",
        "refresh": "重新整理",
        "next": "下一頁",
        "rename": "儲存名稱",
        "revoke": "撤銷存取",
        "label": "裝置名稱（留空即可清除）",
        "close": "關閉",
        "cancel": "停止作業",
        "working": "處理中…",
        "ready": "已載入裝置。",
        "empty": "此頁沒有裝置。",
        "renamed": "已儲存裝置名稱。",
        "revoked_done": "已撤銷裝置存取。",
        "confirm": "要撤銷此裝置之後的存取嗎？已下載的副本仍會留在該裝置。",
        "cancelled": "已停止作業。已送出的變更可能已完成，請重新整理確認。",
        "changed": "連線或工作區已變更。請關閉並重新開啟裝置視窗。",
        "authorization": "存取遭拒。請回到連線視窗重新連接。",
        "offline": "服務暫時無法連接。研究內容未變，請再試一次。",
        "invalid": "名稱須為 64 字以內的單行文字，前後不可有空白。",
        "failed": "作業未完成。請重新整理後再試一次。",
    },
}


COPY["en"].update({
    "pair_unavailable": (
        "This service does not support pairing. "
        "Update it or use manual connection details."
    ),
    "pair": "Pair another device", "pair_copy": "Copy pairing details",
    "pair_help": "Paste these details only on your own device; they grant workspace access.",
    "pair_ready": "Pairing details ready. Expires {expiry}. Copy them to your other device.",
    "pair_again": "Create another invitation? Existing details stay valid until they expire.",
    "pair_copied": "Pairing details copied. Paste them into Paperfact on your other device.",
})
COPY["zh-TW"].update({
    "pair_unavailable": "此服務尚不支援配對，請更新服務或使用進階手動連線資料。",
    "pair": "配對另一台裝置", "pair_copy": "複製配對資料",
    "pair_help": "請只貼到自己的另一台裝置；這會允許存取此工作區。",
    "pair_ready": "配對資料已準備好，於 {expiry} 失效。請複製到另一台裝置。",
    "pair_again": "要再建立一組配對資料嗎？原本的資料在到期前仍有效。",
    "pair_copied": "已複製配對資料，請貼到另一台裝置的 Paperfact。",
})


class DeviceWorker(QThread):
    def __init__(self, task, parent):
        super().__init__(parent)
        self.task, self.ticket = task, Ticket()
        self.result = self.error = None

    def run(self):
        try:
            self.result = self.task(self.ticket)
        except Exception as error:
            self.error = (
                "pair_unavailable"
                if isinstance(error, PairingUnavailableError)
                else "authorization"
                if isinstance(error, PermissionError)
                else "changed"
                if isinstance(error, (DeviceContextChanged, EnrollmentRequired))
                else "cancelled"
                if isinstance(error, (Cancelled, SyncStopped))
                else "offline"
                if isinstance(error, (TimeoutError, ConnectionError))
                else "failed"
            )


class DevicesDialog(QDialog):
    def __init__(self, session, parent=None, *, language="en"):
        super().__init__(parent)
        self.client = DeviceClient(session)
        self.t = COPY.get(language, COPY["en"])
        self._worker = None
        self.disposed = self._closing = self._invalid = False
        self.next_cursor = None
        self._pair_code = self._invitation = None
        self._pair_started = 0
        self._pair_confirming = False
        self.setWindowTitle(self.t["title"])
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(660, 440)
        outer = QVBoxLayout(self)
        for text in (
            self.t["intro"],
            self.client.identity["workspace_id"],
            self.t["current"] + ": " + self.client.identity["device_id"],
            self.t["privacy"],
        ):
            label = QLabel(text)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            outer.addWidget(label)
        self.devices = QTreeWidget()
        self.devices.setHeaderLabels(self.t["columns"])
        self.devices.setAccessibleName(self.t["intro"])
        self.devices.setRootIsDecorated(False)
        self.devices.setColumnWidth(0, 230)
        self.devices.setColumnWidth(1, 230)
        self.devices.itemSelectionChanged.connect(self._selected)
        outer.addWidget(self.devices)
        paging = QHBoxLayout()
        self.refresh_button, self.next_button = (
            QPushButton(self.t[key]) for key in ("refresh", "next")
        )
        self.refresh_button.clicked.connect(self.refresh)
        self.next_button.clicked.connect(self.next_page)
        paging.addWidget(self.refresh_button)
        paging.addWidget(self.next_button)
        paging.addStretch()
        outer.addLayout(paging)
        self.label = QLineEdit()
        # Qt counts UTF-16 units; the wire limit counts Unicode codepoints.
        self.label.setMaxLength(128)
        self.label.setPlaceholderText(self.t["label"])
        self.label.setAccessibleName(self.t["label"])
        outer.addWidget(self.label)
        actions = QHBoxLayout()
        self.rename_button, self.revoke_button = (
            QPushButton(self.t[key]) for key in ("rename", "revoke")
        )
        self.rename_button.clicked.connect(self.rename)
        self.revoke_button.clicked.connect(self.revoke)
        actions.addWidget(self.rename_button)
        actions.addWidget(self.revoke_button)
        outer.addLayout(actions)
        pairing = QHBoxLayout()
        self.pair_button = QPushButton(self.t["pair"])
        self.pair_copy_button = QPushButton(self.t["pair_copy"])
        self.pair_button.clicked.connect(self.create_pairing)
        self.pair_copy_button.clicked.connect(self.copy_pairing)
        pairing.addWidget(self.pair_button)
        pairing.addWidget(self.pair_copy_button)
        outer.addLayout(pairing)
        self.pair_help = QLabel(self.t["pair_help"])
        self.pair_help.setWordWrap(True)
        outer.addWidget(self.pair_help)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        bottom = QHBoxLayout()
        self.cancel_button, self.close_button = (
            QPushButton(self.t[key]) for key in ("cancel", "close")
        )
        self.cancel_button.clicked.connect(self.cancel)
        self.close_button.clicked.connect(self.close)
        bottom.addWidget(self.cancel_button)
        bottom.addStretch()
        bottom.addWidget(self.close_button)
        outer.addLayout(bottom)
        self._poll = QTimer(self)
        self._poll.setInterval(150)
        self._poll.timeout.connect(self._check)
        self._poll.start()
        self._buttons()
        QTimer.singleShot(0, self.refresh)

    @property
    def busy(self):
        return self._worker is not None

    def _row(self):
        item = self.devices.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def _selected(self):
        row = self._row()
        self.label.setText(row["label"] or "" if row else "")
        self._buttons()

    def _buttons(self):
        available = (
            not self.busy
            and not self._pair_confirming
            and not self.disposed
            and not self._closing
            and not self._invalid
            and self.client.current()
            and not self.client.session.busy
        )
        row = self._row()
        self.devices.setEnabled(available)
        self.refresh_button.setEnabled(available)
        self.pair_button.setEnabled(available)
        self.pair_copy_button.setEnabled(
            available and self._invitation is not None and self._invitation.expires_at > time.time()
        )
        self.next_button.setEnabled(available and self.next_cursor is not None)
        self.label.setEnabled(available and row is not None)
        self.rename_button.setEnabled(available and row is not None)
        self.revoke_button.setEnabled(
            available
            and row is not None
            and not row["revoked"]
            and row["device_id"] != self.client.identity["device_id"]
        )
        self.cancel_button.setEnabled(self.busy and not self._closing)

    def _check(self):
        if not self._invalid and not self.client.current():
            self._invalid = True
            if self._worker:
                self._worker.ticket.cancel()
            self.status.setText(self.t["changed"])
        self._buttons()

    def _start(self, kind, task, target=None):
        if (
            self.busy
            or self._pair_confirming
            or self.disposed
            or self._closing
            or self._invalid
            or not self.client.current()
            or self.client.session.busy
        ):
            return False
        worker = DeviceWorker(task, self)
        worker.kind, worker.target = kind, target
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

    def _pair_current(self):
        if self.client.delivery_current():
            return True
        self._invalid = True
        self._pair_code = self._invitation = None
        self.status.setText(self.t["changed"])
        self._buttons()
        return False

    def create_pairing(self):
        from paper_daily.sync_device_management import PAIRING_SECONDS

        if (self.busy or self.disposed or self._closing or self._invalid
                or self._pair_confirming or not self._pair_current()):
            return False
        if self._invitation is not None and self._invitation.expires_at > time.time():
            self._pair_confirming = True
            self._buttons()
            try:
                answer = QMessageBox.question(
                    self, self.t["pair"], self.t["pair_again"],
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
            finally:
                self._pair_confirming = False
                self._buttons()
            if answer != QMessageBox.StandardButton.Yes or not self._pair_current():
                return False
            self._pair_code = self._invitation = None
        if self._pair_code is None or time.monotonic() - self._pair_started >= PAIRING_SECONDS:
            self._pair_code = secrets.token_urlsafe(32)
            self._pair_started = time.monotonic()
            self._invitation = None
        code = self._pair_code
        return self._start("pair", lambda ticket: self.client.create_pairing(code, ticket))

    def copy_pairing(self):
        if (self.busy or self.disposed or self._closing or self._invalid
                or self._pair_confirming or self._invitation is None
                or self._invitation.expires_at <= time.time()
                or not self._pair_current()):
            return False
        QApplication.clipboard().setText(self._invitation.encoded())
        self.status.setText(self.t["pair_copied"])
        return True

    def refresh(self):
        return self._start("list", lambda ticket: self.client.catalog(ticket))

    def next_page(self):
        cursor = self.next_cursor
        if cursor is None:
            return False
        return self._start("list", lambda ticket: self.client.catalog(ticket, after=cursor))

    def rename(self):
        row = self._row()
        if row is None:
            return False
        try:
            label = device_label(self.label.text() or None)
        except ValueError:
            self.status.setText(self.t["invalid"])
            return False
        target = row["device_id"]
        return self._start(
            "rename", lambda ticket: self.client.rename(target, label, ticket), target
        )

    def revoke(self):
        row = self._row()
        if (
            row is None
            or row["revoked"]
            or self.busy
            or self._invalid
            or not self.client.current()
            or row["device_id"] == self.client.identity["device_id"]
        ):
            return False
        if (
            QMessageBox.question(
                self,
                self.t["title"],
                self.t["confirm"],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return False
        target = row["device_id"]
        return self._start("revoke", lambda ticket: self.client.revoke(target, ticket), target)

    def _render(self, item, row):
        item.setData(0, Qt.ItemDataRole.UserRole, dict(row))
        state = (
            self.t["revoked"]
            if row["revoked"]
            else self.t["current"]
            if row["device_id"] == self.client.identity["device_id"]
            else self.t["active"]
        )
        for column, value in enumerate((row["device_id"], row["label"] or "", state)):
            item.setText(column, value)
            item.setToolTip(column, value)

    def _finished(self):
        worker, self._worker = self._worker, None
        if worker is None:
            return
        if self._closing or self.disposed:
            pass
        elif worker.error == "authorization":
            self._invalid = True
            self.status.setText(self.t["authorization"])
        elif worker.error == "changed" or not self.client.current():
            self._invalid = True
            self.status.setText(self.t["changed"])
        elif worker.ticket.cancelled:
            self.status.setText(self.t["cancelled"])
        elif worker.error:
            self.status.setText(self.t[worker.error])
        elif worker.kind == "pair":
            from paper_daily.sync_pairing import Invitation

            if not self.client.delivery_current():
                self._invalid = True
                self.status.setText(self.t["changed"])
            else:
                self._invitation = Invitation(
                    self.client.session.endpoint, code=self._pair_code, **worker.result
                )
                try:
                    expiry = datetime.fromtimestamp(
                        self._invitation.expires_at, UTC
                    ).strftime("%H:%M UTC")
                except (ValueError, OverflowError, OSError):
                    expiry = str(self._invitation.expires_at) + " UTC epoch"
                self.status.setText(self.t["pair_ready"].format(expiry=expiry))
        elif worker.kind == "list":
            self.devices.clear()
            for row in worker.result["devices"]:
                self._render(QTreeWidgetItem(self.devices), row)
            self.next_cursor = worker.result["next_cursor"]
            self.status.setText(self.t["ready"] if worker.result["devices"] else self.t["empty"])
        else:
            for index in range(self.devices.topLevelItemCount()):
                item = self.devices.topLevelItem(index)
                row = item.data(0, Qt.ItemDataRole.UserRole)
                if row["device_id"] == worker.target:
                    key = "label" if worker.kind == "rename" else "revoked"
                    row[key] = worker.result[key]
                    self._render(item, row)
            self.status.setText(self.t["renamed" if worker.kind == "rename" else "revoked_done"])
        worker.deleteLater()
        self._buttons()
        if self._closing:
            self.close()

    def cancel(self):
        if self._worker:
            self._worker.ticket.cancel()
            self.status.setText(self.t["cancelled"])

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if self.busy:
            self._closing = True
            self.cancel()
            event.ignore()
            return
        self.disposed = True
        self._pair_code = self._invitation = None
        self._poll.stop()
        self.done(QDialog.DialogCode.Rejected)
        event.accept()
