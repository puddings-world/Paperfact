"""Actual PDF panes and isolated workspaces exercise managed reader activation."""

import json
import sqlite3
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_sync_document_research import pdf_bytes
from test_sync_operations import client, paper

from paper_daily import store
from paper_daily.desktop import main, pdfpane
from paper_daily.desktop.document_flow import DocumentRunner, anchor_allowed, message
from paper_daily.document_reader import from_workspace
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_document_actions import stage_file
from paper_daily.sync_documents import bind_verified_document, desired_document, verify_document
from paper_daily.sync_operations import ResearchOperations
from paper_daily.sync_service import ReferenceService
from paper_daily.sync_transfers import DocumentTransfers


def wait_for(app, predicate):
    for _ in range(600):
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    pytest.fail("Reader worker did not reach the expected observable state")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "papers.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(main, "PDF_DIR", tmp_path / "pdf")
    side = client(path, "a")
    blobs = BlobStore(tmp_path / "blobs")
    server = ReferenceService(tmp_path / "server.db")
    DocumentTransfers(side, blobs, server, origin="http://127.0.0.1:1")
    actions = ResearchOperations(side)
    created = actions.create_list("Managed", [{"paper": paper()}], request_id="intake")
    identity = created["papers"][0]["paper_id"]

    def attach(text, key, *, bind=True):
        selected = tmp_path / f"{key}.pdf"
        selected.write_bytes(pdf_bytes(text))
        manifest = stage_file(blobs, selected)
        actions.attach_document(identity, manifest, store=blobs, request_id=key)
        if bind:
            with side.journal.transaction() as conn:
                target = desired_document(conn, identity)
                assert bind_verified_document(conn, target, verify_document(blobs, target))
        return manifest

    first = attach("Alpha original evidence", "first")
    data = main.Data()
    shown = data.queue(list_id=created["list_id"])[0]
    widget = main.ReaderPage(
        SimpleNamespace(pal=main.palette(), remember=lambda *_: None, data=data)
    )
    widget.paper = shown
    widget.resize(1300, 850)
    widget.show()
    yield SimpleNamespace(
        app=app,
        widget=widget,
        side=side,
        blobs=blobs,
        server=server,
        actions=actions,
        identity=identity,
        first=first,
        attach=attach,
        data=data,
        list_id=created["list_id"],
        root=tmp_path,
    )
    wait_for(app, lambda: not widget.document_runner.busy)
    widget.pdf.unload()
    widget.close()
    widget.deleteLater()
    app.processEvents()


def open_pdf(w):
    w.widget._load_pdf()
    wait_for(w.app, lambda: not w.widget.document_runner.busy)
    assert w.widget.pdf.page_count() == 1
    assert w.widget._pdf_fingerprint == w.first.sha256


def test_managed_document_opens_verified_projection_without_ai_or_legacy_download(
    workspace, monkeypatch
):
    w = workspace
    monkeypatch.setattr(
        w.widget.fetcher, "start", Mock(side_effect=AssertionError("No legacy download"))
    )
    monkeypatch.setattr(
        w.widget.presentation_pane,
        "_analyze_highlights",
        Mock(side_effect=AssertionError("No automatic AI")),
    )
    open_pdf(w)
    w.widget._prepare_reading_highlights()
    assert w.widget.paper.pdf_path.name == w.first.sha256 + ".pdf"
    assert "Alpha original evidence" in w.widget.pdf.page_text(0)
    assert w.widget.paper.has_pdf and w.widget.open_external.isEnabled()
    assert not w.widget.auto_highlights.isEnabled()
    assert not w.widget.presentation_pane._analyze_highlights.called
    assert not w.widget.fetcher.start.called


def test_new_version_is_announced_without_changing_open_pdf_draft_selection_or_focus(workspace):
    w = workspace
    open_pdf(w)
    selection = w.widget.pdf.selection
    assert selection.focus(selection.find(0, "Alpha original"))
    old_anchor = selection.anchor()
    w.widget.note_edit.setPlainText("Keep this unsaved interpretation")
    w.widget.note_edit.setFocus()
    w.app.processEvents()
    focus = w.app.focusWidget()
    newer = w.attach("Beta replacement evidence", "second")
    w.widget._check_document_update()
    assert w.widget.document_refresh.isVisible()
    assert "Alpha original evidence" in w.widget.pdf.page_text(0)
    assert selection.anchor() == old_anchor
    assert w.widget.note_edit.toPlainText() == "Keep this unsaved interpretation"
    assert w.app.focusWidget() is focus
    assert not w.widget.document_runner.busy
    w.widget.document_refresh.click()
    wait_for(w.app, lambda: not w.widget.document_runner.busy)
    assert w.widget._pdf_fingerprint == newer.sha256
    assert "Beta replacement evidence" in w.widget.pdf.page_text(0)
    assert not selection.anchor()
    assert w.widget.note_edit.toPlainText() == "Keep this unsaved interpretation"


