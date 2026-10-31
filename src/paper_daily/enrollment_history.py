"""Closed archive-only enrollment history; observations never become live job authority."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from paper_daily.enrollment_chat_history import FORMATS as CHAT_FORMATS
from paper_daily.inbox_recovery import PROTOCOL as INBOX_FORMATS
from paper_daily.sync_files import canonical_json, closed, digest, read_json

TABLE = "research_history_archive"
COLUMNS = "record_id protocol body_json"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_history_archive("
    "record_id TEXT PRIMARY KEY,protocol TEXT NOT NULL,body_json TEXT NOT NULL);"
)
FORMATS = {
    "reading_position_import_v1": (
        "package_sha256 source_owner receiver_owner document_hash incoming_json receiver_json"
    ),
    "queue_pin_import_v1": (
        "package_sha256 source_owner receiver_owner incoming_pinned_at receiver_pinned_at"
    ),
    "research_reading_position_receipts": "request_id request_json result_json",
    "research_generation_requests": "request_id context_json row_json status candidate_id reason",
    "research_generation_recovery": "request_id context_json row_json status candidate_id reason",
    "research_parent_lifecycle": "kind entity_id token active",
    **CHAT_FORMATS,
    **INBOX_FORMATS,
}
MAX_ROW = 8 * 1024**2
MAX_RECORDS = 10000
MAX_TOTAL = 64 * 1024**2


def _value(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_ROW:
        raise ValueError("Archived history JSON exceeds its bound")

    def pairs(values):
        out = {}
        for key, value in values:
            if key in out:
                raise ValueError("Duplicate archived history field")
            out[key] = value
        return out

    def invalid(_value):
        raise ValueError("Nonfinite archived history number")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
        read_json(canonical_json(value))
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("Invalid bounded archived history JSON") from exc
    return value


@lru_cache(maxsize=1)
def _columns():
    from paper_daily.sync_recovery import _research_schema

    return _research_schema()


def _snapshot(table, row, owner):
    if row is None:
        return set()
    if not isinstance(row, dict) or set(row) != set(_columns()[table]):
        raise ValueError("Unknown fields in archived research input snapshot")
    if any(value is not None and type(value) not in (str, int, float) for value in row.values()):
        raise ValueError("Archived SQL input contains a non-SQL scalar")
    from paper_daily import annotation_content
    from paper_daily.research_generation import REGISTRY

    column = "id" if table in {"papers", "lists"} else REGISTRY[table][1]
    if row[column] != owner:
        raise ValueError("Archived input belongs to another research owner")
    if table in annotation_content.FEATURES.values():
        feature = next(key for key, value in annotation_content.FEATURES.items() if value == table)
        if "body_json" in row:
            _value(row["body_json"])
        annotation_content.validate_row(feature, row)
    result = set()
    if row.get("document_hash") is not None:
        digest(row["document_hash"])
        result.add(row["document_hash"])
    return result


def generation_sources(row):
    """Validate closed original inputs and collect explicit source declarations only."""
    from paper_daily import research_generation as generation

    generation.validate_request_record(row)
    if len(row["context_json"].encode()) > generation.MAX_CONTEXT_BYTES:
        raise ValueError("Archived generation context exceeds its declared bound")
    context = _value(row["context_json"])
    output = _value(row["row_json"])
    owner = context["owner_id"]
    reader = context["input_reader"]
    inputs = context["inputs"]
    sources = _snapshot(context["table"], context["target"], owner)
    if context["document"] is not None:
        sources.add(context["document"]["sha256"])
    if output.get("document_hash") is not None:
        sources.add(output["document_hash"])
    if reader == "target":
        if inputs is not None:
            raise ValueError("Target-only history cannot carry unknown inputs")
    elif reader in {"claims", "questions", "reading_links"}:
        expected = {"dives", "close_readings"}
        flag = {
            "claims": "claims_known",
            "questions": "question_known",
            "reading_links": "links_known",
        }[reader]
        expected.add(flag)
        if reader == "reading_links":
            expected.add("paper_highlight_analysis")
        closed(inputs, expected)
        if type(inputs[flag]) is not bool:
            raise ValueError("Invalid archived known-deletion input")
        for table in expected - {flag}:
            sources.update(_snapshot(table, inputs[table], owner))
    elif reader == "highlights":
        # The normal publication validator already checks every mark/token/plan.
        for mark in inputs["marks"]:
            sources.add(mark["document_hash"])
    elif reader == "brief":
        closed(inputs, {"paper", "lineage", "recent"})
        paper = inputs["paper"]
        if paper is not None:
            closed(paper, set(_columns()["papers"]) | {"role", "reason"})
            _snapshot(
                "papers",
                {key: value for key, value in paper.items() if key not in {"role", "reason"}},
                owner,
            )
        if not isinstance(inputs["lineage"], str) or not isinstance(inputs["recent"], str):
            raise ValueError("Invalid archived reading context")
    elif reader == "overview":
        closed(inputs, {"paper", "dive", "refs", "later"})
        if inputs["paper"] is not None:
            closed(inputs["paper"], {"title", "venue", "year", "abstract"})
        if not isinstance(inputs["dive"], str):
            raise ValueError("Invalid archived overview input")
        for key, fields in [
            ("refs", {"title", "year", "verdict", "purpose"}),
            ("later", {"title", "year", "verdict", "relation", "why"}),
        ]:
            if not isinstance(inputs[key], list) or len(inputs[key]) > 30:
                raise ValueError("Archived overview input exceeds its bound")
            for value in inputs[key]:
                closed(value, fields)
    elif reader == "survey":
        closed(inputs, {"list", "papers", "_members"})
        _snapshot("lists", inputs["list"], owner)
        for key in ("papers", "_members"):
            if not isinstance(inputs[key], list) or len(inputs[key]) > generation.MAX_ROWS:
                raise ValueError("Archived list input exceeds its bound")
        for paper in inputs["papers"]:
            closed(paper, set(_columns()["papers"]) | {"dive", "context", "later"})
        for member in inputs["_members"]:
            closed(member, {"paper_id", "position"})
    else:
        raise ValueError("Unknown archived generation input reader")
    return sources


def validate_record(protocol, record):
    if not isinstance(protocol, str) or protocol not in FORMATS:
        raise ValueError("Unsupported archived history protocol")
    closed(record, FORMATS[protocol].split())
    if protocol == "reading_position_import_v1":
        from paper_daily.reading_position_packages import validate_import_record

        return validate_import_record(record)
    if protocol == "queue_pin_import_v1":
        from paper_daily.queue_pins import validate_import_record

        validate_import_record(record)
        return set()
    if protocol == "research_reading_position_receipts":
        from paper_daily.reading_position_ops import validate_receipt

        return validate_receipt(record)
    if protocol in INBOX_FORMATS:
        from paper_daily.inbox_content import validate_row as validate_inbox

        validate_inbox(protocol, record)
        return set()
    if protocol in CHAT_FORMATS:
        from paper_daily.enrollment_chat_history import validate_record as validate_chat

        return validate_chat(protocol, record)
    required_text = (
        ("kind", "entity_id", "token")
        if protocol == "research_parent_lifecycle"
        else ("request_id", "context_json", "row_json", "status", "reason")
    )
    if any(not isinstance(record[key], str) for key in required_text):
        raise ValueError("Invalid scalar type in archived history")
    if protocol != "research_parent_lifecycle" and (
        record["candidate_id"] is not None and not isinstance(record["candidate_id"], str)
    ):
        raise ValueError("Invalid archived candidate identity")
    if protocol == "research_parent_lifecycle":
        from paper_daily.research_lifecycle import validate_record as validate_epoch

        validate_epoch(record)
        return set()
    return generation_sources(record)


def wrap(protocol, record):
    validate_record(protocol, record)
    body = canonical_json(record)
    if len(body) > MAX_ROW:
        raise ValueError("Archived history exceeds its record bound")
    identity = hashlib.sha256(canonical_json({"protocol": protocol, "record": record})).hexdigest()
    return {"record_id": identity, "protocol": protocol, "body_json": body.decode("utf-8")}


def validate(row):
    closed(row, COLUMNS.split())
    digest(row["record_id"])
    if not isinstance(row["protocol"], str) or row["protocol"] not in FORMATS:
        raise ValueError("Unsupported archived history protocol")
    if not isinstance(row["body_json"], str) or len(row["body_json"].encode()) > MAX_ROW:
        raise ValueError("Archived history body exceeds its bound")
    record = read_json(row["body_json"].encode("utf-8"))
    sources = validate_record(row["protocol"], record)
    expected = hashlib.sha256(
        canonical_json({"protocol": row["protocol"], "record": record})
    ).hexdigest()
    if row["record_id"] != expected:
        raise ValueError("Archived history identity changed")
    return record, sources


def archived(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
        return []
    records = []
    total = 0
    for raw in conn.execute(
        "SELECT record_id,protocol,CASE WHEN length(CAST(body_json AS BLOB))<=? "
        "THEN body_json ELSE NULL END FROM research_history_archive "
        "ORDER BY record_id LIMIT ?",
        (MAX_ROW, MAX_RECORDS + 1),
    ):
        row = dict(zip(COLUMNS.split(), raw, strict=True))
        validate(row)
        records.append(row)
        total += len(row["body_json"].encode())
        if len(records) > MAX_RECORDS or total > MAX_TOTAL:
            raise ValueError("Archived history exceeds its inventory bound")
    return records


def retain_in(conn, records):
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError("History archive exceeds its record bound")
    if not records:
        return
    if not conn.in_transaction:
        raise ValueError("History archive requires a caller transaction")
    total = 0
    for row in records:
        validate(row)
        total += len(row["body_json"].encode())
        if total > MAX_TOTAL:
            raise ValueError("History archive exceeds its byte bound")
    conn.execute(SCHEMA)
    for row in records:
        prior = conn.execute(
            "SELECT protocol,body_json FROM research_history_archive WHERE record_id=?",
            (row["record_id"],),
        ).fetchone()
        if prior is not None and tuple(prior) != (row["protocol"], row["body_json"]):
            raise ValueError("History archive identity was reused")
        conn.execute(
            "INSERT OR IGNORE INTO research_history_archive VALUES(?,?,?)",
            (row["record_id"], row["protocol"], row["body_json"]),
        )


@lru_cache(maxsize=1)
def lifecycle_triggers():
    """Expected SQL comes from the maintained initializer, not the imported DB."""
    import sqlite3
    from contextlib import closing

    from paper_daily import store
    from paper_daily.research_lifecycle import TRIGGERS, ensure_lifecycle

    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(store.SCHEMA)
        conn.execute("BEGIN")
        ensure_lifecycle(conn)
        return {
            name: sql
            for name, sql in conn.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'")
            if name in TRIGGERS
        }


def verify_lifecycle_schema(conn):
    import re

    def normalized(sql):
        return re.sub(r"\s+", "", sql).lower().replace("ifnotexists", "").rstrip(";")

    for name, sql in lifecycle_triggers().items():
        actual = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)
        ).fetchone()
        if actual is None or normalized(actual[0] or "") != normalized(sql):
            raise ValueError("Parent lifecycle schema requires explicit repair before enrollment")


def collect(conn, database, ticket):
    """Read one caller snapshot; private JSON paths are observations only."""
    from pathlib import Path

    from paper_daily import annotation_content
    from paper_daily import research_generation as generation

    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    records = {row["record_id"]: row for row in archived(conn)}
    counts = {}
    sources = set()
    metadata = []
    keys = set()
    total = sum(len(row["body_json"].encode()) for row in records.values())
    if "research_parent_lifecycle" in names:
        verify_lifecycle_schema(conn)
    for protocol, fields in FORMATS.items():
        if protocol not in names:
            continue
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{protocol}")')]
        if columns != fields.split():
            raise ValueError("Unknown private history columns")
        count = 0
        selected = ",".join(
            f"CASE WHEN typeof([{name}]) IN ('text','blob') "
            f'AND length(CAST("{name}" AS BLOB))>{MAX_ROW} THEN NULL ELSE "{name}" END'
            for name in columns
        )
        for raw in conn.execute(f'SELECT {selected} FROM "{protocol}"'):
            ticket.check()
            value = dict(zip(columns, raw, strict=True))
            wrapped = wrap(protocol, value)
            logical = (
                (protocol, value.get("request_id"))
                if protocol not in {"research_parent_lifecycle", "research_chat_links"}
                else (protocol, value["local_id"])
                if protocol == "research_chat_links"
                else (protocol, value["kind"], value["entity_id"])
            )
            if logical in keys:
                raise ValueError("Duplicate private history identity")
            keys.add(logical)
            if wrapped["record_id"] not in records:
                total += len(wrapped["body_json"].encode())
            records[wrapped["record_id"]] = wrapped
            count += 1
            sources.update(validate(wrapped)[1])
            if count > MAX_RECORDS or len(records) > MAX_RECORDS or total > MAX_TOTAL:
                raise ValueError("Private history exceeds its inventory bound")
        counts[protocol] = count
    from paper_daily.enrollment_chat_history import sidecars as chat_sidecars

    for value, location in chat_sidecars(database, ticket):
        wrapped = wrap("research_chat_recovery", value)
        if wrapped["record_id"] not in records:
            total += len(wrapped["body_json"].encode())
        records[wrapped["record_id"]] = wrapped
        metadata.append(location)
        counts["research_chat_recovery"] = counts.get("research_chat_recovery", 0) + 1
    sidecars = generation.list_recovery_requests(database)
    counts["research_generation_recovery"] = counts.get("research_generation_recovery", 0) + len(
        sidecars
    )
    root = Path(database).resolve().parent
    for value in sidecars:
        ticket.check()
        wrapped = wrap("research_generation_recovery", value)
        if wrapped["record_id"] not in records:
            total += len(wrapped["body_json"].encode())
        records[wrapped["record_id"]] = wrapped
        sources.update(validate(wrapped)[1])
        context = generation.GenerationContext(value["context_json"])
        location = generation._recovery_path(context)
        if not location.is_relative_to(root):
            raise ValueError("Owned history sidecar is outside the selected workspace")
        metadata.append(str(location))
    if len(records) > MAX_RECORDS or total > MAX_TOTAL:
        raise ValueError("Private history exceeds its inventory bound")
    for value in records.values():
        sources.update(validate(value)[1])
    deletions = []
    for feature, owner in conn.execute("SELECT feature,paper_id FROM paper_annotation_known"):
        table = annotation_content.FEATURES.get(feature)
        if table is None:
            raise ValueError("Unknown annotation known-deletion feature")
        if not conn.execute("SELECT 1 FROM papers WHERE id=?", (owner,)).fetchone():
            raise ValueError("Known annotation has no current paper owner")
        if not conn.execute(f'SELECT 1 FROM "{table}" WHERE paper_id=?', (owner,)).fetchone():
            deletions.append({"feature": feature, "paper_id": owner})
    from collections import Counter

    coverage = dict(Counter(row["protocol"] for row in records.values()))
    return {
        "records": sorted(records.values(), key=lambda row: row["record_id"]),
        "counts": counts,
        "archive_counts": coverage,
        "sources": sorted(sources),
        "sidecars": sorted(metadata),
        "known_deletions": sorted(deletions, key=lambda row: (row["paper_id"], row["feature"])),
    }


def idle_lock_files(database):
    """Closed local mutex files are not research; active producers block a snapshot."""
    import errno
    import os
    import re
    from pathlib import Path

    from paper_daily.workspace_service import _safe_path

    root = _safe_path(Path(database).parent / ".research-jobs")
    if not root.exists():
        return []
    if not root.is_dir():
        raise ValueError("Invalid local research job lock directory")
    paths = []
    for item in sorted(root.iterdir()):
        _safe_path(item)
        if (
            not re.fullmatch(r"[0-9a-f]{64}\.lock", item.name)
            or not item.is_file()
            or item.stat().st_size != 1
        ):
            raise ValueError("Unknown local research job lock entry")
        if len(paths) >= MAX_RECORDS:
            raise ValueError("Local research job locks exceed their bound")
        with item.open("rb") as stream:
            acquired = False
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                if stream.read(2) != b"0":
                    raise ValueError("Unknown local research job lock content")
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise ValueError(
                        "Wait for active research work before preparing enrollment"
                    ) from exc
                raise
            finally:
                if acquired:
                    stream.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        paths.append(str(item))
    return paths


def canonical_research_rows(rows):
    """Only declared JSON storage columns normalize encoding; prose stays exact."""
    encoded = []
    for row in rows:
        value = dict(row)
        for key in ("body_json", "anchor", "contexts_json", "reading_json", "authors_json"):
            if value.get(key) is not None:
                value[key] = _value(value[key])
        encoded.append(canonical_json(value))
    return sorted(encoded)
