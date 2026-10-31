"""Actual PDF bounds, private original ownership and transaction/CAS behavior."""

import hashlib
import json
import sqlite3
from contextlib import closing

import pymupdf
import pytest
from test_sync_capture import seed

from paper_daily import local_source_owners as owners
from paper_daily import manual_highlight_ops as highlights
from paper_daily import reading_position_ops as operations
from paper_daily import reading_positions as positions
from paper_daily import source_snapshots, store, sync_content
from paper_daily.sync_artifacts import paths
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import install
from paper_daily.sync_client import SyncClient
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare as prepare_sync
from paper_daily.sync_research import research_order_writer, research_writer
from paper_daily.sync_service import ReferenceService

STAMP = "2026-10-30T10:00:00+00:00"


def make(path, device="a"):
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(store.SCHEMA)
    prepare_sync(path, workspace_id="workspace", device_id=device)
    return SyncClient(
        Journal(path, workspace_id="workspace", device_id=device),
        research_writer,
        order_writer=research_order_writer,
    )


@pytest.fixture
def bound(tmp_path, monkeypatch):
    client = make(tmp_path / "a.sqlite")
    monkeypatch.setattr(store, "DB_PATH", client.journal.path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="a")
    return client


def pdf_bytes(pages=4, label="Source A"):
    with pymupdf.open() as document:
        for index in range(pages):
            page = document.new_page()
            page.insert_text((40, 40), f"{label}, page {index + 1}")
        return document.tobytes()


def view(database, path, paper="local-paper"):
    owner = highlights.capture_owner(database, paper)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return highlights.load(owner, path, digest)


@pytest.fixture
def loaded(bound, tmp_path):
    seed()
    path = tmp_path / "actual-loaded.pdf"
    path.write_bytes(pdf_bytes())
    native = view(bound.journal.path, path)
    return bound, path, native


def prepared(native, page=3, method="entered", **kwargs):
    snapshot = operations.capture(native)
    return operations.prepare(snapshot, page, method=method, recorded_at=STAMP, **kwargs)


def records(database, table):
    with closing(sqlite3.connect(database)) as conn:
        return conn.execute("SELECT * FROM " + table).fetchall()


def test_real_pdf_position_commits_owned_source_and_outbox_once(loaded):
    client, path, native = loaded
    original = path.read_bytes()
    attempt = prepared(native)
    assert attempt.view.page_count == 4
    before = len(client.journal.pending())
    assert operations.save(attempt)["status"] == "saved"
    assert operations.save(attempt)["status"] == "saved"
    assert len(client.journal.pending()) == before + 2
    features = [
        op["payload"]["feature"] for op in client.journal.pending() if "feature" in op["payload"]
    ]
    assert features == ["original_source", "reading_position"]
    assert len(records(client.journal.path, positions.TABLE)) == 1
    receipts = owners.list_owned(client.journal.path)
    assert len(receipts) == 1
    metadata = json.loads(receipts[0]["owner_json"])
    assert metadata["format"] == "paperfact.position-source-owner.v2"
    assert metadata["position_key"] == native.fingerprint
    assert "claim" not in metadata and "generation" not in metadata
    assert source_snapshots.source_path(client.journal.path, receipts[0]).read_bytes() == original
    assert path.read_bytes() == original
    assert operations.current(attempt.view)["page"] == 3
    assert not records(client.journal.path, "paper_claim_sets")


def test_native_chain_requires_exact_committed_head_even_when_new_value_is_identical(loaded):
    client, _path, native = loaded
    captured = operations.capture(native)
    first = operations._native_observation(captured, 4)
    latest = operations._native_observation(captured, 1)
    intent = operations.prepare(captured, 4, method="observed", observation=first)
    committed = operations.save(intent, with_proof=True)
    refreshed = operations.refresh(intent.view)
    rebound = operations.follow_native(latest, committed, refreshed)
    assert rebound.view is refreshed and rebound.page == 1
    same_page = operations._native_observation(captured, 4)
    followed, satisfied = operations.follow_native(
        same_page, committed, refreshed, with_status=True
    )
    assert followed.view is refreshed and satisfied
    prior = next(
        op
        for op in client.journal.pending()
        if op.get("payload", {}).get("feature") == "reading_position"
    )
    newer = client.new_graph_operation("research_content", prior["entity_id"], prior["payload"])
    client.save(newer)
    changed_head = operations.refresh(intent.view)
    assert changed_head.base_json == refreshed.base_json
    assert changed_head.observation_json != refreshed.observation_json
    assert operations.follow_native(latest, committed, changed_head) is latest
    followed, satisfied = operations.follow_native(
        same_page, committed, changed_head, with_status=True
    )
    assert followed is same_page and not satisfied
    identical_value = operations.prepare(
        same_page.view, 4, method="observed", observation=same_page
    )
    assert operations.save(identical_value)["status"] == "retained"
    retained = operations.prepare(latest.view, 1, method="observed", observation=latest)
    assert operations.save(retained)["status"] == "retained"
    assert records(client.journal.path, positions.TABLE)[0][2] == 4


