"""Typed private highlight revisions; target observations never publish research."""

from __future__ import annotations

import re
from contextlib import closing
from pathlib import PurePosixPath, PureWindowsPath

from paper_daily import (
    annotation_content,
    highlight_draft_revision,
    highlight_publication,
    sync_capture,
    sync_content,
)
from paper_daily import research_generation as generation
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.research_review import MAX_DETAIL, digest, encode
from paper_daily.sync_files import closed, uuid
from paper_daily.sync_files import digest as source_digest
from paper_daily.sync_journal import _identifier

ORIGIN = "highlight_resume"
TABLE = "paper_highlight_analysis"
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
    "highlights",
    "manual",
    "conflict",
}


def _value(raw):
    from paper_daily.enrollment_history import _value as parse

    return parse(raw)


def _reference(identity):
    if isinstance(identity, str) and re.fullmatch(r"[0-9a-f]{64}", identity):
        return "archived_draft", identity
    if not isinstance(identity, str) or len(identity) > 256:
        raise ValueError("Invalid highlight draft source")
    origin, separator, value = identity.partition(":")
    if origin not in {"generation", "sidecar", "remote"} or not separator or not value:
        raise ValueError("Unsupported highlight draft source")
    if origin == "remote" and (not value.isdecimal() or int(value) < 1):
        raise ValueError("Invalid highlight conflict identity")
    return origin, value


def record(review, conn, identity):
    origin, source = _reference(identity)
    return review._record(conn, origin, source)


def _row(value):
    if value is not None:
        annotation_content.validate_row("highlight_analysis", value)
    return value


def _payload(value):
    if value is None:
        return None
    closed(value, {"scope", "feature", "key", "source_document_hash", "data"})
    closed(value["scope"], {"kind", "id"})
    if (
        value["feature"] != "highlight_analysis"
        or value["key"] != "main"
        or value["scope"]["kind"] != "paper"
    ):
        raise ValueError("A lone mark is not a retained highlight analysis")
    sync_content.validate_payload(value)
    row = dict(value["data"], paper_id=value["scope"]["id"])
    if isinstance(row.get("body_json"), dict):
        row["body_json"] = encode(row["body_json"])
    _row(row)
    if value["source_document_hash"] != row["document_hash"]:
        raise ValueError("Highlight conflict declares contradictory originals")
    return row


def _scientific(conn, origin, identity, retained):
    """Read typed retained content, never historical filesystem paths."""
    raw = None
    if origin in {"generation", "sidecar"}:
        generation.validate_request_record(retained)
        context = generation.GenerationContext(retained["context_json"])
        if context.table != TABLE:
            raise ValueError("Select a retained highlight analysis")
        baseline, original = _value(retained["row_json"]), context.target
    elif origin == "remote":
        client = getattr(conn, "_capture_client", None)
        if client is None:
            raise ValueError("Highlight conflict needs its enrolled workspace")
        state = client.conflict_observation_in(conn, int(identity))
        operation = state["event"]["operation"]
        if operation["entity_type"] != "research_content" or operation["action"] != "put":
            raise ValueError("Select a retained highlight analysis")
        baseline = _payload(operation["payload"])
        head = state["head"]
        prior = _value(head["operation"])["payload"] if head and head["operation"] else None
        original = _payload(prior) if prior is not None else None
    elif origin == "archived_draft":
        from paper_daily import enrollment_history as history

        value, _sources = history.validate(retained)
        if retained["protocol"] != "research_review_drafts" or value["origin"] != ORIGIN:
            raise ValueError("Select a typed historical highlight draft")
        snapshot = _value(value["preview_json"])
        baseline, original, raw = snapshot["retained"], snapshot["original"], value["body"]
    else:
        raise ValueError("Unsupported retained highlight origin")
    _row(baseline)
    _row(original)
    if baseline is None:
        raise ValueError("Retained highlight analysis is missing")
    if raw is not None:
        highlight_draft_revision.parse(baseline, raw)
    return baseline, original, raw


