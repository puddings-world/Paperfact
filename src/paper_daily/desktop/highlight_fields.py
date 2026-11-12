"""Human highlight fields; native text editing and explicit repeated-quote choices."""

import copy

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from paper_daily import highlight_draft_revision


def is_highlight(data):
    if (data.get("scope") or {}).get("table") == "paper_highlight_analysis":
        return True
    retained = data.get("retained") or {}
    if data.get("origin") == "remote":
        return retained.get("feature") == "highlight_analysis"
    if data.get("origin") == "archived_draft":
        try:
            return (
                highlight_draft_revision._load(retained.get("body", "")).get("format")
                == highlight_draft_revision.FORMAT
            )
        except (ValueError, TypeError, AttributeError):
            return False
    return False


def readable(value, words):
    if value is None:
        return words["absent"]
    # An unresolved report intentionally has analysis=None; its per-quote issues
    # are still meaningful content and must not disappear behind that empty plan.
    if "all_quotes_located" not in value:
        value = value.get("analysis") or value
    if isinstance(value.get("data"), dict):
        value = value["data"]
    body = value.get("body_json", value.get("body", value))
    if isinstance(body, str):
        body = highlight_draft_revision._load(body)
    lines = []
    for index, item in enumerate(body.get("items", []), 1):
        lines.extend(
            [
                f"{index}. {item['text']}",
                words.get("role_" + item["kind"], item["kind"]),
                item["reason"],
                words["page"] + ": " + str(item.get("page") or "—"),
            ]
        )
        location = item.get("location")
        if location:
            lines.append(words.get("loc_" + location["state"], location["state"]))
        lines.append("")
    return "\n".join(lines) or words["absent"]


class HighlightTextEdit(QPlainTextEdit):
    def sizeHint(self):
        # A compact preferred size, not a fixed/max height: the splitter can grow it.
        return QSize(super().sizeHint().width(), 104)