def test_tampered_retry_result_is_refused_before_native_continuation(loaded):
    _client, _path, native = loaded
    captured = operations.capture(native)
    first = operations._native_observation(captured, 4)
    latest = operations._native_observation(captured, 1)
    intent = operations.prepare(captured, 4, method="observed", observation=first)
    committed = operations.save(intent, with_proof=True)
    result = committed.result
    result["position"]["page"] = 2
    with store.connect() as connection, pytest.raises(sqlite3.DatabaseError, match="authorized"):
        connection.execute(
            "UPDATE research_reading_position_receipts SET result_json=? WHERE request_id=?",
            (json.dumps(result), intent.request_id),
        )
    # Install corrupt persisted input through a raw fixture connection; the
    # ordinary product writer above must continue to reject this mutation.
    with closing(sqlite3.connect(native.owner.database)) as connection, connection:
        connection.execute(
            "UPDATE research_reading_position_receipts SET result_json=? WHERE request_id=?",
            (json.dumps(result), intent.request_id),
        )
    with pytest.raises(ValueError):
        operations.follow_native(latest, committed, operations.refresh(intent.view))
    with pytest.raises(ValueError):
        operations.save(intent)
    assert records(native.owner.database, positions.TABLE)[0][2] == 4


@pytest.mark.parametrize("action", ["no-input", "cancel", "rollback"])
def test_bound_backup_after_passive_or_cancelled_preparation_has_no_active_position(
    loaded, tmp_path, action
):
    from paper_daily import sync_recovery

    client, path, native = loaded
    pending = client.journal.pending()
    captured = operations.capture(native)
    if action != "no-input":
        intent = operations.prepare(captured, 3, method="entered")
        if action == "cancel":
            assert operations.save(intent, cancelled=lambda: True) is None
        else:
            with store.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                operations.save_in(connection, intent)
                connection.rollback()
    assert records(client.journal.path, positions.TABLE) == []
    assert records(client.journal.path, positions.RECEIPTS) == []
    assert owners.list_owned(client.journal.path) == []
    assert client.journal.pending() == pending
    output = tmp_path / "passive-or-cancelled.zip"
    sync_recovery.create(client.journal.path, output, legacy_root=client.journal.path.parent)
    assert sync_recovery.inspect(output)
    restored = tmp_path / "restored"
    sync_recovery.restore_detached(output, restored)
    assert records(restored / "papers.db", positions.TABLE) == []
    if action != "no-input":
        assert operations.save(intent)["status"] == "saved"
        assert records(client.journal.path, positions.TABLE)[0][2] == 3
    assert hashlib.sha256(path.read_bytes()).hexdigest() == native.fingerprint


@pytest.mark.parametrize("change", ["changed", "missing", "ABA"])
def test_private_original_changed_during_backup_is_rejected_before_publication(
    loaded, tmp_path, monkeypatch, change
):
    import os

    from paper_daily import sync_recovery

    client, _path, native = loaded
    intent = prepared(native)
    original = intent.view.cached_path.read_bytes()
    before = intent.view.cached_path.stat()
    validate = sync_recovery.inspect

    def changed_after_validation(archive):
        result = validate(archive)
        if change == "missing":
            intent.view.cached_path.unlink()
        else:
            intent.view.cached_path.write_bytes(b"changed original")
            if change == "ABA":
                intent.view.cached_path.write_bytes(original)
                os.utime(intent.view.cached_path, ns=(before.st_atime_ns, before.st_mtime_ns))
        return result

    monkeypatch.setattr(sync_recovery, "inspect", changed_after_validation)
    output = tmp_path / "changed-private-original.zip"
    with pytest.raises(sync_recovery.RecoveryError, match="source cache changed"):
        sync_recovery.create(client.journal.path, output)
    assert not output.exists()
    assert records(client.journal.path, positions.TABLE) == []
    assert owners.list_owned(client.journal.path) == []


