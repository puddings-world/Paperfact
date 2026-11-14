"""Retained Lineage proposals stay readable without generic application authority."""

import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_lineage_candidates import completed
from test_lineage_jobs import work
from test_research_lineage import corpus as corpus

from paper_daily import lineage_candidates
from paper_daily.research_review import ResearchReview


def test_keep_retained_proposal_records_one_decision_without_installing_report(corpus, monkeypatch):
    job, result, _calls = completed(corpus, monkeypatch)
    review = ResearchReview(corpus[0])
    preview = review.preview("generation", job.request_id)
    request = str(uuid4())
    assert review.decide(preview, keep=True, request_id=request) == {
        "decision": "kept",
        "operation_id": None,
    }
    assert review.decide(preview, keep=True, request_id=request) == {
        "decision": "kept",
        "operation_id": None,
    }
    with closing(sqlite3.connect(corpus[0])) as conn:
        rows = conn.execute(
            "SELECT decision,provenance FROM research_review_receipts WHERE request_id=?",
            (request,),
        ).fetchall()
        assert len(rows) == 1 and rows[0][0] == "kept"
        assert json.loads(rows[0][1])["target_kind"] == "paper"
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paper_lineage_sets'"
        ).fetchone()
    assert (
        json.loads(
            json.loads(work(lineage_candidates.saved, corpus[0], "focal")[0]["row_json"])[
                "body_json"
            ]
        )["report"]
        == result.report
    )


def test_target_listing_refuses_corpus_proposal_without_generic_registry_lookup(
    corpus, monkeypatch
):
    job, _result, _calls = completed(corpus, monkeypatch)
    review = ResearchReview(corpus[0])
    preview = review.preview("generation", job.request_id)
    with pytest.raises(ValueError, match="corpus-aware"):
        review.targets(preview)


def test_saved_rows_are_defensive_and_worker_only(corpus, monkeypatch):
    job, _result, _calls = completed(corpus, monkeypatch)
    first = work(lineage_candidates.saved, corpus[0], "focal")
    first[0]["row_json"] = "caller changed copy"
    assert work(lineage_candidates.saved, corpus[0], "focal")[0] == job._state.candidate.record
    with pytest.raises(ValueError, match="worker_required"):
        lineage_candidates.saved(corpus[0], "focal")


def test_private_proposal_cannot_enter_generic_main_key_publication(corpus, monkeypatch):
    from paper_daily import research_generation as generation

    job, _result, _calls = completed(corpus, monkeypatch)
    record = job._state.candidate.record
    before = corpus[0].read_bytes()
    with pytest.raises(ValueError, match="Unsupported"):
        generation.publish_generation(
            generation.GenerationContext(record["context_json"]), row=json.loads(record["row_json"])
        )
    assert corpus[0].read_bytes() == before
