"""Real reader notices retain the PDF and drafts until explicit saved-text reload."""

import sqlite3
import threading
from contextlib import closing
from types import MethodType, SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from test_reader_chat import reader as reader
from test_reader_preparation import settle
from test_research_chat import legacy as legacy
from test_research_generation import pdf

from paper_daily import llm, manual_highlight_ops, store
from paper_daily.desktop import main, reader_preparation
from paper_daily.document_reader import from_workspace

STAMP = "2026-10-26T00:00:00+00:00"


@pytest.fixture
def ready(reader, tmp_path, monkeypatch):
    app, window, view = reader
    owner = manual_highlight_ops.capture_owner(store.DB_PATH, "local-paper")
    view._highlight_owner = owner
    view.paper = SimpleNamespace(id="local-paper", abstract="", title="Fixture")
    view.saved_text_notice.bind(owner)
    monkeypatch.setattr(view, "_load_chat", MethodType(main.ReaderPage._load_chat, view))
    monkeypatch.setattr(view, "_prepare_reading_highlights", lambda: None)
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No notification AI"))
    root = tmp_path / "pdfs"
    root.mkdir()
    pdf(root / "local-paper.pdf")
    document = from_workspace(store.DB_PATH, legacy_root=root).resolve("local-paper")
    view._active_document = document
    assert document.available and view.pdf.load(document.path)
    view._load_notes()
    view._load_dive()
    view._load_chat()
    settle(app, lambda: not view.preparation.busy and view._chat_snapshot is not None)
    window.workspace_changes.timer.stop()
    window.workspace_changes.poll()
    assert not view.saved_text_notice.isVisible()
    view.note_edit.setPlainText("Unsent note draft")
    view.ask_box.setText("Unsent question draft")
    window.stack.setCurrentWidget(view)
    window.show()
    app.processEvents()
    yield app, window, view, document
    view.saved_text_notice.reset()
    view.preparation.dispose()
    settle(app, lambda: not view.preparation.busy)


def incoming():
    with closing(sqlite3.connect(store.DB_PATH)) as conn, conn:
        conn.execute(
            "INSERT INTO dives VALUES(?,?,?,?)", ("local-paper", "Remote explanation", STAMP, None)
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) VALUES(?,?,?,?)",
            ("local-paper", "Remote note", "note", STAMP),
        )
        conn.execute(
            "INSERT INTO chat(paper_id,role,body,created_at) VALUES(?,?,?,?)",
            ("local-paper", "assistant", "Remote answer", STAMP),
        )


def unchanged(view, document, native, page):
    assert view.note_edit.toPlainText() == "Unsent note draft"
    assert view.ask_box.text() == "Unsent question draft"
    assert view._active_document is document
    assert view.pdf.position_identity() == native and view.pdf.current_page() == page


def test_notice_preserves_pdf_focus_and_drafts_then_explicitly_loads_saved_text(ready):
    app, window, view, document = ready
    native, page = view.pdf.position_identity(), view.pdf.current_page()
    before = view.dive_view._body, view.chat_view._body, view.note_log._body
    view.ask_box.setFocus()
    app.processEvents()
    focus = QApplication.focusWidget()
    incoming()
    window.workspace_changes.poll()
    assert view.saved_text_notice.isVisible()
    assert view.saved_text_notice.reload.isEnabled()
    assert (view.dive_view._body, view.chat_view._body, view.note_log._body) == before
    assert QApplication.focusWidget() is focus
    unchanged(view, document, native, page)
    assert view.saved_text_notice.load_updates()
    settle(app, lambda: not view.preparation.busy)
    window.workspace_changes.poll()
    assert not view.saved_text_notice.isVisible()
    assert "Remote explanation" in view.dive_view._body
    assert "Remote answer" in view.chat_view._body
    assert "Remote note" in view.note_log._body
    unchanged(view, document, native, page)


def test_repeated_reload_while_preparing_does_not_duplicate_jobs_or_clear_drafts(
    ready, monkeypatch
):
    app, window, view, document = ready
    incoming()
    window.workspace_changes.poll()
    original = reader_preparation._prepare
    started, release = threading.Event(), threading.Event()
    calls = []

    def held(request, cancelled):
        calls.append(request)
        started.set()
        assert release.wait(5)
        return original(request, cancelled)

    monkeypatch.setattr(reader_preparation, "_prepare", held)
    try:
        assert view.saved_text_notice.load_updates()
        assert started.wait(2)
        for _ in range(25):
            assert view.saved_text_notice.load_updates() is False
        assert len(calls) == 1
        assert view.note_edit.toPlainText() == "Unsent note draft"
    finally:
        release.set()
        settle(app, lambda: not view.preparation.busy)
    assert view._active_document is document


def test_failed_read_keeps_notice_and_retry_uses_same_saved_content(ready, monkeypatch):
    app, window, view, _document = ready
    incoming()
    window.workspace_changes.poll()
    original = view._load_notes
    with monkeypatch.context() as patch:

        def fail():
            raise sqlite3.OperationalError("private failure detail")

        patch.setattr(view, "_load_notes", fail)
        assert view.saved_text_notice.load_updates() is False
        assert "private failure" not in view.saved_text_notice.label.text()
        assert view.saved_text_notice.isVisible()
        assert view.note_edit.toPlainText() == "Unsent note draft"
    assert view._load_notes == original
    assert view.saved_text_notice.load_updates()
    settle(app, lambda: not view.preparation.busy)
    window.workspace_changes.poll()
    assert not view.saved_text_notice.isVisible()


def test_dismissed_snapshot_stays_quiet_but_new_saved_content_reappears(ready):
    _app, window, view, _document = ready
    incoming()
    window.workspace_changes.poll()
    view.saved_text_notice.later.click()
    window.workspace_changes.poll()
    assert not view.saved_text_notice.isVisible()
    with closing(sqlite3.connect(store.DB_PATH)) as conn, conn:
        conn.execute("UPDATE notes SET body='A newer remote note'")
    window.workspace_changes.poll()
    assert view.saved_text_notice.isVisible()
    assert "notes" in view.saved_text_notice._pending()


def test_queued_previous_view_result_is_ignored_after_reader_rebind(ready):
    _app, window, view, _document = ready
    incoming()
    queued = window.workspace_changes._revision()
    owner = view._highlight_owner
    view._qa_epoch += 1
    view.saved_text_notice.bind(owner)
    window.workspace_changes._apply(queued)
    assert not view.saved_text_notice.isVisible()
    assert view.saved_text_notice.load_updates() is False


def test_chinese_notice_labels_are_actual_text_not_terminal_replacements():
    from paper_daily.desktop.saved_text_notice import TEXT

    assert TEXT["zh-TW"]["load"] == "\u8f09\u5165\u5df2\u5b58\u66f4\u65b0"
    assert TEXT["zh-TW"]["later"] == "\u7a0d\u5f8c"
    assert TEXT["zh-TW"]["updated"].startswith("\u5df2\u5b58")
    assert all("?" not in value for value in TEXT["zh-TW"].values())
