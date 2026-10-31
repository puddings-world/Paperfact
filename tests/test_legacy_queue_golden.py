"""Shared Python/mobile queue graph/CAS vectors with no new wire fields."""

import json
from pathlib import Path

import pytest

from paper_daily.sync_graph import check_preconditions
from paper_daily.sync_journal import canonical_operation

VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "legacy-queue-context.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda case: case["name"])
def test_typed_queue_context_golden(case):
    operation, expected = case["operation"], case["expected"]
    if not expected["wire_valid"]:
        with pytest.raises(ValueError):
            canonical_operation(operation)
        return
    canonical_operation(operation)
    state = {(row["kind"], row["id"]): row["metadata"] for row in case["state"]}
    receipts = {row["operation"]["operation_id"]: row for row in case["receipts"]}

    def check():
        return check_preconditions(
            lambda kind, key: state.get((kind, key)), receipts.get, operation
        )

    if expected["graph_error"]:
        with pytest.raises(ValueError):
            check()
        return
    assert check() is expected["graph_result"]
    dependency = receipts.get(operation["depends_on"]) if operation["depends_on"] else None
    base = dependency["sequence"] if dependency else operation["base_revision"]
    data_ok = base == case["head"]["revision"] and (
        not operation["depends_on"]
        or dependency is not None
        and dependency["outcome"] == "accepted"
    )
    assert data_ok is expected["data_cas"]
    assert (check() and data_ok) is expected["accepted"]
