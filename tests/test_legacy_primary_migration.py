"""Explicit source-observed migration; real graphs, bytes and independent recovery."""

import hashlib
import json
import os
import shutil
import sqlite3
import zipfile
from contextlib import closing
from threading import Event, Thread
from types import SimpleNamespace
from uuid import uuid4

import pymupdf
import pytest

from paper_daily import config, followups, llm, store, sync_document_actions, sync_recovery
from paper_daily import later_outcomes as outcomes
from paper_daily.document_reader import from_workspace
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import install
from paper_daily.sync_client import SyncClient
from paper_daily.sync_documents import applied_document, desired_document
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_journal import Journal
from paper_daily.sync_operations import ResearchOperations
from paper_daily.sync_research import prepare as initialize
from paper_daily.sync_research import research_writer
from paper_daily.workspace_service import Cancelled, Ticket


def pdf(path, text):
    staged = path.with_suffix(".next")
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 50), text)
        document.save(staged)
    os.replace(staged, path)


def dump(database):
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        return list(conn.iterdump())


def recreate_parent(fixture):
    """Controlled unreplicated repair actor; protocol deletion remains unsupported."""
    from paper_daily import research_generation as generation
    from paper_daily.research_lifecycle import parent_lifecycle
    from paper_daily.sync_capture import suppress_capture

    with closing(generation._connect(fixture.database)) as conn, conn, suppress_capture(conn):
        conn.row_factory = sqlite3.Row
        original = dict(conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone())
        before = parent_lifecycle(conn, "paper", "paper")
        conn.execute("DELETE FROM papers WHERE id='paper'")
        conn.execute(
            "INSERT INTO papers("
            + ",".join(original)
            + ") VALUES("
            + ",".join("?" for _ in original)
            + ")",
            tuple(original.values()),
        )
        after = parent_lifecycle(conn, "paper", "paper")
        assert before is not None and after is not None and before != after


@pytest.fixture
def make(tmp_path, monkeypatch):
    def factory(queried="A", replace=True):
        root = tmp_path / "workspace"
        root.mkdir()
        database = root / "papers.db"
        with closing(sqlite3.connect(database)) as conn:
            conn.executescript(store.SCHEMA)
        initialize(database, workspace_id="workspace", device_id="desktop")
        client = SyncClient(
            Journal(database, workspace_id="workspace", device_id="desktop"), research_writer
        )
        monkeypatch.setattr(store, "DB_PATH", database)
        monkeypatch.setattr(store, "ensure_dirs", lambda: None)
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            install(conn, workspace_id="workspace", device_id="desktop")
            store.upsert_papers(
                conn,
                [dict(id="paper", title="Paper", venue="Fixture", year=2026, source="fixture")],
            )
        originals = root / "pdf"
        originals.mkdir()
        path = originals / "paper.pdf"
        monkeypatch.setattr(config, "PDF_DIR", originals)
        if queried == "A":
            pdf(path, "Original A was present during the recorded empty query")

        class NoTransport:
            def __getattr__(self, name):
                if name == "base_url":
                    raise AttributeError(name)
                raise AssertionError("Local migration attempted transport")

        blobs = BlobStore(root / "blobs")
        transfers = FileTransfers(
            client, blobs, NoTransport(), origin="https://fixture.invalid", token=None
        )
        transfers.close()
        monkeypatch.setattr(followups, "work_id", lambda _: "W1")
        monkeypatch.setattr(followups, "_citing_openalex", lambda _: [])
        monkeypatch.setattr(followups, "_citing_s2", lambda _: [])

        def no_model(*args, **kwargs):
            pytest.fail("Migration/read/backup attempted a model call")

        monkeypatch.setattr(llm, "complete", no_model)
        monkeypatch.setattr(llm, "complete_result", no_model)
        assert followups.fetch("paper", database=database) == 0
        with client.journal.transaction() as conn:
            recorded = dict(conn.execute("SELECT * FROM paper_later_outcomes").fetchone())
            portable = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
            ).fetchone()[0]
        original_bytes = path.read_bytes() if path.exists() else None
        if replace or queried == "unavailable":
            pdf(path, "Current primary B is distinct from the recorded source")
        reader = from_workspace(database, legacy_root=originals)
        document = reader.resolve("paper")
        assert document.available and not document.managed
        return SimpleNamespace(
            database=database,
            client=client,
            actions=ResearchOperations(client),
            blobs=blobs,
            document=document,
            reader=reader,
            path=path,
            recorded=recorded,
            original_bytes=original_bytes,
            portable=portable,
            bytes=path.read_bytes(),
            root=root,
        )

    return factory


def staged(fixture, **kwargs):
    from paper_daily import legacy_primary_migration as migration

    return migration.prepare(
        fixture.actions, fixture.document, fixture.blobs, request_id=str(uuid4()), **kwargs
    )


