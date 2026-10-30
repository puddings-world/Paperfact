"""Actual managed reader edits retain the displayed document revision's provenance."""

from contextlib import closing

import pytest
from test_managed_reader_ui import wait_for
from test_managed_reader_ui import workspace as _workspace
from test_research_generation import rows

from paper_daily import store, sync_capture

workspace = _workspace


@pytest.fixture
def loaded(workspace, monkeypatch):
    w = workspace
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id=w.side.journal.workspace_id,
                             device_id=w.side.journal.device_id)
    widget = w.widget
    widget.auto_highlights.setChecked(False)
    for name in ("_render_facts", "_check_resources", "_load_dive", "_load_notes", "_load_chat",
                 "_show_cites_if_visible", "_refresh_highlight_materials"):
        monkeypatch.setattr(widget, name, lambda: None)
    monkeypatch.setattr(widget.analysis_bar, "show_paper", lambda *_: None)
    monkeypatch.setattr(widget.questions, "load", lambda *_: None)
    monkeypatch.setattr(widget.presentation_pane, "load", lambda *_, **__: None)
    widget.load(widget.paper)
    wait_for(w.app, lambda: not widget.document_runner.busy)
    assert widget._highlight_view is not None, widget.highlight_status.text()
    return w


def test_retained_managed_pdf_remains_original_source_after_new_desired_version(loaded):
    w = loaded
    selection = w.widget.pdf.selection
    assert selection.focus(selection.find(0, "Alpha original"))
    w.widget._highlight_selection()
    second = w.attach("Beta replacement evidence", "replacement")
    w.widget._check_document_update()
    assert w.widget._pdf_fingerprint == w.first.sha256
    assert selection.focus(selection.find(0, "Alpha"))
    w.widget._highlight_selection()
    old = rows(w.side.journal.path, "SELECT document_hash FROM pdf_highlights")
    assert old == [{"document_hash": w.first.sha256}] * 2
    w.widget._use_latest_document()
    wait_for(w.app, lambda: not w.widget.document_runner.busy)
    assert w.widget._pdf_fingerprint == second.sha256
    assert selection.focus(selection.find(0, "Beta"))
    w.widget._highlight_selection()
    operations = [op for op in w.side.journal.pending()
                  if op.get("payload", {}).get("feature") == "manual_highlight"]
    assert [op["payload"]["source_document_hash"] for op in operations] == [
        w.first.sha256, w.first.sha256, second.sha256
    ]
    assert len(selection._marks) == 1


def test_corrupted_managed_bytes_cannot_persist_selected_coordinates(loaded):
    w = loaded
    selection = w.widget.pdf.selection
    assert selection.focus(selection.find(0, "Alpha original"))
    with w.widget.paper.pdf_path.open("ab") as stream:
        stream.write(b"\n% changed")
    w.widget._highlight_selection()
    assert rows(w.side.journal.path, "SELECT * FROM pdf_highlights") == []
    assert selection.selected_text() == "Alpha original"
    assert "未保存" in w.widget.pdf_note.text()


def test_reload_with_missing_parent_is_not_a_legacy_write_fallback(loaded):
    w = loaded
    original = w.widget.paper
    # A stale caller may try to reopen a paper object after the research row vanished.
    from paper_daily import research_generation as generation

    with closing(generation._connect(w.side.journal.path)) as conn, conn, (
            sync_capture.suppress_capture(conn)):
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM papers WHERE id=?", (original.id,))
    w.widget.load(original)
    assert w.widget._highlight_owner is None
    w.widget._highlight_selection()
    assert rows(w.side.journal.path, "SELECT * FROM pdf_highlights") == []
