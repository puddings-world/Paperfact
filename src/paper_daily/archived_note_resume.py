"""Typed rich-note continuation, with receiver identity and source A kept distinct."""

from __future__ import annotations

import re
from contextlib import closing
from pathlib import PurePosixPath, PureWindowsPath

from paper_daily import review_draft_sources as sources
from paper_daily import sync_capture
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.research_review import digest, encode
from paper_daily.sync_content import RICH_NOTE_FIELDS, validate_rich_note
from paper_daily.sync_files import closed, uuid
from paper_daily.sync_files import digest as hash_value
from paper_daily.sync_journal import _identifier

ORIGIN = "archived_note_resume"
NOTE_FIELDS = {"id", *RICH_NOTE_FIELDS}
EXPECTED = {
    "version",
    "db_path",
    "database_identity",
    "binding",
    "note_id",
    "note_sync_id",
    "paper_id",
    "paper_sync_id",
    "current",
    "observation",
    "parent_lifecycle",
    "document",
}


def _value(raw):
    from paper_daily.enrollment_history import _value as parse

    return parse(raw)


def _source(payload, recorded):
    anchor = payload.get("anchor")
    actual = anchor.get("document_hash") if isinstance(anchor, dict) else None
    if recorded is not None and actual is not None and recorded != actual:
        raise ValueError("Historical note declares contradictory original versions")
    source = actual or recorded
    if source is not None:
        hash_value(source)
    return source


def _historical(record):
    from paper_daily import enrollment_history as history

    value, _sources = history.validate(record)
    if record["protocol"] != "research_review_drafts":
        raise ValueError("Not a saved historical note draft")
    snapshot = _value(value["preview_json"])
    if (
        value["origin"] == "remote" and snapshot["scope"]["kind"] == "note"
    ) or value["origin"] == ORIGIN:
        payload = dict(snapshot["retained"])
    else:
        raise ValueError("Select a historical note draft")
    if set(payload) == {"paper_id", "body"}:
        payload.update(kind="note", created_at="1970-01-01T00:00:00+00:00", page=None, anchor=None)
    closed(payload, RICH_NOTE_FIELDS)
    # Receiver paper/creation identity is chosen explicitly, never inherited here.
    payload["body"] = value["body"]
    return payload, _source(payload, snapshot["source_hash"]), snapshot


def _row_payload(row, paper):
    closed(row, NOTE_FIELDS)
    if type(row["id"]) is not int or row["id"] < 1 or not isinstance(row["paper_id"], str):
        raise ValueError("Invalid saved note SQL identity")
    payload = {key: row[key] for key in RICH_NOTE_FIELDS}
    payload["paper_id"] = paper
    payload["anchor"] = _value(row["anchor"]) if row["anchor"] is not None else None
    validate_rich_note(payload)
    return payload


def _document(value):
    if value is None:
        return
    closed(value, {"sha256", "path", "target", "managed"})
    hash_value(value["sha256"])
    if (
        not isinstance(value["path"], str)
        or not (
            PurePosixPath(value["path"]).is_absolute()
            or PureWindowsPath(value["path"]).is_absolute()
        )
        or type(value["managed"]) is not bool
        or (value["target"] is not None and not isinstance(value["target"], dict))
    ):
        raise ValueError("Invalid saved note current-document observation")


