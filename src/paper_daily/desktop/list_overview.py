"""The parent of all reading lists, navigable with native list keys.

Each list is a card: its name, what is in it (papers, read, explained, pinned) and
a reading-progress bar. Beside the cards, the selected list's details: its note,
the same counts at a glance, and the unread papers it would open next (pinned
first), so the page answers "where was I" before a list is opened. The page is
kept to a readable width instead of spanning a wide screen.
"""

import html
import sqlite3

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from paper_daily import lists
from paper_daily.desktop import fonts

STATS_ROLE = Qt.ItemDataRole.UserRole + 1
CARD_HEIGHT = 78
COLUMN_WIDTH = 1180
DETAIL_WIDTH = 360


def summary(entries: list[dict]) -> str:
    """The line under the page title: how much research the workspace holds."""
    if not entries:
        return "還沒有清單"
    papers = sum(e["count"] for e in entries)
    read = sum(e["read"] for e in entries)
    return f"{len(entries)} 份清單 · 共 {papers:,} 篇 · 已讀 {read:,} 篇"


def card_facts(entry: dict) -> str:
    """What a list holds, in the order a reader asks about it."""
    facts = [f"{entry['count']:,} 篇", f"已讀 {entry['read']:,}"]
    if entry.get("explained"):
        facts.append(f"已講解 {entry['explained']:,}")
    if entry.get("pinned"):
        facts.append(f"置頂 {entry['pinned']:,}")
    return " · ".join(facts)


def up_next_html(papers: list[dict], pal: dict[str, str]) -> str:
    """The next unread papers as short lines, pinned ones marked."""
    if not papers:
        return f"<span style='color:{pal['muted']}'>這份清單都讀完了。</span>"
    lines = []
    for paper in papers:
        mark = (
            f"<span style='color:{pal['accent']};font-weight:600'>置頂</span>　"
            if paper["pinned"] else ""
        )
        lines.append(f"<p style='margin:0 0 6px 0'>{mark}{html.escape(paper['title'])}</p>")
    return "".join(lines)


