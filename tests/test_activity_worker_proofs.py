"""Real source proofs and GUI capability boundaries; ordinary reader load stays separate."""

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from test_research_generation import pdf
from test_sync_document_research import local_blob
from test_workspace_activity import NOTE, PAPER, operation
from test_workspace_activity import activity as activity_fixture

from paper_daily import manual_highlight_ops
from paper_daily.desktop import recorded_navigation
from paper_daily.desktop.research_updates import ResearchUpdatesDialog
from paper_daily.document_reader import DocumentReader
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_documents import bind_verified_document, desired_document, verify_document
from paper_daily.workspace_activity import ActivityReader
from paper_daily.workspace_service import Ticket, WorkspaceChanged

activity = activity_fixture


def worker(task):
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(task).result(timeout=5)


@pytest.fixture
def actual_source(activity, tmp_path):
    database, service, client, server, token, note = activity
    source = tmp_path / "source.pdf"
    pdf(source, "An actual owned source passage")
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    upload = server.blob_begin(token, dict(sha256=digest, size=len(data)))
    server.blob_append(token, upload["upload_id"], 0, data)
    server.blob_commit(token, upload["upload_id"])
    server.push(
        token,
        operation(
            "paper_document",
            PAPER,
            dict(paper_id=PAPER, sha256=digest, size=len(data), media_type="application/pdf"),
            "source-created",
        ),
    )
    anchor = dict(p0=0, o0=0, p1=0, o1=2, document_hash=digest)
    server.push(
        token,
        operation(
            "note",
            NOTE,
            dict(note, anchor=anchor),
            "note-source",
            base=2,
            incarnation="note-created",
        ),
    )
    client.receive(server.pull(token, after=2))
    blobs = BlobStore(tmp_path / "local-blobs")
    local_blob(blobs, data)
    with client.journal.transaction() as conn:
        wanted = desired_document(conn, PAPER)
        assert bind_verified_document(conn, wanted, verify_document(blobs, wanted))
    legacy = tmp_path / "pdf"
    legacy.mkdir()
    resolver = DocumentReader(
        database, blob_store=blobs, projection_root=tmp_path / "reader-pdf", legacy_root=legacy
    )
    row = worker(service.snapshot)["continue"][0]
    selected = worker(lambda: service.resolve(row, locate=True))
    document = resolver.resolve(selected["local_paper_id"])
    assert document.available and document.managed
    from paper_daily import research_generation, sync_capture

    with closing(research_generation._connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="local")
        conn.commit()
    owner = manual_highlight_ops.capture_owner(database, document.local_id)
    # Activity opens after the reader has captured its actual enrolled source owner.
    service = ActivityReader(database)
    row = worker(service.snapshot)["continue"][0]
    moves, opens = [], []
    reader = SimpleNamespace(
        paper=SimpleNamespace(
            id=document.local_id, _document_status=document, _document_reader=resolver
        ),
        _active_document=document,
        _highlight_owner=owner,
        _qa_epoch=1,
        _qa_view_database=database,
        _pdf_fingerprint=digest,
        note_edit=SimpleNamespace(toPlainText=lambda: ""),
        ask_box=SimpleNamespace(text=lambda: ""),
        presentation_pane=SimpleNamespace(busy=False),
        runner=SimpleNamespace(busy=False),
        pdf=SimpleNamespace(
            selection=SimpleNamespace(focus=lambda value: moves.append(value) or True)
        ),
    )
    window = SimpleNamespace(
        reader_page=reader,
        analysis_running=lambda: False,
        stack=SimpleNamespace(setCurrentWidget=lambda _: None),
        open_anywhere=lambda identity: opens.append(identity) or True,
    )

    def change_note(body):
        result = server.push(
            token,
            operation(
                "note",
                NOTE,
                dict(note, anchor=anchor, body=body),
                "note-changed",
                base=4,
                incarnation="note-created",
            ),
        )
        assert result["outcome"] == "accepted"
        client.receive(server.pull(token, after=4))

    window.change_note = change_note
    yield window, service, row, moves, opens
    resolver.close()


