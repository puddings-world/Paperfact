"""Immutable original-PDF artifacts; never a current-document activation intent.

The graph parent is the only portable owner authority. Private job receipts,
filesystem paths and database identities never enter this wire format.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from paper_daily.sync_files import (
    canonical_json,
    closed,
    descriptor,
    digest,
    file_id,
    read_json,
    uuid,
)
from paper_daily.sync_legacy_sources import MAX_FILE, path, validate_pdf

FEATURE = "original_source"
MAX_PDF_BYTES = MAX_FILE


def validate_manifest(payload):
    """Called after the common closed research-file envelope has been checked."""
    digest(payload["slot"])
    if payload["source_document_hash"] != payload["slot"]:
        raise ValueError("Original source hash does not match its immutable slot")
    rows = payload["assets"]
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("Original source requires exactly one PDF asset")
    row = rows[0]
    closed(row, {"id", "role", "sha256", "size", "media_type"})
    if (
        (row["id"], row["role"], row["sha256"], row["media_type"])
        != ("original", "original_pdf", payload["slot"], "application/pdf")
        or type(row["size"]) is not int
        or not 0 < row["size"] <= MAX_PDF_BYTES
    ):
        raise ValueError("Invalid bounded original PDF descriptor")
    body = payload["body"]
    digest(body["sha256"])
    if (
        type(body["size"]) is not int
        or not 0 < body["size"] <= 1024
        or body["media_type"] != "application/json"
    ):
        raise ValueError("Invalid bounded original source body")
    versions = payload["input_versions"]
    if versions != input_versions():
        raise ValueError("Original source artifacts cannot declare model input authority")


def input_versions():
    return {
        "schema_version": 1,
        "complete": False,
        "entities": [],
        "documents": [],
        "inputs_sha256": None,
    }


def encode(paper_id, data):
    """Trusted explicit bytes produce a closed manifest and its full blob closure."""
    uuid(paper_id)
    validate_pdf(data)
    sha = hashlib.sha256(data).hexdigest()
    body = canonical_json({"version": 1, "paper_id": paper_id, "document_hash": sha})
    body_desc = descriptor(body, "application/json")
    payload = {
        "paper_id": paper_id,
        "feature": FEATURE,
        "slot": sha,
        "format_version": 1,
        "source_document_hash": sha,
        "input_versions": input_versions(),
        "body": body_desc,
        "assets": [
            {"id": "original", "role": "original_pdf", **descriptor(data, "application/pdf")}
        ],
    }
    from paper_daily.sync_files import validate_payload

    validate_payload(payload)
    return payload, {body_desc["sha256"]: body, sha: data}


def validate_source_closure(payload, blobs):
    body = read_json(blobs[payload["body"]["sha256"]])
    closed(body, {"version", "paper_id", "document_hash"})
    if (
        type(body["version"]) is not int
        or body["version"] != 1
        or body["paper_id"] != payload["paper_id"]
        or body["document_hash"] != payload["source_document_hash"]
    ):
        raise ValueError("Original source body differs from its exact owner/hash")
    validate_pdf(blobs[body["document_hash"]])
    return body


def _parent(conn, client, paper_id):
    graph = client._optimistic_graph(conn)[0]
    parent = graph.get(("paper", paper_id))
    if parent is None or not parent["active"]:
        raise ValueError("Original source requires an active paper")
    return parent["incarnation"]


def publish(
    client, paper_id, source, *, document_hash, parent_incarnation, store, version_root, request_id
):
    """Publish explicitly selected immutable bytes against one observed paper epoch.

    Source is a trusted explicit local path, not a value decoded from a sync event.
    Bytes/closure are checked before the transaction; owner is checked again in it.
    Identical owner/hash calls reuse the original artifact instead of another job.
    """
    from paper_daily.sync_artifacts import (
        activate,
        desired_file,
        materialize,
        register_paths,
        stage_bytes,
    )
    from paper_daily.sync_journal import _identifier

    uuid(paper_id)
    digest(document_hash)
    _identifier(request_id)
    _identifier(parent_incarnation)
    with client.journal.transaction() as conn:
        if _parent(conn, client, paper_id) != parent_incarnation:
            raise ValueError("Original source paper incarnation changed")
    original = path(source)
    info = original.stat()
    if not original.is_file() or not 0 < info.st_size <= MAX_PDF_BYTES:
        raise ValueError("Original source exceeds its bounded bytes")
    with original.open("rb") as stream:
        data = stream.read(MAX_PDF_BYTES + 1)
    after = original.stat()

    def stable(item):
        return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)

    if len(data) != info.st_size or stable(after) != stable(info):
        raise ValueError("Original source changed during capture")
    if hashlib.sha256(data).hexdigest() != document_hash:
        raise ValueError("Original source differs from its declared digest")
    payload, blobs = encode(paper_id, data)
    identity = file_id(paper_id, FEATURE, document_hash)
    stage_bytes(store, blobs)
    with client.journal.transaction() as conn:
        if _parent(conn, client, paper_id) != parent_incarnation:
            raise ValueError("Original source paper incarnation changed")
        register_paths(conn, client.journal.workspace_id, store, version_root)
        prior = conn.execute(
            "SELECT operation FROM research_file_versions WHERE operation_id=?", (request_id,)
        ).fetchone()
        existing = desired_file(conn, identity)
        if prior:
            operation = json.loads(prior[0])
            if (
                operation["payload"] != payload
                or operation["parents"][0]["incarnation"] != parent_incarnation
                or operation["device_id"] != client.journal.device_id
            ):
                raise ValueError("Original source request identity was reused")
        elif (
            existing is not None
            and existing["payload"] == payload
            and existing["parents"][0]["incarnation"] == parent_incarnation
        ):
            operation = existing
        else:
            graph = client._optimistic_graph(conn)[0].get(("research_file", identity))
            parent = [{"kind": "paper", "id": paper_id, "incarnation": parent_incarnation}]
            operation = client.new_graph_operation_in(
                conn,
                "research_file",
                identity,
                payload,
                operation_id=request_id,
                restore=bool(graph and (not graph["active"] or graph["parents"] != parent)),
            )
            client.journal.apply_in(conn, operation, client.writer)
    directory = materialize(store, version_root, operation)
    with client.journal.transaction() as conn:
        if not activate(conn, operation, directory):
            raise ValueError("Original source target changed before publication")
    return operation


def resolved(conn, paper_id, document_hash):

    """Return verified inspectable bytes for this current paper epoch, or None.



    Does not modify the primary document binding or silently select another hash.

    """

    from paper_daily.sync_artifacts import (
        applied_file,
        desired_file,
        paper_current,
        verify_closure,
    )



    uuid(paper_id)

    digest(document_hash)

    identity = file_id(paper_id, FEATURE, document_hash)

    operation = applied_file(conn, identity)

    if (

        operation is None

        or operation != desired_file(conn, identity)

        or not paper_current(conn, operation)

    ):

        return None

    registered = _inspection_paths(conn)

    if registered is None:

        return None

    verified, _body, _blobs = verify_closure(registered[0], operation)

    from paper_daily.sync_blobs import BlobManifest



    asset = operation["payload"]["assets"][0]

    source = registered[0].verified_path(BlobManifest(document_hash, asset["size"]))

    if not verified.matches(operation):

        raise ValueError("Applied original source is missing or changed")

    return source


_SOURCE_SEAL = object()


@dataclass(frozen=True, init=False)
class PreparedClaimSource:
    context: str
    payload: str
    store: object
    root: object
    operation: object
    proof: object
    seal: object


def stage_claim_source(context, row):
    """Retain a declared accepted-output closure off the research write lock.

    Blob staging alone is private local storage. Only apply_claim_source_in grants
    a shared graph identity, in the accepted claim transaction.
    """
    if context.table != "paper_claim_sets" or context.data["binding"] is None:
        return None
    from contextlib import closing

    from paper_daily import research_generation as generation
    from paper_daily import source_snapshots
    from paper_daily.sync_artifacts import desired_file, stage_bytes, verify_closure
    from paper_daily.sync_blobs import BlobStore
    from paper_daily.workspace_service import _binding, _paths, _tables

    data = context.data
    if generation._identity(context.db_path) != data["database_identity"]:
        raise ValueError("Original source database changed before staging")
    with closing(generation._connect(context.db_path)) as conn:
        if generation._binding(conn) != data["binding"]:
            raise ValueError("Original source workspace changed before staging")
        tables = _tables(conn)
        blob_root, _legacy, registrations = _paths(conn, tables, _binding(conn, tables))
    receipt = next(
        (
            item
            for item in source_snapshots.list_owned(context.db_path)
            if item["request_id"] == context.request_id
        ),
        None,
    )
    if receipt is None or receipt["sha256"] != row["document_hash"]:
        raise ValueError("Declared claim original has no exact owned source receipt")
    owner = json.loads(receipt["owner_json"])
    parent = {key: data["observation"]["parents"][0][key] for key in ("kind", "id", "incarnation")}
    if (
        owner["paper_id"] != context.owner_id
        or owner["parent_lifecycle"] != data["parent_lifecycle"]
        or owner["source_owner_id"] != parent["id"]
    ):
        raise ValueError("Declared original source ownership changed")
    source = source_snapshots.source_path(context.db_path, receipt)
    if source.stat().st_size != receipt["size"]:
        raise ValueError("Declared original source bytes changed")
    with source.open("rb") as stream:
        original = stream.read(receipt["size"] + 1)
    if (
        len(original) != receipt["size"]
        or hashlib.sha256(original).hexdigest() != row["document_hash"]
    ):
        raise ValueError("Declared original source bytes changed")
    payload, blobs = encode(parent["id"], original)
    store = BlobStore(blob_root or context.db_path.parent / "blobs")
    roots = dict(registrations)
    root = (
        roots["research_file_paths"][2]
        if "research_file_paths" in roots
        else store.root / "research-versions"
    )
    stage_bytes(store, blobs)
    with closing(generation._connect(context.db_path)) as conn:
        conn.execute("BEGIN")
        client = conn._capture_client
        identity = file_id(parent["id"], FEATURE, payload["slot"])
        operation = desired_file(conn, identity)
        if not (operation and operation["payload"] == payload and operation["parents"] == [parent]):
            graph = client._optimistic_graph(conn)[0].get(("research_file", identity))
            request = "source:" + hashlib.sha256(context.request_id.encode()).hexdigest()
            operation = client.new_graph_operation_in(
                conn,
                "research_file",
                identity,
                payload,
                operation_id=request,
                restore=bool(graph and (not graph["active"] or graph["parents"] != [parent])),
            )
    proof, _body, _blobs = verify_closure(store, operation)
    prepared = object.__new__(PreparedClaimSource)
    for name, value in {
        "context": context._json,
        "payload": canonical_json(payload).decode(),
        "store": store,
        "root": root,
        "operation": operation,
        "proof": proof,
        "seal": _SOURCE_SEAL,
    }.items():
        object.__setattr__(prepared, name, value)
    return prepared


def apply_claim_source_in(conn, context, row, prepared):
    """Publish shared provenance atomically with the caller's accepted claim write."""
    if prepared is None:
        return
    from paper_daily import sync_capture
    from paper_daily.sync_artifacts import desired_file, register_paths

    if (
        not conn.in_transaction
        or not isinstance(prepared, PreparedClaimSource)
        or getattr(prepared, "seal", None) is not _SOURCE_SEAL
        or prepared.context != context._json
    ):
        raise ValueError("Original source staging lacks its captured publication authority")
    payload = read_json(prepared.payload.encode())
    if payload["slot"] != row["document_hash"]:
        raise ValueError("Original source staging differs from claim output")
    if not prepared.proof.matches(prepared.operation):
        raise ValueError("Original source bytes changed before shared publication")
    client = conn._capture_client
    observed_parent = {
        key: context.data["observation"]["parents"][0][key] for key in ("kind", "id", "incarnation")
    }
    if _parent(conn, client, payload["paper_id"]) != observed_parent["incarnation"]:
        raise ValueError("Original source parent incarnation changed")
    identity = file_id(payload["paper_id"], FEATURE, payload["slot"])
    current = desired_file(conn, identity)
    if (
        current is not None
        and current["payload"] == payload
        and current["parents"] == [observed_parent]
    ):
        return
    graph = client._optimistic_graph(conn)[0].get(("research_file", identity))
    request = "source:" + hashlib.sha256(context.request_id.encode()).hexdigest()
    operation = client.new_graph_operation_in(
        conn,
        "research_file",
        identity,
        payload,
        operation_id=request,
        restore=bool(graph and (not graph["active"] or graph["parents"] != [observed_parent])),
    )
    with sync_capture.suppress_capture(conn):
        register_paths(conn, client.journal.workspace_id, prepared.store, prepared.root)
        result = client.journal.apply_in(conn, operation, client.writer)
        if not result["applied"]:
            raise ValueError("Original source was not applied atomically")
    conn._capture_graph_cache = None


