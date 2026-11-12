"""Real local rescue, pending disposition and exact retry/export without synchronization."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from test_local_blob_binding import no_external as no_external
from test_local_deck_proposals import local as local
from test_local_deck_proposals import native
from test_portable_deck_proposal import scientific as scientific

from paper_daily import local_deck_proposals as catalog
from paper_daily import local_rescue_import as rescue
from paper_daily import portable_deck_archive as archive
from paper_daily.pending_deck_result import PendingDeckResults


@pytest.fixture
def rescued(local):
    database, manifest, blobs, saved, before = local
    path = database.parent / "study.paperfact-draft.zip"
    archive.export(path, manifest, lambda item: blobs[item["sha256"]])
    source = archive.inspect_file(path)
    job = rescue.prepare(
        database, "local-paper", source, expected_native=native(database), request_id="rescue-local"
    )
    return database, source, job, saved, before


def test_actual_local_rescue_retains_full_science_and_replays_without_active_changes(
    rescued, scientific
):
    database, source, job, saved, before = rescued
    result = rescue.run(job)
    assert result.durable
    for _ in range(25):
        assert rescue.run(job).candidate_id == result.candidate_id
    assert saved.read_bytes() == before
    loaded = catalog.read(database, result.candidate_id, expected_native=native(database))
    assert loaded.content["deck"] == source.content["deck"]
    assert loaded.content["evidence"] == source.content["evidence"]
    assert loaded.content["image_bytes"] == scientific[2]
    assert loaded.content["original_bytes"] == scientific[3]
    assert loaded.content["evidence"]["figures"][-1]["caption"] == "Full unused caption"
    assert source.current()
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT count(*) FROM " + catalog.TABLE).fetchone() == (1,)
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_sync_binding'"
        ).fetchone()


def incomplete(rescued, monkeypatch):
    database, _source, job, saved, before = rescued
    actual = catalog._insert

    def fail(*args, **kwargs):
        actual(*args, **kwargs)
        raise sqlite3.OperationalError("Synthetic metadata failure after catalog insert")

    monkeypatch.setattr(catalog, "_insert", fail)
    outcome = rescue.run(job)
    assert not outcome.durable and saved.read_bytes() == before
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT count(*) FROM " + catalog.TABLE).fetchone() == (0,)
    return outcome, actual


def test_unsaved_actual_result_is_app_owned_and_retry_keeps_original_deck(rescued, monkeypatch):
    database, _source, _job, saved, before = rescued
    outcome, actual = incomplete(rescued, monkeypatch)
    pool = PendingDeckResults()
    key = pool.hold(outcome)
    assert pool.hold(outcome) == key and pool.items() == [(key, outcome)]
    assert "local" in pool.label(key) and str(database) in pool.context(key)
    again = pool.retry(key)
    assert not again.durable and pool.pending
    monkeypatch.setattr(catalog, "_insert", actual)
    result = pool.retry(key)
    assert result.durable and result.deck is outcome.deck and not pool.pending
    assert saved.read_bytes() == before
    loaded = catalog.read(database, result.candidate_id, expected_native=native(database))
    assert loaded.current_parent


def test_export_uses_complete_memory_copy_after_source_file_and_database_disappear(
    rescued, scientific, monkeypatch
):
    database, source, _job, saved, before = rescued
    outcome, _actual = incomplete(rescued, monkeypatch)
    pool = PendingDeckResults()
    key = pool.hold(outcome)
    source.source_path.unlink()
    database.unlink()
    destination = saved.parent / "rescued-again.paperfact-draft.zip"
    destination.write_bytes(b"Prior user export")
    with pytest.raises(FileExistsError):
        pool.export(key, destination)
    assert pool.pending and destination.read_bytes() == b"Prior user export"
    destination.unlink()
    assert pool.export(key, destination) == destination and not pool.pending
    read = archive.inspect_file(destination).content
    assert read["image_bytes"] == scientific[2] and read["original_bytes"] == scientific[3]
    assert read["evidence"]["figures"][-1]["caption"] == "Full unused caption"
    assert saved.read_bytes() == before and not database.exists()


def test_recreated_parent_refuses_retry_but_complete_export_remains_available(
    rescued, scientific, tmp_path
):
    database, _source, job, saved, before = rescued
    with closing(sqlite3.connect(database)) as conn, conn:
        row = conn.execute("SELECT * FROM papers WHERE id='local-paper'").fetchone()
        conn.execute("DELETE FROM papers WHERE id='local-paper'")
        conn.execute("INSERT INTO papers VALUES (" + ",".join("?" for _ in row) + ")", row)
    outcome = rescue.run(job)
    assert not outcome.durable
    pool = PendingDeckResults()
    key = pool.hold(outcome)
    assert not pool.retry(key).durable and pool.pending
    assert saved.read_bytes() == before
    destination = tmp_path / "historical.paperfact-draft.zip"
    pool.export(key, destination)
    assert not pool.pending
    assert archive.inspect_file(destination).content["original_bytes"] == scientific[3]


def test_changed_rescue_file_refuses_preparation_without_creating_a_candidate(local):
    database, manifest, blobs, saved, before = local
    path = database.parent / "changed.zip"
    archive.export(path, manifest, lambda item: blobs[item["sha256"]])
    source = archive.inspect_file(path)
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="changed"):
        rescue.prepare(
            database, "local-paper", source, expected_native=native(database), request_id="changed"
        )
    with closing(sqlite3.connect(database)) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (catalog.TABLE,)
        ).fetchone()
    assert saved.read_bytes() == before


def test_duplicate_pending_action_is_refused_while_actual_retry_is_held(rescued, monkeypatch):
    outcome, actual = incomplete(rescued, monkeypatch)
    monkeypatch.setattr(catalog, "_insert", actual)
    pool = PendingDeckResults()
    key = pool.hold(outcome)
    admitted, release = threading.Event(), threading.Event()
    retry = rescue.retry

    def held(value):
        admitted.set()
        assert release.wait(15)
        return retry(value)

    monkeypatch.setattr(rescue, "retry", held)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(pool.retry, key)
        try:
            assert admitted.wait(15)
            with pytest.raises(ValueError, match="progress"):
                pool.retry(key)
            with pytest.raises(ValueError):
                pool.discard(key, expected=outcome)
            assert pool.pending
        finally:
            release.set()
        assert future.result(timeout=15).durable
    assert not pool.pending


def test_invalid_mutated_pending_projection_cannot_replace_or_export_science(rescued, monkeypatch):
    outcome, _actual = incomplete(rescued, monkeypatch)
    pool = PendingDeckResults()
    key = pool.hold(outcome)
    before = outcome.deck.title
    outcome.deck.title = "Altered projection"
    with pytest.raises(ValueError, match="differs"):
        pool.hold(outcome)
    with pytest.raises(ValueError, match="differs"):
        pool.export(key, rescued[0].parent / "altered.zip")
    assert pool.pending
    outcome.deck.title = before
    pool.discard(key, expected=outcome)
    assert not pool.pending


def test_fsync_failure_keeps_previous_rescue_and_pending_result(rescued, monkeypatch):
    outcome, _actual = incomplete(rescued, monkeypatch)
    pool = PendingDeckResults()
    key = pool.hold(outcome)
    destination = rescued[0].parent / "not-yet-exported.zip"

    def denied(_handle):
        raise OSError("Synthetic rescue flush failure")

    monkeypatch.setattr(archive.os, "fsync", denied)
    with pytest.raises(OSError):
        pool.export(key, destination)
    assert pool.pending and not destination.exists()
    assert not list(destination.parent.glob(".paperfact-rescue-*"))


def test_parent_recreation_during_actual_blob_staging_cannot_refresh_original_target(
    local, monkeypatch
):
    database, manifest, blobs, saved, before = local
    path = database.parent / "parent-change.paperfact-draft.zip"
    archive.export(path, manifest, lambda item: blobs[item["sha256"]])
    source = archive.inspect_file(path)
    read = archive.RescueArchive.read_blob
    changed = []

    def replace_parent(value, descriptor):
        if not changed:
            with closing(sqlite3.connect(database)) as conn, conn:
                row = conn.execute("SELECT * FROM papers WHERE id='local-paper'").fetchone()
                conn.execute("DELETE FROM papers WHERE id='local-paper'")
                conn.execute("INSERT INTO papers VALUES (" + ",".join("?" for _ in row) + ")", row)
            changed.append(True)
        return read(value, descriptor)

    monkeypatch.setattr(archive.RescueArchive, "read_blob", replace_parent)
    with pytest.raises(ValueError, match="parent/absence changed"):
        rescue.prepare(
            database, "local-paper", source,
            expected_native=native(database), request_id="held-parent-change",
        )
    assert changed and saved.read_bytes() == before
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT count(*) FROM " + catalog.TABLE).fetchone() == (0,)