@pytest.mark.parametrize("page", [0, -1, True, 1.0, 5, 1000002])
def test_verified_actual_page_bounds_never_clamp_or_publish(loaded, page):
    client, _path, native = loaded
    before = client.journal.pending()
    with pytest.raises(ValueError):
        prepared(native, page)
    assert client.journal.pending() == before
    assert not records(client.journal.path, positions.TABLE)
    assert owners.list_owned(client.journal.path) == []


def test_backward_rereading_is_saved_and_same_page_does_not_duplicate(loaded):
    client, _path, native = loaded
    operations.save(prepared(native, 4))
    operations.save(prepared(native, 2))
    before = len(client.journal.pending())
    result = operations.save(prepared(native, 2))
    assert result["status"] == "unchanged"
    assert len(client.journal.pending()) == before
    assert records(client.journal.path, positions.TABLE)[0][2] == 2


def test_concurrent_positions_retain_both_without_max_page_or_clock_resolution(loaded):
    client, _path, native = loaded
    old = prepared(native, 4)
    fresh = prepared(native, 2, method="entered")
    operations.save(fresh)
    assert operations.save(old)["status"] == "retained"
    assert operations.save(old)["status"] == "retained"
    assert records(client.journal.path, positions.TABLE)[0][2:] == (2, STAMP, "entered")
    retained = operations.prepare_resolution(operations.capture(native), old.request_id)
    assert operations.save(retained)["status"] == "saved"
    assert records(client.journal.path, positions.TABLE)[0][2] == 4
    rows = records(client.journal.path, positions.RECEIPTS)
    assert len(rows) == 3
    assert [json.loads(row[2])["status"] for row in rows] == ["saved", "retained", "saved"]


def test_caller_rollback_undoes_position_original_ownership_receipt_and_outbox(loaded):
    client, _path, native = loaded
    attempt = prepared(native)
    before = client.journal.pending()
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        operations.save_in(conn, attempt)
        conn.rollback()
    assert records(client.journal.path, positions.TABLE) == []
    assert records(client.journal.path, positions.RECEIPTS) == []
    assert owners.list_owned(client.journal.path) == []
    assert client.journal.pending() == before
    assert operations.save(attempt)["status"] == "saved"


def test_old_source_A_stays_owned_when_primary_path_is_replaced_with_B(loaded):
    client, path, native = loaded
    original = path.read_bytes()
    attempt = prepared(native, 4)
    operations.save(attempt)
    path.write_bytes(pdf_bytes(2, "Source B"))
    with pytest.raises(ValueError, match="changed"):
        operations.current(attempt.view)
    newer = view(client.journal.path, path)
    snapshot = operations.capture(newer)
    assert operations.current(snapshot) is None
    operations.save(operations.prepare(snapshot, 1, method="entered"))
    rows = records(client.journal.path, positions.TABLE)
    assert {(row[1], row[2]) for row in rows} == {(native.fingerprint, 4), (newer.fingerprint, 1)}
    receipt = next(
        row for row in owners.list_owned(client.journal.path) if row["sha256"] == native.fingerprint
    )
    assert source_snapshots.source_path(client.journal.path, receipt).read_bytes() == original
    assert path.read_bytes() != original


def test_cancelled_capture_has_no_position_or_owner(loaded):
    client, _path, native = loaded
    assert operations.capture(native, cancelled=lambda: True) is None
    assert not records(client.journal.path, positions.TABLE)
    assert owners.list_owned(client.journal.path) == []


def test_observed_method_requires_actual_native_input_evidence(loaded):
    _client, _path, native = loaded
    snapshot = operations.capture(native)
    with pytest.raises(ValueError, match="genuine native"):
        operations.prepare(snapshot, 2, method="observed")


def test_raw_SQL_cannot_invent_a_verified_position_without_reader_admission(loaded):
    client, _path, native = loaded
    before = client.journal.pending()
    with pytest.raises(sqlite3.Error), store.connect() as conn:
        conn.execute(
            "INSERT INTO reading_positions VALUES(?,?,?,?,?)",
            ("local-paper", native.fingerprint, 3, STAMP, "observed"),
        )
    assert not records(client.journal.path, positions.TABLE)
    assert owners.list_owned(client.journal.path) == []
    assert client.journal.pending() == before


