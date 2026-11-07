"""Pure metadata capability seam; actual native-widget integration is separate."""

import hashlib
import sqlite3
from contextlib import closing

from paper_daily.desktop.later_outcome_status import fence, prepared


def test_delivery_fence_only_rejects_without_sql_hash_or_print(tmp_path, monkeypatch):
    database = tmp_path / "research.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("CREATE TABLE example(value)")
    observed = fence(database)
    outcome = {"state": "queried_no_judged_inputs"}
    delivery = prepared(outcome, database, observed, observed)
    assert delivery is not None

    def forbidden(*args, **kwargs):
        raise AssertionError("Delivery metadata may not run SQL, hashing or print")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(hashlib, "sha256", forbidden)
    monkeypatch.setattr("builtins.print", forbidden)
    assert delivery.unchanged()
    with database.open("ab") as stream:
        stream.write(b"native metadata change")
    assert not delivery.unchanged()
    assert prepared(outcome, database, observed, fence(database)) is None
    assert prepared({"state": "unknown"}, database, observed, observed) is None


def test_prepared_provenance_is_immutable_readable_metadata_without_io(tmp_path, monkeypatch):
    import dataclasses

    import pytest

    database = tmp_path / "research.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("CREATE TABLE example(value)")
    observed = fence(database)
    outcome = {
        "state": "queried_no_judged_inputs",
        "query": {
            "queried_at": "2026-11-01T00:00:00Z",
            "providers": {"openalex": "queried_empty", "semantic_scholar": "unknown"},
        },
    }
    delivery = prepared(outcome, database, observed, observed)
    assert "Recorded query at 2026-11-01T00:00:00Z" in delivery.query_label
    assert (
        "queried, no results" in delivery.query_label and "not established" in delivery.query_label
    )
    assert "queried_empty" not in delivery.query_label
    original = delivery.query_label
    outcome["query"]["providers"]["openalex"] = "unknown"
    assert delivery.query_label == original
    with pytest.raises(dataclasses.FrozenInstanceError):
        delivery.query_label = "forged"

    def forbidden(*args, **kwargs):
        raise AssertionError("Metadata presentation attempted SQL/hash/print")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(hashlib, "sha256", forbidden)
    monkeypatch.setattr("builtins.print", forbidden)
    assert delivery.unchanged() and delivery.query_label == original
