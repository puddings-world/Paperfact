"""Mouse selection over Qt's PDF view.

`QPdfView` renders and scrolls well and exposes no way to select text: there is no
`selectedText`, no hit test, not even a widget-to-page mapping. So selection is built
on top of it -- a transparent overlay that converts a drag into page coordinates, asks
PyMuPDF which words lie between the two points, and draws the highlight itself.

The mapping repeats QPdfView's own page layout (see `PageMap`), checked against the
scroll range, since the view exposes the result of that layout to nobody.

What a selection is for, in a reader for papers you half understand: translate it,
write a note against it, or ask about it. Copying is the least of it.
"""

from __future__ import annotations

import bisect
import contextlib
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from paper_daily.desktop import ai_style


@dataclass
class Word:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    order: int


def _round(x: float) -> int:
    """C++ qRound, which QSize uses; Python's round() goes to even on halves."""
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


class PageMap:
    """Where each page sits in the scrolled document, in both coordinate systems.

    This lays the pages out the way `QPdfView` does, page by page. One scale for the
    whole document, taken from the scrollbars, was right only while every page had
    the same size. In FitToWidth each page is scaled to the viewport on its own, so a
    paper mixing portrait pages with landscape table pages (Cataract-LMM has sixteen
    sizes) put the highlight a little further off on every page after the first odd
    one. Qt also rounds each page to whole pixels, which over forty pages drifts too.
    """

    def __init__(self, view) -> None:
        self.view = view

    def _res(self) -> float:
        screen = self.view.screen() or QGuiApplication.primaryScreen()
        return screen.logicalDotsPerInch() / 72 if screen is not None else 96 / 72

    def _sizes(self, res: float) -> list[tuple[int, int]]:
        doc = self.view.document()
        margins = self.view.documentMargins()
        fit = self.view.zoomMode() == QPdfView.ZoomMode.FitToWidth
        room = self.view.viewport().width() - margins.left() - margins.right()
        out = []
        for i in range(max(doc.pageCount(), 0)):
            pt = doc.pagePointSize(i)
            if fit:
                w, h = _round(pt.width() * res), _round(pt.height() * res)
                f = room / w if w else 1.0
                out.append((_round(w * f), _round(h * f)))
            else:
                z = res * self.view.zoomFactor()
                out.append((_round(pt.width() * z), _round(pt.height() * z)))
        return out

    def pages(self) -> list[tuple[int, int, int, int, float, float]]:
        """(x, y, width, height, px per point across, px per point down) per page."""
        doc = self.view.document()
        if doc is None or doc.pageCount() <= 0:
            return []
        margins = self.view.documentMargins()
        spacing = self.view.pageSpacing()
        res = self._res()
        sizes = self._sizes(res)
        bar = self.view.verticalScrollBar()
        if bar.maximum() > 0 and self.view.zoomMode() != QPdfView.ZoomMode.FitToWidth:
            # At a custom zoom the screen's dpi enters the size. Should Qt have taken
            # it from another screen than this one, the scroll range says so.
            fixed = margins.top() + margins.bottom() + spacing * len(sizes)
            laid = sum(h for _w, h in sizes) or 1
            real = bar.maximum() + self.view.viewport().height() - fixed
            if abs(real - laid) > len(sizes):
                sizes = self._sizes(res * real / laid)
        widest = max(w for w, _h in sizes) + margins.left() + margins.right()
        across = max(widest, self.view.viewport().width())
        out = []
        y = margins.top()
        for i, (w, h) in enumerate(sizes):
            pt = doc.pagePointSize(i)
            sx = w / pt.width() if pt.width() else 1.0
            sy = h / pt.height() if pt.height() else 1.0
            out.append(((across - w) // 2, y, w, h, sx, sy))
            y += h + spacing
        return out

    def at(self, point: QPoint) -> tuple[int, float, float] | None:
        """Widget point -> (page, x, y) in page points."""
        y_doc = self.view.verticalScrollBar().value() + point.y()
        x_doc = self.view.horizontalScrollBar().value() + point.x()
        for index, (x, y, _w, h, sx, sy) in enumerate(self.pages()):
            if y <= y_doc <= y + h:
                return index, (x_doc - x) / sx, (y_doc - y) / sy
        return None

    def doc_y(self, page: int, y_points: float) -> int:
        """Where a point on a page sits in the scrolled document, in pixels."""
        pages = self.pages()
        if not 0 <= page < len(pages):
            return 0
        _x, y, _w, _h, _sx, sy = pages[page]
        return int(y + y_points * sy)

    def doc_x(self, page: int, x_points: float) -> int:
        pages = self.pages()
        if not 0 <= page < len(pages):
            return 0
        x, _y, _w, _h, sx, _sy = pages[page]
        return int(x + x_points * sx)

    def rect_for(self, word: Word, pages=None) -> QRect:
        """Page-point rectangle -> widget rectangle, for drawing the highlight."""
        pages = self.pages() if pages is None else pages
        if not 0 <= word.page < len(pages):
            return QRect()
        x, y, _w, _h, sx, sy = pages[word.page]
        return QRectF(
            x + word.x0 * sx - self.view.horizontalScrollBar().value(),
            y + word.y0 * sy - self.view.verticalScrollBar().value(),
            (word.x1 - word.x0) * sx,
            (word.y1 - word.y0) * sy,
        ).toRect()


def _level_words(page) -> list[tuple[int, tuple]]:
    """PyMuPDF's words with their index, without any set at an angle.

    A preprint stamped "ARTICLE IN PRESS" diagonally across every page gives three
    words whose boxes are a hundred points square, in the middle of the text and
    first in reading order. A drag starting anywhere over them started at the top of
    the page. Rotated axis labels in figures do the same on a smaller scale.
    """
    tp = page.get_textpage()
    slanted = {
        (b["number"], n)
        for b in page.get_text("dict", textpage=tp)["blocks"]
        for n, line in enumerate(b.get("lines", ()))
        if abs(line["dir"][1]) > 0.05
    }
    words = page.get_text("words", textpage=tp)
    return [(i, w) for i, w in enumerate(words) if (w[5], w[6]) not in slanted]


def _page_words(doc, page: int) -> list[Word]:
    if not 0 <= page < doc.page_count:
        return []
    try:
        raw = _level_words(doc[page])
    except Exception:
        raw = []
    # PyMuPDF returns (x0, y0, x1, y1, word, block, line, word_no) already in
    # reading order, which is what makes "everything between these two points"
    # mean what it means on screen.
    # The index counts the slanted words it skips, so a note anchored before
    # they were dropped still points at the same words.
    return [Word(page, w[0], w[1], w[2], w[3], w[4], i) for i, w in raw]


def words_in(path, pages) -> dict[int, list[Word]]:
    """The words of these pages, read from the file itself so that it can be done
    away from the window's thread; `SelectionOverlay.prime` takes the result."""
    import pymupdf

    with pymupdf.open(path) as doc:
        return {page: _page_words(doc, page) for page in sorted(pages)}


class SelectionOverlay(QWidget):
    """Transparent layer that turns a drag into a passage of text."""

    picked = Signal(str)       # a finished selection
    cleared = Signal()
    translate = Signal(str)    # the three things worth doing with a passage
    note = Signal(str)
    ask = Signal(str)
    refine = Signal(str)       # a quick translation, done again by the model
    highlight = Signal()
    erase_highlight = Signal()

    def __init__(self, view, palette: dict[str, str]) -> None:
        super().__init__(view.viewport())
        self.view = view
        self.pal = palette
        self.map = PageMap(view)
        self._doc = None
        self._words: dict[int, list[Word]] = {}
        self._selected: list[Word] = []
        self._marks: list[tuple[dict, list[Word]]] = []
        self._anchor: tuple[int, float, float] | None = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setGeometry(view.viewport().rect())
        view.viewport().installEventFilter(self)
        view.verticalScrollBar().valueChanged.connect(self.update)
        view.horizontalScrollBar().valueChanged.connect(self.update)

        self.bar = _ActionBar(self)
        self.bar.hide()
        self.bar.buttons["translate"].clicked.connect(
            lambda: self.translate.emit(self.selected_text())
        )
        self.bar.buttons["note"].clicked.connect(lambda: self.note.emit(self.selected_text()))
        self.bar.buttons["ask"].clicked.connect(lambda: self.ask.emit(self.selected_text()))
        self.bar.buttons["highlight"].clicked.connect(
            lambda: self.erase_highlight.emit() if self.selected_highlights()
            else self.highlight.emit()
        )

        self.result = _ResultPanel(self)
        self.result.hide()
        self.result.refine.clicked.connect(lambda: self.refine.emit(self.selected_text()))

    # ---- document --------------------------------------------------------
    def set_document(self, path) -> None:
        self.clear()
        self._marks.clear()
        self._words.clear()
        self._close()
        try:
            import pymupdf

            self._doc = pymupdf.open(path)
        except Exception:
            self._doc = None

    def _close(self) -> None:
        if self._doc is not None:
            with contextlib.suppress(Exception):
                self._doc.close()
            self._doc = None

    def words_on(self, page: int) -> list[Word]:
        if page in self._words:
            return self._words[page]
        out = _page_words(self._doc, page) if self._doc is not None else []
        self._words[page] = out
        return out

    def prime(self, words: dict[int, list[Word]]) -> None:
        """Take words already read elsewhere (`words_in`) for the open document."""
        for page, found in words.items():
            self._words.setdefault(page, found)

    # ---- selection -------------------------------------------------------
    def _nearest(self, page: int, x: float, y: float) -> Word | None:
        words = self.words_on(page)
        if not words:
            return None
        # Distance to the box, not to its centre: grabbing the first letter of a long
        # word sits closer to the centre of the short word before it, so a centre
        # measure started selections one word early and ended them one word late.
        def gap(w: Word) -> tuple[float, float]:
            dx = max(w.x0 - x, 0.0, x - w.x1)
            dy = max(w.y0 - y, 0.0, y - w.y1)
            return dy, dx

        return min(words, key=gap)

    def _between(
        self, start: tuple[int, float, float], end: tuple[int, float, float]
    ) -> list[Word]:
        first = self._nearest(*start)
        last = self._nearest(*end)
        if first is None or last is None:
            return []
        # Order by the words found, not by the raw points: in two columns the end of
        # a drag can sit higher on the page than its start yet come later in the text.
        if (last.page, last.order) < (first.page, first.order):
            first, last = last, first
        p1, p2 = first.page, last.page
        picked: list[Word] = []
        for page in range(p1, p2 + 1):
            for w in self.words_on(page):
                if page == p1 and (w.order < first.order):
                    continue
                if page == p2 and (w.order > last.order):
                    continue
                picked.append(w)
        return picked

    def selected_text(self) -> str:
        if not self._selected:
            return ""
        lines: list[list[Word]] = []
        for w in self._selected:
            if lines and abs(lines[-1][-1].y0 - w.y0) < 3 and w.page == lines[-1][-1].page:
                lines[-1].append(w)
            else:
                lines.append([w])
        # Papers hyphenate across lines; joining without repair leaves "visu- ally".
        text = ""
        for line in lines:
            part = " ".join(w.text for w in line)
            if text.endswith("-"):
                text = text[:-1] + part
            elif text:
                text += " " + part
            else:
                text = part
        # Typeset PDFs space author lists and units with hair and thin spaces, which
        # survive into a note or a prompt as invisible junk.
        return " ".join(text.split())

    def set_highlights(self, records: list[dict]) -> None:
        self._marks = []
        for record in records:
            anchor = record["anchor"]
            words = [w for page in range(anchor["p0"], anchor["p1"] + 1)
                     for w in self.words_on(page)
                     if (page, w.order) >= (anchor["p0"], anchor["o0"])
                     and (page, w.order) <= (anchor["p1"], anchor["o1"])]
            if words:
                self._marks.append((record, words))
        self.update()

    def selected_highlights(self) -> list[int]:
        selected = {(w.page, w.order) for w in self._selected}
        return [record["id"] for record, words in self._marks
                if any((w.page, w.order) in selected for w in words)]

    # ---- anchors ---------------------------------------------------------
    # A note is worth more if it can lead back to the passage it was written about.
    # Word order within a page is the cheapest anchor that survives a restart: the
    # file on disk does not change, so index 412 on page 3 is the same word tomorrow.
    def anchor(self) -> dict | None:
        """Where the current selection is, as something storable."""
        if not self._selected:
            return None
        first, last = self._selected[0], self._selected[-1]
        return {"p0": first.page, "o0": first.order, "p1": last.page, "o1": last.order}

    def focus(self, anchor: dict) -> bool:
        """Select that passage again and scroll it into view."""
        try:
            p0, o0 = int(anchor["p0"]), int(anchor["o0"])
            p1, o1 = int(anchor["p1"]), int(anchor["o1"])
        except (KeyError, TypeError, ValueError):
            return False

        picked: list[Word] = []
        for page in range(p0, p1 + 1):
            for w in self.words_on(page):
                if page == p0 and w.order < o0:
                    continue
                if page == p1 and w.order > o1:
                    continue
                picked.append(w)
        if not picked:
            return False

        self._selected = picked
        self.result.hide()
        self.bar.hide()

        # A third of the way down reads as "here" rather than "just off the top".
        top = self.map.doc_y(picked[0].page, picked[0].y0)
        bar = self.view.verticalScrollBar()
        bar.setValue(max(0, min(top - self.view.viewport().height() // 3, bar.maximum())))
        self.update()
        return True

    def find(self, page: int, text: str) -> dict | None:
        """An anchor for `text` where it is printed on `page`, if it can be found.

        Figures are stored by caption and page, not by word order, so the caption is
        located again from its opening words. Hyphenation and ligatures make a full
        match fragile; the first few words are distinctive enough on one page.
        """
        want = [t.casefold() for t in text.split()]
        if not want:
            return None
        head = want[: min(5, len(want))]
        words = self.words_on(page)
        # Captions are often set with an en space after the number ("Fig. 2 "),
        # which PyMuPDF keeps inside the word but str.split() treats as a separator.
        texts = ["".join(w.text.split()).casefold() for w in words]
        for i in range(len(texts) - len(head) + 1):
            if texts[i : i + len(head)] == head:
                last = min(i + len(want), len(words)) - 1
                return {"p0": page, "o0": words[i].order, "p1": page, "o1": words[last].order}
        return None

    def search(self, query: str) -> list[dict]:
        """Every place `query` is printed, as anchors, in reading order.

        Matched over each page's words joined by single spaces, so a phrase finds
        itself across a line break and a fragment finds the word containing it
        ("segment" in "segmentation"), the way a browser's find does.
        """
        want = " ".join(query.split()).casefold()
        if not want or self._doc is None:
            return []
        hits: list[dict] = []
        for page in range(self._doc.page_count):
            words = self.words_on(page)
            starts, parts, at = [], [], 0
            for w in words:
                piece = " ".join(w.text.split()).casefold()
                starts.append(at)
                parts.append(piece)
                at += len(piece) + 1
            text = " ".join(parts)
            i = text.find(want)
            while i != -1:
                first = bisect.bisect_right(starts, i) - 1
                last = bisect.bisect_right(starts, i + len(want) - 1) - 1
                hits.append({"p0": page, "o0": words[first].order,
                             "p1": page, "o1": words[last].order})
                i = text.find(want, i + 1)
        return hits

    def scroll_to_page(self, page: int) -> None:
        bar = self.view.verticalScrollBar()
        bar.setValue(max(0, min(self.map.doc_y(page, 0), bar.maximum())))

    def show_result(self, title: str, text: str, refinable: bool = False) -> None:
        """A translation, beside the words it belongs to."""
        self.result.set_text(title, text, refinable)
        self.result.place(self.bar.geometry(), self.width(), self.height())

    def clear(self) -> None:
        self._selected = []
        self._anchor = None
        self.bar.hide()
        self.result.hide()
        self.update()
        self.cleared.emit()

    # ---- events ----------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self.view.viewport() and event.type() == event.Type.Resize:
            self.setGeometry(self.view.viewport().rect())
        return False

    def mousePressEvent(self, event) -> None:
        self.bar.hide()
        self.result.hide()
        self._anchor = self.map.at(event.position().toPoint())
        self._selected = []
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._anchor is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        here = self.map.at(event.position().toPoint())
        if here is None:
            return
        self._selected = self._between(self._anchor, here)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._anchor is None:
            return
        text = self.selected_text()
        if len(text.strip()) < 2:
            point = event.position().toPoint()
            pages = self.map.pages()
            for _record, words in reversed(self._marks):
                if any(self.map.rect_for(word, pages).contains(point) for word in words):
                    self._selected = words[:]
                    self.update()
                    self.bar.place(point, self.width(), self.height())
                    self.picked.emit(self.selected_text())
                    if _record.get("reason"):
                        self.show_result("AI 重點理由", _record["reason"])
                    return
            self.clear()
            return
        point = event.position().toPoint()
        self.bar.place(point, self.width(), self.height())
        self.picked.emit(text)

    def mouseDoubleClickEvent(self, event) -> None:
        """A double click takes the word under the cursor, as a reader should."""
        at = self.map.at(event.position().toPoint())
        if at is None:
            return
        word = self._nearest(*at)
        if word is None:
            return
        self._selected = [word]
        self.update()
        self.bar.place(event.position().toPoint(), self.width(), self.height())
        self.picked.emit(word.text)

    def paintEvent(self, _event) -> None:
        if not self._selected and not self._marks:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 224, 45, 100))
        painted = set()
        pages = self.map.pages()
        for record, words in self._marks:
            painter.setBrush(
                QColor(95, 218, 145, 100) if record.get("origin") == "ai"
                else QColor(255, 224, 45, 100)
            )
            for word in words:
                key = (word.page, word.order)
                if key not in painted:
                    painted.add(key)
                    rect = self.map.rect_for(word, pages)
                    if self.rect().intersects(rect):
                        painter.drawRect(rect.adjusted(-1, -1, 1, 1))
        colour = QColor(self.pal["accent"])
        colour.setAlpha(58)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        for word in self._selected:
            rect = self.map.rect_for(word, pages)
            if not rect.isNull():
                painter.drawRect(rect.adjusted(-1, -1, 1, 1))


class _ActionBar(QFrame):
    """What to do with the passage you just selected."""

    def __init__(self, overlay: SelectionOverlay) -> None:
        super().__init__(overlay)
        pal = overlay.pal
        self.setStyleSheet(
            f"QFrame{{background:{pal['surface']};border:1px solid {pal['firm']};"
            f"border-radius:7px;}}"
            f"QPushButton{{background:transparent;color:{pal['ink']};border:0;"
            f"padding:6px 10px;font-size:12px;}}"
            f"QPushButton:hover{{color:{pal['accent']};}}"
        )
        layout = QGridLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(0)
        self.buttons: dict[str, QPushButton] = {}
        for index, (key, label) in enumerate((("copy", "複製"), ("translate", "翻譯"),
                           ("note", "寫筆記"), ("ask", "問這段"),
                           ("highlight", "螢光筆"))):
            button = QPushButton(label)
            layout.addWidget(button, index // 3, index % 3)
            self.buttons[key] = button
        self.buttons["highlight"].setCheckable(True)
        self.buttons["highlight"].setStyleSheet(
            "QPushButton:checked { background:#ffe96b; color:#29220a; }"
        )
        self.buttons["highlight"].setToolTip("開：已標記，點一下移除；關：點一下標記並保存。")
        self.buttons["copy"].clicked.connect(self._copy)
        self._overlay = overlay

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._overlay.selected_text())
        self.buttons["copy"].setText("已複製")

    def place(self, point: QPoint, width: int, height: int) -> None:
        self.buttons["copy"].setText("複製")
        marked = bool(self._overlay.selected_highlights())
        self.buttons["highlight"].setChecked(marked)
        self.buttons["highlight"].setText("螢光筆：開" if marked else "螢光筆：關")
        self.adjustSize()
        x = min(max(point.x() - self.width() // 2, 6), max(width - self.width() - 6, 6))
        y = point.y() + 14
        if y + self.height() > height - 6:
            y = max(point.y() - self.height() - 14, 6)
        self.move(x, y)
        self.show()
        self.raise_()


class _ResultPanel(QFrame):
    """A translation shown where the words are, not in a tab somewhere else."""

    def __init__(self, overlay: SelectionOverlay) -> None:
        super().__init__(overlay)
        pal = overlay.pal
        self.setStyleSheet(
            f"QFrame{{background:{pal['surface']};border:1px solid {pal['firm']};"
            f"border-radius:8px;}}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)
        self.head = QLabel()
        self.head.setStyleSheet(
            f"color:{pal['accent']};font-size:10.5px;font-weight:600;border:0;"
        )
        layout.addWidget(self.head)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.setStyleSheet(f"color:{pal['ink']};font-size:13.5px;border:0;")
        layout.addWidget(self.body)
        self.refine = QPushButton("用 AI 精譯(保留術語)")
        ai_style.mark(self.refine)
        layout.addWidget(self.refine)
        self.setMaximumWidth(460)

    def set_text(self, title: str, text: str, refinable: bool = False) -> None:
        self.head.setText(title)
        self.body.setText(text)
        self.refine.setVisible(refinable)
        self.adjustSize()

    def place(self, anchor: QRect, width: int, height: int) -> None:
        self.adjustSize()
        x = min(max(anchor.left(), 8), max(width - self.width() - 8, 8))
        y = anchor.bottom() + 6
        if y + self.height() > height - 8:
            y = max(anchor.top() - self.height() - 6, 8)
        self.move(x, y)
        self.show()
        self.raise_()