@dataclass(frozen=True, init=False)
class PreparedSource:
    """Native byte proof plus explicit local intent, never serialized authority."""

    database: object
    identity: tuple
    workspace: str
    device: str
    payload: str
    parent: str
    request: str
    store: object
    root: object
    proof: object
    proof_operation: object
    seal: object


def prepare_source(
    client, paper_id, source, *, document_hash, parent_incarnation, store, version_root, request_id
):
    """Stage an explicit PDF off-lock, including a planned not-yet-created paper.

    parent_incarnation is caller-owned observed/planned intent. This function does
    not declare the parent active; publish_source_in checks it in the caller's
    transaction. Its synthetic proof envelope is never journaled or shared.
    """
    from pathlib import Path

    from paper_daily.sync_artifacts import stage_bytes, verify_closure
    from paper_daily.sync_blobs import BlobStore
    from paper_daily.sync_journal import _identifier

    uuid(paper_id)
    digest(document_hash)
    _identifier(parent_incarnation)
    _identifier(request_id)
    if not isinstance(store, BlobStore):
        raise ValueError("An explicit owned BlobStore is required")
    database = client.journal.path.resolve(strict=True)
    with client.journal.transaction():
        info = database.stat()
        identity = (info.st_dev, info.st_ino)
    selected = path(source)
    info = selected.stat()
    if not selected.is_file() or not 0 < info.st_size <= MAX_PDF_BYTES:
        raise ValueError("Original source exceeds its bounded bytes")
    with selected.open("rb") as stream:
        original = stream.read(info.st_size + 1)
    after = selected.stat()

    def stable(value):
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns

    if stable(info) != stable(after) or hashlib.sha256(original).hexdigest() != document_hash:
        raise ValueError("Original source changed during explicit staging")
    payload, blobs = encode(paper_id, original)
    stage_bytes(store, blobs)
    operation = {
        "version": 2,
        "operation_id": request_id,
        "workspace_id": client.journal.workspace_id,
        "device_id": client.journal.device_id,
        "entity_type": "research_file",
        "entity_id": file_id(paper_id, FEATURE, document_hash),
        "action": "put",
        "base_revision": 0,
        "depends_on": None,
        "payload": payload,
        "incarnation": request_id,
        "parents": [{"kind": "paper", "id": paper_id, "incarnation": parent_incarnation}],
        "structure_revision": 0,
    }
    proof, _body, _blobs = verify_closure(store, operation)
    value = object.__new__(PreparedSource)
    fields = {
        "database": database,
        "identity": identity,
        "workspace": client.journal.workspace_id,
        "device": client.journal.device_id,
        "payload": canonical_json(payload).decode(),
        "parent": parent_incarnation,
        "request": request_id,
        "store": store,
        "root": Path(version_root).absolute(),
        "proof": proof,
        "proof_operation": operation,
        "seal": _SOURCE_SEAL,
    }
    for key, item in fields.items():
        object.__setattr__(value, key, item)
    return value


