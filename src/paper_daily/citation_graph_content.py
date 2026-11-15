"""Closed citation-neighbour research, backed only by its existing paper-scoped KV."""

from __future__ import annotations

import json

PREFIX = "citegraph."
FEATURE = "citation_graph"
MAX_BYTES = 200 * 1024
MAX_EDGES = 4096
MAX_COUNTS = 512


def selected(row):
    return (isinstance(row, dict) and isinstance(row.get("key"), str)
            and row["key"].startswith(PREFIX))


def _fail():
    raise ValueError("Invalid bounded citation graph") from None


def _lookup(value):
    if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > 4096
            or any(ord(char) < 32 for char in value)):
        _fail()


def _number(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        _fail()


def decode(raw):
    """Validate without normalizing the retained JSON or interpreting lookup IDs."""
    from paper_daily.sync_content import _stamp

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail()
            result[key] = value
        return result

    try:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
            _fail()
        value = json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda *_: _fail())
        fields = {"checked", "edges", "citations", "unplaced"}
        if not isinstance(value, dict) or set(value) != fields:
            _fail()
        _stamp(value["checked"])
        if not isinstance(value["edges"], list) or len(value["edges"]) > MAX_EDGES:
            _fail()
        seen = set()
        for edge in value["edges"]:
            if not isinstance(edge, list) or len(edge) != 2:
                _fail()
            for endpoint in edge:
                _lookup(endpoint)
            if edge[0] == edge[1] or tuple(edge) in seen:
                _fail()
            seen.add(tuple(edge))
        if not isinstance(value["citations"], dict) or len(value["citations"]) > MAX_COUNTS:
            _fail()
        for identity, count in value["citations"].items():
            _lookup(identity)
            _number(count, 2**31 - 1)
        _number(value["unplaced"], 1_000_000)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _fail()


def local_id(row):
    if not isinstance(row, dict) or set(row) != {"key", "value"} or not selected(row):
        _fail()
    local = row["key"][len(PREFIX):]
    if not local or len(local) > 4096:
        _fail()
    decode(row["value"])
    return local


def validate_local(conn, row):
    local = local_id(row)
    if conn.execute("SELECT 1 FROM papers WHERE id=?", (local,)).fetchone() is None:
        _fail()
    return local


def payload(conn, row):
    from paper_daily.sync_content import _portable_paper

    local = validate_local(conn, row)
    return dict(scope=dict(kind="paper", id=_portable_paper(conn, local)), feature=FEATURE,
                key="main", data=dict(value=row["value"]), source_document_hash=None)


def validate_wire(value):
    if (value["source_document_hash"] is not None or value["key"] != "main"
            or not isinstance(value["data"], dict) or set(value["data"]) != {"value"}):
        _fail()
    decode(value["data"]["value"])
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 240 * 1024:
        _fail()


def write_in(conn, operation, local, *, deleting):
    key = PREFIX + local
    if deleting:
        conn.execute("DELETE FROM kv WHERE key=?", (key,))
    else:
        conn.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) "
                     "DO UPDATE SET value=excluded.value",
                     (key, operation["payload"]["data"]["value"]))
