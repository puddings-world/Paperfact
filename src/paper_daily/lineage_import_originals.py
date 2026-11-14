"""Exact imported Lineage originals; native receipts are not sender/AI authority.

Workers verify immutable bytes. Delivery rechecks the actual loaded native owner,
selected cohort, current scientific row and all exact local source associations.
No model, download, source grant, source fallback or recovery adoption is performed.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field

from paper_daily import claim_content, file_change, lineage_packages, lineage_sets, source_snapshots
from paper_daily import lineage_package_publish as publisher
from paper_daily import lineage_package_targets as targets
from paper_daily import local_source_owners as owners
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker
from paper_daily.manual_highlight_ops import HighlightOwner, _readonly_connection
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.workspace_service import _binding, _tables

_KEY = secrets.token_bytes(32)


def has_record(database, row):
    """Receipt selection only; an existing record is not a source permission."""
    with closing(_readonly_connection(database)) as conn:
        conn.execute("BEGIN")
        return publisher.current_in(conn, row) is not None


def _state(conn, owner, row, source_id):
    owner.check(conn)
    if (
        generation._binding(conn) is not None
        or _binding(conn, _tables(conn))
        or targets._target_rows(conn, [row]) != [row]
    ):
        raise ValueError("Imported Lineage paper or workspace changed")
    action = publisher.current_in(conn, row)
    if action is None or action["database_identity"] != generation._identity(owner.database):
        raise ValueError("Imported Lineage lacks its current native receipt")
    item = next(r for r in action["records"] if r["row_json"] == lineage_packages._json(row))
    saved = lineage_sets.decode(row["body_json"])
    selected = {b["paper_id"] for b in saved["bindings"]}
    parents = [p for p in action["parents"] if p["paper_id"] in selected]
    for parent in parents:
        if (
            parent_lifecycle(conn, "paper", parent["paper_id"]) != parent["parent_lifecycle"]
            or not conn.execute("SELECT 1 FROM papers WHERE id=?", (parent["paper_id"],)).fetchone()
        ):
            raise ValueError("Imported Lineage selected paper lifetime changed")
    if not publisher._schema(conn, owners.TABLE, owners.COLUMNS):
        raise ValueError("Imported Lineage original associations are missing")
    for original in item["sources"]:
        if publisher._association(conn, original) != original:
            raise ValueError("Imported Lineage original association changed")
    source = next((s for s in saved["report"]["sources"] if s["id"] == source_id), None)
    if source is None:
        raise ValueError("Imported Lineage source is outside the displayed corpus")
    metadata = lineage_packages._json(
        dict(
            row=row,
            request_id=action["request_id"],
            fingerprint=action["fingerprint"],
            parents=parents,
            originals=item["sources"],
        )
    )
    if source["availability"] == "unavailable":
        return metadata, None, None
    available = [
        (b, s)
        for b, s in zip(saved["bindings"], saved["report"]["sources"], strict=True)
        if s["availability"] == "available"
    ]
    index = next(i for i, (_binding_row, s) in enumerate(available) if s["id"] == source_id)
    return metadata, item["sources"][index], available[index][0]["paper_id"]


def _seal(owner, metadata, source_id, document_hash, paper_id, path, version, data):
    value = [
        id(owner),
        str(owner.database),
        owner.paper_id,
        owner._json,
        metadata,
        source_id,
        document_hash,
        paper_id,
        str(path),
        version,
        id(data),
        os.getpid(),
    ]
    return hmac.new(_KEY, lineage_packages._json(value).encode(), "sha256").hexdigest()


@dataclass(frozen=True, slots=True)
class Original:
    _owner: HighlightOwner = field(repr=False)
    _metadata: str = field(repr=False)
    source_id: str
    document_hash: str
    paper_id: str
    _source: object = field(repr=False)
    _version: tuple = field(repr=False)
    _data: bytes = field(repr=False)
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
                snapshot.document_hash,
                snapshot.paper_id,
                snapshot._source,
                snapshot._version,
                snapshot._data,
            ),
        )
    ):
        raise ValueError("Imported Lineage original requires its native verified snapshot")
    return json.loads(snapshot._metadata)


def metadata_current(snapshot):
    """Native/SQL/file metadata only; never reopen/hash a PDF or write SQL."""
    try:
        expected = _checked(snapshot)
        with closing(_readonly_connection(snapshot._owner.database)) as conn:
            conn.execute("BEGIN")
            metadata, _original, _paper = _state(
                conn, snapshot._owner, expected["row"], snapshot.source_id
            )
        return (
            metadata == snapshot._metadata
            and file_change.version(snapshot._source) == snapshot._version
        )
    except (ValueError, TypeError, OSError, sqlite3.Error):
        return False


def prepare(owner, expected, source_id, *, cancelled=lambda: False):
    """Worker-only exact imported-result read; None means unavailable/cancelled."""
    _worker()
    lineage_sets.validate_row(expected)
    if not isinstance(owner, HighlightOwner) or expected["paper_id"] != owner.paper_id:
        raise ValueError("Imported Lineage needs the actual loaded paper owner")
    claim_content.digest(source_id)
    if cancelled():
        return None
    with closing(_readonly_connection(owner.database)) as conn:
        conn.execute("BEGIN")
        metadata, original, paper = _state(conn, owner, expected, source_id)
    if original is None or cancelled():
        return None
    path = source_snapshots.source_path(owner.database, original)
    try:
        verified = owners._read_pdf(path, original["sha256"], original["size"], cancelled)
    except (ValueError, OSError) as exc:
        raise ValueError("Imported Lineage exact original is missing or changed") from exc
    if verified is None:
        return None
    data, version = verified
    snapshot = Original(
        owner,
        metadata,
        source_id,
        original["sha256"],
        paper,
        path,
        version,
        data,
        _seal(owner, metadata, source_id, original["sha256"], paper, path, version, data),
    )
    if cancelled():
        return None
    if not metadata_current(snapshot):
        raise ValueError("Imported Lineage ownership changed during verification")
    return snapshot


def for_delivery(snapshot, owner, expected, source_id):
    """Deliver immutable bytes only to the identical still-current loaded view."""
    data = _checked(snapshot)
    if (
        owner is not snapshot._owner
        or expected != data["row"]
        or source_id != snapshot.source_id
        or not metadata_current(snapshot)
    ):
        raise ValueError("Loaded imported Lineage view changed before original delivery")
    return snapshot._data