def check_prepared_source_in(conn, client, prepared):
    """Read-only native/binding/source verification; grants no ownership or write."""
    if (
        not conn.in_transaction
        or not isinstance(prepared, PreparedSource)
        or getattr(prepared, "seal", None) is not _SOURCE_SEAL
    ):
        raise ValueError("Original source lacks trusted explicit staging")
    database = client.journal.path.resolve(strict=True)
    info = database.stat()
    main = next((row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"), None)
    if (
        main is None
        or path(main) != database
        or prepared.database != database
        or prepared.identity != (info.st_dev, info.st_ino)
        or (prepared.workspace, prepared.device)
        != (client.journal.workspace_id, client.journal.device_id)
    ):
        raise ValueError("Original source database/workspace binding changed")
    client.journal._binding(conn)
    if not prepared.proof.matches(prepared.proof_operation):
        raise ValueError("Original source bytes changed after staging")
    payload = read_json(prepared.payload.encode())
    if payload != prepared.proof_operation["payload"]:
        raise ValueError("Original source staging payload changed")
    if _parent(conn, client, payload["paper_id"]) != prepared.parent:
        raise ValueError("Original source paper incarnation changed")
    return payload


def publish_source_in(conn, client, prepared):
    """Caller-owned transaction; no file I/O beyond native proof freshness checks.

    Research file/outbox ownership rolls back with the caller. Byte staging may
    remain as a harmless local cache; it grants no graph or current-PDF authority.
    """
    from paper_daily import sync_capture
    from paper_daily.sync_artifacts import desired_file, register_paths

    payload = check_prepared_source_in(conn, client, prepared)
    identity = file_id(payload["paper_id"], FEATURE, payload["slot"])
    parent = [{"kind": "paper", "id": payload["paper_id"], "incarnation": prepared.parent}]
    # A past publication receipt is not permission to use a now-retired source.
    graph = client._optimistic_graph(conn)[0].get(("research_file", identity))
    if graph and (not graph["active"] or graph["parents"] != parent):
        raise ValueError("Deleted or retired original requires explicit source restoration")
    prior = conn.execute(
        "SELECT operation FROM research_file_versions WHERE operation_id=?", (prepared.request,)
    ).fetchone()
    existing = desired_file(conn, identity)
    if prior:
        operation = json.loads(prior[0])
        if (
            operation["payload"] != payload
            or operation["parents"] != parent
            or operation["device_id"] != prepared.device
        ):
            raise ValueError("Original source request identity was reused")
        return operation
    if existing and existing["payload"] == payload and existing["parents"] == parent:
        return existing
    operation = client.new_graph_operation_in(
        conn, "research_file", identity, payload, operation_id=prepared.request
    )
    with sync_capture.suppress_capture(conn):
        register_paths(conn, prepared.workspace, prepared.store, prepared.root)
        result = client.journal.apply_in(conn, operation, client.writer)
        if not result["applied"]:
            raise ValueError("Original source was not applied atomically")
    if hasattr(conn, "_capture_graph_cache"):
        conn._capture_graph_cache = None
    return operation


def inspectable(conn, paper_id, document_hash):
    """Read an exact desired original already owned locally, without binding it.

    Full byte closure is verified on a worker. This grants no applied receipt,
    primary activation, peer authority or permission to inspect an old parent.
    """
    from paper_daily.sync_artifacts import desired_file, paper_current, verify_closure
    from paper_daily.sync_blobs import BlobManifest

    uuid(paper_id)
    digest(document_hash)
    identity = file_id(paper_id, FEATURE, document_hash)
    operation = desired_file(conn, identity)
    if operation is None or not paper_current(conn, operation):
        return None
    registered = _inspection_paths(conn)
    if registered is None:
        return None
    try:
        proof, _body, _blobs = verify_closure(registered[0], operation)
        asset = operation["payload"]["assets"][0]
        source = registered[0].verified_path(BlobManifest(document_hash, asset["size"]))
    except FileNotFoundError:
        return None
    if not proof.matches(operation):
        raise ValueError("Inspectable original source changed during verification")
    if desired_file(conn, identity) != operation or not paper_current(conn, operation):
        return None
    return source


def _inspection_paths(conn):
    """Use existing owned bytes without initializing a BlobStore on a read."""
    from paper_daily.workspace_service import _ReadOnlyStore, _safe_path

    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_file_paths'"
    ).fetchone():
        return None
    row = conn.execute(
        "SELECT workspace,blob_root,version_root FROM research_file_paths WHERE id=1"
    ).fetchone()
    if row is None:
        return None
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if binding is None or row[0] != binding[0]:
        raise ValueError("Original source storage belongs to another workspace")
    root = _safe_path(row[1])
    if not _safe_path(root / "index.sqlite").is_file():
        return None
    return _ReadOnlyStore(root), row[2]
