"""Explicit receiver-side resumption of historical text drafts.

Historical observations are only provenance. New bases belong to this receiver;
byte proofs remain process-only and publication shares the research transaction.
"""

from __future__ import annotations

import hmac
from contextlib import closing

from paper_daily import research_generation as generation
from paper_daily import sync_capture
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.research_review import Preview, digest, encode

ORIGIN = "archived_resume"
TEXT_TABLES = frozenset(
    {
        "dives",
        "close_readings",
        "paper_context",
        "list_surveys",
        "list_reading_goals",
    }
)


def _sealed(review, data):
    text = encode(data)
    return Preview(text, hmac.new(review._seal_key, text.encode(), "sha256").hexdigest())


def _historical(row):
    from paper_daily import enrollment_history as history

    value, _sources = history.validate(row)
    if row["protocol"] != "research_review_drafts":
        raise ValueError("Not a saved historical review draft")
    snapshot = history._value(value["preview_json"])
    source = snapshot["source_hash"]
    if value["origin"] in {"generation", "sidecar", ORIGIN}:
        table = generation.GenerationContext(snapshot["expected"]).table
        retained = dict(snapshot["retained"])
    elif value["origin"] == "remote":
        from paper_daily.sync_content import FEATURES

        payload = snapshot["retained"]
        if snapshot["scope"]["kind"] != "research_content":
            raise ValueError("Historical notes require their typed note resumption flow")
        feature = payload["feature"]
        table = FEATURES[feature][0]
        declared = payload.get("source_document_hash")
        if source is not None and declared is not None and source != declared:
            raise ValueError("Historical draft declares different source versions")
        source = declared or source
        if table not in TEXT_TABLES or payload["key"] != "main":
            raise ValueError("This historical content requires typed source-aware review")
        retained = dict(payload["data"])
        for key, value in list(retained.items()):
            if key.endswith("_json") and value is not None:
                retained[key] = encode(value)
    else:
        raise ValueError("Unsupported historical draft kind")
    if table not in TEXT_TABLES:
        raise ValueError("This historical content requires typed source-aware review")
    field = "body" if "body" in retained else "summary"
    if field not in retained:
        raise ValueError("This historical draft has no editable text")
    retained[field] = value["body"]
    if "edited" in retained:
        retained["edited"] = 1
    return table, retained, source, snapshot


def validate_snapshot(snapshot):
    """Additional closed-format rules beyond the ordinary generation draft codec."""
    from paper_daily.sync_files import digest as source_digest

    source_digest(snapshot["id"])
    expected = generation.GenerationContext(snapshot["expected"])
    if expected.table not in TEXT_TABLES or not snapshot["requires_confirmation"]:
        raise ValueError("Invalid resumed historical draft base")


