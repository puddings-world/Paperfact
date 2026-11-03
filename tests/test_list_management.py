import sqlite3

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QInputDialog
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import analysis_schedule, lists, llm, store
from paper_daily.desktop import queue_view as page_module
from paper_daily.desktop.main import MainWindow
from paper_daily.desktop.queue_view import SORT_IDS

workspace = _workspace


def seed(n=4):
    llm.save_settings(profile="test", backend="cli", model="test-model", isolated=True)
    with store.connect() as conn:
        for name in ("alpha", "beta"):
            conn.execute("INSERT INTO lists(id,name,created_at) VALUES (?,?,?)", (name, name, name))
        store.upsert_papers(conn, [dict(id=f"p{i}", title=f"Paper {i}", venue="Test",
                                       year=2026, source="test")
                                   for i in range(n)])
        conn.executemany(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES ('alpha',?,?,?)",
            [(f"p{i}", i, "now") for i in range(n)],
        )


def papers(list_id="alpha"):
    with store.connect() as conn:
        return [r[0] for r in conn.execute(
            "SELECT paper_id FROM list_papers WHERE list_id=? ORDER BY position", (list_id,)
        )]


def test_rename_and_repeated_order_preserve_identity_and_members(workspace):
    seed()
    for i in range(50):
        lists.rename("alpha", f"  臨床研究 ({i})  ")
        lists.reorder(["beta", "alpha"] if i % 2 else ["alpha", "beta"])
    assert [r["id"] for r in lists.all_lists()] == ["beta", "alpha"]
    assert lists.all_lists()[1]["name"] == "臨床研究 (49)"
    assert papers() == ["p0", "p1", "p2", "p3"]
    with pytest.raises(ValueError):
        lists.rename("alpha", " \n ")
    with pytest.raises(ValueError):
        lists.rename("deleted", "Renamed")
    with pytest.raises(ValueError):
        lists.reorder(["alpha", "alpha"])
    assert [r["id"] for r in lists.all_lists()] == ["beta", "alpha"]


def test_large_paper_reorder_is_atomic_and_preserves_states(workspace):
    seed(5000)
    with store.connect() as conn:
        conn.execute("UPDATE list_papers SET state='read',read_at='yesterday' WHERE paper_id='p2'")
    original = papers()
    reversed_ids = original[::-1]
    lists.reorder_papers("alpha", reversed_ids)
    assert papers() == reversed_ids
    for invalid in (original[:-1], [*original[:-1], "foreign"], [original[0]] * len(original)):
        with pytest.raises(ValueError):
            lists.reorder_papers("alpha", invalid)
        assert papers() == reversed_ids
    with store.connect() as conn:
        assert tuple(conn.execute("SELECT state,read_at FROM list_papers WHERE paper_id='p2'")
                     .fetchone()) == ("read", "yesterday")
    assert papers("beta") == []


def test_legacy_queue_adoption_is_once_and_becomes_an_ordinary_list(workspace):
    assert lists.adopt_legacy_queue() is None
    seed()
    with store.connect() as conn:
        conn.execute("INSERT INTO queue(paper_id,rank,state) VALUES ('p0',2,'read')")
        conn.execute("INSERT INTO queue(paper_id,rank,state) VALUES ('p1',1,'delivered')")
        conn.execute("INSERT INTO queue(paper_id,rank,state) VALUES ('p2',3,'skipped')")
        conn.execute("INSERT INTO pins VALUES ('queue','p0','now')")
    adopted = lists.adopt_legacy_queue()
    assert papers(adopted) == ["p1", "p0"]
    lists.rename(adopted, "My renamed ML list")
    lists.remove_paper(adopted, "p1")
    for _ in range(10):
        assert lists.adopt_legacy_queue() == adopted
    assert papers(adopted) == ["p0"]
    with store.connect() as conn:
        state = conn.execute("SELECT state FROM list_papers WHERE list_id=?", (adopted,))
        assert state.fetchone()[0] == "read"
        assert conn.execute("SELECT 1 FROM pins WHERE scope=?", (adopted,)).fetchone()
        assert conn.execute("SELECT count(*) FROM queue").fetchone()[0] == 3
        assert analysis_schedule.load(conn)["queue"] == 0
    lists.delete_list(adopted)
    lists.adopt_legacy_queue()
    assert not any(row["id"] == adopted for row in lists.all_lists())


