"""Preserve private review decisions without restoring old write authority.

Receipt validation discovers declared source hashes only. It never follows a
stored target or applies a decision to the new workspace.
"""

from __future__ import annotations

from paper_daily.sync_files import closed


def source_hashes(row):
    """Validate closed receipt JSON and retain original strings losslessly."""
    from paper_daily.enrollment_history import _value
    from paper_daily.research_review import RECEIPT_FIELDS, validate_receipt

    closed(row, RECEIPT_FIELDS)
    # Check scalar types before runtime membership tests, so malformed nested
    # values are ordinary migration refusals rather than unhashable exceptions.
    if any(not isinstance(row[key], str) for key in RECEIPT_FIELDS):
        raise ValueError("Invalid archived review decision scalar")
    result = _value(row["result"])
    provenance = _value(row["provenance"])
    closed(result, {"decision", "operation_id"})
    closed(provenance, {"source_document_hash", "target_kind", "target_id", "parent_token"})
    if provenance["target_kind"] is not None and not isinstance(provenance["target_kind"], str):
        raise ValueError("Invalid archived review decision target kind")
    validate_receipt(row)
    source = provenance["source_document_hash"]
    return {source} if source is not None else set()
