"""Refresh observes committed research, including writers without MCP receipts."""

import os
import sqlite3

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QWidget

from paper_daily import lists, store
from paper_daily.desktop.workspace_changes import WorkspaceChanges

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    # Other desktop tests share this QApplication. Their menus / synthetic mouse
    # presses must not masquerade as an active user interaction in this fixture.
    popup = app.activePopupWidget()
    if popup is not None:
        popup.close()
    release_target = QWidget()
    for button in (
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.RightButton,
        Qt.MouseButton.MiddleButton,
    ):
        if app.mouseButtons() & button:
            QTest.mouseRelease(release_target, button)
    app.processEvents()
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as conn:
        conn.execute("INSERT INTO lists VALUES('a','Alpha',NULL,'now')")
        store.upsert_papers(conn, [dict(id="p1", title="One", year=2025, venue="test", source="t")])
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES('a','p1',0,'now')"
        )
    return app


def external(sql, args=()):
    # An independent SQLite connection does not call any app mutation helper.
    with sqlite3.connect(store.DB_PATH) as conn:
        conn.execute(sql, args)


def watcher():
    observer = WorkspaceChanges()
    observer.timer.stop()
    events = []
    observer.changed.connect(lambda: events.append(True))
    return observer, events


def test_legacy_add_and_remove_refresh_without_integration_events(workspace, monkeypatch):
    monkeypatch.setattr(lists, "parse_bibliography", lambda *_a, **_k: [{"title": "New paper"}])
    monkeypatch.setattr(lists.s2, "match_title", lambda *_a: None)
    observer, events = watcher()
    result = lists.add_paper("a", "New paper", log=lambda _: None)
    assert result["added"] == 1
    observer.poll()
    assert events == [True]
    assert lists.remove_paper("a", result["paper_ids"][0])
    observer.poll()
    assert events == [True, True]
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM integration_changes").fetchone()[0] == 0


def test_external_transaction_is_visible_only_once_after_commit_and_not_after_rollback(workspace):
    observer, events = watcher()
    conn = sqlite3.connect(store.DB_PATH)
    try:
        conn.execute("UPDATE lists SET name='Pending' WHERE id='a'")
        observer.poll()
        assert events == []
        conn.rollback()
        observer.poll()
        assert events == []
        conn.execute("UPDATE lists SET name='Renamed' WHERE id='a'")
        conn.execute("UPDATE list_papers SET state='read' WHERE list_id='a'")
        conn.commit()
        observer.poll()
        observer.poll()
        assert events == [True]
    finally:
        conn.close()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE papers SET title='Changed' WHERE id='p1'",
        "UPDATE list_papers SET position=4 WHERE list_id='a'",
        "INSERT INTO dives(paper_id,body,written_at) VALUES('p1','explanation','now')",
        "INSERT INTO pins VALUES('a','p1','now')",
        "INSERT INTO kv VALUES('lists.order','[\"a\"]')",
        "INSERT INTO kv VALUES('followups.checked.p1','true')",
        "DELETE FROM list_papers WHERE list_id='a'",
        "DELETE FROM lists WHERE id='a'",
    ],
)
def test_relevant_external_changes_invalidate_list_views(workspace, sql):
    observer, events = watcher()
    external(sql)
    observer.poll()
    assert events == [True]


def test_account_and_ui_polling_and_unlisted_corpus_do_not_refresh(workspace):
    observer, events = watcher()
    external("INSERT INTO kv VALUES('usage.refresh','123')")
    external("INSERT INTO kv VALUES('ui.list','\"a\"')")
    with store.connect() as conn:
        store.upsert_papers(
            conn, [dict(id="unlisted", title="Corpus", year=2025, venue="test", source="t")]
        )
    observer.poll()
    assert events == []
    store.init_db()
    observer.poll()
    assert events == [], "Repeated schema initialization must not generate a change"


