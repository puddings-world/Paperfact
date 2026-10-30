"""Explicit selected-paper offline checks and device-local retention intent.

This dialog never downloads files, opens an AI connection or edits reader drafts.
A verified result applies to the selected current manifests, never the workspace.
"""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from paper_daily.desktop.flow_layout import FlowLayout
from paper_daily.desktop.workspace_dialog import WorkspaceWorker
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import EnrollmentRequired

TEXT = {
    'en': {
        'title': 'Prepare selected papers for offline reading',
        'intro': 'Check the actual files on this device. Retention marks only save your local '
                 'preference; use Sync connection to download missing managed files.',
        'scope': 'Results cover only the selected current PDF and registered deck assets. '
                 'They do not certify the whole workspace or unregistered files.',
        'verify': 'Verify selected files', 'pin': 'Keep offline', 'unpin': 'Remove offline mark',
        'close': 'Continue reading', 'cancel': 'Stop',
        'headers': ['Paper', 'PDF', 'Deck assets', 'Retention'],
        'empty': 'Select 1–100 papers first.',
        'loading': 'Reading local attachment metadata…',
        'verifying': 'Verifying local bytes and current source versions…',
        'pinning': 'Saving this device’s retention preference…',
        'planned': 'Metadata loaded. Verify local files before relying on offline availability.',
        'pinned': 'Retention preference saved on this device. Verify files before going offline.',
        'ready': 'Verified snapshot ({time}) for the selected current manifests. '
                 'Recheck after source or file changes and before going offline.',
        'partial': 'Offline readiness is incomplete. Check the rows below and sync missing files.',
        'cancelled': 'Stopped. No offline-readiness claim was made.',
        'cancelling': 'Stopping at a safe verification boundary…',
        'changed': 'The workspace changed. Close this dialog and select the papers again.',
        'failure': 'The check did not complete. Check selection, enrollment and local storage, '
                   'then retry. No offline-readiness claim was made.',
        'snapshot_changed': 'Selected source versions changed during checking. Verify again.',
        'enrollment': 'This research has not completed sync enrollment. This page checks only '
                      'synchronized current PDFs and canonical notes/guide decks; it does not '
                      'enroll or migrate existing local files.',
        'kept': 'Marked', 'not_kept': 'Not marked', 'unknown_inventory': 'Inventory unavailable',
        'source': 'Source not verified', 'verified_assets': '{done}/{total} verified',
    },
    'zh-TW': {
        'title': '準備所選論文的離線閱讀',
        'intro': '檢查這台裝置上的實際檔案。「保留離線」只記錄本機意願；'
                 '缺少的受管理檔案請至同步連線下載。',
        'scope': '結果只涵蓋所選的現行 PDF 與已登記簡報素材，'
                 '不代表整個工作區或未登記檔案都可離線使用。',
        'verify': '驗證所選檔案', 'pin': '保留離線', 'unpin': '取消離線標記',
        'close': '返回閱讀', 'cancel': '停止',
        'headers': ['論文', 'PDF', '簡報素材', '離線意願'],
        'empty': '請先選擇 1–100 篇論文。',
        'loading': '正在讀取本機附件資料…',
        'verifying': '正在驗證本機檔案與目前來源版本…',
        'pinning': '正在儲存這台裝置的離線保留意願…',
        'planned': '附件資料已載入；離線使用前請驗證實際檔案。',
        'pinned': '已儲存這台裝置的離線意願；出門前請驗證檔案。',
        'ready': '已驗證快照（{time}）：僅涵蓋所選現行附件。'
                 '來源或檔案變動後，以及離線使用前，請重新驗證。',
        'partial': '離線準備尚未完整；請核對下列狀態，並同步缺少的檔案。',
        'cancelled': '已停止，本次未宣稱離線準備完成。',
        'cancelling': '正在安全的驗證階段結束後停止…',
        'changed': '工作區已變更，請關閉視窗後重新選擇論文。',
        'failure': '檢查未完成；請核對所選論文、同步啟用與本機儲存後重試。本次未宣稱離線準備完成。',
        'snapshot_changed': '驗證期間來源版本有變更，請重新驗證。',
        'enrollment': '這份研究尚未完成同步啟用。此頁只檢查已同步的現行 PDF 與 notes/guide 簡報，'
                      '不會自動啟用同步或遷移本機檔案。',
        'kept': '已標記', 'not_kept': '未標記', 'unknown_inventory': '附件清單不完整',
        'source': '來源尚未驗證', 'verified_assets': '已驗證 {done}/{total}',
    },
}

