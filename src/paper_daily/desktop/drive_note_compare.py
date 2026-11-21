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
        chat = cards[0].get("feature") == "chat"
        if chat:
            self.setWindowTitle(tr("Compare Q&A versions", "比較問答版本"))
        reading = cards[0].get("feature") == "reading"
        if reading:
            self.setWindowTitle(tr("Compare reading status", "比較閱讀狀態"))
        details = cards[0].get("feature") == "list"
        if details:
            self.setWindowTitle(tr("Compare list details", "比較清單名稱與說明"))
        self.resize(900, 450)
        layout = QVBoxLayout(self)
        picker = QComboBox()
        for card in cards:
            if chat:
                picker.addItem(f"{card['title']} · {card['question']}")
                continue
            if details:
                picker.addItem(tr("Conflicting list details", "有衝突的清單欄位"))
                continue
            picker.addItem(card["title"] if guides or reading
                           else f"{card['title']} · #{card['key']}")
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
                    view.setPlainText(tr("Deleted on this device", "這則問答已在本機刪除")
                                      if chat and key == "local" else
                                      tr("No common version", "尚無共同版本"))
                    continue
                if details:
                    labels = {"name": tr("Name", "名稱"), "note": tr("Description", "說明")}
                    view.setPlainText("\n\n".join(
                        f"{labels[field]}\n{payload[field]}" for field in card["fields"]))
                    continue
                if reading:
                    states = {"pending": tr("Pending", "待讀"), "read": tr("Read", "已讀"),
                              "skipped": tr("Skipped", "已略過"),
                              "deferred": tr("Deferred", "稍後讀"),
                              "delivered": tr("Delivered", "已推送")}
                    lines = [states[payload["state"]]]
                    for name, label in (("delivered_at", tr("Delivered", "推送時間")),
                                        ("read_at", tr("Read at", "已讀時間"))):
                        if payload[name]:
                            lines.append(f"{label}  {payload[name]}")
                    view.setPlainText("\n".join(lines))
                    continue
                if chat:
                    view.setPlainText(payload["body"])
                    continue
                names = ("spec", "written_at") if guides else (
                    "kind", "page", "created_at", "anchor")
                fields = [name for name in names if any(
                    card[k][name] != (card["base"] or {}).get(name) for k in ("local", "remote")
                )]
                metadata = [f"{name}: {json.dumps(payload[name], ensure_ascii=False)}"
                            for name in fields]
                view.setPlainText("\n\n".join([payload["body"], *metadata]))

        row = QHBoxLayout()
        layout.addLayout(row)
        for choice, label in (("local", tr("Keep this device's version", "採用本機版本")),
                              ("remote", tr("Use Drive version", "採用 Drive 版本"))):
            button = QPushButton(label)
            button.setAutoDefault(False)
            button.clicked.connect(lambda _, value=choice: choose(value))
            row.addWidget(button)
            if choice == "local":
                local_button = button

        def select_card(index):
            display(index)
            removed = chat and cards[index]["local"] is None
            local_button.setText(tr("Keep deleted on this device", "只在本機保留刪除狀態")
                                 if removed else tr("Keep this device's version", "採用本機版本"))

        picker.currentIndexChanged.connect(select_card)
        select_card(0)
        cancel = QPushButton(tr("Decide later", "稍後決定"))
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)

        def choose(value):
            self.decision = cards[picker.currentIndex()], value
            self.accept()