def test_open_queue_refresh_preserves_checked_papers_filter_selection_and_reader_draft(
    workspace,
    monkeypatch,
):
    from paper_daily.desktop.main import MainWindow

    window = MainWindow()
    monkeypatch.setattr(window.queue_page, "enqueue_pdfs", lambda: None)
    window.active_list = "a"
    window.refresh_lists()
    window.show_queue()
    window.set_marked(["p1"])
    window.queue_page.search.setText("One")
    window.queue_page._select("p1")
    window.reader_page.note_edit.setPlainText("Unfinished note")
    window.reader_page.ask_box.setText("Unfinished question")
    with sqlite3.connect(store.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('p2','One more','one more','test',2026,'external')"
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES('a','p2',1,'now')"
        )
    window._poll_external_lists()
    assert len(window.papers) == 2 and window.queue_page.model.rowCount() == 2, (
        workspace.activeModalWidget(),
        workspace.activePopupWidget(),
        workspace.mouseButtons(),
    )
    assert window.marked_ids() == ["p1"]
    assert window.queue_page.search.text() == "One"
    assert window.queue_page._current_paper().id == "p1"
    assert "未讀 2" in window.progress.text()
    assert "2" in window.list_picker.currentText()
    assert window.reader_page.note_edit.toPlainText() == "Unfinished note"
    window.stack.setCurrentWidget(window.reader_page)
    external("UPDATE lists SET name='New name' WHERE id='a'")
    window._poll_external_lists()
    assert window.stack.currentWidget() is window.reader_page
    assert window.reader_page.ask_box.text() == "Unfinished question"
    window.close()
    window.deleteLater()


def test_modal_defers_refresh_and_storage_failure_retries_without_another_write(
    workspace, monkeypatch
):
    from paper_daily.desktop.main import MainWindow

    window = MainWindow()
    dialog = QDialog(window)
    dialog.setModal(True)
    dialog.show()
    workspace.processEvents()
    external("UPDATE lists SET name='Later' WHERE id='a'")
    window._poll_external_lists()
    assert window._external_refresh_pending
    assert "Later" not in window.list_picker.currentText()
    dialog.close()
    real = window.refresh_lists

    def fail():
        raise sqlite3.OperationalError("busy fixture")

    monkeypatch.setattr(window, "refresh_lists", fail)
    window._poll_external_lists()
    assert window._external_refresh_pending
    monkeypatch.setattr(window, "refresh_lists", real)
    window._poll_external_lists()
    assert not window._external_refresh_pending, (
        workspace.activeModalWidget(),
        workspace.activePopupWidget(),
        workspace.mouseButtons(),
    )
    assert "Later" in window.list_picker.currentText()
    window.close()
    window.deleteLater()


def test_existing_database_and_already_open_writer_acquire_tracking(tmp_path, monkeypatch):
    from paper_daily.workspace_revision import SCHEMA as revision_schema

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "legacy.db")
    legacy = sqlite3.connect(store.DB_PATH)
    try:
        legacy.executescript(store.SCHEMA.removesuffix(revision_schema))
        legacy.execute("INSERT INTO lists VALUES('old','Original','curated note','yesterday')")
        legacy.commit()
        # Prime an old connection's statement cache before the schema migration.
        legacy.execute("UPDATE lists SET name=? WHERE id='old'", ("Original",))
        legacy.commit()
        store.init_db()
        observer, events = watcher()
        with store.connect() as conn:
            assert tuple(conn.execute("SELECT name,note FROM lists").fetchone()) == (
                "Original",
                "curated note",
            )
        legacy.execute("UPDATE lists SET name=? WHERE id='old'", ("From old process",))
        legacy.commit()
        observer.poll()
        assert events == [True]
        with store.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM workspace_revision").fetchone()[0] == 1
    finally:
        legacy.close()


@pytest.mark.parametrize("adopted", [None, "a"])
def test_routine_list_refresh_does_not_request_a_writer_lock(workspace, monkeypatch, adopted):
    if adopted:
        with store.connect() as conn:
            store.set_kv(conn, "lists.legacy_queue", adopted)
    monkeypatch.setattr(lists, "connect", lambda: store.connect(timeout=0.05))
    held = sqlite3.connect(store.DB_PATH)
    try:
        held.execute("BEGIN IMMEDIATE")
        assert lists.adopt_legacy_queue() == adopted
    finally:
        held.rollback()
        held.close()


def test_popup_defers_refresh_until_interaction_finishes(workspace):
    from paper_daily.desktop.main import MainWindow

    window = MainWindow()
    menu = QMenu(window)
    menu.addAction("Fixture choice")
    menu.popup(window.mapToGlobal(window.rect().center()))
    workspace.processEvents()
    try:
        external("UPDATE lists SET name='After menu' WHERE id='a'")
        window._poll_external_lists()
        assert window._external_refresh_pending
        assert "After menu" not in window.list_picker.currentText()
    finally:
        menu.close()
    workspace.processEvents()
    window._poll_external_lists()
    assert not window._external_refresh_pending
    assert "After menu" in window.list_picker.currentText()
    window.close()
    window.deleteLater()
