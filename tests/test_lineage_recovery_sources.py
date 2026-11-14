"""Fresh originals from sealed recovery snapshots; source/history remain independent."""

import json
import sqlite3
import zipfile
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pytest
from lineage_package_fixture import lineage_archive as lineage_archive
from test_lineage_jobs import work
from test_lineage_package_publish import apply
from test_lineage_package_publish import incoming as incoming

from paper_daily import lineage_import_originals, lineage_sets, store, sync_recovery
from paper_daily import lineage_package_publish as publisher
from paper_daily import lineage_package_targets as targets
from paper_daily import lineage_recovery_sources as sources
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import observe_owner
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.workspace_service import Cancelled, Ticket


@pytest.fixture
def recovered(incoming, tmp_path):
    work(apply, incoming)
    with closing(sqlite3.connect(incoming[0])) as conn, conn:
        for identity, title in conn.execute("SELECT id,title FROM papers").fetchall():
            conn.execute(
                "UPDATE papers SET title_key=? WHERE id=?", (store.title_key(title), identity)
            )
    package = tmp_path / "recovery.zip"
    sync_recovery.create(incoming[0], package)
    root = tmp_path / "detached"
    sync_recovery.restore_detached(package, root)
    service = RecoveryAdoptionService(root / "papers.db")
    inspection = service.inspect()
    target = tmp_path / "private-baseline" / "papers.db"
    target.parent.mkdir()
    with closing(sqlite3.connect(target)) as conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.commit()
    return incoming, service, inspection, target


def copy_current(conn, inspection):
    value = json.loads(inspection._snapshot)
    for table in ("papers", "paper_lineage_sets"):
        if table == "paper_lineage_sets":
            conn.execute(lineage_sets.SCHEMA)
        for row in value["tables"].get(table, []):
            columns = list(row)
            conn.execute(
                "INSERT INTO "
                + table
                + "("
                + ",".join(columns)
                + ") VALUES("
                + ",".join("?" for _ in columns)
                + ")",
                [row[c] for c in columns],
            )


def test_exact_fresh_originals_commit_and_read_without_changing_detached_source(
    recovered, monkeypatch
):
    original, service, inspection, destination = recovered
    before = service.database.read_bytes()
    prepared = work(sources.prepare, service, inspection, destination)

    def publish():
        from paper_daily import local_source_owners, research_evidence

        def unexpected(*_args, **_kwargs):
            pytest.fail("Original PDF reads and parsing must finish before the SQL phase")

        with monkeypatch.context() as patch, closing(sqlite3.connect(destination)) as conn:
            patch.setattr(local_source_owners, "_read_pdf", unexpected)
            patch.setattr(research_evidence, "_extract", unexpected)
            conn.execute("BEGIN IMMEDIATE")
            copy_current(conn, inspection)
            assert sources.stage_in(conn, prepared) == dict(lineage_reports=1, batches=1)
            assert sources.stage_in(conn, prepared) == dict(lineage_reports=1, batches=1)
            with closing(sqlite3.connect(destination)) as outside:
                assert outside.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
            conn.commit()

    work(publish)
    assert service.database.read_bytes() == before
    owner = observe_owner(
        destination, "receiver-focal", expected_native=generation._identity(destination)
    )
    row = lineage_sets.saved(destination, owner.paper_id)[0]
    body = lineage_sets.decode(row["body_json"])
    for source in body["report"]["sources"]:
        snapshot = work(lineage_import_originals.prepare, owner, row, source["id"])
        assert lineage_import_originals.for_delivery(snapshot, owner, row, source["id"]) == next(
            data
            for path, data in original[4].files
            if path.endswith(source["document_hash"] + ".pdf")
        )
    with closing(sqlite3.connect(destination)) as conn:
        native = json.loads(
            conn.execute("SELECT body_json FROM research_lineage_imports").fetchone()[0]
        )
        assert native["database_identity"] == generation._identity(destination)
        assert native["database_identity"] != original[1]
        assert {p["parent_lifecycle"] for p in native["parents"]}.isdisjoint(
            {
                p["parent_lifecycle"]
                for p in publisher.validate_record(
                    dict(
                        request_id=original[5]._request,
                        body_json=json.loads(inspection._snapshot)["tables"][publisher.TABLE][0][
                            "body_json"
                        ],
                    )
                )["parents"]
            }
        )
    assert inspection.report["supported"]
    result = work(
        service.prepare,
        inspection,
        destination.parent / "published",
        backup_output=destination.parent / "published.zip",
        request_id=str(uuid4()),
    )
    assert result["editable_copy"] and not result["uploaded"]
    assert lineage_sets.saved(result["database"], owner.paper_id) == [row]
    assert (
        sync_recovery.inspect(destination.parent / "published.zip")["workspace_id"]
        == result["workspace_id"]
    )
    assert service.database.read_bytes() == before