def _source(review, conn, data):
    origin, identity = (
        _reference(data["id"]) if data["origin"] == ORIGIN else (data["origin"], data["id"])
    )
    retained = review._record(conn, origin, identity)
    if digest(retained) != data["record_hash"]:
        raise ValueError("Retained highlight result changed; your edits are retained")
    return origin, identity, retained


def _read(conn, table, identity):
    if table not in {"papers", TABLE}:
        raise ValueError("Unsupported highlight target table")
    column = "id" if table == "papers" else "paper_id"
    columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
    if not columns or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in columns):
        raise ValueError("Unsupported highlight target schema")
    size = "+".join(f'coalesce(length(CAST("{name}" AS BLOB)),0)' for name in columns)
    found = conn.execute(f'SELECT {size} FROM "{table}" WHERE "{column}"=?', (identity,)).fetchone()
    if found is None:
        return None
    if found[0] > (MAX_DETAIL if table == "papers" else annotation_content.MAX_BYTES + 4096):
        raise ValueError("Highlight target exceeds its supported size")
    return dict(conn.execute(f'SELECT * FROM "{table}" WHERE "{column}"=?', (identity,)).fetchone())


def _highlight_state(conn, paper):
    # Bound stored bytes before allocating rows, not only the eventual JSON.
    size = "+".join(
        f'coalesce(length(CAST("{name}" AS BLOB)),0)' for name in highlight_publication.MARK_FIELDS
    )
    count, used = conn.execute(
        f"SELECT count(*),coalesce(sum({size}),0) FROM pdf_ai_highlights WHERE paper_id=?",
        (paper,),
    ).fetchone()
    if count > generation.MAX_ROWS or used > MAX_DETAIL // 2:
        raise ValueError("Highlight observation exceeds its supported bound")
    return highlight_publication.inputs(conn, paper)


def _manual(conn, paper):
    # CAS only: private observations do not replay these rows or grant source access.
    fields = ["id", "paper_id", "document_hash", "anchor", "quote", "created_at"]
    size = "+".join(f'coalesce(length(CAST("{name}" AS BLOB)),0)' for name in fields)
    count, used = conn.execute(
        f"SELECT count(*),coalesce(sum({size}),0) FROM pdf_highlights WHERE paper_id=?", (paper,)
    ).fetchone()
    if count > generation.MAX_ROWS or used > MAX_DETAIL // 2:
        raise ValueError("Manual highlight observation exceeds its supported bound")
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM pdf_highlights WHERE paper_id=? ORDER BY id", (paper,)
        )
    ]
    return dict(count=count, digest=digest(rows))


def _observation(value, owner, paper, feature, key="main"):
    closed(
        value,
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
        value["workspace_id"] != owner["binding"]["workspace_id"]
        or value["kind"] != "research_content"
        or value["entity_id"] != sync_content.content_id(dict(kind="paper", id=paper), feature, key)
        or type(value["revision"]) is not int
        or value["revision"] < 0
        or type(value["active"]) is not bool
    ):
        raise ValueError("Invalid highlight operation observation")
    for field in ("predecessor", "incarnation"):
        if value[field] is not None:
            _identifier(value[field])
    if value["incarnation"] is None and value["active"]:
        raise ValueError("Active highlight observation lacks an incarnation")
    if not isinstance(value["parents"], list) or len(value["parents"]) != 1:
        raise ValueError("Invalid highlight parent observation")
    parent = value["parents"][0]
    closed(parent, {"kind", "id", "incarnation", "active"})
    if parent["kind"] != "paper" or parent["id"] != paper or parent["active"] is not True:
        raise ValueError("Highlight target parent is unavailable")
    _identifier(parent["incarnation"])