class HighlightFields(QWidget):
    changed = Signal()

    def __init__(self, words, parent=None):
        super().__init__(parent)
        self.words, self.value, self.loading, self.report = words, None, False, None
        self.items = QListWidget()
        self.items.setAccessibleName(words["highlights"])
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.items.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.items.setMinimumHeight(90)
        self.items.currentRowChanged.connect(self._show)
        self.quote, self.reason = HighlightTextEdit(), HighlightTextEdit()
        for control, key in ((self.quote, "quote"), (self.reason, "reason")):
            control.setAccessibleName(words[key])
            control.setMinimumHeight(72)
            control.textChanged.connect(self._changed)
        self.quote.setPlaceholderText(words["quote_hint"])
        self.reason.setPlaceholderText(words["reason_hint"])
        self.role = QComboBox()
        for key in ("problem", "contribution", "method", "evidence", "limitation", "definition"):
            self.role.addItem(words["role_" + key], key)
        self.role.setAccessibleName(words["role"])
        self.role.currentIndexChanged.connect(self._changed)
        self.page = QSpinBox()
        self.page.setRange(0, 1000000)
        self.page.setSpecialValueText(words["auto_page"])
        self.page.setAccessibleName(words["page"])
        self.page.valueChanged.connect(self._changed)
        self.location = QLabel(words["auto_location"])
        self.location.setWordWrap(True)
        self.location.setTextFormat(Qt.TextFormat.PlainText)
        self.occurrences = QComboBox()
        self.occurrences.setAccessibleName(words["occurrence"])
        self.occurrences.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.occurrences.setMinimumContentsLength(16)
        self.occurrences.currentIndexChanged.connect(self._choose_occurrence)
        self.clear_location = QPushButton(words["clear_location"])
        self.clear_location.clicked.connect(self._clear_location)
        self.add_item, self.remove_item = (
            QPushButton(words["add_highlight"]),
            QPushButton(words["remove"]),
        )
        self.add_item.clicked.connect(self._add)
        self.remove_item.clicked.connect(self._remove)
        self.count = QLabel()
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_item)
        buttons.addWidget(self.remove_item)
        buttons.addStretch(1)
        buttons.addWidget(self.count)
        for button in (self.add_item, self.remove_item, self.clear_location):
            button.setAutoDefault(False)
        form = QFormLayout()
        form.addRow(words["role"], self.role)
        form.addRow(words["page"], self.page)
        pane = QWidget()
        content = QVBoxLayout(pane)
        content.addLayout(form)
        content.addWidget(QLabel(words["quote"]))
        content.addWidget(self.quote, 1)
        content.addWidget(QLabel(words["reason"]))
        content.addWidget(self.reason, 1)
        content.addWidget(self.location)
        content.addWidget(self.occurrences)
        content.addWidget(self.clear_location)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(pane)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.items)
        self.splitter.addWidget(scroll)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(buttons)
        layout.addWidget(self.splitter, 1)

    def set_draft(self, value):
        self.loading = True
        self.value, self.report = copy.deepcopy(value), None
        self.items.clear()
        for item in self.value["items"]:
            self.items.addItem(item["text"][:90] or "…")
            self.items.item(self.items.count() - 1).setToolTip(item["text"])
        self.items.setCurrentRow(0)
        self.loading = False
        self._show()
        self._controls()

    def draft(self):
        return copy.deepcopy(self.value)

    def _item(self):
        index = self.items.currentRow()
        return (
            self.value["items"][index]
            if self.value and 0 <= index < len(self.value["items"])
            else None
        )

    def _controls(self):
        count = len(self.value["items"]) if self.value else 0
        self.count.setText(str(count) + " / 32")
        self.add_item.setEnabled(0 < count < 32)
        self.remove_item.setEnabled(count > 1 and self.items.currentRow() >= 0)

    def _show(self, *_args):
        if self.loading:
            return
        item = self._item()
        self.loading = True
        for control in (self.quote, self.reason, self.role, self.page):
            control.setEnabled(item is not None)
        self.quote.setPlainText(item["text"] if item else "")
        self.reason.setPlainText(item["reason"] if item else "")
        self.role.setCurrentIndex(self.role.findData(item["kind"]) if item else 0)
        self.page.setValue((item["page"] or 0) if item else 0)
        self._location(item)
        self.loading = False
        self._controls()

    def _location(self, item):
        self.occurrences.clear()
        self.occurrences.addItem(self.words["choose_occurrence"], None)
        found = None
        if self.report and item is not None:
            found = self.report["items"][self.items.currentRow()]["location"]
        candidates = found["candidates"] if found else []
        for index, anchor in enumerate(candidates, 1):
            self.occurrences.addItem(
                self.words["occurrence_at"].format(index=index, page=anchor["p0"] + 1), anchor
            )
        self.occurrences.setVisible(bool(candidates))
        self.occurrences.setEnabled(bool(candidates))
        anchor = item.get("anchor") if item else None
        self.location.setText(
            self.words.get("loc_" + found["state"], found["state"])
            if found
            else self.words["saved_location"].format(page=anchor["p0"] + 1)
            if anchor
            else self.words["auto_location"]
        )
        self.clear_location.setEnabled(anchor is not None)

    def set_report(self, report):
        self.report = copy.deepcopy(report)
        self.loading = True
        self._location(self._item())
        self.loading = False

    def _changed(self, *_args):
        item = self._item()
        if self.loading or item is None:
            return
        quote, page = self.quote.toPlainText(), self.page.value() or None
        if (quote, page) != (item["text"], item["page"]):
            item["anchor"] = None
        item.update(
            text=quote, page=page, reason=self.reason.toPlainText(), kind=self.role.currentData()
        )
        self.report = None
        self.loading = True
        self._location(item)
        self.loading = False
        self.items.currentItem().setText(quote[:90] or "…")
        self.items.currentItem().setToolTip(quote)
        self.changed.emit()

    def _choose_occurrence(self, *_args):
        anchor = self.occurrences.currentData()
        item = self._item()
        if self.loading or item is None or anchor is None:
            return
        item.update(anchor=copy.deepcopy(anchor), page=anchor["p0"] + 1)
        self.report = None
        self._show()
        self.changed.emit()

    def _clear_location(self):
        item = self._item()
        if item is None:
            return
        item["anchor"] = None
        self.report = None
        self._show()
        self.changed.emit()

    def _add(self):
        if not self.value or len(self.value["items"]) >= 32:
            return
        self.value["items"].append(dict(text="", reason="", page=None, anchor=None, kind="method"))
        self.report = None
        self.items.addItem("…")
        self.items.setCurrentRow(len(self.value["items"]) - 1)
        self._controls()
        self.quote.setFocus()
        self.changed.emit()

    def _remove(self):
        if self._item() is None or len(self.value["items"]) <= 1:
            return
        index = self.items.currentRow()
        self.value["items"].pop(index)
        self.loading = True
        self.items.takeItem(index)
        self.items.setCurrentRow(min(index, len(self.value["items"]) - 1))
        self.loading, self.report = False, None
        self._show()
        self._controls()
        self.changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        orientation = Qt.Orientation.Vertical if self.width() < 700 else Qt.Orientation.Horizontal
        if self.splitter.orientation() != orientation:
            self.splitter.setOrientation(orientation)
            self.splitter.setSizes(
                [120, 320] if orientation == Qt.Orientation.Vertical else [220, 600]
            )