def targets(review, preview, *, after="", limit=30):
    data = review._verify_preview(preview)
    if data["origin"] not in {"archived_draft", ORIGIN}:
        raise ValueError("Select a historical saved draft")
    if type(limit) is not int or not 1 <= limit <= 100 or not isinstance(after, str):
        raise ValueError("Invalid target page")
    if review.recovery:
        raise ValueError("Create an editable workspace copy before resuming recovered drafts")
    with closing(review._connect()) as conn:
        record = review._record(conn, data["origin"], data["id"])
        if digest(record) != data["record_hash"]:
            raise ValueError("Historical draft changed; reload it first")
        table, _retained, _source, _snapshot = _historical(record)
        kind = generation.REGISTRY[table][0]
        root, title = ("papers", "title") if kind == "paper" else ("lists", "name")
        rows = conn.execute(
            f'SELECT id,substr("{title}",1,200) AS title FROM "{root}" '
            "WHERE id>? ORDER BY id LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        review._check(conn)
    items = [dict(row) for row in rows[:limit]]
    return {"items": items, "next": items[-1]["id"] if len(rows) > limit else None}


def select(review, preview, target_id):
    """Capture a fresh base only on explicit target selection, never on restart."""
    data = review._verify_preview(preview)
    if data["origin"] not in {"archived_draft", ORIGIN}:
        raise ValueError("Select a historical saved draft")
    if not isinstance(target_id, str) or not target_id:
        raise ValueError("Select a research target")
    if review.recovery:
        raise ValueError("Create an editable workspace copy before resuming recovered drafts")
    with closing(review._connect()) as conn:
        conn.execute("BEGIN")
        record = review._record(conn, data["origin"], data["id"])
        if digest(record) != data["record_hash"]:
            raise ValueError("Historical draft changed; reload it first")
        table, retained, source, historical = _historical(record)
        kind, column, _feature, _reader = generation.REGISTRY[table]
        if source is not None and (kind != "paper" or review.binding is None):
            raise ValueError("Source-bound drafts require an enrolled current paper workspace")
        root, title = ("papers", "title") if kind == "paper" else ("lists", "name")
        parent = conn.execute(f'SELECT * FROM "{root}" WHERE id=?', (target_id,)).fetchone()
        if parent is None:
            raise ValueError("Selected target no longer exists")
        expected = generation.begin_generation(
            conn, table=table, owner_id=target_id, input_reader="target"
        )
        if kind == "paper":
            from paper_daily.document_reader import DocumentReader

            current_document = DocumentReader.from_workspace(review.path).resolve(target_id)
            if current_document.available:
                expected = generation.bind_inputs(expected, document=current_document)
        token = parent_lifecycle(conn, kind, target_id)
        if not token:
            raise ValueError("Selected target has no durable local lifecycle")
        retained[column] = target_id
        generation._validate_row(expected, retained)
        data.update(
            origin=ORIGIN,
            original=historical["current"],
            current=expected.target,
            retained=retained,
            source_hash=source,
            expected=expected._json,
            scope={"table": table, "owner_id": target_id},
            target={"id": target_id, "title": parent[title]},
            parent_token=token,
            parent_row=dict(parent),
            requires_confirmation=True,
            editable=True,
            apply=False,
            resume_state="verification_required",
            reason="Current target selected; verify the retained original before applying",
        )
        review._check(conn)
        return _sealed(review, data)


def check_base(review, conn, data):
    """Check exactly the displayed base; no old path reads or implicit rebasing."""
    if data["origin"] != ORIGIN:
        raise ValueError("Select a resumed historical draft")
    validate_snapshot(data)
    record = review._record(conn, ORIGIN, data["id"])
    if digest(record) != data["record_hash"]:
        raise ValueError("Historical draft changed; your draft is retained")
    expected = generation.GenerationContext(data["expected"])
    table, retained, source, _historical_snapshot = _historical(record)
    kind, column, _feature, _reader = generation.REGISTRY[table]
    retained[column] = expected.owner_id
    if (
        table != expected.table
        or retained != data["retained"]
        or source != data["source_hash"]
        or data["scope"] != {"table": table, "owner_id": expected.owner_id}
    ):
        raise ValueError("Resumed draft differs from its retained provenance")
    reason = generation._stale(conn, expected)
    root = "papers" if kind == "paper" else "lists"
    parent = conn.execute(f'SELECT * FROM "{root}" WHERE id=?', (expected.owner_id,)).fetchone()
    if (
        reason
        or parent is None
        or dict(parent) != data["parent_row"]
        or parent_lifecycle(conn, kind, expected.owner_id) != data["parent_token"]
    ):
        raise ValueError((reason or "Displayed target changed") + "; your draft is retained")
    review._check(conn)
    return expected


def source_intent(expected):
    from paper_daily.review_draft_sources import SourceIntent

    return SourceIntent(generation.REGISTRY[expected.table][0], expected.owner_id,
                        expected.data["document"])


def _proof_key(data):
    from paper_daily.review_draft_sources import key

    return key(data)


def verify(review, preview):
    from paper_daily import archived_draft_resume as adapter
    from paper_daily.review_draft_sources import verify as verify_source

    return verify_source(review, preview, adapter, document_check=_check_document)


def _check_document(document):
    from paper_daily.review_draft_sources import check_document

    return check_document(document)


def apply_in(review, conn, data, body, complete):
    """Publish source plus manual text in the caller's receipt transaction."""
    from paper_daily.review_draft_sources import publish_in

    expected = check_base(review, conn, data)
    publish_in(review, conn, data)
    row = dict(data["retained"])
    if body is not None:
        row["body" if "body" in row else "summary"] = body
    if "edited" in row:
        row["edited"] = 1
    generation._validate_row(expected, row)
    observation = expected.data["observation"]
    with sync_capture.expecting(
        conn,
        [observation],
        source_hashes={observation["entity_id"]: data["source_hash"]} if observation else {},
    ):
        column = generation.REGISTRY[expected.table][1]
        columns = list(row)
        quoted = ",".join(f'"{key}"' for key in columns)
        updates = ",".join(f'"{key}"=excluded."{key}"' for key in columns if key != column)
        conn.execute(
            f'INSERT INTO "{expected.table}"({quoted}) VALUES('
            + ",".join("?" for _ in columns)
            + f') ON CONFLICT("{column}") DO UPDATE SET {updates}',
            tuple(row.values()),
        )
        complete()