def test_capture_save_and_suggestion_read_do_not_manufacture_open_or_read_state(loaded):
    client, _path, native = loaded
    before = {
        table: records(client.journal.path, table)
        for table in ("papers", "list_papers", "kv", "queue")
    }
    attempt = prepared(native)
    assert operations.current(attempt.view) is None
    operations.save(attempt)
    assert operations.current(attempt.view)["page"] == 3
    assert before == {table: records(client.journal.path, table) for table in before}


@pytest.mark.parametrize(
    "change", ["unknown", "owner", "data", "observation", "oversized", "result"]
)
def test_retained_receipts_are_closed_bounded_archive_only_input(loaded, change):
    client, _path, native = loaded
    operations.save(prepared(native))
    raw = records(client.journal.path, positions.RECEIPTS)[0]
    row = dict(zip(positions.RECEIPT_FIELDS.split(), raw, strict=True))
    assert operations.validate_receipt(row) == {native.fingerprint}
    request = json.loads(row["request_json"])
    result = json.loads(row["result_json"])
    if change == "unknown":
        request["path"] = "sender path is never authority"
    elif change == "owner":
        request["owner"]["claim"] = "invented"
    elif change == "data":
        request["data"]["page"] = True
    elif change == "observation":
        request["observation"]["parents"][0]["active"] = 1
    elif change == "oversized":
        request["extra"] = "x" * operations.MAX_RECEIPT
    else:
        result["new_job"] = "never execute"
    row["request_json"], row["result_json"] = json.dumps(request), json.dumps(result)
    with pytest.raises(ValueError):
        operations.validate_receipt(row)


def test_position_history_budget_refuses_new_request_but_keeps_exact_retry(loaded, monkeypatch):
    _client, _path, native = loaded
    attempt = prepared(native)
    result = operations.save(attempt)
    monkeypatch.setattr(source_snapshots, "MAX_RECEIPTS", 1)
    assert operations.save(attempt) == result
    with pytest.raises(ValueError, match="receipt budget"):
        operations.save(prepared(native, 2))


@pytest.mark.parametrize("change", ["original", "cached", "parent", "binding", "database"])
def test_changed_source_lifetime_binding_or_replaced_database_never_saves(loaded, change, tmp_path):
    import os

    client, path, native = loaded
    attempt = prepared(native)
    if change in ("original", "cached"):
        target = path if change == "original" else attempt.view.cached_path
        old = target.stat()
        data = target.read_bytes()
        target.write_bytes(b"X" + data[1:])
        os.utime(target, ns=(old.st_atime_ns, old.st_mtime_ns))
    elif change == "parent":
        with store.connect() as conn:
            conn.execute("DELETE FROM papers WHERE id='local-paper'")
            store.upsert_papers(
                conn,
                [
                    dict(
                        id="local-paper",
                        title="Replacement",
                        venue="Fixture",
                        year=2026,
                        source="fixture",
                    )
                ],
            )
    elif change == "binding":
        with closing(sqlite3.connect(client.journal.path)) as conn, conn:
            conn.execute("UPDATE research_capture_binding SET workspace='other'")
    else:
        replacement = tmp_path / "replacement.db"
        with (
            closing(sqlite3.connect(client.journal.path)) as source,
            closing(sqlite3.connect(replacement)) as target,
        ):
            source.backup(target)
        os.replace(replacement, client.journal.path)
    with pytest.raises((ValueError, sqlite3.Error)):
        operations.save(attempt)
    assert not records(client.journal.path, positions.TABLE)
    assert owners.list_owned(client.journal.path) == []


def test_cancel_after_sql_work_rolls_back_all_ownership_and_retry_is_safe(loaded):
    client, _path, native = loaded
    attempt = prepared(native)
    calls = []

    def cancelled():
        calls.append(1)
        return len(calls) == 2

    before = client.journal.pending()
    assert operations.save(attempt, cancelled=cancelled) is None
    assert not records(client.journal.path, positions.TABLE)
    assert not records(client.journal.path, positions.RECEIPTS)
    assert owners.list_owned(client.journal.path) == []
    assert client.journal.pending() == before
    assert operations.save(attempt)["status"] == "saved"


