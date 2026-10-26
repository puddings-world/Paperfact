"""Document manifests synchronize independently of local attachment availability."""

import hashlib
import json
import sqlite3
from uuid import NAMESPACE_URL, uuid5

import pytest

from paper_daily.sync_blob_service import BlobUnavailableError
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_service import ReferenceService

PAPER = str(uuid5(NAMESPACE_URL, "paperfact-document-fixture"))
PDF = b"%PDF-1.7 synthetic fixture only"


def paper_payload(title="Paper"):
    return {
        "title": title,
        "authors": [],
        "year": 2026,
        **{
            key: None
            for key in (
                "venue",
                "abstract",
                "doi",
                "arxiv_id",
                "s2_id",
                "page_url",
                "pdf_url",
                "source",
            )
        },
    }


def document_payload(data=PDF):
    return {
        "paper_id": PAPER,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "media_type": "application/pdf",
    }


def writer(conn, operation):
    key = (operation["entity_type"], operation["entity_id"])
    if operation["action"] == "delete":
        conn.execute("DELETE FROM research WHERE kind=? AND id=?", key)
        return
    for parent in operation["parents"]:
        assert conn.execute(
            "SELECT 1 FROM research WHERE kind=? AND id=?", (parent["kind"], parent["id"])
        ).fetchone()
    conn.execute(
        "INSERT INTO research VALUES(?,?,?) ON CONFLICT(kind,id) "
        "DO UPDATE SET payload=excluded.payload",
        (*key, json.dumps(operation["payload"])),
    )


def client(path, device):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE research(kind,id,payload,PRIMARY KEY(kind,id))")
    return SyncClient(Journal(path, workspace_id="workspace", device_id=device), writer)


def saved(side, kind="paper_document", identity=PAPER):
    with sqlite3.connect(side.journal.path) as conn:
        row = conn.execute(
            "SELECT payload FROM research WHERE kind=? AND id=?", (kind, identity)
        ).fetchone()
    return json.loads(row[0]) if row else None


def save(side, kind, identity, payload, **kwargs):
    operation = side.new_graph_operation(kind, identity, payload, **kwargs)
    side.save(operation)
    return operation


def upload(server, token, data=PDF):
    description = {key: document_payload(data)[key] for key in ("sha256", "size")}
    begun = server.blob_begin(token, description)
    if not begun["complete"]:
        server.blob_append(token, begun["upload_id"], 0, data)
        server.blob_commit(token, begun["upload_id"])


@pytest.fixture
def pair(tmp_path):
    server = ReferenceService(tmp_path / "service.db", blob_root=tmp_path / "authority-blobs")
    a, b = client(tmp_path / "a.db", "a"), client(tmp_path / "b.db", "b")
    ta, tb = server.enroll("workspace", "a"), server.enroll("workspace", "b")
    upload(server, ta)
    return server, a, b, ta, tb


def transfer(pair):
    server, a, b, ta, tb = pair
    a.sync_once(server, ta)
    b.sync_once(server, tb)


@pytest.mark.parametrize("phase", ["pending", "acknowledged", "received"])
def test_document_builder_uses_pending_or_received_parent_and_receives_without_bytes(pair, phase):
    server, a, b, ta, _ = pair
    root = save(a, "paper", PAPER, paper_payload())
    if phase == "acknowledged":
        receipt = server.push(ta, root)
        a.journal.acknowledge(root["operation_id"], receipt["sequence"])
    elif phase == "received":
        transfer(pair)
    document = save(a, "paper_document", PAPER, document_payload())
    save(a, "paper", PAPER, paper_payload("Renamed after document"))
    save(a, "note", "annotation", {"paper_id": PAPER, "body": "Unrelated note"})
    transfer(pair)
    assert document["parents"] == [
        {"kind": "paper", "id": PAPER, "incarnation": root["incarnation"]}
    ]
    assert saved(a) == saved(b) == document_payload()
    assert saved(b, "paper")["title"] == "Renamed after document"
    assert saved(b, "note", "annotation")["body"] == "Unrelated note"
    assert b.status()["cursor"] == 4 and b.status()["deferred"] == 0
    # The client has no PDF store or reader path and does not fetch external URLs.
    assert not (b.journal.path.parent / "local-blobs").exists()


