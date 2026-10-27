import hashlib
import sqlite3
import zipfile

import pytest
from test_sync_recovery import blob
from test_sync_recovery import research as research_fixture

from paper_daily import sync_recovery
from paper_daily.document_reader import register_document_paths
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_service import ReferenceService
from paper_daily.workspace_service import (
    Cancelled,
    SnapshotChanged,
    Ticket,
    WorkspaceChanged,
    WorkspaceService,
    location_policy,
)

research = research_fixture


@pytest.fixture
def workspace(research):
    service = WorkspaceService(research[0])
    service.status()
    return service


def test_status_is_read_only_and_never_claims_remote_completion(research):
    path, client, *_ = research
    before = path.read_bytes()
    status = WorkspaceService(path).status()
    assert status["counts"]["papers"] == {"value": 1, "capped": False}
    assert status["sync"]["pending"]["value"] == len(client.journal.pending())
    assert status["sync"]["awaiting"]["value"] == 0
    assert not status["files"]["registered"]
    assert "last_synced" not in status and "synced" not in status
    assert path.read_bytes() == before


def test_acknowledged_not_received_is_separate(research, tmp_path):
    path, client, *_ = research
    server = ReferenceService(tmp_path / "server.sqlite")
    token = server.enroll("workspace", "origin-device")
    op = client.journal.pending()[0]
    event = server.push(token, op)
    client.journal.acknowledge(op["operation_id"], event["sequence"])
    result = WorkspaceService(path).status()["sync"]
    assert result["awaiting"]["value"] == 1
    assert result["pending"]["value"] == len(client.journal.pending())


def test_legacy_location_policy_and_missing_database(tmp_path):
    assert (
        location_policy(tmp_path, env={"PAPERFACT_DATA": str(tmp_path)}, frozen=False)
        == "PAPERFACT_DATA"
    )
    assert (
        location_policy(tmp_path, env={"PAPER_DAILY_DATA": str(tmp_path)}, frozen=False)
        == "PAPER_DAILY_DATA"
    )
    assert (
        location_policy(
            tmp_path,
            env={"PAPERFACT_DATA": str(tmp_path / "other"), "PAPER_DAILY_DATA": str(tmp_path)},
            frozen=False,
        )
        == "explicit"
    )
    with pytest.raises(FileNotFoundError):
        WorkspaceService(tmp_path / "absent.db")
    assert not (tmp_path / "absent.db").exists()


def test_complete_backup_and_detached_restore_preserve_content(workspace, research, tmp_path):
    before = research[1].journal.pending()
    target = tmp_path / "backup.zip"
    made = workspace.backup(target, Ticket())
    manifest = workspace.inspect(target, Ticket())
    assert manifest == made["manifest"]
    result = workspace.restore(target, tmp_path / "restored", manifest["backup_id"], Ticket())
    assert result["detached"]
    assert research[1].journal.pending() == before
    with sqlite3.connect(tmp_path / "restored/papers.db") as conn:
        assert conn.execute("SELECT body FROM notes").fetchall() == [("Saved research",)]
        assert conn.execute("SELECT name FROM lists").fetchall() == [("Recovery route",)]
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert "paperfact_sync_identity" not in names
        assert "research_capture_binding" not in names
        assert conn.execute("SELECT count(*) FROM recovery_records").fetchone()[0] > 0


def with_pdf(research, tmp_path):
    source, current, _, paper_id = research
    store = BlobStore(tmp_path / "objects-owned")
    data = b"%PDF-1.7\nfixture original bytes\n%%EOF"
    manifest = blob(store, data)
    operation = current.new_graph_operation(
        "paper_document",
        paper_id,
        {
            "paper_id": paper_id,
            "sha256": manifest.sha256,
            "size": manifest.size,
            "media_type": "application/pdf",
        },
    )
    current.save(operation)
    with sqlite3.connect(source) as conn:
        conn.execute("BEGIN")
        register_document_paths(
            conn,
            workspace_id="workspace",
            blob_root=store.root,
            projection_root=tmp_path / "projections",
            legacy_root=source.parent,
        )
    return store, manifest, data


