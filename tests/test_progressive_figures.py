"""Owned figure loading yields, decodes off-GUI, and never retargets sources."""

import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from test_document_derivatives import workspace as managed_workspace_fixture
from test_window_fits import reader as window_fixture

from paper_daily import audit_inputs, figures, llm, manual_highlight_ops, store
from paper_daily.desktop import figure_loading, figure_pane, pdfpane
from paper_daily.desktop.main import LIGHT


def until(app, predicate):
    end = time.monotonic() + 30
    while not predicate() and time.monotonic() < end:
        QTest.qWait(5)
    assert predicate()


def test_actual_load_yields_before_all_figure_widgets_are_built(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"synthetic extraction boundary")
    found = [
        figures.Figure("paper", f"Figure {i}", "Full caption " * 5, i + 1, tmp_path / "absent.png")
        for i in range(30)
    ]
    monkeypatch.setattr(figure_pane, "extract", lambda *a, **k: found)
    pane = figure_pane.FigurePane(LIGHT)
    drawn, heartbeat, ready = [], [], []
    original = pane._entry

    def entry(*args, **kwargs):
        drawn.append(args[0].label)
        if len(drawn) == 1:
            QTimer.singleShot(0, lambda: heartbeat.append(len(drawn)))
        return original(*args, **kwargs)

    monkeypatch.setattr(pane, "_entry", entry)
    pane.ready.connect(ready.append)
    try:
        pane.load("paper", source, True)
        until(app, lambda: bool(ready) and bool(heartbeat))
        assert 0 < heartbeat[0] < len(found)
        assert drawn == [fig.label for fig in found] and ready == ["paper"]
    finally:
        if pane._thread is not None:
            pane._thread.quit()
            pane._thread.wait(3000)
        pane.deleteLater()
        app.processEvents()


window_reader = window_fixture
managed_workspace = managed_workspace_fixture


def work(call, *args, **kwargs):
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(call, *args, **kwargs).result(timeout=20)


def database_rows(database):
    with closing(audit_inputs._connect(database)) as conn:
        return list(conn.iterdump())


def original_pdf(path, count=4):
    import pymupdf
    from test_document_derivatives import pdf

    with pymupdf.open() as document:
        for index in range(count):
            with pymupdf.open(stream=pdf(f"Original result {index}"), filetype="pdf") as source:
                document.insert_pdf(source)
        document.save(path)


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    from paper_daily.desktop import main
    from paper_daily.desktop.account_status import AccountStatus
    from paper_daily.desktop.update_banner import UpdateBanner

    monkeypatch.setattr(AccountStatus, "check", lambda *a, **k: None)
    monkeypatch.setattr(UpdateBanner, "check_in_background", lambda *a, **k: None)
    monkeypatch.setattr(main.MainWindow, "_refresh_ai_summary", lambda *a, **k: None)

    def forbidden(*a, **k):
        pytest.fail("Figure loading invoked a model")

    monkeypatch.setattr(llm, "complete_result", forbidden)
    monkeypatch.setattr(llm, "complete", forbidden)


@pytest.fixture
def owned(tmp_path, monkeypatch):
    from paper_daily.document_reader import DocumentReader

    app = QApplication.instance() or QApplication([])
    database = tmp_path / "papers.db"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,year,venue,source) "
            "VALUES('paper','Original','original',2026,'Fixture','fixture')"
        )
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(figures, "FIG_DIR", tmp_path / "figures")
    monkeypatch.setattr(figures, "MIN_PNG_BYTES", 0)
    root = tmp_path / "pdf"
    root.mkdir()
    path = root / "paper.pdf"
    original_pdf(path)
    document = DocumentReader(database, projection_root=None, legacy_root=root).resolve("paper")
    owner = manual_highlight_ops.capture_owner(database, "paper")
    view = manual_highlight_ops.load(owner, path, document.sha256, document=document)
    reader = QWidget()
    reader.win = SimpleNamespace()
    reader.paper = SimpleNamespace(id="paper", pdf_path=path)
    reader._qa_epoch = 1
    reader._active_document = document
    reader._highlight_owner, reader._highlight_view = owner, view
    reader._pdf_fingerprint = document.sha256
    reader.pdf = pdfpane.make_pdf_pane(palette=LIGHT)
    assert reader.pdf.load(path)
    until(app, lambda: reader.pdf.position_source_version() is not None)
    reader.figure_pane = figure_pane.FigurePane(LIGHT)
    reader.figure_pane.resize(480, 300)
    reader.figure_pane.show()
    context = figure_loading.capture(reader)
    assert context is not None and context.current()
    data = SimpleNamespace(
        app=app,
        database=database,
        path=path,
        reader=reader,
        pane=reader.figure_pane,
        context=context,
    )
    yield data
    data.pane.request_close()
    until(app, lambda: not data.pane.busy)
    data.pane.dispose()
    reader.pdf.unload()
    data.pane.deleteLater()
    reader.pdf.deleteLater()
    reader.deleteLater()
    app.processEvents()


