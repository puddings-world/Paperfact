"""Actual note editor/Data saves reconcile with an independent research database."""

import sqlite3
from contextlib import closing

from PySide6.QtWidgets import QApplication
from test_sync_capture import bound as bound
from test_sync_capture import make, seed

from paper_daily import store, sync_capture
from paper_daily.desktop import main, note_editor
from paper_daily.sync_service import ReferenceService


def query(path, sql):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(sql).fetchall()


def test_actual_note_editor_saves_once_syncs_and_retains_a_late_stale_edit(
    bound, monkeypatch, tmp_path
):
    app = QApplication.instance() or QApplication([])
    seed()
    a = bound
    b = make(tmp_path / "laptop.sqlite", "b")
    service = ReferenceService(tmp_path / "authority.sqlite")
    ta, tb = service.enroll("workspace", "a"), service.enroll("workspace", "b")
    a.sync_once(service, ta, limit=1000)
    b.sync_once(service, tb, limit=1000)
    monkeypatch.setattr(store, "DB_PATH", b.journal.path)
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="b")
    data = main.Data()
    with store.connect() as conn:
        row = dict(conn.execute("SELECT * FROM notes").fetchone())
    snapshot = data.note_for_edit(row["paper_id"], row["id"])
    assert snapshot["observation"] is not None
    calls = []

    def save(body):
        calls.append(body)
        data.update_note(row["id"], body, expected=snapshot)

    editor = note_editor.NoteEditor(row["body"], main.palette(), language="en", save=save)
    editor.show()
    try:
        editor.editor.setPlainText("Saved in the actual laptop editor")
        editor.accept()
        editor.accept()
        assert calls == ["Saved in the actual laptop editor"]
        assert not editor.isVisible()
        assert query(a.journal.path, "SELECT body FROM notes") == [("first",)]
        pending = b.journal.pending(1000)
        assert len(pending) == 1 and pending[0]["payload"]["body"] == calls[0]
        assert pending[0]["payload"]["created_at"] == row["created_at"]
        b.sync_once(service, tb, limit=1000)
        a.sync_once(service, ta, limit=1000)
        assert query(a.journal.path, "SELECT body FROM notes") == [(calls[0],)]
        assert not b.journal.pending(1000)
    finally:
        editor.deleteLater()
        app.processEvents()

    old = data.note_for_edit(row["paper_id"], row["id"])
    stale = note_editor.NoteEditor(
        calls[0],
        main.palette(),
        language="en",
        save=lambda body: data.update_note(row["id"], body, expected=old),
    )
    stale.show()
    try:
        stale.editor.setPlainText("Keep this late human draft")
        monkeypatch.setattr(store, "DB_PATH", a.journal.path)
        origin = main.Data()
        fresh = origin.note_for_edit("local-paper", 1)
        origin.update_note(1, "Newer desktop text", expected=fresh)
        a.sync_once(service, ta, limit=1000)
        b.sync_once(service, tb, limit=1000)
        monkeypatch.setattr(store, "DB_PATH", b.journal.path)
        pending = b.journal.pending(1000)
        stale.accept()
        stale.accept()
        assert stale.isVisible() and stale.text() == "Keep this late human draft"
        assert stale.save_status.text() == note_editor.SAVE_TEXT["en"]["stale"]
        assert b.journal.pending(1000) == pending
        assert query(b.journal.path, "SELECT body FROM notes") == [("Newer desktop text",)]
        candidates = query(b.journal.path, "SELECT content FROM research_capture_candidates")
        assert len(candidates) == 1 and "Keep this late human draft" in candidates[0][0]
        assert query(a.journal.path, "SELECT body FROM notes") == [("Newer desktop text",)]
        assert query(b.journal.path, "SELECT created_at FROM notes") == [(row["created_at"],)]
    finally:
        stale.deleteLater()
        app.processEvents()