@pytest.mark.parametrize("mutation", ["wrong_id", "wrong_incarnation", "deleted_parent"])
def test_raw_document_parent_guard_prevents_local_and_outbox_mutation(pair, mutation):
    _, a, _, _, _ = pair
    save(a, "paper", PAPER, paper_payload())
    operation = a.new_graph_operation("paper_document", PAPER, document_payload())
    if mutation == "wrong_id":
        operation["parents"][0]["id"] = str(uuid5(NAMESPACE_URL, "different-paper"))
    elif mutation == "wrong_incarnation":
        operation["parents"][0]["incarnation"] = "unknown-incarnation"
    else:
        # Simulate an unavailable parent in the accepted fixture graph, not a paper
        # delete operation (paper deletion remains outside the graph contract).
        with a.journal.transaction() as conn:
            conn.execute("DELETE FROM paperfact_sync_operations")
    pending = a.journal.pending()
    with pytest.raises(ValueError):
        a.save(operation)
    assert a.journal.pending() == pending
    assert saved(a) is None


def test_delete_then_explicit_restore_uses_new_document_incarnation(pair):
    _, a, b, _, _ = pair
    save(a, "paper", PAPER, paper_payload())
    first = save(a, "paper_document", PAPER, document_payload())
    transfer(pair)
    save(a, "paper_document", PAPER, {}, action="delete")
    transfer(pair)
    assert saved(a) == saved(b) is None
    with pytest.raises(ValueError, match="restore=True"):
        a.new_graph_operation("paper_document", PAPER, document_payload())
    restored = save(a, "paper_document", PAPER, document_payload(), restore=True)
    transfer(pair)
    assert restored["incarnation"] != first["incarnation"]
    assert saved(a) == saved(b) == document_payload()


def test_pending_document_update_preserves_local_data_until_delete_conflict_received(pair):
    server, a, b, ta, tb = pair
    save(a, "paper", PAPER, paper_payload())
    save(a, "paper_document", PAPER, document_payload())
    transfer(pair)
    replacement = PDF + b"replacement"
    upload(server, tb, replacement)
    pending = save(b, "paper_document", PAPER, document_payload(replacement))
    save(a, "paper_document", PAPER, {}, action="delete")
    a.sync_once(server, ta)
    b.receive(server.pull(tb, after=b.status()["cursor"]))
    assert saved(b) == pending["payload"]
    assert b.status()["pending"] == 1
    b.sync_once(server, tb)
    assert saved(b) is None
    assert b.history(conflicts_only=True)[0]["operation"] == pending
    b.resolve_conflict(b.history(conflicts_only=True)[0]["sequence"], restore=True)
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    assert saved(a) == saved(b) == document_payload(replacement)


def test_low_level_sync_missing_authority_bytes_is_retryable_without_receipt(pair):
    server, a, b, ta, _ = pair
    save(a, "paper", PAPER, paper_payload())
    replacement = PDF + b"not uploaded yet"
    operation = save(a, "paper_document", PAPER, document_payload(replacement))
    with pytest.raises(BlobUnavailableError):
        a.sync_once(server, ta)
    assert any(item["operation_id"] == operation["operation_id"] for item in a.journal.pending())
    assert len(server.pull(ta)) == 1  # root accepted; missing document allocates no event
    assert saved(a) == document_payload(replacement)
    upload(server, ta, replacement)
    transfer(pair)
    assert saved(b) == document_payload(replacement)


def test_document_projection_failure_rolls_back_all_incoming_metadata(pair):
    server, a, b, ta, tb = pair
    save(a, "paper", PAPER, paper_payload())
    save(a, "paper_document", PAPER, document_payload())
    a.sync_once(server, ta)

    def failing(conn, operation):
        writer(conn, operation)
        if operation["entity_type"] == "paper_document":
            raise RuntimeError("synthetic database failure")

    b.writer = failing
    with pytest.raises(RuntimeError, match="database failure"):
        b.sync_once(server, tb)
    assert b.status()["cursor"] == 0
    assert saved(b) is None and saved(b, "paper") is None
    b.writer = writer
    b.sync_once(server, tb)
    assert saved(b) == document_payload()


