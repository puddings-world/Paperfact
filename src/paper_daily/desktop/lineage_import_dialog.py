"""Saved versus incoming native Lineage comparison; no research writes or AI."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from paper_daily import lineage_sets

COPY = dict(
    title="Compare lineage analyses",
    current="Current version",
    incoming="Incoming version",
    keep="Keep current",
    replace="Use incoming; keep current in history",
    adopt="Keep identical content and include it in sync",
    adoption=("The contents match exactly. Review the package originals before "
              "including this analysis in sync."),
    confirm="Continue with these choices",
    cancel="Cancel",
    choice="For this analysis:",
    unavailable="Replacement is unavailable for an unowned, removed or differently bound analysis.",
    empty="No active saved analysis. Restoration is a separate action.",
    scope="Quotations locate original text; scientific interpretations still need review.",
)
ZH = dict(
    title="\u6bd4\u8f03\u8108\u7d61\u5206\u6790",
    current="\u672c\u6a5f\u7248\u672c",
    incoming="\u50b3\u5165\u7248\u672c",
    keep="\u4fdd\u7559\u672c\u6a5f",
    replace="\u63a1\u7528\u50b3\u5165\u7248\uff0c\u4fdd\u7559\u820a\u7248\u6b77\u53f2",
    adopt="\u4fdd\u7559\u76f8\u540c\u5167\u5bb9\u4e26\u7d0d\u5165\u540c\u6b65",
    adoption="\u5167\u5bb9\u5b8c\u5168\u76f8\u540c\u3002\u8acb\u6838\u5c0d\u7814\u7a76\u5305\u539f\u6587\u5f8c\uff0c\u518d\u5c07\u672c\u5206\u6790\u7d0d\u5165\u540c\u6b65\u3002",
    confirm="\u4f9d\u9019\u4e9b\u9078\u64c7\u7e7c\u7e8c",
    cancel="\u53d6\u6d88",
    choice="\u672c\u4efd\u5206\u6790\uff1a",
)


def version_text(body, written_at, empty):
    if body is None:
        return empty
    lineage_sets.validate(body)
    generation = body["generation"]
    model = generation["returned_model"] or generation["requested_model"] or "not recorded"
    lines = [
        f"Saved: {written_at}",
        f"Model: {generation['backend']} / {model}",
    ]
    sources = {s["id"]: s["identity"]["title"] for s in body["report"]["sources"]}
    stages = dict(
        prior_gap="Earlier gap",
        current_change="This paper's contribution",
        later_development="Later development",
    )
    for statement in body["report"]["statements"]:
        lines.extend(["", stages[statement["stage"]], statement["text"]])
        for passage in statement["passages"]:
            location = passage["location"]
            lines.extend(
                [
                    f"Original: {sources[passage['source_id']]}",
                    f"Location: {location['state']}; page: {location.get('page') or '?'}",
                    passage["quote"],
                ]
            )
    return "\n".join(lines)


class LineageImportDialog(QDialog):
    def __init__(self, conflicts, parent=None, *, language="en"):
        super().__init__(parent)
        if not conflicts or len({r["id"] for r in conflicts}) != len(conflicts):
            raise ValueError("A comparison needs distinct actual Lineage versions")
        self.rows = conflicts
        self.choices = {r["id"]: "keep" for r in conflicts}
        self.t = {**COPY, **(ZH if language.startswith("zh") else {})}
        self.setWindowTitle(self.t["title"])
        self.resize(1050, 680)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        for index, row in enumerate(conflicts):
            self.list.addItem(f"{index + 1}. " + " ".join(row["title"].split())[:100])
            self.list.item(index).setToolTip(row["title"] + "\n" + row["incoming"]["corpus_id"])
        panels = QWidget()
        panel_layout = QVBoxLayout(panels)
        choice_row = QHBoxLayout()
        choice_row.addWidget(QLabel(self.t["choice"]))
        self.choice = QComboBox()
        choice_row.addWidget(self.choice, 1)
        panel_layout.addLayout(choice_row)
        self.reason = QLabel()
        self.reason.setWordWrap(True)
        panel_layout.addWidget(self.reason)
        compare = QSplitter(Qt.Orientation.Horizontal)
        self.current = QPlainTextEdit()
        self.incoming = QPlainTextEdit()
        for label, editor in (
            (self.t["current"], self.current),
            (self.t["incoming"], self.incoming),
        ):
            editor.setReadOnly(True)
            column = QWidget()
            content = QVBoxLayout(column)
            content.addWidget(QLabel(label))
            content.addWidget(editor)
            compare.addWidget(column)
        panel_layout.addWidget(compare, 1)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.list)
        split.addWidget(panels)
        split.setSizes([230, 820])
        layout.addWidget(split, 1)
        notice = QLabel(self.t["scope"])
        notice.setWordWrap(True)
        layout.addWidget(notice)
        buttons = QHBoxLayout()
        self.confirm = QPushButton(self.t["confirm"])
        self.cancel = QPushButton(self.t["cancel"])
        self.confirm.clicked.connect(self.accept)
        self.cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.confirm)
        layout.addLayout(buttons)
        self.list.currentRowChanged.connect(self._selected)
        self.choice.currentIndexChanged.connect(self._changed)
        self.list.setCurrentRow(0)

    def _selected(self, index):
        if index < 0:
            self.confirm.setEnabled(False)
            return
        row = self.rows[index]
        self.choice.blockSignals(True)
        self.choice.clear()
        self.choice.addItem(self.t["keep"], "keep")
        if row["can_replace"]:
            self.choice.addItem(self.t["replace"], "replace")
        if row.get("can_adopt", False):
            self.choice.addItem(self.t["adopt"], "adopt")
        self.choice.setCurrentIndex(self.choice.findData(self.choices[row["id"]]))
        self.choice.blockSignals(False)
        self.reason.setText(self.t["adoption"] if row.get("can_adopt", False) else
                            ("" if row["can_replace"] else self.t["unavailable"]))
        self.current.setPlainText(version_text(row["current"], row["current_at"], self.t["empty"]))
        self.incoming.setPlainText(
            version_text(row["incoming"], row["incoming_at"], self.t["empty"])
        )
        self.confirm.setEnabled(True)
        self._summary()

    def _changed(self, _index):
        index = self.list.currentRow()
        if index >= 0:
            self.choices[self.rows[index]["id"]] = self.choice.currentData()
            self._summary()

    def _summary(self):
        changed = sum(c == "replace" for c in self.choices.values())
        adopted = sum(c == "adopt" for c in self.choices.values())
        self.summary.setText(
            f"Analyses: {len(self.rows)} | Use incoming: {changed} | "
            f"Include in sync: {adopted} | Keep current: {len(self.rows) - changed - adopted}"
        )