def run(prepared):
    from paper_daily.legacy_primary_migration import run

    return run(prepared)


def test_default_attach_stays_intent_only_and_backup_preserves_legacy_sources(make, tmp_path):
    fixture = make()
    manifest = sync_document_actions.stage_file(fixture.blobs, fixture.path)
    receipt = fixture.actions.attach_document(
        fixture.portable, manifest, store=fixture.blobs, request_id="default-attach"
    )
    with fixture.client.journal.transaction() as conn:
        assert desired_document(conn, fixture.portable)["operation_id"] == receipt["operation_id"]
        assert applied_document(conn, fixture.portable) is None
    before = dump(fixture.database)
    archive = tmp_path / "unmigrated.zip"
    manifest = sync_recovery.create(fixture.database, archive, blob_store=fixture.blobs)
    assert sync_recovery.inspect(archive) == manifest
    with zipfile.ZipFile(archive) as package:
        for content in (fixture.original_bytes, fixture.bytes):
            assert package.read("objects/" + hashlib.sha256(content).hexdigest()) == content
    sync_recovery.restore_detached(archive, tmp_path / "restored")
    assert (tmp_path / "restored/papers.db").is_file()
    assert dump(fixture.database) == before
    assert fixture.path.read_bytes() == fixture.bytes
    unexpected = fixture.root / "pdf/unrelated.txt"
    unexpected.write_text("Unrepresented research", encoding="utf-8")
    with pytest.raises(sync_recovery.RecoveryError, match="Legacy research files"):
        sync_recovery.create(
            fixture.database, tmp_path / "incomplete.zip", blob_store=fixture.blobs
        )
    assert not (tmp_path / "incomplete.zip").exists()


@pytest.mark.parametrize("queried", ["A", "unavailable"])
def test_explicit_migration_full_backup_and_fresh_editable_receiver(make, tmp_path, queried):
    fixture = make(queried)
    before = fixture.database.read_bytes()
    prepared = staged(fixture)
    assert fixture.database.read_bytes() == before
    result = run(prepared)
    assert result["status"] == "migrated" and result["action"]["operation_id"]
    assert fixture.path.read_bytes() == fixture.bytes
    current = from_workspace(fixture.database).resolve("paper")
    assert current.managed and current.available and current.sha256 == fixture.document.sha256
    with fixture.client.journal.transaction() as conn:
        assert desired_document(conn, fixture.portable) == applied_document(conn, fixture.portable)
        assert (
            dict(conn.execute("SELECT * FROM paper_later_outcomes").fetchone()) == fixture.recorded
        )
        assert not outcomes.settled(conn, "paper")
    archive = tmp_path / "complete.zip"
    sync_recovery.create(fixture.database, archive, blob_store=fixture.blobs)
    sync_recovery.restore_detached(archive, tmp_path / "detached")
    service = RecoveryAdoptionService(tmp_path / "detached/papers.db")
    inspection = service.inspect()
    assert inspection.report["supported"], inspection.report["blockers"]
    report = service.prepare(
        inspection,
        tmp_path / "editable",
        backup_output=tmp_path / "editable.zip",
        request_id=str(uuid4()),
    )
    assert (
        report["status"] == "prepared_for_review"
        and not report["adopted"]
        and not report["uploaded"]
    )
    with closing(sqlite3.connect(report["database"])) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM paper_later_outcomes").fetchone())
        assert json.loads(row["body_json"]) == json.loads(fixture.recorded["body_json"])
        assert not outcomes.settled(conn, "paper")
        if queried == "A":
            from paper_daily.sync_source_files import resolved

            portable = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
            ).fetchone()[0]
            retained = resolved(conn, portable, row["document_hash"])
            assert retained.read_bytes() == fixture.original_bytes
            assert hashlib.sha256(retained.read_bytes()).hexdigest() == row["document_hash"]
    recovered = from_workspace(report["database"]).resolve("paper")
    assert recovered.available and recovered.managed and recovered.sha256 == fixture.document.sha256
    if queried == "A":
        assert fixture.recorded["document_hash"] != recovered.sha256
    else:
        assert fixture.recorded["document_hash"] is None
    sync_recovery.inspect(report["backup"])