@pytest.mark.parametrize("change", ["paper", "science", "forged", "cancel", "source", "binding"])
def test_stale_or_cancelled_staging_never_commits_caller_research_or_source_grants(
    recovered, change
):
    _original, service, inspection, destination = recovered
    prepared = work(sources.prepare, service, inspection, destination)

    def run():
        with closing(sqlite3.connect(destination)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            copy_current(conn, inspection)
            selected = prepared
            ticket = Ticket()
            if change == "paper":
                conn.execute(
                    "UPDATE papers SET title='Changed destination' WHERE id='receiver-prior'"
                )
            elif change == "science":
                conn.execute("UPDATE paper_lineage_sets SET written_at='2026-10-01T00:00:00+00:00'")
            elif change == "forged":
                selected = replace(prepared, _digest="0" * 64)
            elif change == "cancel":
                ticket.cancel()
            elif change == "source":
                digest = next((service.root / "objects").iterdir())
                digest.write_bytes(b"changed original after source preparation")
            else:
                conn.execute("CREATE TABLE paperfact_sync_identity(workspace TEXT,device TEXT)")
                conn.execute("INSERT INTO paperfact_sync_identity VALUES('bound','fixture')")
            before = list(conn.iterdump())
            expected_error = Cancelled if change == "cancel" else (ValueError, OSError)
            with pytest.raises(expected_error):
                sources.stage_in(conn, selected, ticket=ticket)
            assert conn.in_transaction and list(conn.iterdump()) == before
            conn.rollback()
        with closing(sqlite3.connect(destination)) as conn:
            assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0

    work(run)


def test_recovery_source_cannot_be_its_own_destination_and_fake_inspection_refuses(recovered):
    _original, service, inspection, destination = recovered
    before = service.database.read_bytes()
    with pytest.raises(ValueError, match="independent"):
        work(sources.prepare, service, inspection, service.database)
    with pytest.raises(ValueError, match="native service inspection"):
        work(sources.prepare, service, object(), destination)
    assert service.database.read_bytes() == before


def test_changed_workspace_before_preparation_refuses_without_native_original_grants(recovered):
    _original, service, inspection, destination = recovered
    service.current_path = lambda: destination
    with pytest.raises(ValueError, match="workspace changed"):
        work(sources.prepare, service, inspection, destination)
    assert not (destination.parent / "pdf").exists()


def test_rollback_leaves_no_fresh_parent_or_original_authority(recovered):
    _original, service, inspection, destination = recovered
    prepared = work(sources.prepare, service, inspection, destination)

    def run():
        with closing(sqlite3.connect(destination)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            copy_current(conn, inspection)
            sources.stage_in(conn, prepared)
            conn.rollback()
        with closing(sqlite3.connect(destination)) as conn:
            assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
            names = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert not names & {
                publisher.TABLE,
                "research_local_source_owners",
                "research_parent_lifecycle",
            }

    work(run)


def test_expired_selected_parent_requires_review_instead_of_automatic_fresh_authority(
    incoming, tmp_path
):
    work(apply, incoming)
    with closing(sqlite3.connect(incoming[0])) as conn, conn:
        row = conn.execute("SELECT * FROM papers WHERE id='receiver-prior'").fetchone()
        conn.execute("DELETE FROM papers WHERE id='receiver-prior'")
        conn.execute("INSERT INTO papers VALUES(" + ",".join("?" for _ in row) + ")", row)
    archive = tmp_path / "expired.zip"
    sync_recovery.create(incoming[0], archive)
    root = tmp_path / "expired-detached"
    sync_recovery.restore_detached(archive, root)
    service = RecoveryAdoptionService(root / "papers.db")
    inspection = service.inspect()
    target = tmp_path / "expired-target" / "papers.db"
    target.parent.mkdir()
    with closing(sqlite3.connect(target)) as conn:
        conn.executescript(store.SCHEMA)
    with pytest.raises(ValueError, match="obsolete"):
        work(sources.prepare, service, inspection, target)
    assert not (target.parent / "pdf").exists()


@pytest.mark.parametrize("failure", ["error", "cancel"])
def test_two_batches_fail_atomically_and_can_retry_without_duplicate_native_actions(
    incoming, tmp_path, monkeypatch, failure
):

    with zipfile.ZipFile(incoming[0].parent / "import.zip") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        tables = json.loads(archive.read("tables.json"))
        files = {
            name: archive.read(name) for name in archive.namelist() if name.startswith("files/")
        }
    row = dict(tables["paper_lineage_sets"][0])
    body = lineage_sets.decode(row["body_json"])
    body["corpus_id"] = row["corpus_key"] = str(uuid4())
    row["body_json"] = lineage_sets.canonical(body)
    row["source_hash"] = lineage_sets.source_hash(body)
    tables["paper_lineage_sets"].append(row)
    manifest["lineage_sources"].extend(
        [dict(r, corpus_key=row["corpus_key"]) for r in list(manifest["lineage_sources"])]
    )
    path = tmp_path / "two.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("tables.json", json.dumps(tables))
        for name, data in files.items():
            archive.writestr(name, data)
    with zipfile.ZipFile(path) as archive:
        validated = work(targets.validate, archive, manifest, tables)
    staged = work(
        publisher.stage,
        incoming[0],
        validated,
        incoming[3],
        request_id=str(uuid4()),
        expected_native=incoming[1],
    )

    def seed():
        with closing(sqlite3.connect(incoming[0])) as conn:
            conn.execute("BEGIN IMMEDIATE")
            from test_lineage_package_transaction import seed_in

            seed_in(conn, incoming[2], incoming[3])
            observed = publisher.observe_in(conn, staged)
            publisher.publish_in(conn, staged, observed)
            conn.commit()

    work(seed)
    archived = tmp_path / "two-recovery.zip"
    sync_recovery.create(incoming[0], archived)
    root = tmp_path / "two-detached"
    sync_recovery.restore_detached(archived, root)
    service = RecoveryAdoptionService(root / "papers.db")
    inspection = service.inspect()
    target = tmp_path / "two-target" / "papers.db"
    target.parent.mkdir()
    with closing(sqlite3.connect(target)) as conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.commit()
    monkeypatch.setattr(sources, "MAX_BATCH_ROWS", 1)
    prepared = work(sources.prepare, service, inspection, target)
    assert len(prepared._stages) == 2
    publish = publisher.publish_in
    ticket = Ticket()
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            if failure == "cancel":
                ticket.cancel()
                ticket.check()
            raise ValueError("fixture second batch failure")
        return publish(*args, **kwargs)

    def run():
        with closing(sqlite3.connect(target)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            copy_current(conn, inspection)
            before = list(conn.iterdump())
            with monkeypatch.context() as patch:
                patch.setattr(publisher, "publish_in", fail_second)
                with pytest.raises(Cancelled if failure == "cancel" else ValueError):
                    sources.stage_in(conn, prepared, ticket=ticket)
            assert list(conn.iterdump()) == before and conn.in_transaction
            assert sources.stage_in(conn, prepared) == dict(lineage_reports=2, batches=2)
            assert sources.stage_in(conn, prepared) == dict(lineage_reports=2, batches=2)
            assert conn.execute("SELECT COUNT(*) FROM research_lineage_imports").fetchone()[0] == 2
            assert (
                conn.execute("SELECT COUNT(*) FROM research_local_source_owners").fetchone()[0] == 6
            )
            conn.rollback()

    work(run)


def test_generated_unbound_report_gets_fresh_import_provenance_without_faking_ai(
    tmp_path, monkeypatch
):
    from test_lineage_recovery import published
    from test_research_lineage import corpus

    sender = tmp_path / "generated-source"
    sender.mkdir()
    data = corpus.__wrapped__(sender)
    published(data, monkeypatch)
    archive = tmp_path / "generated.zip"
    sync_recovery.create(data[0], archive)
    root = tmp_path / "generated-detached"
    sync_recovery.restore_detached(archive, root)
    service = RecoveryAdoptionService(root / "papers.db")
    inspection = service.inspect()
    target = tmp_path / "generated-target" / "papers.db"
    target.parent.mkdir()
    with closing(sqlite3.connect(target)) as conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.commit()
    prepared = work(sources.prepare, service, inspection, target)

    def run():
        with closing(sqlite3.connect(target)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            copy_current(conn, inspection)
            assert sources.stage_in(conn, prepared)["lineage_reports"] == 1
            names = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert not names & {"research_generation_requests", "research_lineage_publications"}
            conn.commit()

    work(run)
    owner = observe_owner(target, "focal", expected_native=generation._identity(target))
    row = lineage_sets.saved(target, "focal")[0]
    selected = lineage_sets.decode(row["body_json"])["report"]["sources"][0]
    snapshot = work(lineage_import_originals.prepare, owner, row, selected["id"])
    assert (
        lineage_import_originals.for_delivery(snapshot, owner, row, selected["id"])
        == (data[1] / "focal.pdf").read_bytes()
    )


def test_cancelled_preparation_and_replaced_destination_cannot_gain_sources(recovered):
    import shutil

    _original, service, inspection, destination = recovered
    ticket = Ticket()
    ticket.cancel()
    with pytest.raises(Cancelled):
        work(sources.prepare, service, inspection, destination, ticket=ticket)
    assert not (destination.parent / "pdf").exists()
    prepared = work(sources.prepare, service, inspection, destination)
    replacement = destination.with_name("replacement.db")
    shutil.copyfile(destination, replacement)
    replacement.replace(destination)

    def run():
        with closing(sqlite3.connect(destination)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            copy_current(conn, inspection)
            before = list(conn.iterdump())
            with pytest.raises(ValueError, match="destination changed"):
                sources.stage_in(conn, prepared)
            assert list(conn.iterdump()) == before and conn.in_transaction
            conn.rollback()

    work(run)
