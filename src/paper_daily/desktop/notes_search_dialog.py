"""Search every paper's notes and highlights; a result opens on its passage."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from paper_daily import notes_search
from paper_daily.store import connect


class NotesSearchDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("搜尋全部筆記")
        self.resize(640, 460)
        layout = QVBoxLayout(self)
        self.box = QLineEdit()
        self.box.setPlaceholderText("輸入字詞，在所有論文的筆記與螢光筆中搜尋（空白分隔＝都要有）")
        self.box.setClearButtonEnabled(True)
        layout.addWidget(self.box)
        self.results = QListWidget()
        self.results.setWordWrap(True)
        layout.addWidget(self.results, 1)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{win.pal['faint']};font-size:11px;")
        layout.addWidget(self.status)
        self._timer = QTimer(self, singleShot=True, interval=150)
        self._timer.timeout.connect(self.run)
        self.box.textChanged.connect(lambda _t: self._timer.start())
        self.box.returnPressed.connect(self.open_current)
        self.results.itemActivated.connect(lambda _i: self.open_current())

    def keyPressEvent(self, event) -> None:
        # Arrow keys move through results without leaving the search box.
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.results.count():
            step = 1 if event.key() == Qt.Key.Key_Down else -1
            row = max(0, min(self.results.count() - 1, self.results.currentRow() + step))
            self.results.setCurrentRow(row)
            return
        super().keyPressEvent(event)

    def run(self) -> None:
        self.results.clear()
        query = self.box.text().strip()
        if not query:
            self.status.setText("")
            return
        with connect() as conn:
            hits = notes_search.search(conn, query)
        for hit in hits:
            label = "問 AI" if hit["ask"] else "筆記" if hit["kind"] == "note" else "螢光筆"
            page = f" · 第 {hit['page']} 頁" if hit["page"] else ""
            item = QListWidgetItem(f"{hit['title']}\n{label}{page}　{hit['snippet']}")
            item.setData(Qt.ItemDataRole.UserRole, hit)
            self.results.addItem(item)
        if hits:
            self.results.setCurrentRow(0)
        self.status.setText(f"{len(hits)} 筆" if hits else "沒有符合的筆記或螢光筆。")

    def open_current(self) -> None:
        item = self.results.currentItem()
        if item is None:
            return
        hit = item.data(Qt.ItemDataRole.UserRole)
        if not self.win.open_anywhere(hit["paper_id"]):
            self.status.setText("這篇不在佇列或任何清單裡，無法開啟。")
            return
        self.win.reader_page.reveal(hit["anchor"], hit["page"])
        self.accept()
