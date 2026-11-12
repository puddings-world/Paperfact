"""Worker-only discovery and explicit per-paper migration orchestration."""

import os
import shutil
import sqlite3
from contextlib import closing

import pytest
from test_legacy_primary_migration import dump
from test_legacy_primary_migration import make as make_fixture

from paper_daily.desktop.window_workspace import WindowWorkspace
from paper_daily.workspace_primary_migration import MigrationSource, PrimaryMigration
from paper_daily.workspace_service import WorkspaceChanged, WorkspaceService

make = make_fixture


def controller(fixture):
    source = MigrationSource.capture(WindowWorkspace.capture(), fixture.path.parent)
    service = WorkspaceService(fixture.database)
    service.status()
    return PrimaryMigration(service, source)


def test_catalog_reads_actual_paper_without_research_or_store_writes(make):
    fixture = make()
    before = dump(fixture.database)
    index = (fixture.blobs.root / "index.sqlite").read_bytes()
    worker = controller(fixture)
    result = worker.catalog()
    assert [(item.paper_id, item.title, item.status) for item in result.items] == [
        ("paper", "Paper", "legacy")
    ]
    assert result.bootstrap and result.after is None
    assert dump(fixture.database) == before
    assert (fixture.blobs.root / "index.sqlite").read_bytes() == index


def test_source_capture_and_current_are_only_native_metadata(make, monkeypatch):
    fixture = make()
    owner = WindowWorkspace.capture()

    def forbidden(*args, **kwargs):
        raise AssertionError("Native caller admission performed SQL or hashing")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    source = MigrationSource.capture(owner, fixture.path.parent)
    assert source.current() and source.workspace_current()
    owner.close()
    assert not source.current() and not source.workspace_current()


def test_source_root_absence_does_not_invalidate_ordinary_workspace(make):
    fixture = make()
    source = MigrationSource.capture(WindowWorkspace.capture(), fixture.root / "missing")
    assert source.workspace_current() and not source.current()
    (fixture.root / "missing").mkdir()
    assert not source.current(), "Later creation cannot become the old captured root"


def test_actual_database_replacement_rejects_without_reading_replacement(make, monkeypatch):
    fixture = make()
    worker = controller(fixture)
    replacement = fixture.database.with_suffix(".replacement")
    shutil.copyfile(fixture.database, replacement)
    old = worker.source.identity
    os.replace(replacement, fixture.database)
    assert (fixture.database.stat().st_dev, fixture.database.stat().st_ino) != old

    def forbidden(*args, **kwargs):
        raise AssertionError("Stale operation opened replacement database")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    with pytest.raises(WorkspaceChanged):
        worker.catalog()


def test_actual_root_replacement_does_not_adopt_new_root(make):
    fixture = make()
    worker = controller(fixture)
    fixture.path.parent.rename(fixture.root / "old-pdf")
    fixture.path.parent.mkdir()
    assert not worker.current()
    with pytest.raises(WorkspaceChanged):
        worker.catalog()


def test_registered_store_binding_is_observed_not_rewritten(make):
    fixture = make()
    worker = controller(fixture)
    with closing(sqlite3.connect(fixture.blobs.root / "index.sqlite")) as conn, conn:
        conn.execute("UPDATE transfer_binding SET device='another-device'")
    before = dump(fixture.database)
    with pytest.raises(ValueError, match="another workspace/device"):
        worker.catalog()
    assert dump(fixture.database) == before
    with closing(sqlite3.connect(fixture.blobs.root / "index.sqlite")) as conn:
        assert conn.execute("SELECT device FROM transfer_binding").fetchone()[0] == "another-device"


def test_cancel_before_worker_admission_is_not_reset_by_worker(make):
    from paper_daily.workspace_service import Cancelled

    fixture = make()
    worker = controller(fixture)
    worker.cancel()
    with pytest.raises(Cancelled):
        worker.catalog()
    worker.reset()
    assert worker.catalog().items[0].paper_id == "paper"


