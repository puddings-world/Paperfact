"""Closed archive-only recovered snapshots; never a live device or job journal."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from contextvars import ContextVar
from threading import get_ident
from types import MappingProxyType

from paper_daily.sync_files import canonical_json, closed, digest

TABLE = "research_recovery_provenance"
COLUMNS = "record_id body_json"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_recovery_provenance("
    "record_id TEXT PRIMARY KEY,body_json TEXT NOT NULL)"
)
MAX_DEPTH = 8
_SCHEMA_SCOPE = ContextVar("recovered_provenance_schema_scope", default=None)


class _SchemaScope:
    """One synchronous validation's immutable columns, never research identity or handles."""

    def __init__(self):
        self.owner, self.active, self.registry = get_ident(), True, None

    def current(self):
        return self.active and self.owner == get_ident()

    def close(self):
        # Copied contexts must not retain metadata after the owning call finishes.
        self.active, self.registry = False, None


def _row_registry():
    from paper_daily import sync_recovery as recovery

    scope = _SCHEMA_SCOPE.get()
    if scope is not None and scope.current() and scope.registry is not None:
        return scope.registry
    registry = MappingProxyType({
        name: (section, tuple(columns))
        for name, (section, columns) in recovery._registry().items()
    })
    if scope is not None and scope.current():
        scope.registry = registry
    return registry


def wrap(backup_id, kind, **values):
    body = canonical_json(dict(version=1, backup_id=backup_id, kind=kind, **values))
    return {"record_id": hashlib.sha256(body).hexdigest(), "body_json": body.decode()}


def decode(row):
    from uuid import UUID

    from paper_daily import sync_recovery as recovery

    closed(row, COLUMNS.split())
    digest(row["record_id"])
    raw = row["body_json"]
    if not isinstance(raw, str) or len(raw.encode()) > recovery.MAX_ROW:
        raise ValueError("Recovered provenance exceeds its record bound")
    value = recovery._load(raw)
    if not isinstance(value, dict):
        raise ValueError("Recovered provenance must be a closed object")
    base = {"version", "backup_id", "kind"}
    if value.get("kind") == "manifest":
        closed(value, base | {"manifest"})
    elif value.get("kind") == "row":
        closed(value, base | {"table", "index", "record"})
        registry = _row_registry()
        if (
            not isinstance(value["table"], str)
            or value["table"] not in registry
            or type(value["index"]) is not int
            or value["index"] < 0
        ):
            raise ValueError("Unknown recovered provenance table or index")
        recovery._check_row(value["record"], registry[value["table"]][1])
    else:
        raise ValueError("Unknown recovered provenance kind")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unknown recovered provenance version")
    try:
        if (
            not isinstance(value["backup_id"], str)
            or str(UUID(value["backup_id"])) != value["backup_id"]
        ):
            raise ValueError("Invalid recovered provenance backup ID")
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("Invalid recovered provenance backup ID") from error
    if (
        canonical_json(value) != raw.encode()
        or hashlib.sha256(raw.encode()).hexdigest() != row["record_id"]
    ):
        raise ValueError("Recovered provenance identity differs from its content")
    return value


def encode(manifest, tables):
    rows = [wrap(manifest["backup_id"], "manifest", manifest=manifest)]
    for table in manifest["tables"]:
        for index, record in enumerate(tables[table["name"]]):
            rows.append(
                wrap(manifest["backup_id"], "row", table=table["name"], index=index, record=record)
            )
    return rows


class _Entry:
    """Metadata-only archive inventory accepted by the maintained manifest parser."""

    def __init__(self, name, size):
        self.filename, self.file_size = name, size
        self.external_attr, self.flag_bits = 0, 0

    def is_dir(self):
        return False


