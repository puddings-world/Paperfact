"""Document DTOs expose manifests, never infer byte availability from saved flags."""

import json
import sqlite3

import pytest
from test_sync_document_research import applied, document, local_blob, payload, pdf_bytes, target
from test_sync_reading_state_research import PAPER, database, paper_payload, save

from paper_daily import sync_documents, sync_projection
from paper_daily.store import SCHEMA
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_client import SyncClient
from paper_daily.sync_documents import bind_verified_document, desired_document, verify_document
from paper_daily.sync_journal import Journal
from paper_daily.sync_projection import read_manifest
from paper_daily.sync_research import prepare, research_writer
from paper_daily.sync_service import ReferenceService


def read(path, snapshots=()):
    return read_manifest(
        path, workspace_id="workspace", schema_version=2, verified_documents=snapshots
    )


def test_manifest_without_bytes_and_applied_binding_both_default_to_unchecked(tmp_path):
    path = tmp_path / "research.db"
    journal, data = database(path), pdf_bytes()
    save(journal, document(data))
    wanted = target(path)
    before = path.read_bytes()
    manifest = read(path)
    paper = manifest["papers"][0]
    assert paper["pdf_asset_id"] == "sha256:" + wanted["sha256"]
    assert paper["document"] == {
        "desired": payload(data),
        "applied_sha256": None,
        "availability": "unchecked",
        "revision": None,
        "sync_state": "pending",
    }
    assert manifest["assets"] == [
        {
            "id": paper["pdf_asset_id"],
            "sha256": wanted["sha256"],
            "size": len(data),
            "media_type": "application/pdf",
            "availability": "unchecked",
        }
    ]
    assert manifest["capabilities"]["document_manifests"] is True
    assert manifest["capabilities"]["assets"] is True
    assert manifest["capabilities"]["reader_activation"] is False
    assert path.read_bytes() == before
    store = BlobStore(tmp_path / "blobs")
    local_blob(store, data)
    verified = verify_document(store, wanted)
    with journal.transaction() as conn:
        assert bind_verified_document(conn, wanted, verified)
    assert read(path)["papers"][0]["document"]["availability"] == "unchecked"
    assert read(path)["papers"][0]["document"]["applied_sha256"] == wanted["sha256"]
    ready = read(path, [verified])
    assert ready["papers"][0]["document"]["availability"] == "available"
    assert ready["assets"][0]["availability"] == "available"
    assert str(tmp_path) not in json.dumps(ready)
    legacy = read_manifest(path, workspace_id="workspace")
    assert legacy["papers"][0]["pdf_asset_id"] is None and legacy["assets"] == []
    assert (
        "document" not in legacy["papers"][0] and "document_manifests" not in legacy["capabilities"]
    )


@pytest.mark.parametrize("change", ["replaced", "detached", "parent", "corrupt", "removed"])
def test_obsolete_or_invalidated_snapshot_cannot_advertise_current_availability(tmp_path, change):
    path = tmp_path / "research.db"
    journal, data = database(path), pdf_bytes()
    save(journal, document(data))
    old = target(path)
    store = BlobStore(tmp_path / "blobs")
    final = local_blob(store, data)
    verified = verify_document(store, old)
    with journal.transaction() as conn:
        assert bind_verified_document(conn, old, verified)
    if change == "replaced":
        save(journal, document(pdf_bytes("New"), op_id="new"))
    elif change == "detached":
        save(journal, document(data, op_id="detach", action="delete"))
    elif change == "parent":
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE research_paper_projection SET incarnation='new-paper'")
    elif change == "corrupt":
        final.write_bytes(b"x" * len(data))
    else:
        final.unlink()
    result = read(path, [verified])
    assert result["papers"][0]["document"]["availability"] == "unchecked"
    assert result["papers"][0]["document"]["applied_sha256"] == old["sha256"]
    assert applied(path) == old
    if change == "detached":
        assert result["papers"][0]["pdf_asset_id"] is None and result["assets"] == []