def validate_snapshot(snapshot, owner):
    """Closed private format, with no file access and no generated-table coercion."""
    hash_value(snapshot["id"])
    expected = snapshot["expected"]
    if not isinstance(expected, dict):
        raise ValueError("Invalid saved note observation")
    version = expected.get("version")
    closed(expected, EXPECTED | ({"source_choice"} if version == 2 else set()))
    if type(version) is not int or version not in (1, 2):
        raise ValueError("Invalid saved note observation version")
    for field, owner_field in (
        ("db_path", "path"),
        ("database_identity", "identity"),
        ("binding", "binding"),
    ):
        if expected[field] != owner[owner_field]:
            raise ValueError("Saved note observation differs from its owner")
    if expected["binding"] is None:
        raise ValueError("Saved note needs a managed local workspace")
    uuid(expected["note_sync_id"])
    uuid(expected["paper_sync_id"])
    if (
        type(expected["note_id"]) is not int
        or expected["note_id"] < 1
        or not isinstance(expected["paper_id"], str)
        or not expected["paper_id"]
    ):
        raise ValueError("Invalid saved note target identity")
    _row_payload(expected["current"], expected["paper_sync_id"])
    if (
        expected["current"]["id"] != expected["note_id"]
        or expected["current"]["paper_id"] != expected["paper_id"]
    ):
        raise ValueError("Saved note base differs from its target")
    token = expected["observation"]
    closed(
        token,
        {
            "workspace_id",
            "kind",
            "entity_id",
            "revision",
            "predecessor",
            "incarnation",
            "active",
            "parents",
        },
    )
    if (
        token["workspace_id"] != owner["binding"]["workspace_id"]
        or token["kind"] != "note"
        or token["entity_id"] != expected["note_sync_id"]
        or type(token["revision"]) is not int
        or token["revision"] < 0
        or token["active"] is not True
    ):
        raise ValueError("Invalid saved note operation observation")
    _identifier(token["incarnation"])
    if token["predecessor"] is not None:
        _identifier(token["predecessor"])
    if not isinstance(token["parents"], list) or len(token["parents"]) != 1:
        raise ValueError("Invalid saved note parent observation")
    parent = token["parents"][0]
    closed(parent, {"kind", "id", "incarnation", "active"})
    if (
        parent["kind"] != "paper"
        or parent["id"] != expected["paper_sync_id"]
        or parent["active"] is not True
    ):
        raise ValueError("Saved note belongs to another parent")
    _identifier(parent["incarnation"])
    if not isinstance(expected["parent_lifecycle"], str) or not re.fullmatch(
        r"[0-9a-f]{32}", expected["parent_lifecycle"]
    ):
        raise ValueError("Invalid saved note parent epoch")
    _document(expected["document"])
    if (
        snapshot["origin"] != ORIGIN
        or snapshot["current"] != expected["current"]
        or snapshot["scope"] != {"kind": "note", "id": expected["note_sync_id"]}
        or snapshot["parent_token"] != expected["parent_lifecycle"]
        or not snapshot["requires_confirmation"]
    ):
        raise ValueError("Invalid saved note displayed base")
    target = snapshot["target"]
    closed(target, {"id", "title"})
    if target["id"] != expected["note_sync_id"] or not isinstance(target["title"], str):
        raise ValueError("Invalid explicitly selected note target")
    validate_rich_note(snapshot["retained"])
    if (
        snapshot["retained"]["paper_id"] != expected["paper_sync_id"]
        or snapshot["retained"]["created_at"] != expected["current"]["created_at"]
        or _source(snapshot["retained"], snapshot["source_hash"]) != snapshot["source_hash"]
    ):
        raise ValueError("Saved note changed protected identity or source")
    if version == 2:
        from paper_daily.note_source_mapping import validate_choice

        validate_choice(snapshot)
    from paper_daily.enrollment_history import _snapshot

    _snapshot("papers", snapshot["parent_row"], expected["paper_id"])
    original = snapshot["original"]
    if original is not None:
        if not isinstance(original, dict):
            raise ValueError("Invalid historical note original")
        if set(original) == NOTE_FIELDS:
            _row_payload(original, expected["paper_sync_id"])
        elif set(original) == RICH_NOTE_FIELDS:
            validate_rich_note(original)
        elif set(original) != {"paper_id", "body"}:
            raise ValueError("Invalid historical note original")
    return expected


def source_hashes(snapshot, owner):
    expected = validate_snapshot(snapshot, owner)
    result = {snapshot["source_hash"]} if snapshot["source_hash"] is not None else set()
    choice = expected.get("source_choice")
    if choice and choice["recorded_source"] is not None:
        result.add(choice["recorded_source"])
    for row in (snapshot["current"], snapshot["original"]):
        if row is not None:
            anchor = row.get("anchor")
            anchor = _value(anchor) if isinstance(anchor, str) else anchor
            if isinstance(anchor, dict) and anchor.get("document_hash") is not None:
                result.add(anchor["document_hash"])
    if expected["document"]:
        result.add(expected["document"]["sha256"])
    return result