def _highlights(value, owner, expected):
    closed(value, {"marks", "known", "tokens"})
    if (
        type(value["known"]) is not bool
        or not isinstance(value["marks"], list)
        or len(value["marks"]) > generation.MAX_ROWS
        or not isinstance(value["tokens"], dict)
        or len(value["tokens"]) > generation.MAX_ROWS
    ):
        raise ValueError("Invalid highlight group observation")
    keys = set()
    for mark in value["marks"]:
        highlight_publication._validate_mark(mark, expected["paper_id"])
        key = mark["document_hash"] + ":" + mark["source_key"]
        if key in keys:
            raise ValueError("Duplicate observed highlight")
        keys.add(key)
    if not keys <= value["tokens"].keys():
        raise ValueError("Highlight observation omits a current mark")
    for key, token in value["tokens"].items():
        if not isinstance(key, str) or len(key) != 129 or key[64] != ":":
            raise ValueError("Invalid observed highlight identity")
        source_digest(key[:64])
        source_digest(key[65:])
        _observation(token, owner, expected["paper_sync_id"], "ai_highlight", key)
        if token["parents"] != expected["observation"]["parents"]:
            raise ValueError("Highlight marks differ from their observed parent")


def _document(value):
    if value is None:
        return
    closed(value, {"sha256", "path", "target", "managed"})
    source_digest(value["sha256"])
    if (
        not isinstance(value["path"], str)
        or not (
            PurePosixPath(value["path"]).is_absolute()
            or PureWindowsPath(value["path"]).is_absolute()
        )
        or type(value["managed"]) is not bool
        or (value["target"] is not None and not isinstance(value["target"], dict))
    ):
        raise ValueError("Invalid selected highlight-document observation")


def _conflict(snapshot, owner):
    from paper_daily.enrollment_review_drafts import _remote
    from paper_daily.sync_client import validate_event

    value = snapshot["expected"]["conflict"]
    origin, identity = _reference(snapshot["id"])
    if origin != "remote":
        if value is not None:
            raise ValueError("Unexpected highlight conflict observation")
        return
    closed(value, {"event", "resolved_by", "head", "state", "parents", "outstanding"})
    validate_event(value["event"], owner["binding"]["workspace_id"])
    operation = value["event"]["operation"]
    if (
        str(value["event"]["sequence"]) != identity
        or operation["entity_type"] != "research_content"
        or operation["action"] != "put"
        or operation["entity_id"] != snapshot["expected"]["observation"]["entity_id"]
        or value["resolved_by"] is not None
        or value["outstanding"] is not False
        or _payload(operation["payload"]) != snapshot["retained"]
    ):
        raise ValueError("Highlight draft differs from its unresolved conflict")
    head = value["head"]
    current = _value(head["operation"])["payload"] if head and head["operation"] else None
    if _payload(current) != snapshot["original"]:
        raise ValueError("Highlight draft differs from its canonical comparison")
    _remote(
        dict(
            expected=value,
            scope=dict(kind="research_content", id=operation["entity_id"]),
            current=current,
            retained=operation["payload"],
            original=None,
            target=None,
            parent_token=None,
            parent_row=None,
        ),
        owner,
    )


