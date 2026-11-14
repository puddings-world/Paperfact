"""An original absent from the backup and its note publish as one native action."""

import hashlib
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pymupdf
import pytest
from test_sync_device_recovery import dump
from test_sync_files import LOCAL, PAPER, drain
from test_sync_recovery_positioned_note import notes, source_file
from test_sync_recovery_positioned_note import positioned as positioned
from test_sync_recovery_target import attached
from test_sync_recovery_target import codec as codec
from test_sync_recovery_target import pair as pair
from test_workspace_dialog import app as app
from test_workspace_dialog import wait
from test_workspace_sync import Native

from paper_daily import note_positions, sync_bootstrap
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_note_copy as copy
from paper_daily import sync_recovery_target as target
from paper_daily.desktop.workspace_dialog import WorkspaceDialog
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_authority_backup import BackupCancelled
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_files import file_id
from paper_daily.sync_research import research_writer
from paper_daily.sync_source_files import FEATURE, _inspection_paths
from paper_daily.sync_source_files import publish as publish_source
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import SyncSession


@pytest.fixture
def group(positioned, pair, tmp_path):
    old, previous, _, path, old_note, service, _, _, token = positioned
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 60), "New post-backup source evidence")
        data = pdf.tobytes()
    sha = hashlib.sha256(data).hexdigest()
    original = tmp_path / "post-backup.pdf"
    original.write_bytes(data)
    with pymupdf.open(original) as pdf:
        anchor = note_positions.select(
            pdf, dict(p0=0, o0=0, p1=0, o1=2, document_hash=sha), sha)
    publish_source(
        old, PAPER, original, document_hash=sha,
        parent_incarnation=old_note["parents"][0]["incarnation"],
        store=pair[3].store, version_root=pair[3].root, request_id="post-backup-original",
    )
    operation = old.new_graph_operation("note", str(uuid4()), {
        **old_note["payload"], "body": "New unsent interpretation", "anchor": anchor})
    old.save(operation)
    source = candidates.prepare(old.journal.path, previous.snapshot, previous.workspace)
    change = next(row["change_id"] for row in source.page()["items"]
                  if row["operation_id"] == operation["operation_id"])
    return old, source, change, path, operation, service, sha, data, token


def prepare(group, request=None):
    _, source, change, path, *_ = group
    return copy.prepare(target.observe(source, path), change, request or str(uuid4()),
                        with_original=True)


def peer(path, service, tmp_path_factory):
    token = service.enroll("fresh-research", "original-group-peer")
    endpoint = "https://recovery.fixture.invalid"
    destination = tmp_path_factory.mktemp("note-original-peer") / "workspace"
    joining = SyncSession(path, transport_factory=lambda url: Native(url, service, []))
    joining.connect(endpoint, "fresh-research", "original-group-peer", token, Ticket())
    try:
        assert sync_bootstrap.join(joining, destination, Ticket())["state"] == "metadata_ready"
    finally:
        joining.disconnect()
    database = destination / "papers.db"
    receiving = SyncSession(database, transport_factory=lambda url: Native(url, service, []))
    receiving.connect(endpoint, "fresh-research", "original-group-peer", token, Ticket())
    try:
        assert receiving.prepare_offline([LOCAL], Ticket())["attachments"]["failed"] == 0
    finally:
        receiving.disconnect()
    return database


def test_missing_backup_original_and_note_publish_together_and_reach_native_peer(
    group, tmp_path_factory,
):
    old, source, change, path, operation, service, sha, data, token = group
    identity = file_id(PAPER, FEATURE, sha)
    before = dump(old.journal.path)
    with closing(_readonly_connection(path)) as conn:
        assert desired_file(conn, identity) is None
    request = str(uuid4())
    plan = prepare(group, request)
    assert dump(old.journal.path) == before and attached(path).journal.pending() == []
    first = plan.apply()
    assert first["applied"]
    client = attached(path)
    pending = client.journal.pending()
    assert [op["entity_type"] for op in pending] == ["research_file", "note"]
    assert pending[0]["entity_id"] == identity and pending[0]["parents"] == pending[1]["parents"]
    assert pending[1]["payload"] == operation["payload"]
    assert source_file(path, sha, len(data)).read_bytes() == data
    assert not plan.apply()["applied"]
    assert not copy.prepare(target.observe(source, path), change, request,
                            with_original=True).apply()["applied"]
    with closing(_readonly_connection(path)) as conn:
        store, root = _inspection_paths(conn)
        assert conn.execute("SELECT COUNT(*) FROM research_document_desired").fetchone()[0] == 0
    transfer = FileTransfers(client, BlobStore(store.root), service,
                             origin="https://recovery.fixture.invalid", token=token,
                             version_root=root)
    try:
        drain(lambda: transfer.upload(pending[0]), "uploaded")
        synced = client.sync_once(service, token, prepare_push=transfer.ready_to_push)
        assert synced["pending"] == synced["conflicts"] == 0
    finally:
        transfer.close()
    other = peer(path, service, tmp_path_factory)
    assert notes(other) == notes(path)
    assert source_file(other, sha, len(data)).read_bytes() == data
    assert dump(old.journal.path) == before
    client.save(client.new_graph_operation("note", first["entity_id"], {
        **operation["payload"], "body": "Later private edit"}))
    client.save(client.new_graph_operation("research_file", identity, {}, action="delete"))
    later = dump(path)
    assert not prepare(group, request).apply()["applied"]
    assert dump(path) == later and notes(path)[-1][0] == "Later private edit"
    with pytest.raises(ValueError, match="explicit source restoration"):
        prepare(group)
    assert dump(path) == later


