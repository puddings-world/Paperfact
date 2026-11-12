"""Actual presentation source clicks, immutable originals and owned desktop work."""

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import closing
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThread, QUrl
from PySide6.QtWidgets import QApplication
from test_active_deck_originals import actual as actual
from test_active_deck_originals import case as case
from test_active_deck_originals import codec as codec
from test_active_deck_originals import local as local
from test_active_deck_originals import no_external as no_external
from test_active_deck_originals import original as original
from test_active_deck_originals import package as package
from test_active_deck_originals import ready as ready
from test_active_deck_originals import scientific as scientific

from paper_daily import active_deck_originals, llm, store
from paper_daily.desktop import main, original_version
from paper_daily.desktop.document_flow import anchor_allowed, loaded_document_valid
from paper_daily.document_reader import from_workspace


def baseline(value):
    # Observation must not checkpoint the database and revoke a live proof.
    database = value["database"]
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        sql = list(conn.iterdump())
    files = {
        str(path.relative_to(database.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in database.parent.rglob("*")
        if path.is_file() and not path.name.endswith(("-wal", "-shm"))
    }
    return sql, files


def settle(app, predicate, timeout=15):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate()


@pytest.fixture
def reader(ready, tmp_path, monkeypatch):
    if ready["mode"] == "local":
        root = tmp_path / "current-pdf"
        root.mkdir()
        # The maintained fixture's primary B is distinct from the included original A.
        (root / (ready["paper"] + ".pdf")).write_bytes(scientific_pdf_b(ready))
        resolver = from_workspace(ready["database"], legacy_root=root)
    else:
        resolver = from_workspace(ready["database"])
    loaded = resolver.resolve(ready["paper"])
    assert loaded.available and loaded.sha256 != ready["document_hash"]
    app = QApplication.instance() or QApplication([])
    win = SimpleNamespace(
        pal=main.palette(), remember=lambda *_: None, data=main.Data(), language="en"
    )
    view = main.ReaderPage(win)
    win.reader_page = view
    view.paper = SimpleNamespace(
        id=ready["paper"],
        title="Read original",
        _document_reader=resolver,
        _document_status=loaded,
        _loaded_document=loaded,
    )
    view._active_document = loaded
    view._pdf_fingerprint = loaded.sha256
    view.resize(1300, 850)
    view.show()
    view.auto_highlights.setChecked(False)
    assert view.pdf.load(loaded.path)
    view.pdf.show()
    view.presentation_pane.load(ready["paper"], "Read original")
    view.note_edit.setPlainText("Preserve unsent reading interpretation")
    app.processEvents()
    assert loaded_document_valid(view)
    source = next(s for s in view.presentation_pane.deck.sources if s["id"] == "figure:1")
    assert not anchor_allowed(view, source)
    yield SimpleNamespace(app=app, view=view, win=win, source=source, loaded=loaded, value=ready)
    view.active_originals.request_close()
    settle(app, lambda: not view.active_originals.busy)
    view.pdf.unload()
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def scientific_pdf_b(value):
    # The local original fixture includes A bytes, while this independent PDF is B.
    import pymupdf

    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 50), "Current primary B: retain this document and drafts")
        return pdf.tobytes()


def click(r):
    r.view.presentation_pane.preview.anchorClicked.emit(QUrl("paperfact-source:figure:1"))


def opened(r):
    c = r.view.active_originals
    settle(r.app, lambda: c._worker is None)
    assert c.viewer is not None, r.view.presentation_pane.status.text()
    viewer = c.viewer
    settle(
        r.app,
        lambda: (
            viewer.disposed
            or (viewer.pdf.pageCount() > 0 if viewer.native else viewer._rendered_page >= 0)
        ),
    )
    assert not viewer.disposed and viewer.snapshot.data == r.value["pdf"]
    return viewer


