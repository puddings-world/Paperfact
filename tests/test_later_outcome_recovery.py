"""Actual backup/detached restore/editable receiver, without old native authority."""

import hashlib
import json
import zipfile
from contextlib import closing
from uuid import uuid4

import pytest
from test_later_outcome_packages import exported
from test_research_generation import workspace as workspace

from paper_daily import later_outcomes as outcomes
from paper_daily import research_generation as generation
from paper_daily import sync_recovery
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.sync_blobs import BlobStore
from paper_daily.workspace_enrollment import EnrollmentService


def managed_workspace(workspace):
    """A genuine managed primary fixture, preserving legacy-backup negative separately."""
    from paper_daily.document_reader import from_workspace, register_document_paths
    from paper_daily.sync_document_actions import stage_file
    from paper_daily.sync_documents import bind_verified_document, desired_document, verify_document
    from paper_daily.sync_file_transfers import FileTransfers
    from paper_daily.sync_operations import ResearchOperations

    database, client, document = workspace
    blobs = BlobStore(database.parent / "blobs")

    class InertTransport:
        def __getattr__(self, name):
            if name == "base_url":
                raise AttributeError(name)
            raise AssertionError("Fixture source setup contacted transport")

    transfers = FileTransfers(
        client, blobs, InertTransport(), origin="https://fixture.invalid", token=None
    )
    transfers.close()
    manifest = stage_file(blobs, document.path)
    with client.journal.transaction() as conn:
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
        ).fetchone()[0]
    ResearchOperations(client).attach_document(
        portable, manifest, store=blobs, request_id="fixture-primary-a"
    )
    with client.journal.transaction() as conn:
        target = desired_document(conn, portable)
    verified = verify_document(blobs, target)
    with client.journal.transaction() as conn:
        assert bind_verified_document(conn, target, verified)
        register_document_paths(
            conn,
            workspace_id=client.journal.workspace_id,
            blob_root=blobs.root,
            projection_root=database.parent / "reader-documents",
            legacy_root=document.path.parent,
        )
    document.path.unlink()  # Remove only the fixture's obsolete alias, not a product migration.
    current = from_workspace(database).resolve("paper")
    assert current.managed and current.available and current.sha256 == document.sha256
    return database, client, current


@pytest.mark.parametrize("available", [False, True])
def test_actual_backup_restore_and_fresh_editable_receiver(
    workspace, monkeypatch, tmp_path, available
):
    if available and workspace[1] is not None:
        workspace = managed_workspace(workspace)
    database, document, tables, source_manifest, output, proof = exported(
        workspace, monkeypatch, available
    )
    client = workspace[1]
    package = tmp_path / "original.zip"
    blobs = BlobStore(database.parent / "blobs") if client and available else None
    before = database.read_bytes()
    manifest = sync_recovery.create(database, package, blob_store=blobs)
    assert database.read_bytes() == before
    assert any(row["name"] == outcomes.TABLE for row in manifest["tables"])
    restored = tmp_path / "detached"
    sync_recovery.restore_detached(package, restored)
    service = RecoveryAdoptionService(restored / "papers.db")
    inspection = service.inspect()
    assert inspection.report["supported"], inspection.report["blockers"]
    result = service.prepare(
        inspection,
        tmp_path / "editable",
        backup_output=tmp_path / "editable.zip",
        request_id=str(uuid4()),
    )
    assert (
        result["status"] == "prepared_for_review"
        and not result["adopted"]
        and not result["uploaded"]
    )
    with closing(generation._connect(result["database"])) as conn:
        row = dict(conn.execute("SELECT * FROM paper_later_outcomes").fetchone())
        assert json.loads(row["body_json"]) == json.loads(tables[outcomes.TABLE][0]["body_json"])
        assert row["document_hash"] == (document.sha256 if available else None)
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_compound_requests'"
        ).fetchone()
    sync_recovery.inspect(result["backup"])


@pytest.mark.parametrize("available", [False, True])
def test_actual_unbound_first_enrollment_reports_supported_typed_empty(
    workspace, monkeypatch, tmp_path, available
):
    database, document, tables, source_manifest, output, proof = exported(
        workspace, monkeypatch, available
    )
    service = EnrollmentService(database)
    plan = service.plan(pdfs={"paper": document.path} if available else {})
    if workspace[1] is not None:
        assert not plan["supported"]  # Enrolled migration is a different operation.
        return
    assert plan["supported"], plan["blockers"]
    assert plan["archived_history_by_protocol"]["research_compound_requests"] == 1
    if available:
        assert plan["original_source_count"] >= 1


def test_unmanaged_legacy_primary_backup_preserves_document_and_restores(
    workspace, monkeypatch, tmp_path
):
    database, document, tables, source_manifest, output, proof = exported(
        workspace, monkeypatch, True
    )
    package = tmp_path / "unmanaged.zip"
    before = database.read_bytes()
    content = document.path.read_bytes()
    manifest = sync_recovery.create(
        database, package, blob_store=BlobStore(database.parent / "blobs")
    )
    assert manifest["blobs"] and sync_recovery.inspect(package) == manifest
    with zipfile.ZipFile(package) as archive:
        assert archive.read("objects/" + hashlib.sha256(content).hexdigest()) == content
    sync_recovery.restore_detached(package, tmp_path / "restored")
    assert (tmp_path / "restored/papers.db").is_file()
    assert document.path.read_bytes() == content
    assert database.read_bytes() == before