def test_hidden_retained_reader_does_not_discard_open_version(workspace):
    w = workspace
    open_pdf(w)
    w.widget.hide()
    w.attach("Beta replacement evidence", "second")
    w.widget._load_pdf()
    assert not w.widget.document_runner.busy
    assert w.widget._pdf_fingerprint == w.first.sha256
    assert "Alpha original evidence" in w.widget.pdf.page_text(0)


def test_failed_new_activation_preserves_native_pdf_and_draft_then_retry_works(
    workspace, monkeypatch
):
    w = workspace
    open_pdf(w)
    w.widget.note_edit.setPlainText("Unfinished note")
    newer = w.attach("Beta replacement evidence", "second")
    original = w.widget.pdf.load
    monkeypatch.setattr(w.widget.pdf, "load", lambda _path: False)
    w.widget._use_latest_document()
    wait_for(w.app, lambda: not w.widget.document_runner.busy)
    assert w.widget.pdf.isVisible() and w.widget.open_external.isEnabled()
    assert w.widget._pdf_fingerprint == w.first.sha256
    assert "Alpha original evidence" in w.widget.pdf.page_text(0)
    assert w.widget.note_edit.toPlainText() == "Unfinished note"
    monkeypatch.setattr(w.widget.pdf, "load", original)
    w.widget._use_latest_document()
    wait_for(w.app, lambda: not w.widget.document_runner.busy)
    assert w.widget._pdf_fingerprint == newer.sha256


def test_note_anchors_tag_version_and_mismatched_or_unknown_sources_cannot_navigate(
    workspace, monkeypatch
):
    w = workspace
    open_pdf(w)
    selection = w.widget.pdf.selection
    assert selection.focus(selection.find(0, "Alpha original"))
    page, encoded = w.widget._where()
    assert page == 1 and json.loads(encoded)["document_hash"] == w.first.sha256
    w.data.add_note(w.widget.paper.id, "Old source", "note", page, encoded)
    note_id = w.data.notes(w.widget.paper.id)[0]["id"]
    w.attach("Beta replacement evidence", "second")
    w.widget._use_latest_document()
    wait_for(w.app, lambda: not w.widget.document_runner.busy)
    focus = Mock(wraps=selection.focus)
    find = Mock(wraps=selection.find)
    monkeypatch.setattr(selection, "focus", focus)
    monkeypatch.setattr(selection, "find", find)
    w.widget._jump_to(note_id)
    for source in (
        {"kind": "original", "page": 1, "text": "Alpha original"},
        {"kind": "sentence", "anchor": json.loads(encoded)},
        {"kind": "figure", "page": 1, "document_hash": w.first.sha256},
    ):
        w.widget._jump_to_source(source)
    assert not focus.called and not find.called
    assert "PDF 版本" in w.widget.note_status.text()
    w.widget._jump_to_source(
        {
            "kind": "sentence",
            "page": 1,
            "text": "Beta replacement",
            "document_hash": w.widget._pdf_fingerprint,
        }
    )
    assert focus.called and find.called


def test_old_version_navigation_remains_valid_until_its_projection_changes(workspace):
    w = workspace
    open_pdf(w)
    w.attach("Beta replacement evidence", "second")
    source = {"document_hash": w.first.sha256}
    assert anchor_allowed(w.widget, source)
    w.widget.paper.pdf_path.write_bytes(pdf_bytes("Unexpected external edit"))
    assert not anchor_allowed(w.widget, source)


