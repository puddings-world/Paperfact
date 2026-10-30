"""Completed bounded generation survives delivery bugs without fabricating success."""

import json
from contextlib import closing

import pytest
from test_research_generation import context, output, rows
from test_research_generation import workspace as _workspace

from paper_daily import research_generation as generation

workspace = _workspace


def fail(*args, **kwargs):
    raise RuntimeError("private diagnostic must not enter retained research")


def test_unexpected_delivery_error_retains_exact_completed_output(workspace, monkeypatch):
    database, _, _ = workspace
    observed = context(database, "target")
    value = output("Completed result")
    monkeypatch.setattr(generation, "publish_generation", fail)
    result = generation.publish_generated(observed, row=value)
    assert result.status == "candidate"
    assert generation.publish_generated(observed, row=value) == result
    records = generation.list_recovery_requests(database)
    assert len(records) == 1
    assert json.loads(records[0]["row_json"]) == value
    assert "private diagnostic" not in json.dumps(records)
    restored = generation.GenerationContext(records[0]["context_json"])
    assert generation.retry_publication(restored) == result
    assert rows(database, "SELECT * FROM close_readings") == []


def test_lost_success_delivery_returns_exact_receipt_without_duplicate(workspace, monkeypatch):
    database, _, _ = workspace
    observed = context(database, "target")
    original = generation.publish_generation

    def lost(*args, **kwargs):
        original(*args, **kwargs)
        fail()

    monkeypatch.setattr(generation, "publish_generation", lost)
    result = generation.publish_generated(observed, row=output("Committed result"))
    assert result.status == "accepted"
    assert generation.publish_generated(observed, row=output("Committed result")) == result
    assert len(rows(database, "SELECT * FROM close_readings")) == 1
    assert len(rows(database, "SELECT * FROM research_generation_requests")) == 1
    assert generation.list_recovery_requests(database) == []


def test_reused_delivery_identity_cannot_mask_different_output(workspace):
    database, _, _ = workspace
    observed = context(database, "target")
    assert generation.publish_generated(observed, row=output("Original")).status == "accepted"
    with pytest.raises(ValueError, match="identity was reused"):
        generation.publish_generated(observed, row=output("Different"))
    assert rows(database, "SELECT body FROM close_readings") == [{"body": "Original"}]
    assert generation.list_recovery_requests(database) == []


def test_invalid_output_never_enters_delivery_or_retention(workspace, monkeypatch):
    database, _, _ = workspace
    observed = context(database, "target")
    monkeypatch.setattr(
        generation, "publish_generation", lambda *a, **k: pytest.fail("Invalid delivery")
    )
    with pytest.raises(ValueError):
        generation.publish_generated(observed, row={**output(), "body": ["invalid"]})
    assert generation.list_recovery_requests(database) == []


def test_broken_receipt_probe_still_retains_original_result(workspace, monkeypatch):
    database, _, _ = workspace
    observed = context(database, "target")
    monkeypatch.setattr(generation, "publish_generation", fail)
    monkeypatch.setattr(generation, "_connect", fail)
    assert generation.publish_generated(observed, row=output()).status == "candidate"
    assert len(generation.list_recovery_requests(database)) == 1


def test_retention_failure_is_not_reported_as_saved(workspace, monkeypatch):
    database, _, _ = workspace
    observed = context(database, "target")
    monkeypatch.setattr(generation, "publish_generation", fail)

    def disk_full(*args, **kwargs):
        raise OSError("fixture full disk")

    monkeypatch.setattr(generation, "_retain_outside_database", disk_full)
    with pytest.raises(OSError, match="full disk"):
        generation.publish_generated(observed, row=output())
    assert rows(database, "SELECT * FROM close_readings") == []


def test_malformed_receipt_does_not_replace_the_original_output(workspace, monkeypatch):
    database, _, _ = workspace
    observed = context(database, "target")
    with closing(generation._connect(database)) as conn:
        generation._setup(conn)
        with generation.sync_capture.suppress_capture(conn):
            conn.execute(
                "INSERT INTO research_generation_requests VALUES(?,?,?,?,?,?)",
                (observed.request_id, "{}", "{}", "candidate", "invalid", "invalid"),
            )
        conn.commit()
    monkeypatch.setattr(generation, "publish_generation", fail)
    assert generation.publish_generated(observed, row=output()).status == "candidate"
    records = generation.list_recovery_requests(database)
    assert len(records) == 1 and json.loads(records[0]["row_json"]) == output()


def test_direct_retention_rejects_invalid_output_before_opening_storage(workspace, monkeypatch):
    database, _, _ = workspace
    observed = context(database, "target")
    monkeypatch.setattr(generation, "_connect", lambda *a: pytest.fail("Invalid storage probe"))
    monkeypatch.setattr(
        generation, "_retain_outside_database", lambda *a: pytest.fail("Invalid retention")
    )
    with pytest.raises(ValueError):
        generation.retain_failed_generated(observed, {**output(), "body": ["invalid"]})
