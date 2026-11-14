"""Native-context loss and real enrolled source observations never grant owners."""

import json

import pytest
from test_lineage_jobs import routes, work
from test_lineage_peer_sources import selected as selected
from test_research_lineage import corpus as corpus
from test_research_lineage import proposals
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import lineage_source_snapshots as sources
from paper_daily import llm, research_lineage, source_snapshots
from paper_daily.ai_types import Completion
from paper_daily.lineage_jobs import LineageJob


def test_view_change_at_source_retention_progress_refuses_before_files_or_model(
    corpus, monkeypatch
):
    calls, changed = [], []
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: (
        calls.append(True) or Completion(json.dumps(proposals(corpus[2])))))
    job = work(LineageJob.prepare, corpus[2], connections=routes())

    def progress(stage):
        if stage == "source_retention":
            changed.append(True)

    with pytest.raises(research_lineage.LineageError, match="caller_context_changed"):
        work(job.run, current=lambda: not changed, progress=progress)
    assert calls == [] and source_snapshots.list_owned(corpus[0]) == []
    changed.clear()
    assert work(job.run).report["statements"] and calls == [True]
    assert len(source_snapshots.list_owned(corpus[0])) == 3


def test_real_enrolled_corpus_retains_each_actual_source_without_new_operations(selected):
    _pair, corpus, observed, _prepared = selected
    _service, client, _peer, _files, _peer_files, _token, _peer_token = _pair
    before = client.journal.pending()
    rows = work(sources.retain, corpus, corpus_id=observed.data["corpus_id"],
                request_id=observed.data["request_id"])
    assert len(rows) == 3 and client.journal.pending() == before
    by_source = {json.loads(r["owner_json"])["source_id"]: r for r in rows}
    for source in observed.data["sources"]:
        owner = json.loads(by_source[source["source_id"]]["owner_json"])
        assert owner["paper_id"] == source["local_id"]
        assert owner["source_owner_id"] == source["parent"]["id"]
        assert owner["parent_lifecycle"] == source["lifecycle"]
        assert owner["binding"] == observed.data["binding"]
    retained = source_snapshots.list_owned(client.journal.path)
    assert sorted(retained, key=lambda r: r["request_id"]) == (
        sorted(rows, key=lambda r: r["request_id"]))


def test_closed_document_during_retention_keeps_complete_pair_without_spending_call(
    corpus, monkeypatch
):
    calls = []
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: calls.append(True))
    job = work(LineageJob.prepare, corpus[2], connections=routes())
    publish = sources.atomic_sources.publish

    def close_after_pair(database, row, **kwargs):
        result = publish(database, row, **kwargs)
        corpus[2]._documents[0]._owner.close()
        return result

    monkeypatch.setattr(sources.atomic_sources, "publish", close_after_pair)
    with pytest.raises(research_lineage.LineageError, match="source_changed"):
        work(job.run)
    assert calls == []
    rows = source_snapshots.list_owned(corpus[0])
    assert len(rows) == 1
    assert source_snapshots.source_path(corpus[0], rows[0]).read_bytes() == (
        corpus[1] / "focal.pdf").read_bytes()



@pytest.mark.parametrize("change", ["identity", "epoch"])
def test_rehashed_observation_still_rejects_internally_inconsistent_source(corpus, change):
    from uuid import uuid4

    from paper_daily.claim_content import hashed

    rows = work(sources.retain, corpus[2], corpus_id=str(uuid4()), request_id=str(uuid4()))
    row = next(r for r in rows if json.loads(r["owner_json"])["paper_id"] == "focal")
    owner = json.loads(row["owner_json"])
    if change == "identity":
        owner["source_identity"]["title"] = "Different selected paper"
    else:
        owner["focal_lifecycle"] = "0" * 32
    row["owner_json"] = json.dumps(owner)
    row["request_id"] = "lineage:" + hashed([owner, row["sha256"], row["size"]])
    with pytest.raises(ValueError):
        source_snapshots.validate(row)
