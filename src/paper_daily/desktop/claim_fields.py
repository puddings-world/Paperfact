"""Structured claim proposals; ordinary text controls retain native editing keys."""

import copy
import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from paper_daily import claim_draft_revision


def is_claim(data):
    if (data.get("scope") or {}).get("table") == "paper_claim_sets":
        return True
    retained = data.get("retained") or {}
    if data.get("origin") == "remote" and retained.get("feature") == "claims":
        return True
    if data.get("origin") == "archived_draft":
        try:
            return (
                claim_draft_revision._load(retained.get("body", "")).get("format")
                == claim_draft_revision.FORMAT
            )
        except (ValueError, TypeError, AttributeError):
            return False
    return False


def readable(row, words):
    if row is None:
        return words["absent"]
    if "body_json" not in row and isinstance(row.get("data"), dict):
        row = row["data"]
    if isinstance(row.get("body"), str):
        body = claim_draft_revision._load(row["body"])
    else:
        body = row.get("body_json", row)
    if isinstance(body, str):
        body = json.loads(body)
    report = body.get("report", {})
    claims = report.get("claims", []) if report else body.get("claims", [])
    lines = []
    for number, claim in enumerate(claims, 1):
        lines.extend([f"{number}. {claim['text']}", claim["judgment"]["reason"]])
        for passage in claim["passages"]:
            location = passage.get("location") or dict(state="unverified", page=passage.get("page"))
            state = words.get("loc_" + location["state"], location["state"])
            lines.append(
                f"{words['quote']} ({state}, "
                f"{words['page']}: {location['page'] or '—'})\n{passage['quote']}"
            )
        lines.append("")
    return "\n".join(lines) or words["absent"]


