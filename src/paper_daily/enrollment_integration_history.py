"""Closed import-control history; never install previews or old retry authority."""

from __future__ import annotations

import re
from datetime import datetime

from paper_daily.sync_files import closed, digest, read_json

FORMATS = {
    "integration_operations": "id fingerprint result created_at",
    "integration_previews": "id payload expires_at",
    "integration_changes": "id list_id",
}
# Normalized previews include defaults beyond the original 2 MB request budget.
MAX_JSON = 3 * 1024**2
ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")


def _id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("Unsupported archived import identifier")


def _integer(value, minimum=0, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Unsupported archived import integer")


def _json(value):
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_JSON:
        raise ValueError("Archived import JSON exceeds its bound")
    return read_json(value.encode("utf-8"))


def validate_record(protocol, record):
    if not isinstance(protocol, str) or protocol not in FORMATS:
        raise ValueError("Unsupported archived import history")
    closed(record, FORMATS[protocol].split())
    if protocol == "integration_changes":
        _integer(record["id"], 1)
        if not isinstance(record["list_id"], str) or not 1 <= len(record["list_id"]) <= 128:
            raise ValueError("Unsupported archived import change owner")
        return set()  # The old UI notification is an observation, not a new change.
    _id(record["id"])
    if protocol == "integration_previews":
        from paper_daily.local_import_schema import PaperInput

        _integer(record["expires_at"], 1)
        payload = _json(record["payload"])
        closed(payload, {"preview_id", "name", "target_list_id", "expires_at", "papers"})
        if payload["preview_id"] != record["id"] or payload["expires_at"] != record["expires_at"]:
            raise ValueError("Archived preview differs from its stored identity")
        name = payload["name"]
        if not isinstance(name, str) or not 1 <= len(name) <= 200 or name != name.strip():
            raise ValueError("Unsupported archived preview name")
        if payload["target_list_id"] is not None:
            _id(payload["target_list_id"])
        papers = payload["papers"]
        if not isinstance(papers, list) or not 1 <= len(papers) <= 500:
            raise ValueError("Unsupported archived preview paper count")
        for paper in papers:
            try:
                normalized = PaperInput.model_validate(paper).model_dump()
            except ValueError:
                raise ValueError("Unsupported archived preview paper") from None
            if normalized != paper:
                raise ValueError("Archived preview paper requires explicit migration")
        return set()  # URLs and paper identifiers never become file capabilities.
    if protocol != "integration_operations":
        raise ValueError("Unsupported archived import history")
    digest(record["fingerprint"])
    stamp = record["created_at"]
    if not isinstance(stamp, str) or len(stamp) > 64:
        raise ValueError("Unsupported archived import time")
    try:
        parsed = datetime.fromisoformat(stamp)
        if parsed.utcoffset() is None:
            raise ValueError
    except ValueError:
        raise ValueError("Archived import time requires a timezone") from None
    result = _json(record["result"])
    closed(result, {"operation_id", "list_id", "added", "selected", "paper_ids", "warnings"})
    if result["operation_id"] != record["id"]:
        raise ValueError("Archived import receipt differs from its stored identity")
    _id(result["list_id"])
    _integer(result["selected"], 1, 500)
    _integer(result["added"], 0, result["selected"])
    if not isinstance(result["paper_ids"], list) or len(result["paper_ids"]) != result["selected"]:
        raise ValueError("Archived import receipt has incomplete paper identities")
    for identity in result["paper_ids"]:
        _id(identity)
    warnings = result["warnings"]
    if (not isinstance(warnings, list) or len(warnings) > result["selected"]
            or any(not isinstance(item, str) or not re.fullmatch(
                r"Candidate (?:0|[1-9][0-9]{0,2}): similar title kept separate", item,
            ) for item in warnings)):
        raise ValueError("Unsupported archived import warning")
    return set()  # Preserve receipt bytes privately, never use them for idempotency.
