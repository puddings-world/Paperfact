"""Readable private drafts from prepared and detached workspaces; never write grants."""

from __future__ import annotations

import json

from paper_daily import enrollment_history as history
from paper_daily.sync_files import canonical_json, closed, digest

ORIGIN = "archived_draft"
PROTOCOL = "research_review_drafts"
MAX_CARRIER = 2 * history.MAX_ROW + 4096
# Generic recovery rows stay visible unless the specialized reader owns their
# declared type. Malformed/unrecognized rows are never silently reinterpreted.
RECOVERY_FILTER = (
    " AND table_name<>'research_review_drafts'"
    " AND NOT (table_name='research_history_archive' AND "
    f"CASE WHEN length(CAST(data AS BLOB))<={MAX_CARRIER} THEN "
    "CASE WHEN json_valid(data) THEN "
    "coalesce(json_extract(data,'$.protocol'),'')='research_review_drafts' "
    "ELSE 0 END ELSE 0 END)"
)


def _present(conn, table, fields):
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone():
        return False
    if [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')] != fields.split():
        raise ValueError("Unknown historical draft carrier columns")
    return True


def _carrier(raw, *, raw_protocol=False):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_CARRIER:
        raise ValueError("Historical draft recovery carrier exceeds its byte bound")

    def pairs(values):
        out = {}
        for key, value in values:
            if key in out:
                raise ValueError("Duplicate historical draft carrier field")
            out[key] = value
        return out

    def invalid(_value):
        raise ValueError("Nonfinite historical draft carrier value")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
        if raw_protocol:
            from paper_daily.research_review_drafts import COLUMNS

            closed(value, COLUMNS)
        else:
            closed(value, history.COLUMNS.split())
        canonical_json(value)  # Maintained depth/Unicode/finite checks, not path I/O.
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("Invalid bounded historical draft carrier") from exc
    return history.wrap(PROTOCOL, value) if raw_protocol else value


def _provenance_rows(conn):
    """Index fully validated backup histories, without installing their old tables."""
    from paper_daily import recovery_provenance as provenance
    from paper_daily import sync_recovery as recovery

    def carriers():
        if _present(conn, provenance.TABLE, provenance.COLUMNS):
            for raw in conn.execute(
                "SELECT record_id,CASE WHEN length(CAST(body_json AS BLOB))<=? "
                "THEN body_json END AS body_json,length(CAST(body_json AS BLOB)) AS size "
                "FROM research_recovery_provenance ORDER BY record_id LIMIT ?",
                (recovery.MAX_ROW, recovery.MAX_RECORDS + 1),
            ):
                yield {"record_id": raw["record_id"], "body_json": raw["body_json"]}, raw["size"]
        if _present(conn, "recovery_records", "table_name row_number data"):
            for raw in conn.execute(
                "SELECT CASE WHEN length(CAST(data AS BLOB))<=? THEN data END AS data,"
                "length(CAST(data AS BLOB)) AS size FROM recovery_records "
                "WHERE table_name=? ORDER BY row_number LIMIT ?",
                (recovery.MAX_ROW, provenance.TABLE, recovery.MAX_RECORDS + 1),
            ):
                if (type(raw["size"]) is not int or raw["size"] < 0
                        or raw["size"] > recovery.MAX_ROW):
                    raise ValueError("Recovered draft history carrier exceeds its byte bound")
                row = recovery._load(raw["data"])
                closed(row, provenance.COLUMNS.split())
                yield row, raw["size"]

    rows, total = [], 0
    for count, (row, size) in enumerate(carriers(), 1):
        if type(size) is not int or size < 0 or size > recovery.MAX_ROW:
            raise ValueError("Recovered draft history carrier exceeds its byte bound")
        total += size
        if count > recovery.MAX_RECORDS or total > recovery.MAX_METADATA:
            raise ValueError("Recovered draft history exceeds its inventory bound")
        rows.append(row)
    with provenance.schema_definition_scope():
        provenance.validate_groups(rows)
        pending = [(rows, 0)]
        scanned, scanned_bytes = 0, 0
        while pending:
            selected, depth = pending.pop()
            if depth >= provenance.MAX_DEPTH:
                raise ValueError("Recovered draft history exceeds its nesting bound")
            nested = []
            for row in selected:
                scanned += 1
                scanned_bytes += len(row["body_json"].encode("utf-8"))
                if (scanned > recovery.MAX_RECORDS * provenance.MAX_DEPTH
                        or scanned_bytes > recovery.MAX_METADATA * provenance.MAX_DEPTH):
                    raise ValueError("Recovered draft history exceeds its traversal bound")
                value = provenance.decode(row)
                if value["kind"] != "row":
                    continue
                if value["table"] == PROTOCOL:
                    draft = history.wrap(PROTOCOL, value["record"])
                elif (value["table"] == history.TABLE
                      and value["record"]["protocol"] == PROTOCOL):
                    draft = value["record"]
                elif value["table"] == provenance.TABLE:
                    nested.append(value["record"])
                    continue
                else:
                    continue
                yield draft, len(draft["body_json"].encode("utf-8"))
            if nested:
                pending.append((nested, depth + 1))


def _rows(conn, identity):
    if _present(conn, history.TABLE, history.COLUMNS):
        for raw in conn.execute(
            "SELECT record_id,protocol,CASE WHEN length(CAST(body_json AS BLOB))<=? "
            "THEN body_json ELSE NULL END AS body_json,length(CAST(body_json AS BLOB)) AS size "
            "FROM research_history_archive WHERE protocol=? AND (? IS NULL OR record_id=?) "
            "ORDER BY record_id LIMIT ?",
            (history.MAX_ROW, PROTOCOL, identity, identity, 2 * history.MAX_RECORDS + 1),
        ):
            row = dict(raw)
            size = row.pop("size")
            yield row, size
    if _present(conn, "recovery_records", "table_name row_number data"):
        for raw in conn.execute(
            "SELECT table_name,CASE WHEN length(CAST(data AS BLOB))<=? "
            "THEN data ELSE NULL END AS data,length(CAST(data AS BLOB)) AS size "
            "FROM recovery_records WHERE table_name IN (?,?) "
            "AND CASE WHEN length(CAST(data AS BLOB))>? THEN 1 "
            "WHEN table_name=? THEN 1 WHEN json_valid(data) THEN "
            "json_extract(data,'$.protocol')=? "
            "AND (? IS NULL OR json_extract(data,'$.record_id')=?) ELSE 0 END "
            "ORDER BY table_name,row_number LIMIT ?",
            (
                MAX_CARRIER,
                history.TABLE,
                PROTOCOL,
                MAX_CARRIER,
                PROTOCOL,
                PROTOCOL,
                identity,
                identity,
                2 * history.MAX_RECORDS + 1,
            ),
        ):
            yield _carrier(raw["data"], raw_protocol=raw["table_name"] == PROTOCOL), raw["size"]

    yield from _provenance_rows(conn)


def _records(conn, identity=None):
    found, count, raw_total, unique_total = {}, 0, 0, 0
    for row, size in _rows(conn, identity):
        count += 1
        if type(size) is not int or size < 0:
            raise ValueError("Invalid historical draft carrier byte count")
        raw_total += size
        if count > 2 * history.MAX_RECORDS or raw_total > 4 * history.MAX_TOTAL:
            raise ValueError("Historical draft carriers exceed their inventory bound")
        value, _sources = history.validate(row)
        if row["protocol"] != PROTOCOL:
            raise ValueError("Historical draft carrier changed its declared identity")
        if identity is not None and row["record_id"] != identity:
            continue
        old = found.get(row["record_id"])
        if old is not None:
            if old[0] != row:
                raise ValueError("Conflicting historical draft carrier identity")
            continue
        unique_total += len(row["body_json"].encode("utf-8"))
        found[row["record_id"]] = (row, value["body"][:100] or "…")
        if len(found) > history.MAX_RECORDS or unique_total > history.MAX_TOTAL:
            raise ValueError("Historical drafts exceed their inventory bound")
    return found


def record(conn, identity):
    digest(identity)
    found = _records(conn, identity).get(identity)
    if found is None:
        raise ValueError("Saved historical draft is unavailable")
    return found[0]


def entries(conn, after, limit):
    if after[0] > ORIGIN:
        return []
    lower = after[1] if after[0] == ORIGIN else ""
    records = _records(conn)
    return [
        dict(origin=ORIGIN, id=identity, decision=None, summary=records[identity][1])
        for identity in sorted(records)
        if identity > lower
    ][: limit + 1]


def preview(row):
    value, _sources = history.validate(row)
    if row["protocol"] != PROTOCOL:
        raise ValueError("Not a historical saved review draft")
    snapshot = history._value(value["preview_json"])
    from paper_daily.review_draft_resumption import archived

    source = snapshot["source_hash"]
    try:
        adapter = archived(row)
        details = adapter._historical(row)
        source = details[1] if adapter.ORIGIN == "archived_note_resume" else details[2]
        resumable = True
    except ValueError:
        resumable = False
    return dict(
        resume_supported=resumable,
        retained={"body": value["body"]},
        source_hash=source,
        original=snapshot["current"],
        reason="Historical draft; review the current target and original before applying",
    )
