"""Desktop context transitions never reuse another document's coordinates."""

import sqlite3
from dataclasses import replace

import pytest
from test_managed_reader_ui import open_pdf, wait_for
from test_managed_reader_ui import workspace as workspace_fixture
from test_sync_document_research import pdf_bytes
from test_sync_operations import paper

from paper_daily.desktop.document_flow import anchor_allowed, loaded_document_valid
from paper_daily.document_reader import from_workspace, register_document_paths
from paper_daily.sync_document_actions import stage_file
from paper_daily.sync_documents import bind_verified_document, desired_document, verify_document

workspace = workspace_fixture


def test_changed_registration_clears_native_view_but_preserves_draft_and_can_reopen(workspace):
    w = workspace
    open_pdf(w)
    old = w.widget.paper._document_reader
    w.widget.note_edit.setPlainText("Retain my interpretation")
    with w.side.journal.transaction() as conn:
        register_document_paths(
            conn,
            workspace_id=w.side.journal.workspace_id,
            blob_root=w.blobs.root,
            projection_root=w.root / "new-reader",
            legacy_root=w.root / "new-legacy",
        )
    w.widget._check_document_update()
    assert w.widget.paper._document_reader is not old
    assert w.widget.pdf.page_count() == 0 and w.widget._pdf_fingerprint is None
    assert not w.widget.open_external.isEnabled()
    assert w.widget.note_edit.toPlainText() == "Retain my interpretation"
    w.widget._use_latest_document()
    wait_for(w.app, lambda: not w.widget.document_runner.busy)
    assert w.widget._pdf_fingerprint == w.first.sha256
    assert w.widget.paper.pdf_path.parent == w.root / "new-reader"


def test_new_managed_history_is_detected_without_reloading_the_legacy_reader(workspace):
    w = workspace
    created = w.actions.create_list("Legacy", [{"paper": paper("Legacy")}], request_id="legacy")
    identity = created["papers"][0]["paper_id"]
    w.widget.paper = w.data.queue(list_id=created["list_id"])[0]
    alias = w.widget.paper.pdf_path
    alias.parent.mkdir(exist_ok=True)
    legacy_bytes = pdf_bytes("Unenrolled legacy bytes")
    alias.write_bytes(legacy_bytes)
    assert w.widget.pdf.load(alias)
    w.widget._pdf_fingerprint = "old-unverified-fingerprint"
    w.widget.note_edit.setPlainText("Legacy draft")
    assert loaded_document_valid(w.widget)
    selected = w.root / "new-document.pdf"
    selected.write_bytes(pdf_bytes("Managed bytes"))
    manifest = stage_file(w.blobs, selected)
    w.actions.attach_document(identity, manifest, store=w.blobs, request_id="new-document")
    with w.side.journal.transaction() as conn:
        wanted = desired_document(conn, identity)
        assert bind_verified_document(conn, wanted, verify_document(w.blobs, wanted))
    assert not loaded_document_valid(w.widget)
    w.widget._check_document_update()
    assert w.widget.paper._document_status.managed
    assert w.widget.pdf.page_count() == 0 and w.widget._pdf_fingerprint is None
    assert not w.widget.auto_highlights.isEnabled()
    assert not w.widget.document_runner.busy
    assert w.widget.note_edit.toPlainText() == "Legacy draft"
    assert alias.read_bytes() == legacy_bytes


def test_ambiguous_legacy_filename_is_handled_without_loading_or_starting_work(workspace):
    w = workspace
    with sqlite3.connect(w.side.journal.path) as conn:
        for identity in ("a:b", "a_b"):
            conn.execute(
                "INSERT INTO papers(id,venue,year,title,title_key,source) "
                "VALUES(?,'',2026,'A','a','fixture')",
                (identity,),
            )
    w.widget.paper = replace(w.widget.paper, id="a:b", _loaded_document=None, _has_pdf=None)
    alias = w.root / "pdf" / "a_b.pdf"
    alias.parent.mkdir(exist_ok=True)
    alias.write_bytes(pdf_bytes("Ambiguous file"))
    w.widget._load_pdf()
    assert w.widget.paper._document_status.status == "ambiguous"
    assert w.widget.pdf.page_count() == 0 and not w.widget.document_runner.busy
    assert not w.widget.open_external.isEnabled() and not w.widget.auto_highlights.isEnabled()
    assert not loaded_document_valid(w.widget)