def test_overview_native_move_and_rename_keep_active_list(workspace, monkeypatch):
    seed()
    window = MainWindow()
    try:
        window._open_list("alpha")
        window.show_lists()
        page = window.lists_page
        assert page.view.model().moveRows(QModelIndex(), 0, 1, QModelIndex(), 2)
        assert [r["id"] for r in lists.all_lists()] == ["beta", "alpha"]
        assert window.active_list == "alpha"
        page.view.setCurrentRow(0)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("研究乙", True))
        page.rename_button.click()
        assert lists.all_lists()[0]["name"] == "研究乙"
        assert page.view.currentItem().data(Qt.ItemDataRole.UserRole) == "beta"
        assert window.active_list == "alpha"
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("ignored", False))
        page.rename_button.click()
        assert lists.all_lists()[0]["name"] == "研究乙"
        window.refresh_lists()
        assert window.list_picker.itemData(0) == "beta"
    finally:
        window.close()
        window.deleteLater()


def test_paper_native_drop_persists_and_rejects_stale_or_filtered_drag(workspace):
    seed()
    window = MainWindow()
    try:
        window._open_list("alpha")
        page = window.queue_page
        page.sort.setCurrentIndex(SORT_IDS.index("custom"))
        page.refresh()
        model = page.model
        data = model.mimeData([model.index(0)])
        assert model.dropMimeData(data, Qt.DropAction.MoveAction, 4, 0, QModelIndex())
        assert papers() == ["p1", "p2", "p3", "p0"]
        assert [p.id for p in window.papers] == papers()
        assert not model.dropMimeData(data, Qt.DropAction.MoveAction, 0, 0, QModelIndex())
        page.sort.setCurrentIndex(SORT_IDS.index("citations"))
        assert not model.can_reorder
        assert not model.moveRows(QModelIndex(), 0, 1, QModelIndex(), 4)
        page.sort.setCurrentIndex(SORT_IDS.index("custom"))
        data = model.mimeData([model.index(0)])
        window._open_list("beta")
        assert not model.dropMimeData(data, Qt.DropAction.MoveAction, 0, 0, QModelIndex())
        window._open_list("alpha")
        page.search.setText("Paper 1")
        page.refresh()
        assert not model.can_reorder
        assert papers() == ["p1", "p2", "p3", "p0"]
    finally:
        window.close()
        window.deleteLater()


def test_failed_paper_drag_leaves_view_and_database_unchanged(workspace, monkeypatch):
    seed()
    window = MainWindow()
    try:
        window._open_list("alpha")
        page = window.queue_page
        page.sort.setCurrentIndex(SORT_IDS.index("custom"))
        def fail(*args):
            raise sqlite3.OperationalError("fixture locked")
        monkeypatch.setattr(lists, "reorder_papers", fail)
        assert not page.model.moveRows(QModelIndex(), 0, 1, QModelIndex(), 4)
        assert [p.id for p in window.papers] == papers()
        assert page.model.index(0).data() == "Paper 0"
        assert "未儲存" in page.blurb.text()
    finally:
        window.close()
        window.deleteLater()


def test_pinned_papers_can_be_dragged_into_their_own_order_and_keep_it(workspace):
    from paper_daily.desktop.queue_view import PAPER_ROLE

    seed(5)
    window = MainWindow()
    try:
        window._open_list("alpha")
        page = window.queue_page
        page.sort.setCurrentIndex(SORT_IDS.index("citations"))
        assert window.set_pinned(["p1", "p2", "p3"], True)
        model = page.model

        def shown():
            return [model.index(i).data(PAPER_ROLE).id for i in range(model.rowCount())]

        pinned = shown()[:3]
        assert sorted(pinned) == ["p1", "p2", "p3"] and model.can_reorder_pins
        # Drag the first pinned paper below the third: allowed, and remembered.
        data = model.mimeData([model.index(0)])
        assert model.dropMimeData(data, Qt.DropAction.MoveAction, 3, 0, QModelIndex())
        order = pinned[1:] + pinned[:1]
        assert shown()[:3] == order
        page.refresh()
        assert shown()[:3] == order
        # A pinned paper is never dropped among the others, and the others stay put.
        assert not model.moveRows(QModelIndex(), 0, 1, QModelIndex(), 5)
        assert not model.moveRows(QModelIndex(), 4, 1, QModelIndex(), 0)
        assert shown()[:3] == order
        # The list's own order and its pins are untouched.
        assert papers() == ["p0", "p1", "p2", "p3", "p4"]
    finally:
        window.close()
        window.deleteLater()