def test_registered_pdf_bytes_are_verified_backed_up_and_restored(research, tmp_path):
    store, manifest, data = with_pdf(research, tmp_path)
    service = WorkspaceService(research[0])
    status = service.status()
    assert status["files"]["verified_bytes"] == len(data)
    assert status["files"]["unavailable"] == 0
    output = tmp_path / "with-pdf.zip"
    service.backup(output, Ticket())
    preview = service.inspect(output, Ticket())
    service.restore(output, tmp_path / "restored", preview["backup_id"], Ticket())
    restored = tmp_path / "restored/objects" / manifest.sha256
    assert restored.read_bytes() == data
    assert hashlib.sha256(restored.read_bytes()).hexdigest() == manifest.sha256
    assert store.verified_path(manifest).read_bytes() == data


def test_corrupt_file_status_and_missing_closure_refuse_backup(research, tmp_path):
    store, manifest, data = with_pdf(research, tmp_path)
    service = WorkspaceService(research[0])
    service.status()
    store.verified_path(manifest).write_bytes(b"x" * len(data))
    assert service.status()["files"]["unavailable"] == 1
    output = tmp_path / "broken.zip"
    with pytest.raises(ValueError):
        service.backup(output, Ticket())
    assert not output.exists()


def test_status_verification_budget_is_explicit(research, tmp_path, monkeypatch):
    with_pdf(research, tmp_path)
    monkeypatch.setattr("paper_daily.workspace_service.VERIFY_BYTES", 1)
    result = WorkspaceService(research[0]).status()["files"]
    assert result["partial"] and result["verified_bytes"] == 0


@pytest.mark.parametrize("action", ["cancel", "switch", "write", "replace"])
def test_backup_late_changes_never_publish(workspace, tmp_path, monkeypatch, action):
    original = sync_recovery.create
    ticket = Ticket()
    active = [workspace.path]
    workspace.current_path = lambda: active[0]

    def during(*args, **kwargs):
        result = original(*args, **kwargs)
        if action == "cancel":
            ticket.cancel()
        elif action == "switch":
            active[0] = tmp_path / "other.db"
        elif action == "write":
            with sqlite3.connect(workspace.path) as conn:
                conn.execute("UPDATE lists SET name='Newer live name'")
        else:
            old = workspace.path.with_suffix(".old")
            workspace.path.rename(old)
            workspace.path.write_bytes(old.read_bytes())
        return result

    monkeypatch.setattr(sync_recovery, "create", during)
    destination = tmp_path / "cancelled.zip"
    with pytest.raises((Cancelled, WorkspaceChanged, SnapshotChanged, PermissionError)):
        workspace.backup(destination, ticket)
    assert not destination.exists()
    assert not list(tmp_path.glob(".paperfact-backup-ui-*"))


def test_sidecar_change_during_snapshot_requires_retry(workspace, tmp_path, monkeypatch):
    fingerprints = iter([b"before", b"after"])
    monkeypatch.setattr(workspace, "_sidecars", lambda: next(fingerprints))
    with pytest.raises(SnapshotChanged):
        workspace.backup(tmp_path / "out.zip", Ticket())
    assert not (tmp_path / "out.zip").exists()


def test_failed_backup_can_retry_and_existing_output_is_preserved(workspace, tmp_path, monkeypatch):
    target = tmp_path / "backup.zip"
    original = sync_recovery.create
    monkeypatch.setattr(
        sync_recovery, "create", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    )
    with pytest.raises(OSError):
        workspace.backup(target, Ticket())
    assert not target.exists()
    monkeypatch.setattr(sync_recovery, "create", original)
    workspace.backup(target, Ticket())
    before = target.read_bytes()
    with pytest.raises(ValueError):
        workspace.backup(target, Ticket())
    assert target.read_bytes() == before


def test_restore_requires_exact_inspected_bytes_and_new_destination(workspace, tmp_path):
    package = tmp_path / "backup.zip"
    workspace.backup(package, Ticket())
    preview = workspace.inspect(package, Ticket())
    with zipfile.ZipFile(package, "a") as archive:
        archive.comment = b"A valid but different archive after preview"
    assert sync_recovery.inspect(package) == preview
    with pytest.raises(ValueError, match="changed"):
        workspace.restore(package, tmp_path / "restored", preview["backup_id"], Ticket())
    assert not (tmp_path / "restored").exists()
    workspace.inspect(package, Ticket())
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep.txt").write_text("original")
    with pytest.raises(ValueError):
        workspace.restore(package, existing, preview["backup_id"], Ticket())
    assert (existing / "keep.txt").read_text() == "original"


