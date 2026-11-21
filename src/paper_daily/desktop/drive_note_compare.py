"""Choose a complete, reviewed version of one conflicted reader note."""

import json

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class NoteComparison(QDialog):
    def __init__(self, cards, parent):
        super().__init__(parent)
        tr = parent.tr
        self.decision = None
        guides = cards[0].get("feature") == "dive"
        self.setWindowTitle(tr("Compare guide versions", "比較講解版本") if guides
                            else tr("Compare note versions", "比較筆記版本"))
        self.resize(900, 450)
        layout = QVBoxLayout(self)
        picker = QComboBox()
        for card in cards:
            picker.addItem(card["title"] if guides else f"{card['title']} · #{card['key']}")
        layout.addWidget(picker)
        columns = QHBoxLayout()
        layout.addLayout(columns)
        views = {}
        for key, label in (("base", tr("Common version", "共同版本")),
                           ("local", tr("This device", "本機版本")), ("remote", "Drive")):
            column = QVBoxLayout()
            columns.addLayout(column)
            column.addWidget(QLabel(label))
            view = views[key] = QPlainTextEdit()
            view.setAccessibleName(label)
            view.setReadOnly(True)
            column.addWidget(view)

        def display(index):
            card = cards[index]
            for key, view in views.items():
                payload = card[key]
                if payload is None:
                    view.setPlainText(tr("No common version", "尚無共同版本"))
                    continue
                names = ("spec", "written_at") if guides else (
                    "kind", "page", "created_at", "anchor")
                fields = [name for name in names if any(
                    card[k][name] != (card["base"] or {}).get(name) for k in ("local", "remote")
                )]
                metadata = [f"{name}: {json.dumps(payload[name], ensure_ascii=False)}"
                            for name in fields]
                view.setPlainText("\n\n".join([payload["body"], *metadata]))

        picker.currentIndexChanged.connect(display)
        display(0)
        row = QHBoxLayout()
        layout.addLayout(row)
        for choice, label in (("local", tr("Keep this device's version", "採用本機版本")),
                              ("remote", tr("Use Drive version", "採用 Drive 版本"))):
            button = QPushButton(label)
            button.setAutoDefault(False)
            button.clicked.connect(lambda _, value=choice: choose(value))
            row.addWidget(button)
        cancel = QPushButton(tr("Decide later", "稍後決定"))
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)

        def choose(value):
            self.decision = cards[picker.currentIndex()], value
            self.accept()
