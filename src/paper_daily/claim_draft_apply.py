"""Exact-source human revisions with process-only proof and atomic shared writes."""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime

from paper_daily import (
    annotation_content,
    claim_content,
    claim_draft_resume,
    claim_draft_revision,
    resumed_draft_originals,
    review_draft_sources,
    sync_capture,
    sync_content,
)
from paper_daily.archived_draft_resume import _sealed
from paper_daily.research_review import _setup, digest, encode
from paper_daily.sync_journal import _identifier

_SEAL = object()


@dataclass(frozen=True)
class _Revision:
    review: object
    prepared: object
    body: str
    draft_digest: str
    written_at: str
    restoring: bool
    seal: object


def _cancel(cancelled):
    if cancelled():
        raise ValueError("Claim revision verification cancelled")


def _clear(review, identity):
    review._claim_revisions.pop(identity, None)
    review._resume_sources.pop(identity, None)
    review._resume_documents.pop(identity, None)
    review._resume_cache_owners.pop(identity, None)


def verify(review, preview, body, *, restore_deleted=False, cancelled=lambda: False):
    """Worker-only: validate original ownership and every edited quote, without AI."""
    from paper_daily import research_evidence

    data = review._verify_preview(preview)
    if data["origin"] != claim_draft_resume.ORIGIN or type(restore_deleted) is not bool:
        raise ValueError("Select a typed claim draft and explicit restoration choice")
    identity = review_draft_sources.key(data)
    with review._file_apply_lock:
        _clear(review, identity)
        try:
            _cancel(cancelled)
            claim_draft_revision.parse(data["retained"]["body_json"], body)
            observed = data["expected"]["observation"]
            deleted = observed["incarnation"] is not None and not observed["active"]
            if deleted != restore_deleted:
                raise ValueError(
                    "Explicit claim restoration is required"
                    if deleted
                    else "Claims are not deleted; review the current target"
                )
            ready = review_draft_sources.verify(review, preview, claim_draft_resume)
            original = resumed_draft_originals.prepare(
                review, ready, data["source_hash"], cancelled=cancelled
            )
            snapshot = research_evidence.capture_original(original, cancelled=cancelled)
            result = claim_draft_revision.revise_for_receiver(
                snapshot, data["retained"]["body_json"], body, cancelled=cancelled
            )
            resumed_draft_originals.revalidate(original, cancelled=cancelled)
            _cancel(cancelled)
            with closing(review._connect()) as conn:
                conn.execute("BEGIN")
                claim_draft_resume.check_base(review, conn, ready.data)
                review._check(conn)
            prepared = review._resume_sources.get(identity)
            if prepared is None:
                raise ValueError("Verify the claim original again")
            value = _Revision(
                review,
                prepared,
                encode(result["body"]),
                result["draft_digest"],
                datetime.now(UTC).isoformat(),
                restore_deleted,
                _SEAL,
            )
            review._claim_revisions[identity] = value
            while len(review._claim_revisions) > 64:
                review._claim_revisions.pop(next(iter(review._claim_revisions)))
            shown = ready.data
            shown.update(
                claim_draft_digest=value.draft_digest,
                claim_restore=restore_deleted,
                reason="Original quotes checked; compare and confirm the selected claim target",
            )
            return _sealed(review, shown)
        except BaseException:
            _clear(review, identity)
            raise


def _revision(review, data, body=None):
    identity = review_draft_sources.key(data)
    value = review._claim_revisions.get(identity)
    if (
        data["origin"] != claim_draft_resume.ORIGIN
        or not data["apply"]
        or data.get("resume_state") != "ready"
        or not isinstance(value, _Revision)
        or value.seal is not _SEAL
        or value.review is not review
        or value.prepared is not review._resume_sources.get(identity)
        or identity not in review._resume_documents
        or data.get("claim_draft_digest") != value.draft_digest
        or data.get("claim_restore") is not value.restoring
    ):
        raise ValueError("Claim draft needs verification in this session before applying")
    if body is not None:
        parsed = claim_draft_revision.parse(data["retained"]["body_json"], body)
        if claim_content.hashed(parsed) != value.draft_digest:
            raise ValueError("The claim draft changed; verify its edited quotes again")
    return value


def report(review, preview):
    """Worker read: return scientific fields only, never a serialized capability."""
    data = review._verify_preview(preview)
    with review._file_apply_lock:
        value = _revision(review, data)
        identity = review_draft_sources.key(data)
        resumed_draft_originals._metadata(
            review,
            preview,
            value.prepared,
            review._resume_documents[identity],
            review._resume_cache_owners.get(identity),
        )
        return annotation_content.decode("claims", value.body)


def apply(review, preview, body, *, request_id, confirm_target=False, _operation_receipt=None):
    """One explicit typed transaction: source, claim operation/outbox and receipt."""
    data = review._verify_preview(preview)
    if _operation_receipt is not None and not callable(_operation_receipt):
        raise ValueError("Expected a trusted local claim receipt callback")
    if data["origin"] != claim_draft_resume.ORIGIN:
        raise ValueError("Select a typed claim draft")
    if confirm_target is not True:
        raise ValueError("Confirm the displayed claim target before applying")
    _identifier(request_id)
    if not isinstance(body, str):
        raise ValueError("A structured claim draft is required")
    stable = {key: value for key, value in data.items() if key not in {"session", "resume_state"}}
    fingerprint = digest(dict(preview=stable, body=body, confirm_target=True))
    with review._file_apply_lock, closing(review._connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        review._check(conn)
        _setup(conn)
        old = conn.execute(
            "SELECT fingerprint,result FROM research_review_receipts WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if old is not None:
            if old[0] != fingerprint:
                raise ValueError("Claim review retry changed its decision or draft")
            result = json.loads(old[1])
            if _operation_receipt is not None:
                _operation_receipt(conn, result)
                review._check(conn)
                conn.commit()
            return result
        value = _revision(review, data, body)
        expected = claim_draft_resume.check_base(review, conn, data)
        scientific = annotation_content.decode("claims", value.body)
        row = dict(
            paper_id=expected["paper_id"],
            body_json=value.body,
            source_hash=claim_content.source_digest(scientific["inputs"], data["source_hash"]),
            document_hash=data["source_hash"],
            written_at=value.written_at,
        )
        annotation_content.validate_row("claims", row)
        if scientific["report"]["source"] != dict(
            paper_id=expected["paper_sync_id"], document_hash=data["source_hash"]
        ):
            raise ValueError("Verified claim content belongs to another receiver or original")
        review_draft_sources.publish_in(review, conn, data)
        payload = sync_content.content_payload(conn, "paper_claim_sets", row)
        client = conn._capture_client
        with sync_capture.suppress_capture(conn):
            if expected["version"] == 2:
                outcome = client.resolve_conflict_in(
                    conn,
                    int(data["id"].split(":", 1)[1]),
                    expected=expected["conflict"],
                    payload=payload,
                    operation_id=request_id,
                    restore=value.restoring,
                )
            else:
                operation = client.new_graph_operation_in(
                    conn,
                    "research_content",
                    expected["observation"]["entity_id"],
                    payload,
                    operation_id=request_id,
                    restore=value.restoring,
                )
                outcome = client.journal.apply_in(conn, operation, client.writer)
            if not outcome["applied"]:
                raise ValueError("Reviewed claim revision did not apply atomically")
        conn._capture_graph_cache = None
        result = dict(decision="applied", operation_id=request_id)
        review._receipt(conn, request_id, fingerprint, data, result)
        if _operation_receipt is not None:
            _operation_receipt(conn, result)
        review._check(conn)
        conn.commit()
        return result
