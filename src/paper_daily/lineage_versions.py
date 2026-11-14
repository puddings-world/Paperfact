"""Bounded, read-only Lineage versions; listed provenance never grants restoration."""

from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime

from paper_daily import (
    lineage_lifecycle,
    lineage_package_publish,
    lineage_projection,
    lineage_publication,
    lineage_recovery,
    lineage_sets,
    lineage_wire,
)
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker
from paper_daily.manual_highlight_ops import HighlightOwner, _readonly_connection

MAX_RECORDS = 4096
MAX_TOTAL = 64 * 1024**2


def _records(conn, table, columns, *, where="", parameters=(), max_records=MAX_RECORDS):
    if not lineage_package_publish._schema(conn, table, columns):
        return []
    fields = columns.split()
    size_sql = "+".join(f"length(CAST({field} AS BLOB))" for field in fields)
    count, total, largest = conn.execute(
        f"SELECT count(*),COALESCE(sum({size_sql}),0),COALESCE(max({size_sql}),0) "
        f"FROM {table} {where}",
        parameters,
    ).fetchone()
    if count > max_records or total > MAX_TOTAL or largest > generation.MAX_CONTEXT_BYTES * 2:
        raise ValueError("Lineage version history exceeds its read budget")
    return [
        dict(zip(fields, row, strict=True))
        for row in conn.execute(
            f"SELECT {','.join(fields)} FROM {table} {where} ORDER BY rowid DESC LIMIT ?",
            (*parameters, max_records),
        )
    ]


def _recovered_versions(group):
    """Validated archive data only; none of these rows acquires a runtime origin."""
    layers = [group.lineage]
    if group.lineage_archive.lineage is not None:
        layers.append(group.lineage_archive.lineage)
    for layer in layers:
        yield from layer.rows.values()
        for receipt in layer.publications.values():
            yield lineage_recovery.publication(receipt)[0]
        yield from layer.imported.reports.values()
        for operation in layer.bound.history.values():
            if operation["action"] == "put":
                yield layer.bound._local_row(operation, group)
    for nested in getattr(group, "_recovered_groups", ()):
        yield from _recovered_versions(nested)


def collect(owner, *, limit=100, offset=0):
    """List actual generated/imported/native versions without model/file/network work.

    `current` describes exact visible equality, while `occupied` describes the
    corpus slot. An origin is provenance data, not current source permission.
    Rows displaced by import can be browsed even if their older receipt is absent;
    these have no origin and require reviewed adoption instead of direct restore.
    """
    _worker()
    if not isinstance(owner, HighlightOwner):
        raise ValueError("Lineage versions require their loaded owner")
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or type(offset) is not int
        or not 0 <= offset <= MAX_RECORDS
    ):
        raise ValueError("Invalid Lineage version page")
    with closing(_readonly_connection(owner.database)) as conn:
        conn.execute("BEGIN")
        owner.check(conn)
        found = {}

        def add(row, origin):
            lineage_sets.validate_row(row)
            if row["paper_id"] != owner.paper_id:
                return
            key = generation._json(row)
            if key not in found or found[key]["origin"] is None:
                found[key] = dict(row=row, origin=origin)
            if len(found) > MAX_RECORDS:
                raise ValueError("Lineage version catalog exceeds its record budget")

        if generation._binding(conn) is not None:
            for raw in _records(
                conn, lineage_projection.HISTORY, lineage_projection.HISTORY_COLUMNS
            ):
                operation = lineage_projection.validate_history(raw)
                if operation["action"] == "put":
                    add(
                        lineage_wire.decode_row(conn, operation["payload"]),
                        dict(kind="native", id=operation["operation_id"]),
                    )
        else:
            # Prefer the maintained imported receiver receipt for identical rows,
            # matching current-row origin selection. Newest receipt wins ties.
            for raw in _records(
                conn, lineage_package_publish.TABLE, lineage_package_publish.COLUMNS
            ):
                body = lineage_package_publish.validate_record(raw)
                for item in body["records"]:
                    add(json.loads(item["row_json"]), dict(kind="import", id=body["request_id"]))
                    previous = json.loads(item["before_json"])
                    if previous is not None:
                        add(previous, None)
            for raw in _records(conn, lineage_publication.TABLE, lineage_recovery.COLUMNS):
                row, _sources = lineage_recovery.publication(raw)
                add(row, dict(kind="generated", id=raw["request_id"]))
        # Local actions retain versions even if their provenance subsequently
        # becomes unavailable. They stay data, not a replacement provenance grant.
        for raw in _records(conn, lineage_lifecycle.TABLE, lineage_lifecycle.COLUMNS):
            body = lineage_lifecycle.validate_record(raw)
            row = json.loads(body["row_json"])
            if generation._json(row) not in found:
                add(row, None)
        # Enrollment preserves old receipts as archive data, never live grants.
        # Browse their scientific rows without inventing runtime restore origins.
        from paper_daily import enrollment_history

        archived_protocols = (
            "research_lineage_publications",
            "research_lineage_imports",
            "research_lineage_actions",
        )
        for wrapped in _records(
            conn,
            enrollment_history.TABLE,
            enrollment_history.COLUMNS,
            where="WHERE protocol IN (?,?,?)",
            parameters=archived_protocols,
        ):
            archived, _sources = enrollment_history.validate(wrapped)
            if wrapped["protocol"] == "research_lineage_publications":
                row, _originals = lineage_recovery.publication(archived)
                add(row, None)
            elif wrapped["protocol"] == "research_lineage_imports":
                action = lineage_package_publish.validate_record(archived)
                for item in action["records"]:
                    add(json.loads(item["row_json"]), None)
                    previous = json.loads(item["before_json"])
                    if previous is not None:
                        add(previous, None)
            else:
                action = lineage_lifecycle.validate_record(archived)
                add(json.loads(action["row_json"]), None)
        from paper_daily import recovery_provenance, sync_recovery

        recovered = _records(
            conn,
            recovery_provenance.TABLE,
            recovery_provenance.COLUMNS,
            max_records=sync_recovery.MAX_RECORDS,
        )
        if recovered:
            for group in recovery_provenance.validate_groups(recovered):
                for row in _recovered_versions(group):
                    add(row, None)
        current = {}
        for item in found.values():
            row = item["row"]
            key = row["corpus_key"]
            if key not in current:
                current[key] = lineage_projection._current(conn, owner.paper_id, key)
            item.update(current=current[key] == row, occupied=current[key] is not None)
        ordered = sorted(
            found.values(),
            key=lambda item: (
                datetime.fromisoformat(item["row"]["written_at"]),
                item["row"]["corpus_key"],
                generation._json(item["row"]),
            ),
            reverse=True,
        )
        return dict(
            items=ordered[offset : offset + limit],
            more=len(ordered) > offset + limit,
            total=len(ordered),
            offset=offset,
        )