@pytest.mark.parametrize("available", [False, True])
def test_actual_first_enrollment_keeps_recorded_body_and_fresh_receiver_source(
    workspace, monkeypatch, tmp_path, available
):
    from pathlib import Path

    from paper_daily.document_reader import from_workspace
    from paper_daily.research_lifecycle import parent_lifecycle
    from paper_daily.workspace_enrollment import EnrollmentBlocked

    database, document, tables, _manifest, _output, _proof = exported(
        workspace, monkeypatch, available
    )
    service = EnrollmentService(database)
    before = database.read_bytes()
    outputs = tmp_path.parent / (tmp_path.name + "-outputs")
    outputs.mkdir()
    if workspace[1] is not None:
        with pytest.raises(EnrollmentBlocked):
            service.prepare(
                outputs / "enrolled-copy",
                backup_output=outputs / "enrolled-backup.zip",
                request_id=str(uuid4()),
                pdfs={"paper": document.path} if available else {},
            )
        assert database.read_bytes() == before
        return
    result = service.prepare(
        outputs / "enrolled-copy",
        backup_output=outputs / "enrolled-backup.zip",
        request_id=str(uuid4()),
        pdfs={"paper": document.path} if available else {},
    )
    destination = Path(result["database"])
    assert (
        result["status"] == "prepared_for_review"
        and not result["adopted"]
        and not result["uploaded"]
    )
    assert database.read_bytes() == before and destination != database
    with closing(generation._connect(destination)) as conn:
        row = dict(conn.execute("SELECT * FROM paper_later_outcomes").fetchone())
        assert json.loads(row["body_json"]) == json.loads(tables[outcomes.TABLE][0]["body_json"])
        assert parent_lifecycle(conn, "paper", "paper")
        assert outcomes.settled(conn, "paper")
    if available:
        resolved = from_workspace(destination).resolve("paper")
        assert resolved.available and resolved.sha256 == document.sha256
    sync_recovery.inspect(result["backup"])


def test_enrollment_source_cancellation_during_actual_byte_read_is_cancelled(
    workspace, monkeypatch
):
    from paper_daily import later_outcome_packages as packages
    from paper_daily import local_source_owners as owners
    from paper_daily.workspace_service import Cancelled, Ticket

    database, _document, tables, _manifest, _output, _proof = exported(workspace, monkeypatch, True)
    ticket = Ticket()
    original = owners._read_pdf
    reads = []

    def cancelled_read(path, sha, size, cancelled):
        reads.append(path)
        ticket.cancel()
        return original(path, sha, size, cancelled)

    monkeypatch.setattr(owners, "_read_pdf", cancelled_read)
    before = database.read_bytes()
    selected = {}
    with closing(generation._connect(database)) as conn, pytest.raises(Cancelled):
        packages.add_enrollment_sources(conn, tables[outcomes.TABLE], selected, ticket=ticket)
    assert len(reads) == 1 and selected == {} and database.read_bytes() == before


def test_recovery_source_cancellation_during_actual_byte_read_is_cancelled(
    workspace, monkeypatch, tmp_path
):
    from paper_daily import later_outcome_recovery as recovery
    from paper_daily import local_source_owners as owners
    from paper_daily.workspace_service import Cancelled, Ticket

    if workspace[1] is not None:
        workspace = managed_workspace(workspace)
    database, _document, _tables, _manifest, _output, _proof = exported(
        workspace, monkeypatch, True
    )
    archive = tmp_path / "cancel-backup.zip"
    sync_recovery.create(
        database, archive, blob_store=BlobStore(database.parent / "blobs") if workspace[1] else None
    )
    detached = tmp_path / "cancel-detached"
    sync_recovery.restore_detached(archive, detached)
    service = RecoveryAdoptionService(detached / "papers.db")
    inspection = service.inspect()
    assert inspection.report["supported"], inspection.report["blockers"]
    ticket, reads = Ticket(), []
    real_stage, original = recovery.stage, owners._read_pdf

    def stage(*args, **kwargs):
        def cancelled_read(path, sha, size, cancelled):
            reads.append(path)
            ticket.cancel()
            return original(path, sha, size, cancelled)

        monkeypatch.setattr(owners, "_read_pdf", cancelled_read)
        return real_stage(*args, **kwargs)

    monkeypatch.setattr(recovery, "stage", stage)
    before = (detached / "papers.db").read_bytes()
    with pytest.raises(Cancelled):
        service.prepare(
            inspection,
            tmp_path / "cancel-editable",
            backup_output=tmp_path / "cancel-editable.zip",
            request_id=str(uuid4()),
            ticket=ticket,
        )
    assert len(reads) == 1 and (detached / "papers.db").read_bytes() == before
    assert not (tmp_path / "cancel-editable").exists()
    assert not (tmp_path / "cancel-editable.zip").exists()
