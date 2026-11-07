"""Explicit, source-preserving application of verified retained deck candidates.

Preparation reads immutable cached bytes. Application materializes outside the
write lock, then compares the displayed base and commits one shared operation.
No model, account lookup, retargeting or retrospective source binding occurs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from paper_daily.file_change import version
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_blobs import BlobManifest, _no_link
from paper_daily.sync_deck_publication import _observation, _same_observation, runtime
from paper_daily.sync_files import canonical_json, validate_closure, validate_payload
from paper_daily.workspace_service import _ReadOnlyStore


def _stamp(path, *, stream=None):
    # Native Windows revisions contain nested tuples; previews round-trip JSON.
    return json.loads(json.dumps(version(path, stream=stream)))


def _native(path):
    path = Path(path)
    for entry in (path, *path.parents):
        _no_link(entry)
    info = path.stat()
    return [info.st_dev, info.st_ino]


def _storage(conn):
    row = conn.execute(
        "SELECT workspace,blob_root,version_root FROM research_file_paths WHERE id=1"
    ).fetchone()
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if row is None or binding is None or row[0] != binding[0]:
        raise ValueError("Configure original artifact storage before reviewing retained slides")
    store = _ReadOnlyStore(Path(row[1]))
    root = Path(row[2])
    if root.exists() and not root.is_dir():
        raise ValueError("Original artifact storage is unavailable")
    for entry in (root, *root.parents):
        _no_link(entry)
    anchor = root.parent
    while not anchor.exists():
        if anchor.parent == anchor:
            raise ValueError("Original artifact storage has no available parent directory")
        anchor = anchor.parent
    return store, root, {
        "registration": list(row), "blob_root": _native(store.root),
        "blob_index": _native(store.root / "index.sqlite"),
        "version_root": _native(root) if root.exists() else None,
        "version_anchor": [str(anchor), _native(anchor)],
    }


def _body(store, payload, files):
    def read(row):
        manifest = BlobManifest(row["sha256"], row["size"])
        path = store._path(manifest)
        before = _stamp(path)
        if before[2] != manifest.size:
            raise ValueError("Retained artifact size changed")
        with path.open("rb") as stream:
            if _stamp(path, stream=stream) != before:
                raise ValueError("Retained artifact changed before reading")
            data = stream.read(manifest.size + 1)
            if _stamp(path, stream=stream) != before:
                raise ValueError("Retained artifact changed while reading")
        key = str(path)
        if key in files and files[key] != before:
            raise ValueError("Retained artifact changed between versions")
        files[key] = before
        return data

    return validate_closure(payload, read)["deck"]


def _client(conn):
    path = next(row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main")
    client = runtime(database=path)
    if client is None:
        raise ValueError("Retained slides require their original enrolled workspace")
    return client


def prepare_in(conn, record):
    """Read the actual decks and capture a new displayed base, without applying."""
    payload = json.loads(record["payload"])
    validate_payload(payload, entity_id=record["entity_id"])
    if payload["feature"] != "deck":
        raise ValueError("This retained file needs its own typed review")
    original = json.loads(record["observation"])
    if not isinstance(original, dict):
        raise ValueError("Invalid original deck observation")
    client = _client(conn)
    current = _observation(conn, client, original.get("local_id"), payload["slot"])
    for key in ("database", "database_identity", "device_id", "workspace_id", "local_id",
                "paper_id", "entity_id", "mode"):
        if original.get(key) != current[key]:
            raise ValueError("Retained slides belong to another original workspace or paper")
    if record["entity_id"] != current["entity_id"] or payload["paper_id"] != current["paper_id"]:
        raise ValueError("Retained slides belong to another paper")
    old_parents = original.get("observed")
    if not isinstance(old_parents, list) or not old_parents:
        raise ValueError("Original paper lifecycle is unavailable")
    old = old_parents[0]
    now = current["observed"][0]
    if (old.get("kind"), old.get("id")) != ("paper", payload["paper_id"]) or not (
        old.get("metadata") and old["metadata"].get("active")
        and old["metadata"].get("incarnation") == now["metadata"]["incarnation"]
    ):
        raise ValueError("Original paper lifecycle changed; export the retained slides instead")
    token = parent_lifecycle(conn, "paper", current["local_id"])
    original_token = original.get("local_parent_lifecycle")
    if original_token is not None and original_token != token:
        raise ValueError("Original paper lifecycle changed; the old slides cannot be reattached")
    if token is None:
        raise ValueError("Current paper requires a durable local lifecycle")
    parent = conn.execute("SELECT * FROM papers WHERE id=?", (current["local_id"],)).fetchone()
    store, _root, storage = _storage(conn)
    files = {}
    retained = _body(store, payload, files)
    current_operation = desired_file(conn, record["entity_id"])
    current_body = _body(store, current_operation["payload"], files) if current_operation else None
    previous = original.get("artifact")
    original_body = _body(store, previous["payload"], files) if previous else None
    _check_files(files)
    slot = current["observed"][1]["metadata"]
    restoring = bool(slot and not slot["active"])
    return {
        "apply": True, "editable": False,
        "reason": ("These slides were deleted. Review and confirm restoration as a new version"
                   if restoring else "Review the retained slides against the current version, "
                   "then confirm application"),
        "retained": retained, "original": original_body, "current": current_body,
        "source_hash": payload["source_document_hash"],
        "scope": {"kind": "paper", "id": current["local_id"]},
        "target": {"id": current["local_id"], "title": parent["title"], "restoring": restoring},
        "requires_confirmation": True, "parent_token": token, "parent_row": dict(parent),
        "expected": {"observation": current, "storage": storage, "files": files,
                     "candidate_sha256": hashlib.sha256(canonical_json(record)).hexdigest()},
    }


def _check_files(files):
    for filename, expected in files.items():
        path = Path(filename)
        _native(path)
        if _stamp(path) != expected:
            raise ValueError("Displayed artifact bytes changed; review the slides again")


def check_in(conn, record, data, *, allow_storage_creation=False):
    """Compare the original displayed base, never silently rebuild it on Apply."""
    expected = data["expected"]
    if not isinstance(expected, dict) or set(expected) != {
        "observation", "storage", "files", "candidate_sha256"
    }:
        raise ValueError("Prepare and review retained slides before applying")
    if hashlib.sha256(canonical_json(record)).hexdigest() != expected["candidate_sha256"]:
        raise ValueError("Displayed retained slide closure changed; review again")
    client = _client(conn)
    before = expected["observation"]
    current = _observation(conn, client, before["local_id"], before["mode"])
    if not _same_observation(current, before):
        raise ValueError("Displayed slide version or inputs changed; review again")
    if parent_lifecycle(conn, "paper", before["local_id"]) != data["parent_token"]:
        raise ValueError("Displayed paper lifecycle changed; review again")
    parent = conn.execute("SELECT * FROM papers WHERE id=?", (before["local_id"],)).fetchone()
    if parent is None or dict(parent) != data["parent_row"]:
        raise ValueError("Displayed paper changed; review again")
    slot = current["observed"][1]["metadata"]
    if data["target"].get("restoring") is not bool(slot and not slot["active"]):
        raise ValueError("Displayed slide restoration choice changed; review again")
    store, root, storage = _storage(conn)
    if storage != expected["storage"]:
        old = expected["storage"]
        created = (allow_storage_creation and old["version_root"] is None
                   and storage["version_root"] is not None
                   and all(storage[key] == old[key] for key in (
                       "registration", "blob_root", "blob_index"))
                   and _native(Path(old["version_anchor"][0])) == old["version_anchor"][1])
        if not created:
            raise ValueError("Original artifact storage changed; review again")
    payload = json.loads(record["payload"])
    validate_payload(payload, entity_id=record["entity_id"])
    _check_files(expected["files"])
    files = {}
    body = _body(store, payload, files)
    if body != data["retained"] or any(expected["files"].get(k) != v for k, v in files.items()):
        raise ValueError("Displayed retained slides changed; review again")
    _check_files(expected["files"])
    return client, store, root, payload