@pytest.mark.parametrize("queried", ["A", "unavailable"])
def test_explicit_stage_confirm_fresh_review_backup_and_editable_restore(make, tmp_path, queried):
    from uuid import uuid4

    from paper_daily import sync_recovery
    from paper_daily.document_reader import from_workspace
    from paper_daily.recovery_adoption import RecoveryAdoptionService
    from paper_daily.sync_source_files import resolved
    from paper_daily.workspace_service import Ticket

    fixture = make(queried)
    worker = controller(fixture)
    catalog = worker.catalog()
    pending = fixture.client.journal.pending()
    plan = worker.stage(catalog, ("paper",))
    assert worker.plan_current(plan)
    assert plan.items[0].sha256 == fixture.document.sha256
    assert fixture.client.journal.pending() == pending
    assert (
        not from_workspace(fixture.database, legacy_root=fixture.path.parent)
        .resolve("paper")
        .managed
    )
    result = worker.commit(plan)
    assert [item.paper_id for item in result.committed] == ["paper"]
    assert result.remaining == () and result.outcome == "complete"
    assert not list(tmp_path.glob("*.zip")), "Migration must not auto-create a backup"
    service, status = worker.refresh_readiness()
    assert status["path"] == str(fixture.database.parent)
    assert not worker.needs_refresh and worker.service is service
    archive = tmp_path / "new-backup.zip"
    assert service.backup(archive, Ticket())["path"] == str(archive)
    sync_recovery.restore_detached(archive, tmp_path / "detached")
    adoption = RecoveryAdoptionService(tmp_path / "detached/papers.db")
    inspection = adoption.inspect()
    assert inspection.report["supported"], inspection.report["blockers"]
    report = adoption.prepare(
        inspection,
        tmp_path / "editable",
        backup_output=tmp_path / "editable.zip",
        request_id=str(uuid4()),
    )
    assert report["status"] == "prepared_for_review" and not report["uploaded"]
    current = from_workspace(report["database"]).resolve("paper")
    assert current.managed and current.available and current.sha256 == fixture.document.sha256
    with closing(sqlite3.connect(report["database"])) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM paper_later_outcomes").fetchone())
        assert row["body_json"] == fixture.recorded["body_json"]
        if queried == "A":
            paper = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
            ).fetchone()[0]
            assert (
                resolved(conn, paper, row["document_hash"]).read_bytes() == fixture.original_bytes
            )
        else:
            assert row["document_hash"] is None
    assert fixture.path.read_bytes() == fixture.bytes


@pytest.mark.parametrize(
    "selected",
    [(), ("paper", "paper"), ["paper"], tuple(str(i) for i in range(17))],
    ids=["empty", "duplicate", "mutable", "oversize"],
)
def test_selection_refuses_before_setup_or_source_writes(make, selected):
    fixture = make()
    worker = controller(fixture)
    catalog = worker.catalog()
    before = dump(fixture.database)
    with pytest.raises(ValueError):
        worker.stage(catalog, selected)
    assert dump(fixture.database) == before
    assert fixture.path.read_bytes() == fixture.bytes