def validate_snapshot(snapshot, owner, body=None):
    """Closed private-history codec; owner paths are never restore destinations."""
    expected = snapshot["expected"]
    closed(expected, EXPECTED)
    if type(expected["version"]) is not int or expected["version"] != 1:
        raise ValueError("Unsupported highlight draft observation")
    _reference(snapshot["id"])
    if owner["binding"] is None or any(
        expected[field] != owner[key]
        for field, key in (
            ("db_path", "path"),
            ("database_identity", "identity"),
            ("binding", "binding"),
        )
    ):
        raise ValueError("Highlight draft belongs to another owner")
    paper = expected["paper_id"]
    if not isinstance(paper, str) or not 1 <= len(paper) <= 4096:
        raise ValueError("Invalid highlight receiver")
    uuid(expected["paper_sync_id"])
    _observation(expected["observation"], owner, expected["paper_sync_id"], "highlight_analysis")
    if not isinstance(expected["parent_lifecycle"], str) or not re.fullmatch(
        r"[0-9a-f]{32}", expected["parent_lifecycle"]
    ):
        raise ValueError("Invalid highlight parent lifetime")
    _document(expected["document"])
    for row in (
        expected["current"],
        snapshot["current"],
        snapshot["original"],
        snapshot["retained"],
    ):
        _row(row)
    if expected["current"] is not None and expected["current"]["paper_id"] != paper:
        raise ValueError("Current highlight analysis belongs to another paper")
    _highlights(expected["highlights"], owner, expected)
    manual = expected["manual"]
    closed(manual, {"count", "digest"})
    if type(manual["count"]) is not int or not 0 <= manual["count"] <= generation.MAX_ROWS:
        raise ValueError("Invalid manual mark observation")
    source_digest(manual["digest"])
    if manual["count"] == 0 and manual["digest"] != digest([]):
        raise ValueError("Contradictory empty manual mark observation")
    closed(snapshot["target"], {"id", "title"})
    from paper_daily.enrollment_history import _snapshot

    _snapshot("papers", snapshot["parent_row"], paper)
    if (
        snapshot["parent_row"] is None
        or snapshot["origin"] != ORIGIN
        or snapshot["current"] != expected["current"]
        or snapshot["scope"] != dict(table=TABLE, owner_id=paper)
        or snapshot["parent_token"] != expected["parent_lifecycle"]
        or snapshot["requires_confirmation"] is not True
        or snapshot["apply"] is not False
        or snapshot["editable"] is not True
        or snapshot["target"] != dict(id=paper, title=snapshot["parent_row"]["title"])
        or snapshot["retained"] is None
        or snapshot["source_hash"] != snapshot["retained"]["document_hash"]
    ):
        raise ValueError("Highlight draft differs from its displayed target/source")
    source_digest(snapshot["source_hash"])
    _conflict(snapshot, owner)
    if body is not None:
        highlight_draft_revision.parse(snapshot["retained"], body)
    encode(snapshot)
    return expected


def source_hashes(snapshot, owner):
    expected = validate_snapshot(snapshot, owner)
    result = {snapshot["source_hash"]}
    result.update(mark["document_hash"] for mark in expected["highlights"]["marks"])
    for row in (snapshot["current"], snapshot["original"]):
        if row is not None and row["document_hash"] is not None:
            result.add(row["document_hash"])
    if expected["document"] is not None:
        result.add(expected["document"]["sha256"])
    return result