class _Manifest:
    def __init__(self, value):
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("tables"), list)
            or not isinstance(value.get("blobs"), list)
        ):
            raise ValueError("Invalid recovered provenance manifest")
        self.value = value
        self.entries = {"manifest.json": _Entry("manifest.json", len(canonical_json(value)))}
        for item in value.get("tables", []):
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or type(item.get("size")) is not int
            ):
                raise ValueError("Invalid recovered table descriptor")
            name = "tables/" + item["name"] + ".jsonl"
            if name in self.entries:
                raise ValueError("Duplicate recovered table inventory")
            self.entries[name] = _Entry(name, item["size"])
        for item in value.get("blobs", []):
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("sha256"), str)
                or type(item.get("size")) is not int
            ):
                raise ValueError("Invalid recovered blob descriptor")
            name = "objects/" + item["sha256"]
            if name in self.entries:
                raise ValueError("Duplicate recovered blob inventory")
            self.entries[name] = _Entry(name, item["size"])

    def namelist(self):
        return list(self.entries)

    def infolist(self):
        return list(self.entries.values())

    def getinfo(self, name):
        return self.entries[name]

    def read(self, name):
        if name != "manifest.json":
            raise ValueError("No data reads in recovered manifest inventory")
        return canonical_json(self.value)


def _validate_groups(rows, *, depth=0):
    """Use complete original record validation, including nested declared closures."""
    from paper_daily import sync_recovery as recovery

    if depth >= MAX_DEPTH:
        raise ValueError("Recovered provenance nesting exceeds its explicit limit")
    grouped = defaultdict(list)
    size = 0
    for count, row in enumerate(rows, 1):
        value = decode(row)
        size += len(row["body_json"].encode())
        if count > recovery.MAX_RECORDS or size > recovery.MAX_METADATA:
            raise ValueError("Recovered provenance exceeds its grouped metadata bound")
        grouped[value["backup_id"]].append(value)
    result = []
    for backup_id, values in grouped.items():
        headers = [value for value in values if value["kind"] == "manifest"]
        if len(headers) != 1:
            raise ValueError("Recovered provenance requires exactly one manifest")
        manifest = recovery._manifest(_Manifest(headers[0]["manifest"]))
        if manifest["backup_id"] != backup_id:
            raise ValueError("Recovered provenance backup owner differs")
        tables = defaultdict(dict)
        for value in values:
            if value["kind"] != "row":
                continue
            table, index = value["table"], value["index"]
            if index in tables[table]:
                raise ValueError("Duplicate recovered provenance row")
            tables[table][index] = value["record"]
        expected = {table["name"] for table in manifest["tables"]}
        if set(tables) - expected:
            raise ValueError("Undeclared recovered provenance table")
        records = recovery._Records(manifest["workspace_id"], manifest["cursor"])
        records._provenance_depth = depth + 1
        for table in manifest["tables"]:
            selected = tables[table["name"]]
            if set(selected) != set(range(table["count"])):
                raise ValueError("Incomplete recovered provenance rows")
            data = b"".join(
                (recovery._json(selected[index]) + "\n").encode() for index in range(table["count"])
            )
            if len(data) != table["size"] or hashlib.sha256(data).hexdigest() != table["sha256"]:
                raise ValueError("Recovered provenance table differs from its inspected manifest")
            for index in range(table["count"]):
                record = selected[index]
                if table["name"] in {
                    "research_generation_requests",
                    "research_generation_recovery",
                }:
                    from paper_daily.enrollment_history import generation_sources

                    records.research_sources.update(generation_sources(record))
                records.row(table["name"], record)
        records.finish()
        if records.refs != {item["sha256"]: item["size"] for item in manifest["blobs"]}:
            raise ValueError("Recovered provenance does not retain its complete blob closure")
        result.append(records)
    return result


def validate_groups(rows, *, depth=0):
    """Share trusted column metadata only within this call and its nested groups."""
    current = _SCHEMA_SCOPE.get()
    if current is not None and current.current() and depth != 0:
        return _validate_groups(rows, depth=depth)
    scope = _SchemaScope()
    token = _SCHEMA_SCOPE.set(scope)
    try:
        return _validate_groups(rows, depth=depth)
    finally:
        scope.close()
        _SCHEMA_SCOPE.reset(token)


def retain_in(conn, rows):
    if not conn.in_transaction:
        raise ValueError("Recovered provenance requires its publication transaction")
    validate_groups(rows)
    if rows:
        conn.execute(SCHEMA)
    for row in rows:
        previous = conn.execute(
            "SELECT body_json FROM " + TABLE + " WHERE record_id=?", (row["record_id"],)
        ).fetchone()
        if previous is not None and previous[0] != row["body_json"]:
            raise ValueError("Recovered provenance record was reused")
        conn.execute(
            "INSERT OR IGNORE INTO " + TABLE + " VALUES(?,?)", (row["record_id"], row["body_json"])
        )
