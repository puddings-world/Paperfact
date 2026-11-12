"""Typed receiver observations and private structured claim drafts; no publication."""

from __future__ import annotations

import re
from contextlib import closing
from pathlib import PurePosixPath, PureWindowsPath

from paper_daily import annotation_content, claim_draft_revision, sync_capture, sync_content
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.research_review import MAX_DETAIL, digest, encode
from paper_daily.sync_files import closed, uuid
from paper_daily.sync_files import digest as source_digest
from paper_daily.sync_journal import _identifier

ORIGIN = "claim_resume"
EXPECTED = {
    "version",
    "db_path",
    "database_identity",
    "binding",
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


def _reference(identity):
    if isinstance(identity, str) and re.fullmatch(r"[0-9a-f]{64}", identity):
        return "archived_draft", identity
    if not isinstance(identity, str) or len(identity) > 256:
        raise ValueError("Invalid claim draft source identity")
    origin, separator, value = identity.partition(":")
    if origin not in {"generation", "sidecar", "remote"} or not separator or not value:
        raise ValueError("Unsupported claim draft source")
    if origin == "remote" and (not value.isdecimal() or int(value) < 1):
        raise ValueError("Invalid claim conflict identity")
    return origin, value


def record(review, conn, identity):
    origin, source = _reference(identity)
    return review._record(conn, origin, source)


def _row(value):
    if value is None:
        return None
    annotation_content.validate_row("claims", value)
    return value


def _payload(value):
    if value is None:
        return None
    closed(value, {"scope", "feature", "key", "source_document_hash", "data"})
    closed(value["scope"], {"kind", "id"})
    if value["feature"] != "claims" or value["key"] != "main" or value["scope"]["kind"] != "paper":
        raise ValueError("Select a typed claim-set result")
    row = dict(value["data"], paper_id=value["scope"]["id"])
    if isinstance(row.get("body_json"), dict):
        row["body_json"] = encode(row["body_json"])
    _row(row)
    if value["source_document_hash"] != row["document_hash"]:
        raise ValueError("Claim conflict declares contradictory originals")
    return row


def _scientific(conn, origin, identity, retained):
    """Read validated content only; archived paths/observations grant no authority."""
    raw = None
    if origin in {"generation", "sidecar"}:
        from paper_daily import research_generation as generation

        generation.validate_request_record(retained)
        context = generation.GenerationContext(retained["context_json"])
        if context.table != "paper_claim_sets":
            raise ValueError("Select a retained claim-set result")
        baseline, original = _value(retained["row_json"]), context.target
    elif origin == "remote":
        client = getattr(conn, "_capture_client", None)
        if client is None:
            raise ValueError("Claim conflict needs its enrolled workspace")
        state = client.conflict_observation_in(conn, int(identity))
        operation = state["event"]["operation"]
        if operation["entity_type"] != "research_content" or operation["action"] != "put":
            raise ValueError("Select a retained claim-set result")
        baseline = _payload(operation["payload"])
        head = state["head"]
        prior = _value(head["operation"])["payload"] if head and head["operation"] else None
        original = _payload(prior) if prior and prior.get("feature") == "claims" else None
    elif origin == "archived_draft":
        from paper_daily import enrollment_history as history

        value, _sources = history.validate(retained)
        if retained["protocol"] != "research_review_drafts":
            raise ValueError("Select a historical claim draft")
        snapshot = _value(value["preview_json"])
        if value["origin"] in {"generation", "sidecar", ORIGIN}:
            if snapshot["scope"] is None or snapshot["scope"].get("table") != "paper_claim_sets":
                raise ValueError("Select a historical claim draft")
            baseline, original = snapshot["retained"], snapshot["original"]
        elif value["origin"] == "remote":
            baseline, original = _payload(snapshot["retained"]), _payload(snapshot["original"])
        else:
            raise ValueError("Unsupported historical claim draft")
        raw = value["body"]
    else:
        raise ValueError("Unsupported retained claim origin")
    _row(baseline)
    _row(original)
    if baseline is None:
        raise ValueError("Select a retained claim-set result")
    if raw is not None:
        claim_draft_revision.parse(baseline["body_json"], raw)
    return baseline, original, raw


def _source(review, conn, data):
    origin, identity = (
        _reference(data["id"]) if data["origin"] == ORIGIN else (data["origin"], data["id"])
    )
    retained = review._record(conn, origin, identity)
    if digest(retained) != data["record_hash"]:
        raise ValueError("Retained claim result changed; your draft is retained")
    return origin, identity, retained


def _read(conn, table, column, identity):
    if (table, column) not in {("papers", "id"), ("paper_claim_sets", "paper_id")}:
        raise ValueError("Unsupported claim target table")
    columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
    if not columns or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in columns):
        raise ValueError("Unsupported claim target schema")
    size = "+".join(f'coalesce(length(CAST("{name}" AS BLOB)),0)' for name in columns)
    found = conn.execute(f'SELECT {size} FROM "{table}" WHERE "{column}"=?', (identity,)).fetchone()
    limit = MAX_DETAIL if table == "papers" else annotation_content.MAX_BYTES + 4096
    if found is None:
        return None
    if found[0] > limit:
        raise ValueError("Claim target exceeds its supported size")
    return dict(conn.execute(f'SELECT * FROM "{table}" WHERE "{column}"=?', (identity,)).fetchone())