def test_restore_cancel_after_rebuild_removes_only_own_stage(workspace, tmp_path, monkeypatch):
    package = tmp_path / "backup.zip"
    workspace.backup(package, Ticket())
    preview = workspace.inspect(package, Ticket())
    original = sync_recovery.restore_detached
    ticket = Ticket()

    def cancel_after(*args, **kwargs):
        result = original(*args, **kwargs)
        ticket.cancel()
        return result

    monkeypatch.setattr(sync_recovery, "restore_detached", cancel_after)
    with pytest.raises(Cancelled):
        workspace.restore(package, tmp_path / "restored", preview["backup_id"], ticket)
    assert package.is_file() and workspace.path.is_file()
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".paperfact-restore-ui-*"))


def test_ticket_cancel_after_publish_does_not_lie_about_success():
    ticket = Ticket()
    results = []
    ticket.publish(lambda: results.append("published"))
    ticket.cancel()
    assert results == ["published"] and ticket.published and not ticket.cancelled


@pytest.mark.parametrize("name", ["", "source/nested.zip", "source/papers.db"])
def test_unsafe_destinations_leave_workspace_untouched(workspace, tmp_path, name):
    with pytest.raises(ValueError):
        workspace.backup(tmp_path / name if name else "", Ticket())


def test_rebound_database_does_not_reuse_prior_file_registration(workspace):
    with sqlite3.connect(workspace.path) as conn:
        conn.execute("UPDATE research_sync_binding SET workspace='other-workspace'")
    with pytest.raises(WorkspaceChanged):
        workspace.status()


def test_replaced_database_before_backup_preserves_replacement(workspace, tmp_path):
    import gc

    gc.collect()  # Fixture sqlite context managers commit, but release handles at GC.
    old = workspace.path.with_suffix(".old")
    workspace.path.rename(old)
    workspace.path.write_bytes(old.read_bytes())
    replacement = workspace.path.read_bytes()
    with pytest.raises(WorkspaceChanged):
        workspace.backup(tmp_path / "out.zip", Ticket())
    assert workspace.path.read_bytes() == replacement
    assert not (tmp_path / "out.zip").exists()


def test_unavailable_registered_store_is_unknown_not_zero_verified(research, tmp_path):
    store, _, _ = with_pdf(research, tmp_path)
    import gc

    gc.collect()
    (store.root / "index.sqlite").unlink()
    result = WorkspaceService(research[0]).status()
    assert result["files"]["unavailable"] is None
    assert result["files"]["partial"] and result["files"]["error"] == "unavailable"
    assert result["counts"]["papers"]["value"] == 1


def test_real_retained_conflict_is_counted_separately(research, tmp_path):
    from test_sync_operations import client as make_client

    path, first, *_ = research
    note = next(op for op in first.journal.pending() if op["entity_type"] == "note")
    authority = ReferenceService(tmp_path / "authority.sqlite")
    a = authority.enroll("workspace", "origin-device")
    first.sync_once(authority, a)
    second = make_client(tmp_path / "second.sqlite", "second")
    b = authority.enroll("workspace", "second")
    second.sync_once(authority, b)
    for current, body in ((first, "first edit"), (second, "second edit")):
        operation = current.new_graph_operation(
            "note", note["entity_id"], {**note["payload"], "body": body}
        )
        current.save(operation)
    first.sync_once(authority, a)
    second.sync_once(authority, b)
    result = WorkspaceService(second.journal.path).status()["sync"]
    assert result["conflicts"] == {"value": 1, "capped": False}
    assert result["pending"]["value"] == result["awaiting"]["value"] == 0


def test_counts_expose_cap_instead_of_false_exact_total(research, monkeypatch):
    with sqlite3.connect(research[0]) as conn:
        conn.execute(
            "INSERT INTO lists(id,name,note,created_at) VALUES('extra','Extra','','2026-01-01')"
        )
    monkeypatch.setattr("paper_daily.workspace_service.COUNT_LIMIT", 1)
    result = WorkspaceService(research[0]).status()
    assert result["counts"]["lists"] == {"value": 1, "capped": True}


def test_valid_blob_read_access_time_change_is_not_corruption(research, tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    store, manifest, data = with_pdf(research, tmp_path)
    target = store.root / "objects" / manifest.sha256
    original = Path.stat
    calls = []

    def changed_access(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path != target:
            return info
        calls.append(1)
        fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
        fields["st_atime_ns"] += len(calls)
        fields["st_atime"] += len(calls)
        return SimpleNamespace(**fields)

    monkeypatch.setattr(Path, "stat", changed_access)
    result = WorkspaceService(research[0]).status()["files"]
    assert len(calls) >= 2
    assert result["verified_bytes"] == len(data)
    assert result["unavailable"] == 0
