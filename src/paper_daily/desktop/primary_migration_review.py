"""One contextual, native review group; execution remains owned by WorkspaceDialog."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class _SummaryLabel(QLabel):
    """Keep wrapped source identity fully readable inside the scrolling review."""

    def _fit_height(self):
        height = max(0, self.heightForWidth(self.width()))
        if height != self.minimumHeight():
            self.setMinimumHeight(height)

    def setText(self, text):
        super().setText(text)
        self._fit_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()


class PrimaryMigrationReview(QWidget):
    review_requested = Signal(str)
    stage_requested = Signal(object)
    commit_requested = Signal()

    def __init__(self, parent=None, *, zh=False):
        super().__init__(parent)
        self.zh = zh
        self.catalog = self.plan = None
        self._active = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.review_button = QPushButton(
            "檢查備份用本機 PDF…" if zh else "Review local PDFs for backup…"
        )
        self.review_button.clicked.connect(lambda: self.review_requested.emit(""))
        layout.addWidget(self.review_button)
        self.details = QWidget()
        details = QVBoxLayout(self.details)
        details.setContentsMargins(0, 0, 0, 0)
        self.summary = _SummaryLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        policy = self.summary.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.summary.setSizePolicy(policy)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details.addWidget(self.summary)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(["論文", "本機 PDF"] if zh else ["Paper", "Local PDF"])
        self.table.setRootIsDecorated(False)
        self.table.setWordWrap(True)
        self.table.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(lambda *_: self._buttons())
        details.addWidget(self.table)
        row = QHBoxLayout()
        self.next_button = QPushButton("下一頁" if zh else "Next page")
        self.next_button.clicked.connect(self._next)
        self.stage_button = QPushButton(
            "檢查並暫存所選 PDF" if zh else "Check and stage selected PDFs"
        )
        self.stage_button.clicked.connect(lambda: self.stage_requested.emit(self.selected()))
        row.addWidget(self.next_button)
        row.addWidget(self.stage_button)
        details.addLayout(row)
        self.commit_button = QPushButton("確認準備備份用 PDF" if zh else "Confirm PDFs for backup")
        self.commit_button.clicked.connect(lambda: self.commit_requested.emit())
        details.addWidget(self.commit_button)
        layout.addWidget(self.details)
        self.details.hide()
        self._buttons()

    def selected(self):
        return tuple(
            item.data(0, Qt.ItemDataRole.UserRole)
            for index in range(self.table.topLevelItemCount())
            if (item := self.table.topLevelItem(index)).checkState(0) == Qt.CheckState.Checked
        )

    def _next(self):
        if self.catalog is not None and self.catalog.after:
            self.review_requested.emit(self.catalog.after)

    def set_active(self, value):
        self._active = value
        self._buttons()

    def _buttons(self):
        self.review_button.setEnabled(self._active and self.plan is None)
        self.table.setEnabled(self._active and self.plan is None)
        self.next_button.setEnabled(
            self._active
            and self.plan is None
            and self.catalog is not None
            and self.catalog.after is not None
        )
        selected = self.selected()
        limit = 1 if self.catalog is not None and self.catalog.bootstrap else 16
        self.stage_button.setEnabled(
            self._active and self.plan is None and 1 <= len(selected) <= limit
        )
        self.commit_button.setEnabled(self._active and self.plan is not None)
        self.commit_button.setVisible(self.plan is not None)

    def show_catalog(self, catalog):
        self.catalog, self.plan = catalog, None
        self.table.blockSignals(True)
        self.table.clear()
        for row in catalog.items:
            text = (
                ("尚未驗證" if self.zh else "Not yet verified")
                if row.status == "legacy"
                else ("已受管理" if self.zh else "Managed")
                if row.status == "managed"
                else ("無法準備" if self.zh else "Not eligible")
            )
            item = QTreeWidgetItem([row.title, text])
            item.setData(0, Qt.ItemDataRole.UserRole, row.paper_id)
            item.setToolTip(0, row.paper_id)
            if row.status == "legacy":
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
            self.table.addTopLevelItem(item)
        self.table.blockSignals(False)
        self.summary.setText(
            (
                "準備時會複製並驗證本機 PDF，確認前不會變更論文原始檔案關聯。"
                if self.zh
                else (
                    "Staging copies and verifies local PDFs. "
                    "Paper document associations change only after confirmation."
                )
            )
            + (
                "\n"
                + (
                    "讀取路徑尚未登記：先準備一份 PDF，再重新檢查其他論文。"
                    if self.zh
                    else (
                        "Reader paths are not registered: prepare one PDF first, "
                        "then review the remaining papers again."
                    )
                )
                if catalog.bootstrap
                else ""
            )
        )
        self.details.show()
        self._buttons()

    def show_plan(self, plan):
        self.plan = plan
        lines = [
            (
                f"{len(plan.items)} 份 PDF 已暫存；尚未變更原始檔案關聯。"
                if self.zh
                else f"{len(plan.items)} PDFs staged; no document associations changed."
            )
        ]
        lines.extend(
            f"{row.title}\n{row.size:,} bytes · SHA-256 {row.sha256}" for row in plan.items
        )
        self.summary.setText("\n\n".join(lines))
        self.details.show()
        self._buttons()

    def show_result(self, result):
        self.catalog = self.plan = None
        self.table.clear()
        suffix = (
            (
                "已停止；已完成的論文保留。"
                if self.zh
                else "Stopped; completed papers remain prepared."
            )
            if result.outcome != "complete"
            else ""
        )
        self.summary.setText(
            (
                f"已準備 {len(result.committed)} 份；尚有 {len(result.remaining)} 份。"
                if self.zh
                else f"Prepared {len(result.committed)} PDFs; {len(result.remaining)} remain."
            )
            + "\n"
            + suffix
            + "\n"
            + (
                "尚未建立備份。請先按「重新檢查」，檢閱新狀態後再建立備份。"
                if self.zh
                else (
                    "Backup not created. Refresh and review the new status "
                    "before creating a backup."
                )
            )
        )
        self.details.show()
        self._buttons()

    def clear_plan(self):
        self.plan = None
        self._buttons()

    def clear_review(self):
        self.catalog = self.plan = None
        self.table.clear()
        self.summary.clear()
        self.details.hide()
        self._buttons()
