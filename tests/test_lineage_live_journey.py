"""Actual journal/service Lineage publication, transport, rollback and retained evidence."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from test_lineage_jobs import routes, work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import rows
from test_sync_files import drain

from paper_daily import (
    lineage_bound_originals,
    lineage_observation,
    lineage_peer_sources,
    lineage_projection,
    lineage_sets,
    lineage_shared_publication,
    llm,
    research_generation,
    research_lineage,
    sync_recovery,
)
from paper_daily.ai_types import Completion
from paper_daily.lineage_jobs import LineageJob
from paper_daily.manual_highlight_ops import observe_owner
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import canonical_operation
from paper_daily.sync_research import research_projection_writer


def native(client):
    return SyncClient.attach_existing(
        client.journal, client.writer, projection_writer=research_projection_writer
    )


def candidate(
    selected, monkeypatch, *, text="The focal study supplies a concrete change.", observed=None
):
    observed = observed or selected[2]
    corpus = selected[1]
    response = dict(
        format=research_lineage.PROPOSALS,
        focal=corpus.focal,
        statements=[
            dict(
                stage="current_change",
                subject=corpus.focal,
                text=text,
                function="unresolved",
                judgment=dict(status="unresolved", reason="No independent semantic validation."),
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
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: Completion(json.dumps(response)))
    job = work(LineageJob.prepare, corpus, connections=routes(), publication_observation=observed)
    work(job.run)
    return job._state.candidate


def publish(client, staged, result, **options):
    with client.journal.transaction() as conn:
        return lineage_shared_publication.publish_in(conn, client, staged, result, **options)


def setup_publication(selected, monkeypatch):
    result = candidate(selected, monkeypatch)
    client = native(selected[0][1])
    receipt = work(publish, client, selected[3], result)
    operations = client.journal.pending()
    science = next(op for op in operations if op["operation_id"] == receipt["operation_id"])
    sources = [op for op in operations if op["entity_type"] == "research_file"]
    return client, result, receipt, science, sources


def sync_all(selected, client, sources):
    service, _a, peer, files, _peer_files, token, peer_token = selected[0]
    first = client.sync_once(service, token, prepare_push=files.ready_to_push)
    assert first["deferred_push"] == 4  # Three held sources and their real scientific child.
    assert not any(e["operation"]["entity_type"] == "research_content" for e in service.pull(token))
    for source in sources:
        drain(lambda op=source: files.upload(op), "uploaded")
    second = client.sync_once(service, token, prepare_push=files.ready_to_push)
    assert second["deferred_push"] == 1
    final = client.sync_once(service, token, prepare_push=files.ready_to_push)
    assert final["pending"] == 0 and final["conflicts"] == 0
    from paper_daily.research_lifecycle import ensure_lifecycle
    from paper_daily.sync_capture import install

    # The low-level pair fixture is intentionally bare; perform real workspace
    # editing/capture setup before exposing it as an application reader.
    with closing(research_generation._connect(peer.journal.path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        install(conn, workspace_id=peer.journal.workspace_id, device_id=peer.journal.device_id)
        conn.commit()
    receiving = native(peer)
    receiving.sync_once(service, peer_token)
    return receiving


def test_real_journal_publication_retries_once_and_syncs_full_report_before_peer_pdf_download(
    selected, monkeypatch
):
    client, result, receipt, science, sources = setup_publication(selected, monkeypatch)
    assert json.loads(canonical_operation(science)) == science
    assert receipt["applied"] and len(rows(client, lineage_sets.TABLE)) == 1
    retry = work(publish, client, selected[3], result)
    assert not retry["applied"] and retry["sequence"] == receipt["sequence"]
    assert len(rows(client, lineage_projection.HISTORY)) == 1
    peer = sync_all(selected, client, sources)
    local, remote = rows(client, lineage_sets.TABLE)[0], rows(peer, lineage_sets.TABLE)[0]
    assert local["source_hash"] == remote["source_hash"]
    assert json.loads(remote["body_json"])["report"] == json.loads(local["body_json"])["report"]
    assert remote["document_hash"] == local["document_hash"]
    with closing(peer.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_applied").fetchone()[0] == 0
        assert not conn.execute("SELECT 1 FROM research_document_desired").fetchall()
    assert not work(publish, client, selected[3], result)["applied"]
    # Download owned peer originals without rebinding a primary PDF.
    peer_files = selected[0][4]
    for source in sources:
        drain(lambda identity=source["entity_id"]: peer_files.download(identity), "bound")
    owner = observe_owner(
        peer.journal.path,
        remote["paper_id"],
        expected_native=research_generation._identity(peer.journal.path),
    )
    source_id = json.loads(remote["body_json"])["report"]["sources"][0]["id"]
    original = work(lineage_bound_originals.prepare, owner, remote, source_id)
    assert lineage_bound_originals.for_delivery(original, owner, remote, source_id) == (
        selected[1]._documents[0].path.read_bytes()
    )


def test_actual_compound_publication_and_candidate_archive_restore_keep_full_evidence(
    selected, monkeypatch, tmp_path
):
    client, _result, _receipt, science, _sources = setup_publication(selected, monkeypatch)
    package = tmp_path / "actual-bound-publication.zip"
    made = sync_recovery.create(client.journal.path, package, blob_store=selected[0][3].store)
    assert sync_recovery.inspect(package) == made
    detached = tmp_path / "restored"
    sync_recovery.restore_detached(package, detached)
    saved = lineage_sets.saved(
        detached / "papers.db", rows(client, lineage_sets.TABLE)[0]["paper_id"]
    )
    assert saved == rows(client, lineage_sets.TABLE)
    with closing(sqlite3.connect(detached / "papers.db")) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paperfact_sync_identity'"
        ).fetchone()
    assert science["operation_id"] == _receipt["operation_id"]


@pytest.mark.parametrize("failure", ["second-source", "late-paper-change", "late-cancel"])
def test_late_failure_rolls_back_real_sources_science_and_receipt_but_keeps_prior_caller_work(
    selected, monkeypatch, failure
):
    client = native(selected[0][1])
    result = candidate(selected, monkeypatch)
    before = client.journal.pending()
    with client.journal.transaction() as conn:
        conn.execute("CREATE TABLE caller_work(value TEXT)")
    cancelled = [0]

    def cancel():
        cancelled[0] += 1
        return failure == "late-cancel" and cancelled[0] == 2

    def attempt():
        with client.journal.transaction() as conn:
            conn.execute("INSERT INTO caller_work VALUES('keep')")
            if failure == "second-source":
                conn.execute(
                    "CREATE TRIGGER fixture_source_fail BEFORE INSERT ON research_file_versions "
                    "WHEN (SELECT count(*) FROM research_file_versions)=1 "
                    "BEGIN SELECT RAISE(ABORT,'fixture second source failure'); END"
                )
            if failure == "late-paper-change":
                conn.execute(
                    "CREATE TRIGGER fixture_late_paper AFTER INSERT ON "
                    "research_lineage_sync_sources "
                    "BEGIN UPDATE papers SET title='fixture changed identity' "
                    "WHERE id=NEW.paper_id; END"
                )
            with pytest.raises((ValueError, sqlite3.DatabaseError)):
                lineage_shared_publication.publish_in(
                    conn, client, selected[3], result, cancelled=cancel
                )
            assert conn.execute("SELECT value FROM caller_work").fetchone()[0] == "keep"
            assert conn.execute("SELECT count(*) FROM paper_lineage_sets").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 0
            assert (
                conn.execute("SELECT count(*) FROM research_lineage_sync_history").fetchone()[0]
                == 0
            )

    work(attempt)
    assert client.journal.pending() == before
    with closing(client.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM research_generation_requests").fetchone()[0] == 1


def test_concurrent_real_retries_create_one_scientific_action_and_three_sources(
    selected, monkeypatch
):
    client = native(selected[0][1])
    result = candidate(selected, monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish, client, selected[3], result) for _ in range(2)]
        receipts = [f.result(timeout=15) for f in futures]
    assert sorted(r["applied"] for r in receipts) == [False, True]
    assert receipts[0]["sequence"] == receipts[1]["sequence"]
    assert len(rows(client, lineage_projection.HISTORY)) == 1
    with closing(client.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 3


def test_retry_after_a_later_generated_edit_never_overwrites_or_rebases_the_old_result(
    selected, monkeypatch
):
    client, first, _receipt, _science, _sources = setup_publication(selected, monkeypatch)
    old = selected[2].data
    from uuid import uuid4

    observed = work(lineage_observation.observe, selected[1], old["corpus_id"], str(uuid4()))
    staged = work(
        lineage_peer_sources.prepare,
        observed,
        store=selected[0][3].store,
        version_root=selected[0][3].root,
        client=client,
    )
    second = candidate(selected, monkeypatch, text="A later explicit analysis.", observed=observed)
    work(publish, client, staged, second)
    before = rows(client, lineage_sets.TABLE), client.journal.pending()
    with pytest.raises(ValueError):
        work(publish, client, selected[3], first)
    assert (rows(client, lineage_sets.TABLE), client.journal.pending()) == before
    assert len(rows(client, lineage_projection.HISTORY)) == 2