def _document(value):
    if value is None:
        return
    closed(value, {"sha256", "path", "target", "managed"})
    source_digest(value["sha256"])
    path = value["path"]
    if (
        not isinstance(path, str)
        or not (PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute())
        or type(value["managed"]) is not bool
        or (value["target"] is not None and not isinstance(value["target"], dict))
    ):
        raise ValueError("Invalid selected claim-document observation")


def validate_snapshot(snapshot, owner, body=None):
    """Pure private-history codec; historical owner fields never authorize I/O."""
    expected = snapshot["expected"]
    if (
        not isinstance(expected, dict)
        or type(expected.get("version")) is not int
        or expected["version"] not in {1, 2}
    ):
        raise ValueError("Unsupported claim draft observation")
    closed(expected, EXPECTED | ({"conflict"} if expected["version"] == 2 else set()))
    _reference(snapshot["id"])
    if (
        any(
            expected[field] != owner[key]
            for field, key in (
                ("db_path", "path"),
                ("database_identity", "identity"),
                ("binding", "binding"),
            )
        )
        or owner["binding"] is None
    ):
        raise ValueError("Claim draft observation belongs to another owner")
    paper = expected["paper_id"]
    if not isinstance(paper, str) or not 1 <= len(paper) <= 4096:
        raise ValueError("Invalid claim target identity")
    uuid(expected["paper_sync_id"])
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
    scope = {"kind": "paper", "id": expected["paper_sync_id"]}
    if (
        token["workspace_id"] != owner["binding"]["workspace_id"]
        or token["kind"] != "research_content"
        or token["entity_id"] != sync_content.content_id(scope, "claims", "main")
        or type(token["revision"]) is not int
        or token["revision"] < 0
        or type(token["active"]) is not bool
    ):
        raise ValueError("Invalid claim-set operation observation")
    for key in ("predecessor", "incarnation"):
        if token[key] is not None:
            _identifier(token[key])
    if token["incarnation"] is None and token["active"]:
        raise ValueError("Active claims lack a recorded incarnation")
    if not isinstance(token["parents"], list) or len(token["parents"]) != 1:
        raise ValueError("Invalid claim parent observation")
    parent = token["parents"][0]
    closed(parent, {"kind", "id", "incarnation", "active"})
    if (
        parent["kind"] != "paper"
        or parent["id"] != expected["paper_sync_id"]
        or parent["active"] is not True
    ):
        raise ValueError("Claim target parent is unavailable")
    _identifier(parent["incarnation"])
    if not isinstance(expected["parent_lifecycle"], str) or not re.fullmatch(
        r"[0-9a-f]{32}", expected["parent_lifecycle"]
    ):
        raise ValueError("Invalid claim target lifetime")
    _document(expected["document"])
    _row(expected["current"])
    _row(snapshot["retained"])
    _row(snapshot["original"])
    if expected["current"] is not None and expected["current"]["paper_id"] != paper:
        raise ValueError("Current claim snapshot belongs to another paper")
    target = snapshot["target"]
    closed(target, {"id", "title"})
    if not isinstance(snapshot["parent_row"], dict):
        raise ValueError("Invalid claim target parent snapshot")
    if (
        snapshot["origin"] != ORIGIN
        or snapshot["current"] != expected["current"]
        or snapshot["scope"] != {"table": "paper_claim_sets", "owner_id": paper}
        or snapshot["parent_token"] != expected["parent_lifecycle"]
        or snapshot["requires_confirmation"] is not True
        or target["id"] != paper
        or target["title"] != snapshot["parent_row"].get("title")
    ):
        raise ValueError("Claim draft differs from its displayed receiver target")
    if (
        snapshot["retained"] is None
        or snapshot["source_hash"] != snapshot["retained"]["document_hash"]
    ):
        raise ValueError("Claim draft changed its original source")
    from paper_daily.enrollment_history import _snapshot

    _snapshot("papers", snapshot["parent_row"], paper)
    if expected["version"] == 2:
        from paper_daily import claim_conflict_review

        claim_conflict_review.validate(snapshot, owner)
    if body is not None:
        claim_draft_revision.parse(snapshot["retained"]["body_json"], body)
    return expected


