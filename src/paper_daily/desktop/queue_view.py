"""The queue screen.

A model/view list rather than a widget per row. The first version built a QWidget
with three child labels for every visible paper and rebuilt all of them on each
keystroke -- about 1200 widgets per character typed, which made search unusable and
forced a 400-row cap to stay even close to responsive.

Here the model holds plain data, the delegate paints a row on demand, and only the
rows actually on screen are ever drawn. Filtering is a model reset, so the whole
5000-paper queue can be listed with no cap.
"""

from __future__ import annotations

import json
import re
import sqlite3
from uuid import uuid4

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QMimeData,
    QModelIndex,
    QProcess,
    QProcessEnvironment,
    QRect,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from paper_daily import runtime, venues
from paper_daily.desktop import ai_style, fonts
from paper_daily.desktop.focus_scope import scopes
from paper_daily.store import connect, get_kv, set_kv

ROW_HEIGHT = 74
# The pin toggle at the right end of every row.
PIN_W = 52
ROOT = runtime.bundle_root()
PAPER_ROLE = Qt.ItemDataRole.UserRole + 1

# The strip on the left where a click ticks the row instead of opening it. Opening is
# what a click on this list has always meant, so the two must not overlap.
MARK_W = 30
BOX = 15

# (label, key, reverse). The default key is None because the order it stands for is
# not a property of the rows: ranked reading order in the queue, and in a list the
# order someone chose.
#
# A missing citation count is unknown, not zero, but there is nowhere honest to put
# unknown in a sorted column, so it sorts as zero and the row shows no cites tag.
def _when(paper) -> tuple[int, int]:
    """(year, month). The month comes from the arXiv id ("2508.10215" is August
    2025) when it is the same year, so papers within one year are in order too."""
    m = re.match(r"(\d{2})(\d{2})\.", paper.arxiv_id or "")
    month = int(m[2]) if m and 2000 + int(m[1]) == (paper.year or 0) else 0
    return (paper.year or 0, month)


TYPE_ORDER = ("method", "system", "benchmark", "application", "principle")


def _analysed(paper) -> int:
    return sum((paper.has_dive, paper.has_cites, paper.has_later))


SORTS = [
    ("自訂順序", None, False),
    ("引用數 多 → 少", lambda p: p.citations or 0, True),
    ("時間 新 → 舊", lambda p: (_when(p), p.citations or 0), True),
    ("時間 舊 → 新", lambda p: (_when(p), -(p.citations or 0)), False),
    ("依發表處分組", lambda p: venues.group_key(p.venue, p.year), False),
    ("依論文類型分組", lambda p: (
        TYPE_ORDER.index(p.paper_type) if p.paper_type in TYPE_ORDER else len(TYPE_ORDER),
        -(p.year or 0),
    ), False),
    ("待分析的在前", lambda p: (_analysed(p), not p.has_pdf), False),
    ("被依賴數 多 → 少", lambda p: (p.dependents, p.citations or 0), True),
    ("最近標記已讀", lambda p: p.read_at or "", True),
    ("標題 A → Z", lambda p: p.title.lower(), False),
]


