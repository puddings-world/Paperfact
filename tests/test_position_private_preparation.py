"""Passive viewing, cancelled intents and restart caches grant no live authority."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from test_reading_position_packages import workspace
from test_reading_positions import pdf_bytes, records, view

from paper_daily import local_source_owners as owners
from paper_daily import position_source_snapshots as private
from paper_daily import reading_position_ops as operations
from paper_daily import reading_positions as positions
from paper_daily import source_snapshots, sync_recovery
from paper_daily.sync_files import canonical_json
from paper_daily.workspace_enrollment import EnrollmentService


@pytest.fixture
def local(tmp_path, monkeypatch):
    database = workspace(tmp_path / "local", monkeypatch, existing=True)
    path = database.parent / "pdf/local-paper.pdf"
    path.write_bytes(pdf_bytes())
    return database, path, view(database, path)


def unchanged(database):
    assert records(database, positions.TABLE) == []
    assert records(database, positions.RECEIPTS) == []
    assert owners.list_owned(database) == []


def plan(database, path):
    result = EnrollmentService(database).plan(pdfs={"local-paper": path})
    assert result["supported"], result["blockers"]
    assert result["original_source_count"] == 0
    return result


def test_passive_capture_and_resume_suggestion_are_readonly_and_enroll_without_saved_page(local):
    database, path, actual = local
    before = {
        str(p.relative_to(database.parent)): p.read_bytes()
        for p in database.parent.rglob("*")
        if p.is_file()
    }
    captured = operations.capture(actual)
    assert captured.cached_path is None
    assert operations.current(captured) is None
    after = {
        str(p.relative_to(database.parent)): p.read_bytes()
        for p in database.parent.rglob("*")
        if p.is_file()
    }
    assert after == before
    unchanged(database)
    assert source_snapshots.list_owned(database) == []
    plan(database, path)


@pytest.mark.parametrize("action", ["no-input", "cancelled-save", "rollback"])
def test_independent_enrollment_backup_has_no_invented_position_after_preparation(
    local, tmp_path, action
):
    database, path, actual = local
    captured = operations.capture(actual)
    if action != "no-input":
        prepared = operations.prepare(captured, 3, method="entered")
        if action == "cancelled-save":
            assert operations.save(prepared, cancelled=lambda: True) is None
        else:
            from paper_daily import store

            with store.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                operations.save_in(conn, prepared)
                conn.rollback()
        (receipt,) = source_snapshots.list_owned(database)
        assert private.verify(database, receipt)[0].read_bytes() == path.read_bytes()
    unchanged(database)
    plan(database, path)
    output = tmp_path / "backup.zip"
    result = EnrollmentService(database).prepare(
        tmp_path / "new-copy",
        backup_output=output,
        request_id=str(uuid4()),
        pdfs={"local-paper": path},
    )
    assert records(Path(result["database"]), positions.TABLE) == []
    assert sync_recovery.inspect(output)
    sync_recovery.restore_detached(output, tmp_path / "restored")
    assert records(tmp_path / "restored/papers.db", positions.TABLE) == []
    unchanged(database)


def test_failed_private_pair_publication_leaves_no_alias_and_retry_grants_only_on_commit(
    local, monkeypatch
):
    database, path, actual = local
    captured = operations.capture(actual)
    rename = private.os.rename

    def failed(*_args, **_kwargs):
        raise OSError("fixture failed before pair publication")

    monkeypatch.setattr(private.os, "rename", failed)
    with pytest.raises(OSError, match="fixture failed"):
        operations.prepare(captured, 3, method="entered")
    unchanged(database)
    assert source_snapshots.list_owned(database) == []
    assert not list(database.parent.glob("pdf/.reading-positions/**/*.pdf"))
    plan(database, path)
    monkeypatch.setattr(private.os, "rename", rename)
    attempt = operations.prepare(captured, 3, method="entered")
    unchanged(database)
    assert operations.save(attempt)["status"] == "saved"
    (receipt,) = owners.list_owned(database)
    assert private.verify(database, receipt)[0].read_bytes() == path.read_bytes()


@pytest.mark.parametrize("member", [None, "original.pdf", "receipt.json"])
def test_restart_ignores_only_bounded_disposable_staging_without_replay(local, member):
    database, path, actual = local
    metadata = operations._source_receipt(actual.owner, actual.fingerprint, path.stat().st_size)
    owner = json.loads(metadata["owner_json"])
    directory = private.stage_root(database, owner["database_identity"], owner["binding"])
    stage = directory / ".position-stage-abcdefgh"
    stage.mkdir()
    if member:
        (stage / member).write_bytes(b"incomplete preparation")
    assert source_snapshots.list_owned(database) == []
    unchanged(database)
    plan(database, path)
    (stage / "unknown.txt").write_bytes(b"not a permitted cache member")
    with pytest.raises(ValueError, match="Unsupported private"):
        source_snapshots.list_owned(database)


def test_old_v1_position_receipt_remains_valid_at_its_original_path(local):
    database, path, actual = local
    row = operations._source_receipt(actual.owner, actual.fingerprint, path.stat().st_size)
    metadata = json.loads(row["owner_json"])
    metadata["format"] = "paperfact.position-source-owner.v1"
    row.update(
        owner_json=canonical_json(metadata).decode(),
        request_id="position:" + hashlib.sha256(canonical_json(metadata)).hexdigest(),
    )
    owners.validate(row)
    destination = source_snapshots.source_path(database, row)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(path.read_bytes())
    source_snapshots._publish_receipt(source_snapshots.receipt_path(database, row), row)
    assert source_snapshots.list_owned(database) == [row]
    assert destination.parts[-3] == ".reading-positions"


def test_incomplete_published_pair_fails_closed_not_treated_as_disposable(local):
    database, path, actual = local
    attempt = operations.prepare(operations.capture(actual), 3, method="entered")
    receipt = json.loads(attempt.view.receipt_json)
    private_path = source_snapshots.source_path(database, receipt)
    private_path.unlink()
    with pytest.raises((ValueError, OSError)):
        source_snapshots.list_owned(database)
    unchanged(database)


@pytest.mark.parametrize("change", ["receipt", "extra", "owner", "original", "stage-size"])
def test_malformed_private_pair_or_oversized_disposable_cache_never_loads(local, change):
    database, path, actual = local
    prepared = operations.prepare(operations.capture(actual), 3, method="entered")
    receipt = json.loads(prepared.view.receipt_json)
    sidecar = source_snapshots.receipt_path(database, receipt)
    if change == "receipt":
        sidecar.unlink()
    elif change == "extra":
        (sidecar.parent / "unknown.json").write_text("{}")
    elif change == "owner":
        changed = dict(receipt, request_id="position:" + "f" * 64)
        sidecar.write_bytes(canonical_json(changed))
    elif change == "original":
        prepared.view.cached_path.write_bytes(b"changed original")
    else:
        owner = json.loads(receipt["owner_json"])
        stage = private.stage_root(database, owner["database_identity"], owner["binding"])
        stage = stage / ".position-stage-abcdefgh"
        stage.mkdir()
        with (stage / "receipt.json").open("wb") as stream:
            stream.truncate(source_snapshots.MAX_RECEIPT + 1)
    with pytest.raises((ValueError, OSError)):
        source_snapshots.list_owned(database)
    unchanged(database)


def test_cancelled_provenance_has_aggregate_budget_but_exact_pair_retry_still_works(
    local, monkeypatch
):
    database, path, actual = local
    original = path.read_bytes()
    first = operations.prepare(operations.capture(actual), 3, method="entered")
    monkeypatch.setattr(source_snapshots, "MAX_RECEIPTS", 1)
    path.write_bytes(pdf_bytes(2, "Another exact original"))
    with pytest.raises(ValueError, match="receipt budget"):
        operations.prepare(operations.capture(view(database, path)), 2, method="entered")
    first_receipt = json.loads(first.view.receipt_json)
    assert private.publish(database, first_receipt, data=original)[0].read_bytes() == original
    assert source_snapshots.list_owned(database) == [first_receipt]
    unchanged(database)