def held(r, monkeypatch):
    entered, release, calls = threading.Event(), threading.Event(), []
    prepare = active_deck_originals.prepare

    def controlled(*args, **kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(20)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(active_deck_originals, "prepare", controlled)
    click(r)
    settle(r.app, entered.is_set)
    return release, calls


def test_repeated_actual_source_click_opens_exact_original_once_off_gui_and_preserves_b(
    reader, monkeypatch
):
    r = reader
    before, physical = baseline(r.value), r.loaded.path.read_bytes()
    prepare, calls = active_deck_originals.prepare, []

    def observed(*args, **kwargs):
        calls.append(QThread.currentThread() != r.app.thread())
        return prepare(*args, **kwargs)

    def deny(*_args, **_kwargs):
        pytest.fail("Reading a saved source must not call AI or accounts")

    monkeypatch.setattr(active_deck_originals, "prepare", observed)
    monkeypatch.setattr(llm, "complete_result", deny)
    monkeypatch.setattr(llm, "capture_connections", deny)
    for _ in range(25):
        click(r)
    viewer = opened(r)
    assert viewer.snapshot.document_hash == r.value["document_hash"]
    assert viewer.page.value() == 1 and calls == [True]
    click(r)
    r.app.processEvents()
    assert r.view.active_originals.viewer is viewer and calls == [True]
    assert r.view._active_document is r.loaded and r.view._pdf_fingerprint == r.loaded.sha256
    assert r.loaded.path.read_bytes() == physical
    assert r.view.note_edit.toPlainText() == "Preserve unsent reading interpretation"
    assert baseline(r.value) == before


@pytest.mark.parametrize("change", ["paper", "source", "close"])
def test_held_source_read_never_opens_after_context_change_or_close(reader, monkeypatch, change):
    r = reader
    before = baseline(r.value)
    release, calls = held(r, monkeypatch)
    try:
        for _ in range(25):
            click(r)
        if change == "paper":
            r.view.paper = SimpleNamespace(id="another-paper")
        elif change == "source":
            r.view.presentation_pane.deck.sources[0]["text"] = "A new unsaved interpretation"
        else:
            assert not r.view.close()
            assert r.view.isVisible() and r.view.active_originals.busy
    finally:
        release.set()
    settle(r.app, lambda: not r.view.active_originals.busy)
    assert calls == [True] and r.view.active_originals.viewer is None
    assert r.view.note_edit.toPlainText() == "Preserve unsent reading interpretation"
    assert baseline(r.value) == before


def test_prepare_failure_is_sanitized_and_explicit_retry_opens_same_saved_source(
    reader, monkeypatch
):
    r = reader
    prepare = active_deck_originals.prepare

    def denied(*_args, **_kwargs):
        raise ValueError("private SQL and private workspace path")

    monkeypatch.setattr(active_deck_originals, "prepare", denied)
    click(r)
    settle(r.app, lambda: not r.view.active_originals.busy)
    assert r.view.active_originals.viewer is None
    status = r.view.presentation_pane.status.text()
    assert "could not be verified" in status and "private" not in status
    monkeypatch.setattr(active_deck_originals, "prepare", prepare)
    click(r)
    assert opened(r).snapshot.document_hash == r.value["document_hash"]


def test_note_write_revalidates_same_original_without_sql_json_or_hash_on_gui(reader, monkeypatch):
    r = reader
    click(r)
    viewer = opened(r)
    captured = viewer.snapshot.active_proof.capture
    with closing(sqlite3.connect(r.value["database"])) as conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) VALUES(?,?,'note','2026-11-01')",
            (r.value["paper"], "New unrelated note"),
        )
        conn.commit()
    before = baseline(r.value)
    actual = active_deck_originals.revalidate
    calls = []

    def checked(*args, **kwargs):
        calls.append(QThread.currentThread() != r.app.thread())
        return actual(*args, **kwargs)

    monkeypatch.setattr(active_deck_originals, "revalidate", checked)
    viewer.check()
    settle(r.app, lambda: not viewer.busy)
    assert calls == [True] and not viewer.disposed and viewer.view.isEnabled()
    assert (
        viewer.snapshot.active_proof.capture is captured and viewer.snapshot.data == r.value["pdf"]
    )
    assert r.view._active_document is r.loaded and baseline(r.value) == before

    def forbidden(*_args, **_kwargs):
        pytest.fail("Final GUI admission must only read native metadata")

    with monkeypatch.context() as scoped:
        scoped.setattr(sqlite3, "connect", forbidden)
        scoped.setattr(json, "loads", forbidden)
        scoped.setattr(hashlib, "sha256", forbidden)
        scoped.setattr(original_version.pymupdf, "open", forbidden)
        assert original_version.metadata_current(viewer.snapshot)


