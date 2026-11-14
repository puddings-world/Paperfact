"""Real application coordinator uses native stores and journal, never an unbound bypass."""

import json
from contextlib import closing

import pytest
from test_lineage_jobs import routes, work
from test_lineage_live_journey import sync_all
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import rows

from paper_daily import lineage_sets, llm, research_lineage
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion
from paper_daily.lineage_workflow import LineageWorkflow
from paper_daily.manual_highlight_ops import observe_owner


def prepare(selected):
    client = selected[0][1]
    owners = [x["local_id"] for x in research_lineage._checked(selected[1])["observed"]]
    owner = observe_owner(
        client.journal.path, owners[0], expected_native=generation._identity(client.journal.path)
    )
    return work(
        LineageWorkflow.prepare,
        owner,
        owners[1:],
        connections=routes(),
        legacy_root=selected[1]._documents[0].path.parent,
    )


def test_native_workflow_publishes_real_outbox_and_peer_receives_same_report(selected, monkeypatch):
    workflow = prepare(selected)
    corpus = workflow._job._corpus
    response = dict(
        format=research_lineage.PROPOSALS,
        focal=corpus.focal,
        statements=[
            dict(
                stage="current_change",
                subject=corpus.focal,
                text="A concrete selected result.",
                function="unresolved",
                judgment=dict(status="unresolved", reason="Review needed."),
                passages=[
                    dict(
                        source_id=corpus.focal,
                        role="change_evidence",
                        cites=None,
                        quote="Actual selected original 0.",
                        page=1,
                        anchor=None,
                    )
                ],
            )
        ],
    )
    calls = []

    def complete(*_args, **_kwargs):
        calls.append(True)
        return Completion(json.dumps(response))

    monkeypatch.setattr(llm, "complete_result", complete)
    outcome = work(workflow.run)
    assert outcome.state == "queued_sync" and outcome.operation_id
    assert work(workflow.run) is outcome and len(calls) == 1
    client = workflow._client
    source_ops = [op for op in client.journal.pending() if op["entity_type"] == "research_file"]
    assert len(source_ops) == 3
    assert len(rows(client, lineage_sets.TABLE)) == 1
    peer = sync_all(selected, client, source_ops)
    assert (
        rows(peer, lineage_sets.TABLE)[0]["source_hash"]
        == rows(client, lineage_sets.TABLE)[0]["source_hash"]
    )
    assert not any(op["operation_id"] == outcome.operation_id for op in client.journal.pending())
    assert work(workflow.run) is outcome and len(calls) == 1
    with closing(client.journal._connect()) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_lineage_publications'"
        ).fetchone()


def test_native_missing_file_registration_refuses_before_any_completion(selected, monkeypatch):
    client = selected[0][1]
    before = client.journal.pending()
    with client.journal.transaction() as conn:
        conn.execute("DELETE FROM research_file_paths")
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No model call"))
    with pytest.raises(ValueError, match="Register the native original-file store"):
        prepare(selected)
    assert rows(client, lineage_sets.TABLE) == []
    assert client.journal.pending() == before


def test_missing_native_blob_index_is_not_recreated_by_analysis_preparation(selected, monkeypatch):
    client, files = selected[0][1], selected[0][3]
    index = files.store.root / "index.sqlite"
    index.rename(index.with_suffix(".unavailable"))
    before = client.journal.pending()
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No model call"))
    with pytest.raises(ValueError, match="store is unavailable"):
        prepare(selected)
    assert not index.exists()
    assert rows(client, lineage_sets.TABLE) == []
    assert client.journal.pending() == before
