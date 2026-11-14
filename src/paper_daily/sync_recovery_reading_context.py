"""Read-only exact context for a retained native explanation-link operation.

Context digests bind displayed sections and ordered highlight items, not missing
execution metadata. This resolver grants no target write or replay authority.
"""

from __future__ import annotations

from contextlib import closing
from itertools import product

from paper_daily import reading_links
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_claim_group as history
from paper_daily import sync_recovery_highlight_group as highlights
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_client import validate_event
from paper_daily.sync_content import content_id
from paper_daily.sync_journal import MAX_BYTES, canonical_operation

FORMAT = "paperfact.recovery-reading-context.v1"
FEATURES = ("dive", "close_reading", "highlight_analysis")
MAX_VERSIONS = 32
MAX_COMBINATIONS = 512
MAX_CONTEXT_BYTES = 2 * 1024**2


def _valid(operation, root, feature):
    if operation is None:
        return feature != "highlight_analysis"
    if (
        operation["version"] != 2
        or operation["workspace_id"] != root["workspace_id"]
        or operation["entity_type"] != "research_content"
        or operation["entity_id"] != content_id(root["payload"]["scope"], feature, "main")
        or operation["parents"] != root["parents"]
    ):
        return False
    if operation["action"] == "delete":
        return feature != "highlight_analysis"
    payload = operation["payload"]
    if payload["feature"] != feature or payload["scope"] != root["payload"]["scope"]:
        return False
    if payload["source_document_hash"] not in (None, root["payload"]["source_document_hash"]):
        return False
    if feature == "highlight_analysis":
        return (
            payload["source_document_hash"] == root["payload"]["source_document_hash"]
            and payload["data"]["source_hash"]
            == root["payload"]["data"]["body_json"]["analysis_hash"]
        )
    return True


def _put(operation):
    return operation if operation and operation["action"] == "put" else None


def _parts(operations):
    return reading_links.sections(
        *(
            operation["payload"]["data"]["body"] if operation else None
            for operation in operations[:2]
        )
    )


def _matches(root, operations):
    if operations[2] is None:
        return False
    parts = _parts(operations)
    analysis = operations[2]["payload"]["data"]
    if (
        reading_links._key(parts, dict(analysis["body_json"], source_hash=analysis["source_hash"]))
        != root["payload"]["data"]["source_hash"]
    ):
        return False
    sections = {row["id"] for row in parts}
    items = analysis["body_json"]["items"]
    if any(
        link["section"] not in sections or link["quote"] >= len(items)
        for link in root["payload"]["data"]["body_json"]["links"]
    ):
        raise ValueError("Recorded link indexes do not belong to their exact context")
    return True


def _events(conn, identity, check):
    conn.set_progress_handler(lambda: (check(), 0)[1], 1000)
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()[0]
    for count, (sequence, raw) in enumerate(
        conn.execute(
            "SELECT sequence,event FROM paperfact_sync_inbox WHERE outcome='accepted' AND CASE "
            "WHEN length(CAST(event AS BLOB))<=? THEN CASE WHEN json_valid(event) THEN "
            "json_extract(event,'$.operation.entity_type')='research_content' AND "
            "json_extract(event,'$.operation.entity_id')=? ELSE 0 END ELSE 0 END "
            "ORDER BY sequence DESC",
            (candidates.review.MAX_EVENT, identity),
        ),
        1,
    ):
        check()
        if count > candidates.review.MAX_RECORDS:
            raise ValueError("Reading context exceeds its history budget")
        event = backup._decode(raw)
        validate_event(event, binding)
        if event["sequence"] != sequence or event["outcome"] != "accepted":
            raise ValueError("Reading context inbox disagrees with retained history")
        yield event["operation"]
        conn.set_progress_handler(lambda: (check(), 0)[1], 1000)


def _current(conn, root, feature, check):
    conn.set_progress_handler(lambda: (check(), 0)[1], 1000)
    identity = content_id(root["payload"]["scope"], feature, "main")
    current = history._head(conn, identity)
    if current is None:
        # Absence is usable only when no uncaptured native row is being ignored.
        empty = dict(scope=root["payload"]["scope"], feature=feature, key="main")
        return (None, history._visible(conn, empty) is None and feature != "highlight_analysis")
    retained = history._old(conn, current["operation_id"], check)
    if retained != current:
        raise ValueError("Reading context head differs from its native receipt")
    own = conn.execute(
        "SELECT 1 FROM paperfact_sync_operations WHERE operation_id=?", (current["operation_id"],)
    ).fetchone()
    if not own and not any(event == current for event in _events(conn, identity, check)):
        return None, False
    return _put(current), _valid(current, root, feature)