def _record(review, conn, data):
    record = review._record(conn, data["origin"], data["id"])
    if digest(record) != data["record_hash"]:
        raise ValueError("Historical note draft changed; your edits are retained")
    return record


def targets(review, preview, *, after="", limit=30):
    data = review._verify_preview(preview)
    if type(limit) is not int or not 1 <= limit <= 100 or not isinstance(after, str):
        raise ValueError("Invalid note target page")
    if review.recovery or review.binding is None:
        raise ValueError("Create a managed editable copy before resuming note drafts")
    with closing(review._connect()) as conn:
        _historical(_record(review, conn, data))
        rows = conn.execute(
            "SELECT m.sync_id AS id,substr(p.title,1,100)||' · '||substr(n.body,1,120) AS title "
            "FROM notes n JOIN research_note_identity m ON m.local_id=n.id "
            "AND m.paper_id=n.paper_id AND m.created_at=n.created_at "
            "JOIN papers p ON p.id=n.paper_id WHERE m.sync_id>? ORDER BY m.sync_id LIMIT ?",
            (after, limit + 1),
        ).fetchall()
        review._check(conn)
    items = [dict(row) for row in rows[:limit]]
    return {"items": items, "next": items[-1]["id"] if len(rows) > limit else None}


def select(review, preview, target_id):
    from paper_daily.archived_draft_resume import _sealed
    from paper_daily.document_reader import DocumentReader

    data = review._verify_preview(preview)
    uuid(target_id)
    if review.recovery or review.binding is None:
        raise ValueError("Create a managed editable copy before resuming note drafts")
    with closing(review._connect()) as conn:
        conn.execute("BEGIN")
        payload, source, historical = _historical(_record(review, conn, data))
        note = conn.execute(
            "SELECT n.* FROM notes n JOIN research_note_identity m ON m.local_id=n.id "
            "AND m.paper_id=n.paper_id AND m.created_at=n.created_at WHERE m.sync_id=?",
            (target_id,),
        ).fetchone()
        if note is None:
            raise ValueError("Selected note target no longer exists")
        note = dict(note)
        parent = conn.execute("SELECT * FROM papers WHERE id=?", (note["paper_id"],)).fetchone()
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (note["paper_id"],)
        ).fetchone()
        observation = sync_capture.observe_note(conn, note["id"])
        token = parent_lifecycle(conn, "paper", note["paper_id"])
        if parent is None or portable is None or observation is None or not token:
            raise ValueError("Selected note lacks its managed parent observation")
        payload.update(paper_id=portable[0], created_at=note["created_at"])
        validate_rich_note(payload)
        document = DocumentReader.from_workspace(review.path).resolve(note["paper_id"])
        expected = dict(
            version=1,
            db_path=str(review.path),
            database_identity=review.identity,
            binding=review.binding,
            note_id=note["id"],
            note_sync_id=target_id,
            paper_id=note["paper_id"],
            paper_sync_id=portable[0],
            current=note,
            observation=observation,
            parent_lifecycle=token,
            document=None,
        )
        if document.available:
            expected["document"] = dict(
                sha256=document.sha256,
                path=str(document.path.resolve()),
                target=document.target,
                managed=document.managed,
            )
        old_choice = (historical.get("expected") or {}).get("source_choice")
        if old_choice is not None:
            # Preserve the original attribution across repeated adoption. The
            # old receipt remains archival evidence, never a new receiver grant.
            expected.update(version=2, source_choice={
                **old_choice, "action": "retained", "receipt": None})
        data.update(
            origin=ORIGIN,
            original=historical["current"],
            current=note,
            retained=payload,
            source_hash=source,
            expected=expected,
            scope={"kind": "note", "id": target_id},
            target={"id": target_id, "title": parent["title"] + " · " + note["body"][:120]},
            parent_token=token,
            parent_row=dict(parent),
            requires_confirmation=True,
            editable=True,
            apply=False,
            resume_state="verification_required",
            reason="Current note selected; verify its original before applying",
        )
        validate_snapshot(
            data, {"path": str(review.path), "identity": review.identity, "binding": review.binding}
        )
        review._check(conn)
        return _sealed(review, data)


