"""The independently checked mobile vectors retain exact Python verdicts."""

import json
from pathlib import Path

import pytest

from paper_daily.sync_journal import canonical_operation

FIXTURE = json.loads((Path(__file__).parent / "fixtures/reading-position-wire.json").read_text())


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda row: row["name"])
def test_closed_wire_golden(case):
    operation = json.loads(case["wire"])
    assert operation == case["operation"]
    if case["valid"]:
        canonical_operation(operation)
    else:
        with pytest.raises((ValueError, TypeError)):
            canonical_operation(operation)