def test_same_source_remains_settled_and_retry_is_single(make):
    fixture = make(replace=False)
    prepared = staged(fixture)
    first = run(prepared)
    pending = fixture.client.journal.pending()
    assert run(prepared) == first and fixture.client.journal.pending() == pending
    with fixture.client.journal.transaction() as conn:
        assert outcomes.settled(conn, "paper")
        assert conn.execute("SELECT COUNT(*) FROM research_action_receipts").fetchone()[0] == 1
    assert sum(op["entity_type"] == "paper_document" for op in pending) == 1
    assert fixture.path.read_bytes() == fixture.bytes


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "native",
        "binding",
        "parent",
        "target",
        "reader-close",
        "reader-root",
        "lifetime",
        "cancel",
    ],
)
def test_pending_migration_refuses_changed_scope_without_adopting_new_authority(make, change):
    fixture = make()
    live = Event()
    live.set()
    ticket = Ticket()
    prepared = staged(fixture, current=live.is_set, ticket=ticket)
    if change == "source":
        pdf(fixture.path, "Different current C after selected B")
    elif change == "native":
        old = (fixture.database.stat().st_dev, fixture.database.stat().st_ino)
        replacement = fixture.database.with_suffix(".replacement")
        shutil.copyfile(fixture.database, replacement)
        os.replace(replacement, fixture.database)
        assert (fixture.database.stat().st_dev, fixture.database.stat().st_ino) != old
    elif change == "binding":
        with closing(sqlite3.connect(fixture.database)) as conn, conn:
            conn.execute("UPDATE research_capture_binding SET device='other-device'")
    elif change == "parent":
        recreate_parent(fixture)
    elif change == "target":
        manifest = sync_document_actions.stage_file(fixture.blobs, fixture.path)
        fixture.actions.attach_document(
            fixture.portable, manifest, store=fixture.blobs, request_id="other-target"
        )
    elif change == "reader-close":
        fixture.reader.close()
    elif change == "reader-root":
        other = fixture.root / "different-pdf"
        other.mkdir()
        (other / "paper.pdf").write_bytes(fixture.bytes)
        fixture.reader.legacy_root = other
    elif change == "lifetime":
        live.clear()
    else:
        ticket.cancel()
    before = dump(fixture.database)
    with pytest.raises((ValueError, Cancelled)):
        run(prepared)
    assert dump(fixture.database) == before


@pytest.mark.parametrize("change", ["cancel", "source", "lifetime", "late-sql"])
def test_final_publication_failure_rolls_back_all_migration_state_and_retry(
    make, monkeypatch, change
):
    fixture = make()
    live = Event()
    live.set()
    ticket = Ticket()
    prepared = staged(fixture, current=live.is_set, ticket=ticket)
    before = dump(fixture.database)
    if change == "cancel":
        real = sync_document_actions.verify_document

        def verify(*args):
            result = real(*args)
            ticket.cancel()
            return result

        monkeypatch.setattr(sync_document_actions, "verify_document", verify)
    else:
        real = fixture.client.journal.apply_in

        def apply(conn, operation, writer):
            result = real(conn, operation, writer)
            if operation["entity_type"] == "paper_document":
                if change == "source":
                    pdf(fixture.path, "Source C changed during final publication")
                elif change == "lifetime":
                    live.clear()
                else:
                    raise OSError("Fixture late SQL failure")
            return result

        monkeypatch.setattr(fixture.client.journal, "apply_in", apply)
    with pytest.raises((ValueError, Cancelled, OSError)):
        run(prepared)
    assert dump(fixture.database) == before and not ticket.published
    if change == "late-sql":
        monkeypatch.setattr(fixture.client.journal, "apply_in", real)
        first = run(prepared)
        assert run(prepared) == first
        assert fixture.path.read_bytes() == fixture.bytes


def test_publication_wins_concurrent_cancel_only_after_commit(make, monkeypatch):
    from paper_daily import legacy_primary_migration as migration

    fixture = make()
    ticket = Ticket()
    prepared = staged(fixture, ticket=ticket)
    real = migration.bind_verified_document
    attempted, finished = Event(), Event()

    def cancel():
        attempted.set()
        ticket.cancel()
        finished.set()

    thread = Thread(target=cancel)

    def bind(*args):
        thread.start()
        assert attempted.wait(5)
        assert not finished.is_set()
        return real(*args)

    monkeypatch.setattr(migration, "bind_verified_document", bind)
    result = run(prepared)
    thread.join(5)
    assert finished.is_set() and not thread.is_alive()
    assert result["status"] == "migrated" and ticket.published and not ticket.cancelled
    with fixture.client.journal.transaction() as conn:
        assert desired_document(conn, fixture.portable) == applied_document(conn, fixture.portable)


def test_checkpoint_and_unrelated_global_path_are_not_new_workspace_authority(
    make, monkeypatch, tmp_path
):
    fixture = make()
    prepared = staged(fixture)
    with closing(sqlite3.connect(fixture.database)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    other = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(other)) as conn:
        conn.execute("CREATE TABLE marker(value)")
    before = other.read_bytes()
    monkeypatch.setattr(store, "DB_PATH", other)
    assert run(prepared)["status"] == "migrated"
    assert other.read_bytes() == before


