"""Closed log-owned Markdown recovery, paths remain passive sender observations."""

from __future__ import annotations

import hashlib
from pathlib import Path

from paper_daily import legacy_briefs, legacy_workflow
from paper_daily.sync_files import canonical_json

TABLE = "research_legacy_brief_recovery"
COLUMNS = "local_id paper_id sha256 size media_type legacy_day"


def validate(row):
    from paper_daily.sync_files import closed

    closed(row, COLUMNS.split())
    if type(row["local_id"]) is not int or not 0 < row["local_id"] <= 2**63 - 1:
        raise ValueError("Invalid original reading-event identity")
    legacy_workflow._text(row["paper_id"], 4096)
    if not row["paper_id"]:
        raise ValueError("Brief requires its original paper")
    legacy_workflow.validate_descriptor({key: row[key] for key in ("sha256", "size", "media_type")})
    legacy_briefs._day(row["legacy_day"])
    return row


def relative(row):
    validate(row)
    return (
        Path("briefs")
        / (row["legacy_day"] or "undated")
        / (str(row["local_id"]) + "-" + row["sha256"] + ".md")
    )


def collect(conn, database, destination, *, legacy_root=None, blob_store=None):
    """Read only explicit current log declarations, no history-context path scan."""
    from paper_daily.sync_artifacts import (
        applied_file,
        desired_file,
        verify_closure,
        version_directory,
    )
    from paper_daily.sync_files import file_id

    # Reject oversized scalars before fetching their contents from a source DB.
    limits = dict(
        id=128, paper_id=4096, delivered_at=64, brief_path=32768, role=128, note=200 * 1024
    )
    for name, maximum in limits.items():
        if conn.execute(
            'SELECT 1 FROM reading_log WHERE typeof("'
            + name
            + '") IN (?,?) AND length(CAST("'
            + name
            + '" AS BLOB))>? LIMIT 1',
            ("text", "blob", maximum),
        ).fetchone():
            raise ValueError("Reading brief metadata exceeds its closed field bound")
    rows, objects, aliases = [], {}, {}
    byte_total = 0
    total = 0
    root = Path(legacy_root or Path(database).parent)
    registered = legacy_briefs.registered_paths(conn)
    for count, raw in enumerate(
        conn.execute(
            "SELECT * FROM reading_log ORDER BY id LIMIT ?", (legacy_workflow.MAX_ROWS + 1,)
        ),
        1,
    ):
        row = dict(raw)
        legacy_workflow.validate_event(row)
        total += len(canonical_json(row))
        if count > legacy_workflow.MAX_ROWS or total > legacy_workflow.MAX_METADATA:
            raise ValueError("Reading brief metadata exceeds its bounded inventory")
        if row["brief_path"] is None:
            continue
        source = Path(row["brief_path"])
        if not source.is_absolute():
            source = root / source
        trusted_root = root / "briefs"
        if not source.is_relative_to(trusted_root):
            # Enrolled bytes must be exactly the current desired AND applied file,
            # current event incarnation and declared digest; not a guessed cache name.
            if registered is None:
                raise ValueError("Reading brief is outside its declared owned root")
            mapping = conn.execute(
                "SELECT sync_key FROM research_content_identity "
                "WHERE feature='reading_event' AND local_id=? AND paper_id=?",
                (row["id"], row["paper_id"]),
            ).fetchone()
            portable = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (row["paper_id"],)
            ).fetchone()
            if mapping is None or portable is None:
                raise ValueError("Reading brief lacks an exact owner identity")
            operation = applied_file(conn, file_id(portable[0], "legacy_brief", mapping[0]))
            if operation is None or desired_file(conn, operation["entity_id"]) != operation:
                raise ValueError("Reading brief is not the current applied file")
            if blob_store is None or blob_store.root != registered[0]:
                raise ValueError("Reading brief requires its explicitly owned blob store")
            versions = registered[1]
            proof, body, _objects = verify_closure(blob_store, operation)
            if not proof.matches(operation):
                raise ValueError("Reading brief closure changed")
            from paper_daily.sync_content import content_id

            marker = conn.execute(
                "SELECT incarnation,parent_incarnation FROM research_content_projection "
                "WHERE entity_id=? AND feature='reading_event'",
                (content_id({"kind": "paper", "id": portable[0]}, "reading_event", mapping[0]),),
            ).fetchone()
            if marker is None or tuple(marker) != (
                body["event_incarnation"],
                operation["parents"][0]["incarnation"],
            ):
                raise ValueError("Reading brief belongs to an older event or paper lifetime")
            if source != version_directory(versions, operation) / legacy_briefs.filename(body):
                raise ValueError("Reading brief path is not its owned materialization")
            target = legacy_briefs.target(conn, mapping[0])
            descriptor = {
                key: operation["payload"]["assets"][0][key]
                for key in ("sha256", "size", "media_type")
            }
            if (
                target is None
                or target["paper_id"] != row["paper_id"]
                or target["descriptor_json"] != canonical_json(descriptor).decode()
            ):
                raise ValueError("Reading brief differs from its logical declaration")
            prepared = legacy_workflow.read_brief(source, trusted_root=source.parent)
            day = body["legacy_day"]
        else:
            prepared = legacy_workflow.read_brief(source, trusted_root=trusted_root)
            day = prepared.legacy_day
        item = dict(
            local_id=row["id"], paper_id=row["paper_id"], **prepared.descriptor, legacy_day=day
        )
        validate(item)
        rows.append(item)
        if item["sha256"] not in objects:
            byte_total += len(prepared.data)
            if byte_total > 8 * 1024**3:
                raise ValueError("Legacy briefs exceed the bounded archive bytes")
            target_path = Path(destination) / (item["sha256"] + ".md")
            with target_path.open("xb") as stream:
                stream.write(prepared.data)
            objects[item["sha256"]] = target_path
        aliases[source] = (item["sha256"], item["size"])
    return rows, objects, aliases


def validate_records(records):
    for identity, row in records.legacy_briefs.items():
        event = records.legacy_events.get(identity)
        if event is None or event["paper_id"] != row["paper_id"] or not event["brief_path"]:
            raise ValueError("Recovered brief has no exact declared reading event")
        if row["paper_id"] not in records.paper_ids:
            raise ValueError("Recovered brief has no paper owner")
    for identity, event in records.legacy_events.items():
        if event["brief_path"] is not None and identity not in records.legacy_briefs:
            raise ValueError("Declared reading brief lacks its verified recovery closure")


def restore(stage, records):
    """Read-only text cache, never activate a sender path or sync identity."""
    for row in records.legacy_briefs.values():
        source = stage / "objects" / row["sha256"]
        data = source.read_bytes()
        if len(data) != row["size"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("Recovered Markdown differs from its declared bytes")
        legacy_briefs.validate_markdown(data)
        target = stage / relative(row)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