def start_owned(w):
    w.pane.load(w.reader.paper.id, w.path, True, context=w.context)


def hold_decode(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = figure_loading.decode
    calls = []

    def decode(*args, **kwargs):
        calls.append(threading.current_thread() is threading.main_thread())
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(figure_loading, "decode", decode)
    return entered, release, calls


def test_owned_load_held_decode_keeps_heartbeat_and_full_toc_then_gui_pixmaps(owned, monkeypatch):
    w = owned
    before = database_rows(w.database)
    entered, release, calls = hold_decode(monkeypatch)
    original_connect = audit_inputs._connect
    import pymupdf

    original_open = pymupdf.open
    gui_pixmaps = []

    def connect(*a, **k):
        assert threading.current_thread() is not threading.main_thread(), "GUI SQL"
        return original_connect(*a, **k)

    def parse(*a, **k):
        assert threading.current_thread() is not threading.main_thread(), "GUI PDF parsing"
        return original_open(*a, **k)

    class Pixmap:
        @staticmethod
        def fromImage(image):
            assert threading.current_thread() is threading.main_thread(), "Worker QPixmap"
            gui_pixmaps.append(True)
            return QPixmap.fromImage(image)

    monkeypatch.setattr(audit_inputs, "_connect", connect)
    monkeypatch.setattr(pymupdf, "open", parse)
    monkeypatch.setattr(figure_pane, "QPixmap", Pixmap)
    ready, heartbeat = [], []
    w.pane.ready.connect(ready.append)
    try:
        start_owned(w)
        until(w.app, entered.is_set)
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        until(w.app, lambda: bool(heartbeat))
        assert w.pane.busy and ready == []
        assert len(w.pane._entries) == 4 and all(e is None for e in w.pane._entries)
        assert all(f"href='{i}'" in w.pane._toc.text() for i in range(4))
    finally:
        release.set()
    until(w.app, lambda: not w.pane.busy)
    assert ready == ["paper"] and len(gui_pixmaps) == 4 and calls == [False] * 4
    assert w.pane.loaded_document_hash == w.reader._pdf_fingerprint
    assert all(e is not None for e in w.pane._entries)
    captions = [label.text() for entry in w.pane._entries for label in entry.findChildren(QLabel)]
    assert sum("Synthetic research result" in caption for caption in captions) == 4
    monkeypatch.setattr(audit_inputs, "_connect", original_connect)
    assert database_rows(w.database) == before


def test_repeated_actual_capture_coalesces_same_running_request(owned, monkeypatch):
    w = owned
    entered, release, calls = hold_decode(monkeypatch)
    ready = []
    w.pane.ready.connect(ready.append)
    try:
        start_owned(w)
        until(w.app, entered.is_set)
        worker = w.pane._running
        for _ in range(30):
            context = figure_loading.capture(w.reader)
            assert context == w.context
            w.pane.load("paper", w.path, True, context=context)
        assert w.pane._running is worker and w.pane._requested is None
    finally:
        release.set()
    until(w.app, lambda: not w.pane.busy)
    assert ready == ["paper"] and len(calls) == 4


@pytest.mark.parametrize("change", ["paper", "epoch", "pdf", "workspace", "database"])
def test_pending_owned_decode_never_delivers_or_jumps_to_changed_context(
    owned, monkeypatch, change, tmp_path
):
    w = owned
    entered, release, _ = hold_decode(monkeypatch)
    ready, jumps = [], []
    w.pane.ready.connect(ready.append)
    w.pane.jump.connect(lambda *a: jumps.append(a))
    try:
        start_owned(w)
        until(w.app, entered.is_set)
        old = w.pane._running.figures[0]
        if change == "paper":
            w.reader.paper = SimpleNamespace(id="other")
        elif change == "epoch":
            w.reader._qa_epoch += 1
        elif change == "pdf":
            w.path.write_bytes(w.path.read_bytes())
        elif change == "workspace":
            monkeypatch.setattr(store, "DB_PATH", tmp_path / "other.db")
        else:
            replacement = w.database.with_suffix(".replacement")
            replacement.write_bytes(w.database.read_bytes())
            os.replace(replacement, w.database)
        w.pane._jump(old)
        assert jumps == []
    finally:
        release.set()
    until(w.app, lambda: not w.pane.busy)
    assert ready == [] and all(e is None for e in w.pane._entries)
    assert not (tmp_path / "other.db").exists()


def test_changed_asset_queued_before_gui_insert_is_rejected(owned, monkeypatch):
    w = owned
    queued, ready = [], []
    monkeypatch.setattr(w.pane, "_queue_entry", queued.append)
    w.pane.ready.connect(ready.append)
    start_owned(w)
    until(w.app, lambda: bool(queued))
    row = queued[0]
    row.figure.path.write_bytes(b"changed queued image")
    w.pane._insert_entry(row)
    until(w.app, lambda: not w.pane.busy)
    assert ready == [] and all(e is None for e in w.pane._entries)
    assert any("retry" in label.text() for label in w.pane.findChildren(QLabel))


def test_decode_failure_then_explicit_retry_keeps_saved_rows(owned, monkeypatch):
    w = owned
    before = database_rows(w.database)
    original = figure_loading.decode
    calls = []

    def fail_once(*a, **k):
        calls.append(True)
        if len(calls) == 1:
            raise ValueError("synthetic decoder failure")
        return original(*a, **k)

    monkeypatch.setattr(figure_loading, "decode", fail_once)
    ready = []
    w.pane.ready.connect(ready.append)
    start_owned(w)
    until(w.app, lambda: not w.pane.busy)
    assert ready == []
    assert any("retry" in label.text() for label in w.pane.findChildren(QLabel))
    start_owned(w)
    until(w.app, lambda: not w.pane.busy)
    assert ready == ["paper"] and len(calls) == 5
    assert database_rows(w.database) == before


def test_close_with_active_decode_vetoes_until_real_worker_drain(owned, monkeypatch):
    w = owned
    entered, release, _ = hold_decode(monkeypatch)
    ready = []
    w.pane.ready.connect(ready.append)
    try:
        start_owned(w)
        until(w.app, entered.is_set)
        worker = w.pane._running
        assert not w.pane.close()
        assert w.pane.busy and worker.isRunning() and w.pane.isVisible()
    finally:
        release.set()
    until(w.app, lambda: not w.pane.busy)
    assert ready == [] and w.pane.close() and w.pane._disposed


def test_loaded_proof_is_not_forgeable_by_copying_bytes_or_owner_metadata(owned):
    w = owned
    proof = work(
        figures.capture_loaded, w.context.view, w.context.document, w.context.native_version
    )
    corrupted = replace(proof, data=b"unowned PDF bytes")
    with pytest.raises(ValueError, match="actual loaded source proof"):
        work(figures.extract, "paper", w.path, loaded_source=corrupted, root=w.context.root)
    with pytest.raises(ValueError):
        work(
            figures.capture_loaded, dict(path=w.path), w.context.document, w.context.native_version
        )


def test_owned_legacy_extraction_preserves_default_cached_only_contract(owned, monkeypatch):
    w = owned
    start_owned(w)
    until(w.app, lambda: not w.pane.busy)
    before = {p: p.read_bytes() for p in w.context.root.rglob("*") if p.is_file()}
    import pymupdf

    monkeypatch.setattr(pymupdf, "open", lambda *a, **k: pytest.fail("cached_only parsed PDF"))
    found = figures.extract("paper", w.path, cached_only=True)
    assert len(found) == 4 and all(f.path.is_file() for f in found)
    assert [f.caption for f in found] == [f.caption for f in w.pane._frame.figures]
    assert {p: p.read_bytes() for p in w.context.root.rglob("*") if p.is_file()} == before


def test_pending_toc_selection_prioritizes_its_real_entry_on_same_worker(owned, monkeypatch):
    w = owned
    entered, release, _ = hold_decode(monkeypatch)
    drawn = []
    original = w.pane._entry
    monkeypatch.setattr(
        w.pane, "_entry", lambda fig, *a: drawn.append(fig.page) or original(fig, *a)
    )
    try:
        start_owned(w)
        until(w.app, entered.is_set)
        w.pane._toc.linkActivated.emit("3")
    finally:
        release.set()
    until(w.app, lambda: not w.pane.busy)
    assert drawn[:2] == [1, 4] and sorted(drawn) == [1, 2, 3, 4]
    assert w.pane._entries[3] is not None


def test_stable_foreign_png_cannot_borrow_original_source_label(owned, monkeypatch):
    w = owned
    original = figure_loading.decode
    once = []

    def changed(path, expected=None):
        if not once:
            once.append(True)
            path.write_bytes(b"foreign stable image bytes")
        return original(path, expected)

    monkeypatch.setattr(figure_loading, "decode", changed)
    ready = []
    w.pane.ready.connect(ready.append)
    start_owned(w)
    until(w.app, lambda: not w.pane.busy)
    assert ready == [] and all(e is None for e in w.pane._entries)
    start_owned(w)
    until(w.app, lambda: not w.pane.busy)
    assert ready == ["paper"]


def test_deleting_pane_with_active_decode_retains_worker_until_actual_drain(owned, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid

    w = owned
    pane = figure_pane.FigurePane(LIGHT)
    entered, release, _ = hold_decode(monkeypatch)
    ready = []
    pane.ready.connect(ready.append)
    try:
        pane.load("paper", w.path, True, context=w.context)
        until(w.app, entered.is_set)
        worker = pane._running
        pane.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(pane)
        assert worker in figure_loading._LIVE
    finally:
        release.set()
    until(w.app, lambda: worker not in figure_loading._LIVE)
    assert ready == []


def test_large_ordinary_pdf_does_not_inherit_claim_or_lineage_32mib_limit(owned):
    from paper_daily.document_reader import DocumentReader

    w = owned
    w.reader.pdf.unload()
    padding = b"\n%" + b"x" * (33 * 1024 * 1024)
    w.path.write_bytes(w.path.read_bytes() + padding)
    document = DocumentReader(w.database, projection_root=None, legacy_root=w.path.parent).resolve(
        "paper"
    )
    owner = w.reader._highlight_owner
    view = manual_highlight_ops.load(owner, w.path, document.sha256, document=document)
    assert w.reader.pdf.load(w.path)
    until(w.app, lambda: w.reader.pdf.position_source_version() is not None)
    w.reader._active_document, w.reader._highlight_view = document, view
    w.reader._pdf_fingerprint = document.sha256
    proof = work(figures.capture_loaded, view, document, w.reader.pdf.position_source_version())
    assert len(proof.data) > 32 * 1024 * 1024
    found = work(figures.extract, "paper", w.path, loaded_source=proof, root=w.context.root)
    assert len(found) == 4 and all(f.meta["document_hash"] == document.sha256 for f in found)


def test_actual_main_restart_update_and_close_wait_for_held_decode(
    window_reader, tmp_path, monkeypatch
):
    window, app = window_reader
    reader = window.reader_page
    path = tmp_path / "actual-native.pdf"
    original_pdf(path, count=2)
    owner = manual_highlight_ops.capture_owner(store.DB_PATH, "p")
    digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
    reader._highlight_owner = owner
    reader._highlight_view = manual_highlight_ops.load(owner, path, digest)
    reader._active_document = None
    reader._pdf_fingerprint = digest
    assert reader.pdf.load(path)
    until(app, lambda: reader.pdf.position_source_version() is not None)
    until(app, lambda: not reader.preparation.busy and not reader.reading_positions.busy)
    monkeypatch.setattr(figures, "FIG_DIR", tmp_path / "figures")
    monkeypatch.setattr(figures, "MIN_PNG_BYTES", 0)
    entered, release, _ = hold_decode(monkeypatch)
    remembered, saves = [], []
    reader.ask_box.setText("UNSENT QUESTION")
    reader.note_edit.setPlainText("UNSENT NOTE")
    monkeypatch.setattr(window, "remember", lambda *a: remembered.append(a))
    monkeypatch.setattr(
        reader.presentation_pane, "save_changes", lambda: saves.append(True) or True
    )
    monkeypatch.setattr(reader, "_load_dive", lambda: None)
    try:
        reader._load_figures()
        until(app, entered.is_set)
        worker = reader.figure_pane._running
        for _ in range(5):
            assert window._prepare_restart() is False
            assert window._prepare_update() is False
            assert window.close() is False
        assert worker.isRunning() and reader.figure_pane.busy
        assert remembered == saves == []
        assert window.isVisible() and not window.workspace_changes.disposed
        assert not reader.figure_pane._disposed
        assert reader.ask_box.text() == "UNSENT QUESTION"
        assert reader.note_edit.toPlainText() == "UNSENT NOTE"
    finally:
        release.set()
    until(app, lambda: not reader.figure_pane.busy)
    until(
        app,
        lambda: (
            not reader.preparation.busy
            and not reader.reading_positions.busy
            and not window.activity_hub.busy
        ),
    )
    assert window._prepare_restart() is True
    assert saves and remembered
    assert reader.ask_box.text() == "UNSENT QUESTION"
    assert reader.note_edit.toPlainText() == "UNSENT NOTE"
    assert window.close() and reader.figure_pane._disposed


def test_loaded_managed_A_figures_stay_bound_when_primary_B_is_desired(managed_workspace):
    from test_document_derivatives import pdf
    from test_document_reader import LOCAL

    from paper_daily import research_generation as generation
    from paper_daily import sync_capture
    from paper_daily.sync_documents import desired_document

    w = managed_workspace
    app = QApplication.instance() or QApplication([])
    first = w.install(pdf("Original version A"), "source-A")
    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_research import research_writer

    SyncClient(w.journal, research_writer)
    with closing(generation._connect(w.path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(
            conn, workspace_id=w.journal.workspace_id, device_id=w.journal.device_id
        )
        conn.commit()
    owner = manual_highlight_ops.capture_owner(w.path, LOCAL)
    view = manual_highlight_ops.load(owner, first.path, first.sha256, document=first)
    native = QWidget()
    native.win = SimpleNamespace()
    native.paper = SimpleNamespace(id=LOCAL)
    native._qa_epoch = 1
    native._active_document, native._highlight_owner = first, owner
    native._highlight_view, native._pdf_fingerprint = view, first.sha256
    native.pdf = pdfpane.make_pdf_pane(palette=LIGHT)
    assert native.pdf.load(first.path)
    until(app, lambda: native.pdf.position_source_version() is not None)
    later = w.install(pdf("Desired version B", second_page=True), "source-B")
    assert not first._owner.current(first) and first._owner.intact(first)
    before = database_rows(w.path), w.journal.pending()
    context = figure_loading.capture(native)
    assert context is not None and context.current()
    pane = figure_pane.FigurePane(LIGHT)
    ready, jumps = [], []
    pane.ready.connect(ready.append)
    pane.jump.connect(lambda page, caption: jumps.append((page, pane.loaded_document_hash)))
    try:
        pane.load(LOCAL, first.path, True, context=context)
        until(app, lambda: not pane.busy)
        assert ready == [LOCAL] and pane.loaded_document_hash == first.sha256
        assert len(pane._frame.figures) == 1
        pane._jump(pane._frame.figures[0])
        assert jumps == [(1, first.sha256)]
        assert figures.extract(LOCAL, first.path, document=first, cached_only=True) == []
        with closing(audit_inputs._connect(w.path)) as conn:
            assert desired_document(conn, first.paper_id)["sha256"] == later.sha256
        assert (database_rows(w.path), w.journal.pending()) == before
    finally:
        pane.request_close()
        until(app, lambda: not pane.busy)
        pane.dispose()
        pane.deleteLater()
        native.pdf.unload()
        native.pdf.deleteLater()
        native.deleteLater()
        app.processEvents()


def test_rapid_same_paper_new_pdf_keeps_latest_request_and_rejects_old_jump(owned, monkeypatch):
    w = owned
    entered, release, _ = hold_decode(monkeypatch)
    ready, jumps = [], []
    w.pane.ready.connect(ready.append)
    w.pane.jump.connect(lambda *args: jumps.append(args))
    try:
        start_owned(w)
        until(w.app, entered.is_set)
        old = w.pane._running.figures[0]
        replacement = w.path.parent / "replacement-B.pdf"
        original_pdf(replacement, count=2)
        digest = __import__("hashlib").sha256(replacement.read_bytes()).hexdigest()
        owner = w.reader._highlight_owner
        new_view = manual_highlight_ops.load(owner, replacement, digest)
        w.reader._active_document, w.reader._highlight_view = None, new_view
        w.reader._pdf_fingerprint = digest
        w.reader._qa_epoch += 1
        assert w.reader.pdf.load(replacement)
        until(w.app, lambda: w.reader.pdf.position_source_version() is not None)
        latest = figure_loading.capture(w.reader)
        assert latest is not None
        for _ in range(20):
            w.pane.load("paper", replacement, True, context=latest)
        w.pane._jump(old)
        assert jumps == []
        w.pane._check_context()
        assert w.pane._requested is not None
    finally:
        release.set()
    until(w.app, lambda: not w.pane.busy)
    assert ready == ["paper"] and w.pane.loaded_document_hash == digest
    assert len(w.pane._entries) == 2 and all(e is not None for e in w.pane._entries)


def test_empty_extraction_preserves_no_ready_and_no_navigation_contract(owned, monkeypatch):
    monkeypatch.setattr(figure_pane, "extract", lambda *a, **k: [])
    ready = []
    owned.pane.ready.connect(ready.append)
    start_owned(owned)
    until(owned.app, lambda: not owned.pane.busy)
    assert ready == [] and owned.pane._entries == []
    assert owned.pane.loaded_document_hash is None


def test_native_finished_delivery_rechecks_context_before_leaving_old_rows(owned, monkeypatch):
    w = owned
    delivered, ready = [], []
    original = w.pane._next_request
    monkeypatch.setattr(w.pane, "_next_request", lambda: delivered.append(True))
    w.pane.ready.connect(ready.append)
    start_owned(w)
    until(w.app, lambda: bool(delivered))
    worker = w.pane._running
    assert worker.wait(0) and all(e is not None for e in w.pane._entries)
    w.reader._qa_epoch += 1
    original()
    assert ready == [] and w.pane._entries == [] and not w.pane.busy


# Continuation acceptance: ordinary research/private writes are not figure inputs.
def figure_write(w, kind, index=1):
    if kind == "reading":
        from paper_daily.desktop import ui_state

        ui_state.save("ui.paper.opened:paper", f"2026-10-31T14:00:{index:02d}+00:00")
        assert ui_state.flush()
    else:
        with store.connect(path=w.database) as conn:
            conn.execute(
                "INSERT INTO notes(paper_id,body,kind,created_at) "
                "VALUES('paper',?,'note','2026-10-31T14:00:00+00:00')",
                (f"Saved interpretation {index}",),
            )


def image_count(pane):
    return sum(
        not label.pixmap().isNull()
        for entry in pane._entries
        if entry is not None
        for label in entry.findChildren(QLabel)
    )


def observe_local_work(monkeypatch):
    counts = dict(extract=0, decode=0, check=0)
    extract, decode, check = (
        figure_pane.extract,
        figure_loading.decode,
        figures.recheck_loaded_lease,
    )

    def extracted(*a, **k):
        counts["extract"] += 1
        return extract(*a, **k)

    def decoded(*a, **k):
        counts["decode"] += 1
        return decode(*a, **k)

    def checked(*a, **k):
        counts["check"] += 1
        return check(*a, **k)

    monkeypatch.setattr(figure_pane, "extract", extracted)
    monkeypatch.setattr(figure_loading, "decode", decoded)
    monkeypatch.setattr(figures, "recheck_loaded_lease", checked)
    return counts


@pytest.mark.parametrize("kind", ["reading", "note"])
def test_owned_decode_survives_real_db_only_write_without_extra_local_work(
    owned, monkeypatch, kind
):
    w = owned
    counts = observe_local_work(monkeypatch)
    entered, release, _ = hold_decode(monkeypatch)
    ready = []
    w.pane.ready.connect(ready.append)
    try:
        start_owned(w)
        until(w.app, entered.is_set)
        until(w.app, lambda: not w.pane._toc.isHidden())
        worker = w.pane._running
        figure_write(w, kind)
        w.pane._check_context()
        assert worker is w.pane._running and not worker.stopped.is_set()
        assert not w.pane._toc.isHidden() and w.context.current()
    finally:
        release.set()
    until(w.app, lambda: not w.pane.busy)
    assert ready == ["paper"] and image_count(w.pane) == 4
    assert counts["extract"] == 1 and counts["decode"] == 4
    before = database_rows(w.database)
    jumps = []
    w.pane.jump.connect(lambda *args: jumps.append(args))
    w.pane._jump(w.pane._frame.figures[0])
    assert len(jumps) == 1 and database_rows(w.database) == before


@pytest.mark.parametrize("kind", ["reading", "note"])
def test_ready_frame_survives_real_db_write_and_one_lane_recheck(owned, monkeypatch, kind):
    w = owned
    counts = observe_local_work(monkeypatch)
    ready, jumps = [], []
    w.pane.ready.connect(ready.append)
    w.pane.jump.connect(lambda *args: jumps.append(args))
    start_owned(w)
    until(w.app, lambda: not w.pane.busy)
    original_entries = tuple(w.pane._entries)
    original_toc = w.pane._toc.text()
    before = counts.copy()
    figure_write(w, kind)
    after_write_rows = database_rows(w.database)
    w.pane._jump(w.pane._frame.figures[0])
    assert jumps == []
    w.pane._check_context()
    assert w.pane.busy and image_count(w.pane) == 4
    assert not w.pane._toc.isHidden() and tuple(w.pane._entries) == original_entries
    assert all(not w.pane.recheck_source() for _ in range(20))
    until(w.app, lambda: not w.pane.busy)
    assert tuple(w.pane._entries) == original_entries and w.pane._toc.text() == original_toc
    assert image_count(w.pane) == 4 and ready == ["paper"]
    assert counts["extract"] == before["extract"] == 1 and counts["decode"] == before["decode"] == 4
    assert counts["check"] == before["check"] + 1
    w.pane._jump(w.pane._frame.figures[0])
    assert len(jumps) == 1 and database_rows(w.database) == after_write_rows


def test_initial_ready_waits_for_one_stable_lease_without_another_extraction(owned, monkeypatch):
    w = owned
    counts = observe_local_work(monkeypatch)
    queued, ready = [], []
    actual = w.pane._next_request
    monkeypatch.setattr(w.pane, "_next_request", lambda: queued.append(True))
    w.pane.ready.connect(ready.append)
    start_owned(w)
    until(w.app, lambda: bool(queued))
    assert w.pane._running.wait(0) and ready == [] and image_count(w.pane) == 4
    figure_write(w, "reading")
    monkeypatch.setattr(w.pane, "_next_request", actual)
    actual()
    assert w.pane.busy and ready == [] and image_count(w.pane) == 4
    until(w.app, lambda: not w.pane.busy)
    assert ready == ["paper"] and image_count(w.pane) == 4
    assert counts["extract"] == 1 and counts["decode"] == 4


@pytest.mark.parametrize("change", ["binding", "parent", "database", "pdf", "view"])
def test_completed_frame_still_revokes_real_owner_source_and_native_changes(owned, change):
    w = owned
    ready, jumps = [], []
    w.pane.ready.connect(ready.append)
    w.pane.jump.connect(lambda *args: jumps.append(args))
    start_owned(w)
    until(w.app, lambda: not w.pane.busy)
    old = w.pane._frame.figures[0]
    if change == "binding":
        from paper_daily import sync_research

        sync_research.prepare(w.database, workspace_id="other", device_id="device")
    elif change == "parent":
        with store.connect(path=w.database) as conn:
            conn.execute("DELETE FROM papers WHERE id='paper'")
            store.upsert_papers(
                conn,
                [dict(id="paper", title="Recreated", year=2026, venue="Fixture", source="fixture")],
            )
    elif change == "database":
        replacement = w.database.with_suffix(".replacement")
        replacement.write_bytes(w.database.read_bytes())
        os.replace(replacement, w.database)
    elif change == "pdf":
        w.path.write_bytes(w.path.read_bytes())
    else:
        w.reader._qa_epoch += 1
    w.pane._check_context()
    w.pane._jump(old)
    assert jumps == []
    until(w.app, lambda: not w.pane.busy and w.pane._frame is None)
    assert w.pane._entries == [] and ready == ["paper"]


def test_unstable_real_recheck_latches_until_explicit_retry_without_reextract(owned, monkeypatch):
    w = owned
    counts = observe_local_work(monkeypatch)
    ready, jumps = [], []
    w.pane.ready.connect(ready.append)
    w.pane.jump.connect(lambda *args: jumps.append(args))
    start_owned(w)
    until(w.app, lambda: not w.pane.busy)
    before = counts.copy()
    original = figures._check_loaded
    writes = []

    def unstable(*args, **kwargs):
        result = original(*args, **kwargs)
        writes.append(True)
        figure_write(w, "reading", len(writes) + 1)
        return result

    monkeypatch.setattr(figures, "_check_loaded", unstable)
    figure_write(w, "reading")
    w.pane._check_context()
    until(w.app, lambda: not w.pane.busy)
    assert len(writes) == 1 and w.pane._lease_failed
    assert image_count(w.pane) == 4 and not w.pane._toc.isHidden()
    assert ready == ["paper"]
    w.pane._jump(w.pane._frame.figures[0])
    assert jumps == []
    for _ in range(30):
        w.pane._check_context()
    assert len(writes) == 1 and not w.pane.busy
    assert counts["extract"] == before["extract"] and counts["decode"] == before["decode"]
    monkeypatch.setattr(figures, "_check_loaded", original)
    assert w.pane.recheck_source()
    assert all(not w.pane.recheck_source() for _ in range(20))
    until(w.app, lambda: not w.pane.busy)
    assert not w.pane._lease_failed and image_count(w.pane) == 4
    assert ready == ["paper"] and counts["check"] == before["check"] + 2
    w.pane._jump(w.pane._frame.figures[0])
    assert len(jumps) == 1


def test_active_source_check_coalesces_and_close_waits_for_actual_native_drain(owned, monkeypatch):
    w = owned
    counts = observe_local_work(monkeypatch)
    ready = []
    w.pane.ready.connect(ready.append)
    start_owned(w)
    until(w.app, lambda: not w.pane.busy)
    before = counts.copy()
    original = figures.recheck_loaded_lease
    entered, release = threading.Event(), threading.Event()
    checks = []

    def held(*args, **kwargs):
        checks.append(True)
        entered.set()
        assert release.wait(20)
        return original(*args, **kwargs)

    monkeypatch.setattr(figures, "recheck_loaded_lease", held)
    try:
        figure_write(w, "note")
        w.pane._check_context()
        until(w.app, entered.is_set)
        worker = w.pane._running
        assert image_count(w.pane) == 4 and ready == ["paper"]
        for _ in range(30):
            w.pane._check_context()
            assert not w.pane.recheck_source()
        assert len(checks) == 1
        assert not w.pane.close() and w.pane.busy and worker.isRunning()
    finally:
        release.set()
    until(w.app, lambda: not w.pane.busy)
    assert w.pane.close() and ready == ["paper"]
    assert counts["extract"] == before["extract"] and counts["decode"] == before["decode"]


def test_db_write_during_queued_row_reuses_same_decoded_image_once(owned, monkeypatch):
    w = owned
    counts = observe_local_work(monkeypatch)
    actual = w.pane._queue_entry
    once = []

    def queued(row):
        if not once:
            once.append(True)
            figure_write(w, "reading")
        actual(row)

    monkeypatch.setattr(w.pane, "_queue_entry", queued)
    ready = []
    w.pane.ready.connect(ready.append)
    start_owned(w)
    until(w.app, lambda: not w.pane.busy)
    assert ready == ["paper"] and image_count(w.pane) == 4
    assert counts["extract"] == 1 and counts["decode"] == 4
