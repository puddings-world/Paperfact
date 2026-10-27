"""A list opens on the papers last opened; ties fall through the menu order, and
only 自訂順序 takes a drag, which it then keeps."""

import pytest
from test_queue_keys import page as _page

from paper_daily import lists, store
from paper_daily.desktop import ui_state
from paper_daily.desktop.queue_view import PAPER_ROLE, SORT_IDS, ordered

page = _page


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()


def _shown(widget):
    return [widget.model.index(r, 0).data(PAPER_ROLE).id for r in range(widget.model.rowCount())]


def test_the_recent_order_is_the_default_and_ignores_the_old_numbered_setting(page, db):
    widget, _win = page
    with store.connect() as conn:
        store.set_kv(conn, "ui.sort", "4")
    widget.restore_sort()
    assert SORT_IDS[widget.sort.currentIndex()] == "recent"


def test_opened_papers_come_first_newest_first_and_the_rest_keep_list_order(page, db):
    widget, _win = page
    with store.connect() as conn:
        store.set_kv(conn, "ui.paper.opened:p3", "2026-10-27T01:00:00+00:00")
    ui_state.save("ui.paper.opened:p1", "2026-10-27T02:00:00+00:00")
    widget.sort.setCurrentIndex(SORT_IDS.index("recent"))
    widget.refresh()
    assert _shown(widget) == ["p1", "p3", "p0", "p2", "p4"]
    # Only 自訂順序 can be dragged: it is the order a drag changes.
    assert not widget.model.can_reorder
    widget.sort.setCurrentIndex(SORT_IDS.index("custom"))
    assert widget.model.can_reorder and _shown(widget) == ["p0", "p1", "p2", "p3", "p4"]


def test_choosing_a_sort_is_remembered_by_name(page, db):
    widget, _win = page
    widget.sort.setCurrentIndex(SORT_IDS.index("venue"))
    with store.connect() as conn:
        assert ui_state.read(conn, "ui.sort.mode") == "venue"
    widget.restore_sort()
    assert SORT_IDS[widget.sort.currentIndex()] == "venue"


def test_a_drag_in_the_custom_order_is_what_custom_shows_next_time(page, db, monkeypatch):
    widget, win = page
    saved = []
    monkeypatch.setattr(lists, "reorder_papers", lambda list_id, ids: saved.append(ids))
    widget.sort.setCurrentIndex(SORT_IDS.index("custom"))
    order = ["p4", "p0", "p1", "p2", "p3"]
    assert widget._save_paper_order(order)
    assert saved == [order] and [p.id for p in win.papers] == order
    widget.sort.setCurrentIndex(SORT_IDS.index("venue"))
    widget.sort.setCurrentIndex(SORT_IDS.index("custom"))
    assert _shown(widget) == order


def test_a_failed_drag_changes_neither_order_nor_sort(page, db, monkeypatch):
    widget, win = page

    def refuse(_list_id, _ids):
        raise ValueError("論文已變動")

    monkeypatch.setattr(lists, "reorder_papers", refuse)
    widget.sort.setCurrentIndex(SORT_IDS.index("custom"))
    before = [p.id for p in win.papers]
    assert not widget._save_paper_order(list(reversed(before)))
    assert [p.id for p in win.papers] == before
    assert SORT_IDS[widget.sort.currentIndex()] == "custom"


def _paper(i, **kw):
    from test_queue_keys import _paper as make

    paper = make(i)
    for key, value in kw.items():
        setattr(paper, key, value)
    return paper


def test_ties_fall_through_the_menu_order_then_the_list_order():
    a = _paper(1, citations=10, venue="MICCAI", year=2025)
    b = _paper(2, citations=10, venue="MICCAI", year=2026)
    c = _paper(3, citations=10, venue="MICCAI", year=2026, opened_at="2026-10-27T01:00:00+00:00")
    d = _paper(4, citations=50, venue="arXiv", year=2024)
    e = _paper(5, citations=10, venue="MICCAI", year=2026)
    rows = list(enumerate([a, b, c, d, e], 1))
    # Most cited first; among the ties the opened one, then newer, then list order.
    assert [p.id for _i, p in ordered(rows, "citations")] == ["p4", "p3", "p2", "p5", "p1"]
    # Oldest first does not get undone by the newest-first tiebreak.
    assert [p.id for _i, p in ordered(rows, "oldest")][0] == "p4"
    assert [p.id for _i, p in ordered(rows, "oldest")][-3:] == ["p3", "p2", "p5"]
    assert ordered(rows, "custom") == rows


def test_the_menu_lists_sorts_by_importance_with_custom_last():
    assert SORT_IDS[:6] == ["recent", "venue", "newest", "oldest", "citations", "dependents"]
    assert SORT_IDS[-1] == "custom"