def _versions(conn, root, feature, current, valid, check):
    identity = content_id(root["payload"]["scope"], feature, "main")
    values, seen = [], set()

    def add(operation):
        if not _valid(operation, root, feature):
            return
        value = _put(operation)
        if value is None:
            signature = "absent"
        elif feature == "highlight_analysis":
            data = value["payload"]["data"]
            signature = candidates._json([data["source_hash"], data["body_json"]["items"]])
        else:
            body = value["payload"]["data"]["body"]
            signature = candidates._json(
                reading_links.sections(
                    body if feature == "dive" else None,
                    body if feature == "close_reading" else None,
                )
            )
        if signature in seen:
            return
        if len(values) >= MAX_VERSIONS:
            raise ValueError("Reading context exceeds its version budget; no history was truncated")
        seen.add(signature)
        values.append(value)

    if valid:
        add(current)
    conn.set_progress_handler(lambda: (check(), 0)[1], 1000)
    for count, (raw, fingerprint) in enumerate(
        conn.execute(
            "SELECT CASE WHEN length(CAST(envelope AS BLOB))<=? THEN envelope END,fingerprint "
            "FROM paperfact_sync_operations WHERE entity_type='research_content' AND entity_id=? "
            "ORDER BY sequence DESC",
            (MAX_BYTES, identity),
        ),
        1,
    ):
        check()
        if count > candidates.review.MAX_RECORDS or raw is None:
            raise ValueError("Reading context exceeds its record/byte budget")
        operation = backup._decode(raw)
        canonical_operation(operation)
        if candidates._fingerprint(operation) != fingerprint:
            raise ValueError("Reading context journal fingerprint changed")
        add(operation)
    for operation in _events(conn, identity, check):
        retained = history._old(conn, operation["operation_id"], check)
        if retained != operation:
            raise ValueError("Reading context differs from its accepted receipt")
        add(operation)
    return values


def resolve(source, change_id, *, seconds=30, cancelled=lambda: False):
    """Resolve historical visible context with bounded search; never write or call AI."""
    check = backup._guard(seconds, cancelled)
    if not isinstance(source, candidates.ReviewIndex):
        raise ValueError("Use a prepared source recovery review")
    source._check(check)
    root = source.details(change_id, cancelled=cancelled)["operation"]
    if (
        root["version"] != 2
        or root["entity_type"] != "research_content"
        or root["action"] != "put"
        or root["payload"].get("feature") != "reading_links"
        or root["payload"]["key"] != "main"
        or not root["payload"]["source_document_hash"]
    ):
        raise ValueError("Select native source-bound explanation links")
    with closing(_readonly_connection(source.database)) as conn:
        conn.execute("BEGIN")
        conn.set_progress_handler(lambda: (check(), 0)[1], 1000)
        current = [_current(conn, root, feature, check) for feature in FEATURES]
        selected = tuple(value[0] for value in current)
        if not all(value[1] for value in current) or not _matches(root, selected):
            versions = [
                _versions(conn, root, feature, *value, check)
                for feature, value in zip(FEATURES, current, strict=True)
            ]
            selected = None
            for count, combination in enumerate(product(*versions), 1):
                check()
                if count > MAX_COMBINATIONS:
                    raise ValueError(
                        "Reading context exceeds its search budget; review it explicitly"
                    )
                if _matches(root, combination):
                    selected = combination
                    break
            if selected is None:
                raise ValueError("No native history matches the exact explanation-link context")
    source._check(check)
    proof, _marks = highlights._locate_source(source, selected[2], check)
    native_members = [
        dict(feature=feature, operation=value, data=value["payload"]["data"] if value else None)
        for feature, value in zip(FEATURES, selected, strict=True)
    ]
    native_members.append(
        dict(feature="reading_links", operation=root, data=root["payload"]["data"])
    )
    source._check(check)
    highlights.native._original_current(proof)
    result = dict(
        format=FORMAT,
        state="resolved_read_only",
        members=native_members,
        source_operation_id=root["operation_id"],
        original_hash=root["payload"]["source_document_hash"],
        link_count=len(root["payload"]["data"]["body_json"]["links"]),
        context_binding="sections-and-ordered-highlight-items",
        semantics="not_checked",
        write_authority=False,
    )

    if len(candidates._json(result).encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError("Reading context exceeds its result byte budget")
    return result