def no_gui_io(monkeypatch):
    main = threading.get_ident()
    observed = []
    connect, digest, sha256 = sqlite3.connect, hashlib.file_digest, hashlib.sha256

    def sql(*args, **kwargs):
        assert threading.get_ident() != main, "Activity opened SQL on GUI"
        observed.append("sql")
        return connect(*args, **kwargs)

    def hashed(*args, **kwargs):
        assert threading.get_ident() != main, "Activity hashed source on GUI"
        observed.append("hash")
        return digest(*args, **kwargs)

    def sha(*args, **kwargs):
        assert threading.get_ident() != main, "Activity hashed on GUI"
        observed.append("hash")
        return sha256(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", sql)
    monkeypatch.setattr(hashlib, "file_digest", hashed)
    monkeypatch.setattr(hashlib, "sha256", sha)
    return observed


def test_constructor_poll_snapshot_and_render_never_use_gui_sql_or_hash(activity, monkeypatch):
    app = QApplication.instance() or QApplication([])
    seen = no_gui_io(monkeypatch)
    service = ActivityReader(activity[0])
    assert seen == []
    report = worker(service.snapshot)
    assert seen and service.current(report)
    dialog = ResearchUpdatesDialog(service)
    dialog._poll.stop()
    dialog._check()
    dialog._render(report)
    assert dialog.trees[0].topLevelItemCount() == 1
    dialog.close()
    app.processEvents()


def test_actual_source_prepare_hashes_off_gui_and_delivery_only_focuses(actual_source, monkeypatch):
    window, service, row, moves, opens = actual_source
    seen = no_gui_io(monkeypatch)
    main = threading.get_ident()
    focus = window.reader_page.pdf.selection.focus
    window.reader_page.pdf.selection.focus = lambda anchor: (
        pytest.fail("Native focus left GUI") if threading.get_ident() != main else focus(anchor)
    )
    task = recorded_navigation.capture(window, service, row, locate=True)
    prepared = worker(lambda: task(Ticket()))
    assert "sql" in seen and "hash" in seen
    assert prepared.source_verified
    assert recorded_navigation.activate(window, service, prepared) == "located"
    assert moves == [row["resume"]["anchor"]] and not opens


@pytest.mark.parametrize(
    "change",
    [
        "binding",
        "note",
        "parent",
        "pdf",
        "epoch",
        "owner",
        "document",
        "source_generation",
        "source_closed",
        "resolver",
        "paper",
        "draft",
        "busy",
        "workspace",
    ],
)
def test_delayed_prepared_source_rejects_changed_context(actual_source, change):
    window, service, row, moves, opens = actual_source
    task = recorded_navigation.capture(window, service, row, locate=True)
    prepared = worker(lambda: task(Ticket()))
    reader = window.reader_page
    if change == "note":
        window.change_note("Newer note")
    elif change in {"binding", "parent"}:
        with closing(sqlite3.connect(service.path)) as conn, conn:
            if change == "binding":
                conn.execute("UPDATE paperfact_sync_identity SET device='other'")
            else:
                value = json.loads(
                    conn.execute(
                        "SELECT metadata FROM paperfact_sync_graph WHERE entity_type='paper'"
                    ).fetchone()[0]
                )
                value["incarnation"] = "new-parent"
                conn.execute(
                    "UPDATE paperfact_sync_graph SET metadata=? WHERE entity_type='paper'",
                    (json.dumps(value),),
                )
    elif change == "pdf":
        reader._active_document.path.write_bytes(b"changed source")
    elif change == "epoch":
        reader._qa_epoch += 1
    elif change == "owner":
        reader._highlight_owner = None
    elif change == "document":
        from dataclasses import replace

        reader._active_document = replace(reader._active_document)
    elif change == "source_generation":
        reader._active_document._owner.invalidate()
    elif change == "source_closed":
        reader._active_document._owner.close()
    elif change == "resolver":
        reader.paper._document_reader = object()
    elif change == "paper":
        reader.paper = SimpleNamespace(**vars(reader.paper))
    elif change == "draft":
        reader.note_edit.toPlainText = lambda: "Keep draft"
    elif change == "busy":
        reader.runner.busy = True
    else:
        service.current_path = lambda: service.path.with_name("other.sqlite")
    try:
        result = recorded_navigation.activate(window, service, prepared)
    except WorkspaceChanged:
        result = "changed"
    assert result in {"changed", "source", "drafts"}
    assert not moves and not opens


@pytest.mark.parametrize("change", ["binding", "note", "replace"])
def test_first_worker_never_accepts_changed_initial_witness(activity, change):
    path = activity[0]
    service = ActivityReader(path)
    inode = path.stat().st_ino
    if change == "replace":
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
    else:
        with closing(sqlite3.connect(path)) as conn, conn:
            if change == "binding":
                conn.execute("UPDATE paperfact_sync_identity SET device='new-device'")
            else:
                conn.execute("UPDATE notes SET body='New note'")
        assert path.stat().st_ino == inode
    with pytest.raises(WorkspaceChanged):
        worker(service.snapshot)


def test_sealed_results_cannot_be_mutated_or_rebound(activity):
    service = activity[1]
    proof = worker(service.snapshot)
    with pytest.raises(FrozenInstanceError):
        proof._json = "{}"
    rows = proof["continue"]
    rows[0]["paper_id"] = "other"
    assert proof["continue"][0]["paper_id"] == PAPER
    other = ActivityReader(activity[0])
    assert not other.current(proof)


def test_explicit_refresh_retains_binding_and_rejects_account_rebind(activity):
    path, service, *_ = activity
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE paperfact_sync_identity SET device='replacement-device'")
    assert not service.current()
    with pytest.raises(WorkspaceChanged):
        worker(service.snapshot)


def pump(app, predicate):
    import time

    from PySide6.QtTest import QTest

    deadline = time.monotonic() + 5
    while not predicate():
        app.processEvents()
        assert time.monotonic() < deadline
        QTest.qWait(1)
    app.processEvents()


def actual_dialog(window, service):
    return ResearchUpdatesDialog(
        service,
        prepare=lambda row, locate: recorded_navigation.capture(
            window, service, row, locate=locate
        ),
        activate=lambda prepared, locate: recorded_navigation.activate(
            window, service, prepared, locate=locate
        ),
        can_locate=lambda row: recorded_navigation.can_locate(window, row, database=service.path),
        blocked=lambda: recorded_navigation.blocked(window),
    )


def test_actual_dialog_read_poll_source_activation_and_delivery_are_gui_io_free(
    actual_source, monkeypatch
):
    window, service, row, moves, opens = actual_source
    app = QApplication.instance() or QApplication([])
    seen = no_gui_io(monkeypatch)
    dialog = actual_dialog(window, service)
    dialog.show()
    pump(app, lambda: not dialog.busy and dialog.trees[0].topLevelItemCount() > 0)
    dialog._check()
    tree = dialog.trees[0]
    tree.setCurrentItem(tree.topLevelItem(0))
    assert dialog.locate_button.isEnabled()
    assert dialog.open_selected(locate=True)
    for _ in range(10):
        assert not dialog.open_selected(locate=True) and not dialog.refresh()
    pump(app, lambda: dialog.disposed)
    assert moves == [row["resume"]["anchor"]] and not opens
    assert "sql" in seen and "hash" in seen


def test_actual_source_close_cancels_worker_and_keeps_drafts(actual_source, monkeypatch):
    window, service, _row, moves, opens = actual_source
    app = QApplication.instance() or QApplication([])
    dialog = actual_dialog(window, service)
    dialog.show()
    pump(app, lambda: not dialog.busy and dialog.trees[0].topLevelItemCount() > 0)
    tree = dialog.trees[0]
    tree.setCurrentItem(tree.topLevelItem(0))
    started, release = threading.Event(), threading.Event()
    from paper_daily import audit_inputs

    original = audit_inputs.verify_loaded_source

    def held(*args):
        started.set()
        assert release.wait(3)
        return original(*args)

    monkeypatch.setattr(audit_inputs, "verify_loaded_source", held)
    try:
        assert dialog.open_selected(locate=True)
        assert started.wait(1)
        window.reader_page.note_edit.toPlainText = lambda: "Unsent draft"
        dialog.close()
        assert dialog.busy and dialog._closing and not dialog.disposed
    finally:
        release.set()
    pump(app, lambda: dialog.disposed)
    assert window.reader_page.note_edit.toPlainText() == "Unsent draft"
    assert not moves and not opens


def test_source_semantic_change_during_hash_is_not_resealed(actual_source, monkeypatch):
    window, service, row, moves, opens = actual_source
    from paper_daily import audit_inputs

    original = audit_inputs.verify_loaded_source

    def changed(*args):
        verified = original(*args)
        window.change_note("Changed during source proof")
        return verified

    monkeypatch.setattr(audit_inputs, "verify_loaded_source", changed)
    task = recorded_navigation.capture(window, service, row, locate=True)
    with pytest.raises(WorkspaceChanged):
        worker(lambda: task(Ticket()))
    assert not moves and not opens


def test_accepted_activity_close_releases_modal_and_hides(actual_source):
    window, service, _row, _moves, _opens = actual_source
    app = QApplication.instance() or QApplication([])
    dialog = actual_dialog(window, service)
    dialog.show()
    pump(app, lambda: not dialog.busy and dialog.trees[0].topLevelItemCount() > 0)
    assert app.activeModalWidget() is dialog
    assert dialog.close()
    app.processEvents()
    assert dialog.disposed and not dialog.isVisible()
    assert app.activeModalWidget() is not dialog


def test_read_only_wal_open_does_not_invalidate_unchanged_database(tmp_path):
    path = tmp_path / "wal.sqlite"
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        conn.execute("CREATE TABLE fixture(value)")
        conn.commit()
    wal = path.with_name(path.name + "-wal")
    assert not wal.exists()
    service = ActivityReader(path)
    before = service._initial[0]
    report = worker(service.snapshot)
    assert report["available"] is False and service.current(report)
    assert service._observed[0] == before
    assert not wal.exists() or wal.stat().st_size == 0


def test_nonempty_wal_and_checkpoint_invalidate_existing_proof(tmp_path):
    path = tmp_path / "wal.sqlite"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE fixture(value)")
        conn.commit()
    service = ActivityReader(path)
    report = worker(service.snapshot)
    before_db = report._versions[0]
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("INSERT INTO fixture VALUES('new committed value')")
        writer.commit()
        assert path.with_name(path.name + "-wal").stat().st_size > 0
        assert not service.current(report)
        refreshed = worker(service.snapshot)
        assert refreshed._versions[0] == before_db
        assert service.current(refreshed)
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        assert not service.current(refreshed)
        assert service._observed == refreshed._versions  # No latest-version adoption.


def test_initial_same_inode_rebind_in_nonempty_wal_is_rejected(activity):
    path = activity[0]
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        service = ActivityReader(path)
        writer.execute("UPDATE paperfact_sync_identity SET device='rebound'")
        writer.commit()
        assert path.with_name(path.name + "-wal").stat().st_size > 0
        assert service._initial[0][1][1] == path.stat().st_ino
        with pytest.raises(WorkspaceChanged):
            worker(service.snapshot)
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        with pytest.raises(WorkspaceChanged):
            worker(service.snapshot)
        assert service.needs_reopen


def test_actual_ordinary_open_retains_legacy_io_boundary_and_no_research_write(
    actual_source, monkeypatch
):
    # Integration coverage of the existing reader; not a claim that ordinary open is GUI-I/O-free.
    from paper_daily import llm, store
    from paper_daily.desktop import main

    _captured, service, _row, _moves, _opens = actual_source
    document = _captured.reader_page._active_document
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(store, "DB_PATH", service.path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    monkeypatch.setattr(
        llm, "complete", lambda *a, **k: pytest.fail("Ordinary activity open called AI")
    )
    monkeypatch.setattr(
        main, "_spawn", lambda *a, **k: pytest.fail("Ordinary activity open spawned work")
    )
    window = main.MainWindow()
    paper = main.Paper(
        id=document.local_id,
        title="Actual recorded source",
        venue="Fixture",
        year=2026,
        award=None,
        paper_type=None,
        authors=[],
        abstract=None,
        citations=None,
        is_canon=False,
        pdf_url=None,
        page_url=None,
        arxiv_id=None,
        role="main",
        reason=None,
        state="pending",
        touched_at=None,
        _document_status=document,
        _document_reader=document._owner,
    )

    def research_state():
        with closing(sqlite3.connect(service.path)) as conn:
            return tuple(
                tuple(conn.execute(sql))
                for sql in (
                    "SELECT id,paper_id,body,anchor,created_at FROM notes ORDER BY id",
                    "SELECT * FROM queue ORDER BY paper_id",
                    "SELECT * FROM reading_log ORDER BY id",
                    "SELECT * FROM paperfact_sync_operations ORDER BY sequence",
                )
            )

    before = research_state()
    window.papers = [paper]
    window._recorded_navigation = True
    gui_reads = []
    connect = sqlite3.connect
    gui = threading.get_ident()

    def observed(*args, **kwargs):
        if threading.get_ident() == gui:
            gui_reads.append(True)
        return connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", observed)
    try:
        assert window.open_anywhere(paper.id)
        pump(app, lambda: not window.reader_page.document_runner.busy)
        assert window.reader_page.paper is paper
        assert window.reader_page._active_document.sha256 == document.sha256
        assert window.reader_page._qa_view_database == service.path
        assert paper.state == "pending" and paper.opened_at is None
        assert gui_reads  # This intentionally records the separately scoped maintenance gap.
        assert research_state() == before
    finally:
        window._recorded_navigation = False
        window.close()
        window.deleteLater()
        app.processEvents()


def test_rebind_between_initial_native_capture_and_first_sql_is_never_adopted(
    activity, monkeypatch
):
    path = activity[0]
    service = ActivityReader(path)
    original = service._begin

    def changed(conn, versions):
        with closing(sqlite3.connect(path)) as writer, writer:
            writer.execute("UPDATE paperfact_sync_identity SET device='during-initial-delay'")
        return original(conn, versions)

    monkeypatch.setattr(service, "_begin", changed)
    with pytest.raises(WorkspaceChanged):
        worker(service.snapshot)
    assert service.binding is None and service.needs_reopen
    monkeypatch.setattr(service, "_begin", original)
    with pytest.raises(WorkspaceChanged):
        worker(service.snapshot)
