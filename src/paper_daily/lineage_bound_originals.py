"""Read-only exact originals for a bound Lineage projection.

The desktop adapter consumes these proofs without download, source grant,
primary activation or replay.
The projection is metadata; existing original ownership and verified bytes are
independent requirements. GUI delivery requires the actual loaded owner object.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field

from paper_daily import (
    claim_content,
    lineage_dependencies,
    lineage_projection,
    lineage_sets,
    lineage_wire,
    sync_artifacts,
    sync_source_files,
)
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker
from paper_daily.lineage_originals import _row
from paper_daily.manual_highlight_ops import HighlightOwner, _readonly_connection
from paper_daily.sync_content import _local_scope

_KEY = secrets.token_bytes(32)


def _metadata(conn, owner, expected, source_id):
    owner.check(conn)
    if _row(conn, owner.paper_id, expected["corpus_key"]) != expected:
        raise ValueError("Displayed bound Lineage result changed")
    raw = conn.execute(
        "SELECT entity_id FROM " + lineage_projection.TABLE + " WHERE paper_id=? AND corpus_key=?",
        (owner.paper_id, expected["corpus_key"]),
    ).fetchone()
    if raw is None:
        raise ValueError("Bound Lineage has no current projection provenance")
    marker, operation = lineage_projection._marker(conn, raw[0])
    client = getattr(conn, "_capture_client", None)
    if client is None:
        raise ValueError("Bound Lineage requires its existing capture binding")
    client.journal._binding(conn)
    if (
        operation["workspace_id"] != client.journal.workspace_id
        or marker["active"] != 1
        or marker["fingerprint"] != claim_content.hashed(expected)
        or lineage_wire.decode_row(conn, operation["payload"]) != expected
    ):
        raise ValueError("Bound Lineage projection no longer owns the displayed result")
    graph = client._optimistic_graph(conn)[0]
    if not lineage_dependencies.active(
        lambda kind, identity: graph.get((kind, identity)), operation
    ):
        raise ValueError("Bound Lineage selected source lifetime changed")
    for parent in operation["parents"]:
        _local_scope(conn, dict(kind="paper", id=parent["id"]), required=True)
        projected = conn.execute(
            "SELECT incarnation FROM research_paper_projection WHERE sync_id=?", (parent["id"],)
        ).fetchone()
        if projected is None or projected[0] != parent["incarnation"]:
            raise ValueError("Bound Lineage selected paper projection changed")
    sources = operation["payload"]["data"]["body_json"]["report"]["sources"]
    selected = next((s for s in sources if s["id"] == source_id), None)
    if selected is None:
        raise ValueError("Lineage source is not selected in the displayed corpus")
    if selected["availability"] == "unavailable":
        return None, None, None
    pin = next(p for p in operation["source_dependencies"] if p["source_id"] == source_id)
    original = sync_artifacts.desired_file(conn, pin["file_id"])
    if (
        original is None
        or original["incarnation"] != pin["incarnation"]
        or original["parents"]
        != [next(p for p in operation["parents"] if p["id"] == pin["paper_id"])]
        or not sync_artifacts.paper_current(conn, original)
    ):
        raise ValueError("Bound Lineage exact original is no longer owned locally")
    registered = sync_source_files._inspection_paths(conn)
    if registered is None:
        return None, None, None
    local = _local_scope(conn, dict(kind="paper", id=pin["paper_id"]), required=True)
    metadata = generation._json(
        dict(
            row=expected,
            marker=marker,
            original=original,
            local=local,
            storage=[str(registered[0].root), str(registered[1])],
        )
    )
    return metadata, original, registered[0]


def _seal(owner, metadata, source_id, data, proof):
    value = [
        id(owner),
        str(owner.database),
        owner.paper_id,
        owner._json,
        metadata,
        source_id,
        id(data),
        id(proof),
        os.getpid(),
    ]
    return hmac.new(_KEY, generation._json(value).encode(), "sha256").hexdigest()


@dataclass(frozen=True, slots=True)
class Original:
    _owner: HighlightOwner = field(repr=False)
    _metadata: str = field(repr=False)
    source_id: str
    _data: bytes = field(repr=False)
    _proof: object = field(repr=False)
    _seal: str = field(repr=False)


def _checked(snapshot):
    if (
        not isinstance(snapshot, Original)
        or not isinstance(snapshot._owner, HighlightOwner)
        or not isinstance(snapshot._data, bytes)
        or not isinstance(snapshot._seal, str)
        or not hmac.compare_digest(
            snapshot._seal,
            _seal(
                snapshot._owner,
                snapshot._metadata,
                snapshot.source_id,
                snapshot._data,
                snapshot._proof,
            ),
        )
    ):
        raise ValueError("Bound Lineage original requires its native verified snapshot")
    return json.loads(snapshot._metadata)


def metadata_current(snapshot):
    """Read-only SQL/native/file metadata guard; no byte hashing or model calls."""
    try:
        expected = _checked(snapshot)
        with closing(_readonly_connection(snapshot._owner.database)) as conn:
            conn.execute("BEGIN")
            metadata, operation, _store = _metadata(
                conn, snapshot._owner, expected["row"], snapshot.source_id
            )
        return metadata == snapshot._metadata and snapshot._proof.matches(operation)
    except (ValueError, TypeError, OSError, sqlite3.Error):
        return False


def prepare(owner, expected, source_id, *, cancelled=lambda: False):
    """Worker-only, saved-only source verification. Missing bytes never trigger AI/network."""
    _worker()
    if not isinstance(owner, HighlightOwner):
        raise ValueError("Bound Lineage requires the actual loaded paper owner")
    lineage_sets.validate_row(expected)
    claim_content.digest(source_id)
    if expected["paper_id"] != owner.paper_id:
        raise ValueError("Bound Lineage belongs to another loaded paper")
    if cancelled():
        return None
    with closing(_readonly_connection(owner.database)) as conn:
        conn.execute("BEGIN")
        metadata, operation, store = _metadata(conn, owner, expected, source_id)
    if metadata is None or cancelled():
        return None
    try:
        proof, _body, blobs = sync_artifacts.verify_closure(store, operation)
    except FileNotFoundError:
        return None
    data = blobs[operation["payload"]["source_document_hash"]]
    snapshot = Original(
        owner, metadata, source_id, data, proof, _seal(owner, metadata, source_id, data, proof)
    )
    if cancelled():
        return None
    if not metadata_current(snapshot):
        raise ValueError("Bound Lineage original ownership changed during verification")
    return snapshot


def for_delivery(snapshot, owner, expected, source_id):
    """Return immutable verified bytes only to the actual current loaded result."""
    metadata = _checked(snapshot)
    if (
        owner is not snapshot._owner
        or expected != metadata["row"]
        or source_id != snapshot.source_id
        or not metadata_current(snapshot)
    ):
        raise ValueError("Loaded bound Lineage view changed before original delivery")
    return snapshot._data