def test_same_transaction_paper_and_document_builder(pair):
    _, a, _, _, _ = pair
    with a.journal.transaction() as conn:
        root = a.new_graph_operation_in(conn, "paper", PAPER, paper_payload())
        a.journal.apply_in(conn, root, writer)
        document = a.new_graph_operation_in(conn, "paper_document", PAPER, document_payload())
        a.journal.apply_in(conn, document, writer)
    assert saved(a) == document_payload()
    assert document["parents"][0]["incarnation"] == root["incarnation"]


def test_prepare_push_skips_document_chain_but_pushes_unrelated_note_and_pulls(pair):
    server, a, b, ta, tb = pair
    save(b, "list", "remote-list", {"name": "Remote research", "note": ""})
    b.sync_once(server, tb)
    save(a, "paper", PAPER, paper_payload())
    first = save(a, "paper_document", PAPER, document_payload())
    second = save(a, "paper_document", PAPER, document_payload())
    save(a, "note", "independent-note", {"paper_id": PAPER, "body": "Local note"})
    seen = []

    def prepare(operation):
        seen.append(operation["operation_id"])
        return operation["entity_type"] != "paper_document"

    result = a.sync_once(server, ta, prepare_push=prepare)
    assert result["deferred_push"] == 2 and result["pushed"] == 2
    assert second["operation_id"] not in seen
    assert saved(a, "list", "remote-list")["name"] == "Remote research"
    assert [item["operation_id"] for item in a.journal.pending()] == [
        first["operation_id"],
        second["operation_id"],
    ]
    result = a.sync_once(server, ta, prepare_push=lambda _: True)
    assert result["deferred_push"] == 0 and result["pushed"] == 2
    b.sync_once(server, tb)
    assert saved(b) == document_payload()


def test_prepare_push_propagates_parent_creation_and_structural_dependencies(pair):
    server, a, _, ta, _ = pair
    root = save(a, "paper", PAPER, paper_payload())
    save(a, "paper_document", PAPER, document_payload())
    save(a, "paper", PAPER, paper_payload("Later title"))
    save(a, "list", "unrelated", {"name": "Independent", "note": ""})
    result = a.sync_once(
        server, ta, prepare_push=lambda op: op["operation_id"] != root["operation_id"]
    )
    assert result["deferred_push"] == 3 and result["pushed"] == 1
    assert [event["operation"]["entity_type"] for event in server.pull(ta)] == ["list"]


def test_prepare_callback_cannot_mutate_persisted_intent_or_sent_operation(pair):
    server, a, _, ta, _ = pair
    original = save(a, "paper", PAPER, paper_payload())

    def prepare(operation):
        operation["payload"]["title"] = "Injected title"
        return True

    with pytest.raises(ValueError, match="cannot change"):
        a.sync_once(server, ta, prepare_push=prepare)
    assert server.pull(ta) == []
    assert a.journal.pending() == [original]
    assert saved(a, "paper")["title"] == "Paper"


@pytest.mark.parametrize("outcome", ["error", "invalid_result"])
def test_prepare_error_is_visible_preserves_pending_and_releases_lock(pair, outcome):
    server, a, _, ta, _ = pair
    original = save(a, "paper", PAPER, paper_payload())

    def prepare(operation):
        if outcome == "error":
            raise PermissionError("session revoked")
        return None

    expected = PermissionError if outcome == "error" else ValueError
    with pytest.raises(expected):
        a.sync_once(server, ta, prepare_push=prepare)
    assert a.journal.pending() == [original]
    assert server.pull(ta) == []
    assert a.sync_once(server, ta)["pushed"] == 1


def test_http_document_push_missing_blob_is_retryable_and_metadata_only_receive(pair):
    from test_sync_http import running

    from paper_daily.sync_http import HttpTransport, make_server

    server, a, b, ta, tb = pair
    save(a, "paper", PAPER, paper_payload())
    replacement = PDF + b"HTTP retry"
    save(a, "paper_document", PAPER, document_payload(replacement))
    with running(make_server(server)) as url, HttpTransport(url) as transport:
        with pytest.raises(BlobUnavailableError):
            a.sync_once(transport, ta)
        assert len(server.pull(ta)) == 1
        upload(server, ta, replacement)
        a.sync_once(transport, ta)
        b.sync_once(transport, tb)
    assert saved(b) == document_payload(replacement)
    assert b.status()["cursor"] == 2
