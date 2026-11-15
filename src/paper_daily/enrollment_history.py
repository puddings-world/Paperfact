"""Closed archive-only enrollment history; observations never become live job authority."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from paper_daily.enrollment_chat_history import FORMATS as CHAT_FORMATS
from paper_daily.enrollment_integration_history import FORMATS as INTEGRATION_FORMATS
from paper_daily.inbox_recovery import PROTOCOL as INBOX_FORMATS
from paper_daily.sync_files import canonical_json, closed, digest, read_json

TABLE = "research_history_archive"
COLUMNS = "record_id protocol body_json"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_history_archive("
    "record_id TEXT PRIMARY KEY,protocol TEXT NOT NULL,body_json TEXT NOT NULL);"
)
COMPOUND_TEXT = "compound_text_history_v1"
MAX_TEXT = 3 * 1024**2
FORMATS = {
    COMPOUND_TEXT: "protocol request text",
    "research_lineage_publications": "request_id candidate_id row_json sources_json",
    "research_lineage_imports": "request_id body_json",
    "research_lineage_actions": "request_id body_json",
    "research_observed_current_deck_recovery": "paper_id slot parent_token manifest_json",
    "research_local_deck_proposals": (
        "proposal_id request_id paper_id captured_json owner_json manifest_json fingerprint"
    ),
    "research_enrolled_deck_proposals": (
        "proposal_id request_id local_id portable_id captured_json owner_json "
        "manifest_json fingerprint"
    ),
    "research_common_deck_proposal_recovery": (
        "record_id paper_id proposal_id manifest_json provenance_json"
    ),
    "common_proposal_adoption_v1": "source_id proposal_id receiver_json fingerprint",
    "later_outcome_import_v1": (
        "package_sha256 source_owner receiver_owner incoming_json receiver_json"
    ),
    "research_compound_requests": (
        "request_id context_json mutations_json status candidate_id reason"
    ),
    "research_compound_recovery": (
        "request_id context_json mutations_json status candidate_id reason"
    ),
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
    "research_review_receipts": (
        "request_id fingerprint origin origin_id decision result provenance"
    ),
    "research_review_drafts": (
        "draft_id origin origin_id owner_json preview_json body request_id revision "
        "updated_at save_order fingerprint"
    ),
    **CHAT_FORMATS,
    **INTEGRATION_FORMATS,
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
    if context.get("format") == "paperfact.lineage-proposal-context.v1":
        from paper_daily.lineage_candidates import originals

        return {r["sha256"] for r in originals(row)}
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
    elif reader == "later_outcome":
        from paper_daily.later_outcome_history import generation_inputs

        generation_inputs(inputs)
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
    if protocol == COMPOUND_TEXT:
        if not isinstance(record["request"], dict):
            raise ValueError("Invalid extracted-text history request")
        if not isinstance(record["protocol"], str) or record["protocol"] not in {
            "research_compound_requests", "research_compound_recovery"
        }:
            raise ValueError("Unsupported extracted-text history origin")
        return compound_sources(record["request"], text_snapshot=record["text"])
    if protocol in INTEGRATION_FORMATS:
        from paper_daily.enrollment_integration_history import validate_record as validate_import

        return validate_import(protocol, record)
    if protocol == "research_lineage_publications":
        from paper_daily.lineage_recovery import publication

        _row, sources = publication(record)
        return {source["sha256"] for source in sources}
    if protocol == "research_lineage_imports":
        from paper_daily.lineage_package_publish import validate_record as validate_import
        from paper_daily.lineage_sets import decode

        action = validate_import(record)
        sources = {source["sha256"] for item in action["records"] for source in item["sources"]}
        for item in action["records"]:
            before = _value(item["before_json"])
            if before is not None:
                sources.update(
                    source["document_hash"]
                    for source in decode(before["body_json"])["report"]["sources"]
                    if source["availability"] == "available"
                )
        return sources
    if protocol == "research_lineage_actions":
        from paper_daily.lineage_lifecycle import validate_record as validate_action

        validate_action(record)
        return set()  # Archive evidence grants no source ownership or replay rights.
    if protocol == "research_observed_current_deck_recovery":
        from paper_daily.proposal_recovery_current import validate as validate_current

        value = validate_current(record)
        return {item["sha256"] for item in value["originals"]}
    if protocol in {"research_local_deck_proposals", "research_enrolled_deck_proposals"}:
        from paper_daily import enrolled_deck_proposals, local_deck_proposals

        module = (
            local_deck_proposals
            if protocol == local_deck_proposals.TABLE
            else enrolled_deck_proposals
        )
        module.validate_record(record)
        return set()  # Full bytes are declared only by the separately validated carrier.
    if protocol == "research_common_deck_proposal_recovery":
        from paper_daily import proposal_recovery

        manifest = proposal_recovery.validate_row(record)["manifest"]
        return {item["sha256"] for item in manifest["originals"]}
    if protocol == "common_proposal_adoption_v1":
        from paper_daily.proposal_recovery_review import validate_link

        return validate_link(record)
    if protocol == "later_outcome_import_v1":
        from paper_daily.later_outcome_packages import validate_import_record

        return validate_import_record(record)
    if protocol in {"research_compound_requests", "research_compound_recovery"}:
        return compound_sources(record)
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
    if protocol == "research_review_receipts":
        from paper_daily.enrollment_review_decisions import source_hashes

        return source_hashes(record)
    if protocol == "research_review_drafts":
        from paper_daily.enrollment_review_drafts import source_hashes

        return source_hashes(record)
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
    text_snapshots = {}
    for archived_row in records.values():
        if archived_row["protocol"] == COMPOUND_TEXT:
            saved, _ = validate(archived_row)
            text_snapshots[compound_text_key(saved["request"])] = saved["text"]
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
            if protocol in {"research_compound_requests", "research_compound_recovery"}:
                wrapped, text_path = wrap_compound_input(protocol, value, database, ticket)
                if text_path is not None:
                    metadata.append(str(text_path))
                    text_snapshots[compound_text_key(value)] = _value(wrapped["body_json"])["text"]
            else:
                wrapped = wrap(protocol, value)
            logical = (
                (protocol, value["id"])
                if protocol in INTEGRATION_FORMATS
                else (protocol, value["draft_id"])
                if protocol == "research_review_drafts"
                else (protocol, value.get("request_id"))
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
    from paper_daily import research_compound as compound

    for value in compound.list_recovery_requests(database):
        ticket.check()
        wrapped, text_path = wrap_compound_input(
            "research_compound_recovery", value, database, ticket
        )
        if text_path is not None:
            metadata.append(str(text_path))
            text_snapshots[compound_text_key(value)] = _value(wrapped["body_json"])["text"]
        if wrapped["record_id"] not in records:
            total += len(wrapped["body_json"].encode())
        records[wrapped["record_id"]] = wrapped
        sources.update(validate(wrapped)[1])
        location = compound._recovery_path(compound.Context(value["context_json"]))
        if not location.is_relative_to(root):
            raise ValueError("Owned empty-query sidecar is outside selected workspace")
        metadata.append(str(location))
        counts["research_compound_recovery"] = counts.get("research_compound_recovery", 0) + 1
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
        "sidecars": sorted(set(metadata)),
        "compound_text_snapshots": text_snapshots,
        "known_deletions": sorted(deletions, key=lambda row: (row["paper_id"], row["feature"])),
    }


class ActiveResearchWork(ValueError):
    """A recognized native producer still owns its local coordination lock."""


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
                    raise ActiveResearchWork(
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


def canonical_membership_rows(rows):
    """Preserve complete list order and fields while adopting native dense ordinals."""
    lists = {}
    for item in rows:
        row = dict(item)
        if type(row.get("position")) is not int or row["position"] < 0:
            raise ValueError("List positions need explicit ordering repair")
        lists.setdefault(row["list_id"], []).append(row)
    canonical = []
    for members in lists.values():
        if len({row["position"] for row in members}) != len(members):
            raise ValueError("Ambiguous list positions need explicit ordering repair")
        for position, row in enumerate(sorted(members, key=lambda row: row["position"])):
            row["position"] = position
            canonical.append(row)
    return canonical_research_rows(canonical)
def compound_sources(record, *, text_snapshot=None):
    """Retain typed compound history without replaying its model or publication."""
    from paper_daily import research_compound as compound
    from paper_daily import sync_content

    context = _value(record["context_json"])
    _value(record["mutations_json"])
    compound.validate_request_record(record)
    if type(context["version"]) is not int:
        raise ValueError("Unsupported archived compound version")
    phase = context["phase"]
    if phase not in ("citations", "judge") and context["prompts"]:
        raise ValueError("Unexpected model inputs for archived lookup or manual work")
    paper = context["paper"]
    closed(paper, set(compound.PAPER_INPUT_COLUMNS[phase].split(",")))
    for key, value in paper.items():
        if key == "year":
            sync_content._integer(value, nullable=True)
        else:
            sync_content._text(value, 32768, nullable=key != "id")
    if phase == "resources" and paper["authors_json"] is not None:
        authors = _value(paper["authors_json"])
        if not isinstance(authors, list) or len(authors) > 512:
            raise ValueError("Unsupported resource author snapshot")
        for author in authors:
            sync_content._text(author, 4096, nullable=False)
    text = context["text_source"]
    if text is not None and text["sha256"] is not None:
        if not isinstance(text_snapshot, str):
            raise ValueError("Extracted compound text requires retained verified bytes")
        try:
            raw_text = text_snapshot.encode("utf-8")
        except UnicodeError:
            raise ValueError("Invalid retained extracted-text encoding") from None
        if len(raw_text) > MAX_TEXT or hashlib.sha256(raw_text).hexdigest() != text["sha256"]:
            raise ValueError("Retained extracted-text bytes differ from the observation")
    elif text_snapshot is not None:
        raise ValueError("Unexpected retained text without its original observation")
    source = (context["document"] or {}).get("sha256")
    feature, column = compound.TABLES[compound.PHASES[phase]]
    for row in context["rows"]:
        data = {key: row[key] for key in sync_content.FEATURES[feature][2].split()}
        if data.get("contexts_json") is not None:
            data["contexts_json"] = _value(data["contexts_json"])
        sync_content.validate_payload(
            dict(
                scope={"kind": "paper", "id": "11111111-1111-4111-8111-111111111111"},
                feature=feature,
                key=row[column],
                data=data,
                source_document_hash=source,
            )
        )
    return {source} if source is not None else set()


def resource_sources(record):
    """Keep the resource-specific validator closed to other compound phases."""
    context = _value(record["context_json"])
    if not isinstance(context, dict) or context.get("phase") != "resources":
        raise ValueError("Select archived resource work")
    return compound_sources(record)


def redundant_compound_hint(conn, row, *, text_snapshots=None):
    """A completion hint is redundant only with its validated accepted archive input."""
    import sqlite3

    scope = next(
        (
            (prefix, phase)
            for prefix, phase in (("resources:", "resources"), ("followups.checked.", "fetch"))
            if row["key"].startswith(prefix)
        ),
        None,
    )
    if scope is None:
        return False
    prefix, phase = scope
    owner = row["key"][len(prefix) :]
    try:
        completion = _value(row["value"])
        if not owner:
            return False
        if phase == "resources":
            if completion not in ("text", "notext"):
                return False
        else:
            from paper_daily.sync_content import _stamp

            _stamp(completion)
        if not conn.execute("SELECT 1 FROM papers WHERE id=?", (owner,)).fetchone():
            return False
        protocol = "research_compound_requests"
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (protocol,)
        ).fetchone():
            return False
        fields = FORMATS[protocol].split()
        if [
            r[1] for r in conn.execute('PRAGMA table_info("research_compound_requests")')
        ] != fields:
            return False
        query = (
            "SELECT "
            + ",".join(
                f'CASE WHEN length(CAST("{field}" AS BLOB))<=? THEN "{field}" END'
                for field in fields
            )
            + ",CASE WHEN length(CAST(candidate_id AS BLOB))>? THEN 1 ELSE 0 END"
            + " FROM research_compound_requests WHERE status='accepted' AND "
            + "CASE WHEN length(CAST(context_json AS BLOB))<=? THEN "
            + "CASE WHEN json_valid(context_json) THEN json_extract(context_json,'$.owner_id') "
            + "END END=? LIMIT ?"
        )
        total = 0
        arguments = (*([MAX_ROW] * (len(fields) + 2)), owner, MAX_RECORDS + 1)
        for count, record in enumerate(conn.execute(query, arguments), 1):
            value = dict(zip(fields, record[:-1], strict=True))
            if record[-1] or any(value[key] is None for key in fields if key != "candidate_id"):
                return False
            total += sum(
                len(item.encode("utf-8")) for item in value.values() if isinstance(item, str)
            )
            if count > MAX_RECORDS or total > MAX_TOTAL:
                return False
            context = _value(value["context_json"])
            if context.get("phase") != phase or context.get("owner_id") != owner:
                continue
            retained = (text_snapshots or {}).get(compound_text_key(value))
            compound_sources(value, text_snapshot=retained)
            if _value(value["mutations_json"])["completion"] == completion:
                return True
    except (ValueError, TypeError, AttributeError, sqlite3.Error):
        return False
    return False


def compound_text_key(record):
    """Match a complete exact request, never just a reused request identifier."""
    return hashlib.sha256(canonical_json(record)).hexdigest()


def wrap_compound_input(protocol, record, database, ticket):
    """Read only a known workspace cache name; observed paths are not capabilities."""
    import os
    from pathlib import Path

    from paper_daily.fetch import _safe_name
    from paper_daily.file_change import version
    from paper_daily.sync_recovery import _path

    context = _value(record["context_json"])
    text = context.get("text_source") if isinstance(context, dict) else None
    if not isinstance(text, dict) or text.get("sha256") is None:
        return wrap(protocol, record), None
    from paper_daily import research_compound as compound

    compound.validate_request_record(record)
    digest(text["sha256"])
    root = Path(database).absolute().parent
    filename = _safe_name(context["owner_id"]) + ".txt"
    recorded = os.path.normcase(os.path.abspath(text["path"]))
    candidates = [root / folder / filename for folder in ("text", "pdf")]
    selected = next(
        (path for path in candidates if os.path.normcase(str(path.absolute())) == recorded), None
    )
    if selected is None:
        raise ValueError("Extracted input requires its known workspace cache location")
    ticket.check()
    try:
        selected = _path(selected)
        before = version(selected)
        with selected.open("rb") as stream:
            raw = stream.read(MAX_TEXT + 1)
            opened = version(selected, stream=stream)
        after = version(selected)
    except OSError:
        raise ValueError("Retained extracted text is missing or inaccessible") from None
    ticket.check()
    if before != opened or before != after:
        raise ValueError("Extracted input changed during capture")
    if len(raw) > MAX_TEXT or hashlib.sha256(raw).hexdigest() != text["sha256"]:
        raise ValueError("Extracted input bytes differ from their recorded observation")
    try:
        retained = raw.decode("utf-8")
    except UnicodeError:
        raise ValueError("Invalid extracted-text encoding") from None
    wrapped = wrap(COMPOUND_TEXT, dict(protocol=protocol, request=record, text=retained))
    return wrapped, selected
