"""Actual ReaderPage.load uses observed edits; standalone legacy helpers remain intact."""

import os
import sqlite3
from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_manual_highlight_ops import QUOTE, ai
from test_research_generation import rows
from test_research_generation import workspace as _workspace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from paper_daily import llm, manual_highlight_ops, pdf_highlights, store, sync_capture
from paper_daily import research_generation as generation
from paper_daily.desktop import main

workspace = _workspace


@pytest.fixture
def loaded(workspace, monkeypatch):
    database, client, document = workspace
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main, "PDF_DIR", document.path.parent)
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Unexpected account read"))
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Unexpected AI call"))
    widget = main.ReaderPage(SimpleNamespace(pal=main.palette(), remember=lambda *_: None))
    widget.auto_highlights.setChecked(False)
    for name in ("_render_facts", "_check_resources", "_load_dive", "_load_notes", "_load_chat",
                 "_show_cites_if_visible", "_refresh_highlight_materials"):
        monkeypatch.setattr(widget, name, lambda: None)
    monkeypatch.setattr(widget.analysis_bar, "show_paper", lambda *_: None)
    monkeypatch.setattr(widget.questions, "load", lambda *_: None)
    monkeypatch.setattr(widget.presentation_pane, "load", lambda *_, **__: None)
    paper = main.Paper(
        "paper", "Paper", "Fixture", 2026, None, None, [], None, None, False,
        None, None, None, "", None, "pending", None,
        _document_reader=document._owner, _document_status=document,
    )
    widget.resize(1200, 750)
    widget.show()
    widget.load(paper)
    app.processEvents()
    assert widget._highlight_owner.database == database.resolve()
    assert widget._highlight_view is not None, widget.highlight_status.text()
    yield SimpleNamespace(widget=widget, app=app, database=database, client=client,
                          document=document, paper=paper)
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def select(w):
    selection = w.widget.pdf.selection
    assert selection.focus(selection.find(0, QUOTE))
    return selection


def test_real_loaded_reader_adds_and_removes_without_legacy_write_helpers(loaded, monkeypatch):
    w = loaded
    monkeypatch.setattr(pdf_highlights, "add", lambda *_: pytest.fail("Legacy write used"))
    monkeypatch.setattr(pdf_highlights, "remove", lambda *_: pytest.fail("Legacy delete used"))
    selection = select(w)
    selection.highlight.emit()
    assert len(selection._marks) == 1 and not selection._selected
    assert rows(w.database, "SELECT quote FROM pdf_highlights") == [{"quote": QUOTE}]
    select(w).erase_highlight.emit()
    assert not selection._marks
    assert rows(w.database, "SELECT * FROM pdf_highlights") == []


def test_workspace_switch_preserves_selection_and_writes_neither_db(loaded, monkeypatch):
    w = loaded
    selection = select(w)
    target = w.database.with_name("another.sqlite")
    monkeypatch.setattr(store, "DB_PATH", target)
    w.widget._highlight_selection()
    assert selection.selected_text() == QUOTE
    assert not target.exists()
    assert rows(w.database, "SELECT * FROM pdf_highlights") == []
    assert "未保存" in w.widget.pdf_note.text()
    monkeypatch.setattr(store, "DB_PATH", w.database)
    w.widget._highlight_selection()
    assert len(selection._marks) == 1


@pytest.mark.parametrize("change", ["parent", "pdf"])
def test_loaded_reader_changed_parent_or_pdf_preserves_selection_and_refuses_write(loaded, change):
    w = loaded
    selection = select(w)
    if change == "parent":
        with closing(generation._connect(w.database)) as conn, sync_capture.suppress_capture(conn):
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM papers WHERE id='paper'")
            conn.commit()
    else:
        with w.document.path.open("ab") as stream:
            stream.write(b"\n% changed")
    w.widget._highlight_selection()
    assert selection.selected_text() == QUOTE
    assert rows(w.database, "SELECT * FROM pdf_highlights") == []
    assert "未保存" in w.widget.pdf_note.text()


def test_loaded_reader_failed_commit_preserves_selection_and_retry_works(loaded, monkeypatch):
    w = loaded
    selection = select(w)
    original = sync_capture.CaptureConnection.commit

    def fail(_conn):
        raise sqlite3.OperationalError("Fixture storage unavailable")

    monkeypatch.setattr(sync_capture.CaptureConnection, "commit", fail)
    w.widget._highlight_selection()
    assert selection.selected_text() == QUOTE
    assert rows(w.database, "SELECT * FROM pdf_highlights") == []
    assert "storage unavailable" in w.widget.pdf_note.text()
    monkeypatch.setattr(sync_capture.CaptureConnection, "commit", original)
    w.widget._highlight_selection()
    assert len(selection._marks) == 1


