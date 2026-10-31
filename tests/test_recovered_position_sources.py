"""Sealed recovery source rejection, receiver transaction and atomic retry."""

import copy
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_joint_position_inbox_recovery import raw_position_requests
from test_reading_position_preservation import local as local_fixture
from test_reading_positions import records, view

from paper_daily import (
    manual_highlight_ops,
    position_source_snapshots,
    recovery_provenance,
    store,
    sync_artifacts,
    sync_recovery,
    sync_source_files,
)
from paper_daily import reading_position_ops as operations
from paper_daily import reading_positions as positions
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.sync_files import canonical_json
from paper_daily.sync_projection import read_manifest
from paper_daily.workspace_enrollment import EnrollmentService
from paper_daily.workspace_service import Cancelled, SnapshotChanged, Ticket

local = local_fixture


def backup(database, output):
    with closing(sqlite3.connect(database)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        storage = sync_artifacts.paths(conn) if "research_file_paths" in tables else None
    sync_recovery.create(database, output, blob_store=storage[0] if storage else None)
    return sync_recovery.inspect(output)


def detached(database, root):
    root.mkdir()
    archive = root / "complete.zip"
    manifest = backup(database, archive)
    sync_recovery.restore_detached(archive, root / "detached")
    service = RecoveryAdoptionService(root / "detached/papers.db")
    inspection = service.inspect()
    assert inspection.report["supported"], inspection.report["blockers"]
    return service, inspection, archive, manifest


def prepare(service, inspection, root, **kwargs):
    return service.prepare(
        inspection,
        root / "editable",
        backup_output=root / "independent.zip",
        request_id=str(uuid4()),
        **kwargs,
    )


@pytest.fixture
def bound_source(local, tmp_path, monkeypatch):
    source, current, original, _attempt = local
    result = EnrollmentService(source).prepare(
        tmp_path / "enrolled",
        backup_output=tmp_path / "initial.zip",
        request_id=str(uuid4()),
        pdfs={"local-paper": current},
    )
    database = Path(result["database"])
    monkeypatch.setattr(store, "DB_PATH", database)
    digest = hashlib.sha256(original).hexdigest()
    with closing(sqlite3.connect(database)) as conn:
        portable = conn.execute("SELECT sync_id FROM research_paper_identity").fetchone()[0]
        exact = sync_source_files.inspectable(conn, portable, digest)
    assert exact is not None
    intent = operations.prepare(
        operations.capture(view(database, exact)),
        3,
        method="entered",
        recorded_at="2026-10-31T10:00:00+00:00",
    )
    assert operations.save(intent)["status"] == "saved"
    return SimpleNamespace(database=database, digest=digest, portable=portable, original=original)


@pytest.mark.parametrize("change", ["missing", "retired", "wrong_parent"])
def test_bound_source_refusal_never_falls_back_to_native_cache(bound_source, tmp_path, change):
    source = bound_source
    with closing(sqlite3.connect(source.database)) as conn, conn:
        identity, raw = conn.execute(
            "SELECT entity_id,operation FROM research_file_desired"
        ).fetchone()
        if change == "missing":
            conn.execute("DELETE FROM research_file_desired WHERE entity_id=?", (identity,))
        elif change == "retired":
            conn.execute("UPDATE research_file_desired SET active=0 WHERE entity_id=?", (identity,))
        else:
            value = json.loads(raw)
            value["parents"][0]["incarnation"] = str(uuid4())
            conn.execute(
                "UPDATE research_file_desired SET operation=? WHERE entity_id=?",
                (canonical_json(value).decode(), identity),
            )
    with pytest.raises(ValueError, match="Source-bound reading positions are not supported"):
        read_manifest(
            source.database,
            workspace_id=records(source.database, "paperfact_sync_identity")[0][1],
            schema_version=2,
        )
    service, inspection, _archive, _manifest = detached(source.database, tmp_path / "recovery")
    before = service.database.read_bytes()
    with pytest.raises(ValueError, match="Recovered position original"):
        prepare(service, inspection, tmp_path)
    assert service.database.read_bytes() == before
    assert not (tmp_path / "editable").exists() and not (tmp_path / "independent.zip").exists()
    assert records(service.database, positions.TABLE)[0][1] == source.digest


@pytest.mark.parametrize("change", ["missing", "wrong_owner", "wrong_epoch", "retired_parent"])
def test_unbound_source_requires_current_exact_sql_and_private_receipt(local, tmp_path, change):
    database, primary, original, _attempt = local
    primary.write_bytes(original)  # Original/current A; no untracked primary B in this capsule.
    with closing(sqlite3.connect(database)) as conn, conn:
        request, encoded = conn.execute(
            "SELECT request_id,owner_json FROM research_local_source_owners"
        ).fetchone()
        if change == "missing":
            conn.execute("DELETE FROM research_local_source_owners")
        elif change == "retired_parent":
            conn.execute("UPDATE research_parent_lifecycle SET active=0 WHERE kind='paper'")
        else:
            owner = json.loads(encoded)
            if change == "wrong_owner":
                owner["paper_id"] = owner["source_owner_id"] = "another-paper"
            else:
                owner["parent_lifecycle"] = uuid4().hex
            encoded = canonical_json(owner).decode()
            new_id = "position:" + hashlib.sha256(encoded.encode()).hexdigest()
            conn.execute(
                "UPDATE research_local_source_owners SET request_id=?,owner_json=? "
                "WHERE request_id=?",
                (new_id, encoded, request),
            )
    service, inspection, _archive, _manifest = detached(database, tmp_path / "recovery")
    before = service.database.read_bytes()
    with pytest.raises(ValueError, match="Recovered reading position"):
        prepare(service, inspection, tmp_path)
    assert service.database.read_bytes() == before
    assert not (tmp_path / "editable").exists() and not (tmp_path / "independent.zip").exists()


def test_unbound_exact_private_original_can_be_adopted_without_old_identity(local, tmp_path):
    database, primary, original, _attempt = local
    primary.write_bytes(original)
    service, inspection, _archive, _manifest = detached(database, tmp_path / "recovery")
    result = prepare(service, inspection, tmp_path)
    target = Path(result["database"])
    assert records(target, positions.TABLE) == records(database, positions.TABLE)
    assert records(target, positions.RECEIPTS) == []
    with closing(sqlite3.connect(target)) as conn:
        portable = conn.execute("SELECT sync_id FROM research_paper_identity").fetchone()[0]
        exact = sync_source_files.inspectable(conn, portable, hashlib.sha256(original).hexdigest())
    assert exact is not None and exact.read_bytes() == original


@pytest.mark.parametrize("failure", ["storage", "cancel", "parent", "row"])
def test_receiver_failure_after_private_publication_rolls_back_and_retry_is_fresh(
    bound_source, tmp_path, monkeypatch, failure
):
    from paper_daily import recovery_position_sources as staging

    service, inspection, _archive, _manifest = detached(
        bound_source.database, tmp_path / "recovery"
    )
    before = service.database.read_bytes()
    ticket, published = Ticket(), []
    original = position_source_snapshots.publish
    capture = staging.capture_owner_in

    def broken(database, row, **kwargs):
        result = original(database, row, **kwargs)
        published.append(Path(database).parent)
        if failure == "storage":
            raise OSError("fixture receiver storage failure")
        if failure == "cancel":
            ticket.cancel()
        return result

    def changed(conn, paper):
        owner = capture(conn, paper)
        if failure == "parent":
            conn.execute(
                "UPDATE research_parent_lifecycle SET token=? WHERE kind='paper' AND entity_id=?",
                (uuid4().hex, paper),
            )
        elif failure == "row":
            conn.execute("UPDATE reading_positions SET page=1 WHERE paper_id=?", (paper,))
        return owner

    with monkeypatch.context() as patch:
        patch.setattr(position_source_snapshots, "publish", broken)
        patch.setattr(staging, "capture_owner_in", changed)
        with pytest.raises((ValueError, OSError, Cancelled)):
            prepare(service, inspection, tmp_path, ticket=ticket)
    assert published and all(not folder.exists() for folder in published)
    assert service.database.read_bytes() == before
    assert not (tmp_path / "editable").exists() and not (tmp_path / "independent.zip").exists()
    result = prepare(service, inspection, tmp_path)  # Same sealed source; new explicit attempt.
    target = Path(result["database"])
    assert records(target, positions.TABLE) == records(service.database, positions.TABLE)
    assert records(target, positions.RECEIPTS) == []
    assert service.database.read_bytes() == before


@pytest.mark.parametrize("factory", [None, sqlite3.Row])
def test_capture_owner_in_uses_caller_transaction_without_committing_drafts(local, factory):
    database = local[0]
    with closing(sqlite3.connect(database)) as conn:
        conn.row_factory = factory
        with pytest.raises(ValueError, match="caller transaction"):
            manual_highlight_ops.capture_owner_in(conn, "local-paper")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO kv VALUES('fixture.unsent','keep until caller decides')")
        with pytest.raises(ValueError, match="owner changed"):
            manual_highlight_ops.capture_owner_in(conn, "local-paper", expected_identity=[0, 0])
        assert conn.in_transaction
        owner = manual_highlight_ops.capture_owner_in(conn, "local-paper")
        owner.check(conn)
        assert conn.in_transaction
        assert conn.execute("SELECT value FROM kv WHERE key='fixture.unsent'").fetchone()[0]
        conn.rollback()
        assert conn.execute("SELECT value FROM kv WHERE key='fixture.unsent'").fetchone() is None


def test_source_bytes_changed_inside_staging_require_fresh_inspection_before_retry(
    bound_source, tmp_path, monkeypatch
):
    from paper_daily import recovery_position_sources as staging

    service, inspection, _archive, _manifest = detached(
        bound_source.database, tmp_path / "recovery"
    )
    original_authority = staging._authority
    original = service.root / "objects" / bound_source.digest
    before = service.database.read_bytes()

    def changed(*args):
        result = original_authority(*args)
        original.write_bytes(b"changed original after metadata preflight")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(staging, "_authority", changed)
        with pytest.raises(ValueError):
            prepare(service, inspection, tmp_path)
    assert service.database.read_bytes() == before
    assert not (tmp_path / "editable").exists() and not (tmp_path / "independent.zip").exists()
    original.write_bytes(bound_source.original)
    with pytest.raises(SnapshotChanged):
        prepare(service, inspection, tmp_path)
    fresh = service.inspect()
    result = prepare(service, fresh, tmp_path)
    assert records(Path(result["database"]), positions.TABLE) == records(
        service.database, positions.TABLE
    )


def test_raw_context_cannot_grant_receiver_ownership(local):
    from paper_daily import recovery_position_sources as staging

    database = local[0]
    before = database.read_bytes()
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN")
        with pytest.raises(ValueError, match="native sealed inspection"):
            staging.stage(object(), {}, conn, {}, Ticket())
        assert conn.in_transaction
        conn.rollback()
    assert database.read_bytes() == before


@pytest.mark.parametrize("change", ["valid", "unknown_version", "missing_row", "bad_hash"])
def test_joint_provenance_selector_validates_nested_history_before_selecting(
    bound_source, tmp_path, change
):
    archive = tmp_path / "source.zip"
    manifest = backup(bound_source.database, archive)
    with zipfile.ZipFile(archive) as zipped:
        tables = {
            row["name"]: [
                json.loads(line)
                for line in zipped.read("tables/" + row["name"] + ".jsonl").splitlines()
            ]
            for row in manifest["tables"]
        }
    inner = recovery_provenance.encode(manifest, tables)
    if change == "unknown_version":
        value = json.loads(inner[0]["body_json"])
        value["version"] = 2
        raw = canonical_json(value)
        inner[0] = {"record_id": hashlib.sha256(raw).hexdigest(), "body_json": raw.decode()}
    elif change == "missing_row":
        inner.pop()
    elif change == "bad_hash":
        inner[0] = dict(inner[0], record_id="0" * 64)
    outer = copy.deepcopy(manifest)
    outer["backup_id"] = str(uuid4())
    raw = b"".join(canonical_json(row) + b"\n" for row in inner)
    outer["tables"].append(
        dict(
            name=recovery_provenance.TABLE,
            section="protocol",
            columns=["record_id", "body_json"],
            count=len(inner),
            size=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
    )
    tables[recovery_provenance.TABLE] = inner
    nested = recovery_provenance.encode(outer, tables)
    if change == "valid":
        expected = tables[positions.RECEIPTS]
        assert expected and all(row in raw_position_requests(nested) for row in expected)
    else:
        with pytest.raises(ValueError):
            raw_position_requests(nested)
