"""Visible, app-owned disposition for completed but unsaved slide results."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from paper_daily.desktop.ask import AskRunner
from paper_daily.pending_deck_result import PendingDeckResults

COPY = {
    "en": {
        "notice": (
            "Presentation completed, but is not saved. "
            "Retry saving, export a recovery copy, or explicitly discard it before leaving."
        ),
        "retry": "Retry saving",
        "export": "Export recovery copy…",
        "discard": "Discard…",
        "confirm": "Discard this unsaved result?",
        "warning": (
            "This result exists only in this app session. Discarding cannot be undone. "
            "Previously saved research stays unchanged."
        ),
        "retained": (
            "The result is now retained for review in its original workspace; "
            "the current presentation is unchanged."
        ),
        "exported": (
            "A verified recovery copy was exported. It contains slides, evidence "
            "and every captured image; it does not apply changes."
        ),
        "failed": "Still unsaved: {reason}",
        "working": "Saving the completed result; AI is not being called again…",
        "filter": "Paperfact draft recovery (*.paperfact-draft.json)",
    },
    "zh-TW": {
        "notice": "簡報已產生，但尚未儲存。請重試儲存、匯出救援副本，或明確放棄此結果，再離開。",
        "retry": "重試儲存",
        "export": "匯出救援副本…",
        "discard": "放棄此結果…",
        "confirm": "要放棄這份尚未儲存的結果嗎？",
        "warning": (
            "這份結果目前只保留在 App 記憶體中，放棄後無法復原。先前已儲存的研究內容不受影響。"
        ),
        "retained": "結果已保留在原工作區，等待核對；目前簡報未被替換。",
        "exported": "救援副本已匯出並核對，包含簡報、來源證據與所有已擷取圖片；未套用任何變更。",
        "failed": "仍未儲存：{reason}",
        "working": "正在儲存已完成的結果，不會再次呼叫 AI…",
        "filter": "Paperfact 草稿救援檔 (*.paperfact-draft.json)",
    },
}


class PendingDeckHub(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.results = PendingDeckResults()

    def hold(self, result):
        key = self.results.hold(result)
        self.changed.emit()
        return key


def hub():
    app = QApplication.instance()
    value = getattr(app, "_pending_deck_hub", None)
    if value is None:
        value = PendingDeckHub(app)
        app._pending_deck_hub = value
    return value


class PendingDeckPanel(QWidget):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.hub = hub()
        self.copy = COPY.get(getattr(pane.window(), "language", "zh-TW"), COPY["en"])
        self._action = False
        self.runner = AskRunner(self)
        layout = QVBoxLayout(self)
        self.notice = QLabel(self.copy["notice"])
        self.notice.setWordWrap(True)
        self.notice.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.notice.setMinimumWidth(0)
        layout.addWidget(self.notice)
        self.choice = QComboBox()
        self.choice.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.choice.setMinimumContentsLength(15)
        self.choice.setMinimumWidth(0)
        layout.addWidget(self.choice)
        self.detail = QLabel()
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.detail.setMinimumWidth(0)
        layout.addWidget(self.detail)
        actions = QHBoxLayout()
        self.retry_button = QPushButton(self.copy["retry"])
        self.export_button = QPushButton(self.copy["export"])
        self.discard_button = QPushButton(self.copy["discard"])
        for button, callback in (
            (self.retry_button, self.retry),
            (self.export_button, self.export),
            (self.discard_button, self.discard),
        ):
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.choice.currentIndexChanged.connect(self._details)
        self.hub.changed.connect(self.refresh)
        self.refresh()

    @property
    def pending(self):
        return self.hub.results.pending or self._action or self.runner.busy

    def _selected(self):
        key = self.choice.currentData()
        return next(((k, result) for k, result in self.hub.results.items() if k == key), None)

    def _details(self):
        selected = self._selected()
        detail = (
            (self.hub.results.context(selected[0]) + "\n" + str(selected[1].reason or ""))
            if selected
            else ""
        )
        self.detail.setText(detail)
        self.detail.setToolTip(detail)

    def refresh(self):
        selected = self.choice.currentData()
        self.choice.blockSignals(True)
        self.choice.clear()
        for key, result in self.hub.results.items():
            context = self.hub.results.label(key)
            self.choice.addItem(f"{result.deck.paper_title} — {result.deck.title} · {context}", key)
        index = self.choice.findData(selected)
        self.choice.setCurrentIndex(max(0, index))
        self.choice.blockSignals(False)
        self._details()
        self.setVisible(self.pending)
        if not self.hub.results.pending and self.runner.busy:
            QTimer.singleShot(25, self.refresh)
        self.choice.setEnabled(not self._action)
        for button in (self.retry_button, self.export_button, self.discard_button):
            button.setEnabled(self.pending and not self._action)
        # The parent finishes constructing its normal controls before attachment.
        if getattr(self.pane, "pending_panel", None) is self:
            self.pane._update_controls()

    def _run(self, key, *, destination=None):
        if self._action or self.runner.busy:
            return
        self._action = True
        self.refresh()
        self.pane.status.setText(self.copy["working"])
        owner, results = self.hub, self.hub.results

        def call(_prompt):
            try:
                if destination is None:
                    result = results.retry(key)
                    if not result.durable:
                        return None, result.reason or "Storage remains unavailable"
                    return "retained", "ok"
                results.export(key, destination)
                return "exported", "ok"
            except (ValueError, OSError, KeyError) as exc:
                return None, str(exc)
            finally:
                owner.changed.emit()

        try:
            self.runner.start("", self._done, self._failed, call=call, task="slides")
        except Exception:
            self._action = False
            self.refresh()
            raise

    def _done(self, outcome):
        self._action = False
        self.refresh()
        self.pane.status.setText(self.copy[outcome])

    def _failed(self, reason):
        self._action = False
        self.refresh()
        self.pane.status.setText(self.copy["failed"].format(reason=reason))

    def retry(self):
        selected = self._selected()
        if selected:
            self._run(selected[0])

    def export(self):
        if self._action or self.runner.busy:
            return
        selected = self._selected()
        if not selected:
            return
        from paper_daily.local_rescue_import import LocalRetention

        local = isinstance(selected[1], LocalRetention)
        filename = "Paperfact-recovery.paperfact-draft." + ("zip" if local else "json")
        file_filter = "Paperfact (*.paperfact-draft.zip)" if local else self.copy["filter"]
        self._action = True
        self.refresh()
        try:
            path, _kind = QFileDialog.getSaveFileName(
                self, self.copy["export"], filename, file_filter,
            )
        finally:
            self._action = False
            self.refresh()
        if path:
            self._run(selected[0], destination=path)

    def discard(self):
        if self._action or self.runner.busy:
            return
        existing = getattr(self, "_confirmation", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            return
        selected = self._selected()
        if not selected:
            return
        key, result = selected
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            self.copy["confirm"],
            self.copy["warning"] + "\n\n" + self.hub.results.context(key),
            QMessageBox.StandardButton.NoButton,
            self,
        )
        box.setTextFormat(Qt.TextFormat.PlainText)
        discard = box.addButton(self.copy["discard"], QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        self._confirmation = box

        def finished(_code):
            if box.clickedButton() is discard:
                try:
                    self.hub.results.discard(key, expected=result)
                except ValueError as exc:
                    self.pane.status.setText(str(exc))
                self.hub.changed.emit()
            box.deleteLater()

        box.finished.connect(finished)
        box.open()
