"""Actual retained Lineage completions feed the native observed builder once."""

import json
from contextlib import closing
from uuid import uuid4

import pytest
from test_lineage_jobs import routes, work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected

from paper_daily import (
    lineage_candidates,
    lineage_observation,
    lineage_operations,
    lineage_peer_sources,
    llm,
    research_lineage,
)
from paper_daily.ai_types import Completion
from paper_daily.lineage_jobs import LineageJob
from paper_daily.sync_journal import canonical_operation


def completion(selected, monkeypatch, *, changed_route=False):
    active, calls = [True], []

    def complete(*_a, **_k):
        calls.append(True)
        active[0] = not changed_route
        return Completion(
            json.dumps(
                dict(format=research_lineage.PROPOSALS, focal=selected[1].focal, statements=[])
            ),
            model="fixture-returned-model",
        )

    monkeypatch.setattr(llm, "complete_result", complete)
    job = work(
        LineageJob.prepare,
        selected[1],
        connections=routes(),
        publication_observation=selected[2],
        route_current=lambda: active[0],
    )
    work(job.run)
    return job, calls


def build_candidate(client, staged, candidate):
    with client.journal.transaction() as conn:
        originals = lineage_peer_sources.publish_in(conn, client, staged)
        before = list(conn.iterdump())
        frame = lineage_operations.from_candidate_in(conn, client, staged, originals, candidate)
        assert list(conn.iterdump()) == before
        return frame, originals


def test_actual_completion_keeps_request_and_models_and_build_retry_spends_no_more_calls(
    selected, monkeypatch
):
    client = selected[0][1]
    job, calls = completion(selected, monkeypatch)
    candidate = job._state.candidate
    before = client.journal.pending()
    frame, sources = work(build_candidate, client, selected[3], candidate)
    assert frame["operation_id"] == job.request_id == selected[2].data["request_id"]
    assert frame["payload"]["data"]["body_json"]["generation"] == dict(
        task="lineage",
        backend="openai",
        requested_model="lineage-selected",
        returned_model="fixture-returned-model",
    )
    assert frame["source_dependencies"] and len(sources) == 3
    assert work(build_candidate, client, selected[3], candidate)[0] == frame
    assert calls == [True]
    assert len(client.journal.pending()) == len(before) + 3
    assert all(op["entity_type"] != "research_content" for op in client.journal.pending())
    assert len(work(lineage_candidates.saved, client.journal.path, selected[2].data["focal"])) == 1
    assert json.loads(canonical_operation(frame)) == frame


def test_retained_route_changed_candidate_refuses_and_rolls_back_all_child_source_writes(
    selected, monkeypatch
):
    client = selected[0][1]
    job, calls = completion(selected, monkeypatch, changed_route=True)
    assert job._state.candidate.record["reason"] == "route_changed"
    before = client.journal.pending()
    with pytest.raises(ValueError, match="original current publication lease"):
        work(build_candidate, client, selected[3], job._state.candidate)
    assert client.journal.pending() == before and calls == [True]
    with closing(client.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM paper_lineage_sets").fetchone()[0] == 0
    assert len(work(lineage_candidates.saved, client.journal.path, selected[2].data["focal"])) == 1


def test_candidate_cannot_be_retargeted_to_another_sealed_observation(selected, monkeypatch):
    client, files = selected[0][1], selected[0][3]
    job, _calls = completion(selected, monkeypatch)
    other = work(lineage_observation.observe, selected[1], str(uuid4()), str(uuid4()))
    staged = work(
        lineage_peer_sources.prepare,
        other,
        store=files.store,
        version_root=files.root,
        client=client,
    )
    before = client.journal.pending()
    with pytest.raises(ValueError, match="original current publication lease"):
        work(build_candidate, client, staged, job._state.candidate)
    assert client.journal.pending() == before
    with closing(client.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 0


def test_foreign_database_is_refused_before_reading_its_private_paper_mappings(
    selected, monkeypatch
):
    client, peer = selected[0][1], selected[0][2]
    job, _calls = completion(selected, monkeypatch)
    _frame, sources = work(build_candidate, client, selected[3], job._state.candidate)
    statements = []

    def wrong_target():
        with peer.journal.transaction() as conn:
            conn.set_trace_callback(statements.append)
            try:
                return lineage_operations.from_candidate_in(
                    conn, client, selected[3], sources, job._state.candidate
                )
            finally:
                conn.set_trace_callback(None)

    with pytest.raises(ValueError):
        work(wrong_target)
    assert not any("FROM research_paper_identity" in sql for sql in statements)
