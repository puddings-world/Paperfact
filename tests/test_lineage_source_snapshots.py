"""Exact corpus originals survive calls, cancellation, retry and detached backup."""

import copy
import json
import sqlite3
import zipfile
from contextlib import closing
from uuid import uuid4

import pytest
from test_lineage_jobs import routes, work
from test_research_lineage import corpus as corpus
from test_research_lineage import proposals

from paper_daily import lineage_source_snapshots as sources
from paper_daily import llm, research_lineage, source_snapshots, sync_recovery
from paper_daily.ai_types import Completion
from paper_daily.lineage_jobs import LineageJob


def prepare(corpus, monkeypatch, complete=None):
    if complete is None:
        def complete(*_a, **_k):
            return Completion(json.dumps(proposals(corpus[2])))
    monkeypatch.setattr(llm, "complete_result", complete)
    return work(LineageJob.prepare, corpus[2], connections=routes())


def test_all_originals_are_durable_before_first_completion_and_retry_is_exact(corpus, monkeypatch):
    database, root, captured = corpus
    before = database.read_bytes()
    originals = {p.stem: p.read_bytes() for p in root.glob("*.pdf")}
    calls = []

    def complete(*_a, **_k):
        assert database.read_bytes() == before
        rows = source_snapshots.list_owned(database)
        assert len(rows) == 3
        assert {json.loads(r["owner_json"])["paper_id"] for r in rows} == set(originals)
        assert all(source_snapshots.source_path(database, r).read_bytes() ==
                   originals[json.loads(r["owner_json"])["paper_id"]] for r in rows)
        calls.append(True)
        return Completion(json.dumps(proposals(captured)))

    job = prepare(corpus, monkeypatch, complete)
    result = work(job.run)
    rows = source_snapshots.list_owned(database)
    assert result.execution["corpus_id"] == job.corpus_id
    assert all(json.loads(r["owner_json"])["generation_request_id"] == job.request_id for r in rows)
    assert all(json.loads(r["owner_json"])["corpus_id"] == job.corpus_id for r in rows)
    assert work(job.run) is result and calls == [True]
    assert source_snapshots.list_owned(database) == rows
    with closing(sqlite3.connect(database)) as conn:
        saved = conn.execute(
            "SELECT status,row_json FROM research_generation_requests WHERE request_id=?",
            (job.request_id,),
        ).fetchall()
        assert len(saved) == 1 and saved[0][0] == "candidate"
        assert json.loads(saved[0][1])["paper_id"] == "focal"
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paper_lineage_sets'").fetchone()


def test_failed_source_publication_spends_no_call_and_same_job_repairs_exact_retry(
    corpus, monkeypatch
):
    calls = []
    job = prepare(corpus, monkeypatch, lambda *_a, **_k: (
        calls.append(True) or Completion(json.dumps(proposals(corpus[2])))))
    publish = sources.atomic_sources.publish
    lost = []

    def fail(database, row, **kwargs):
        result = publish(database, row, **kwargs)
        if not lost:
            lost.append(True)
            raise OSError("fixture source receipt acknowledgement lost")
        return result

    monkeypatch.setattr(sources.atomic_sources, "publish", fail)
    with pytest.raises(OSError, match="acknowledgement"):
        work(job.run)
    assert calls == []
    first = source_snapshots.list_owned(corpus[0])
    assert len(first) == 1
    assert work(job.run).report["statements"]
    rows = source_snapshots.list_owned(corpus[0])
    assert len(rows) == 3 and first[0] in rows and calls == [True]


def test_cancel_between_originals_keeps_only_complete_pairs_and_resumes_without_duplicates(
    corpus, monkeypatch
):
    calls, stopped = [], []
    job = prepare(corpus, monkeypatch, lambda *_a, **_k: (
        calls.append(True) or Completion(json.dumps(proposals(corpus[2])))))
    publish = sources.atomic_sources.publish

    def stop(database, row, **kwargs):
        result = publish(database, row, **kwargs)
        stopped.append(True)
        return result

    monkeypatch.setattr(sources.atomic_sources, "publish", stop)
    with pytest.raises(research_lineage.LineageError, match="cancelled"):
        work(job.run, cancelled=lambda: bool(stopped))
    assert calls == [] and len(source_snapshots.list_owned(corpus[0])) == 1
    stopped.clear()
    monkeypatch.setattr(sources.atomic_sources, "publish", publish)
    assert work(job.run).report["statements"]
    assert calls == [True] and len(source_snapshots.list_owned(corpus[0])) == 3
    assert not list(corpus[0].parent.rglob(".position-stage-*"))


def test_missing_peer_has_no_invented_original_and_ids_are_explicit(corpus):
    captured = research_lineage.capture(corpus[0], "focal", ["missing"], legacy_root=corpus[1])
    key, request = str(uuid4()), str(uuid4())
    rows = work(sources.retain, captured, corpus_id=key, request_id=request)
    assert len(rows) == 1
    owner = json.loads(rows[0]["owner_json"])
    assert owner["paper_id"] == owner["focal_paper_id"] == "focal"
    assert owner["source_id"] == captured.focal and owner["corpus_id"] == key
    assert captured.sources[1]["availability"] == "unavailable"