class PaperListModel(QAbstractListModel):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[tuple[int, object]] = []
        self.reorder = None
        self.can_reorder = False
        self._epoch = uuid4().hex

    def set_rows(self, rows: list[tuple[int, object]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self._epoch = uuid4().hex
        self.endResetModel()

    def flags(self, index):
        flags = super().flags(index)
        if self.can_reorder:
            flags |= (Qt.ItemFlag.ItemIsDragEnabled if index.isValid()
                      else Qt.ItemFlag.ItemIsDropEnabled)
        return flags

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def mimeTypes(self):
        return ["application/x-paperfact-paper-order"]

    def mimeData(self, indexes):
        data = QMimeData()
        rows = sorted({index.row() for index in indexes if index.isValid()})
        if self.can_reorder and len(rows) == 1:
            data.setData(self.mimeTypes()[0], json.dumps([self._epoch, rows[0]]).encode())
        return data

    def dropMimeData(self, data, action, row, column, parent):
        if not self.can_reorder or action != Qt.DropAction.MoveAction or parent.isValid():
            return False
        try:
            epoch, source = json.loads(bytes(data.data(self.mimeTypes()[0])))
        except (ValueError, TypeError):
            return False
        if epoch != self._epoch or type(source) is not int:
            return False
        return self.moveRows(QModelIndex(), source, 1, QModelIndex(),
                             len(self._rows) if row < 0 else row)

    def moveRows(self, source_parent, source, count, destination_parent, destination):
        if (not self.can_reorder or self.reorder is None or source_parent.isValid()
                or destination_parent.isValid() or count != 1
                or not 0 <= source < len(self._rows)
                or not 0 <= destination <= len(self._rows)
                or destination in (source, source + 1)):
            return False
        rows = list(self._rows)
        moved = rows.pop(source)
        rows.insert(destination - (destination > source), moved)
        if not self.reorder([paper.id for _position, paper in rows]):
            return False
        self.beginMoveRows(source_parent, source, source, destination_parent, destination)
        self._rows = [(i, paper) for i, (_old, paper) in enumerate(rows, 1)]
        self._epoch = uuid4().hex
        self.endMoveRows()
        self.dataChanged.emit(self.index(0), self.index(len(rows) - 1))
        return True

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008 - Qt's signature
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        position, paper = self._rows[index.row()]
        if role == PAPER_ROLE:
            return paper
        if role == Qt.ItemDataRole.UserRole:
            return position
        if role == Qt.ItemDataRole.DisplayRole:
            return paper.title
        return None


class PaperDelegate(QStyledItemDelegate):
    """Paints one paper: its position, title, and a strip of tags and authors."""

    def __init__(self, palette: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.page = parent
        self.pal = palette
        self.title_font = fonts.font(fonts.SERIF, 11)
        self.tag_font = fonts.font(fonts.SANS, 8)
        self.pos_font = fonts.font(fonts.MONO, 8)

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, ROW_HEIGHT)

    def _tags(self, paper) -> list[tuple[str, str, str]]:
        """(text, foreground, background) for each tag on this row."""
        p = self.pal
        # A preprint is greyed: whether something passed review is part of what it is.
        ink = p["faint"] if venues.is_preprint(paper.venue) else p["ink"]
        out = [("置頂", "#ffffff", p["accent"])] if paper.pinned else []
        out.append((venues.label(paper.venue, paper.year), ink, p["sunk"]))
        if paper.award:
            out.append((paper.award, p["award"], p["awardSoft"]))
        if paper.is_canon:
            out.append(("canon", p["accent"], p["accentSoft"]))
        if paper.paper_type:
            out.append((paper.paper_type, p["muted"], p["sunk"]))
        if paper.citations:
            out.append((f"{paper.citations:,} cites", p["muted"], p["sunk"]))
        if paper.dependents:
            out.append((f"{paper.dependents} 篇依賴", p["accent"], p["accentSoft"]))
        parts = (("講解", paper.has_dive), ("承先", paper.has_cites), ("啟後", paper.has_later))
        if all(ok for _n, ok in parts):
            out.append(("已分析", p["done"], p["doneSoft"]))
        elif not any(ok for _n, ok in parts):
            out.append(("未分析", p["muted"], p["sunk"]))
        else:
            missing = "·".join(n for n, ok in parts if not ok)
            out.append((f"缺 {missing}", p["accent"], p["accentSoft"]))
        if not paper.has_pdf:
            # "找不到" once every source was tried: right-click to supply it by hand.
            text = "缺 PDF(找不到,右鍵補)" if paper.pdf_failed else "缺 PDF"
            out.append((text, p["warn"], p["warnSoft"]))
        if paper.read:
            out.append(("已讀", p["done"], p["doneSoft"]))
        elif paper.state == "delivered":
            # In a list nothing is delivered: it only means the paper was opened,
            # which is not having read it.
            in_list = bool(self.page) and bool(self.page.win.active_list)
            out.append(("開過" if in_list else "已送出", p["faint"], p["sunk"]))
        return out

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paper = index.data(PAPER_ROLE)
        position = index.data(Qt.ItemDataRole.UserRole)
        pal = self.pal
        r = option.rect

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(r, QColor(pal["accentSoft"]))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(r, QColor(pal["surface"]))
        painter.setPen(QColor(pal["border"]))
        painter.drawLine(r.left() + 8, r.bottom(), r.right() - 8, r.bottom())

        marked = bool(self.page) and paper.id in self.page.win.marked_ids()
        box = QRect(r.left() + 10, r.top() + (ROW_HEIGHT - BOX) // 2, BOX, BOX)
        if marked:
            painter.fillRect(box, QColor(pal["accent"]))
            painter.setPen(QColor("#ffffff"))
            painter.drawLine(box.left() + 3, box.center().y(),
                             box.center().x() - 1, box.bottom() - 4)
            painter.drawLine(box.center().x() - 1, box.bottom() - 4,
                             box.right() - 3, box.top() + 4)
        else:
            painter.setPen(QColor(pal["firm"]))
            painter.drawRect(box)

        left = r.left() + MARK_W + 2
        painter.setFont(self.pos_font)
        painter.setPen(QColor(pal["faint"]))
        pos_text = f"{position}."
        pos_w = QFontMetrics(self.pos_font).horizontalAdvance("9999.") + 6
        painter.drawText(
            QRect(left, r.top() + 8, pos_w, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            pos_text,
        )

        text_left = left + pos_w + 8
        text_width = r.right() - text_left - 12 - PIN_W

        painter.setFont(self.title_font)
        painter.setPen(QColor(pal["muted"] if paper.read else pal["ink"]))
        title = QFontMetrics(self.title_font).elidedText(
            paper.title, Qt.TextElideMode.ElideRight, text_width
        )
        painter.drawText(
            QRect(text_left, r.top() + 6, text_width, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title,
        )

        painter.setFont(self.tag_font)
        metrics = QFontMetrics(self.tag_font)
        x = text_left
        y = r.top() + 29
        for text, fg, bg in self._tags(paper):
            w = metrics.horizontalAdvance(text) + 10
            if x + w > r.right() - 12 - PIN_W:
                break
            painter.fillRect(QRect(x, y, w, 17), QColor(bg))
            painter.setPen(QColor(fg))
            painter.drawText(
                QRect(x, y, w, 17), Qt.AlignmentFlag.AlignCenter, text
            )
            x += w + 4

        if paper.authors:
            who = " · ".join(paper.authors[:8])
            if len(paper.authors) > 8:
                who += f" · 等 {len(paper.authors)} 人"
            painter.setPen(QColor(pal["muted"]))
            painter.drawText(
                QRect(text_left, y + 22, text_width, 17),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                metrics.elidedText(who, Qt.TextElideMode.ElideRight, text_width),
            )

        pin = QRect(r.right() - PIN_W + 6, r.top() + (ROW_HEIGHT - 22) // 2, PIN_W - 14, 22)
        if paper.pinned:
            painter.fillRect(pin, QColor(pal["accent"]))
            painter.setPen(QColor("#ffffff"))
        else:
            painter.setPen(QColor(pal["firm"]))
            painter.drawRect(pin.adjusted(0, 0, -1, -1))
            painter.setPen(QColor(pal["faint"]))
        painter.drawText(pin, Qt.AlignmentFlag.AlignCenter, "置頂")
        painter.restore()


class QueuePage(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self.win = window
        pal = window.pal

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 12)
        outer.setSpacing(10)

        self.heading = QLabel("Reading queue")
        self.heading.setFont(fonts.font(fonts.SERIF, 17, QFont.Weight.DemiBold))
        self.heading.setStyleSheet(f"color:{pal['ink']};")
        outer.addWidget(self.heading)

        self.blurb = QLabel()
        self.blurb.setWordWrap(True)
        self.blurb.setStyleSheet(f"color:{pal['muted']};font-size:12px;")
        outer.addWidget(self.blurb)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜尋標題、作者或發表處(如 MICCAI、預印本)…")
        self.search.setClearButtonEnabled(True)
        controls.addWidget(self.search, 1)

        self.f_unread = QCheckBox("只看未讀")
        self.f_history = QCheckBox("讀過的")
        self.f_award = QCheckBox("oral / spotlight")
        self.f_principle = QCheckBox("原理型")
        self.f_pdf = QCheckBox("已有原文")
        self.f_roots = QCheckBox("地基")
        self.f_roots.setToolTip("語料庫裡最多論文依賴的那些,依被依賴數排序")
        self.f_todo = QCheckBox("未分析完")
        self.f_nopdf = QCheckBox("缺 PDF")
        for box in (self.f_unread, self.f_history, self.f_todo, self.f_nopdf, self.f_award,
                    self.f_principle, self.f_pdf, self.f_roots):
            box.stateChanged.connect(self.refresh)
            box.setStyleSheet(f"color:{pal['muted']};font-size:12px;")
            controls.addWidget(box)

        self.sort = QComboBox()
        self.sort.setToolTip("重新排序目前顯示的論文。左邊的編號仍然是它原本的位置。")
        for label, _key, _reverse in SORTS:
            self.sort.addItem(label)
        self.sort.currentIndexChanged.connect(self._sort_changed)
        controls.addWidget(self.sort)

        outer.addLayout(controls)

        # Ticking the box at the left of a row selects it; this bar acts on all the
        # ticked rows at once. One kind of selection for every batch action -- the
        # tick used to mean only "take to the phone page", which nothing said.
        ticks = QHBoxLayout()
        ticks.setSpacing(6)
        self.sel_label = QLabel("")
        self.sel_label.setStyleSheet(f"color:{pal['muted']};font-size:12px;")
        ticks.addWidget(self.sel_label)
        button_css = (
            f"QPushButton{{background:{pal['surface']};color:{pal['ink']};"
            f"border:1px solid {pal['firm']};border-radius:5px;padding:3px 10px;"
            f"font-size:12px;}}"
            f"QPushButton:disabled{{color:{pal['faint']};border-color:{pal['border']};}}"
        )
        self._batch_buttons: list[QPushButton] = []
        for text, action, needs_ticks in (
            ("全選", self._tick_all, False),
            ("清除勾選", self._untick_all, True),
            ("置頂", lambda: self._batch("pin"), True),
            ("取消置頂", lambda: self._batch("unpin"), True),
            ("標記已讀", lambda: self._batch("read"), True),
            ("標記未讀", lambda: self._batch("unread"), True),
            ("分析", lambda: self._batch("analyze"), True),
            ("從清單移除", lambda: self._batch("remove"), True),
        ):
            button = QPushButton(text)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(button_css)
            button.clicked.connect(action)
            button.setProperty("needs_ticks", needs_ticks)
            if text == "分析":
                ai_style.mark(button, pal)
            ticks.addWidget(button)
            self._batch_buttons.append(button)
        self.remove_btn = self._batch_buttons[-1]
        ticks.addStretch(1)
        self.pocket_btn = QPushButton("帶出門")
        self.pocket_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pocket_btn.setToolTip(
            "把勾選的論文(所有清單合計)整理成一個手機看得到的頁面。"
        )
        self.pocket_btn.setStyleSheet(button_css)
        self.pocket_btn.clicked.connect(self.win.show_pocket)
        ticks.addWidget(self.pocket_btn)
        outer.addLayout(ticks)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.analysis = QLabel("")
        self.analysis.setStyleSheet(f"color:{pal['muted']};font-size:12px;")
        bar.addWidget(self.analysis, 1)
        self.analyze_btn = QPushButton("")
        self.analyze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.analyze_btn.setToolTip(
            "替清單裡還沒分析完的論文補齊:下載原文、整篇講解、承先(引用分析)、"
            "啟後(後續研究)與研究脈絡。三篇同時進行,可以隨時停止,已完成的部分會保留。"
        )
        ai_style.mark(self.analyze_btn, pal, primary=True)
        self.analyze_btn.clicked.connect(self._toggle_analyze)
        self.survey_btn = QPushButton("清單綜覽")
        self.survey_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.survey_btn.setToolTip(
            "把整份清單當成一個研究領域來讀:研究脈絡、研究路線與代表作、資料集、"
            "目前的進展、面對的挑戰、可以做的題目。"
        )
        ai_style.mark(self.survey_btn, pal)
        self.survey_btn.clicked.connect(self._show_survey)
        bar.addWidget(self.survey_btn)
        bar.addWidget(self.analyze_btn)
        outer.addLayout(bar)
        self._job: QProcess | None = None
        self._then = None
        self._job_line = ""
        self._reload_soon = QTimer(self)
        self._reload_soon.setSingleShot(True)
        self._reload_soon.setInterval(4000)
        self._reload_soon.timeout.connect(self.win.reload)

        self.model = PaperListModel()
        self.model.reorder = self._save_paper_order
        self.view = QListView()
        self.view.setDragDropMode(QListView.DragDropMode.InternalMove)
        self.view.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.view.setDragDropOverwriteMode(False)
        self.view.setDropIndicatorShown(True)
        self.view.setModel(self.model)
        self.view.setItemDelegate(PaperDelegate(pal, self))
        self.view.setUniformItemSizes(True)
        self.view.setMouseTracking(True)
        self.view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.view.verticalScrollBar().setSingleStep(ROW_HEIGHT // 3)
        self.view.setStyleSheet(
            f"QListView{{background:{pal['ground']};border:1px solid {pal['border']};}}"
        )
        self.view.clicked.connect(self._open)
        self.view.activated.connect(self._open)
        self.view.viewport().installEventFilter(self)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        outer.addWidget(self.view, 1)
        # The row keys act on the highlighted row, and only while the list has the
        # keys: in the search box the same letters are typing.
        # Enter opens on every platform: a macOS list view takes Return as "edit" and
        # never emits activated for it.
        for key, act in (
            ("A", self._tick_current),
            ("T", self._pin_current),
            ("Return", self._open_current),
            ("Enter", self._open_current),
        ):
            shortcut = QShortcut(QKeySequence(key), self.view)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(act)
        self.search.installEventFilter(self)
        scopes(pal["accent"]).add(
            self.view,
            "論文列表",
            "↑↓ 選擇 · Enter 開啟 · A 勾選 · T 置頂",
        )

        self.count = QLabel("")
        self.count.setStyleSheet(f"color:{pal['faint']};font-size:11px;")
        outer.addWidget(self.count)

        # Typing is still cheaper than a model reset per character, so coalesce the
        # keystrokes rather than filtering 5000 rows on each one.
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _: self._debounce.start())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self.focus_list)

    def focus_list(self) -> None:
        """Arriving on the list puts the keys on it, at the paper just read, so
        ↑↓ and Enter work without a click first."""
        focus = QApplication.focusWidget()
        if not self.isVisible() or (focus is not None and self.isAncestorOf(focus)):
            return
        if not self.view.currentIndex().isValid():
            self._select(self.win._last_paper)
        self.view.setFocus(Qt.FocusReason.OtherFocusReason)

    def _select(self, paper_id: str | None) -> None:
        rows = [p.id for _i, p in self.model._rows]
        if not rows:
            return
        row = rows.index(paper_id) if paper_id in rows else 0
        index = self.model.index(row)
        self.view.setCurrentIndex(index)
        self.view.scrollTo(index)

    def _current_paper(self):
        index = self.view.currentIndex()
        return index.data(PAPER_ROLE) if index.isValid() else None

    def _tick_current(self) -> None:
        paper = self._current_paper()
        if paper is not None:
            self.win.toggle_marked(paper.id)

    def _pin_current(self) -> None:
        paper = self._current_paper()
        if paper is not None:
            self.win.set_pinned([paper.id], not paper.pinned)

    def eventFilter(self, obj, event) -> bool:
        """A press in the tick strip marks the row; everywhere else opens it.

        The view never sees a press, release or double click in the tick strip or
        the pin: it still remembers the last row it opened, so a release there would
        emit `clicked` for that row, and a fast second tick also arrives as a double
        click that it turns into a press of its own. That second tick comes as an
        ordinary press too, so only presses toggle.
        """
        mouse = (
            obj is self.view.viewport()
            and event.type()
            in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
            )
            and event.button() == Qt.MouseButton.LeftButton
        )
        in_strip = mouse and event.position().x() < MARK_W
        in_pin = mouse and event.position().x() > self.view.viewport().width() - PIN_W
        if (in_strip or in_pin) and event.type() != QEvent.Type.MouseButtonPress:
            return True
        if (
            obj is self.search
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self.model.rowCount()
        ):
            # From the search box straight into the results.
            if not self.view.currentIndex().isValid():
                self._select(None)
            self.view.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        if in_strip or in_pin:
            index = self.view.indexAt(event.position().toPoint())
            paper = index.data(PAPER_ROLE) if index.isValid() else None
            if paper is not None:
                if in_pin:
                    self.win.set_pinned([paper.id], not paper.pinned)
                else:
                    self.win.toggle_marked(paper.id)
                return True
        return super().eventFilter(obj, event)

    def ticked(self) -> list[str]:
        """The ticked papers among those on screen, in the order shown."""
        marked = set(self.win.marked_ids())
        return [p.id for _i, p in self.model._rows if p.id in marked]

    def update_pocket_btn(self) -> None:
        n = len(self.ticked())
        self.sel_label.setText(
            f"已勾選 {n} 篇:"
            if n
            else "勾選左邊方框(或按 A)可一次處理多篇,或「帶出門」"
        )
        # Hidden rather than greyed out: eight dead buttons on every visit read as
        # clutter, and they appear the moment a box is ticked.
        for button in self._batch_buttons:
            needed = bool(n) or not button.property("needs_ticks")
            button.setEnabled(needed)
            button.setVisible(needed)
        self.remove_btn.setText("從清單移除" if self.win.active_list else "從佇列移除")
        total = len(self.win.marked_ids())
        self.pocket_btn.setText(f"帶出門 ({total})" if total else "帶出門")

    def _tick_all(self) -> None:
        shown = [p.id for _i, p in self.model._rows]
        self.win.set_marked([*self.win.marked_ids(), *(i for i in shown
                                                       if i not in self.win.marked_ids())])

    def _untick_all(self) -> None:
        shown = set(p.id for _i, p in self.model._rows)
        self.win.set_marked([i for i in self.win.marked_ids() if i not in shown])

    def _batch(self, action: str) -> None:
        ids = self.ticked()
        if not ids:
            return
        if action in ("pin", "unpin"):
            self.win.set_pinned(ids, action == "pin")
        elif action in ("read", "unread"):
            self.win.set_read_many(ids, action == "read")
        elif action == "analyze":
            self._start(["analyze", *ids, "--retry"])
        elif action == "remove" and self.win.remove_papers(ids):
            self._untick_all()

    def _matches(self, paper) -> bool:
        if self.f_history.isChecked() and not paper.read:
            return False
        if self.f_unread.isChecked() and paper.read:
            return False
        if self.f_award.isChecked() and not paper.award:
            return False
        if self.f_principle.isChecked() and paper.paper_type != "principle":
            return False
        if self.f_pdf.isChecked() and not paper.has_pdf:
            return False
        if self.f_roots.isChecked() and paper.dependents < 3:
            return False
        if self.f_todo.isChecked() and _analysed(paper) == 3:
            return False
        if self.f_nopdf.isChecked() and paper.has_pdf:
            return False
        q = self.search.text().strip().lower()
        if not q:
            return True
        # The venue as shown, so "miccai" or "預印本" filters the way the row reads.
        where = venues.label(paper.venue, paper.year).lower()
        return q in paper.title.lower() or q in " ".join(paper.authors).lower() or q in where

    def refresh(self) -> None:
        # A list is in the order someone chose; the queue is in ranked order. Saying
        # the wrong one is worse than saying nothing.
        if self.win.active_list:
            # rsplit: only the trailing "(read/total)" is ours to drop -- the name
            # itself may contain brackets.
            self.heading.setText(self.win.list_picker.currentText().rsplit(" (", 1)[0])
            self.blurb.setText(
                "拖曳論文可調整自訂順序並自動儲存；點擊或 Enter 開讀。"
                "「下一篇」依自訂順序取下一篇未讀論文。"
            )
        else:
            self.heading.setText("Reading queue")
            self.blurb.setText(
                "最新年份優先,同一年之內按影響力排序。點任一篇直接開讀,"
                "或按「下一篇」取下一篇未讀的。"
            )

        # oral/spotlight, principle type and 地基 come from the conference crawl;
        # in an imported list they filter almost everything away.
        for box in (self.f_award, self.f_principle, self.f_roots):
            box.setVisible(not self.win.active_list)
            if self.win.active_list and box.isChecked():
                box.blockSignals(True)
                box.setChecked(False)
                box.blockSignals(False)
        self._say_analysis()
        scroll = self.view.verticalScrollBar().value()
        QTimer.singleShot(0, self.view, lambda: self.view.verticalScrollBar().setValue(scroll))
        rows = [
            (i, p) for i, p in enumerate(self.win.papers, 1) if self._matches(p)
        ]
        label, key, reverse = SORTS[self.sort.currentIndex()]
        if key is not None:
            # The blurb above just claimed the default order. Say what is actually on
            # screen instead.
            self.blurb.setText(
                f"目前依「{label}」排序,左邊的編號仍是它在"
                f"{'清單' if self.win.active_list else '佇列'}裡的原本位置。"
                "「下一篇」按鈕走的還是原本的順序。"
            )
            # The position shown on each row stays the paper's place in the queue or
            # the list: sorting by citations is a way to look at the same reading
            # order, not a way to renumber it.
            rows.sort(key=lambda pair: key(pair[1]), reverse=reverse)
            rows = self._pinned_first(rows)
            self._show_rows(rows)
            return

        # Ranking is recomputed every night as citation data arrives, so a paper read
        # yesterday can be anywhere by morning. In history mode order by when it was
        # read instead, which is the only order that makes it findable again.
        if self.f_history.isChecked():
            rows.sort(key=lambda pair: pair[1].read_at or "", reverse=True)
        elif self.f_roots.isChecked():
            # Reading order here is what the field depends on, not what is newest.
            rows.sort(key=lambda pair: -pair[1].dependents)

        rows = self._pinned_first(rows)
        self._show_rows(rows)

    def _show_rows(self, rows: list) -> None:
        # A reset drops the highlighted row; pinning moves it to the top, and the
        # highlight should follow it there rather than fall back to row one.
        current = self._current_paper()
        self.model.can_reorder = bool(self.win.active_list) and (
            self.sort.currentIndex() == 0 and not self.search.text().strip()
            and not any(box.isChecked() for box in (
                self.f_unread, self.f_history, self.f_todo, self.f_nopdf,
                self.f_award, self.f_principle, self.f_pdf, self.f_roots,
            )) and not any(p.pinned for _i, p in rows)
        )
        if self.win.active_list and not self.model.can_reorder:
            self.blurb.setText(self.blurb.text() +
                " 要拖曳排序，請切回「自訂順序」、清除搜尋與篩選，並取消置頂。")
        self.model.set_rows(rows)
        self._select(current.id if current is not None else getattr(self.win, "_last_paper", None))
        self._say_count(rows)

    def _save_paper_order(self, paper_ids):
        from paper_daily import lists

        try:
            lists.reorder_papers(self.win.active_list, paper_ids)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.blurb.setText(f"順序未儲存：{exc}")
            return False
        papers = {paper.id: paper for paper in self.win.papers}
        self.win.papers = [papers[pid] for pid in paper_ids]
        self.blurb.setText("自訂順序已儲存；「下一篇」會依這個順序閱讀。")
        return True

    def _open_current(self):
        index = self.view.currentIndex()
        if index.isValid():
            self._open(index)

    # ---- analysis -----------------------------------------------------------
    def _say_analysis(self) -> None:
        papers = self.win.papers
        full = sum(1 for p in papers if _analysed(p) == 3)
        none = sum(1 for p in papers if _analysed(p) == 0)
        no_pdf = sum(1 for p in papers if not p.has_pdf)
        text = (
            f"分析:完整 {full} · 部分 {len(papers) - full - none} · 未分析 {none}"
            f" · 缺 PDF {no_pdf}"
        )
        if self._job is not None:
            text += f"  —  {self._job_line}"
        self.analysis.setText(text)
        self.analyze_btn.setVisible(bool(self.win.active_list))
        self.survey_btn.setVisible(bool(self.win.active_list))
        left = len(papers) - full
        if self._job is not None:
            self.analyze_btn.setText("停止分析")
            self.analyze_btn.setEnabled(True)
        else:
            self.analyze_btn.setText(f"分析未完成的 {left} 篇" if left else "全部分析完成")
            self.analyze_btn.setEnabled(bool(left))

    def _show_survey(self) -> None:
        from paper_daily.desktop.survey_dialog import SurveyDialog

        list_id = self.win.active_list
        if not list_id:
            return
        with connect() as conn:
            row = conn.execute("SELECT name FROM lists WHERE id=?", (list_id,)).fetchone()
        SurveyDialog(list_id, row["name"] if row else list_id, self.win.pal, self.win).exec()

    def _toggle_analyze(self) -> None:
        if self._job is not None:
            self._then = None
            self._job.kill()
            return
        self._analyze_list()

    def _analyze_list(self):
        self._start(["analyze", "--list", self.win.active_list, "--jobs", "3"])

    def _start(self, args: list[str], then=None) -> None:
        from paper_daily.desktop.ai_access import ANALYSIS_TASKS, requires_ai

        if args and args[0] == "analyze":
            requires_ai(*ANALYSIS_TASKS)(type(self)._start_ready)(self, args, then)
        else:
            self._start_ready(args, then)

    def _start_ready(self, args: list[str], then=None) -> None:
        """Run a paper-daily command beside the window, its last line on the bar."""
        if self._job is not None:
            self.analysis.setText("上一個工作還在跑,等它結束或先停止。")
            return
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        self._job = QProcess(self)
        self._job.setProcessEnvironment(env)
        self._job.setWorkingDirectory(str(ROOT))
        self._job.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._job.readyReadStandardOutput.connect(self._job_output)
        self._job.finished.connect(self._job_done)
        self._job.errorOccurred.connect(self._job_error)
        self._then = then
        self._job_line = "開始…"
        self._say_analysis()
        program, *rest = runtime.cli_command(*args)
        self._job.start(program, rest)

    def _job_output(self) -> None:
        chunk = bytes(self._job.readAllStandardOutput()).decode("utf-8", "replace")
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        if lines:
            self._job_line = lines[-1][:120]
            self._say_analysis()
        # A finished paper changes its row; redraw now and then, not on every line.
        if not self._reload_soon.isActive():
            self._reload_soon.start()

    def _job_done(self, code: int, _status) -> None:
        self._job = None
        then, self._then = self._then, None
        self.win.reload()
        if then is not None and code == 0:
            then()

    def _job_error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart and self._job is not None:
            job, self._job = self._job, None
            self._then = None
            job.deleteLater()
            self.win.reload()
            self.analysis.setText("無法啟動背景工作；請確認安裝後重試。")

    def _supply_pdf(self, paper, source: str) -> None:
        """Hand over a PDF no source had, then analyse the paper with it."""
        if source == "url":
            url, ok = QInputDialog.getText(
                self, "補 PDF", f"PDF 網址:\n{paper.title[:80]}"
            )
            if not ok or not url.strip():
                return
            args = ["repdf", paper.id, "--url", url.strip()]
        else:
            path, _ = QFileDialog.getOpenFileName(self, "選擇 PDF", "", "PDF (*.pdf)")
            if not path:
                return
            args = ["repdf", paper.id, "--file", path]
        self._start(args, then=lambda: self._start(["analyze", paper.id, "--retry"]))

    @staticmethod
    def _pinned_first(rows: list) -> list:
        """Pinned papers above the rest, each group still in the order chosen."""
        return [r for r in rows if r[1].pinned] + [r for r in rows if not r[1].pinned]

    def _say_count(self, rows: list) -> None:
        total = len(self.win.papers)
        read = sum(1 for p in self.win.papers if p.read)
        where = "清單" if self.win.active_list else "佇列"
        self.count.setText(f"顯示 {len(rows)} 篇 · {where}共 {total} 篇 · 已讀 {read} 篇")
        self.update_pocket_btn()

    def _sort_changed(self, index: int) -> None:
        # Worth remembering: someone who reads a list by citation count reads the
        # next one that way too, and re-picking it on every launch is a chore.
        with connect() as conn:
            set_kv(conn, "ui.sort", str(index))
        self.refresh()

    def restore_sort(self) -> None:
        with connect() as conn:
            stored = get_kv(conn, "ui.sort")
        if stored and stored.isdigit() and int(stored) < len(SORTS):
            self.sort.setCurrentIndex(int(stored))

    def _open(self, index: QModelIndex) -> None:
        paper = index.data(PAPER_ROLE)
        if paper is not None:
            self.win.open_paper(paper.id)

    def _menu(self, point) -> None:
        """Right-click: act on one row without opening it.

        An imported list is a first draft -- entries get missed, and a citation
        sometimes resolves to the wrong paper -- so removing one has to be as cheap
        as reading one.
        """
        index = self.view.indexAt(point)
        paper = index.data(PAPER_ROLE) if index.isValid() else None
        if paper is None:
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{self.win.pal['surface']};color:{self.win.pal['ink']};"
            f"border:1px solid {self.win.pal['firm']};}}"
            f"QMenu::item:selected{{background:{self.win.pal['accentSoft']};}}"
        )
        menu.addAction("開啟").triggered.connect(lambda: self.win.open_paper(paper.id))
        menu.addAction("取消置頂" if paper.pinned else "置頂").triggered.connect(
            lambda: self.win.set_pinned([paper.id], not paper.pinned)
        )
        if self.win.active_list:
            menu.addAction("從這個清單移除").triggered.connect(
                lambda: self.win.remove_paper(paper.id, paper.title)
            )
        else:
            menu.addAction("插到佇列最前面").triggered.connect(
                lambda: self.win.promote(paper.id)
            )
            menu.addAction("從佇列移除").triggered.connect(
                lambda: self.win.remove_paper(paper.id, paper.title)
            )
        menu.addSeparator()
        menu.addAction("分析這篇(補齊缺的部分)").triggered.connect(
            lambda: self._start(["analyze", paper.id, "--retry"])
        )
        label = "補 PDF" if not paper.has_pdf else "換一份 PDF"
        menu.addAction(f"{label}:貼網址…").triggered.connect(
            lambda: self._supply_pdf(paper, "url")
        )
        menu.addAction(f"{label}:選本機檔案…").triggered.connect(
            lambda: self._supply_pdf(paper, "file")
        )
        menu.addSeparator()
        menu.addAction("標記為已讀").triggered.connect(
            lambda: self.win.set_read(paper.id, True)
        )
        menu.addAction("標記為未讀").triggered.connect(
            lambda: self.win.set_read(paper.id, False)
        )
        menu.exec(self.view.viewport().mapToGlobal(point))