def check_base(review, conn, data):
    expected = validate_snapshot(
        data, {"path": str(review.path), "identity": review.identity, "binding": review.binding}
    )
    review._check(conn)
    payload, source, _old = _historical(_record(review, conn, data))
    payload.update(paper_id=expected["paper_sync_id"], created_at=expected["current"]["created_at"])
    choice = expected.get("source_choice")
    if choice is not None:
        from paper_daily.note_source_mapping import apply_choice

        old_choice = (_old.get("expected") or {}).get("source_choice")
        recorded = old_choice["recorded_source"] if old_choice else source
        if choice["recorded_source"] != recorded:
            raise ValueError("Reviewed source choice changed historical attribution")
        if choice["action"] == "retained" and (
            old_choice is None or choice != {**old_choice, "action": "retained", "receipt": None}
        ):
            raise ValueError("Historical association differs from the immutable draft")
        payload, source = apply_choice(payload, choice), choice["source"]
    if payload != data["retained"] or source != data["source_hash"]:
        raise ValueError("Resumed note differs from its immutable historical provenance")
    row = conn.execute("SELECT * FROM notes WHERE id=?", (expected["note_id"],)).fetchone()
    mapping = conn.execute(
        "SELECT local_id,paper_id,created_at FROM research_note_identity WHERE sync_id=?",
        (expected["note_sync_id"],),
    ).fetchone()
    paper_mapping = conn.execute(
        "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (expected["paper_id"],)
    ).fetchone()
    parent = conn.execute("SELECT * FROM papers WHERE id=?", (expected["paper_id"],)).fetchone()
    if (
        row is None
        or dict(row) != expected["current"]
        or mapping is None
        or tuple(mapping)
        != (expected["note_id"], expected["paper_id"], expected["current"]["created_at"])
        or paper_mapping is None
        or paper_mapping[0] != expected["paper_sync_id"]
        or parent is None
        or dict(parent) != data["parent_row"]
        or parent_lifecycle(conn, "paper", expected["paper_id"]) != data["parent_token"]
        or sync_capture.observe_note(conn, expected["note_id"]) != expected["observation"]
    ):
        raise ValueError("Displayed note or parent changed; your draft is retained")
    return expected


def source_intent(expected):
    return sources.SourceIntent("paper", expected["paper_id"], expected["document"])


def verify(review, preview):
    from paper_daily import archived_note_resume as adapter

    data = review._verify_preview(preview)
    if data["source_hash"] is None and (
        data["retained"]["anchor"] is not None or data["retained"]["page"] is not None
    ):
        raise ValueError("Note position needs its recorded PDF version; your draft is retained")
    return sources.verify(review, preview, adapter)


def chosen_source(review, data):
    from paper_daily.note_source_mapping import chosen_source as resolve

    return resolve(review, data)


def validate_source(data, prepared):
    import pymupdf

    from paper_daily.note_positions import verify as verify_position

    note = data["retained"]
    location = prepared.proof.files[data["source_hash"]][0]
    with pymupdf.open(location) as document:
        if note["page"] is not None and not 1 <= note["page"] <= document.page_count:
            raise ValueError("Recorded note page is outside its original PDF")
        if note["anchor"] is not None:
            verify_position(document, note["anchor"])
    if not prepared.proof.matches(prepared.proof_operation):
        raise ValueError("Note original changed while validating its page")


def apply_in(review, conn, data, body, complete):
    expected = check_base(review, conn, data)
    sources.publish_in(review, conn, data)
    payload = dict(data["retained"])
    if body is not None:
        payload["body"] = body
    validate_rich_note(payload)
    with sync_capture.expecting(conn, [expected["observation"]]):
        changed = conn.execute(
            "UPDATE notes SET body=?,kind=?,page=?,anchor=? "
            "WHERE id=? AND paper_id=? AND created_at=?",
            (
                payload["body"],
                payload["kind"],
                payload["page"],
                encode(payload["anchor"]) if payload["anchor"] is not None else None,
                expected["note_id"],
                expected["paper_id"],
                expected["current"]["created_at"],
            ),
        )
        if changed.rowcount != 1:
            raise ValueError("Displayed note disappeared; your draft is retained")
        complete()
