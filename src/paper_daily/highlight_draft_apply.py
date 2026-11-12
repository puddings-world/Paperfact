"""Confirmed human highlight groups: one native transaction, no model or recapture."""

from __future__ import annotations

import json
from contextlib import closing
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from paper_daily import (
    annotation_content,
    highlight_draft_revision,
    highlight_publication,
    review_draft_sources,
    sync_capture,
    sync_content,
    sync_source_files,
)
from paper_daily import (
    highlight_draft_resume as resume,
)
from paper_daily import (
    highlight_draft_verification as verification,
)
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.research_review import _setup, digest, encode, validate_receipt
from paper_daily.research_review_drafts import DraftStore
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_files import file_id
from paper_daily.sync_journal import _identifier


def _deleted(observed):
    return observed["incarnation"] is not None and not observed["active"]


def _token(expected, key):
    # Unknown keys inherit the ORIGINAL captured parent, never a recaptured base.
    prior = expected["highlights"]["tokens"].get(key)
    if prior is not None:
        return prior
    return dict(
        workspace_id=expected["binding"]["workspace_id"],
        kind="research_content",
        entity_id=sync_content.content_id(
            dict(kind="paper", id=expected["paper_sync_id"]), "ai_highlight", key
        ),
        revision=0,
        predecessor=None,
        incarnation=None,
        active=False,
        parents=expected["observation"]["parents"],
    )


def _plan(data, report, written_at):
    expected = data["expected"]
    if (
        report["all_quotes_located"] is not True
        or report["analysis"] is None
        or not report["marks"]
        or len(report["marks"]) != len(report["analysis"]["items"])
        or report["source"]
        != dict(paper_id=expected["paper_sync_id"], document_hash=data["source_hash"])
    ):
        raise ValueError("Resolve every highlight quote before applying the complete group")
    row = dict(
        paper_id=expected["paper_id"],
        body_json=encode(report["analysis"]),
        source_hash=report["baseline_source_hash"],
        document_hash=data["source_hash"],
        written_at=written_at,
    )
    annotation_content.validate_row("highlight_analysis", row)
    old = {
        (mark["document_hash"], mark["source_key"]): mark
        for mark in expected["highlights"]["marks"]
    }
    marks, observations = [], []
    for found in report["marks"]:
        item = report["analysis"]["items"][found["item_index"]]
        key = row["document_hash"] + ":" + found["source_key"]
        mark = dict(
            paper_id=expected["paper_id"],
            document_hash=row["document_hash"],
            source_key=found["source_key"],
            analysis_hash=row["source_hash"],
            anchor=encode(found["anchor"]),
            quote=item["text"],
            reason=item["reason"],
            hidden=old.get((row["document_hash"], found["source_key"]), {}).get("hidden", 0),
        )
        highlight_publication._validate_mark(mark, expected["paper_id"])
        marks.append(mark)
        observations.append(_token(expected, key))
    return row, marks, observations


def _write(conn, client, table, row, observed, operation_id, *, conflict=None):
    if (
        sync_capture.observe_target(
            conn,
            "paper",
            row["paper_id"],
            "highlight_analysis" if table == resume.TABLE else "ai_highlight",
            "main" if table == resume.TABLE else row["document_hash"] + ":" + row["source_key"],
        )
        != observed
    ):
        raise ValueError("Displayed highlight operation changed; retain your draft")
    payload = sync_content.content_payload(conn, table, row)
    with sync_capture.suppress_capture(conn):
        if conflict is not None:
            result = client.resolve_conflict_in(
                conn,
                conflict["event"]["sequence"],
                expected=conflict,
                payload=payload,
                operation_id=operation_id,
                restore=_deleted(observed),
            )
        else:
            operation = client.new_graph_operation_in(
                conn,
                "research_content",
                observed["entity_id"],
                payload,
                operation_id=operation_id,
                restore=_deleted(observed),
            )
            result = client.journal.apply_in(conn, operation, client.writer)
        if not result["applied"]:
            raise ValueError("Reviewed highlight group did not apply atomically")
    conn._capture_graph_cache = None


def _next_token(observed, request):
    return dict(
        observed,
        predecessor=request,
        active=True,
        incarnation=observed["incarnation"] if observed["active"] else request,
    )