def test_catalog_has_no_ddl_but_explicit_stage_initializes_missing_ledger(make):
    fixture = make()
    with closing(sqlite3.connect(fixture.database)) as conn, conn:
        conn.execute("DROP TABLE research_action_receipts")
    worker = controller(fixture)
    before = dump(fixture.database)
    catalog = worker.catalog()
    assert dump(fixture.database) == before
    pending = fixture.client.journal.pending()
    plan = worker.stage(catalog, ("paper",))
    assert worker.plan_current(plan) and worker.needs_refresh
    with closing(sqlite3.connect(fixture.database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_action_receipts").fetchone()[0] == 0
    assert fixture.client.journal.pending() == pending


@pytest.mark.parametrize(
    "column", ["request_IFNOTEXISTSid", "wrong"], ids=["normalizer-substring", "wrong-column"]
)
def test_explicit_setup_refuses_foreign_ledger_without_replacing_it(make, column):
    from paper_daily.sync_operations import ResearchOperations

    fixture = make()
    with closing(sqlite3.connect(fixture.database)) as conn, conn:
        conn.execute("DROP TABLE research_action_receipts")
        conn.execute(
            f"CREATE TABLE research_action_receipts ({column} TEXT PRIMARY KEY,"
            "fingerprint TEXT NOT NULL,result TEXT NOT NULL)"
        )
    before = dump(fixture.database)
    expected = (fixture.database, (fixture.database.stat().st_dev, fixture.database.stat().st_ino))
    with pytest.raises(ValueError, match="ledger"):
        ResearchOperations(fixture.client, expected=expected)
    assert dump(fixture.database) == before


def test_setup_rejects_actual_native_replacement_before_open(make):
    from paper_daily.sync_operations import ResearchOperations

    fixture = make()
    expected = (fixture.database, (fixture.database.stat().st_dev, fixture.database.stat().st_ino))
    replacement = fixture.database.with_suffix(".replacement")
    shutil.copyfile(fixture.database, replacement)
    os.replace(replacement, fixture.database)
    assert (fixture.database.stat().st_dev, fixture.database.stat().st_ino) != expected[1]
    before = dump(fixture.database)
    with pytest.raises(ValueError, match="replaced"):
        ResearchOperations(fixture.client, expected=expected)
    assert dump(fixture.database) == before


def test_setup_checks_actual_connection_path_not_only_journal_path(make, monkeypatch):
    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_journal import Journal
    from paper_daily.sync_operations import ResearchOperations
    from paper_daily.sync_research import research_writer

    fixture = make()
    other = fixture.database.with_name("other.db")
    shutil.copyfile(fixture.database, other)
    with closing(sqlite3.connect(other)) as conn, conn:
        conn.execute("DROP TABLE research_action_receipts")
    journal = Journal.attach_existing(
        fixture.database, workspace_id="workspace", device_id="desktop"
    )
    monkeypatch.setattr(journal, "_connect", lambda: sqlite3.connect(other))
    client = SyncClient.attach_existing(journal, research_writer)
    expected = (fixture.database, (fixture.database.stat().st_dev, fixture.database.stat().st_ino))
    before = dump(other)
    with pytest.raises(ValueError, match="another database"):
        ResearchOperations(client, expected=expected)
    assert dump(other) == before


def test_changed_reviewed_paper_refuses_before_preparation(make):
    from paper_daily import store

    fixture = make()
    worker = controller(fixture)
    catalog = worker.catalog()
    with store.connect() as conn:
        conn.execute("UPDATE papers SET title='Changed study' WHERE id='paper'")
    before = dump(fixture.database)
    with pytest.raises(WorkspaceChanged, match="paper or parent"):
        worker.stage(catalog, ("paper",))
    assert dump(fixture.database) == before


def add_papers(fixture):
    from test_legacy_primary_migration import pdf

    from paper_daily import store

    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                dict(id=value, title=value, venue="Fixture", year=2026, source="fixture")
                for value in ("second", "third")
            ],
        )
    for identity in ("second", "third"):
        pdf(fixture.path.parent / f"{identity}.pdf", f"Independent original for {identity}")


def registered_batch(fixture):
    worker = controller(fixture)
    catalog = worker.catalog()
    plan = worker.stage(catalog, ("paper",))
    assert len(worker.commit(plan).committed) == 1
    worker.refresh_readiness()
    add_papers(fixture)
    worker.reset()
    catalog = worker.catalog()
    assert not catalog.bootstrap
    return worker, worker.stage(catalog, ("second", "third"))


def test_first_registration_requires_one_paper_then_explicit_second_review(make):
    fixture = make()
    add_papers(fixture)
    worker = controller(fixture)
    catalog = worker.catalog()
    before = dump(fixture.database)
    with pytest.raises(ValueError, match="one PDF first"):
        worker.stage(catalog, ("paper", "second"))
    assert dump(fixture.database) == before
    plan = worker.stage(catalog, ("paper",))
    assert len(worker.commit(plan).committed) == 1
    with pytest.raises(WorkspaceChanged, match="Refresh"):
        worker.catalog()
    worker.refresh_readiness()
    assert not worker.catalog().bootstrap


