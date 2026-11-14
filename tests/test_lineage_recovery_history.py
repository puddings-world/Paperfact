"""Old exact-original publication history survives a newer canonical PDF version."""

import json
import zipfile
from uuid import uuid4

from test_lineage_jobs import work
from test_lineage_publication import publish
from test_lineage_recovery import published
from test_lineage_target_jobs import job_for
from test_research_evidence import pdf
from test_research_lineage import corpus as corpus
from test_sync_recovery import archive_rows

from paper_daily import (
    lineage_observation,
    lineage_publication,
    lineage_sets,
    llm,
    research_lineage,
    sync_recovery,
)
from paper_daily.ai_types import Completion


def test_current_version_and_prior_publication_keep_distinct_originals(
    corpus, monkeypatch, tmp_path
):
    first = published(corpus, monkeypatch)
    old_hash = corpus[2].sources[0]["document_hash"]
    pdf(corpus[1] / "focal.pdf", [["A separately revised exact focal original."]])
    current = research_lineage.capture(
        corpus[0],
        "focal",
        ["prior", "later"],
        legacy_root=corpus[1],
    )
    assert current.sources[0]["document_hash"] != old_hash
    observed = work(lineage_observation.observe, current, first.corpus_id, str(uuid4()))
    response = json.dumps(
        dict(format=research_lineage.PROPOSALS, focal=current.focal, statements=[])
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: Completion(response))
    second = job_for((corpus[0], corpus[1], current), observed)
    work(second.run)
    work(publish, corpus[0], work(lineage_publication.prepare, second._state.candidate))
    package = tmp_path / "history.zip"
    manifest = sync_recovery.create(corpus[0], package)
    assert sync_recovery.inspect(package) == manifest
    assert len(archive_rows(package, "paper_lineage_sets")) == 1
    receipts = archive_rows(package, "research_lineage_publications")
    assert {r["request_id"] for r in receipts} == {first.request_id, second.request_id}
    assert len(archive_rows(package, "research_local_source_owners")) == 6
    assert {old_hash, current.sources[0]["document_hash"]} <= {
        b["sha256"] for b in manifest["blobs"]
    }
    with zipfile.ZipFile(package) as archive:
        assert archive.read("objects/" + old_hash) != archive.read(
            "objects/" + current.sources[0]["document_hash"]
        )
    target = tmp_path / "restored"
    sync_recovery.restore_detached(package, target)
    saved = lineage_sets.saved(target / "papers.db", "focal")
    assert len(saved) == 1 and saved[0]["document_hash"] == current.sources[0]["document_hash"]
