"""Two private fixture workspaces exchange PDF bytes without activating a reader."""

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from test_sync_document_research import pdf_bytes
from test_sync_http import running
from test_sync_operations import client, paper

from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_document_actions import stage_file
from paper_daily.sync_documents import applied_document, desired_document
from paper_daily.sync_http import HttpTransport, make_server
from paper_daily.sync_operations import ResearchOperations
from paper_daily.sync_service import ReferenceService
from paper_daily.sync_transfers import CHUNK_BYTES, DocumentTransfers


@pytest.fixture
def setup(tmp_path):
    a, b = client(tmp_path / "a.db", "a"), client(tmp_path / "b.db", "b")
    server = ReferenceService(tmp_path / "server.db", blob_root=tmp_path / "server-blobs")
    ta, tb = server.enroll("workspace", "a"), server.enroll("workspace", "b")
    stores = [BlobStore(tmp_path / name) for name in ("a-blobs", "b-blobs")]
    actions = ResearchOperations(a)
    created = actions.create_list(
        "Portable reading", [{"paper": paper(), "notes": ["Important"]}], request_id="intake"
    )
    identity = created["papers"][0]["paper_id"]
    transfers = [
        DocumentTransfers(c, s, server, origin="http://127.0.0.1:1", token=t)
        for c, s, t in zip((a, b), stores, (ta, tb), strict=True)
    ]
    return a, b, server, ta, tb, stores, transfers, actions, identity


def attach(setup, tmp_path, *, large=False, request_id="pdf", text="Research"):
    a, _, _, _, _, stores, _, actions, identity = setup
    data = pdf_bytes(text)
    if large:
        data += b"\n%" + b"x" * (CHUNK_BYTES + 100) + b"\n%%EOF\n"
    source = tmp_path / (request_id + ".pdf")
    source.write_bytes(data)
    manifest = stage_file(stores[0], source)
    result = actions.attach_document(identity, manifest, store=stores[0], request_id=request_id)
    operation = next(
        op for op in a.journal.pending(1000) if op["operation_id"] == result["operation_id"]
    )
    return operation, manifest, data


def finish_upload(transfer, operation):
    for _ in range(8):
        state = transfer.upload(operation)
        if state["state"] == "uploaded":
            return state
        assert state["state"] == "uploading", state
    pytest.fail("Upload did not finish within bounded fixture steps")


def send(setup, operation):
    a, b, server, ta, tb, _, transfers, _, _ = setup
    finish_upload(transfers[0], operation)
    a.sync_once(server, ta, prepare_push=transfers[0].ready_to_push)
    b.sync_once(server, tb)


def bound(side, identity):
    with sqlite3.connect(side.journal.path) as conn:
        return applied_document(conn, identity)


def test_resume_upload_and_download_after_restart_without_blocking_research(setup, tmp_path):
    a, b, server, ta, tb, stores, transfers, _, identity = setup
    operation, manifest, data = attach(setup, tmp_path, large=True)
    assert transfers[0].upload(operation)["offset"] == CHUNK_BYTES
    assert not transfers[0].ready_to_push(operation)
    result = a.sync_once(server, ta, prepare_push=transfers[0].ready_to_push)
    assert result["deferred_push"] == 1
    b.sync_once(server, tb)
    with sqlite3.connect(b.journal.path) as conn:
        assert conn.execute("SELECT body FROM notes").fetchone()[0] == "Important"
        assert desired_document(conn, identity) is None
    restarted = DocumentTransfers(a, stores[0], server, origin="http://127.0.0.1:1", token=ta)
    assert restarted.upload(operation)["state"] == "uploaded"
    a.sync_once(server, ta, prepare_push=restarted.ready_to_push)
    b.sync_once(server, tb)
    assert b.status()["deferred"] == 0 and bound(b, identity) is None
    assert transfers[1].download(identity)["state"] == "downloading"
    assert bound(b, identity) is None
    resumed = DocumentTransfers(b, stores[1], server, origin="http://127.0.0.1:1", token=tb)
    assert resumed.download(identity)["state"] == "bound"
    assert stores[1].verified_path(manifest).read_bytes() == data
    assert bound(b, identity)["operation_id"] == operation["operation_id"]