def test_changed_live_pdf_keeps_exact_originals_in_independent_backup(corpus, monkeypatch):
    from paper_daily import store

    database, root, captured = corpus
    # Match the maintained research schema, without enrolling a sync identity.
    with closing(sqlite3.connect(database)) as conn, conn:
        store._migrate(conn)
    original = (root / "focal.pdf").read_bytes()

    def complete(*_a, **_k):
        (root / "focal.pdf").write_bytes(b"changed live source after completion started")
        return Completion(json.dumps(proposals(captured)))

    job = prepare(corpus, monkeypatch, complete)
    result = work(job.run)
    assert result.retention_reason == "source_or_owner_changed"
    rows = source_snapshots.list_owned(database)
    focal = next(r for r in rows if json.loads(r["owner_json"])["paper_id"] == "focal")
    assert source_snapshots.source_path(database, focal).read_bytes() == original
    # The changed live primary is not a valid PDF; remove only this fixture alias.
    # The complete independent original pairs must remain sufficient for backup.
    (root / "focal.pdf").unlink()
    archive = database.parent / "lineage-sources.zip"
    sync_recovery.create(database, archive)
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.read("objects/" + focal["sha256"]) == original
    restored = database.parent / "detached"
    sync_recovery.restore_detached(archive, restored)
    assert source_snapshots.list_owned(restored / "papers.db") == []
    with closing(sqlite3.connect(restored / "papers.db")) as conn:
        kept = [json.loads(r[0]) for r in conn.execute(
            "SELECT data FROM recovery_records WHERE table_name=?", (source_snapshots.TABLE,))]
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paperfact_sync_identity'").fetchone()
    assert sorted(kept, key=lambda r: r["request_id"]) == sorted(
        rows, key=lambda r: r["request_id"])
    assert all((restored / "objects" / r["sha256"]).read_bytes() ==
               source_snapshots.source_path(database, r).read_bytes() for r in kept)


@pytest.mark.parametrize("field,value", [
    ("corpus_id", "invalid"), ("generation_request_id", "invalid"),
    ("source_id", "missing-hash"), ("focal_lifecycle", "invalid"),
    ("focal_paper_id", ""),
])
def test_malformed_lineage_observation_is_not_an_archive_receipt(corpus, field, value):
    rows = work(sources.retain, corpus[2], corpus_id=str(uuid4()), request_id=str(uuid4()))
    row = copy.deepcopy(rows[0])
    owner = json.loads(row["owner_json"])
    owner[field] = value
    row["owner_json"] = json.dumps(owner)
    with pytest.raises(ValueError):
        source_snapshots.validate(row)


def test_corpus_observation_cannot_authorize_claim_original_even_with_matching_owner(corpus):
    from paper_daily import local_source_owners
    from paper_daily.manual_highlight_ops import capture_owner

    rows = work(sources.retain, corpus[2], corpus_id=str(uuid4()), request_id=str(uuid4()))
    row = next(r for r in rows if json.loads(r["owner_json"])["paper_id"] == "focal")
    owner = capture_owner(corpus[0], "focal")
    with closing(sqlite3.connect(corpus[0])) as conn:
        assert not local_source_owners._owner_matches(conn, owner, row, generated=True)
        assert not local_source_owners._owner_matches(conn, owner, row)
    assert local_source_owners.validate(row) == row



def test_failed_completion_keeps_all_originals_and_new_request_keeps_distinct_observations(
    corpus, monkeypatch
):
    calls = []

    def failed(*_a, **_k):
        calls.append(True)
        return Completion(None, "fixture unavailable")

    job = prepare(corpus, monkeypatch, failed)
    with pytest.raises(research_lineage.LineageError, match="lineage_generation_failed"):
        work(job.run)
    first = source_snapshots.list_owned(corpus[0])
    assert len(first) == 3
    with pytest.raises(research_lineage.LineageError, match="explicit_new_job_required"):
        work(job.run)
    assert calls == [True] and source_snapshots.list_owned(corpus[0]) == first
    key = job.corpus_id
    next_job = work(LineageJob.prepare, corpus[2], connections=routes(), corpus_id=key)
    assert next_job.corpus_id == key and next_job.request_id != job.request_id
    with pytest.raises(research_lineage.LineageError, match="lineage_generation_failed"):
        work(next_job.run)
    rows = source_snapshots.list_owned(corpus[0])
    assert len(rows) == 6 and len({r["sha256"] for r in rows}) == 3
    assert {json.loads(r["owner_json"])["generation_request_id"] for r in rows} == {
        job.request_id, next_job.request_id}


@pytest.mark.parametrize("key", ["", "not-a-uuid", 1])
def test_invalid_explicit_corpus_key_refuses_before_archive_or_model(corpus, monkeypatch, key):
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No paid call"))
    with pytest.raises(ValueError):
        work(LineageJob.prepare, corpus[2], connections=routes(), corpus_id=key)
    assert source_snapshots.list_owned(corpus[0]) == []