def test_the_pin_button_answers_the_pointer(workspace):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from paper_daily.desktop.queue_view import PIN_W

    seed(2)
    window = MainWindow()
    try:
        window.resize(1000, 700)
        window.show()
        window._open_list("alpha")
        page = window.queue_page
        viewport = page.view.viewport()
        row = page.view.visualRect(page.model.index(0))
        over = QPointF(viewport.width() - PIN_W / 2, row.center().y())
        move = QMouseEvent(QEvent.Type.MouseMove, over, over, Qt.MouseButton.NoButton,
                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(viewport, move)
        assert page._pin_hover_row == 0
        assert viewport.cursor().shape() == Qt.CursorShape.PointingHandCursor
        assert "置頂" in viewport.toolTip()
        QApplication.sendEvent(viewport, QEvent(QEvent.Type.Leave))
        assert page._pin_hover_row is None
    finally:
        window.close()
        window.deleteLater()


def test_tick_bar_actions_have_list_keys(workspace, monkeypatch):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    seed(3)
    window = MainWindow()
    try:
        window.show()
        window._open_list("alpha")
        page = window.queue_page
        page.view.setFocus()
        QApplication.processEvents()

        def ids():
            return [p.id for _i, p in page.model._rows]

        QTest.keyClick(page.view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        assert page.ticked() == ids()
        QTest.keyClick(page.view, Qt.Key.Key_T, Qt.KeyboardModifier.ShiftModifier)
        assert all(p.pinned for _i, p in page.model._rows)
        QTest.keyClick(page.view, Qt.Key.Key_T, Qt.KeyboardModifier.ShiftModifier)
        assert not any(p.pinned for _i, p in page.model._rows)
        QTest.keyClick(page.view, Qt.Key.Key_M, Qt.KeyboardModifier.ShiftModifier)
        assert all(p.read for p in window.papers)
        QTest.keyClick(page.view, Qt.Key.Key_A,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        assert page.ticked() == []

        page._select(ids()[0])
        page.view.setFocus()
        first = page._current_paper().id
        QTest.keyClick(page.view, Qt.Key.Key_M)
        assert not next(p for p in window.papers if p.id == first).read

        QTest.keyClick(page.view, Qt.Key.Key_A)  # Tick the highlighted row.
        asked = []
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(1)
                            or QMessageBox.StandardButton.No)
        QTest.keyClick(page.view, Qt.Key.Key_Delete)
        assert asked == [1] and first in papers()  # Asked first; said no.
        assert "Shift+M" in next(b for b in page._batch_buttons
                                 if b.text() == "標記已讀").toolTip()
    finally:
        window.close()
        window.deleteLater()


def test_the_venue_tag_opens_the_papers_page(workspace, monkeypatch):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QDesktopServices, QMouseEvent
    from PySide6.QtWidgets import QApplication

    seed(2)
    with store.connect() as conn:
        conn.execute("UPDATE papers SET page_url='https://doi.org/10.1/x' WHERE id='p0'")
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    window = MainWindow()
    try:
        window.resize(1000, 700)
        window.show()
        window._open_list("alpha")
        page = window.queue_page
        viewport = page.view.viewport()
        index = next(page.model.index(i) for i in range(page.model.rowCount())
                     if page.model.index(i).data(Qt.ItemDataRole.DisplayRole) == "Paper 0")
        rect = page.view.itemDelegate().link_rect(page.view.visualRect(index),
                                                  index.data(page_module.PAPER_ROLE))
        assert not rect.isEmpty()
        point = QPointF(rect.center())
        for kind, button in ((QEvent.Type.MouseMove, Qt.MouseButton.NoButton),
                             (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton)):
            QApplication.sendEvent(viewport, QMouseEvent(
                kind, point, point, button, button, Qt.KeyboardModifier.NoModifier))
            if kind == QEvent.Type.MouseMove:
                assert "出版頁面（DOI）" in viewport.toolTip()
        assert opened == ["https://doi.org/10.1/x"]
        assert window.reader_page is not None and window.stack.currentWidget() is page
    finally:
        window.close()
        window.deleteLater()
