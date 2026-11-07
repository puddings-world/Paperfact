"""Owned full-deck byte receipts; archived data never confers writer authority."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
from contextlib import closing
from copy import deepcopy
from pathlib import Path

from paper_daily import file_change
from paper_daily.sync_blobs import BlobManifest, _no_link
from paper_daily.sync_files import MAX_BODY, canonical_json, closed, descriptor, digest, identifier

TABLE = "research_deck_draft_recovery"
COLUMNS = "candidate_id manifest"
MAX_RECEIPT = 160 * 1024**2
MAX_RECEIPTS = 2000
MAX_COLLECTION = 256 * 1024**2
ROOT = ".paperfact-deck-drafts"
_WRITE_LOCK = threading.RLock()
HASH = re.compile(r"[0-9a-f]{64}")
HEADER_FIELDS = {"version", "owner", "raw", "closure", "evidence", "objects", "fingerprint"}


def _path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        _no_link(part)
    return path


def _native(path):
    info = _path(path).stat()
    if not info.st_ino:
        raise ValueError("Draft receipt requires known native ownership")
    return [info.st_dev, info.st_ino]


def _load(data):
    if not isinstance(data, bytes) or len(data) > MAX_RECEIPT:
        raise ValueError("Draft receipt exceeds 160 MiB")

    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("Duplicate draft receipt JSON field")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("Nonfinite draft receipt JSON")

    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)
        canonical_json(value)  # Bound nesting; never silently normalize bad JSON.
        return value
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Invalid draft receipt JSON") from error


def _database_owner(conn):
    """Observe the selected database; another namespace never chooses this owner."""
    path = _path(
        next(row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main")
    ).resolve(strict=True)
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_sync_binding'"
    ).fetchone():
        return None
    rows = conn.execute("SELECT id,workspace,origin FROM research_sync_binding LIMIT 2").fetchall()
    if len(rows) != 1 or rows[0][0] != 1:
        raise ValueError("Selected draft workspace binding is incomplete or ambiguous")
    owner = {
        "database": str(path),
        "database_identity": _native(path),
        "parent_identity": _native(path.parent),
        "workspace_id": rows[0][1],
        "device_id": rows[0][2],
    }
    _validate_owner(owner)
    return owner


def _owner(conn, raw):
    from paper_daily.raw_deck_closure import _scope

    owner = _database_owner(conn)
    if owner is None:
        raise ValueError("Selected database has no original draft owner")
    _scope(conn, Path(owner["database"]), json.loads(raw["observation"]))
    return owner


def _validate_owner(owner):
    closed(owner, {"database", "database_identity", "parent_identity", "workspace_id", "device_id"})
    if not isinstance(owner["database"], str) or len(owner["database"].encode()) > 4096:
        raise ValueError("Invalid original draft database description")
    for key in ("workspace_id", "device_id"):
        identifier(owner[key])
    for key in ("database_identity", "parent_identity"):
        value = owner[key]
        if (
            not isinstance(value, list)
            or len(value) != 2
            or any(type(item) is not int or item < 0 for item in value)
            or not value[1]
        ):
            raise ValueError("Invalid original draft native identity")


def _namespace(owner):
    _validate_owner(owner)
    namespace = hashlib.sha256(canonical_json(owner)).hexdigest()
    return _path(Path(owner["database"]).parent / ROOT / namespace)


def location(owner, candidate_id):
    """Derive a location from an already observed owner, never an archived path."""
    identifier(candidate_id)
    name = hashlib.sha256(candidate_id.encode()).hexdigest() + ".json"
    return _namespace(owner) / name


def _expected_objects(header):
    from paper_daily.raw_deck_closure import validate_row

    payload, inventory = validate_row(header["closure"])
    result = {}
    for item in [payload["body"], *payload["assets"], *inventory["images"]]:
        value = {key: item[key] for key in ("sha256", "size")}
        BlobManifest(**value)
        if value["sha256"] in result and result[value["sha256"]] != value:
            raise ValueError("Inconsistent draft object sizes")
        result[value["sha256"]] = value
    return [result[key] for key in sorted(result)]


def _verify(header, read):
    from paper_daily.raw_deck_closure import source_hash, summarize, verify_summary

    closed(header, HEADER_FIELDS)
    if type(header["version"]) is not int or header["version"] != 1:
        raise ValueError("Unsupported full-deck receipt")
    _validate_owner(header["owner"])
    source_hash(header["raw"])
    observation = json.loads(header["raw"]["observation"])
    owner = header["owner"]
    if any(
        observation.get(key) != owner[key]
        for key in ("database", "database_identity", "workspace_id", "device_id")
    ):
        raise ValueError("Receipt differs from its original source owner")
    evidence = header["evidence"]
    if evidence is not None and (
        not isinstance(evidence, dict) or len(canonical_json(evidence)) > MAX_BODY
    ):
        raise ValueError("Draft evidence exceeds its bounded snapshot")
    if header["objects"] != _expected_objects(header):
        raise ValueError("Draft receipt has missing, duplicate or undeclared objects")
    digest(header["fingerprint"])
    expected = hashlib.sha256(
        canonical_json({k: v for k, v in header.items() if k != "fingerprint"})
    ).hexdigest()
    if header["fingerprint"] != expected:
        raise ValueError("Draft request fingerprint changed")
    for item in header["objects"]:
        data = read(item)
        if (
            not isinstance(data, bytes)
            or len(data) != item["size"]
            or hashlib.sha256(data).hexdigest() != item["sha256"]
        ):
            raise ValueError("Draft receipt object bytes changed")
    return verify_summary(summarize(header["raw"]), header["closure"], read)


def capture(conn, raw, closure, evidence, blobs):
    owner = _owner(conn, raw)
    header = {
        "version": 1,
        "owner": owner,
        "raw": deepcopy(raw),
        "closure": deepcopy(closure),
        "evidence": deepcopy(evidence),
    }
    header["objects"] = _expected_objects(header)
    if set(blobs) != {item["sha256"] for item in header["objects"]}:
        raise ValueError("Draft capture has undeclared or missing bytes")
    header["fingerprint"] = hashlib.sha256(canonical_json(header)).hexdigest()
    _verify(header, lambda row: blobs[row["sha256"]])
    data = canonical_json(
        {
            "header": header,
            "data": {
                sha: base64.b64encode(data).decode("ascii") for sha, data in sorted(blobs.items())
            },
        }
    )
    if len(data) > MAX_RECEIPT:
        raise ValueError("Draft receipt exceeds 160 MiB")
    return data


def decode(data):
    value = _load(data)
    closed(value, {"header", "data"})
    header = value["header"]
    if not isinstance(value["data"], dict):
        raise ValueError("Invalid draft byte map")
    objects = {}
    for sha, encoded in value["data"].items():
        digest(sha)
        if not isinstance(encoded, str):
            raise ValueError("Invalid draft object encoding")
        try:
            objects[sha] = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise ValueError("Invalid draft object encoding") from error
    if (
        not isinstance(header, dict)
        or not isinstance(header.get("objects"), list)
        or set(objects)
        != {item.get("sha256") for item in header["objects"] if isinstance(item, dict)}
    ):
        raise ValueError("Draft byte map differs from its declared objects")
    _verify(header, lambda row: objects[row["sha256"]])
    return header, objects


def _read_file(path):
    path = _path(path)
    before = file_change.version(path)
    if before[2] > MAX_RECEIPT:
        raise ValueError("Draft receipt exceeds 160 MiB")
    with path.open("rb") as stream:
        if file_change.version(path, stream=stream) != before:
            raise ValueError("Draft receipt changed before reading")
        data = stream.read(MAX_RECEIPT + 1)
        if file_change.version(path, stream=stream) != before:
            raise ValueError("Draft receipt changed while reading")
    if file_change.version(path) != before:
        raise ValueError("Draft receipt changed after reading")
    return data, before


def read_owned(conn, raw, *, missing_ok=False):
    owner = _owner(conn, raw)
    path = location(owner, raw["candidate_id"])
    try:
        data, proof = _read_file(path)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise ValueError("Raw draft has no owned byte receipt") from None
    header, objects = decode(data)
    if header["owner"] != owner or header["raw"] != raw or _owner(conn, raw) != owner:
        raise ValueError("Draft receipt owner/source changed")
    return header, objects, {str(path): proof}


def check_retry(header, raw, deck, evidence):
    if header["raw"] != raw or canonical_json(header["evidence"]) != canonical_json(evidence):
        raise ValueError("Draft request identity was reused for different evidence")
    images = getattr(deck, "_revision_figures", None)
    if images is not None:
        inventory = json.loads(header["closure"]["inventory"])["images"]
        if not isinstance(images, dict) or set(images) != {item["id"] for item in inventory}:
            raise ValueError("Draft request captured image inventory changed")
        for item in inventory:
            data = images[item["id"]]
            if (
                not isinstance(data, bytes)
                or len(data) != item["size"]
                or hashlib.sha256(data).hexdigest() != item["sha256"]
            ):
                raise ValueError("Draft request captured image bytes changed")


def write_owned(conn, data):
    with _WRITE_LOCK:
        return _write_owned(conn, data)


def _write_owned(conn, data):
    header, _objects = decode(data)
    raw = header["raw"]
    owner = _owner(conn, raw)
    if owner != header["owner"]:
        raise ValueError("Draft receipt belongs to another original owner")
    path = location(owner, raw["candidate_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    _path(path)
    entries = _inventory(path.parent)
    if not path.exists() and (
        len(entries) >= MAX_RECEIPTS
        or sum(item.stat().st_size for item in entries) + len(data) > MAX_COLLECTION
    ):
        raise OSError("Draft receipt collection capacity is unavailable")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".draft-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if _owner(conn, raw) != owner:
            raise ValueError("Original draft ownership changed before retention")
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing, _proof = _read_file(path)
            if decode(existing)[0] != header:
                raise ValueError("Draft receipt identity reused for different bytes") from None
        if _owner(conn, raw) != owner:
            raise ValueError("Original draft ownership changed during retention")
        retained = read_owned(conn, raw)
        if retained[0] != header:
            raise ValueError("Retained draft differs from its captured request")
        return retained[2]
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _inventory(namespace):
    """Bound only the selected owner namespace before reading any receipt."""
    namespace = _path(namespace)
    if not namespace.exists():
        return []
    result, total = [], 0
    for path in sorted(namespace.iterdir()):
        _path(path)
        if not path.is_file() or path.suffix != ".json" or not HASH.fullmatch(path.stem):
            raise ValueError("Unknown or incomplete draft receipt file")
        size = path.stat().st_size
        total += size
        result.append(path)
        if size > MAX_RECEIPT or len(result) > MAX_RECEIPTS or total > MAX_COLLECTION:
            raise ValueError("Draft receipt collection exceeds its bounded inventory")
    return result


def validate_manifest(row):
    closed(row, {"candidate_id", "manifest"})
    identifier(row["candidate_id"])
    value = _load(row["manifest"].encode())
    closed(
        value,
        {
            "version",
            "candidate_id",
            "source_sha256",
            "workspace_id",
            "body",
            "payload",
            "objects",
            "documents",
        },
    )
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported draft archive protocol")
    if value["candidate_id"] != row["candidate_id"]:
        raise ValueError("Draft archive identity mismatch")
    identifier(value["workspace_id"])
    digest(value["source_sha256"])
    from paper_daily.sync_files import validate_payload

    validate_payload(value["payload"])
    if value["payload"]["feature"] != "deck":
        raise ValueError("Draft archive requires an editable deck")
    objects = value["objects"]
    if not isinstance(objects, list) or len(objects) > 513:
        raise ValueError("Invalid draft archive object inventory")
    seen = set()
    for item in [value["body"], *objects]:
        closed(item, {"sha256", "size"})
        BlobManifest(**item)
        if not 0 < item["size"] <= MAX_RECEIPT or item["sha256"] in seen:
            raise ValueError("Duplicate or invalid draft archive object")
        seen.add(item["sha256"])
    if (
        not isinstance(value["documents"], list)
        or len(value["documents"]) > 512
        or value["documents"] != sorted(set(value["documents"]))
    ):
        raise ValueError("Invalid draft source inventory")
    for sha in value["documents"]:
        digest(sha)
    return value


def references(manifest):
    yield manifest["body"]
    yield from manifest["objects"]


def read_retained(row, read):
    from paper_daily.raw_deck_closure import source_hash, summarize

    manifest = validate_manifest(row)
    data = read(manifest["body"])
    if descriptor(data, "application/json")["sha256"] != manifest["body"]["sha256"]:
        raise ValueError("Draft archive header bytes changed")
    if len(data) != manifest["body"]["size"]:
        raise ValueError("Draft archive header size changed")
    header = _load(data)
    body = _verify(header, read)
    if (
        header["raw"]["candidate_id"] != row["candidate_id"]
        or source_hash(header["raw"]) != manifest["source_sha256"]
        or header["owner"]["workspace_id"] != manifest["workspace_id"]
        or header["objects"] != manifest["objects"]
        or json.loads(header["closure"]["payload"]) != manifest["payload"]
        or summarize(header["raw"])["documents"] != manifest["documents"]
    ):
        raise ValueError("Draft archive manifest differs from its captured bytes")
    return {
        "raw": header["raw"],
        "closure": header["closure"],
        "deck": body["deck"],
        "evidence": header["evidence"],
        "images": json.loads(header["closure"]["inventory"])["images"],
        "publish": False,
        "sync": False,
        "requires_explicit_review": True,
    }


def collect(database, temporary):
    """Bounded owned sidecar inventory; stage verified bytes without using BlobStore."""
    database = _path(database).resolve(strict=True)
    native = _native(database)
    objects, rows, aliases = {}, [], {}
    staging = Path(temporary) / "full-deck-draft-objects"
    staging.mkdir()

    def stage(data):
        item = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        path = staging / item["sha256"]
        if not path.exists():
            path.write_bytes(data)
        objects[item["sha256"]] = path
        return item

    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        selected = _database_owner(conn)
        paths = _inventory(_namespace(selected)) if selected is not None else []
        for path in paths:
            data, proof = _read_file(path)
            header, blobs = decode(data)
            owner = _owner(conn, header["raw"])
            if (
                owner != selected
                or header["owner"] != owner
                or location(owner, header["raw"]["candidate_id"]) != path
            ):
                raise ValueError("Draft receipt is not owned by this original workspace")
            # Existing CAS-ready rows remain subject to their own strict byte
            # checks; backup is not an implicit repair of damaged primary data.
            from paper_daily.raw_deck_closure import TABLE as CLOSURES
            from paper_daily.raw_deck_closure import source_hash, summarize, verify_in

            if (
                conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (CLOSURES,)).fetchone()
                and conn.execute(
                    "SELECT 1 FROM " + CLOSURES + " WHERE candidate_id=?",
                    (header["raw"]["candidate_id"],),
                ).fetchone()
            ):
                verify_in(conn, header["raw"])
            payload = json.loads(header["closure"]["payload"])
            manifest = {
                "version": 1,
                "candidate_id": header["raw"]["candidate_id"],
                "source_sha256": source_hash(header["raw"]),
                "workspace_id": owner["workspace_id"],
                "payload": payload,
                "body": stage(canonical_json(header)),
                "objects": header["objects"],
                "documents": summarize(header["raw"])["documents"],
            }
            row = {
                "candidate_id": manifest["candidate_id"],
                "manifest": canonical_json(manifest).decode(),
            }
            for blob in blobs.values():
                stage(blob)
            read_retained(row, lambda item: objects[item["sha256"]].read_bytes())
            if file_change.version(path) != proof or _owner(conn, header["raw"]) != owner:
                raise ValueError("Draft receipt changed during archive collection")
            rows.append(row)
            aliases[path] = (hashlib.sha256(data).hexdigest(), len(data))
    if _native(database) != native:
        raise ValueError("Original database changed during draft collection")
    return rows, objects, aliases


def read_detached(database, candidate_id):
    """Verify archived bytes only; never return an old publisher or live job."""
    identifier(candidate_id)
    database = _path(database).resolve(strict=True)
    native = _native(database)
    objects = database.parent / "objects"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        if not conn.execute("SELECT 1 FROM recovery_identity WHERE id=1").fetchone():
            raise ValueError("Select a detached recovery workspace")
        rows = conn.execute(
            "SELECT CASE WHEN length(CAST(data AS BLOB))<=? THEN data ELSE NULL END "
            "FROM recovery_records WHERE table_name=? AND json_valid(data) "
            "AND json_extract(data,'$.candidate_id')=? LIMIT 2",
            (MAX_BODY, TABLE, candidate_id),
        ).fetchall()
        if len(rows) != 1 or rows[0][0] is None:
            raise ValueError("Archived draft receipt is missing, duplicate or oversized")
        row = _load(rows[0][0].encode())

        def read(item):
            digest(item["sha256"])
            path = _path(objects / item["sha256"])
            before = file_change.version(path)
            if before[2] != item["size"]:
                raise ValueError("Archived draft object size changed")
            with path.open("rb") as stream:
                if file_change.version(path, stream=stream) != before:
                    raise ValueError("Archived draft object changed before reading")
                data = stream.read(item["size"] + 1)
                if file_change.version(path, stream=stream) != before:
                    raise ValueError("Archived draft object changed during reading")
            if file_change.version(path) != before:
                raise ValueError("Archived draft object changed after reading")
            return data

        result = read_retained(row, read)
        result["image_bytes"] = {item["id"]: read(item) for item in result["images"]}
    if _native(database) != native:
        raise ValueError("Detached recovery database changed during reading")
    return result
