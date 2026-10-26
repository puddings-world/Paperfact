"""Editing keeps drafts until a guarded save succeeds in its original workspace."""

import sqlite3
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QWidget
from test_sync_capture import bound as _bound_fixture
from test_sync_capture import seed

from paper_daily import store
from paper_daily.desktop import main, note_editor

bound = _bound_fixture


@pytest.fixture
def notes(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "papers.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    store.init_db()
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) VALUES('paper-a','Original','now')"
        )
    return SimpleNamespace(app=app, path=path, data=main.Data())


def body(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT body FROM notes WHERE id=1").fetchone()[0]


def test_editor_saves_once_and_closes_only_after_success(notes):
    calls = []
    editor = None

    def save(text):
        calls.append(text)
        editor.accept()  # A reentrant activation must not duplicate the save.

    editor = note_editor.NoteEditor("Draft", main.palette(), save=save)
    editor.show()
    try:
        editor.accept()
        editor.accept()
        assert calls == ["Draft"]
        assert editor.result() == QDialog.DialogCode.Accepted
        assert not editor.isVisible()
    finally:
        editor.deleteLater()
        notes.app.processEvents()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_save_failure_keeps_draft_selection_and_allows_retry(notes, language):
    attempts = []

    def save(text):
        attempts.append(text)
        if len(attempts) == 1:
            raise OSError("private provider message must not be displayed")

    editor = note_editor.NoteEditor("Unsaved draft", main.palette(), save=save, language=language)
    editor.show()
    editor.editor.selectAll()
    try:
        editor.accept()
        assert editor.isVisible()
        assert editor.text() == "Unsaved draft"
        assert editor.editor.textCursor().selectedText() == "Unsaved draft"
        assert editor.save_button.isEnabled()
        assert editor.save_status.text() == note_editor.SAVE_TEXT[language]["failed"]
        editor.accept()
        assert editor.result() == QDialog.DialogCode.Accepted
        assert attempts == ["Unsaved draft", "Unsaved draft"]
    finally:
        editor.deleteLater()
        notes.app.processEvents()


def test_empty_or_cancelled_editor_never_saves(notes):
    calls = []
    editor = note_editor.NoteEditor("  ", main.palette(), save=calls.append)
    editor.show()
    try:
        editor.accept()
        assert editor.isVisible()
        assert editor.save_status.text()
        editor.editor.setPlainText("A cancelled draft")
        editor.reject()
        assert calls == []
        assert editor.result() == QDialog.DialogCode.Rejected
    finally:
        editor.deleteLater()
        notes.app.processEvents()


def test_retained_conflict_is_explained_without_exposing_error_text(notes):
    class Conflict(Exception):
        candidate_id = "candidate-1"

    def save(_text):
        raise Conflict("private body")

    editor = note_editor.NoteEditor("My revision", main.palette(), save=save, language="en")
    editor.show()
    try:
        editor.accept()
        assert editor.isVisible() and editor.text() == "My revision"
        assert editor.save_status.text() == note_editor.SAVE_TEXT["en"]["stale"]
    finally:
        editor.deleteLater()
        notes.app.processEvents()


def test_note_edit_snapshot_and_save_preserve_anchor(notes):
    with store.connect() as conn:
        conn.execute("UPDATE notes SET page=3,anchor='fixture-anchor' WHERE id=1")
    snapshot = notes.data.note_for_edit("paper-a", 1)
    assert snapshot["observation"] is None
    notes.data.update_note(1, "Revised", expected=snapshot)
    with sqlite3.connect(notes.path) as conn:
        assert conn.execute("SELECT body,page,anchor FROM notes").fetchone() == (
            "Revised", 3, "fixture-anchor"
        )
    assert notes.data.note_for_edit("different-paper", 1) is None


def test_legacy_stale_editor_does_not_overwrite_another_window(notes):
    snapshot = notes.data.note_for_edit("paper-a", 1)
    notes.data.update_note(1, "Newer elsewhere")
    with pytest.raises(ValueError, match="changed"):
        notes.data.update_note(1, "Stale draft", expected=snapshot)
    assert body(notes.path) == "Newer elsewhere"


@pytest.mark.parametrize("change", ["delete", "replace", "workspace"])
def test_removed_or_rebound_note_rejects_old_editor(notes, tmp_path, monkeypatch, change):
    snapshot = notes.data.note_for_edit("paper-a", 1)
    if change == "workspace":
        other = tmp_path / "other.db"
        monkeypatch.setattr(store, "DB_PATH", other)
        store.init_db()
        with store.connect() as conn:
            conn.execute("INSERT INTO notes VALUES(1,'paper-a','Other','then','note',NULL,NULL)")
    else:
        with store.connect() as conn:
            conn.execute("DELETE FROM notes WHERE id=1")
            if change == "replace":
                conn.execute(
                    "INSERT INTO notes VALUES(1,'paper-b','Different','then','note',NULL,NULL)"
                )
    with pytest.raises(ValueError):
        notes.data.update_note(1, "Wrong target", expected=snapshot)
    if change == "workspace":
        assert body(notes.path) == "Original"
        assert body(other) == "Other"
    elif change == "replace":
        assert body(notes.path) == "Different"
    else:
        with sqlite3.connect(notes.path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0


@pytest.mark.parametrize("action", ["save", "cancel", "stale", "paper-switch"])
def test_real_reader_note_edit_flow(notes, monkeypatch, action):
    reader = QWidget()
    reader.paper = SimpleNamespace(id="paper-a")
    reader.win = SimpleNamespace(data=notes.data, pal=main.palette())
    refreshed = []
    reader._load_notes = lambda: refreshed.append(True)
    observed = []

    class ScriptedEditor(note_editor.NoteEditor):
        def exec(self):
            self.show()
            self.editor.setPlainText("My edited note")
            if action == "cancel":
                self.reject()
                return self.result()
            if action == "stale":
                notes.data.update_note(1, "Remote revision")
            if action == "paper-switch":
                reader.paper = SimpleNamespace(id="paper-b")
            self.accept()
            observed.append((self.isVisible(), self.text(), self.save_status.text()))
            return self.result()

    monkeypatch.setattr(main, "NoteEditor", ScriptedEditor)
    try:
        main.ReaderPage._edit_note(reader, 1)
        expected = {"save": "My edited note", "stale": "Remote revision"}.get(action, "Original")
        assert body(notes.path) == expected
        assert refreshed == ([True] if action == "save" else [])
        if action in ("stale", "paper-switch"):
            assert observed[0][0] and observed[0][1] == "My edited note" and observed[0][2]
    finally:
        reader.close()
        reader.deleteLater()
        notes.app.processEvents()


def test_bound_note_save_records_real_outbox_and_stale_retry_retains_one_candidate(bound):
    app = QApplication.instance() or QApplication([])
    seed()
    data = main.Data()
    stale = data.note_for_edit("local-paper", 1)
    assert stale["observation"] is not None
    data.update_note(1, "Newer revision", expected=data.note_for_edit("local-paper", 1))
    pending = len(bound.journal.pending())
    assert bound.journal.pending()[-1]["payload"]["body"] == "Newer revision"
    editor = note_editor.NoteEditor(
        "My retained candidate", main.palette(), language="en",
        save=lambda text: data.update_note(1, text, expected=stale),
    )
    editor.show()
    try:
        editor.accept()
        editor.accept()
        assert editor.isVisible() and editor.text() == "My retained candidate"
        assert editor.save_status.text() == note_editor.SAVE_TEXT["en"]["stale"]
        assert len(bound.journal.pending()) == pending
        with sqlite3.connect(store.DB_PATH) as conn:
            assert conn.execute("SELECT body FROM notes").fetchone()[0] == "Newer revision"
            candidates = conn.execute("SELECT content FROM research_capture_candidates").fetchall()
            assert len(candidates) == 1
            assert "My retained candidate" in candidates[0][0]
    finally:
        editor.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("mode", ["delete", "stale", "missing", "wrong-paper", "failure"])
def test_reader_delete_uses_the_visible_note_and_reports_failure(notes, monkeypatch, mode):
    reader = QWidget()
    reader.paper = SimpleNamespace(id="paper-a")
    reader.win = SimpleNamespace(data=notes.data)
    reader.note_status = QLabel(reader)
    reader._visible_notes = {1: dict(notes.data.notes("paper-a")[0])}
    reader._open_notes = {1}
    refreshed = []
    reader._load_notes = lambda: refreshed.append(True)
    if mode == "stale":
        notes.data.update_note(1, "A newer note to review")
    elif mode == "missing":
        notes.data.delete_note(1)
    elif mode == "wrong-paper":
        reader.paper = SimpleNamespace(id="paper-b")
    elif mode == "failure":
        def fail(*args, **kwargs):
            raise OSError("Private storage detail")
        monkeypatch.setattr(notes.data, "delete_note", fail)
    try:
        main.ReaderPage._note_action(reader, QUrl("del:1"))
        main.ReaderPage._note_action(reader, QUrl("del:1"))
        with sqlite3.connect(notes.path) as conn:
            saved = conn.execute("SELECT body FROM notes").fetchall()
        if mode in ("delete", "missing"):
            assert saved == []
        elif mode == "stale":
            assert saved == [("A newer note to review",)]
        else:
            assert saved == [("Original",)]
        assert refreshed == ([True] if mode == "delete" else [])
        assert reader.note_status.text()
        assert "Private storage detail" not in reader.note_status.text()
    finally:
        reader.deleteLater()
        notes.app.processEvents()


def test_bound_delete_records_one_retained_tombstone(bound):
    seed()
    data = main.Data()
    snapshot = data.note_for_edit("local-paper", 1)
    before = len(bound.journal.pending())
    assert data.delete_note(1, expected=snapshot)
    operations = bound.journal.pending()
    assert len(operations) == before + 1
    assert operations[-1]["entity_type"] == "note" and operations[-1]["action"] == "delete"
    with pytest.raises(ValueError):
        data.delete_note(1, expected=snapshot)
    assert len(bound.journal.pending()) == before + 1
