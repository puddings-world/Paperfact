"""Actual retained Lineage versions remain readable without source or replay grants."""

import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_lineage_jobs import work
from test_lineage_lifecycle import active as active
from test_lineage_publication import publish
from test_lineage_target_jobs import job_for
from test_research_lineage import corpus as corpus

from paper_daily import (
    lineage_lifecycle,
    lineage_observation,
    lineage_publication,
    lineage_versions,
    llm,
    research_lineage,
)
from paper_daily.ai_types import Completion


def test_generated_current_removed_and_restored_versions_are_read_only(active):
    owner, row = active
    before = owner.database.read_bytes()
    result = work(lineage_versions.collect, owner)
    assert result["total"] == 1 and not result["more"]
    item = result["items"][0]
    assert item["row"] == row and item["current"] and item["occupied"]
    assert item["origin"]["kind"] == "generated"
    assert owner.database.read_bytes() == before
    work(lineage_lifecycle.change, owner, row, request_id=str(uuid4()), action="retire")
    removed = work(lineage_versions.collect, owner)["items"][0]
    assert not removed["current"] and not removed["occupied"]
    assert removed["origin"] == item["origin"]
    work(
        lineage_lifecycle.change,
        owner,
        row,
        request_id=str(uuid4()),
        action="restore",
        origin=removed["origin"],
    )
    assert work(lineage_versions.collect, owner)["items"] == [item]


def test_multiple_real_generated_versions_keep_exact_original_provenance_and_paging(
    active, corpus, monkeypatch
):
    owner, old = active
    captured = research_lineage.capture(
        corpus[0], "focal", ["prior", "later"], legacy_root=corpus[1]
    )
    observed = work(lineage_observation.observe, captured, old["corpus_key"], str(uuid4()))
    response = json.dumps(
        dict(format=research_lineage.PROPOSALS, focal=captured.focal, statements=[])
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: Completion(response))
    job = job_for((corpus[0], corpus[1], captured), observed)
    work(job.run)
    work(publish, corpus[0], work(lineage_publication.prepare, job._state.candidate))
    monkeypatch.setattr(
        llm, "complete_result", lambda *_a, **_k: pytest.fail("History cannot call AI")
    )
    versions = work(lineage_versions.collect, owner)
    assert versions["total"] == 2
    assert sum(item["current"] for item in versions["items"]) == 1
    historical = next(item for item in versions["items"] if item["row"] == old)
    assert not historical["current"] and historical["occupied"]
    assert historical["origin"]["kind"] == "generated"
    first = work(lineage_versions.collect, owner, limit=1)
    second = work(lineage_versions.collect, owner, limit=1, offset=1)
    assert first["more"] and not second["more"]
    assert first["items"] + second["items"] == versions["items"]
    with pytest.raises(ValueError, match="target changed"):
        work(
            lineage_lifecycle.change,
            owner,
            old,
            request_id=str(uuid4()),
            action="restore",
            origin=historical["origin"],
        )


def test_lost_provenance_keeps_historical_data_without_restore_origin(active):
    owner, row = active
    work(lineage_lifecycle.change, owner, row, request_id=str(uuid4()), action="retire")
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        conn.execute("DELETE FROM research_lineage_publications")
    result = work(lineage_versions.collect, owner)
    assert result["total"] == 1
    assert result["items"][0] == dict(row=row, origin=None, current=False, occupied=False)


@pytest.mark.parametrize(
    "options", [dict(limit=0), dict(limit=True), dict(offset=-1), dict(offset=True)]
)
def test_invalid_history_page_does_not_read_or_mutate(active, options):
    owner, _row = active
    before = owner.database.read_bytes()
    with pytest.raises(ValueError, match="version page"):
        work(lineage_versions.collect, owner, **options)
    assert owner.database.read_bytes() == before
