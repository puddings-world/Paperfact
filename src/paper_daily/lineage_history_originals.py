"""Exact historical Lineage originals without report activation or source grants.

A selected retained publication/import/native put must still own its original
paper/source lifetimes. Scientific current-row visibility is not read permission.
Current-row reader contracts remain independent and unchanged.
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
    file_change,
    lineage_lifecycle,
    lineage_originals,
    lineage_package_publish,
    lineage_publication,
    lineage_sets,
    local_source_owners,
    source_snapshots,
    sync_artifacts,
    sync_source_files,
)
from paper_daily import position_source_snapshots as atomic_sources
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker
from paper_daily.manual_highlight_ops import HighlightOwner, _readonly_connection
from paper_daily.sync_content import _local_scope

_KEY = secrets.token_bytes(32)


def _state(conn, owner, row, origin, source_id):
    owner.check(conn)
    actual, scientific = lineage_lifecycle._origin_in(conn, owner, row, origin, sources=True)
    body = lineage_sets.decode(row["body_json"])
    selected = next((s for s in body["report"]["sources"] if s["id"] == source_id), None)
    if selected is None:
        raise ValueError("Historical source is outside the selected report")
    if selected["availability"] == "unavailable":
        return None, None, None
    binding = next(b for b in body["bindings"] if b["source_id"] == source_id)
    store = None
    if actual["kind"] == "native":
        for parent in scientific["parents"]:
            _local_scope(conn, dict(kind="paper", id=parent["id"]), required=True)
            projected = conn.execute(
                "SELECT incarnation FROM research_paper_projection WHERE sync_id=?", (parent["id"],)
            ).fetchone()
            if projected is None or projected[0] != parent["incarnation"]:
                raise ValueError("Historical selected paper projection changed")
        pin = next(p for p in scientific["source_dependencies"] if p["source_id"] == source_id)
        original = sync_artifacts.desired_file(conn, pin["file_id"])
        if (
            original is None
            or original["incarnation"] != pin["incarnation"]
            or original["parents"]
            != [next(p for p in scientific["parents"] if p["id"] == pin["paper_id"])]
            or original["payload"]["source_document_hash"] != selected["document_hash"]
            or not sync_artifacts.paper_current(conn, original)
        ):
            raise ValueError("Historical exact original is no longer owned locally")
        registered = sync_source_files._inspection_paths(conn)
        if registered is None:
            return None, None, None
        store = registered[0]
        provenance = dict(
            operation=scientific, original=original, storage=[str(store.root), str(registered[1])]
        )
    elif actual["kind"] == "generated":
        raw = lineage_publication._receipt(conn, actual["id"])
        receipt = dict(
            zip(("request_id", "candidate_id", "row_json", "sources_json"), raw, strict=True)
        )
        candidate = lineage_originals._candidate(conn, actual["id"])
        originals = json.loads(receipt["sources_json"])
        original = next(
            r for r in originals if json.loads(r["owner_json"])["source_id"] == source_id
        )
        if json.loads(original["owner_json"])["paper_id"] != binding["paper_id"]:
            raise ValueError("Historical original has a different selected owner")
        provenance = dict(publication=receipt, candidate=candidate, original=original)
    else:
        action = lineage_package_publish._read(conn, actual["id"])
        item = next(r for r in action["records"] if r["row_json"] == generation._json(row))
        original = next(
            r
            for r in item["sources"]
            if json.loads(r["owner_json"])["paper_id"] == binding["paper_id"]
            and r["sha256"] == selected["document_hash"]
        )
        provenance = dict(action=action, original=original)
    metadata = generation._json(dict(row=row, origin=actual, provenance=provenance))
    return metadata, original, store


def _seal(owner, metadata, source_id, data, path, version, receipt, receipt_version, closure):
    return hmac.new(
        _KEY,
        generation._json(
            [
                id(owner),
                str(owner.database),
                owner.paper_id,
                owner._json,
                metadata,
                source_id,
                id(data),
                str(path),
                version,
                str(receipt),
                receipt_version,
                id(closure),
                os.getpid(),
            ]
        ).encode(),
        "sha256",
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class Original:
    _owner: HighlightOwner = field(repr=False)
    _metadata: str = field(repr=False)
    source_id: str
    _data: bytes = field(repr=False)
    _path: object = field(repr=False)
    _version: object = field(repr=False)
    _receipt: object = field(repr=False)
    _receipt_version: object = field(repr=False)
    _closure: object = field(repr=False)
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
                snapshot._path,
                snapshot._version,
                snapshot._receipt,
                snapshot._receipt_version,
                snapshot._closure,
            ),
        )
    ):
        raise ValueError("Historical original requires its native verified snapshot")
    return json.loads(snapshot._metadata)


def metadata_current(snapshot):
    """Read-only source/lifetime/native metadata, never scientific activation or PDF hash."""
    try:
        expected = _checked(snapshot)
        with closing(_readonly_connection(snapshot._owner.database)) as conn:
            conn.execute("BEGIN")
            metadata, original, _store = _state(
                conn, snapshot._owner, expected["row"], expected["origin"], snapshot.source_id
            )
        if metadata != snapshot._metadata:
            return False
        if snapshot._closure is not None:
            return snapshot._closure.matches(original)
        return file_change.version(snapshot._path) == snapshot._version and (
            snapshot._receipt is None
            or file_change.version(snapshot._receipt) == snapshot._receipt_version
        )
    except (ValueError, TypeError, KeyError, StopIteration, OSError, sqlite3.Error):
        return False


def prepare(owner, expected, origin, source_id, *, cancelled=lambda: False):
    """Worker-only verified history read; no current-row requirement or write permission."""
    _worker()
    if not isinstance(owner, HighlightOwner):
        raise ValueError("Historical original requires its actual loaded owner")
    lineage_sets.validate_row(expected)
    claim_content.closed(origin, {"kind", "id"})
    claim_content.text(origin["kind"], 32)
    if origin["kind"] not in {"generated", "import", "native"}:
        raise ValueError("Unknown historical Lineage provenance")
    claim_content.text(origin["id"], 128)
    if not origin["id"]:
        raise ValueError("Missing historical Lineage origin")
    if expected["paper_id"] != owner.paper_id:
        raise ValueError("Historical original belongs to another loaded paper")
    claim_content.digest(source_id)
    if cancelled():
        return None
    with closing(_readonly_connection(owner.database)) as conn:
        conn.execute("BEGIN")
        metadata, original, store = _state(conn, owner, expected, origin, source_id)
    if metadata is None or cancelled():
        return None
    path = version = receipt = receipt_version = closure = None
    if origin["kind"] == "native":
        try:
            closure, _body, blobs = sync_artifacts.verify_closure(store, original)
        except FileNotFoundError:
            return None
        data = blobs[original["payload"]["source_document_hash"]]
    else:
        path = source_snapshots.source_path(owner.database, original)
        if origin["kind"] == "generated":
            receipt = source_snapshots.receipt_path(owner.database, original)
            receipt_version = file_change.version(receipt)
        verified = local_source_owners._read_pdf(
            path, original["sha256"], original["size"], cancelled
        )
        if verified is None:
            return None
        data, version = verified
        if origin["kind"] == "generated":
            verified_path, verified_version = atomic_sources.verify(
                owner.database, original, known_version=version
            )
            if (
                verified_path != path
                or verified_version != version
                or file_change.version(receipt) != receipt_version
            ):
                raise ValueError("Historical exact original changed during verification")
    snapshot = Original(
        owner,
        metadata,
        source_id,
        data,
        path,
        version,
        receipt,
        receipt_version,
        closure,
        _seal(owner, metadata, source_id, data, path, version, receipt, receipt_version, closure),
    )
    if cancelled():
        return None
    if not metadata_current(snapshot):
        raise ValueError("Historical original ownership changed during verification")
    return snapshot


def for_delivery(snapshot, owner, expected, source_id):
    """Return immutable original bytes only to the same still-authorized historical view."""
    metadata = _checked(snapshot)
    if (
        owner is not snapshot._owner
        or expected != metadata["row"]
        or source_id != snapshot.source_id
        or not metadata_current(snapshot)
    ):
        raise ValueError("Historical view changed before original delivery")
    return snapshot._data
