"""The list page works from the keyboard: it has the keys on arrival, at the paper
just read; ↑↓ choose, Enter opens, A ticks and T pins the highlighted row, and the
search box hands ↓ to the results."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from paper_daily.desktop.main import LIGHT, Paper  # noqa: E402
from paper_daily.desktop.queue_view import MARK_W, PIN_W, QueuePage  # noqa: E402


def _paper(i):
    return Paper(
        id=f"p{i}",
        title=f"Paper {i}",
        venue="MICCAI",
        year=2026,
        award=None,
        paper_type=None,
        authors=[],
        abstract=None,
        citations=None,
        is_canon=False,
        pdf_url=None,
        page_url=None,
        arxiv_id=None,
        role="list",
        reason=None,
        state="pending",
        touched_at=None,
        _has_pdf=True,
    )


class _Window:
    pal = LIGHT
    active_list = "list"

    def __init__(self):
        self.papers = [_paper(i) for i in range(5)]
        self.marked: list[str] = []
        self.opened: list[str] = []
        self._last_paper = "p3"
        self.list_picker = QComboBox()
        self.list_picker.addItem("Cataract (0/5)")
        self.page = None

    def show_pocket(self):
        pass

    def reload(self):
        pass

    def marked_ids(self):
        return self.marked

    def toggle_marked(self, paper_id):
        if paper_id in self.marked:
            self.marked.remove(paper_id)
        else:
            self.marked.append(paper_id)

    def set_pinned(self, ids, on):
        for paper in self.papers:
            if paper.id in ids:
                paper.pinned = on
        self.page.refresh()

    def open_paper(self, paper_id):
        self.opened.append(paper_id)


@pytest.fixture
def page():
    app = QApplication.instance() or QApplication([])
    win = _Window()
    page = QueuePage(win)
    win.page = page
    page.refresh()
    page.resize(900, 700)
    page.show()
    page.activateWindow()
    for _ in range(5):
        app.processEvents()
    yield page, win
    page.deleteLater()
    app.processEvents()


def _current(page):
    return page._current_paper().id


def test_the_list_has_the_keys_on_arrival_at_the_paper_just_read(page):
    page, _win = page
    assert QApplication.focusWidget() is page.view
    assert _current(page) == "p3"


def test_arrows_choose_and_enter_opens(page):
    page, win = page
    QTest.keyClick(page.view, Qt.Key.Key_Down)
    assert _current(page) == "p4"
    QTest.keyClick(page.view, Qt.Key.Key_Return)
    assert win.opened == ["p4"]


def test_a_ticks_and_t_pins_the_highlighted_row_which_stays_highlighted(page):
    page, win = page
    QTest.keyClick(page.view, Qt.Key.Key_A)
    assert win.marked == ["p3"]
    QTest.keyClick(page.view, Qt.Key.Key_T)
    # Pinned rows move to the top, and the highlight goes with the paper.
    assert win.papers[3].pinned and page.model._rows[0][1].id == "p3"
    assert _current(page) == "p3"


def test_letters_in_the_search_box_are_typing_and_down_enters_the_results(page):
    page, win = page
    page.search.setFocus()
    QTest.keyClicks(page.search, "at")
    assert page.search.text() == "at" and win.marked == []
    QTest.keyClick(page.search, Qt.Key.Key_Down)
    assert QApplication.focusWidget() is page.view


def test_open_anywhere_switches_to_the_list_that_holds_the_paper():
    from types import SimpleNamespace

    from paper_daily.desktop.main import MainWindow

    QApplication.instance() or QApplication([])
    picker = QComboBox()
    picker.addItem("queue", None)
    picker.addItem("Cataract", "cat")
    holdings = {None: [_paper(1)], "cat": [_paper(7)]}
    opened = []
    win = SimpleNamespace(
        papers=holdings[None],
        list_picker=picker,
        data=SimpleNamespace(queue=lambda list_id=None: holdings[list_id]),
        reader_page=SimpleNamespace(paper=None),
    )

    def open_paper(paper_id):
        opened.append(paper_id)
        win.reader_page.paper = SimpleNamespace(id=paper_id)

    win.open_paper = open_paper
    assert MainWindow.open_anywhere(win, "p7")
    assert picker.currentData() == "cat" and opened == ["p7"]
    assert not MainWindow.open_anywhere(win, "missing")


def test_pending_scroll_restore_is_cancelled_when_the_list_is_destroyed(monkeypatch):
    from shiboken6 import delete

    app = QApplication.instance() or QApplication([])
    win = _Window()
    page = QueuePage(win)
    win.page = page
    touched = []
    original = page.view.verticalScrollBar

    def scroll_bar():
        touched.append(True)
        return original()

    monkeypatch.setattr(page.view, "verticalScrollBar", scroll_bar)
    page.refresh()
    touched.clear()
    delete(page)
    app.processEvents()
    assert not touched, "a queued refresh must never access a destroyed list"


def test_enter_opens_even_where_the_view_does_not_activate_on_enter(page):
    # macOS list views take Return as "edit" and emit no activated signal.
    page, win = page
    page.view.blockSignals(True)
    QTest.keyClick(page.view, Qt.Key.Key_Return)
    QTest.keyClick(page.view, Qt.Key.Key_Enter)
    assert win.opened == ["p3", "p3"]


def test_the_batch_actions_appear_only_once_a_paper_is_ticked(page):
    page, win = page
    page.update_pocket_btn()
    shown = [b.text() for b in page._batch_buttons if not b.isHidden()]
    assert shown == ["全選"]
    QTest.keyClick(page.view, Qt.Key.Key_A)
    page.update_pocket_btn()
    shown = [b.text() for b in page._batch_buttons if not b.isHidden()]
    assert "置頂" in shown and "標記已讀" in shown and "從清單移除" in shown
    assert page.sel_label.text().startswith("已勾選 1 篇")


def _row_point(page, row, x):
    rect = page.view.visualRect(page.model.index(row))
    return QPoint(x, rect.center().y())


@pytest.mark.parametrize("zone", ["tick", "pin"])
def test_quick_clicks_on_the_tick_box_or_pin_never_open_the_paper(page, zone):
    # Ticking boxes fast, or re-ticking the paper opened last, used to reach the
    # list's own click handling and open the paper as well.
    page, win = page
    viewport = page.view.viewport()
    x = MARK_W // 2 if zone == "tick" else viewport.width() - PIN_W // 2
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=_row_point(page, 1, 300))
    assert win.opened == ["p1"]
    point = _row_point(page, 1, x)
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(viewport, Qt.MouseButton.LeftButton, pos=point)
    assert win.opened == ["p1"]
    if zone == "tick":
        # Each press counts, a double click's second one too: ticked, off, on.
        assert win.marked == ["p1"]
