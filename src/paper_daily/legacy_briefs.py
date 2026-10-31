"""Closed exact legacy Markdown assets; paths and embedded text grant no authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from paper_daily import legacy_workflow
from paper_daily.sync_files import canonical_json, closed, digest, read_json, uuid
from paper_daily.sync_journal import _identifier

TARGETS = "research_legacy_brief_targets"
TARGET_COLUMNS = "event_key paper_id descriptor_json"
TARGET_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_legacy_brief_targets("
    "event_key TEXT PRIMARY KEY,paper_id TEXT NOT NULL,descriptor_json TEXT NOT NULL)"
)
BODY_FIELDS = {"version", "paper_id", "event_id", "event_incarnation", "legacy_day"}


def input_versions():
    return {
        "schema_version": 1,
        "complete": False,
        "entities": [],
        "documents": [],
        "inputs_sha256": None,
    }


def _day(value):
    if value is None:
        return
    if (
        not isinstance(value, str)
        or len(value) != 10
        or date.fromisoformat(value).isoformat() != value
    ):
        raise ValueError("Invalid declared legacy briefing date")


def validate_manifest(payload):
    uuid(payload["paper_id"])
    uuid(payload["slot"])
    from paper_daily.sync_files import validate_input_versions

    validate_input_versions(payload["input_versions"])
    if (
        payload["feature"] != "legacy_brief"
        or type(payload["format_version"]) is not int
        or payload["format_version"] != 1
        or payload["source_document_hash"] is not None
        or payload["input_versions"] != input_versions()
    ):
        raise ValueError("Invalid legacy brief file ownership/version")
    body = payload["body"]
    closed(body, {"sha256", "size", "media_type"})
    digest(body["sha256"])
    if (
        type(body["size"]) is not int
        or not 0 < body["size"] <= 4096
        or body["media_type"] != "application/json"
    ):
        raise ValueError("Invalid bounded legacy brief body")
    assets = payload["assets"]
    if not isinstance(assets, list) or len(assets) != 1:
        raise ValueError("Legacy brief requires exactly one Markdown asset")
    asset = assets[0]
    closed(asset, {"id", "role", "sha256", "size", "media_type"})
    if asset["id"] != "markdown" or asset["role"] != "markdown":
        raise ValueError("Unknown legacy brief asset role")
    legacy_workflow.validate_descriptor(
        {key: asset[key] for key in ("sha256", "size", "media_type")}
    )


def validate_body(body, payload):
    closed(body, BODY_FIELDS)
    if (
        type(body["version"]) is not int
        or body["version"] != 1
        or body["paper_id"] != payload["paper_id"]
        or body["event_id"] != payload["slot"]
    ):
        raise ValueError("Legacy brief body differs from its exact event/paper")
    uuid(body["paper_id"])
    uuid(body["event_id"])
    _identifier(body["event_incarnation"])
    _day(body["legacy_day"])
    return body


def validate_markdown(data):
    if not isinstance(data, bytes) or not 0 < len(data) <= legacy_workflow.MAX_BRIEF:
        raise ValueError("Legacy Markdown exceeds its bounded bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeError as error:
        raise ValueError("Legacy brief must be exact UTF-8 Markdown") from error
    if "\x00" in text:
        raise ValueError("Unsupported binary legacy Markdown")
    return text


def validate_closure(payload, blobs):
    validate_manifest(payload)
    body = read_json(blobs[payload["body"]["sha256"]])
    validate_body(body, payload)
    validate_markdown(blobs[payload["assets"][0]["sha256"]])
    return body


def encode(paper_id, event_id, event_incarnation, data, *, legacy_day=None):
    validate_markdown(data)
    body = {
        "version": 1,
        "paper_id": paper_id,
        "event_id": event_id,
        "event_incarnation": event_incarnation,
        "legacy_day": legacy_day,
    }
    from paper_daily.sync_files import descriptor

    encoded = canonical_json(body)
    metadata = descriptor(encoded, "application/json")
    asset = {"id": "markdown", "role": "markdown", **descriptor(data, "text/markdown")}
    payload = {
        "paper_id": paper_id,
        "feature": "legacy_brief",
        "slot": event_id,
        "format_version": 1,
        "source_document_hash": None,
        "input_versions": input_versions(),
        "body": metadata,
        "assets": [asset],
    }
    blobs = {metadata["sha256"]: encoded, asset["sha256"]: data}
    from paper_daily.sync_files import validate_closure as verify

    verify(payload, lambda row: blobs[row["sha256"]])
    return payload, blobs


def filename(body):
    _day(body["legacy_day"])
    return (body["legacy_day"] or "undated") + "-brief.md"


def target(conn, event_key):
    uuid(event_key)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TARGETS,)).fetchone():
        return None
    row = conn.execute(
        "SELECT event_key,CASE WHEN length(CAST(paper_id AS BLOB))<=4096 "
        "THEN paper_id END,CASE WHEN length(CAST(descriptor_json AS BLOB))<=1024 "
        "THEN descriptor_json END FROM " + TARGETS + " WHERE event_key=?",
        (event_key,),
    ).fetchone()
    if row is None:
        return None
    result = dict(zip(TARGET_COLUMNS.split(), row, strict=True))
    validate_target(result)
    return result


def validate_target(row):
    closed(row, TARGET_COLUMNS.split())
    uuid(row["event_key"])
    legacy_workflow._text(row["paper_id"], 4096)
    if not row["paper_id"]:
        raise ValueError("Legacy brief requires its exact paper identity")
    if not isinstance(row["descriptor_json"], str) or len(row["descriptor_json"].encode()) > 1024:
        raise ValueError("Legacy brief declaration exceeds its closed bound")
    legacy_workflow.validate_descriptor(read_json(row["descriptor_json"].encode()))
    return row


def declare_in(conn, event_key, local_paper, descriptor):
    if not conn.in_transaction:
        raise ValueError("Legacy brief declaration requires its caller transaction")
    row = {
        "event_key": event_key,
        "paper_id": local_paper,
        "descriptor_json": canonical_json(legacy_workflow.validate_descriptor(descriptor)).decode(),
    }
    validate_target(row)
    previous = target(conn, event_key)
    if previous and previous["paper_id"] != local_paper:
        raise ValueError("Legacy brief event cannot move between papers")
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TARGETS,)).fetchone():
        raise ValueError("Legacy brief capture schema is not initialized")
    conn.execute(
        "INSERT INTO " + TARGETS + " VALUES(?,?,?) ON CONFLICT(event_key) "
        "DO UPDATE SET descriptor_json=excluded.descriptor_json",
        tuple(row[key] for key in TARGET_COLUMNS.split()),
    )


def clear_in(conn, event_key):
    if target(conn, event_key) is not None:
        conn.execute("DELETE FROM " + TARGETS + " WHERE event_key=?", (event_key,))


def descriptor_for_row(conn, row, event_key):
    previous = target(conn, event_key)
    if row["brief_path"] is None:
        if event_key in getattr(conn, "_legacy_brief_clears", set()):
            return None
        return json.loads(previous["descriptor_json"]) if previous else None
    from paper_daily.sync_artifacts import applied_file, version_directory
    from paper_daily.sync_files import file_id

    portable = conn.execute(
        "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (row["paper_id"],)
    ).fetchone()[0]
    operation = applied_file(conn, file_id(portable, "legacy_brief", event_key))
    registered = registered_paths(conn)
    if previous and operation is not None and registered is not None:
        folder = version_directory(registered[1], operation)
        source = Path(row["brief_path"])
        if source.parent == folder and source.name.endswith("-brief.md"):
            return json.loads(previous["descriptor_json"])
    generated = getattr(conn, "_legacy_brief_buffers", {}).get(row["brief_path"])
    if generated is not None:
        if (
            getattr(generated, "seal", None) is not _BUFFER_SEAL
            or generated.paper_id != row["paper_id"]
            or generated.delivered_at != row["delivered_at"]
        ):
            raise ValueError("Generated legacy brief does not match its observed event")
        prepared = generated
    else:
        prepared = getattr(conn, "_legacy_brief_inputs", {}).get(row["id"])
    if prepared is not None:
        if generated is None and (
            (
                prepared.source != Path(row["brief_path"])
                and getattr(conn, "_legacy_brief_input_paths", {}).get(row["id"])
                != row["brief_path"]
            )
            or not prepared_current(prepared)
        ):
            raise ValueError("Prepared legacy brief changed before capture")
    else:
        raise ValueError("Legacy brief bytes require an explicit captured stage")
    if hasattr(conn, "_capture_client"):
        saved = getattr(conn, "_legacy_prepared_briefs", {})
        saved[event_key] = prepared
        conn._legacy_prepared_briefs = saved
    return prepared.descriptor


def registered_paths(conn):
    """Metadata only; readers must not create a BlobStore or research path table."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='research_file_paths'").fetchone():
        return None
    rows = conn.execute(
        "SELECT workspace,blob_root,version_root FROM research_file_paths LIMIT 2"
    ).fetchall()
    if not rows:
        return None
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if len(rows) != 1 or binding is None or rows[0][0] != binding[0]:
        raise ValueError("Legacy brief storage belongs to another workspace")
    return Path(rows[0][1]), Path(rows[0][2])


