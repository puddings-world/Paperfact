"""Content-only recovery carrier for owned common proposals; no receiver authority.

The original native catalog is the collector's authority, never the SQL snapshot.
All provenance is archive-only. Reading a carrier follows only declared blobs
through the caller callback, not archived local paths, owners or observations.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing, suppress
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from paper_daily import enrolled_deck_proposals as enrolled
from paper_daily import local_deck_proposals as local
from paper_daily import portable_deck_proposal as codec
from paper_daily.research_file_review import _storage
from paper_daily.sync_deck_publication import runtime
from paper_daily.sync_files import canonical_json, closed, digest, identifier, read_json, text

TABLE = "research_common_deck_proposal_recovery"
COLUMNS = "record_id paper_id proposal_id manifest_json provenance_json"
VERSION = 1
MAX_ROWS = 2000
MAX_ROW_BYTES = 16 * 1024**2
MAX_METADATA_BYTES = 256 * 1024**2
MAX_TOTAL_BYTES = 8 * 1024**3
MAX_OBJECTS = 10000
_SEAL = object()
_UNSET = object()
_CATALOGS = {"local": local, "enrolled": enrolled}


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _record_id(kind, row):
    return _hash(canonical_json({"source_kind": kind, "record": row}))


def _json(value, maximum):
    if not isinstance(value, str) or len(value.encode()) > maximum:
        raise ValueError("Common proposal carrier metadata exceeds its bound")
    return read_json(value.encode())


def validate_row(row, *, papers=None, paper_map=None, workspace=_UNSET):
    """Validate archived structure/scope only; no native/path/receiver authority."""
    closed(row, COLUMNS.split())
    digest(row["record_id"])
    text(row["paper_id"], 4096)
    identifier(row["proposal_id"])
    if len(canonical_json(row)) > MAX_ROW_BYTES:
        raise ValueError("Common proposal recovery row exceeds 16 MiB")
    manifest = _json(row["manifest_json"], codec.MAX_METADATA_BYTES)
    codec.fingerprint(manifest)
    provenance = _json(row["provenance_json"], MAX_ROW_BYTES)
    closed(provenance, {"version", "source_kind", "current_parent", "record"})
    if (
        type(provenance["version"]) is not int
        or provenance["version"] != VERSION
        or not isinstance(provenance["source_kind"], str)
        or provenance["source_kind"] not in _CATALOGS
        or type(provenance["current_parent"]) is not bool
    ):
        raise ValueError("Unsupported common proposal provenance")
    kind, original = provenance["source_kind"], provenance["record"]
    _CATALOGS[kind].validate_record(original)
    local_id = original["paper_id"] if kind == "local" else original["local_id"]
    if (
        row["record_id"] != _record_id(kind, original)
        or row["proposal_id"] != original["proposal_id"]
        or row["paper_id"] != local_id
        or row["manifest_json"] != original["manifest_json"]
    ):
        raise ValueError("Recovery carrier differs from its exact archived catalog row")
    if papers is not None and local_id not in papers:
        raise ValueError("Recovered proposal needs its declared source paper row")
    if kind == "enrolled":
        owner = read_json(original["owner_json"].encode())["target"]
        if workspace is not _UNSET and owner["binding"][0] != workspace:
            raise ValueError("Archived proposal belongs to another source workspace")
        if paper_map is not None and paper_map.get(original["portable_id"]) != local_id:
            raise ValueError("Archived proposal source mapping differs from its paper scope")
    elif workspace is not _UNSET and workspace is not None:
        raise ValueError("Local-only proposal cannot claim enrolled source authority")
    return {"manifest": manifest, "provenance": provenance}


def references(row):
    """Deduplicated closed descriptors for the existing recovery exact-blob set."""
    manifest = validate_row(row)["manifest"]
    return local._references(manifest)


def read(row, read_blob):
    """Pure full-science archive read; archived native paths are never consulted."""
    checked = validate_row(row)
    value = codec.decode(checked["manifest"], read_blob)
    return {
        **value,
        "paper_id": row["paper_id"],
        "proposal_id": row["proposal_id"],
        "provenance": checked["provenance"],
        "archive_only": True,
        "publish": False,
        "sync": False,
        "requires_explicit_review": True,
    }


def _roster(conn):
    rows, size = [], 0
    for kind, module in _CATALOGS.items():
        if not module._schema(conn):
            continue
        ids = conn.execute(
            "SELECT proposal_id FROM " + module.TABLE + " ORDER BY proposal_id LIMIT ?",
            (MAX_ROWS + 1,),
        ).fetchall()
        for (identity,) in ids:
            row = module.record(conn, identity)
            size += len(canonical_json(row))
            rows.append([kind, row])
            if len(rows) > MAX_ROWS or size > MAX_METADATA_BYTES:
                raise ValueError("Common proposal source roster exceeds its bound")
    return rows


def _actual_roster(database, native):
    if local._native(database) != native:
        raise ValueError("Original common proposal database was replaced")
    with closing(local._connect(database)) as conn:
        rows = _roster(conn)
    if local._native(database) != native:
        raise ValueError("Original common proposal database changed during roster read")
    return rows


def _source_read(database, native, kind, identity, current):
    local._check(current)
    if kind == "local":
        return local.read(database, identity, expected_native=native, current=current)
    client = runtime(database=database)
    if client is None:
        raise ValueError("Enrolled common proposal has no actual source runtime")
    with closing(local._connect(database)) as conn:
        store, _root, _proof = _storage(conn)
    return enrolled.read(client, store, identity, expected_native=native, current=current)


def _science(content):
    return {
        key: value
        for key, value in content.items()
        if key
        not in {
            "paper_id",
            "proposal_id",
            "provenance",
            "archive_only",
            "publish",
            "sync",
            "requires_explicit_review",
        }
    }


def _verify_source(database, native, roster, current, expected_states=None):
    if _actual_roster(database, native) != roster:
        raise ValueError("Selected common proposal roster changed")
    witnesses = []
    for kind, row in roster:
        proposal = _source_read(database, native, kind, row["proposal_id"], current)
        if proposal.record != row:
            raise ValueError("Snapshot proposal differs from original native catalog")
        if (
            expected_states is not None
            and proposal.current_parent != expected_states[row["proposal_id"]]
        ):
            raise ValueError("Original proposal parent lifetime changed during collection")
        witnesses.extend((str(path), stamp) for path, stamp in proposal.witnesses)
    local._files_current(witnesses)
    if _actual_roster(database, native) != roster:
        raise ValueError("Selected common proposal roster changed during verification")
    local._check(current)
    return tuple(witnesses)


def _read_object(path, descriptor):
    path = local._path(path)
    before = local.file_change.version(path)
    if before[2] != descriptor["size"]:
        raise ValueError("Collected proposal object size changed")
    with path.open("rb") as stream:
        if local.file_change.version(path, stream=stream) != before:
            raise ValueError("Collected proposal object changed before read")
        value = stream.read(descriptor["size"] + 1)
        if local.file_change.version(path, stream=stream) != before:
            raise ValueError("Collected proposal object changed during read")
    if local.file_change.version(path) != before:
        raise ValueError("Collected proposal object changed after read")
    return value


def _snapshot(conn):
    if not isinstance(conn, sqlite3.Connection):
        raise ValueError("Use an actual caller-owned SQL snapshot connection")
    main = next(row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main")
    path = local._path(main)
    return path, local._native(path)


def _cleanup(directory, identity, owned):
    if local._native(directory) != identity:
        return
    for path in owned:
        if path.parent != directory:
            raise ValueError("Refuse cleanup outside the owned proposal stage")
        local._no_link(path)
        if path.exists():
            local._path(path)  # Never follow a substituted symlink on cleanup.
            path.unlink()
    directory.rmdir()  # Never recursively remove foreign/unrecognized entries.


@dataclass(frozen=True)
class Collection:
    _rows: str = field(repr=False)
    _objects: tuple = field(repr=False)
    _files: tuple = field(repr=False)
    _database: Path = field(repr=False)
    _native: tuple = field(repr=False)
    _roster: str = field(repr=False)
    _parents: str = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    @property
    def rows(self):
        return json.loads(self._rows)

    @property
    def objects(self):
        return {key: Path(path) for key, path in self._objects}

    @property
    def witnesses(self):
        return tuple((Path(path), tuple(stamp)) for path, stamp in self._files)

    def check(self, *, current=lambda: True):
        if self._seal is not _SEAL:
            raise ValueError("Use an actual source-bound collected proposal set")
        _verify_source(
            self._database,
            self._native,
            json.loads(self._roster),
            current,
            json.loads(self._parents),
        )
        local._files_current(self._files)
        for row in self.rows:
            read(row, lambda item: _read_object(self.objects[item["sha256"]], item))
        local._check(current)
        return True


def collect(original_database, snapshot_conn, temporary, *, expected_native, current=lambda: True):
    """Verify original source ownership and spool content into a new private temp child.

    Snapshot SQL is compared with the original, never treated as native authority.
    The caller owns snapshot_conn and temporary; neither is committed/closed here.
    """
    local._check(current)
    database, native = local._path(original_database), local._expected(expected_native)
    if local._native(database) != native:
        raise ValueError("Original common proposal source native identity changed")
    snapshot = _snapshot(snapshot_conn)
    roster = _roster(snapshot_conn)
    if _actual_roster(database, native) != roster:
        raise ValueError("SQL snapshot proposal roster differs from original native source")
    papers = {row[0] for row in snapshot_conn.execute("SELECT id FROM papers")}
    temporary = local._path(temporary)
    if not temporary.is_dir():
        raise ValueError("Choose an existing owned temporary collection directory")
    directory = temporary / ("common-proposals-" + uuid4().hex)
    directory.mkdir()
    identity, owned, objects, descriptions = local._native(directory), [], {}, {}
    rows, files, total, metadata, parent_states = [], [], 0, 0, {}
    try:
        for kind, original in roster:
            proposal = _source_read(database, native, kind, original["proposal_id"], current)
            if proposal.record != original:
                raise ValueError("Snapshot catalog row differs from original native owner")
            science = proposal.content
            parent_states[original["proposal_id"]] = proposal.current_parent
            manifest, blobs = codec.encode(
                science["deck"],
                science["evidence"],
                science["image_bytes"],
                science["original_bytes"],
                source_document_hash=science["source_document_hash"],
            )
            if canonical_json(manifest).decode() != original["manifest_json"]:
                raise ValueError("Verified scientific proposal differs from its captured manifest")
            provenance = {
                "version": VERSION,
                "source_kind": kind,
                "current_parent": proposal.current_parent,
                "record": original,
            }
            row = {
                "record_id": _record_id(kind, original),
                "paper_id": original["paper_id"] if kind == "local" else original["local_id"],
                "proposal_id": original["proposal_id"],
                "manifest_json": original["manifest_json"],
                "provenance_json": canonical_json(provenance).decode(),
            }
            validate_row(row, papers=papers)
            metadata += len(canonical_json(row))
            if metadata > MAX_METADATA_BYTES:
                raise ValueError("Common proposal recovery metadata exceeds its budget")
            for item in references(row):
                local._check(current)
                old = descriptions.setdefault(item["sha256"], item)
                if old != item:
                    raise ValueError("Common proposal object descriptors disagree")
                if item["sha256"] in objects:
                    continue
                total += item["size"]
                if len(objects) >= MAX_OBJECTS or total > MAX_TOTAL_BYTES:
                    raise ValueError("Common proposal recovery objects exceed their budget")
                if local._native(directory) != identity:
                    raise ValueError("Owned proposal collection directory changed")
                path = directory / item["sha256"]
                owned.append(path)
                value = blobs[item["sha256"]]
                with path.open("xb") as stream:
                    stream.write(value)
                local._check(current)
                if _read_object(path, item) != value or _hash(value) != item["sha256"]:
                    raise ValueError("Collected scientific object changed during staging")
                objects[item["sha256"]] = str(path)
            archived = read(row, lambda item: _read_object(Path(objects[item["sha256"]]), item))
            if _science(archived) != science:
                raise ValueError("Archived scientific proposal changed during collection")
            files.extend((str(path), stamp) for path, stamp in proposal.witnesses)
            after = _source_read(database, native, kind, original["proposal_id"], current)
            if (
                after.record != original
                or after.content != science
                or after.current_parent != proposal.current_parent
            ):
                raise ValueError("Original native proposal changed during staging")
            local._files_current(files)
            rows.append(row)
        _verify_source(database, native, roster, current, parent_states)
        if _snapshot(snapshot_conn) != snapshot or _roster(snapshot_conn) != roster:
            raise ValueError("Caller SQL snapshot changed during proposal collection")
        for path in objects.values():
            files.append((path, tuple(local.file_change.version(local._path(path)))))
        local._files_current(files)
        local._check(current)
        return Collection(
            canonical_json(rows).decode(),
            tuple(sorted(objects.items())),
            tuple(files),
            database,
            native,
            canonical_json(roster).decode(),
            canonical_json(parent_states).decode(),
            _SEAL,
        )
    except BaseException:
        with suppress(OSError, ValueError):
            _cleanup(directory, identity, owned)
        raise