def test_complete_loopback_http_pdf_round_trip(setup, tmp_path):
    a, b, server, ta, tb, stores, _, _, identity = setup
    operation, manifest, data = attach(setup, tmp_path)
    with running(make_server(server)) as url, HttpTransport(url) as transport:
        upload = DocumentTransfers(a, stores[0], transport, origin=url, token=ta)
        download = DocumentTransfers(b, stores[1], transport, origin=url, token=tb)
        finish_upload(upload, operation)
        a.sync_once(transport, ta, prepare_push=upload.ready_to_push)
        for _ in range(8):
            b.sync_once(transport, tb)
            with sqlite3.connect(b.journal.path) as conn:
                if desired_document(conn, identity) is not None:
                    break
        assert download.download(identity)["state"] == "bound"
    assert stores[1].verified_path(manifest).read_bytes() == data


@pytest.mark.parametrize("interrupt", ["cancel", "close", "session", "replace", "delete"])
def test_late_download_never_binds_after_context_change(setup, tmp_path, monkeypatch, interrupt):
    a, b, server, ta, tb, _, transfers, _, identity = setup
    operation, _, _ = attach(setup, tmp_path)
    send(setup, operation)
    reached, release = Event(), Event()
    original = server.blob_read

    def delayed(*args, **kwargs):
        data = original(*args, **kwargs)
        reached.set()
        assert release.wait(8)
        return data

    monkeypatch.setattr(server, "blob_read", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(transfers[1].download, identity)
        assert reached.wait(8)
        try:
            if interrupt == "cancel":
                transfers[1].cancel(identity)
            elif interrupt == "close":
                transfers[1].close()
            elif interrupt == "session":
                transfers[1].set_session(None)
                transfers[1].set_session(tb)
            elif interrupt == "replace":
                newer, _, _ = attach(setup, tmp_path, request_id="newer", text="Updated")
                send(setup, newer)
            else:
                b.save(b.new_graph_operation("paper_document", identity, {}, action="delete"))
        finally:
            release.set()
        assert future.result()["state"] in {"interrupted", "stale"}
    assert bound(b, identity) is None
    if interrupt == "cancel":
        assert transfers[1].download(identity)["state"] == "cancelled"
        assert transfers[1].download(identity, retry=True)["state"] == "bound"


def test_repeated_activation_is_busy_and_does_not_duplicate_download(setup, tmp_path, monkeypatch):
    _, b, server, _, _, _, transfers, _, identity = setup
    operation, _, _ = attach(setup, tmp_path)
    send(setup, operation)
    reached, release, calls = Event(), Event(), []
    original = server.blob_read

    def delayed(*args, **kwargs):
        calls.append(1)
        reached.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(server, "blob_read", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(transfers[1].download, identity)
        assert reached.wait(8)
        try:
            assert transfers[1].download(identity)["state"] == "busy"
        finally:
            release.set()
        assert future.result()["state"] == "bound"
    assert len(calls) == 1 and bound(b, identity) is not None


def test_failure_retry_is_explicit_sanitized_and_preserves_previous_binding(
    setup, tmp_path, monkeypatch
):
    _, b, server, _, _, _, transfers, _, identity = setup
    operation, _, _ = attach(setup, tmp_path)
    send(setup, operation)
    assert transfers[1].download(identity)["state"] == "bound"
    previous = bound(b, identity)
    newer, _, _ = attach(setup, tmp_path, request_id="new", text="New document")
    send(setup, newer)
    original = server.blob_read

    def failing(*args, **kwargs):
        raise OSError("secret-token and private content")

    monkeypatch.setattr(server, "blob_read", failing)
    assert transfers[1].download(identity)["state"] == "failed"
    monkeypatch.setattr(server, "blob_read", original)
    assert transfers[1].download(identity)["state"] == "failed"
    assert bound(b, identity) == previous
    assert b"secret-token" not in b.journal.path.read_bytes()
    assert transfers[1].download(identity, retry=True)["state"] == "bound"
    assert bound(b, identity)["sha256"] != previous["sha256"]


def test_corrupt_remote_bytes_do_not_bind(setup, tmp_path, monkeypatch):
    _, b, server, _, _, _, transfers, _, identity = setup
    operation, _, _ = attach(setup, tmp_path)
    send(setup, operation)
    original = server.blob_read

    def damaged(*args, **kwargs):
        data = original(*args, **kwargs)
        return b"X" + data[1:]

    monkeypatch.setattr(server, "blob_read", damaged)
    failure = transfers[1].download(identity)
    assert failure["state"] == "failed" and failure["error"] == "invalid_partial"
    assert bound(b, identity) is None
    monkeypatch.setattr(server, "blob_read", original)
    assert transfers[1].download(identity, retry=True)["state"] == "bound"


def test_local_attach_is_retry_safe_and_rejects_changed_request(setup, tmp_path):
    a, _, _, _, _, stores, _, actions, identity = setup
    operation, manifest, _ = attach(setup, tmp_path)
    count = len(a.journal.pending(1000))
    receipt = actions.attach_document(identity, manifest, store=stores[0], request_id="pdf")
    assert receipt["operation_id"] == operation["operation_id"]
    assert len(a.journal.pending(1000)) == count
    other, other_manifest, _ = attach(setup, tmp_path, request_id="new", text="Other")
    with pytest.raises(ValueError, match="retry changed"):
        actions.attach_document(identity, other_manifest, store=stores[0], request_id="pdf")
    assert actions.attach_document(identity, manifest, store=stores[0], request_id="pdf") == receipt
    with sqlite3.connect(a.journal.path) as conn:
        assert desired_document(conn, identity)["operation_id"] == other["operation_id"]


@pytest.mark.parametrize("data", [b"<html>Not PDF</html>", b"%PDF-1.7\ntruncated"])
def test_invalid_local_document_cannot_create_research_intent(setup, tmp_path, data):
    a, _, _, _, _, stores, _, actions, identity = setup
    source = tmp_path / "invalid.pdf"
    source.write_bytes(data)
    manifest = stage_file(stores[0], source)
    before = a.journal.pending(1000)
    with pytest.raises(ValueError):
        actions.attach_document(identity, manifest, store=stores[0], request_id="bad")
    assert a.journal.pending(1000) == before
    with sqlite3.connect(a.journal.path) as conn:
        assert desired_document(conn, identity) is None


def test_binding_rejects_wrong_device_store_and_credential_urls(setup):
    a, b, server, ta, _, stores, _, _, _ = setup
    with pytest.raises(ValueError, match="another workspace"):
        DocumentTransfers(b, stores[0], server, origin="http://127.0.0.1:1")
    with pytest.raises(ValueError):
        DocumentTransfers(a, stores[0], server, origin="https://secret@example.org", token=ta)


def test_signed_out_absent_and_revoked_transfer_status(setup, tmp_path):
    _, b, server, _, tb, _, transfers, _, identity = setup
    assert transfers[1].download(identity)["state"] == "absent"
    operation, _, _ = attach(setup, tmp_path)
    send(setup, operation)
    transfers[1].close()
    assert transfers[1].download(identity)["state"] == "signed_out"
    transfers[1].set_session(tb)
    server.revoke(tb)
    assert transfers[1].download(identity)["state"] == "failed"
    assert bound(b, identity) is None


def test_source_file_is_staged_without_changing_legacy_file(setup, tmp_path):
    _, _, _, _, _, stores, _, _, _ = setup
    data = pdf_bytes()
    path = tmp_path / "a_b.pdf"
    path.write_bytes(data)
    manifest = stage_file(stores[0], path)
    assert manifest == BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    assert stage_file(stores[0], path) == manifest
    assert path.read_bytes() == stores[0].verified_path(manifest).read_bytes()


def test_staging_resumes_long_partial_without_moving_source_cursor_to_durable_eof(setup, tmp_path):
    _, _, _, _, _, stores, _, _, _ = setup
    data = pdf_bytes() + b"\n%" + b"x" * (CHUNK_BYTES * 3) + b"\n%%EOF\n"
    manifest = BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    stores[0].begin(manifest)
    stores[0].append(manifest, 0, data[: CHUNK_BYTES * 2])
    path = tmp_path / "interrupted-copy.pdf"
    path.write_bytes(data)
    assert stage_file(stores[0], path) == manifest
    assert stores[0].verified_path(manifest).read_bytes() == data


def test_concurrent_same_action_returns_single_receipt_and_manifest(setup, tmp_path):
    a, _, _, _, _, stores, _, actions, identity = setup
    path = tmp_path / "parallel.pdf"
    path.write_bytes(pdf_bytes())
    manifest = stage_file(stores[0], path)
    before = len(a.journal.pending(1000))

    def create(_):
        return actions.attach_document(identity, manifest, store=stores[0], request_id="parallel")

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(create, range(3)))
    assert results[0] == results[1] == results[2]
    assert len(a.journal.pending(1000)) == before + 1


def test_local_document_projection_failure_rolls_back_intent_receipt_and_outbox(setup, tmp_path):
    a, _, _, _, _, stores, _, actions, identity = setup
    path = tmp_path / "rollback.pdf"
    path.write_bytes(pdf_bytes())
    manifest = stage_file(stores[0], path)
    original = a.writer
    before = a.journal.pending(1000)

    def failing(conn, operation):
        original(conn, operation)
        if operation["entity_type"] == "paper_document":
            raise RuntimeError("Fixture failure after document projection")

    a.writer = failing
    with pytest.raises(RuntimeError):
        actions.attach_document(identity, manifest, store=stores[0], request_id="rollback")
    assert a.journal.pending(1000) == before
    with sqlite3.connect(a.journal.path) as conn:
        assert desired_document(conn, identity) is None
        assert (
            conn.execute(
                "SELECT 1 FROM research_action_receipts WHERE request_id='rollback'"
            ).fetchone()
            is None
        )
    a.writer = original
    assert actions.attach_document(identity, manifest, store=stores[0], request_id="rollback")


def test_cancel_during_upload_begin_does_not_send_a_followup_chunk(setup, tmp_path, monkeypatch):
    _, _, server, _, _, _, transfers, _, identity = setup
    operation, _, _ = attach(setup, tmp_path)
    reached, release, append_calls = Event(), Event(), []
    original = server.blob_begin

    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        reached.set()
        assert release.wait(8)
        return result

    def unexpected(*args, **kwargs):
        append_calls.append(1)
        raise AssertionError("Cancelled upload sent another chunk")

    monkeypatch.setattr(server, "blob_begin", delayed)
    monkeypatch.setattr(server, "blob_append", unexpected)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(transfers[0].upload, operation)
        assert reached.wait(8)
        try:
            transfers[0].cancel(identity)
        finally:
            release.set()
        assert future.result()["state"] == "interrupted"
    assert append_calls == []
    assert not transfers[0].ready_to_push(operation)


def test_lost_upload_response_retries_from_authority_offset(setup, tmp_path, monkeypatch):
    _, _, server, _, _, _, transfers, _, _ = setup
    operation, _, _ = attach(setup, tmp_path, large=True)
    original = server.blob_append

    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("Response lost after durable append")

    monkeypatch.setattr(server, "blob_append", lost)
    assert transfers[0].upload(operation)["state"] == "failed"
    monkeypatch.setattr(server, "blob_append", original)
    assert transfers[0].upload(operation, retry=True)["state"] == "uploaded"
    assert transfers[0].ready_to_push(operation)


def test_download_binding_failure_preserves_cursor_and_reuses_verified_bytes(
    setup, tmp_path, monkeypatch
):
    _, b, server, _, _, _, transfers, _, identity = setup
    operation, _, _ = attach(setup, tmp_path)
    send(setup, operation)
    cursor = b.status()["cursor"]
    import paper_daily.sync_transfers as module

    original = module.bind_verified_document

    def failing(conn, target, verified):
        assert original(conn, target, verified)
        raise RuntimeError("Fixture failure after applied binding")

    monkeypatch.setattr(module, "bind_verified_document", failing)
    assert transfers[1].download(identity)["state"] == "failed"
    assert bound(b, identity) is None and b.status()["cursor"] == cursor
    monkeypatch.setattr(module, "bind_verified_document", original)

    def no_download(*args, **kwargs):
        raise AssertionError("Verified local bytes should be reusable")

    monkeypatch.setattr(server, "blob_read", no_download)
    assert transfers[1].download(identity, retry=True)["state"] == "bound"


def test_endpoint_binding_does_not_reuse_old_authority_upload_receipt(setup, tmp_path):
    a, _, _, ta, _, stores, transfers, _, _ = setup
    operation, _, _ = attach(setup, tmp_path)
    finish_upload(transfers[0], operation)
    other_server = ReferenceService(tmp_path / "other.db", blob_root=tmp_path / "other-blobs")
    other = DocumentTransfers(a, stores[0], other_server, origin="http://127.0.0.1:2", token=ta)
    assert not other.ready_to_push(operation)


@pytest.mark.parametrize("action", ["cancel", "close"])
def test_completed_upload_cannot_publish_after_cancel_or_signout(setup, tmp_path, action):
    _, _, _, _, _, _, transfers, _, identity = setup
    operation, _, _ = attach(setup, tmp_path)
    finish_upload(transfers[0], operation)
    assert transfers[0].ready_to_push(operation)
    if action == "cancel":
        transfers[0].cancel(identity)
    else:
        transfers[0].close()
    assert not transfers[0].ready_to_push(operation)


def test_matching_upload_overlap_accepts_later_durable_remote_offset(setup, tmp_path, monkeypatch):
    _, _, server, _, _, _, transfers, _, _ = setup
    operation, _, data = attach(setup, tmp_path, large=True)
    original = server.blob_append

    def concurrent(token, upload_id, offset, chunk):
        for position in range(0, len(data), CHUNK_BYTES):
            original(token, upload_id, position, data[position : position + CHUNK_BYTES])
        return original(token, upload_id, offset, chunk)

    monkeypatch.setattr(server, "blob_append", concurrent)
    assert transfers[0].upload(operation)["state"] == "uploaded"
    assert transfers[0].ready_to_push(operation)


@pytest.mark.parametrize("workspace,device", [("other", "a"), ("workspace", "other")])
def test_wrong_session_never_sends_local_document(setup, tmp_path, monkeypatch, workspace, device):
    _, _, server, _, _, _, transfers, _, _ = setup
    operation, _, _ = attach(setup, tmp_path)
    transfers[0].set_session(server.enroll(workspace, device))
    calls = []

    def unexpected(*args, **kwargs):
        calls.append(1)
        raise AssertionError("Mismatched session must not begin a blob transfer")

    monkeypatch.setattr(server, "blob_begin", unexpected)
    assert transfers[0].upload(operation)["state"] == "failed"
    assert calls == [] and not transfers[0].ready_to_push(operation)


def test_cancel_during_local_verification_sends_no_blob_request(setup, tmp_path, monkeypatch):
    _, _, server, _, _, _, transfers, _, identity = setup
    operation, _, _ = attach(setup, tmp_path)
    original = transfers[0]._verify
    calls = []

    def cancelled(target):
        verified = original(target)
        transfers[0].cancel(identity)
        return verified

    def unexpected(*args, **kwargs):
        calls.append(1)
        raise AssertionError("Cancelled verification must not begin an upload")

    monkeypatch.setattr(transfers[0], "_verify", cancelled)
    monkeypatch.setattr(server, "blob_begin", unexpected)
    assert transfers[0].upload(operation)["state"] == "interrupted"
    assert calls == []


def test_session_binding_checked_again_after_account_switch(setup, tmp_path, monkeypatch):
    _, _, server, _, _, _, transfers, _, _ = setup
    operation, _, _ = attach(setup, tmp_path, large=True)
    assert transfers[0].upload(operation)["state"] == "uploading"
    transfers[0].set_session(server.enroll("other-workspace", "a"))
    original = server.blob_append
    calls = []

    def observed(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(server, "blob_append", observed)
    assert transfers[0].upload(operation)["state"] == "failed"
    assert calls == []


def test_completed_upload_requires_fresh_binding_after_session_replacement(setup, tmp_path):
    _, _, server, ta, _, _, transfers, _, _ = setup
    operation, _, _ = attach(setup, tmp_path)
    finish_upload(transfers[0], operation)
    transfers[0].set_session(server.enroll("other", "a"))
    assert not transfers[0].ready_to_push(operation)
    with pytest.raises(PermissionError):
        transfers[0].authenticate()
    assert not transfers[0].ready_to_push(operation)
    transfers[0].set_session(ta)
    assert transfers[0].authenticate()
    assert transfers[0].ready_to_push(operation)


def test_metadata_only_pass_can_authenticate_without_sending_blobs(setup, monkeypatch):
    a, _, server, ta, _, _, transfers, _, _ = setup

    def unexpected(*args, **kwargs):
        raise AssertionError("Metadata-only pass must not send PDF bytes")

    monkeypatch.setattr(server, "blob_begin", unexpected)
    assert transfers[0].authenticate()
    result = a.sync_once(server, ta, prepare_push=transfers[0].ready_to_push)
    assert result["pushed"] > 0 and result["deferred_push"] == 0
