"""Closed archive-only QA review receipts; stored observations grant no authority."""

from __future__ import annotations

from paper_daily import enrollment_chat_history as history
from paper_daily import research_chat_review as review
from paper_daily.sync_content import content_id
from paper_daily.sync_documents import _validate_target
from paper_daily.sync_files import closed

PROTOCOL = "research_chat_review_receipts"
COLUMNS = "request_id fingerprint record_json target_json answer_json result_json"


def source_hashes(row):
    """Validate every nested declared input without opening any observed path."""
    from paper_daily.enrollment_history import _value

    # Parse opaque JSON strings strictly before the runtime validator. Preserve
    # the original strings in the archive, including whitespace and Unicode.
    closed(row, COLUMNS.split())
    record = _value(row["record_json"])
    snapshot = _value(row["target_json"])
    _value(row["answer_json"])
    _value(row["result_json"])
    review.validate_receipt(row)
    sources = history.validate_record("research_chat_requests", record)
    target = snapshot["target"]
    parent = target["parent"]
    paper = parent["row"]
    if type(paper["_rowid"]) is not int or paper["_rowid"] < 1:
        raise ValueError("Invalid archived reviewed-paper row identity")
    history._text(paper["id"], 4096)
    history._text(paper["title"], 2000)
    history._text(paper["venue"], 120, nullable=True)
    history._text(paper["abstract"], 128 * 1024, nullable=True)
    if paper["year"] is not None and (
        type(paper["year"]) is not int or not 0 <= paper["year"] <= 2200
    ):
        raise ValueError("Invalid archived reviewed-paper year")

    binding, portable = snapshot["binding"], parent["portable"]
    if (binding is None) != (portable is None):
        raise ValueError("Archived review parent differs from its workspace binding")
    history._observation(parent["observation"], binding=binding, kind="paper", identity=portable)
    expected_parent = None
    if binding is not None:
        observed = parent["observation"]
        expected_parent = dict(
            kind="paper",
            id=portable,
            incarnation=observed["incarnation"],
            active=observed["active"],
        )
    for name, key in (("user_observation", "user_key"), ("answer_observation", "answer_key")):
        identity = (
            content_id({"kind": "paper", "id": portable}, "chat", target[key]) if portable else None
        )
        history._observation(
            target[name],
            binding=binding,
            kind="research_content",
            identity=identity,
            parent=expected_parent,
        )
    for turn in target["history"] + ([target["question"]] if target["question"] else []):
        sources.update(history._turn(turn))
    desired = target["desired"]
    if desired is not None:
        document = _value(desired[0])
        _validate_target(document)
        if (
            binding is None
            or document["workspace_id"] != binding["workspace_id"]
            or document["paper_id"] != portable
        ):
            raise ValueError("Archived review document belongs to another workspace or paper")
        sources.add(document["sha256"])
    return sources