def _store(conn, client):
    from paper_daily.sync_artifacts import register_paths
    from paper_daily.sync_blobs import BlobStore
    from paper_daily.workspace_service import WorkspaceChanged, _binding, _paths, _tables

    # Reuse the maintained metadata-only reconciliation across PDF and artifact
    # registrations. A derived brief must not split an existing workspace store.
    tables = _tables(conn)
    try:
        root, _legacy, registrations = _paths(conn, tables, _binding(conn, tables))
    except WorkspaceChanged as error:
        raise WorkspaceChanged("Workspace storage requires explicit reconciliation") from error
    artifact = next((row for name, row in registrations if name == "research_file_paths"), None)
    if root is not None and (not root.is_dir() or not (root / "index.sqlite").is_file()):
        raise ValueError("Registered workspace storage is unavailable")
    store = BlobStore(root or client.journal.path.parent / "blobs")
    versions = Path(artifact[2]) if artifact else client.journal.path.parent / "research-versions"
    register_paths(conn, client.journal.workspace_id, store, versions)
    return store, versions


def _small_body(store, operation):
    from paper_daily.sync_blobs import BlobManifest

    payload = operation["payload"]
    validate_manifest(payload)
    row = payload["body"]
    try:
        path = store.verified_path(BlobManifest(row["sha256"], row["size"]))
    except FileNotFoundError:
        return None  # Metadata editing remains possible before explicit file download.
    if path is None:
        return None
    data = path.read_bytes()
    if len(data) != row["size"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise ValueError("Legacy brief metadata bytes changed")
    return validate_body(read_json(data), payload)


def publish_for_event(conn, client, event, previous=None):
    """Row metadata and its file intent share the caller's research transaction."""
    from uuid import NAMESPACE_URL, uuid5

    from paper_daily.sync_artifacts import desired_file, stage_bytes
    from paper_daily.sync_files import file_id

    value = event["payload"] if event["action"] == "put" else (previous or {}).get("payload", {})
    if value.get("feature") != "reading_event":
        return None
    key, paper = value["key"], event["parents"][0]["id"]
    identity = file_id(paper, "legacy_brief", key)
    current = desired_file(conn, identity)
    if event["action"] == "delete" or value["data"]["brief"] is None:
        if current is None:
            return None
        operation = client.new_graph_operation_in(
            conn, "research_file", identity, {}, action="delete"
        )
        client.journal.apply_in(conn, operation, client.writer)
    else:
        descriptor = value["data"]["brief"]
        store, _versions = _store(conn, client)
        if current and current["payload"]["assets"]:
            old = current["payload"]["assets"][0]
            if {name: old[name] for name in ("sha256", "size", "media_type")} == descriptor:
                body = _small_body(store, current)
                if body and body["event_incarnation"] == event["incarnation"]:
                    return current
        prepared = getattr(conn, "_legacy_prepared_briefs", {}).get(key)
        if prepared is None:
            # Metadata can be edited offline before this device has its files.
            return None
        if not prepared_current(prepared) or prepared.descriptor != descriptor:
            raise ValueError("Captured legacy brief changed before publication")
        payload, blobs = encode(
            paper, key, event["incarnation"], prepared.data, legacy_day=prepared.legacy_day
        )
        stage_bytes(store, blobs)
        operation_id = str(
            uuid5(
                NAMESPACE_URL,
                client.journal.workspace_id
                + ":legacy-brief:"
                + key
                + ":"
                + event["incarnation"]
                + ":"
                + payload["body"]["sha256"],
            )
        )
        graph = client._optimistic_graph(conn)[0].get(("research_file", identity))
        operation = client.new_graph_operation_in(
            conn,
            "research_file",
            identity,
            payload,
            operation_id=operation_id,
            restore=bool(graph and not graph["active"]),
        )
        client.journal.apply_in(conn, operation, client.writer)
    if getattr(conn, "_capture_graph_cache", None) is not None:
        client._overlay_optimistic(conn._capture_graph_cache, operation)
    return operation


def bind_in(conn, operation, materialized):
    """Current paper/event epoch + exact declaration, never a bare saved path."""
    from paper_daily.sync_content import content_id

    payload = operation["payload"]
    encoded = getattr(materialized, "_legacy_brief_body", None)
    if (
        not isinstance(encoded, bytes)
        or len(encoded) != payload["body"]["size"]
        or hashlib.sha256(encoded).hexdigest() != payload["body"]["sha256"]
    ):
        raise ValueError("Legacy brief requires its sealed materialized metadata")
    body = validate_body(read_json(encoded), payload)
    if set(materialized.files) != {"brief.json", filename(body)} or not materialized.matches(
        operation
    ):
        raise ValueError("Legacy brief materialization changed")
    marker = conn.execute(
        "SELECT incarnation,parent_incarnation FROM research_content_projection "
        "WHERE entity_id=? AND feature='reading_event' AND scope_id=? AND item_key=?",
        (
            content_id(
                {"kind": "paper", "id": payload["paper_id"]}, "reading_event", body["event_id"]
            ),
            payload["paper_id"],
            body["event_id"],
        ),
    ).fetchone()
    if marker is None or tuple(marker) != (
        body["event_incarnation"],
        operation["parents"][0]["incarnation"],
    ):
        return False
    mapping = conn.execute(
        "SELECT local_id,paper_id FROM research_content_identity "
        "WHERE feature='reading_event' AND sync_key=?",
        (body["event_id"],),
    ).fetchone()
    if mapping is None or mapping[0] is None:
        return False
    declaration = target(conn, body["event_id"])
    asset = payload["assets"][0]
    expected = {name: asset[name] for name in ("sha256", "size", "media_type")}
    if (
        declaration is None
        or declaration["paper_id"] != mapping[1]
        or json.loads(declaration["descriptor_json"]) != expected
    ):
        return False
    row = conn.execute("SELECT paper_id FROM reading_log WHERE id=?", (mapping[0],)).fetchone()
    if row is None or row[0] != mapping[1]:
        return False
    conn.execute(
        "UPDATE reading_log SET brief_path=? WHERE id=? AND paper_id=?",
        (str(materialized.path / filename(body)), mapping[0], mapping[1]),
    )
    return True


_BUFFER_SEAL = object()


@dataclass(frozen=True, init=False)
class _GeneratedBrief:
    data: bytes = field(repr=False)
    paper_id: str
    delivered_at: str
    legacy_day: str
    descriptor: dict
    seal: object = field(repr=False)


def prepared_current(value):
    if isinstance(value, _GeneratedBrief):
        return getattr(value, "seal", None) is _BUFFER_SEAL and value.descriptor == {
            "sha256": hashlib.sha256(value.data).hexdigest(),
            "size": len(value.data),
            "media_type": "text/markdown",
        }
    return legacy_workflow.brief_current(value)


def record_pack(conn, paper_id, delivered_at, role, data, *, legacy_day):
    """Atomic enrolled producer: immutable bytes, event and file intent, owned path.

    No mutable legacy path is published. Outer rollback drops all SQL authority;
    verified staged bytes left after failure cannot authorize an event themselves.
    """
    from uuid import uuid4

    from paper_daily.sync_artifacts import activate, desired_file, materialize, paths
    from paper_daily.sync_capture import _flush, enabled, suppress_capture
    from paper_daily.sync_content import _row_key
    from paper_daily.sync_files import file_id

    if not enabled(conn):
        raise ValueError("Owned brief production requires enrolled capture")
    legacy_workflow.require_ready(conn)
    validate_markdown(data)
    _day(legacy_day)
    legacy_workflow._time(delivered_at)
    value = object.__new__(_GeneratedBrief)
    for key, item in dict(
        data=data,
        paper_id=paper_id,
        delivered_at=delivered_at,
        legacy_day=legacy_day,
        seal=_BUFFER_SEAL,
        descriptor={
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "media_type": "text/markdown",
        },
    ).items():
        object.__setattr__(value, key, item)
    token = "legacy-pending:" + str(uuid4())
    buffers = getattr(conn, "_legacy_brief_buffers", {})
    buffers[token] = value
    conn._legacy_brief_buffers = buffers
    try:
        inserted = conn.execute(
            "INSERT INTO reading_log(paper_id,delivered_at,brief_path,role) VALUES(?,?,?,?)",
            (paper_id, delivered_at, token, role),
        )
        row = dict(
            conn.execute("SELECT * FROM reading_log WHERE id=?", (inserted.lastrowid,)).fetchone()
        )
        with suppress_capture(conn):
            key = _row_key(conn, "reading_log", row)
            _flush(conn)
            paper = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (paper_id,)
            ).fetchone()[0]
            operation = desired_file(conn, file_id(paper, "legacy_brief", key))
            if operation is None:
                raise ValueError("Generated brief file intent was not published")
            store, root = paths(conn)
            installed = materialize(store, root, operation)
            if not activate(conn, operation, installed):
                raise ValueError("Generated brief event changed before binding")
            return Path(
                conn.execute(
                    "SELECT brief_path FROM reading_log WHERE id=?", (inserted.lastrowid,)
                ).fetchone()[0]
            )
    except BaseException:
        conn.rollback()
        conn._capture_failed = True
        raise