@pytest.mark.parametrize("failure", ["exception", "cancel"])
def test_failure_after_original_write_rolls_back_both_and_retries_once(group, monkeypatch, failure):
    _, _, _, path, _, _, sha, _, _ = group
    plan = prepare(group)
    identity = file_id(PAPER, FEATURE, sha)
    activate, written = CaptureConnection._activate, []

    def failing(conn):
        activate(conn)

        def write(conn, operation):
            research_writer(conn, operation)
            written.append(operation["entity_type"])
            if operation["entity_type"] == "note" and failure == "exception":
                raise RuntimeError("simulated second-child failure")

        conn._capture_client.writer = write

    monkeypatch.setattr(CaptureConnection, "_activate", failing)
    before = dump(path)
    with pytest.raises(RuntimeError if failure == "exception" else BackupCancelled):
        plan.apply(cancelled=lambda: failure == "cancel" and "note" in written)
    assert written == ["research_file", "note"] and dump(path) == before
    assert attached(path).journal.pending() == []
    with closing(_readonly_connection(path)) as conn:
        assert desired_file(conn, identity) is None
    monkeypatch.setattr(CaptureConnection, "_activate", activate)
    assert plan.apply()["applied"]
    assert len(attached(path).journal.pending()) == 2 and len(notes(path)) == 2


def test_changed_old_original_and_forged_include_choice_never_publish(group):
    old, _, _, path, _, _, sha, data, _ = group
    plan = prepare(group)
    before = dump(path)
    with pytest.raises(ValueError, match="prepared note-copy decision"):
        replace(plan, with_original=False).apply()
    original = source_file(old.journal.path, sha, len(data))
    original.write_bytes(data + b"\n% changed old original\n")
    with pytest.raises((ValueError, OSError)):
        plan.apply()
    assert dump(path) == before and attached(path).journal.pending() == []
    original.write_bytes(data)
    assert plan.apply()["applied"]


def test_desktop_explains_original_and_cancellation_has_no_cache_or_research_write(
    group, app, monkeypatch,
):
    from PySide6.QtWidgets import QMessageBox

    from paper_daily.document_reader import register_document_paths

    old, source, _change, path, operation, _, sha, data, _ = group
    client = attached(path)
    client.save(client.new_graph_operation("paper_document", PAPER, dict(
        paper_id=PAPER, sha256=sha, size=len(data), media_type="application/pdf")))
    with client.journal.transaction() as conn:
        store, _ = _inspection_paths(conn)
        register_document_paths(conn, workspace_id="fresh-research", blob_root=store.root,
                                projection_root=path.parent / "reader-documents",
                                legacy_root=path.parent / "pdf")
    owner = WorkspaceDialog(old.journal.path, language="en")
    owner.show()
    try:
        wait(app, lambda: owner._ready and not owner.busy)
        owner.task_tabs.setCurrentIndex(2)
        owner.device_review.disclosure.setChecked(True)
        ui = owner.device_review.changes
        assert owner.device_review.inspect(source.snapshot)
        wait(app, lambda: not owner.busy)
        assert ui.load(path.parent)
        wait(app, lambda: not owner.busy)
        change = next(row["change_id"] for row in ui.page["items"]
                      if row["operation_id"] == operation["operation_id"])
        for index in range(ui.rows.count()):
            ui.rows.setCurrentRow(index)
            if ui.selected() == change:
                break
        assert ui.selected() == change
        before = dump(path)
        with closing(_readonly_connection(path)) as conn:
            store, _ = _inspection_paths(conn)
            cache_before = sorted(str(p) for p in (store.root / "objects").rglob("*"))
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        assert ui.plan.with_original and ui.copy_button.text() == "Copy note and original"
        assert "PDF" in ui.notice.text()
        assert dump(path) == before
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
        ui.copy_button.click()
        assert not owner.busy and dump(path) == before
        assert sorted(str(p) for p in (store.root / "objects").rglob("*")) == cache_before
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        pending = attached(path).journal.pending()
        assert [op["entity_type"] for op in pending] == ["paper_document", "research_file", "note"]
        assert len(notes(path)) == 2
        with closing(_readonly_connection(path)) as conn:
            assert desired_file(conn, file_id(PAPER, FEATURE, sha)) is not None
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()