STATES = {
    'en': {
        'unchecked': 'Not verified', 'missing_manifest': 'Manifest missing',
        'unbound': 'Files not bound', 'stale': 'Source changed', 'verified': 'Verified',
        'unconfigured': 'Storage not configured', 'budget_exceeded': 'Verification limit reached',
        'unavailable': 'Unavailable', 'invalid': 'Invalid bytes or metadata',
    },
    'zh-TW': {
        'unchecked': '尚未驗證', 'missing_manifest': '缺少附件清單',
        'unbound': '檔案尚未綁定', 'stale': '來源已變更', 'verified': '已驗證',
        'unconfigured': '尚未設定儲存', 'budget_exceeded': '已達驗證上限',
        'unavailable': '無法取得', 'invalid': '檔案或資料無效',
    },
}


def _service(database, *, current_path=None):
    # Service construction performs local reads, so it belongs on the worker too.
    from paper_daily.workspace_offline import OfflineService

    return OfflineService(database, current_path=current_path)


class OfflineDialog(QDialog):
    pins_changed = Signal()

    def __init__(self, database, paper_ids, parent=None, *, current_path=None,
                 service_factory=None, language='zh-TW'):
        super().__init__(parent)
        self.language = language if language in TEXT else 'en'
        self.t = TEXT[self.language]
        self.path = Path(database).resolve()
        self.current_path = current_path or (lambda: self.path)
        self.service_factory = service_factory or _service
        self.service = None
        self._worker = None
        self._closing = self._invalid = self.disposed = False
        self._plan = None
        self.last_verified_at = None
        try:
            info = self.path.stat()
            self._identity = (info.st_dev, info.st_ino)
        except OSError:
            self._identity = None
            self._invalid = True
        valid = (isinstance(paper_ids, (list, tuple)) and 0 < len(paper_ids) <= 100
                 and all(isinstance(value, str) and value and len(value) <= 512
                         for value in paper_ids))
        self.paper_ids = list(dict.fromkeys(paper_ids)) if valid else []
        self.setWindowTitle(self.t['title'])
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(760, 460)
        layout = QVBoxLayout(self)
        for key in ('intro', 'scope'):
            label = QLabel(self.t[key])
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(label)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(self.t['headers'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 300)
        self.table.setColumnWidth(1, 145)
        self.table.setAccessibleName(self.t['title'])
        layout.addWidget(self.table, 1)
        row = FlowLayout(spacing=6)
        self.verify_button = QPushButton(self.t['verify'])
        self.verify_button.clicked.connect(self.verify)
        self.pin_button = QPushButton(self.t['pin'])
        self.pin_button.clicked.connect(lambda: self.set_pins(True))
        self.unpin_button = QPushButton(self.t['unpin'])
        self.unpin_button.clicked.connect(lambda: self.set_pins(False))
        for button in (self.verify_button, self.pin_button, self.unpin_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.status = QLabel(self.t['loading'] if self.paper_ids else self.t['empty'])
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.cancel_button = QPushButton(self.t['cancel'])
        self.cancel_button.clicked.connect(self.cancel)
        self.close_button = QPushButton(self.t['close'])
        self.close_button.clicked.connect(self.close)
        bottom.addWidget(self.cancel_button)
        bottom.addStretch()
        bottom.addWidget(self.close_button)
        layout.addLayout(bottom)
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._check_context)
        self._poll.start()
        self._buttons()
        if self._invalid:
            self.status.setText(self.t['changed'])
        elif self.paper_ids:
            QTimer.singleShot(0, self.refresh)

    @property
    def busy(self):
        return self._worker is not None

    def _buttons(self):
        active = not self.busy and not self.disposed and not self._closing and not self._invalid
        self.verify_button.setEnabled(active and bool(self.paper_ids))
        rows = self._plan.get('papers', []) if self._plan else []
        mapped = bool(rows and len(rows) == len(self.paper_ids)
                      and all(row.get('portable_id') for row in rows))
        self.pin_button.setEnabled(active and mapped)
        self.unpin_button.setEnabled(active and mapped)
        self.cancel_button.setEnabled(self.busy and not self._closing)
        self.progress.setVisible(self.busy)

    def _check_context(self):
        try:
            info = self.path.stat()
            current = Path(self.current_path()).resolve()
            changed = current != self.path or (info.st_dev, info.st_ino) != self._identity
        except (OSError, ValueError):
            changed = True
        if changed:
            self._invalid = True
            if self.busy:
                self._worker.ticket.cancel()
            if not self.disposed:
                self.status.setText(self.t['changed'])
            self._buttons()
        return not changed

    def _start(self, kind):
        if (self.busy or self.disposed or self._closing or self._invalid
                or not self.paper_ids or not self._check_context()):
            return False

        def task(ticket, _progress):
            try:
                if self.service is None:
                    self.service = self.service_factory(self.path, current_path=self.current_path)
                if kind == 'verify':
                    return self.service.status(self.paper_ids, ticket)
                if kind in ('pin', 'unpin'):
                    self.service.set_pins(self.paper_ids, enabled=kind == 'pin', ticket=ticket)
                return self.service.plan(self.paper_ids, ticket)
            except EnrollmentRequired:
                return {'unavailable': 'enrollment'}

        worker = WorkspaceWorker(task, Ticket(), self)
        self._worker = worker
        self.status.setText(self.t['verifying'] if kind == 'verify' else
                            self.t['loading'] if kind == 'plan' else self.t['pinning'])
        worker.finished.connect(lambda: self._finished(worker, kind))
        self._buttons()
        worker.start()
        return True

    def refresh(self):
        return self._start('plan')

    def verify(self):
        return self._start('verify')

    def set_pins(self, enabled):
        return self._start('pin' if enabled else 'unpin')

    def cancel(self):
        if self.busy:
            self._worker.ticket.cancel()
            self.status.setText(self.t['cancelling'])

    def _finished(self, worker, kind):
        if self._worker is not worker:
            return
        self._worker = None
        valid = self._check_context()
        if not self.disposed and not self._closing and valid:
            if worker.error:
                self.status.setText(self.t.get(worker.error, self.t['failure']))
                if worker.error == 'changed':
                    self._invalid = True
            elif worker.ticket.cancelled:
                self.status.setText(self.t['cancelled'])
            elif worker.result.get('unavailable') == 'enrollment':
                self._plan = None
                self.last_verified_at = None
                self.status.setText(self.t['enrollment'])
            else:
                self._show_result(worker.result, verified=kind == 'verify')
                if kind in ('pin', 'unpin'):
                    self.status.setText(self.t['pinned'])
                    self.pins_changed.emit()
        worker.deleteLater()
        self._buttons()
        if self._closing:
            self.close()

    def _show_result(self, result, *, verified):
        self._plan = result
        selected = self.table.currentRow()
        selected_id = (self.table.item(selected, 0).data(Qt.ItemDataRole.UserRole)
                       if selected >= 0 and self.table.item(selected, 0) else None)
        scroll = self.table.verticalScrollBar().value()
        self.table.setRowCount(len(result['papers']))
        for row, paper in enumerate(result['papers']):
            title = QTableWidgetItem(paper['title'])
            title.setData(Qt.ItemDataRole.UserRole, paper['paper_id'])
            self.table.setItem(row, 0, title)
            state = paper['pdf']['state']
            self.table.setItem(row, 1, QTableWidgetItem(
                STATES[self.language].get(state, STATES[self.language]['invalid'])))
            artifacts = paper.get('artifacts', [])
            done = sum(item['state'] == 'verified' for item in artifacts)
            text = self.t['verified_assets'].format(done=done, total=len(artifacts))
            if not paper.get('artifact_inventory_available'):
                text = self.t['unknown_inventory']
            elif any(item.get('source_state') != 'current' for item in artifacts):
                text += ' · ' + self.t['source']
            self.table.setItem(row, 2, QTableWidgetItem(text))
            self.table.setItem(row, 3, QTableWidgetItem(
                self.t['kept'] if paper.get('pinned') else self.t['not_kept']))
            if paper['paper_id'] == selected_id:
                self.table.selectRow(row)
        self.table.resizeRowsToContents()
        self.table.verticalScrollBar().setValue(scroll)
        ready = (verified and result.get('ready') is True and bool(result['papers'])
                 and all(row.get('ready') is True for row in result['papers']))
        self.last_verified_at = (
            datetime.now().astimezone().isoformat(timespec='seconds') if ready else None)
        self.status.setText(self.t['ready'].format(time=self.last_verified_at) if ready else
                            self.t['partial'] if verified else self.t['planned'])

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
        self.done(QDialog.DialogCode.Rejected)
        event.accept()