def test_retry_does_not_revive_newer_target(make):
    fixture = make()
    prepared = staged(fixture)
    run(prepared)
    old = fixture.client.journal.pending()
    path = fixture.root / "C.pdf"
    pdf(path, "A newer explicit managed primary C")
    manifest = sync_document_actions.stage_file(fixture.blobs, path)
    fixture.actions.attach_document(
        fixture.portable, manifest, store=fixture.blobs, request_id="newer-C"
    )
    before = dump(fixture.database)
    with pytest.raises(ValueError):
        run(prepared)
    assert dump(fixture.database) == before and fixture.client.journal.pending() != old


@pytest.mark.parametrize("change", ["source", "parent", "native", "target", "registration"])
def test_change_while_blob_verifies_is_not_recaptured_as_new_authority(make, monkeypatch, change):
    from paper_daily.document_reader import register_document_paths

    fixture = make()
    prepared = staged(fixture)
    original = sync_document_actions.verify_document
    state = {}

    def verify(*args):
        result = original(*args)
        if not state:
            state["started"] = True
            if change == "source":
                pdf(fixture.path, "A changed source before final admission")
            elif change == "parent":
                recreate_parent(fixture)
            elif change == "native":
                old = (fixture.database.stat().st_dev, fixture.database.stat().st_ino)
                replacement = fixture.database.with_suffix(".replacement")
                shutil.copyfile(fixture.database, replacement)
                os.replace(replacement, fixture.database)
                assert (fixture.database.stat().st_dev, fixture.database.stat().st_ino) != old
            elif change == "target":
                fixture.actions.attach_document(
                    fixture.portable,
                    prepared._manifest,
                    store=fixture.blobs,
                    request_id="other-during-verify",
                )
            else:
                with fixture.client.journal.transaction() as conn:
                    register_document_paths(
                        conn,
                        workspace_id="workspace",
                        blob_root=fixture.blobs.root,
                        legacy_root=fixture.path.parent,
                        projection_root=fixture.root / "different-reader",
                    )
            state["expected"] = dump(fixture.database)
        return result

    monkeypatch.setattr(sync_document_actions, "verify_document", verify)
    with pytest.raises(ValueError):
        run(prepared)
    assert dump(fixture.database) == state["expected"]


def test_same_pdf_and_bibliography_do_not_merge_distinct_paper_owners(make):
    from paper_daily import legacy_primary_migration as migration

    fixture = make()
    run(staged(fixture))
    with store.connect() as conn:
        store.upsert_papers(
            conn, [dict(id="second", title="Paper", venue="Fixture", year=2026, source="fixture")]
        )
    second_path = fixture.path.parent / "second.pdf"
    second_path.write_bytes(fixture.bytes)
    second = from_workspace(fixture.database).resolve("second")
    assert second.available and not second.managed and second.sha256 == fixture.document.sha256
    result = migration.run(
        migration.prepare(fixture.actions, second, fixture.blobs, request_id=str(uuid4()))
    )
    assert result["paper_id"] == "second"
    with fixture.client.journal.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 2
        rows = conn.execute("SELECT target FROM research_document_applied").fetchall()
        assert len(rows) == 2
        assert len({json.loads(row[0])["paper_id"] for row in rows}) == 2
        assert {json.loads(row[0])["sha256"] for row in rows} == {fixture.document.sha256}


def test_same_prepared_job_is_single_flight_while_real_verification_is_held(make, monkeypatch):
    fixture = make()
    prepared = staged(fixture)
    original = sync_document_actions.verify_document
    entered, release = Event(), Event()
    results, errors = [], []

    def verify(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(sync_document_actions, "verify_document", verify)

    def worker():
        try:
            results.append(run(prepared))
        except Exception as error:
            errors.append(error)

    thread = Thread(target=worker)
    thread.start()
    assert entered.wait(5)
    try:
        with pytest.raises(ValueError, match="already running"):
            run(prepared)
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and errors == [] and len(results) == 1
    assert (
        sum(op["entity_type"] == "paper_document" for op in fixture.client.journal.pending()) == 1
    )


@pytest.mark.parametrize("change", ["reader-root", "reader-generation"])
def test_reader_change_during_maintained_staging_cannot_be_adopted(make, monkeypatch, change):
    from paper_daily import legacy_primary_migration as migration

    fixture = make()
    original = migration.stage_file
    staged_bytes = []

    def stage(store, path):
        manifest = original(store, path)
        staged_bytes.append(manifest.sha256)
        if change == "reader-root":
            other = fixture.root / "staging-other-root"
            other.mkdir()
            (other / "paper.pdf").write_bytes(fixture.bytes)
            fixture.reader.legacy_root = other
        else:
            fixture.reader.invalidate()
        return manifest

    monkeypatch.setattr(migration, "stage_file", stage)
    before = dump(fixture.database)
    with pytest.raises(ValueError):
        staged(fixture)
    assert staged_bytes == [fixture.document.sha256]
    assert dump(fixture.database) == before and fixture.path.read_bytes() == fixture.bytes