class ListCard(QStyledItemDelegate):
    """Paints one list as a card; the item's text stays the plain label for
    accessibility and for code that reads it."""

    def __init__(self, palette: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.pal = palette
        self.name_font = fonts.font(fonts.SANS, 12)
        self.name_font.setBold(True)
        self.facts_font = fonts.font(fonts.SANS, 9)
        self.note_font = fonts.font(fonts.SANS, 9)
        self.pct_font = fonts.font(fonts.SANS, 11)
        self.pct_font.setBold(True)

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, CARD_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:
        pal = self.pal
        entry = index.data(STATS_ROLE) or {}
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = option.rect.adjusted(2, 4, -2, -4)
        painter.setBrush(QColor(pal["accentSoft"] if selected else pal["surface"]))
        edge = pal["accent"] if selected else pal["firm"] if hovered else pal["border"]
        painter.setPen(QPen(QColor(edge), 2 if selected else 1))
        painter.drawRoundedRect(card, 8, 8)

        bar_w = 168
        right = card.right() - 18
        left = card.left() + 18
        text_w = right - bar_w - 28 - left
        name = entry.get("name") or index.data(Qt.ItemDataRole.DisplayRole) or ""
        painter.setFont(self.name_font)
        painter.setPen(QColor(pal["ink"]))
        painter.drawText(
            QRect(left, card.top() + 12, text_w, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(self.name_font).elidedText(name, Qt.TextElideMode.ElideRight, text_w),
        )
        if entry:
            line = card_facts(entry)
            if entry.get("note"):
                line += "　" + " ".join(entry["note"].split())
            painter.setFont(self.facts_font)
            painter.setPen(QColor(pal["muted"]))
            painter.drawText(
                QRect(left, card.top() + 40, text_w, 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                QFontMetrics(self.facts_font).elidedText(
                    line, Qt.TextElideMode.ElideRight, text_w
                ),
            )
            count, read = entry.get("count", 0), entry.get("read", 0)
            share = read / count if count else 0.0
            painter.setFont(self.pct_font)
            painter.setPen(QColor(pal["done"] if count and read == count else pal["ink"]))
            painter.drawText(
                QRect(right - bar_w, card.top() + 12, bar_w, 24),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{share:.0%}" if count else "—",
            )
            track = QRect(right - bar_w, card.top() + 46, bar_w, 6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal["border"] if selected else pal["sunk"]))
            painter.drawRoundedRect(track, 3, 3)
            if read:
                filled = QRect(track.left(), track.top(), max(6, round(bar_w * share)), 6)
                painter.setBrush(QColor(pal["done"]))
                painter.drawRoundedRect(filled, 3, 3)
        painter.restore()


class ListOverview(QWidget):
    def __init__(self, window):
        super().__init__()
        self.win = window
        pal = window.pal
        self.setObjectName("listOverview")
        self.setStyleSheet(
            f"#listOverview{{background:{pal['ground']};}}"
            f"#listOverview QPushButton{{background:{pal['surface']};color:{pal['ink']};"
            f"border:1px solid {pal['firm']};border-radius:6px;padding:6px 14px;}}"
            f"#listOverview QPushButton:hover{{border-color:{pal['accent']};}}"
            f"#listOverview QPushButton:disabled{{color:{pal['faint']};"
            f"border-color:{pal['border']};}}"
            f"#listOverview QPushButton#primary{{background:{pal['accent']};color:#ffffff;"
            f"border-color:{pal['accent']};font-weight:600;}}"
            f"#listOverview QListWidget{{background:transparent;border:none;outline:none;}}"
            f"#emptyCard{{background:{pal['surface']};border:1px dashed {pal['firm']};"
            f"border-radius:10px;}}"
            f"#detail{{background:{pal['surface']};border:1px solid {pal['border']};"
            f"border-radius:10px;}}"
            f"#detail QLabel{{background:transparent;}}"
            f"#figure{{color:{pal['ink']};font-weight:700;}}"
            f"#figureLabel, #detailNote, #upNextTitle{{color:{pal['muted']};}}"
            f"#upNext{{color:{pal['ink']};}}"
        )
        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 28, 24, 16)
        column = QWidget()
        column.setMaximumWidth(COLUMN_WIDTH)
        outer.addStretch(1)
        outer.addWidget(column, 100)
        outer.addStretch(1)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("研究清單")
        title.setFont(fonts.font(fonts.SANS, 18))
        title.setStyleSheet(f"color:{pal['ink']};font-weight:700;")
        titles.addWidget(title)
        self.summary = QLabel()
        self.summary.setStyleSheet(f"color:{pal['muted']};")
        titles.addWidget(self.summary)
        header.addLayout(titles, 1)
        self.import_button = QPushButton("匯入研究資料包…")
        self.import_button.setToolTip("開啟資料包並預覽；沿用包內清單名稱與內容。")
        self.import_button.clicked.connect(window._import_bundle)
        header.addWidget(self.import_button, 0, Qt.AlignmentFlag.AlignBottom)
        self.import_link_button = QPushButton("網址匯入…")
        self.import_link_button.clicked.connect(lambda: window._import_bundle_link())
        header.addWidget(self.import_link_button, 0, Qt.AlignmentFlag.AlignBottom)
        self.export_button = QPushButton("匯出選取清單…")
        self.export_button.setEnabled(False)
        self.export_button.setToolTip("請先選擇清單。")
        self.export_button.clicked.connect(self.export_selected)
        header.addWidget(self.export_button, 0, Qt.AlignmentFlag.AlignBottom)
        self.create_button = QPushButton("＋ 建立清單")
        self.create_button.setObjectName("primary")
        self.create_button.clicked.connect(window._import_list)
        header.addWidget(self.create_button, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(header)

        self.empty_card = QFrame()
        self.empty_card.setObjectName("emptyCard")
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(32, 36, 32, 36)
        empty_layout.setSpacing(12)
        self.empty = QLabel(
            "你的研究工作區目前是空的。\n建立自己的清單，或匯入同事分享的研究資料包。"
        )
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setFont(fonts.font(fonts.SANS, 12))
        self.empty.setStyleSheet(f"color:{pal['muted']};")
        empty_layout.addWidget(self.empty)
        ai_row = QHBoxLayout()
        ai_row.addStretch(1)
        self.ai_button = QPushButton("登入／管理 AI 帳號…")
        self.ai_button.clicked.connect(window._ai_settings)
        ai_row.addWidget(self.ai_button)
        ai_row.addStretch(1)
        empty_layout.addLayout(ai_row)
        layout.addWidget(self.empty_card)

        self.body = QWidget()
        body = QHBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(18)
        self.view = QListWidget()
        self.view.setItemDelegate(ListCard(pal, self.view))
        self.view.setMouseTracking(True)
        self.view.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.view.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.view.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.view.model().rowsMoved.connect(self._save_order)
        self.view.itemActivated.connect(lambda _item: self.open_selected())
        self.view.currentItemChanged.connect(self._selection_changed)
        body.addWidget(self.view, 1)

        self.actions = QFrame()
        self.actions.setObjectName("detail")
        self.actions.setFixedWidth(DETAIL_WIDTH)
        detail = QVBoxLayout(self.actions)
        detail.setContentsMargins(20, 18, 20, 18)
        detail.setSpacing(10)
        self.selected_label = QLabel()
        self.selected_label.setWordWrap(True)
        self.selected_label.setFont(fonts.font(fonts.SANS, 14))
        self.selected_label.setStyleSheet(f"color:{pal['ink']};font-weight:700;")
        detail.addWidget(self.selected_label)
        self.note = QLabel()
        self.note.setObjectName("detailNote")
        self.note.setWordWrap(True)
        detail.addWidget(self.note)
        figures = QHBoxLayout()
        figures.setSpacing(6)
        self.figures: dict[str, QLabel] = {}
        for key, label in (("count", "篇"), ("read", "已讀"), ("explained", "已講解"),
                           ("pinned", "置頂")):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            number = QLabel("0")
            number.setObjectName("figure")
            number.setFont(fonts.font(fonts.SANS, 15))
            cell.addWidget(number)
            caption = QLabel(label)
            caption.setObjectName("figureLabel")
            cell.addWidget(caption)
            figures.addLayout(cell, 1)
            self.figures[key] = number
        detail.addLayout(figures)
        detail.addSpacing(4)
        up_title = QLabel("接下來讀")
        up_title.setObjectName("upNextTitle")
        detail.addWidget(up_title)
        self.up_next = QLabel()
        self.up_next.setObjectName("upNext")
        self.up_next.setWordWrap(True)
        self.up_next.setTextFormat(Qt.TextFormat.RichText)
        self.up_next.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        detail.addWidget(self.up_next)
        detail.addStretch(1)
        self.open_button = QPushButton("開啟清單")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.open_selected)
        detail.addWidget(self.open_button)
        row = QHBoxLayout()
        self.rename_button = QPushButton("重新命名…")
        self.rename_button.setEnabled(False)
        self.rename_button.clicked.connect(self.rename_selected)
        row.addWidget(self.rename_button)
        detail.addLayout(row)
        body.addWidget(self.actions)
        layout.addWidget(self.body, 1)

        footer = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{pal['muted']};")
        footer.addWidget(self.status, 1)
        hint = QLabel("拖曳調整順序 · F2 改名 · Enter／→ 開啟 · Alt＋← 回到上一層")
        hint.setStyleSheet(f"color:{pal['faint']};")
        footer.addWidget(hint)
        layout.addLayout(footer)

        # Return and Enter as well as Right: on macOS a list view takes Return as
        # "edit" and never emits itemActivated for it.
        for key in ("Right", "Return", "Enter"):
            shortcut = QShortcut(QKeySequence(key), self.view, self.open_selected)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut = QShortcut(QKeySequence("F2"), self.view, self.rename_selected)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)

    def _save_order(self, *_args):
        order = [self.view.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.view.count())]
        try:
            lists.reorder(order)
        except (ValueError, sqlite3.Error, OSError) as exc:
            self.status.setText(f"順序未儲存：{exc}")
            QTimer.singleShot(0, self.refresh)
            return
        self.win.refresh_lists()
        self.status.setText("清單順序已儲存。")

    def rename_selected(self):
        item = self.view.currentItem()
        list_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        entry = next((entry for entry in lists.all_lists() if entry["id"] == list_id), None)
        if entry is None:
            return
        name, accepted = QInputDialog.getText(
            self, "重新命名清單", "清單名稱", text=entry["name"]
        )
        if not accepted:
            return
        try:
            lists.rename(list_id, name)
        except (ValueError, sqlite3.Error, OSError) as exc:
            self.status.setText(str(exc))
            return
        self.win.refresh_lists()
        self.refresh()
        for index in range(self.view.count()):
            if self.view.item(index).data(Qt.ItemDataRole.UserRole) == list_id:
                self.view.setCurrentRow(index)
        self.win.queue_page.refresh()
        self.status.setText("名稱已儲存；論文與研究內容保持不變。")

    def refresh(self, *, preserve_state=False):
        selected = self.view.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        scroll = self.view.verticalScrollBar().value()
        self.view.clear()
        entries = {entry["id"]: entry for entry in lists.all_lists()}
        picker = self.win.list_picker
        for index in range(picker.count()):
            list_id = picker.itemData(index)
            item = QListWidgetItem(picker.itemText(index))
            item.setData(Qt.ItemDataRole.UserRole, list_id)
            item.setData(STATS_ROLE, entries.get(list_id))
            self.view.addItem(item)
        row = max(0, picker.currentIndex())
        if preserve_state and selected_id:
            row = next((i for i in range(self.view.count())
                        if self.view.item(i).data(Qt.ItemDataRole.UserRole) == selected_id), row)
        self.view.setCurrentRow(row)
        if preserve_state:
            self.view.verticalScrollBar().setValue(scroll)
        empty = self.view.count() == 0
        self.summary.setText(summary(list(entries.values())))
        self.empty_card.setVisible(empty)
        self.body.setVisible(not empty)
        if self.isVisible() and not preserve_state:
            self.view.setFocus()

    def _selection_changed(self, current, _previous):
        list_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        entry = current.data(STATS_ROLE) if current else None
        name = entry["name"] if entry else current.text() if current else ""
        self.open_button.setEnabled(current is not None)
        self.export_button.setEnabled(bool(list_id))
        self.rename_button.setEnabled(bool(list_id))
        self.selected_label.setText(name)
        note = " ".join(((entry or {}).get("note") or "").split())
        self.note.setText(note)
        self.note.setVisible(bool(note))
        for key, number in self.figures.items():
            number.setText(f"{(entry or {}).get(key, 0):,}")
        self.up_next.setText(up_next_html(lists.up_next(list_id, 6) if list_id else [],
                                          self.win.pal))
        self.export_button.setToolTip(
            f"匯出「{name}」整份清單的研究資料包：已下載 PDF、分析、筆記及簡報等已儲存內容。"
            if list_id else "請先選擇清單。"
        )

    def export_selected(self):
        item = self.view.currentItem()
        list_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if list_id:
            self.win._export_list_bundle(list_id)

    def open_selected(self):
        item = self.view.currentItem()
        if item is None:
            return
        index = self.win.list_picker.findData(item.data(Qt.ItemDataRole.UserRole))
        if index < 0:
            return
        if index == self.win.list_picker.currentIndex():
            self.win.show_queue()
        else:
            self.win.list_picker.setCurrentIndex(index)

    def showEvent(self, event):
        super().showEvent(event)
        self.view.setFocus()