def targets(review, preview, *, after="", limit=30):
    data = review._verify_preview(preview)
    if review.recovery or review.binding is None:
        raise ValueError("Create a managed editable copy before continuing highlight drafts")
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or not isinstance(after, str)
        or len(after) > 4096
    ):
        raise ValueError("Invalid highlight target page")
    with closing(review._connect()) as conn:
        origin, identity, retained = _source(review, conn, data)
        baseline, _original, _raw = _scientific(conn, origin, identity, retained)
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
    from paper_daily.archived_draft_resume import _sealed
    from paper_daily.document_reader import DocumentReader

    data = review._verify_preview(preview)
    if review.recovery or review.binding is None:
        raise ValueError("Create a managed editable copy before continuing highlight drafts")
    if not isinstance(target_id, str) or not 1 <= len(target_id) <= 4096:
        raise ValueError("Select a current highlight target")
    with closing(review._connect()) as conn:
        conn.execute("BEGIN")
        origin, identity, retained = _source(review, conn, data)
        baseline, original, saved = _scientific(conn, origin, identity, retained)
        parent = _read(conn, "papers", target_id)
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (target_id,)
        ).fetchone()
        if parent is None or portable is None:
            raise ValueError("Selected highlight target is missing or not enrolled")
        observation = sync_capture.observe_target(
            conn, "paper", target_id, "highlight_analysis", "main"
        )
        epoch = parent_lifecycle(conn, "paper", target_id)
        current = _read(conn, TABLE, target_id)
        document = DocumentReader.from_workspace(review.path).resolve(target_id)
        observed_document = (
            dict(
                sha256=document.sha256,
                path=str(document.path.resolve()),
                target=document.target,
                managed=document.managed,
            )
            if document.available
            else None
        )
        raw = body if body is not None else saved
        if raw is None:
            raw = encode(highlight_draft_revision.editable(baseline))
        highlight_draft_revision.parse(baseline, raw)
        conflict = None
        if origin == "remote":
            from paper_daily.claim_conflict_review import capture

            conflict = capture(conn._capture_client, conn, int(identity), observation["entity_id"])
        data.update(
            origin=ORIGIN,
            id=identity if origin == "archived_draft" else origin + ":" + identity,
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
                highlights=_highlight_state(conn, target_id),
                manual=_manual(conn, target_id),
                conflict=conflict,
            ),
            scope=dict(table=TABLE, owner_id=target_id),
            target=dict(id=target_id, title=parent["title"]),
            parent_token=epoch,
            parent_row=parent,
            requires_confirmation=True,
            editable=True,
            apply=False,
            resume_state="verification_required",
            reason=(
                "Highlight target selected; private edits require complete "
                "original/group verification before application"
            ),
        )
        validate_snapshot(
            data, dict(path=str(review.path), identity=review.identity, binding=review.binding), raw
        )
        review._check(conn)
        return _sealed(review, data), raw


def check_base(review, conn, data):
    # Internal source verification has a sealed staging-only preview. Private
    # history retains apply=False; this metadata projection grants no publication.
    expected = validate_snapshot(
        dict(data, apply=False),
        dict(path=str(review.path), identity=review.identity, binding=review.binding),
    )
    review._check(conn)
    origin, identity, retained = _source(review, conn, data)
    baseline, original, _body = _scientific(conn, origin, identity, retained)
    if baseline != data["retained"] or original != data["original"]:
        raise ValueError("Retained highlight provenance changed; your edits are retained")
    paper = expected["paper_id"]
    portable = conn.execute(
        "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (paper,)
    ).fetchone()
    if (
        portable is None
        or portable[0] != expected["paper_sync_id"]
        or _read(conn, "papers", paper) != data["parent_row"]
        or parent_lifecycle(conn, "paper", paper) != expected["parent_lifecycle"]
        or _read(conn, TABLE, paper) != expected["current"]
        or sync_capture.observe_target(conn, "paper", paper, "highlight_analysis", "main")
        != expected["observation"]
        or _highlight_state(conn, paper) != expected["highlights"]
        or _manual(conn, paper) != expected["manual"]
    ):
        raise ValueError("Displayed highlight group changed; your edits are retained")
    if (
        origin == "remote"
        and conn._capture_client.conflict_observation_in(conn, int(identity))
        != expected["conflict"]
    ):
        raise ValueError("Displayed highlight conflict changed; your edits are retained")
    return expected


def save(review, preview, body, request_id, *, draft_id, revision=None):
    from paper_daily.research_review_drafts import DraftStore

    if review.closed:
        raise ValueError("Highlight review is closed; retain or export pending edits")
    data = review._verify_preview(preview)
    if data["origin"] != ORIGIN:
        raise ValueError("Select a typed highlight draft target")
    highlight_draft_revision.parse(data["retained"], body)
    return DraftStore(review).save(preview, body, request_id, draft_id=draft_id, revision=revision)


def source_intent(expected):
    from paper_daily.review_draft_sources import SourceIntent

    return SourceIntent("paper", expected["paper_id"], expected["document"])


def verify(review, preview):
    raise ValueError("Use verify_highlight_draft with its exact edited body")
