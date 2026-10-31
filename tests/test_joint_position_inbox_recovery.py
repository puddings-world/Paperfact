"""One complete workspace must preserve position A, primary B and Inbox history."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
from test_inbox_union_integration import (
    archived_evidence,
    assert_content,
    canonical_rows,
)
from test_inbox_union_integration import combined as combined_fixture
from test_queue_pin_packages import package as package_fixture
from test_reading_positions import pdf_bytes, records, view
from test_research_inbox import payload, rows, saved

from paper_daily import (
    document_reader,
    enrollment_history,
    inbox_content,
    manual_highlight_ops,
    recovery_provenance,
    source_snapshots,
    store,
    sync_artifacts,
    sync_recovery,
    sync_source_files,
)
from paper_daily import reading_position_ops as operations
from paper_daily import reading_positions as positions
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.research_inbox import Inbox
from paper_daily.sync_client import SyncClient
from paper_daily.sync_document_actions import stage_file
from paper_daily.sync_documents import bind_verified_document, desired_document, verify_document
from paper_daily.sync_journal import Journal
from paper_daily.sync_operations import ResearchOperations
from paper_daily.sync_projection import read_manifest
from paper_daily.sync_research import research_order_writer, research_writer
from paper_daily.workspace_enrollment import EnrollmentService

combined = combined_fixture
package = package_fixture
STAMP = "2026-10-31T08:12:34.123456+00:00"


def identity(database):
    with closing(sqlite3.connect(database)) as conn:
        return conn.execute("SELECT workspace,device FROM paperfact_sync_identity").fetchone()


def portable(database, paper):
    with closing(sqlite3.connect(database)) as conn:
        return conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (paper,)
        ).fetchone()[0]


def pdf_text(data):
    with pymupdf.open(stream=data, filetype="pdf") as document:
        return document.page_count, "\n".join(page.get_text() for page in document)


def exact_primary(database, paper, expected):
    resolved = document_reader.resolve_document(paper, db_path=database)
    assert resolved.available, resolved.reason
    assert resolved.path.read_bytes() == expected
    assert resolved.sha256 == hashlib.sha256(expected).hexdigest()
    return resolved


def attach_primary(database, paper, selected):
    """Use the actual explicit action and verified activation, not fabricated targets."""
    workspace, device = identity(database)
    client = SyncClient(
        Journal(database, workspace_id=workspace, device_id=device),
        research_writer,
        order_writer=research_order_writer,
    )
    reader = document_reader.from_workspace(database)
    with client.journal.transaction() as conn:
        blob_store, _version_root = sync_artifacts.paths(conn)
    manifest = stage_file(blob_store, selected)
    owner = portable(database, paper)
    ResearchOperations(client).attach_document(
        owner, manifest, store=blob_store, request_id="joint-primary-B"
    )
    with client.journal.transaction() as conn:
        target = desired_document(conn, owner)
    verified = verify_document(blob_store, target)
    with client.journal.transaction() as conn:
        assert bind_verified_document(conn, target, verified)
    reader.invalidate()


def archive_bytes(package, original, current):
    manifest = sync_recovery.inspect(package)
    with zipfile.ZipFile(package) as archive:
        for data, count, label in (
            (original, 4, "Joint original A"),
            (current, 2, "Joint primary B"),
        ):
            digest = hashlib.sha256(data).hexdigest()
            assert any(
                row["sha256"] == digest and row["size"] == len(data) for row in manifest["blobs"]
            )
            restored = archive.read("objects/" + digest)
            assert restored == data
            pages, text = pdf_text(restored)
            assert pages == count and label in text
    return manifest


def raw_position_requests(provenance):
    """Select exact rows only after maintained complete/nested closure validation."""
    recovery_provenance.validate_groups(provenance)
    result = []

    def select(row, depth=0, ancestors=frozenset()):
        if depth >= recovery_provenance.MAX_DEPTH or row["record_id"] in ancestors:
            raise ValueError("Recovered request provenance is cyclic or too deep")
        value = recovery_provenance.decode(row)
        if value["kind"] != "row":
            return
        if value["table"] == positions.RECEIPTS:
            operations.validate_receipt(value["record"])
            result.append(value["record"])
        elif value["table"] == recovery_provenance.TABLE:
            select(value["record"], depth + 1, ancestors | {row["record_id"]})

    for row in provenance:
        select(row)
    return result


@pytest.mark.parametrize(
    "unbound_position_first", [False, True], ids=["enrolled", "unbound-to-enrolled"]
)
def test_actual_joint_position_original_and_inbox_survive_two_complete_recovery_cycles(
    combined, tmp_path, monkeypatch, unbound_position_first
):
    original = combined
    paper = original.pin_owner
    original_bytes = pdf_bytes(4, "Joint original A")
    current_bytes = pdf_bytes(2, "Joint primary B")
    digest = hashlib.sha256(original_bytes).hexdigest()
    source_pdf = original.database.parent / "pdf" / (paper + ".pdf")
    source_pdf.parent.mkdir()
    source_pdf.write_bytes(original_bytes)

    if unbound_position_first:
        intent = operations.prepare(
            operations.capture(view(original.database, source_pdf, paper=paper)),
            4,
            method="entered",
            recorded_at="2026-10-30T10:00:00+00:00",
        )
        assert operations.save(intent)["status"] == "saved"
        (receipt,) = source_snapshots.list_owned(original.database)
        assert json.loads(receipt["owner_json"])["format"] == "paperfact.position-source-owner.v2"
        source_pdf.write_bytes(current_bytes)

    initial = EnrollmentService(original.database).prepare(
        tmp_path / "joint-live",
        backup_output=tmp_path / "initial-independent.zip",
        request_id=str(uuid4()),
        pdfs={paper: source_pdf},
    )
    database = Path(initial["database"])
    monkeypatch.setattr(store, "DB_PATH", database)
    workspace, device = identity(database)
    owner = manual_highlight_ops.capture_owner(database, paper)
    if unbound_position_first:
        with closing(sqlite3.connect(database)) as conn:
            located = sync_source_files.inspectable(conn, portable(database, paper), digest)
        assert located is not None and located.read_bytes() == original_bytes
        actual = manual_highlight_ops.load(owner, located, digest)
    else:
        loaded = exact_primary(database, paper, original_bytes)
        actual = manual_highlight_ops.load(owner, loaded.path, loaded.sha256, document=loaded)
    intent = operations.prepare(operations.capture(actual), 3, method="entered", recorded_at=STAMP)
    assert operations.save(intent)["status"] == "saved"
    private = source_snapshots.list_owned(database)
    assert any(
        row["sha256"] == digest
        and json.loads(row["owner_json"])["format"] == "paperfact.position-source-owner.v2"
        for row in private
    )
    if not unbound_position_first:
        selected = tmp_path / "selected-primary-B.pdf"
        selected.write_bytes(current_bytes)
        attach_primary(database, paper, selected)
    exact_primary(database, paper, current_bytes)

    # Keep current/deleted/conflicting Inbox content plus a live sender request in
    # this same DB, alongside the curated queue pin and its original import record.
    service = Inbox(database)
    _, sender_request, _id, _outcome = saved(service, payload("Live joint reading follow-up"))
    original.expected = {
        row["id"]: {"payload": row["payload"], "active": bool(row["active"])}
        for row in service.read(include_deleted=True).data["items"]
    }
    history = canonical_rows(database, inbox_content.HISTORY)
    candidates = canonical_rows(database, inbox_content.CANDIDATES)
    assert candidates and any(not item["active"] for item in original.expected.values())
    requests = rows(database, inbox_content.REQUESTS)
    position_requests = rows(database, positions.RECEIPTS)
    assert requests and position_requests
    expected_position = [(paper, digest, 3, STAMP, "entered")]
    assert records(database, positions.TABLE) == expected_position
    source_operations = {row["operation_id"] for row in rows(database, "paperfact_sync_operations")}
    owners = {rows(database, inbox_content.OWNER)[0]["token"]}
    devices, workspaces = {device}, {workspace}
    before = database.read_bytes()
    backup = tmp_path / "joint-complete.zip"
    with closing(sqlite3.connect(database)) as conn:
        blob_store, _version_root = sync_artifacts.paths(conn)
    sync_recovery.create(database, backup, blob_store=blob_store)
    archive_bytes(backup, original_bytes, current_bytes)
    assert database.read_bytes() == before

    for cycle in range(2):
        detached = tmp_path / f"joint-detached-{cycle}"
        sync_recovery.restore_detached(backup, detached)
        detached_db = detached / "papers.db"
        assert_content(detached_db, original, history, candidates)
        assert records(detached_db, positions.TABLE) == expected_position
        assert rows(detached_db, inbox_content.REQUESTS) == []
        assert records(detached_db, positions.RECEIPTS) == []
        token = rows(detached_db, inbox_content.OWNER)[0]["token"]
        assert token not in owners
        owners.add(token)
        with closing(sqlite3.connect(detached_db)) as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
            assert (
                "paperfact_sync_identity" not in names and "research_capture_binding" not in names
            )
        assert (detached / "pdf" / (paper + ".pdf")).read_bytes() == current_bytes
        assert (detached / "objects" / digest).read_bytes() == original_bytes
        adopter = RecoveryAdoptionService(detached_db)
        inspection = adopter.inspect()
        assert inspection.report["supported"], inspection.report["blockers"]
        output = tmp_path / f"joint-editable-{cycle}"
        independent = tmp_path / f"joint-independent-{cycle}.zip"
        detached_before = detached_db.read_bytes()
        try:
            prepared = adopter.prepare(
                inspection, output, backup_output=independent, request_id=str(uuid4())
            )
        finally:
            # A refused migration must not mutate the detached source, substitute
            # primary B, or leave a half-published editable/independent pair.
            assert detached_db.read_bytes() == detached_before
            assert database.read_bytes() == before
            assert (detached / "pdf" / (paper + ".pdf")).read_bytes() == current_bytes
            assert (detached / "objects" / digest).read_bytes() == original_bytes
            assert output.exists() == independent.exists()
        target = Path(prepared["database"])
        assert_content(target, original, history, candidates)
        assert records(target, positions.TABLE) == expected_position
        assert records(target, positions.RECEIPTS) == []
        assert rows(target, inbox_content.REQUESTS) == []
        current = exact_primary(target, paper, current_bytes)
        assert pdf_text(current.path.read_bytes())[0] == 2
        with closing(sqlite3.connect(target)) as conn:
            located = sync_source_files.inspectable(conn, portable(target, paper), digest)
            assert located is not None and located.read_bytes() == original_bytes
            archived, retained_requests = archived_evidence(conn)
            assert all(row in retained_requests for row in requests)
            assert all(row in archived for row in original.pin_history)
            retained_positions = [
                enrollment_history.validate(row)[0]
                for row in archived
                if row["protocol"] == positions.RECEIPTS
            ]
            retained_positions += raw_position_requests(
                [
                    {"record_id": identity, "body_json": body}
                    for identity, body in conn.execute(
                        "SELECT record_id,body_json FROM research_recovery_provenance"
                    )
                ]
            )
            assert all(row in retained_positions for row in position_requests)
        next_workspace, next_device = identity(target)
        assert next_workspace not in workspaces and next_device not in devices
        workspaces.add(next_workspace)
        devices.add(next_device)
        token = rows(target, inbox_content.OWNER)[0]["token"]
        assert token not in owners
        owners.add(token)
        target_operations = rows(target, "paperfact_sync_operations")
        assert all(row["operation_id"] not in source_operations for row in target_operations)
        for row in target_operations:
            operation = json.loads(row["envelope"])
            assert operation["workspace_id"] == next_workspace
            assert operation["device_id"] == next_device
        with pytest.raises(ValueError, match="Source-bound reading positions are not supported"):
            read_manifest(target, workspace_id=next_workspace, schema_version=1)
        snapshot_before = target.read_bytes()
        snapshot = read_manifest(target, workspace_id=next_workspace, schema_version=2)
        assert target.read_bytes() == snapshot_before
        assert snapshot["required_capabilities"] == ["inbox", "queue_pin", "reading_position"]
        (position,) = snapshot["reading_positions"]
        owner = portable(target, paper)
        assert {
            key: position[key]
            for key in ("paper_id", "document_hash", "page", "recorded_at", "method")
        } == {
            "paper_id": owner,
            "document_hash": digest,
            "page": 3,
            "recorded_at": STAMP,
            "method": "entered",
        }
        source = position["source"]
        assert source["parents"] == [
            {
                "kind": "paper",
                "id": owner,
                "incarnation": current.target["parent_incarnation"],
            }
        ]
        assert source["manifest"]["paper_id"] == owner
        assert source["manifest"]["slot"] == source["manifest"]["source_document_hash"] == digest
        (asset,) = source["manifest"]["assets"]
        assert (asset["sha256"], asset["size"], asset["role"]) == (
            digest,
            len(original_bytes),
            "original_pdf",
        )
        projected = next(item for item in snapshot["papers"] if item["id"] == owner)
        assert projected["pdf_asset_id"] == "sha256:" + hashlib.sha256(current_bytes).hexdigest()
        assert projected["pdf_asset_id"] != "sha256:" + digest
        assert {digest, current.sha256} <= {item["sha256"] for item in snapshot["assets"]}
        receiver = Inbox(target)
        replay = receiver.save(
            receiver.read(),
            request_id=sender_request,
            item_id=original.live_id,
            payload=payload("Old sender request must not replay"),
        )
        assert replay["status"] == "conflict"
        assert_content(target, original, history, candidates)
        backup = Path(prepared["backup"])
        assert (
            archive_bytes(backup, original_bytes, current_bytes)["workspace_id"] == next_workspace
        )
    assert database.read_bytes() == before
    exact_primary(database, paper, current_bytes)
