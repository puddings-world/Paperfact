"""A list opens on the papers last opened, and a drag there sets the list's order."""

import pytest
from test_queue_keys import page as _page

from paper_daily import lists, store
from paper_daily.desktop import ui_state
from paper_daily.desktop.queue_view import PAPER_ROLE, SORT_IDS

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
    assert widget.model.can_reorder


def test_choosing_a_sort_is_remembered_by_name(page, db):
    widget, _win = page
    widget.sort.setCurrentIndex(SORT_IDS.index("venue"))
    with store.connect() as conn:
        assert ui_state.read(conn, "ui.sort.mode") == "venue"
    widget.restore_sort()
    assert SORT_IDS[widget.sort.currentIndex()] == "venue"


def test_a_drag_in_the_recent_order_saves_it_as_the_custom_order(page, db, monkeypatch):
    widget, win = page
    saved = []
    monkeypatch.setattr(lists, "reorder_papers", lambda list_id, ids: saved.append(ids))
    widget.sort.setCurrentIndex(SORT_IDS.index("recent"))
    order = ["p4", "p0", "p1", "p2", "p3"]
    assert widget._save_paper_order(order)
    assert saved == [order] and [p.id for p in win.papers] == order
    assert SORT_IDS[widget.sort.currentIndex()] == "custom"
    with store.connect() as conn:
        assert ui_state.read(conn, "ui.sort.mode") == "custom"


def test_a_failed_drag_changes_neither_order_nor_sort(page, db, monkeypatch):
    widget, win = page

    def refuse(_list_id, _ids):
        raise ValueError("論文已變動")

    monkeypatch.setattr(lists, "reorder_papers", refuse)
    widget.sort.setCurrentIndex(SORT_IDS.index("recent"))
    before = [p.id for p in win.papers]
    assert not widget._save_paper_order(list(reversed(before)))
    assert [p.id for p in win.papers] == before
    assert SORT_IDS[widget.sort.currentIndex()] == "recent"