@pytest.mark.parametrize("mode", ["missing", "detached", "unbound"])
def test_managed_unavailable_never_opens_legacy_alias_or_downloads(workspace, monkeypatch, mode):
    w = workspace
    if mode == "missing":
        w.blobs.verified_path(w.first).unlink()
    elif mode == "detached":
        w.side.save(w.side.new_graph_operation("paper_document", w.identity, {}, action="delete"))
    else:
        w.attach("Not bound yet", "second", bind=False)
    legacy = main.PDF_DIR / (w.widget.paper.id.replace(":", "_") + ".pdf")
    legacy.parent.mkdir(exist_ok=True)
    legacy.write_bytes(pdf_bytes("Wrong legacy document"))
    blocked = Mock(side_effect=AssertionError("No legacy fetch allowed"))
    monkeypatch.setattr(w.widget.fetcher, "start", blocked)
    w.widget._load_pdf()
    wait_for(w.app, lambda: not w.widget.document_runner.busy)
    assert w.widget.pdf.page_count() == 0
    assert w.widget.pdf_missing.isVisible() and not w.widget.open_external.isEnabled()
    assert not blocked.called and not w.widget.paper.has_pdf
    assert legacy.read_bytes().startswith(b"%PDF-")


def test_repeated_activation_and_close_while_verifying_do_not_duplicate_or_destroy_job(
    workspace, monkeypatch
):
    w = workspace
    resolver = w.widget.paper._document_reader
    original = resolver.resolve
    reached, release, calls = Event(), Event(), []

    def delayed(identity):
        calls.append(identity)
        reached.set()
        assert release.wait(8)
        return original(identity)

    monkeypatch.setattr(resolver, "resolve", delayed)
    w.widget._load_pdf()
    assert reached.wait(8)
    try:
        w.widget._load_pdf()
        event = Mock()
        window = SimpleNamespace(reader_page=w.widget, findChildren=lambda _: [], activity_hub=None)
        main.MainWindow.closeEvent(window, event)
        event.ignore.assert_called_once()
    finally:
        release.set()
    wait_for(w.app, lambda: not w.widget.document_runner.busy)
    assert len(calls) == 1 and w.widget._pdf_fingerprint == w.first.sha256


def test_stale_completion_cannot_activate_after_document_target_changes(workspace, monkeypatch):
    w = workspace
    resolver = w.widget.paper._document_reader
    original = resolver.resolve
    reached, release = Event(), Event()

    def delayed(identity):
        result = original(identity)
        reached.set()
        assert release.wait(8)
        return result

    monkeypatch.setattr(resolver, "resolve", delayed)
    w.widget._load_pdf()
    assert reached.wait(8)
    try:
        w.attach("Beta replacement evidence", "second")
    finally:
        release.set()
    wait_for(w.app, lambda: not w.widget.document_runner.busy)
    assert w.widget._pdf_fingerprint is None and w.widget.pdf.page_count() == 0
    assert w.widget.document_refresh.isVisible()


def test_runner_invalidation_makes_late_callback_inert(workspace):
    w = workspace
    entered, released, calls = Event(), Event(), []

    def delayed(_identity):
        entered.set()
        assert released.wait(8)
        return SimpleNamespace(available=True)

    runner = DocumentRunner()
    assert runner.start(
        SimpleNamespace(resolve=delayed), "fixture", lambda *args: calls.append(args)
    )
    assert entered.wait(8)
    runner.invalidate()
    released.set()
    wait_for(w.app, lambda: not runner.busy)
    assert calls == []


@pytest.mark.parametrize("backend", ["qt", "pixmap"])
def test_native_pane_rejects_bad_replacement_without_losing_previous_document(workspace, backend):
    w = workspace
    cls = pdfpane._QtPdfPane if backend == "qt" else pdfpane._PixmapPdfPane
    pane = cls()
    good = w.root / "native.pdf"
    bad = w.root / "invalid.pdf"
    good.write_bytes(pdf_bytes("Native original"))
    bad.write_bytes(b"not a PDF")
    assert pane.load(good)
    assert not pane.load(bad)
    assert pane.page_count() == 1 and "Native original" in pane.page_text(0)
    pane.unload()
    assert pane.page_count() == 0 and pane.page_text(0) == ""
    pane.deleteLater()


def test_configured_paths_survive_coordinator_restart(workspace):
    w = workspace
    custom = w.root / "custom-reader"
    legacy = w.root / "custom-legacy"
    DocumentTransfers(
        w.side,
        w.blobs,
        w.server,
        origin="http://127.0.0.1:1",
        reader_root=custom,
        legacy_root=legacy,
    )
    with sqlite3.connect(w.side.journal.path) as conn:
        before = conn.execute("SELECT * FROM document_reader_paths").fetchone()
    DocumentTransfers(w.side, w.blobs, w.server, origin="http://127.0.0.1:1")
    with sqlite3.connect(w.side.journal.path) as conn:
        assert conn.execute("SELECT * FROM document_reader_paths").fetchone() == before
    assert from_workspace(w.side.journal.path).projection_root == custom
    listed = w.data.queue(list_id=w.list_id)[0]
    assert listed._document_reader.projection_root == custom
    assert listed._document_reader.legacy_root == legacy