def source_hashes(snapshot, owner):
    expected = validate_snapshot(snapshot, owner)
    result = {snapshot["source_hash"]}
    for row in (snapshot["current"], snapshot["original"]):
        if row is not None:
            result.add(row["document_hash"])
    if expected["document"]:
        result.add(expected["document"]["sha256"])
    return result


def targets(review, preview, *, after="", limit=30):
    data = review._verify_preview(preview)
    if review.recovery or review.binding is None:
        raise ValueError("Create a managed editable copy before continuing claim drafts")
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or not isinstance(after, str)
        or len(after) > 4096
    ):
        raise ValueError("Invalid claim target page")
    with closing(review._connect()) as conn:
        origin, identity, retained = _source(review, conn, data)
        baseline, _original, _body = _scientific(conn, origin, identity, retained)
        remote_paper = baseline["paper_id"] if origin == "remote" else None
        rows = conn.execute(
            "SELECT p.id,substr(p.title,1,200) AS title FROM papers p "
            "JOIN research_paper_identity m ON m.local_id=p.id "
            "WHERE p.id>? AND (? IS NULL OR m.sync_id=?) ORDER BY p.id LIMIT ?",
            (after, remote_paper, remote_paper, limit + 1),
        ).fetchall()
        review._check(conn)
    items = [dict(row) for row in rows[:limit]]
    return dict(items=items, next=items[-1]["id"] if len(rows) > limit else None)