def _final_marks(expected, marks, tokens, operation_ids):
    # Compute the result from captured input + reviewed plan, not a convenient
    # post-write reread that could bless an intervening trusted callback's edit.
    merged = {
        (mark["document_hash"], mark["source_key"]): mark
        for mark in expected["highlights"]["marks"]
    }
    merged.update({(mark["document_hash"], mark["source_key"]): mark for mark in marks})
    observed = dict(expected["highlights"]["tokens"])
    for mark, token, identity in zip(marks, tokens, operation_ids, strict=True):
        observed[mark["document_hash"] + ":" + mark["source_key"]] = _next_token(token, identity)
    return dict(marks=[merged[key] for key in sorted(merged)], known=True, tokens=observed)


def _canonical_marks(state):
    return dict(
        state, marks=[dict(mark, anchor=json.loads(mark["anchor"])) for mark in state["marks"]]
    )


def _cancel(cancelled):
    if cancelled():
        raise ValueError("Highlight application cancelled; research is unchanged")


def _after(review, conn, data, value, row, final_marks, final_analysis, private):
    expected = data["expected"]
    review._check(conn)
    saved_private = conn.execute(
        "SELECT * FROM research_review_drafts WHERE draft_id=?", (private["draft_id"],)
    ).fetchone()
    if saved_private is None or dict(saved_private) != private:
        raise ValueError("Private highlight revision changed during grouped application")
    if (
        resume._read(conn, "papers", expected["paper_id"]) != data["parent_row"]
        or parent_lifecycle(conn, "paper", expected["paper_id"]) != expected["parent_lifecycle"]
        or resume._manual(conn, expected["paper_id"]) != expected["manual"]
    ):
        raise ValueError("Paper or manual highlights changed during grouped application")
    saved = resume._read(conn, resume.TABLE, expected["paper_id"])
    if saved is None or {**saved, "body_json": json.loads(saved["body_json"])} != {
        **row,
        "body_json": json.loads(row["body_json"]),
    }:
        raise ValueError("Analysis changed during grouped application")
    if (
        sync_capture.observe_target(conn, "paper", expected["paper_id"], "highlight_analysis")
        != final_analysis
    ):
        raise ValueError("Analysis operation changed during grouped application")
    if _canonical_marks(resume._highlight_state(conn, expected["paper_id"])) != _canonical_marks(
        final_marks
    ):
        raise ValueError("Highlight group changed during grouped application")
    review_draft_sources.check_document(review._resume_documents[review_draft_sources.key(data)])
    client = conn._capture_client
    payload = sync_source_files.check_prepared_source_in(conn, client, value.prepared)
    registered = conn.execute(
        "SELECT workspace,blob_root,version_root FROM research_file_paths WHERE id=1"
    ).fetchone()
    if registered is None or tuple(registered) != (
        value.prepared.workspace,
        str(value.prepared.store.root),
        str(value.prepared.root),
    ):
        raise ValueError("Original source storage changed during grouped application")
    identity = file_id(payload["paper_id"], sync_source_files.FEATURE, data["source_hash"])
    operation = desired_file(conn, identity)
    parents = [dict(kind="paper", id=expected["paper_sync_id"], incarnation=value.prepared.parent)]
    state = client._optimistic_graph(conn)[0].get(("research_file", identity))
    if (
        operation is None
        or operation["payload"] != payload
        or operation["parents"] != parents
        or not state
        or not state["active"]
        or state["parents"] != parents
    ):
        raise ValueError("Original source was removed or retired during grouped application")


