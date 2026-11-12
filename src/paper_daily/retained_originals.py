"""Read exact retained proposal originals without primary activation or AI.

The sealed proof is a local read capability, never a publication/source grant.
Worker preparation verifies the complete existing catalog. Later metadata checks
use bounded SQL/native/file versions, never parse or rehash a PDF on the GUI.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import local_deck_proposals as local
from paper_daily import research_file_review as files
from paper_daily import sync_capture
from paper_daily.sync_artifacts import desired_file, paper_current
from paper_daily.sync_files import canonical_json, digest, file_id

_SEAL = object()


@dataclass(frozen=True, init=False)
class RetainedOriginal:
    service: object = field(repr=False)
    preview: object = field(repr=False)
    proposal: object = field(repr=False)
    origin: str
    paper_id: str
    document_hash: str
    data: bytes = field(repr=False)
    source: Path = field(repr=False)
    file_version: tuple = field(repr=False)
    storage_root: Path = field(repr=False)
    witnesses: bytes = field(repr=False)
    operation: bytes | None = field(repr=False)
    _seal: object = field(repr=False)


def _connect(service):
    if service.closed or local._native(service.path) != tuple(service.identity):
        raise ValueError("Original review workspace is closed or was replaced")
    conn = sqlite3.connect(
        service.path.as_uri() + "?mode=ro",
        uri=True,
        factory=sync_capture.CaptureConnection,
        timeout=0.025,
    )
    conn.row_factory = sqlite3.Row
    return conn


def _metadata(conn, service, view, proposal, origin, document_hash):
    from paper_daily.research_review import digest as record_digest

    service._check(conn)
    record = service._record(conn, origin, view["id"])
    if record != proposal.record or record_digest(record) != view["record_hash"]:
        raise ValueError("Retained original proposal changed; reopen its review")
    owner = json.loads(record["owner_json"])
    if origin == "local_deck":
        local._scope(conn, owner, exact_row=False)
        return None
    from paper_daily import enrolled_deck_proposals as enrolled

    enrolled._scope(conn, proposal._owner, proposal._store, owner["target"], exact_row=False)
    operation = desired_file(conn, file_id(record["portable_id"], "original_source", document_hash))
    if operation is None or not paper_current(conn, operation):
        raise ValueError("Retained original source was removed or retired")
    return canonical_json(operation)


def metadata_current(proof):
    """No hashing, PDF parsing, schema creation or account lookup."""
    if not isinstance(proof, RetainedOriginal) or getattr(proof, "_seal", None) is not _SEAL:
        return False
    try:
        service = proof.service
        view = service._verify_preview(proof.preview)
        with closing(_connect(service)) as conn:
            conn.execute("BEGIN")
            operation = _metadata(
                conn,
                service,
                view,
                proof.proposal,
                proof.origin,
                proof.document_hash,
            )
            if operation != proof.operation:
                return False
        files._check_files(json.loads(proof.witnesses))
        with closing(local._connect(local._path(proof.storage_root / "index.sqlite"))) as conn:
            row = conn.execute(
                "SELECT size,complete FROM blobs WHERE digest=?",
                (proof.document_hash,),
            ).fetchone()
            if row is None or tuple(row) != (len(proof.data), 1):
                return False
        return True
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        return False


def prepare(service, preview, document_hash, *, cancelled=lambda: False):
    """Worker-only; select a declared original in this authenticated native proposal."""
    if cancelled():
        return None
    digest(document_hash)
    view = service._verify_preview(preview)
    origin = view["origin"]
    if origin not in {"local_deck", "enrolled_deck"} or service.recovery:
        raise ValueError("Select an owned retained presentation original")
    from paper_daily.proposal_recovery_review import virtual

    if virtual(view["id"]):
        raise ValueError("Verify the recovered proposal before opening its retained original")
    with closing(_connect(service)) as conn:
        conn.execute("BEGIN")
        service._check(conn)
        record = service._record(conn, origin, view["id"])
        from paper_daily.research_review import digest as record_digest

        if record_digest(record) != view["record_hash"]:
            raise ValueError("Retained slides changed; reload the preview")
        manifest = json.loads(record["manifest_json"])
        if not any(row["sha256"] == document_hash for row in manifest["originals"]):
            raise ValueError("The selected original is outside this retained proposal")
    if origin == "local_deck":
        proposal = local.read(
            service.path,
            view["id"],
            expected_native=service.identity,
            current=lambda: not cancelled() and not service.closed,
        )
        owner = json.loads(proposal.record["owner_json"])
        root = local._root(service.path, owner["native"])
        paper = proposal.record["paper_id"]
    else:
        from paper_daily import enrolled_deck_proposals as enrolled
        from paper_daily import enrolled_deck_review

        client, store, _root, _storage = enrolled_deck_review._context(service)
        proposal = enrolled.read(
            client,
            store,
            view["id"],
            expected_native=service.identity,
            current=lambda: not cancelled() and not service.closed,
        )
        root = proposal._store.root
        paper = proposal.record["local_id"]
    if cancelled():
        return None
    if not proposal.current_parent or proposal.record != record:
        raise ValueError("Retained original belongs to an old paper lifetime")
    source = local._path(root / "objects" / document_hash)
    version = next((version for path, version in proposal.witnesses if path == source), None)
    if version is None:
        raise ValueError("Retained original has no verified file witness")
    data = proposal.content["original_bytes"][document_hash]
    with closing(_connect(service)) as conn:
        conn.execute("BEGIN")
        operation = _metadata(conn, service, view, proposal, origin, document_hash)
    proof = object.__new__(RetainedOriginal)
    for name, value in dict(
        service=service,
        preview=preview,
        proposal=proposal,
        origin=origin,
        paper_id=paper,
        document_hash=document_hash,
        data=data,
        source=source,
        file_version=version,
        storage_root=root,
        witnesses=canonical_json({str(path): version for path, version in proposal.witnesses}),
        operation=operation,
        _seal=_SEAL,
    ).items():
        object.__setattr__(proof, name, value)
    if cancelled():
        return None
    if not metadata_current(proof):
        raise ValueError("Retained original changed before opening")
    return proof