def test_matching_current_pdf_keeps_left_navigation_and_materials_do_not_borrow_deck_grant(
    reader, monkeypatch
):
    r = reader
    pages = []
    monkeypatch.setattr(r.view.pdf.selection, "scroll_to_page", pages.append)
    r.view.presentation_pane.source_requested.emit(
        dict(id="current-page", kind="original", page=1, document_hash=r.loaded.sha256)
    )
    assert pages == [0] and not r.view.active_originals.busy
    r.view.presentation_pane.materials_panel.source_requested.emit(r.source)
    r.app.processEvents()
    assert r.view.active_originals.viewer is None and not r.view.active_originals.busy
    assert not anchor_allowed(r.view, r.source)


def test_parent_launch_barrier_keeps_owned_preparation_until_worker_drain(reader, monkeypatch):
    r = reader
    release, calls = held(r, monkeypatch)
    try:
        for _ in range(3):
            assert not main.MainWindow._preparation_ready(r.win)
        assert "Cited original" in r.view.ask_status.text()
        assert r.view.active_originals.busy and calls == [True]
    finally:
        release.set()
    settle(r.app, lambda: not r.view.active_originals.busy)
    assert main.MainWindow._preparation_ready(r.win)
    assert r.view.active_originals.viewer is None


def test_unsaved_slide_draft_keeps_saved_source_readable_without_autosave(reader):
    r = reader
    pane = r.view.presentation_pane
    before = baseline(r.value)
    pane.slide_title.setText("An unsaved alternative explanation")
    pane._autosave.stop()
    assert pane._dirty
    click(r)
    viewer = opened(r)
    assert viewer.snapshot.document_hash == r.value["document_hash"]
    assert pane._dirty and pane.slide_title.text() == "An unsaved alternative explanation"
    assert baseline(r.value) == before and r.view._active_document is r.loaded


def test_unsaved_changed_source_never_borrows_saved_deck_original(reader):
    r = reader
    before = baseline(r.value)
    r.source["text"] = "New unsaved source assertion"
    click(r)
    settle(r.app, lambda: not r.view.active_originals.busy)
    assert r.view.active_originals.viewer is None
    assert "could not be verified" in r.view.presentation_pane.status.text()
    assert r.source["text"] == "New unsaved source assertion"
    assert baseline(r.value) == before


def test_closing_and_reopening_held_renderer_waits_without_duplicate_job(reader, monkeypatch):
    r = reader
    entered, release, calls = threading.Event(), threading.Event(), []
    actual = original_version.render_page
    monkeypatch.setattr(original_version, "HAVE_QTPDF", False)

    def controlled(*args):
        calls.append(True)
        entered.set()
        assert release.wait(20)
        return actual(*args)

    monkeypatch.setattr(original_version, "render_page", controlled)
    before = baseline(r.value)
    try:
        click(r)
        settle(r.app, entered.is_set)
        viewer = r.view.active_originals.viewer
        assert viewer is not None and viewer.busy
        assert not main.MainWindow._preparation_ready(r.win)
        assert viewer._closing and r.view.active_originals.busy
        for _ in range(25):
            click(r)
        assert r.view.active_originals.viewer is viewer and calls == [True]
        assert r.view.active_originals._worker is None
    finally:
        release.set()
    settle(r.app, lambda: not r.view.active_originals.busy)
    assert r.view.active_originals.viewer is None
    assert baseline(r.value) == before and r.view._active_document is r.loaded
    assert r.view.note_edit.toPlainText() == "Preserve unsent reading interpretation"


def test_workspace_switch_before_worker_delivery_never_opens_or_touches_other_database(
    reader, monkeypatch, tmp_path
):
    r = reader
    other = tmp_path / "other-workspace.sqlite"
    with closing(sqlite3.connect(other)) as conn:
        conn.execute("CREATE TABLE untouched(value TEXT)")
        conn.execute("INSERT INTO untouched VALUES('Private other workspace')")
        conn.commit()
    before = baseline(r.value)
    other_bytes = other.read_bytes()
    release, calls = held(r, monkeypatch)
    try:
        monkeypatch.setattr(store, "DB_PATH", other)
    finally:
        release.set()
    settle(r.app, lambda: not r.view.active_originals.busy)
    assert calls == [True] and r.view.active_originals.viewer is None
    assert other.read_bytes() == other_bytes and baseline(r.value) == before
    assert r.view.note_edit.toPlainText() == "Preserve unsent reading interpretation"