class ClaimFields(QWidget):
    changed = Signal()

    def __init__(self, words, parent=None):
        super().__init__(parent)
        self.words, self.value, self.loading = words, None, False
        self.claims = QListWidget()
        self.claims.setAccessibleName(words["claims"])
        self.claims.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.claims.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.claims.currentRowChanged.connect(self._show_claim)
        self.assertion = QPlainTextEdit()
        self.reason = QPlainTextEdit()
        self.quote = QPlainTextEdit()
        for control, label in (
            (self.assertion, "assertion"),
            (self.reason, "reason"),
            (self.quote, "quote"),
        ):
            control.setAccessibleName(words[label])
            control.setMaximumHeight(120)
            control.setMinimumHeight(65)
            control.textChanged.connect(self._changed)
        self.judgment = QComboBox()
        for key in ("unresolved", "inferred", "supported"):
            self.judgment.addItem(words[key], key)
        self.judgment.currentIndexChanged.connect(self._changed)
        self.passages = QComboBox()
        self.passages.setAccessibleName(words["passages"])
        self.passages.currentIndexChanged.connect(self._show_passage)
        self.page = QSpinBox()
        self.page.setRange(0, 100000)
        self.page.setSpecialValueText(words["auto_page"])
        self.page.valueChanged.connect(self._changed)
        self.location = QLabel()
        self.location.setWordWrap(True)
        self.clear_location = QPushButton(words["clear_location"])
        self.clear_location.clicked.connect(self._clear_location)
        self.citation_title, self.doi = QLineEdit(), QLineEdit()
        for control in (self.citation_title, self.doi):
            control.textEdited.connect(self._changed)
        detail = QWidget()
        form = QFormLayout(detail)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow(words["assertion"], self.assertion)
        form.addRow(words["judgment"], self.judgment)
        form.addRow(words["reason"], self.reason)
        form.addRow(words["passages"], self.passages)
        form.addRow(words["quote"], self.quote)
        form.addRow(words["page"], self.page)
        form.addRow(self.location)
        form.addRow(self.clear_location)
        self.external = QCheckBox(words["citation"])
        self.external.toggled.connect(self._changed)
        form.addRow(self.external)
        form.addRow(words["citation_title"], self.citation_title)
        form.addRow("DOI", self.doi)
        buttons = QHBoxLayout()
        self.add_passage, self.remove_passage = (
            QPushButton(words["add_passage"]),
            QPushButton(words["remove"]),
        )
        self.add_passage.clicked.connect(lambda: self._structural("passage", True))
        self.remove_passage.clicked.connect(lambda: self._structural("passage", False))
        buttons.addWidget(self.add_passage)
        buttons.addWidget(self.remove_passage)
        form.addRow(buttons)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(detail)
        navigation = QWidget()
        nav = QVBoxLayout(navigation)
        nav.setContentsMargins(0, 0, 0, 0)
        nav.addWidget(self.claims)
        self.add_claim, self.remove_claim = (
            QPushButton(words["add_claim"]),
            QPushButton(words["remove"]),
        )
        self.add_claim.clicked.connect(lambda: self._structural("claim", True))
        self.remove_claim.clicked.connect(lambda: self._structural("claim", False))
        nav.addWidget(self.add_claim)
        nav.addWidget(self.remove_claim)
        self.split = QSplitter()
        self.split.addWidget(navigation)
        self.split.addWidget(scroll)
        self.split.setSizes([210, 600])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.split)

    def set_draft(self, value):
        self.loading = True
        self.value = copy.deepcopy(value)
        self.claims.clear()
        self.claims.addItems([item["text"][:80] or "…" for item in self.value["claims"]])
        self.loading = False
        self.claims.setCurrentRow(0)
        self._show_claim()

    def draft(self):
        return copy.deepcopy(self.value)

    def _claim(self):
        index = self.claims.currentRow()
        return self.value["claims"][index] if self.value is not None and index >= 0 else None

    def _passage(self):
        claim, index = self._claim(), self.passages.currentIndex()
        return claim["passages"][index] if claim is not None and index >= 0 else None

    def _show_claim(self, *_args):
        claim = self._claim()
        if self.loading or claim is None:
            return
        self.loading = True
        self.assertion.setPlainText(claim["text"])
        self.reason.setPlainText(claim["judgment"]["reason"])
        self.judgment.setCurrentIndex(self.judgment.findData(claim["judgment"]["status"]))
        self.passages.clear()
        self.passages.addItems(
            [f"{index + 1}. {item['quote'][:65]}" for index, item in enumerate(claim["passages"])]
        )
        self.loading = False
        self._show_passage()
        self.remove_claim.setEnabled(len(self.value["claims"]) > 1)
        self.add_claim.setEnabled(len(self.value["claims"]) < 16)
        self.add_passage.setEnabled(
            sum(len(item["passages"]) for item in self.value["claims"]) < 48
        )

    def _show_passage(self, *_args):
        if self.loading:
            return
        passage = self._passage()
        self.loading = True
        self.quote.setPlainText(passage["quote"] if passage else "")
        self.page.setValue((passage["page"] or 0) if passage else 0)
        anchor = passage.get("anchor") if passage else None
        self.location.setText(
            self.words["saved_location"].format(page=anchor["p0"] + 1)
            if anchor
            else self.words["auto_location"]
        )
        citation = (passage or {}).get("citation") or {}
        self.external.setChecked(bool(citation))
        self.citation_title.setText(citation.get("title") or "")
        self.doi.setText(citation.get("doi") or "")
        for control in (self.quote, self.page, self.external, self.remove_passage):
            control.setEnabled(passage is not None)
        self.clear_location.setEnabled(anchor is not None)
        self.citation_title.setEnabled(bool(citation))
        self.doi.setEnabled(bool(citation))
        self.loading = False

    def _changed(self, *_args):
        claim = self._claim()
        if self.loading or claim is None:
            return
        claim["text"] = self.assertion.toPlainText()
        claim["judgment"] = dict(
            status=self.judgment.currentData(), reason=self.reason.toPlainText()
        )
        self.claims.currentItem().setText(claim["text"][:80] or "…")
        passage = self._passage()
        if passage is not None:
            quote, page = self.quote.toPlainText(), self.page.value() or None
            if (quote, page) != (passage["quote"], passage["page"]):
                passage["anchor"] = None
                self.location.setText(self.words["auto_location"])
                self.clear_location.setEnabled(False)
            passage.update(quote=quote, page=page)
            if self.external.isChecked():
                prior = passage.get("citation") or {}
                passage["citation"] = dict(
                    paper_id=prior.get("paper_id"),
                    title=self.citation_title.text() or None,
                    doi=self.doi.text() or None,
                )
            else:
                passage.pop("citation", None)
            self.citation_title.setEnabled(self.external.isChecked())
            self.doi.setEnabled(self.external.isChecked())
        self.changed.emit()

    def _clear_location(self):
        passage = self._passage()
        if passage is not None:
            passage["anchor"] = None
            self.page.setValue(0)
            self._show_passage()
            self.changed.emit()

    def _structural(self, kind, adding):
        if self.value is None:
            return
        items = self.value["claims"] if kind == "claim" else self._claim()["passages"]
        if adding:
            total = (
                len(items)
                if kind == "claim"
                else sum(len(item["passages"]) for item in self.value["claims"])
            )
            if total >= (16 if kind == "claim" else 48):
                return
            items.append(
                dict(text="", judgment=dict(status="unresolved", reason=""), passages=[])
                if kind == "claim"
                else dict(quote="", page=None, anchor=None)
            )
        elif items and (kind != "claim" or len(items) > 1):
            del items[self.claims.currentRow() if kind == "claim" else self.passages.currentIndex()]
        else:
            return
        if kind == "claim":
            value = self.draft()
            self.set_draft(value)
            self.claims.setCurrentRow(len(items) - 1 if adding else 0)
        else:
            self._show_claim()
            self.passages.setCurrentIndex(len(items) - 1 if adding else 0)
        self.changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.split.setOrientation(
            Qt.Orientation.Vertical if self.width() < 650 else Qt.Orientation.Horizontal
        )
