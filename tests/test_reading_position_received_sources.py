"""A received position retains its current exact original without native receipts."""

import sqlite3
from contextlib import closing

import pytest
from test_reading_positions import bound as _bound
from test_reading_positions import loaded as _loaded
from test_reading_positions import make, prepared

from paper_daily import local_source_owners, reading_position_ops, reading_positions
from paper_daily.sync_artifacts import paths
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_service import ReferenceService
from paper_daily.sync_source_files import inspectable
from paper_daily.workspace_service import Cancelled, Ticket

bound, loaded = _bound, _loaded


@pytest.fixture
def received(loaded, tmp_path):
    client, path, native = loaded
    reading_position_ops.save(prepared(native), with_proof=True)
    service = ReferenceService(tmp_path / "authority.sqlite", blob_root=tmp_path / "blobs")
    token = service.enroll("workspace", "a")
    with client.journal.transaction() as conn:
        blobs, versions = paths(conn)
    source = next(
        op
        for op in client.journal.pending()
        if op.get("payload", {}).get("feature") == "original_source"
    )
    sender = FileTransfers(
        client, blobs, service, origin="https://fixture.invalid", token=token, version_root=versions
    )
    try:
        for _ in range(20):
            if sender.upload(source)["state"] == "uploaded":
                break
        else:
            pytest.fail("Bounded fixture upload did not finish")
    finally:
        sender.close()
    for operation in client.journal.pending():
        event = service.push(token, operation)
        assert event["outcome"] == "accepted"
        client.journal.acknowledge(operation["operation_id"], event["sequence"])
    client.receive(service.pull(token))
    peer = make(tmp_path / "peer.sqlite", "peer")
    peer_token = service.enroll("workspace", "peer")
    peer.receive(service.pull(peer_token))
    receiver = FileTransfers(
        peer,
        BlobStore(tmp_path / "peer-blobs"),
        service,
        origin="https://fixture.invalid",
        token=peer_token,
    )
    try:
        for _ in range(20):
            if receiver.download(source["entity_id"])["state"] == "bound":
                break
        else:
            pytest.fail("Bounded fixture download did not finish")
    finally:
        receiver.close()
    assert local_source_owners.list_owned(peer.journal.path) == []
    with peer.journal.transaction() as conn:
        original = inspectable(conn, source["payload"]["paper_id"], native.fingerprint)
        assert original.read_bytes() == path.read_bytes()
    return peer, native.fingerprint, original


def inventory(peer, ticket=None):
    result = {}
    with peer.journal.transaction() as conn:
        rows = [
            dict(zip(reading_positions.FIELDS.split(), row, strict=True))
            for row in conn.execute(
                "SELECT paper_id,document_hash,page,recorded_at,method FROM reading_positions"
            )
        ]
        reading_position_ops.add_enrollment_sources(
            conn, rows, [], result, ticket=ticket or Ticket()
        )
    return result


def test_received_exact_original_can_enter_source_inventory_without_invented_native_owner(received):
    peer, sha, source = received
    before = peer.journal.path.read_bytes()
    result = inventory(peer)
    assert len(result) == 1
    (record,) = result.values()
    assert record == dict(path=str(source), sha256=sha, size=source.stat().st_size)
    assert peer.journal.path.read_bytes() == before
    assert local_source_owners.list_owned(peer.journal.path) == []


@pytest.mark.parametrize(
    "change", ["missing", "changed", "retired", "raw_page", "wrong_lifetime", "unapplied"]
)
def test_received_source_fallback_never_guesses_or_trusts_tampered_position(received, change):
    peer, _sha, source = received
    if change == "missing":
        source.unlink()
    elif change == "changed":
        source.write_bytes(b"%PDF-1.7\nwrong bytes\n%%EOF")
    else:
        with closing(sqlite3.connect(peer.journal.path)) as conn, conn:
            statements = {
                "retired": "UPDATE research_file_desired SET active=0",
                "raw_page": "UPDATE reading_positions SET page=1",
                "wrong_lifetime": "UPDATE research_paper_projection SET incarnation='replacement'",
                "unapplied": "UPDATE paperfact_sync_graph_projection SET active=0 "
                "WHERE entity_type='research_content'",
            }
            conn.execute(statements[change])
    with pytest.raises((ValueError, FileNotFoundError)):
        inventory(peer)
    assert local_source_owners.list_owned(peer.journal.path) == []


def test_cancellation_during_owned_read_creates_no_receipt_or_inventory(received, monkeypatch):
    peer, _sha, _source = received
    ticket = Ticket()

    def cancelled_read(*_args, **_kwargs):
        ticket.cancel()
        return None

    monkeypatch.setattr(local_source_owners, "_read_pdf", cancelled_read)
    with pytest.raises(Cancelled):
        inventory(peer, ticket)
    assert local_source_owners.list_owned(peer.journal.path) == []