def test_batch_cancel_after_commit_reports_that_success_and_stops_remaining(make, monkeypatch):
    from paper_daily import legacy_primary_migration as migration
    from paper_daily.document_reader import from_workspace

    fixture = make()
    worker, plan = registered_batch(fixture)
    real = migration.run
    calls = []

    def commit_then_cancel(prepared):
        result = real(prepared)
        calls.append(result["paper_id"])
        worker.cancel()
        return result

    monkeypatch.setattr(migration, "run", commit_then_cancel)
    result = worker.commit(plan)
    assert calls == ["second"]
    assert result.outcome == "cancelled" and result.remaining == ("third",)
    assert [item.paper_id for item in result.committed] == ["second"]
    reader = from_workspace(fixture.database)
    assert reader.resolve("second").managed and not reader.resolve("third").managed
    worker.reset()
    worker.refresh_readiness()
    assert not worker.needs_refresh


def test_partial_failure_is_reported_and_retry_does_not_duplicate_committed_paper(
    make, monkeypatch
):
    from paper_daily import legacy_primary_migration as migration

    fixture = make()
    worker, plan = registered_batch(fixture)
    real = migration.run
    calls = []

    def fail_second(prepared):
        if calls:
            raise OSError("private fixture body")
        result = real(prepared)
        calls.append(result["paper_id"])
        return result

    monkeypatch.setattr(migration, "run", fail_second)
    result = worker.commit(plan)
    assert result.outcome == "failed" and result.remaining == ("third",)
    assert [item.paper_id for item in result.committed] == ["second"]
    monkeypatch.setattr(migration, "run", real)
    worker.reset()
    worker.refresh_readiness()
    catalog = worker.catalog()
    assert next(item.status for item in catalog.items if item.paper_id == "second") == "managed"
    retry = worker.stage(catalog, ("third",))
    assert [item.paper_id for item in worker.commit(retry).committed] == ["third"]
    with fixture.client.journal.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_action_receipts").fetchone()[0] == 3


def test_cancellation_after_explicit_setup_has_no_document_intent(make, monkeypatch):
    from paper_daily import legacy_primary_migration as migration
    from paper_daily.workspace_service import Cancelled

    fixture = make()
    worker = controller(fixture)
    catalog = worker.catalog()
    pending = fixture.client.journal.pending()
    real = migration.prepare

    def cancel_before_seal(*args, **kwargs):
        worker.cancel()
        return real(*args, **kwargs)

    monkeypatch.setattr(migration, "prepare", cancel_before_seal)
    with pytest.raises(Cancelled):
        worker.stage(catalog, ("paper",))
    assert fixture.client.journal.pending() == pending
    with fixture.client.journal.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_action_receipts").fetchone()[0] == 0
    assert fixture.path.read_bytes() == fixture.bytes
    assert worker.needs_refresh