def materialize_pending(client, store, root, *, ticket):
    from paper_daily.sync_artifacts import activate, materialize

    with client.journal.transaction() as conn:
        values = [
            json.loads(row[0])
            for row in conn.execute("SELECT operation FROM research_file_desired WHERE active=1")
        ]
    for operation in values:
        if operation["payload"]["feature"] != "legacy_brief":
            continue
        ticket.check()
        installed = materialize(store, root, operation)
        with client.journal.transaction() as conn:
            if not activate(conn, operation, installed):
                raise ValueError("Staged reading brief changed before binding")


def compare_baseline(conn, expected, current, briefs):
    """Only an exact verified managed replacement may change a legacy path."""
    if {row["id"] for row in expected} != {row["id"] for row in current}:
        raise ValueError("Reading-event identities changed during enrollment")
    actual = {row["id"]: row for row in current}
    for row in expected:
        other = actual[row["id"]]
        if any(row[key] != other[key] for key in row if key != "brief_path"):
            raise ValueError("Reading-event metadata changed during enrollment")
        if row["brief_path"] is None:
            if other["brief_path"] is not None:
                raise ValueError("Enrollment invented a reading brief")
            continue
        prepared = briefs.get(row["id"])
        if prepared is None or not legacy_workflow.brief_current(prepared):
            raise ValueError("Original reading brief changed during enrollment")
        source = Path(other["brief_path"])
        current_proof = legacy_workflow.read_brief(source, trusted_root=source.parent)
        if current_proof.data != prepared.data:
            raise ValueError("Enrollment changed declared Markdown bytes")
        key = conn.execute(
            "SELECT sync_key FROM research_content_identity "
            "WHERE feature='reading_event' AND local_id=? AND paper_id=?",
            (row["id"], row["paper_id"]),
        ).fetchone()[0]
        declaration = target(conn, key)
        if declaration is None or json.loads(declaration["descriptor_json"]) != prepared.descriptor:
            raise ValueError("Enrollment lost the original reading brief declaration")


def relocate_in(conn, store, old_root, new_root):
    from paper_daily.sync_artifacts import applied_file, version_directory
    from paper_daily.sync_files import file_id

    for event_key, paper in conn.execute("SELECT event_key,paper_id FROM " + TARGETS):
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (paper,)
        ).fetchone()[0]
        operation = applied_file(conn, file_id(portable, "legacy_brief", event_key))
        if operation is None:
            continue
        body = _small_body(store, operation)
        if body is None:
            raise ValueError("Reading brief metadata disappeared before relocation")
        old = version_directory(old_root, operation) / filename(body)
        new = version_directory(new_root, operation) / filename(body)
        identity = conn.execute(
            "SELECT local_id FROM research_content_identity "
            "WHERE feature='reading_event' AND sync_key=? AND paper_id=?",
            (event_key, paper),
        ).fetchone()
        if identity is None or conn.execute(
            "SELECT brief_path FROM reading_log WHERE id=?", (identity[0],)
        ).fetchone()[0] != str(old):
            raise ValueError("Reading brief path changed before relocation")
        conn.execute("UPDATE reading_log SET brief_path=? WHERE id=?", (str(new), identity[0]))