def apply(
    review,
    preview,
    body,
    *,
    request_id,
    confirm_target=False,
    restore_deleted=False,
    draft_id=None,
    revision=None,
    cancelled=lambda: False,
    _operation_receipt=None,
):
    """Atomically save private words, source, analysis, marks, outbox and retry receipt."""
    data = review._verify_preview(preview)
    if data["origin"] != resume.ORIGIN:
        raise ValueError("Select a typed highlight draft")
    if confirm_target is not True:
        raise ValueError("Confirm the displayed highlight target before applying")
    if type(restore_deleted) is not bool:
        raise ValueError("Choose explicitly whether to restore deleted highlights")
    if _operation_receipt is not None and not callable(_operation_receipt):
        raise ValueError("Expected a trusted local highlight receipt callback")
    _identifier(request_id)
    if not isinstance(body, str):
        raise ValueError("An encoded highlight draft is required")
    parsed = highlight_draft_revision.parse(data["retained"], body)
    selected_draft = draft_id or str(uuid5(NAMESPACE_URL, "paperfact:highlight:" + request_id))
    stable = {key: value for key, value in data.items() if key not in {"session", "resume_state"}}
    fingerprint = digest(
        dict(
            preview=stable,
            body=body,
            confirm_target=True,
            restore_deleted=restore_deleted,
            draft_id=selected_draft,
            revision=revision,
        )
    )
    with review._file_apply_lock, closing(review._connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        review._check(conn)
        _setup(conn)
        prior = conn.execute(
            "SELECT fingerprint,result FROM research_review_receipts WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if prior is not None:
            if prior[0] != fingerprint:
                raise ValueError("Highlight review retry changed its decision or draft")
            result = json.loads(prior[1])
            if _operation_receipt is not None:
                _operation_receipt(conn, result)
                review._check(conn)
                conn.commit()
            return result
        _cancel(cancelled)
        value = verification._verified(review, data)
        if digest(parsed) != value.draft_digest:
            raise ValueError("The highlight draft changed; verify its edited quotes again")
        expected = resume.check_base(review, conn, data)
        report = json.loads(value.report_json)
        row, marks, tokens = _plan(data, report, datetime.now(UTC).isoformat())
        restoration = (
            _deleted(expected["observation"])
            or (expected["current"] is None and expected["highlights"]["known"])
            or any(_deleted(token) for token in tokens)
        )
        if restoration != restore_deleted:
            raise ValueError(
                "Explicit restoration of deleted highlights is required"
                if restoration
                else "This highlight group has no deleted content"
            )
        # Keep the exact body in the same commit, even when a caller has no prior variant.
        DraftStore(review).save_in(
            conn, preview, body, request_id, draft_id=selected_draft, revision=revision
        )
        private = dict(
            conn.execute(
                "SELECT * FROM research_review_drafts WHERE draft_id=?", (selected_draft,)
            ).fetchone()
        )
        review_draft_sources.publish_in(review, conn, data)
        client = conn._capture_client
        _write(
            conn,
            client,
            resume.TABLE,
            row,
            expected["observation"],
            request_id,
            conflict=expected["conflict"],
        )
        operation_ids = []
        for mark, token in zip(marks, tokens, strict=True):
            identity = str(
                uuid5(
                    NAMESPACE_URL,
                    request_id + "/mark/" + mark["document_hash"] + ":" + mark["source_key"],
                )
            )
            _write(conn, client, "pdf_ai_highlights", mark, token, identity)
            operation_ids.append(identity)
        final_marks = _final_marks(expected, marks, tokens, operation_ids)
        final_analysis = _next_token(expected["observation"], request_id)
        _after(review, conn, data, value, row, final_marks, final_analysis, private)
        result = dict(decision="applied", operation_id=request_id)
        review._receipt(conn, request_id, fingerprint, data, result)
        receipt = dict(
            conn.execute(
                "SELECT * FROM research_review_receipts WHERE request_id=?", (request_id,)
            ).fetchone()
        )
        validate_receipt(receipt)
        if (
            receipt["fingerprint"] != fingerprint
            or receipt["origin"] != resume.ORIGIN
            or receipt["origin_id"] != data["id"]
            or json.loads(receipt["result"]) != result
        ):
            raise ValueError("Highlight decision receipt differs from its group")

        if _operation_receipt is not None:
            _operation_receipt(conn, result)
        _after(review, conn, data, value, row, final_marks, final_analysis, private)
        current_receipt = conn.execute(
            "SELECT * FROM research_review_receipts WHERE request_id=?", (request_id,)
        ).fetchone()
        if current_receipt is None or dict(current_receipt) != receipt:
            raise ValueError("Highlight decision receipt changed during grouped application")
        _cancel(cancelled)
        conn.commit()
        return result