def test_new_reader_status_copy_has_both_languages():
    for key in ("checking", "anchor", "older", "missing", "refresh", "manual_ai"):
        assert message(key, "en") != message(key, "zh-TW")


def test_invalid_projection_cannot_save_coordinates_edit_highlights_or_open_external(
    workspace, monkeypatch
):
    w = workspace
    open_pdf(w)
    assert w.widget.pdf.selection.focus(w.widget.pdf.selection.find(0, "Alpha original"))
    w.widget.paper.pdf_path.write_bytes(pdf_bytes("Changed behind the reader"))
    add = Mock(side_effect=AssertionError("Invalid coordinates must not be written"))
    remove = Mock(side_effect=AssertionError("Invalid coordinates must not delete highlights"))
    external = Mock()
    monkeypatch.setattr(main.pdf_highlights, "add", add)
    monkeypatch.setattr(main.pdf_highlights, "remove", remove)
    monkeypatch.setattr(main.QDesktopServices, "openUrl", external)
    assert w.widget._where() == (None, None)
    w.widget._highlight_selection()
    w.widget._erase_selection_highlights()
    w.widget._open_external()
    assert not add.called and not remove.called and not external.called


def test_workspace_refresh_notifies_new_pdf_without_reloading_reader(workspace):
    w = workspace
    open_pdf(w)
    w.widget.note_edit.setPlainText("Preserved draft")
    w.attach("Beta replacement evidence", "second")
    window = SimpleNamespace(
        reader_page=w.widget,
        refresh_lists=Mock(),
        lists_page=SimpleNamespace(refresh=Mock()),
        stack=SimpleNamespace(currentWidget=lambda: None),
        queue_page=object(),
    )
    main.MainWindow._refresh_external_list_views(window)
    assert w.widget.document_refresh.isVisible()
    assert w.widget.note_edit.toPlainText() == "Preserved draft"
    assert w.widget._pdf_fingerprint == w.first.sha256
    assert not w.widget.document_runner.busy


def test_list_row_reload_and_badges_do_not_hash_pdfs(workspace, monkeypatch):
    w = workspace
    open_pdf(w)

    def denied(*args, **kwargs):
        raise AssertionError("List metadata and repaint must not hash a PDF")

    monkeypatch.setattr(BlobStore, "_verify", denied)
    monkeypatch.setattr(main.pdf_highlights, "document_hash", denied)
    shown = w.data.queue(list_id=w.list_id)[0]
    assert shown.has_pdf and shown.has_pdf
    assert shown.pdf_path.name == w.first.sha256 + ".pdf"


def test_switching_papers_while_verification_runs_opens_only_the_latest_selection(
    workspace, monkeypatch
):
    w = workspace
    added = w.actions.add_papers(
        w.list_id, [{"paper": paper("Second paper")}], request_id="add-second"
    )
    identity = added["papers"][0]["paper_id"]
    source = w.root / "other-paper.pdf"
    source.write_bytes(pdf_bytes("Different paper entirely"))
    manifest = stage_file(w.blobs, source)
    w.actions.attach_document(identity, manifest, store=w.blobs, request_id="other-document")
    with w.side.journal.transaction() as conn:
        target = desired_document(conn, identity)
        assert bind_verified_document(conn, target, verify_document(w.blobs, target))
    other = next(p for p in w.data.queue(list_id=w.list_id) if p.id != w.widget.paper.id)
    first_id = w.widget.paper.id
    resolver = w.widget.paper._document_reader
    original = resolver.resolve
    reached, release, calls = Event(), Event(), []

    def delayed(local_id):
        calls.append(local_id)
        if local_id == first_id:
            reached.set()
            assert release.wait(8)
        return original(local_id)

    monkeypatch.setattr(resolver, "resolve", delayed)
    w.widget._load_pdf()
    assert reached.wait(8)
    try:
        w.widget.paper = other
        w.widget._load_pdf()
    finally:
        release.set()
    wait_for(w.app, lambda: not w.widget.document_runner.busy)
    assert w.widget._pdf_fingerprint == manifest.sha256
    assert "Different paper entirely" in w.widget.pdf.page_text(0)
    assert calls == [first_id, other.id]
