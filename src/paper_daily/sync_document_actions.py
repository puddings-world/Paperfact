"""Explicit local PDF staging and retry-safe research intent; no reader replacement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_documents import MAX_PDF_BYTES, validate_manifest, verify_document
from paper_daily.sync_journal import _identifier


def stage_file(store: BlobStore, path: Path) -> BlobManifest:
    """Copy an explicitly selected file into owned immutable bytes, off the UI thread.

    This checks byte identity, not PDF readability. attach_document validates the
    actual PDF before any research intent is recorded. No URL fetching is allowed.
    """
    if not isinstance(store, BlobStore):
        raise ValueError("An explicitly owned BlobStore is required")
    source = Path(path)
    if not source.is_file() or not 0 < source.stat().st_size <= MAX_PDF_BYTES:
        raise ValueError("Select a nonempty file of at most 150 MiB")
    digest, size = hashlib.sha256(), 0
    with source.open("rb") as stream:
        while chunk := stream.read(256 * 1024):
            size += len(chunk)
            if size > MAX_PDF_BYTES:
                raise ValueError("Selected file exceeds 150 MiB")
            digest.update(chunk)
    manifest = BlobManifest(digest.hexdigest(), size)
    state = store.begin(manifest)
    if not state["complete"]:
        # Read from the start so overlap is verified against the same digest.
        with source.open("rb") as stream:
            offset = 0
            while chunk := stream.read(min(store.chunk_bytes, 256 * 1024)):
                store.append(manifest, offset, chunk)
                offset += len(chunk)
        store.finalize(manifest)
    return manifest


def attach_document(actions, paper_id, manifest, *, store, request_id, _legacy=None):
    """Commit one manifest and outbox operation after verifying immutable PDF bytes.

    File validation happens outside the write transaction. Rebuilding the target
    inside it rejects a concurrent paper/document incarnation change. An exact
    action retry returns its original receipt without rewinding newer content.
    """
    _identifier(request_id)
    if not isinstance(manifest, BlobManifest):
        raise ValueError("Expected a staged BlobManifest")
    payload = {
        "paper_id": paper_id,
        "sha256": manifest.sha256,
        "size": manifest.size,
        "media_type": "application/pdf",
    }
    validate_manifest(payload, paper_id=paper_id)
    legacy = None
    request = {"mode": "attach_document", **payload}
    if _legacy is not None:
        from paper_daily.legacy_primary_migration import validate_for_attach

        legacy = validate_for_attach(_legacy, actions, paper_id, manifest, store, request_id)
        request = {"mode": "migrate_legacy_primary", **payload, "observation": legacy.fingerprint}
    fingerprint = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    journal = actions.client.journal

    def receipt(conn):
        row = conn.execute(
            "SELECT fingerprint,result FROM research_action_receipts WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if row is not None and row[0] != fingerprint:
            raise ValueError("Research action retry changed its content")
        return json.loads(row[1]) if row else None

    def build(conn):
        graph = actions.client._optimistic_graph(conn)[0]
        old = graph.get(("paper_document", paper_id))
        parent = graph.get(("paper", paper_id))
        if parent is None or not parent["active"]:
            raise ValueError("A document requires an active portable paper")
        parents = [{"kind": "paper", "id": paper_id, "incarnation": parent["incarnation"]}]
        restore = old is not None and (not old["active"] or old["parents"] != parents)
        return actions.client.new_graph_operation_in(
            conn,
            "paper_document",
            paper_id,
            payload,
            operation_id=actions._id(request_id, "document-op"),
            restore=restore,
        )

    def target(operation):
        return {
            **payload,
            "workspace_id": journal.workspace_id,
            "operation_id": operation["operation_id"],
            "incarnation": operation["incarnation"],
            "parent_incarnation": operation["parents"][0]["incarnation"],
        }

    with journal.transaction() as conn:
        previous = receipt(conn)
        if previous is not None:
            if legacy is not None:
                legacy._replay_in(conn, previous)
            return previous
        if legacy is not None:
            legacy._check_in(conn)
        operation = build(conn)
    expected = target(operation)
    verified = verify_document(store, expected)

    def publish():
        with journal.transaction() as conn:
            previous = receipt(conn)
            if previous is not None:
                if legacy is not None:
                    legacy._replay_in(conn, previous)
                return previous
            if legacy is not None:
                legacy._check_in(conn)
            current = build(conn)
            if current != operation or not verified.matches(expected):
                raise ValueError("Document changed while verifying; retry the action")
            journal.apply_in(conn, current, actions.client.writer)
            if legacy is not None:
                legacy._bind_in(conn, target(current), verified)
            result = {"paper_id": paper_id, "operation_id": current["operation_id"], **payload}
            encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
            if legacy is not None:
                legacy._before_receipt(conn, target(current))
            conn.execute(
                "INSERT INTO research_action_receipts VALUES(?,?,?)",
                (request_id, fingerprint, encoded),
            )
            return json.loads(encoded)

    return legacy._publish(publish) if legacy is not None else publish()