def test_projection_never_hashes_or_reads_pdf_content(tmp_path, monkeypatch):
    path = tmp_path / "research.db"
    journal, data = database(path), pdf_bytes()
    save(journal, document(data))
    store = BlobStore(tmp_path / "blobs")
    local_blob(store, data)
    verified = verify_document(store, target(path))

    def forbidden(*args, **kwargs):
        pytest.fail("Read projection attempted full document verification")

    monkeypatch.setattr(sync_documents, "verify_document", forbidden)
    monkeypatch.setattr(BlobStore, "verified_path", forbidden)
    assert read(path, [verified])["assets"][0]["availability"] == "available"
    with pytest.raises(ValueError, match="verification snapshots"):
        read(path, [{"available": True}])


def test_received_manifest_advances_cursor_without_local_bytes_or_url_fetch(tmp_path):
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
    prepare(path, workspace_id="workspace", device_id="device")
    client = SyncClient(
        Journal(path, workspace_id="workspace", device_id="device"), research_writer
    )
    service = ReferenceService(tmp_path / "service.db", blob_root=tmp_path / "authority-blobs")
    token = service.enroll("workspace", "device")
    client.save(client.new_graph_operation("paper", PAPER, paper_payload()))
    client.sync_once(service, token)
    data = pdf_bytes()
    meta = payload(data)
    upload = service.blob_begin(token, {"sha256": meta["sha256"], "size": meta["size"]})
    service.blob_append(token, upload["upload_id"], 0, data)
    service.blob_commit(token, upload["upload_id"])
    value = client.new_graph_operation("paper_document", PAPER, meta)
    event = service.push(token, value)
    client.receive(service.pull(token, after=1))
    manifest = read(path)
    assert manifest["cursor"] == event["sequence"]
    assert manifest["papers"][0]["document"]["sync_state"] == "synced"
    assert manifest["assets"][0]["availability"] == "unchecked"
    assert applied(path) is None
    with sqlite3.connect(path) as conn:
        assert desired_document(conn, PAPER)["operation_id"] == value["operation_id"]
        assert conn.execute("SELECT state FROM research_document_intents").fetchall() == [
            ("pending",)
        ]


def test_manifest_identity_and_cursor_use_one_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "research.db"
    journal, data = database(path), pdf_bytes()
    save(journal, document(data))
    SyncClient(journal, research_writer)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    old = target(path)
    changed, original = False, sqlite3.connect

    def connect(*args, **kwargs):
        conn = original(*args, **kwargs)

        def trace(statement):
            nonlocal changed
            if not changed and "FROM research_document_desired" in statement:
                changed = True
                fresh = dict(old, operation_id="updated", sha256="b" * 64)
                with original(path) as writer:
                    writer.execute(
                        "UPDATE research_document_desired SET target=?", (json.dumps(fresh),)
                    )
                    writer.execute("UPDATE paperfact_sync_cursor SET sequence=1")

        conn.set_trace_callback(trace)
        return conn

    monkeypatch.setattr(sync_projection.sqlite3, "connect", connect)
    first = read(path)
    assert changed and first["cursor"] == 0
    assert first["papers"][0]["document"]["desired"]["sha256"] == old["sha256"]
    second = read(path)
    assert (
        second["cursor"] == 1 and second["papers"][0]["document"]["desired"]["sha256"] == "b" * 64
    )


def test_document_records_obey_limits_and_orphans_are_not_silently_dropped(tmp_path):
    path = tmp_path / "research.db"
    journal, data = database(path), pdf_bytes()
    save(journal, document(data))
    with pytest.raises(ValueError, match="record limit"):
        read_manifest(path, workspace_id="workspace", schema_version=2, max_records=5)
    # DTO1's five original source records remain within its unchanged limit.
    assert read_manifest(path, workspace_id="workspace", max_records=5)["schema_version"] == 1
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE research_document_desired SET paper_id='unknown-paper'")
    with pytest.raises(ValueError, match="unresolved paper reference"):
        read(path)