def test_unrelated_paper_write_and_real_checkpoint_do_not_invalidate_selected_source(make):
    from paper_daily import store

    fixture = make()
    worker = controller(fixture)
    catalog = worker.catalog()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id="unrelated",
                    title="Unrelated paper",
                    venue="Fixture",
                    year=2026,
                    source="fixture",
                )
            ],
        )
    assert worker.catalog_current(catalog)
    plan = worker.stage(catalog, ("paper",))
    with closing(sqlite3.connect(fixture.database)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert worker.plan_current(plan), "A checkpoint is not a source/parent replacement"
    assert len(worker.commit(plan).committed) == 1


def test_changed_staged_source_is_refused_without_new_intent(make):
    from test_legacy_primary_migration import pdf

    fixture = make()
    worker = controller(fixture)
    plan = worker.stage(worker.catalog(), ("paper",))
    pending = fixture.client.journal.pending()
    pdf(fixture.path, "A newer local source after explicit staging")
    assert not worker.plan_current(plan)
    result = worker.commit(plan)
    assert not result.committed and result.remaining == ("paper",)
    assert result.outcome == "failed" and fixture.client.journal.pending() == pending


def test_guarded_setup_refuses_foreign_same_name_view_without_mutation(make):
    from paper_daily.sync_operations import ResearchOperations

    fixture = make()
    with closing(sqlite3.connect(fixture.database)) as conn, conn:
        conn.execute("DROP TABLE research_action_receipts")
        conn.execute("CREATE VIEW research_action_receipts AS SELECT 1 AS request_id")
    before = dump(fixture.database)
    expected = (fixture.database, (fixture.database.stat().st_dev, fixture.database.stat().st_ino))
    with pytest.raises(ValueError, match="schema"):
        ResearchOperations(fixture.client, expected=expected)
    assert dump(fixture.database) == before


def test_actual_outer_workspace_change_at_setup_commit_rolls_back_ledger(make, monkeypatch):
    from paper_daily import store, workspace_sync

    fixture = make()
    with closing(sqlite3.connect(fixture.database)) as conn, conn:
        conn.execute("DROP TABLE research_action_receipts")
    other = fixture.database.with_name("next-workspace.db")
    shutil.copyfile(fixture.database, other)
    before, other_before = dump(fixture.database), dump(other)
    worker = controller(fixture)
    catalog = worker.catalog()
    execute = workspace_sync._Connection.execute

    def change_after_create(conn, sql, *args):
        result = execute(conn, sql, *args)
        if sql.startswith("CREATE TABLE IF NOT EXISTS research_action_receipts"):
            monkeypatch.setattr(store, "DB_PATH", other)
        return result

    monkeypatch.setattr(workspace_sync._Connection, "execute", change_after_create)
    with pytest.raises(WorkspaceChanged):
        worker.stage(catalog, ("paper",))
    assert dump(fixture.database) == before
    assert dump(other) == other_before
    assert not worker.source.workspace_current()


def test_store_native_identity_is_not_recaptured_after_initial_binding_read(make, monkeypatch):
    fixture = make()
    worker = controller(fixture)
    initial = worker._context
    changed = []
    index = fixture.blobs.root / "index.sqlite"
    before = dump(fixture.database)

    def replace_after_observation():
        context = initial()
        if not changed:
            replacement = index.with_suffix(".replacement")
            with (
                closing(sqlite3.connect(index.as_uri() + "?mode=ro", uri=True)) as source,
                closing(sqlite3.connect(replacement)) as receiver,
            ):
                source.backup(receiver)
            os.replace(replacement, index)
            assert (index.stat().st_dev, index.stat().st_ino) != context[2]
            changed.append(True)
        return context

    monkeypatch.setattr(worker, "_context", replace_after_observation)
    with pytest.raises(WorkspaceChanged, match="File store was replaced"):
        worker.catalog()
    assert changed == [True] and dump(fixture.database) == before


@pytest.mark.parametrize("interference", ["registration", "binding"])
def test_readiness_rejects_exact_scope_change_inside_status(make, monkeypatch, interference):
    from paper_daily.document_reader import register_document_paths

    fixture = make()
    worker = controller(fixture)
    plan = worker.stage(worker.catalog(), ("paper",))
    assert len(worker.commit(plan).committed) == 1
    original_service = worker.service
    real = WorkspaceService.status
    actor = {}

    def changed(service, *args, **kwargs):
        with closing(sqlite3.connect(fixture.database)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if interference == "registration":
                register_document_paths(
                    conn,
                    workspace_id="workspace",
                    blob_root=fixture.blobs.root,
                    projection_root=fixture.root / "external-reader-projection",
                    legacy_root=fixture.path.parent,
                )
            else:
                # Controlled unsupported external rebinding, not protocol adoption.
                conn.execute("UPDATE research_sync_binding SET origin='external-device'")
        actor["database"] = dump(fixture.database)
        return real(service, *args, **kwargs)

    monkeypatch.setattr(WorkspaceService, "status", changed)
    with pytest.raises(ValueError):
        worker.refresh_readiness()
    assert worker.service is original_service and worker.needs_refresh
    assert dump(fixture.database) == actor["database"]
    assert fixture.path.read_bytes() == fixture.bytes
