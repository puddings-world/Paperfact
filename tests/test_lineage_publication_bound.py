"""A local publisher must not bypass a real enrolled workspace's journal."""

import json

import pytest
from test_lineage_jobs import routes, work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_publication import count

from paper_daily import lineage_publication, llm, research_lineage
from paper_daily.ai_types import Completion
from paper_daily.lineage_jobs import LineageJob


def test_real_enrolled_candidate_requires_compound_sync_publisher(selected, monkeypatch):
    peers, corpus, observed, _peer_staging = selected
    client = peers[1]
    before = client.journal.pending()
    response = json.dumps(
        dict(format=research_lineage.PROPOSALS, focal=corpus.focal, statements=[])
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: Completion(response))
    job = work(LineageJob.prepare, corpus, connections=routes(), publication_observation=observed)
    work(job.run)
    with pytest.raises(
        research_lineage.LineageError, match="lineage_compound_sync_publication_required"
    ):
        work(lineage_publication.prepare, job._state.candidate)
    assert client.journal.pending() == before
    assert count(client.journal.path, "paper_lineage_sets") == 0
    assert count(client.journal.path, lineage_publication.TABLE) == 0