def test_same_local_id_in_another_explicit_database_cannot_preserve_open_native_pdf(workspace):
    w = workspace
    open_pdf(w)
    copied = w.root / "another-workspace.db"
    with sqlite3.connect(w.side.journal.path) as source, sqlite3.connect(copied) as receiver:
        source.backup(receiver)
    w.widget.paper._document_reader = from_workspace(copied)
    w.widget.note_edit.setPlainText("Do not erase")
    w.widget._check_document_update()
    assert w.widget.pdf.page_count() == 0 and w.widget._active_document is None
    assert w.widget.note_edit.toPlainText() == "Do not erase"
    assert not loaded_document_valid(w.widget)


@pytest.mark.parametrize("damage", ["modified", "removed"])
def test_invalid_open_file_is_cleared_without_changing_draft(workspace, damage):
    w = workspace
    open_pdf(w)
    path = w.widget.paper.pdf_path
    w.widget.note_edit.setPlainText("Draft survives invalidation")
    if damage == "modified":
        path.write_bytes(pdf_bytes("Unexpected edit"))
    else:
        # Windows protects a native open handle; model removal after it is released.
        w.widget.pdf.unload()

        def removed():
            try:
                path.unlink()
                return True
            except PermissionError:
                return False

        wait_for(w.app, removed)
    assert not loaded_document_valid(w.widget)
    w.widget._check_document_update()
    assert w.widget.pdf.page_count() == 0
    assert w.widget.paper._loaded_document is None and w.widget._pdf_fingerprint is None
    assert not w.widget.open_external.isEnabled()
    assert w.widget.note_edit.toPlainText() == "Draft survives invalidation"


def test_retained_old_document_allows_only_consistent_provenance(workspace):
    w = workspace
    open_pdf(w)
    newer = w.attach("New desired document", "newer")
    w.widget._check_document_update()
    assert loaded_document_valid(w.widget)
    assert anchor_allowed(w.widget, {"document_hash": w.first.sha256})
    assert anchor_allowed(w.widget, {"anchor": {"document_hash": w.first.sha256}})
    assert not anchor_allowed(
        w.widget,
        {
            "document_hash": w.first.sha256,
            "anchor": {"document_hash": newer.sha256},
        },
    )
    assert not anchor_allowed(
        w.widget,
        {
            "document_hash": newer.sha256,
            "anchor": {"document_hash": w.first.sha256},
        },
    )
    w.widget._pdf_fingerprint = newer.sha256
    assert not loaded_document_valid(w.widget)


def test_new_target_during_native_load_cannot_publish_stale_fingerprint(workspace, monkeypatch):
    w = workspace
    original = w.widget.pdf.load

    def changed(path):
        loaded = original(path)
        w.attach("New target during open", "native-switch")
        return loaded

    monkeypatch.setattr(w.widget.pdf, "load", changed)
    w.widget._load_pdf()
    wait_for(w.app, lambda: not w.widget.document_runner.busy)
    assert w.widget.pdf.page_count() == 0 and w.widget._pdf_fingerprint is None
    assert w.widget.paper._loaded_document is None


def test_switch_to_unenrolled_workspace_rejects_old_managed_content(workspace):
    from paper_daily.store import SCHEMA

    w = workspace
    tooltip = w.widget.auto_highlights.toolTip()
    checked = w.widget.auto_highlights.isChecked()
    open_pdf(w)
    assert w.widget.auto_highlights.toolTip() != tooltip
    assert w.widget.auto_highlights.isChecked() == checked
    fresh = w.root / "unenrolled.db"
    with sqlite3.connect(fresh) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,venue,year,title,title_key,source) "
            "VALUES(?,'',2026,'Different workspace','different','fixture')",
            (w.widget.paper.id,),
        )
    w.widget.paper._document_reader = from_workspace(fresh, legacy_root=w.root / "other-pdf")
    assert not loaded_document_valid(w.widget)
    w.widget._check_document_update()
    assert not w.widget.paper._document_status.managed
    assert w.widget.auto_highlights.toolTip() == tooltip
    assert w.widget.auto_highlights.isChecked() == checked
    assert w.widget.pdf.page_count() == 0 and w.widget._active_document is None
    assert not w.widget.open_external.isEnabled()