def test_unobserved_shared_parent_delete_preserves_position_and_retains_rejected_intent(loaded):
    from paper_daily.sync_capture import StaleCaptureError

    client, _path, native = loaded
    attempt = prepared(native)
    operations.save(attempt)
    before = records(client.journal.path, positions.TABLE)
    with pytest.raises(StaleCaptureError), store.connect() as conn:
        conn.execute("DELETE FROM papers WHERE id='local-paper'")
    assert records(client.journal.path, positions.TABLE) == before
    assert len(records(client.journal.path, "research_capture_candidates")) == 1
    assert operations.save(attempt)["status"] == "saved"


def test_lightweight_package_export_requires_exact_position_originals(loaded, tmp_path):
    from paper_daily import bundle

    _client, _path, native = loaded
    operations.save(prepared(native))
    output = tmp_path / "not-lossy.zip"
    with pytest.raises(ValueError, match="Include PDFs"):
        bundle.export("list", output, with_pdfs=False)
    assert not output.exists()


def test_real_server_two_peer_projection_and_no_receive_echo(loaded, tmp_path):
    client, _path, native = loaded
    operations.save(prepared(native))
    service = ReferenceService(tmp_path / "server.db", blob_root=tmp_path / "server-blobs")
    token = service.enroll("workspace", "a")
    with store.connect() as conn:
        blobs, root = paths(conn)
    sender = FileTransfers(
        client, blobs, service, origin="https://fixture.invalid", token=token, version_root=root
    )
    original = next(
        op
        for op in client.journal.pending()
        if op.get("payload", {}).get("feature") == "original_source"
    )
    try:
        for _ in range(20):
            if sender.upload(original)["state"] == "uploaded":
                break
        else:
            pytest.fail("Original PDF upload did not complete")
    finally:
        sender.close()
    for operation in client.journal.pending():
        event = service.push(token, operation)
        assert event["outcome"] == "accepted"
        client.journal.acknowledge(operation["operation_id"], event["sequence"])
    client.receive(service.pull(token))
    peer = make(tmp_path / "peer.db", "b")
    peer_token = service.enroll("workspace", "b")
    peer.receive(service.pull(peer_token))
    assert client.journal.pending() == peer.journal.pending() == []
    peer_rows = records(peer.journal.path, positions.TABLE)
    assert [(row[1], row[2], row[3], row[4]) for row in peer_rows] == [
        (native.fingerprint, 3, STAMP, "entered")
    ]
    assert (
        records(peer.journal.path, "list_papers")[0][2:4]
        == records(client.journal.path, "list_papers")[0][2:4]
    )
    receiver = FileTransfers(
        peer,
        BlobStore(tmp_path / "peer-blobs"),
        service,
        origin="https://fixture.invalid",
        token=peer_token,
    )
    try:
        for _ in range(20):
            if receiver.download(original["entity_id"])["state"] == "bound":
                break
        else:
            pytest.fail("Original PDF download did not complete")
    finally:
        receiver.close()
    from paper_daily.sync_source_files import inspectable

    with peer.journal.transaction() as conn:
        source = inspectable(conn, original["payload"]["paper_id"], native.fingerprint)
    assert source.read_bytes() == native.path.read_bytes()


@pytest.mark.parametrize("change", ["unknown", "bool", "float", "naive", "method", "hash", "scope"])
def test_wire_is_closed_and_exact(change):
    payload = dict(
        scope={"kind": "paper", "id": "00000000-0000-4000-8000-000000000001"},
        feature="reading_position",
        key="a" * 64,
        source_document_hash="a" * 64,
        data=dict(page=2, recorded_at=STAMP, method="entered"),
    )
    sync_content.validate_payload(payload)
    if change == "unknown":
        payload["data"]["page_count"] = 100
    elif change == "bool":
        payload["data"]["page"] = True
    elif change == "float":
        payload["data"]["page"] = 1.0
    elif change == "naive":
        payload["data"]["recorded_at"] = "2026-10-30T10:00:00"
    elif change == "method":
        payload["data"]["method"] = "estimated"
    elif change == "hash":
        payload["source_document_hash"] = "b" * 64
    else:
        payload["scope"]["kind"] = "list"
    with pytest.raises(ValueError):
        sync_content.validate_payload(payload)
