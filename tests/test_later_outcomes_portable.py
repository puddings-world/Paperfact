"""Actual enrolled publication and read-only projection, never live lookup."""

import hashlib
import json
from contextlib import closing

import pytest
from test_research_generation import workspace as workspace

from paper_daily import config, followups, llm
from paper_daily import later_outcomes as outcomes
from paper_daily import research_generation as generation
from paper_daily.sync_projection import read_manifest


@pytest.mark.parametrize("available", [False, True], ids=["missing-original", "available-original"])
def test_actual_bound_or_local_empty_query_publication_and_idempotent_retry(
    workspace, monkeypatch, available
):
    path, client, document = workspace
    monkeypatch.setattr(config, "PDF_DIR", document.path.parent)
    if not available:
        document.path.unlink()
    monkeypatch.setattr(followups, "work_id", lambda _: "W1")
    monkeypatch.setattr(followups, "_citing_openalex", lambda _: [])
    monkeypatch.setattr(followups, "_citing_s2", lambda _: [])
    monkeypatch.setattr(llm, "complete", lambda *a, **kw: pytest.fail("Empty query called model"))
    assert followups.fetch("paper", database=path) == 0
    with closing(generation._connect(path)) as conn:
        row = dict(conn.execute("SELECT * FROM paper_later_outcomes").fetchone())
        requests = [dict(r) for r in conn.execute("SELECT * FROM research_generation_requests")]
        request = next(
            r for r in requests if json.loads(r["context_json"])["table"] == outcomes.TABLE
        )
        assert request["status"] == "accepted"
        assert outcomes.settled(conn, "paper")
    assert row["document_hash"] == (document.sha256 if available else None)
    assert generation.retry_publication(path, request["request_id"]).status == "accepted"
    if client:
        ops = [op for op in client.journal.pending() if op["entity_type"] == "research_content"]
        assert len(ops) == 1 and ops[0]["payload"]["feature"] == "later_outcome"
        sources = [
            op
            for op in client.journal.pending()
            if op["entity_type"] == "research_file"
            and op["payload"]["feature"] == "original_source"
        ]
        assert len(sources) == int(available)
        if available:
            assert sources[0]["payload"]["source_document_hash"] == document.sha256
            assert sources[0]["parents"] == ops[0]["parents"]
        before = path.read_bytes()
        manifest = read_manifest(path, workspace_id="workspace")
        assert path.read_bytes() == before
        assert manifest["required_capabilities"] == ["later_outcome"]
        value = manifest["papers"][0]["later_outcome"]
        assert value["body"] == json.loads(row["body_json"])
        assert value["document_hash"] == row["document_hash"]


@pytest.mark.parametrize("change", ["partial", "different-device"])
def test_readonly_source_binding_is_observed_not_instrumentation_or_new_authority(
    workspace, monkeypatch, change
):
    import sqlite3

    from paper_daily.later_outcome_packages import _owned, read

    path, client, document = workspace
    monkeypatch.setattr(config, "PDF_DIR", document.path.parent)
    monkeypatch.setattr(followups, "work_id", lambda _: "W1")
    monkeypatch.setattr(followups, "_citing_openalex", lambda _: [])
    monkeypatch.setattr(followups, "_citing_s2", lambda _: [])
    assert followups.fetch("paper", database=path) == 0
    before = path.read_bytes()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        row = read(conn, "paper")
        assert hashlib.sha256(_owned(conn, path, row).read_bytes()).hexdigest() == document.sha256
    assert path.read_bytes() == before
    if client is None:
        return  # Positive actual unbound receipt, with a real native/source comparison above.
    with closing(sqlite3.connect(path)) as conn, conn:
        if change == "partial":
            conn.execute("DELETE FROM research_sync_binding")
        else:
            conn.execute("UPDATE research_capture_binding SET device='other-device'")
    with (
        closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn,
        pytest.raises(ValueError),
    ):
        _owned(conn, path, row)
