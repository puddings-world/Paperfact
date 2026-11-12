"""Exact-original highlight verification and staged reading, without publication."""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass

from paper_daily import highlight_draft_resume as resume
from paper_daily import (
    highlight_draft_revision,
    paper_highlights,
    research_evidence,
    resumed_draft_originals,
    review_draft_sources,
)
from paper_daily.archived_draft_resume import _sealed
from paper_daily.research_review import digest, encode

_SEAL = object()


@dataclass(frozen=True)
class _Verification:
    review: object
    source_preview: object
    prepared: object
    draft_digest: str
    report_json: str
    seal: object

    def __reduce__(self):
        raise TypeError("Highlight verification is process-only")


def _cancel(cancelled):
    if cancelled():
        raise ValueError("Highlight verification cancelled")


def _clear(review, key):
    review._highlight_verifications.pop(key, None)
    review._resume_sources.pop(key, None)
    review._resume_documents.pop(key, None)
    review._resume_cache_owners.pop(key, None)


def _source_text_hash(data, cancelled):
    """Match actual HighlightJob page provenance from bounded captured bytes."""
    import pymupdf

    pages, size = [], 0
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.page_count > 20000:
            raise ValueError("Highlight original exceeds its page bound")
        for index, page in enumerate(document):
            _cancel(cancelled)
            text = paper_highlights.normalize(page.get_text())
            size += len(text)
            if size > 240000:
                raise ValueError("Highlight original exceeds its text bound")
            pages.append(dict(page=index + 1, text=text))
    if not any(page["text"] for page in pages):
        raise ValueError("Highlight original has no readable text")
    return paper_highlights._hash(pages)


def verify(review, preview, body, *, cancelled=lambda: False):
    """Worker-only: verify A and the entire edited group, never grant generic Apply."""
    data = review._verify_preview(preview)
    if data["origin"] != resume.ORIGIN:
        raise ValueError("Select a typed highlight draft")
    key = review_draft_sources.key(data)
    with review._file_apply_lock:
        _clear(review, key)
        try:
            _cancel(cancelled)
            draft = highlight_draft_revision.parse(data["retained"], body)
            _cancel(cancelled)
            source_preview = review_draft_sources.verify(review, preview, resume)
            original = resumed_draft_originals.prepare(
                review, source_preview, data["source_hash"], cancelled=cancelled
            )
            if _source_text_hash(original.data, cancelled) != data["retained"]["source_hash"]:
                raise ValueError("Retained highlight source text differs from the exact original")
            snapshot = research_evidence.capture_original(original, cancelled=cancelled)
            result = highlight_draft_revision.revise_for_receiver(
                snapshot, data["retained"], body, cancelled=cancelled
            )
            resumed_draft_originals.revalidate(original, cancelled=cancelled)
            _cancel(cancelled)
            with closing(review._connect()) as conn:
                conn.execute("BEGIN")
                resume.check_base(review, conn, data)
                review._check(conn)
            prepared = review._resume_sources.get(key)
            if prepared is None or digest(draft) != result["draft_digest"]:
                raise ValueError("Verify this highlight draft again")
            # Keep only bounded content and metadata, not another full PDF copy.
            review._highlight_verifications[key] = _Verification(
                review, source_preview, prepared, result["draft_digest"], encode(result), _SEAL
            )
            while len(review._highlight_verifications) > 64:
                _clear(review, next(iter(review._highlight_verifications)))
            data.update(
                apply=False,
                resume_state="verified" if result["all_quotes_located"] else "needs_location",
                highlight_draft_digest=result["draft_digest"],
                reason=(
                    "Original and edited highlight locations checked; no research was published"
                    if result["all_quotes_located"]
                    else "Original checked; resolve missing or ambiguous passages before applying"
                ),
            )
            return _sealed(review, data)
        except BaseException:
            _clear(review, key)
            raise


def _verified(review, data):
    value = review._highlight_verifications.get(review_draft_sources.key(data))
    if (
        review.closed
        or data["origin"] != resume.ORIGIN
        or data.get("resume_state") not in {"verified", "needs_location"}
        or not isinstance(value, _Verification)
        or value.seal is not _SEAL
        or value.review is not review
        or data.get("highlight_draft_digest") != value.draft_digest
        or value.prepared is not review._resume_sources.get(review_draft_sources.key(data))
    ):
        raise ValueError("Highlight draft needs verification in this session")
    return value


def report(review, preview):
    """Worker read of scientific fields; no serialization of proof or Apply rights."""
    data = review._verify_preview(preview)
    with review._file_apply_lock:
        value = _verified(review, data)
        key = review_draft_sources.key(data)
        resumed_draft_originals._metadata(
            review,
            value.source_preview,
            value.prepared,
            review._resume_documents.get(key),
            review._resume_cache_owners.get(key),
        )
        return json.loads(value.report_json)


def original(review, preview, *, cancelled=lambda: False):
    """Read verified staged A; current B and publication remain independent."""
    data = review._verify_preview(preview)
    with review._file_apply_lock:
        value = _verified(review, data)
        return resumed_draft_originals.prepare(
            review, value.source_preview, data["source_hash"], cancelled=cancelled
        )