def test_real_ai_hide_updates_user_state_and_keeps_original_text(loaded):
    w = loaded
    ai(w.widget._highlight_view)
    w.widget._load_highlights(w.paper.pdf_path)
    selection = select(w)
    assert selection.selected_highlights()[0] < 0
    w.widget._erase_selection_highlights()
    assert not selection._marks
    result = rows(w.database, "SELECT hidden,quote FROM pdf_ai_highlights")[0]
    assert result == {"hidden": 1, "quote": QUOTE}


def test_empty_and_repeated_actions_do_not_create_duplicate_marks(loaded):
    w = loaded
    w.widget._highlight_selection()
    w.widget._erase_selection_highlights()
    assert rows(w.database, "SELECT * FROM pdf_highlights") == []
    select(w)
    for _ in range(20):
        w.widget._highlight_selection()
    assert len(rows(w.database, "SELECT * FROM pdf_highlights")) == 1
    select(w)
    for _ in range(20):
        w.widget._erase_selection_highlights()
    assert rows(w.database, "SELECT * FROM pdf_highlights") == []


def test_navigation_after_saved_action_never_clears_new_selection(loaded, monkeypatch):
    w = loaded
    with store.connect() as conn:
        store.upsert_papers(conn, [dict(id="other", title="Other", year=2026, venue="Fixture",
                                       source="fixture")])
    other_path = w.document.path.with_name("other.pdf")
    other_path.write_bytes(w.document.path.read_bytes())
    other = replace(w.paper, id="other", title="Other",
                    _document_status=w.document._owner.inspect("other"))
    original = manual_highlight_ops.add

    def navigate(view, anchor, quote):
        original(view, anchor, quote)
        w.widget.load(other)
        select(w)

    monkeypatch.setattr(manual_highlight_ops, "add", navigate)
    select(w)
    w.widget._highlight_selection()
    assert w.widget.paper.id == "other"
    assert w.widget.pdf.selection.selected_text() == QUOTE
    assert rows(w.database, "SELECT paper_id FROM pdf_highlights") == [{"paper_id": "paper"}]


def test_close_after_transaction_cannot_abandon_saved_mark(loaded, monkeypatch):
    w = loaded
    original = manual_highlight_ops.add

    def close(view, anchor, quote):
        original(view, anchor, quote)
        w.widget.close()

    monkeypatch.setattr(manual_highlight_ops, "add", close)
    select(w)
    w.widget._highlight_selection()
    assert not w.widget.isVisible()
    assert rows(w.database, "SELECT quote FROM pdf_highlights") == [{"quote": QUOTE}]


@pytest.mark.parametrize("kind", ["rotated", "hyphen_blank_page"])
def test_actual_selection_word_stream_matches_verified_manual_operation(loaded, kind):
    import pymupdf

    w = loaded
    target = w.document.path.with_name("parity.pdf")
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        if kind == "rotated":
            page.insert_text((40, 50), "Original experiment")
            page.insert_text((300, 150), "ROTATED STAMP", rotate=90)
            page.insert_text((40, 75), "Final evidence")
        else:
            page.insert_text((40, 50), "Original multi-")
            page.insert_text((40, 75), "device experiment")
            pdf.new_page()  # A valid cross-page selection can cross an empty page.
            pdf.new_page().insert_text((40, 50), "Final result")
        pdf.save(target)
    with store.connect() as conn:
        store.upsert_papers(conn, [dict(id="parity", title="Parity", year=2026, venue="Fixture",
                                       source="fixture")])
    paper = replace(w.paper, id="parity", title="Parity",
                    _document_status=w.document._owner.inspect("parity"))
    w.widget.load(paper)
    w.app.processEvents()
    selection = w.widget.pdf.selection
    last_page = 0 if kind == "rotated" else 2
    final_word = selection.words_on(last_page)[-1]
    anchor = dict(p0=0, o0=0, p1=last_page, o1=final_word.order)
    assert selection.focus(anchor)
    quote = selection.selected_text()
    assert "ROTATED" not in quote
    if kind == "hyphen_blank_page":
        assert "multidevice" in quote
    w.widget._highlight_selection()
    assert rows(w.database, "SELECT quote FROM pdf_highlights") == [{"quote": quote}]
    assert len(selection._marks) == 1


def test_pdf_parser_failure_preserves_selection_and_retry_is_possible(loaded, monkeypatch):
    import pymupdf

    w = loaded
    selection = select(w)
    original = pymupdf.open

    def fail(*_args, **_kwargs):
        raise RuntimeError("Fixture parser failure")

    monkeypatch.setattr(pymupdf, "open", fail)
    w.widget._highlight_selection()
    assert selection.selected_text() == QUOTE
    assert rows(w.database, "SELECT * FROM pdf_highlights") == []
    assert "PDF verification failed" in w.widget.pdf_note.text()
    monkeypatch.setattr(pymupdf, "open", original)
    w.widget._highlight_selection()
    assert len(selection._marks) == 1
