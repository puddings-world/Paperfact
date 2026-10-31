"""Declared generated cache aliases remain covered even when blobs already own A."""

import os
import sqlite3
import zipfile
from contextlib import closing

import pytest
from test_claim_jobs import claims as claims_fixture
from test_claim_jobs import job
from test_claim_jobs import ready as ready_fixture
from test_claim_jobs import workspace as workspace_fixture

from paper_daily import file_change, source_snapshots, sync_recovery
from paper_daily.sync_artifacts import paths
from paper_daily.sync_document_actions import stage_file
from paper_daily.sync_documents import bind_verified_document, desired_document, verify_document
from paper_daily.sync_operations import ResearchOperations

claims = claims_fixture
ready = ready_fixture
workspace = workspace_fixture


def owned(claims):
    assert job(claims).run().status == "accepted"
    database = claims[0][0]
    client = claims[0][1]
    blobs = None
    if client is not None:
        with closing(sqlite3.connect(database)) as conn:
            blobs = paths(conn)[0]
            portable = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
            ).fetchone()[0]
        manifest = stage_file(blobs, claims[0][2].path)
        ResearchOperations(client).attach_document(
            portable, manifest, store=blobs, request_id="fixture-current-primary"
        )
        with client.journal.transaction() as conn:
            target = desired_document(conn, portable)
        proof = verify_document(blobs, target)
        with client.journal.transaction() as conn:
            assert bind_verified_document(conn, target, proof)
    receipt = source_snapshots.list_owned(database)[0]
    cache = source_snapshots.source_path(database, receipt)
    return database, blobs, receipt, cache


def test_duplicate_owned_cache_is_retained_without_materializing_or_changing_research(
    claims, tmp_path
):
    database, blobs, receipt, cache = owned(claims)
    before_db, before_cache = database.read_bytes(), cache.read_bytes()

    def research_files():
        return sorted(
            str(path)
            for folder in (database.parent / "pdf", database.parent / ".paperfact-source-snapshots")
            for path in folder.rglob("*")
            if path.is_file()
        )

    before_files = research_files()
    output = tmp_path / "complete.zip"
    manifest = sync_recovery.create(
        database, output, blob_store=blobs, pdf_roots=[claims[0][2].path.parent]
    )
    assert sync_recovery.inspect(output) == manifest
    with zipfile.ZipFile(output) as archive:
        assert archive.read("objects/" + receipt["sha256"]) == before_cache
        rows = archive.read("tables/research_source_snapshot_recovery.jsonl")
        assert receipt["sha256"].encode() in rows
    assert database.read_bytes() == before_db and cache.read_bytes() == before_cache
    assert research_files() == before_files


@pytest.mark.parametrize("change", ["corrupt", "foreign"])
def test_matching_blob_never_hides_corrupt_or_foreign_cache_contents(claims, tmp_path, change):
    database, blobs, _receipt, cache = owned(claims)
    if change == "corrupt":
        data, stat = cache.read_bytes(), cache.stat()
        cache.write_bytes(b"X" + data[1:])
        os.utime(cache, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    else:
        foreign = cache.parent.parent / "foreign-owner" / cache.name
        foreign.parent.mkdir()
        foreign.write_bytes(b"foreign unrelated contents:" + cache.read_bytes())
    output = tmp_path / "refused.zip"
    with pytest.raises(ValueError):
        sync_recovery.create(
            database, output, blob_store=blobs, pdf_roots=[claims[0][2].path.parent]
        )
    assert not output.exists()


def test_same_size_restored_mtime_change_during_alias_read_is_rejected(
    claims, tmp_path, monkeypatch
):
    database, blobs, _receipt, cache = owned(claims)
    original, calls = file_change.version, []

    def changed(path, *, stream=None):
        if path == cache:
            calls.append(1)
            if len(calls) == 2:
                data, stat = cache.read_bytes(), cache.stat()
                cache.write_bytes(b"X" + data[1:])
                os.utime(cache, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        return original(path, stream=stream)

    monkeypatch.setattr(file_change, "version", changed)
    output = tmp_path / "changed.zip"
    with pytest.raises(ValueError, match="source cache changed"):
        sync_recovery.create(
            database, output, blob_store=blobs, pdf_roots=[claims[0][2].path.parent]
        )
    assert len(calls) >= 2 and not output.exists()
