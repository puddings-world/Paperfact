"""Progressive, read-only device versus authority-backup review."""

import weakref

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from paper_daily import sync_authority_backup as backup
from paper_daily import sync_device_recovery
from paper_daily.workspace_service import Cancelled, WorkspaceChanged
from paper_daily.workspace_sync import local_binding


class DeviceRecoveryReview(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self._owner, self.enrolled = weakref.ref(owner), False
        self.disclosure = QPushButton(
            "同步服務備份比對（進階）" if owner.zh else "Compare service backup (advanced)"
        )
        self.disclosure.setCheckable(True)
        self.content = QWidget()
        self.content.setVisible(False)
        self.disclosure.toggled.connect(self.content.setVisible)
        self.button = QPushButton(
            "選擇服務備份資料夾…" if owner.zh else "Choose service backup folder…"
        )
        self.button.clicked.connect(self.choose)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.reset()
        content = QVBoxLayout(self.content)
        content.addWidget(self.button)
        content.addWidget(self.label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.disclosure)
        layout.addWidget(self.content)

    @property
    def owner(self):
        return self._owner()

    def reset(self):
        self.label.setText(
            "唯讀檢查這台裝置比服務備份多出的同步變更。"
            "請選擇含 manifest.json 的服務備份資料夾，不是研究清單 ZIP。"
            "未儲存草稿不在檢查範圍；不會改動、重送或切換資料。"
            if self.owner.zh
            else "Read-only comparison with a service backup folder containing manifest.json, "
            "not a list ZIP. Unsaved drafts are excluded. No edits, replay or workspace switch."
        )

    def set_active(self, active):
        self.button.setEnabled(bool(active and self.enrolled))
        self.button.setToolTip(
            "僅適用於已建立同步佇列的裝置。"
            if self.owner.zh
            else "Requires an existing device sync journal."
        )

    def choose(self):
        if not self.button.isEnabled():
            return False
        selected = QFileDialog.getExistingDirectory(
            self, "選擇同步服務備份" if self.owner.zh else "Choose sync service backup"
        )
        return self.inspect(selected) if selected else False

    def inspect(self, selected):
        owner = self.owner
        if not selected or not self.button.isEnabled() or not owner._adoption_context_current():
            return False
        self.reset()
        service = owner.service

        def run(ticket, _progress):
            ticket.check()
            service.check()
            binding = local_binding(service.path)
            if binding is None:
                raise WorkspaceChanged("Device journal is no longer bound")
            try:
                result = sync_device_recovery.review(
                    service.path,
                    selected,
                    binding["workspace_id"],
                    cancelled=lambda: ticket.cancelled,
                )
            except backup.BackupCancelled:
                raise Cancelled() from None
            ticket.check()
            service.check()
            return result

        return owner._start("device_review", run)

    def deliver(self, result):
        owner = self.owner
        owner.service.check()
        if not owner._adoption_context_current():
            raise WorkspaceChanged("Review destination changed")
        labels = [
            ("backup_sequence", "服務備份序號", "Service backup sequence"),
            ("device_cursor", "本機已收到序號", "Device received sequence"),
            ("journal_already_in_backup", "本機操作已在備份", "Local operations already in backup"),
            (
                "unconfirmed_not_in_backup",
                "本機未確認且不在備份",
                "Unconfirmed and absent from backup",
            ),
            (
                "acknowledged_after_backup",
                "服務已回覆但不在備份",
                "Acknowledged but absent from backup",
            ),
            ("received_after_backup", "本機收到的備份後變更", "Received events after backup"),
        ]
        lines = [f"{zh if owner.zh else en}: {result[key]:,}" for key, zh, en in labels]
        lines.append(
            "以上類別可能重疊，不能相加。未確認不代表從未送出。"
            if owner.zh
            else "Categories may overlap; do not sum. Unconfirmed does not mean never sent."
        )
        lines.append(
            "請保留舊工作區並建立完整研究備份，再於新工作區審閱匯入。"
            if result["requires_preservation"] and owner.zh
            else "Keep the old workspace and create a complete research backup before import."
            if result["requires_preservation"]
            else "這次未找到上述備份外變更；仍不代表所有研究與附件都已完整核對。"
            if owner.zh
            else "No uncovered journal work observed; this is not a full research/file audit."
        )
        lines.append(
            "這是檢查當下的結果；後續修改請重新檢查。沒有自動重送或切換工作區。"
            if owner.zh
            else "Point-in-time review; rerun after edits. No replay or workspace switch."
        )
        self.label.setText("\n".join(lines))
        owner.status.setText(
            "本機與服務備份比對完成。" if owner.zh else "Device/backup review finished."
        )