def select(review, preview, target_id, *, body=None):
    """Explicit receiver selection returns a preview and its structured edit text."""
    from paper_daily.archived_draft_resume import _sealed
    from paper_daily.document_reader import DocumentReader

    data = review._verify_preview(preview)
    if review.recovery or review.binding is None:
        raise ValueError("Create a managed editable copy before continuing claim drafts")
    if not isinstance(target_id, str) or not 1 <= len(target_id) <= 4096:
        raise ValueError("Select a current claim target")
    with closing(review._connect()) as conn:
        conn.execute("BEGIN")
        origin, identity, retained = _source(review, conn, data)
        baseline, original, saved = _scientific(conn, origin, identity, retained)
        parent = _read(conn, "papers", "id", target_id)
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (target_id,)
        ).fetchone()
        observation = (
            sync_capture.observe_target(conn, "paper", target_id, "claims", "main")
            if parent is not None
            else None
        )
        epoch = parent_lifecycle(conn, "paper", target_id) if parent is not None else None
        if parent is None or portable is None or observation is None or not epoch:
            raise ValueError("Selected claim target no longer exists or is not enrolled")
        current = _read(conn, "paper_claim_sets", "paper_id", target_id)
        document = DocumentReader.from_workspace(review.path).resolve(target_id)
        observed_document = None
        if document.available:
            observed_document = dict(
                sha256=document.sha256,
                path=str(document.path.resolve()),
                target=document.target,
                managed=document.managed,
            )
        raw = body if body is not None else saved
        if raw is None:
            raw = encode(claim_draft_revision.editable(baseline["body_json"]))
        claim_draft_revision.parse(baseline["body_json"], raw)
        reference = identity if origin == "archived_draft" else origin + ":" + identity
        data.update(
            origin=ORIGIN,
            id=reference,
            original=original,
            current=current,
            retained=baseline,
            source_hash=baseline["document_hash"],
            expected=dict(
                version=1,
                db_path=str(review.path),
                database_identity=review.identity,
                binding=review.binding,
                paper_id=target_id,
                paper_sync_id=portable[0],
                current=current,
                observation=observation,
                parent_lifecycle=epoch,
                document=observed_document,
            ),
            scope={"table": "paper_claim_sets", "owner_id": target_id},
            target={"id": target_id, "title": parent["title"]},
            parent_token=epoch,
            parent_row=parent,
            requires_confirmation=True,
            editable=True,
            apply=False,
            resume_state="verification_required",
            reason="Current claim target selected; verify its original before applying",
        )
        if origin == "remote":
            from paper_daily import claim_conflict_review

            data["expected"].update(
                version=2,
                conflict=claim_conflict_review.capture(
                    conn._capture_client, conn, int(identity), observation["entity_id"]
                ),
            )
        validate_snapshot(
            data, dict(path=str(review.path), identity=review.identity, binding=review.binding), raw
        )
        review._check(conn)
        return _sealed(review, data), raw


def check_base(review, conn, data):
    expected = validate_snapshot(
        data, dict(path=str(review.path), identity=review.identity, binding=review.binding)
    )
    review._check(conn)
    origin, identity, retained = _source(review, conn, data)
    baseline, original, _body = _scientific(conn, origin, identity, retained)
    if baseline != data["retained"] or original != data["original"]:
        raise ValueError("Retained claim provenance changed; your edits are retained")
    paper = expected["paper_id"]
    portable = conn.execute(
        "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (paper,)
    ).fetchone()
    if (
        portable is None
        or portable[0] != expected["paper_sync_id"]
        or _read(conn, "papers", "id", paper) != data["parent_row"]
        or parent_lifecycle(conn, "paper", paper) != expected["parent_lifecycle"]
        or _read(conn, "paper_claim_sets", "paper_id", paper) != expected["current"]
        or sync_capture.observe_target(conn, "paper", paper, "claims", "main")
        != expected["observation"]
    ):
        raise ValueError("Displayed claim target changed; your edits are retained")
    from paper_daily import claim_conflict_review

    claim_conflict_review.check(conn._capture_client, conn, data)
    return expected


def save(review, preview, body, request_id, *, draft_id, revision=None):
    if review.closed:
        raise ValueError("Claim review is closed; retain or export pending edits")
    from paper_daily.research_review_drafts import DraftStore

    data = review._verify_preview(preview)
    if data["origin"] != ORIGIN:
        raise ValueError("Select a typed claim draft target")
    claim_draft_revision.parse(data["retained"]["body_json"], body)
    return DraftStore(review).save(preview, body, request_id, draft_id=draft_id, revision=revision)


def source_intent(expected):
    from paper_daily.review_draft_sources import SourceIntent

    return SourceIntent("paper", expected["paper_id"], expected["document"])


def verify(review, preview):
    raise ValueError("Use verify_claim_draft with its exact edited structured body")
