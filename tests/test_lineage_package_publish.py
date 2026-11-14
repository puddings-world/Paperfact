"""Real off-lock byte publication and atomic native import receipts; no live wiring."""

import json
import sqlite3
import zipfile
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pytest
from lineage_package_fixture import copy_archive
from lineage_package_fixture import lineage_archive as lineage_archive
from test_lineage_jobs import work
from test_lineage_package_transaction import seed_in

from paper_daily import lineage_package_publish as publisher
from paper_daily import lineage_package_targets as targets
from paper_daily import (
    lineage_sets,
    local_source_owners,
    research_generation,
    source_snapshots,
    store,
)
from paper_daily.research_lifecycle import ensure_lifecycle


@pytest.fixture
def incoming(lineage_archive, tmp_path):
    manifest, tables = copy_archive(lineage_archive, tmp_path / "import.zip")
    with zipfile.ZipFile(tmp_path / "import.zip") as archive:
        validated = work(targets.validate, archive, manifest, tables)
    papers = tables["papers"] + tables["cited_papers"]
    mapping = {p["id"]: "receiver-" + p["id"] for p in papers}
    database = tmp_path / "receiver.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        conn.commit()
    native = research_generation._identity(database)
    staged = work(
        publisher.stage,
        database,
        validated,
        mapping,
        request_id=str(uuid4()),
        expected_native=native,
    )
    return database, native, papers, mapping, validated, staged


def observe_in(conn, incoming):
    return targets.observe_in(conn, incoming[4], incoming[3], expected_native=incoming[1])


def apply(incoming, *, rollback=False):
    database, _native, papers, mapping, _validated, staged = incoming
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        seed_in(conn, papers, mapping)
        observed = observe_in(conn, incoming)
        result = publisher.publish_in(conn, staged, observed)
        assert result["state"] == "imported"
        assert publisher.publish_in(conn, staged, observed)["state"] == "already_imported"
        with closing(sqlite3.connect(database)) as outside:
            assert outside.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
        if rollback:
            conn.rollback()
        else:
            conn.commit()
    return result, observed


def test_real_report_all_originals_and_retry_receipt_commit_once_without_ai_identity(incoming):
    result, _observed = work(apply, incoming)
    database = incoming[0]
    with closing(sqlite3.connect(database)) as conn:
        record = conn.execute("SELECT request_id,body_json FROM " + publisher.TABLE).fetchone()
        body = publisher.validate_record(dict(zip(publisher.COLUMNS.split(), record, strict=True)))
        row = json.loads(body["records"][0]["row_json"])
        assert conn.execute("SELECT COUNT(*) FROM " + publisher.TABLE).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM research_local_source_owners").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM paper_lineage_sets").fetchone()[0] == 1
        assert (
            dict(
                zip(
                    lineage_sets.COLUMNS.split(),
                    conn.execute("SELECT * FROM paper_lineage_sets").fetchone(),
                    strict=True,
                )
            )
            == row
        )
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not names & {
            "research_generation_requests",
            "research_generation_recovery",
            "research_lineage_publications",
            "paperfact_sync_identity",
        }
        for original in body["records"][0]["sources"]:
            owner = json.loads(original["owner_json"])
            assert owner["database_identity"] == incoming[1]
            assert owner["paper_id"] in incoming[3].values()
            assert owner["binding"] is None
            assert original["request_id"].startswith("import:")
            expected = next(
                data
                for path, data in incoming[4].files
                if path.endswith(original["sha256"] + ".pdf")
            )
            assert source_snapshots.source_path(database, original).read_bytes() == expected

    def retry_fresh():
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("BEGIN")
            fresh = observe_in(conn, incoming)
            assert publisher.publish_in(conn, incoming[5], fresh)["state"] == "already_imported"
            conn.rollback()

    work(retry_fresh)
    assert result["request_id"] == incoming[5]._request


def test_outer_rollback_removes_papers_reports_associations_and_receipt_but_leaves_unowned_bytes(
    incoming,
):
    _result, old = work(apply, incoming, rollback=True)
    with closing(sqlite3.connect(incoming[0])) as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not names & {publisher.TABLE, "paper_lineage_sets", local_source_owners.TABLE}
    assert list((incoming[0].parent / "pdf").rglob("*.pdf"))
    with pytest.raises(ValueError):

        def stale():
            with closing(sqlite3.connect(incoming[0])) as conn:
                conn.execute("BEGIN IMMEDIATE")
                seed_in(conn, incoming[2], incoming[3])
                publisher.publish_in(conn, incoming[5], old)

        work(stale)
    # A fresh caller transaction can repair the abandoned SQL boundary.
    work(apply, incoming)


def test_mid_original_sql_failure_rolls_back_all_child_writes_and_preserves_caller_work(incoming):
    def run():
        with closing(sqlite3.connect(incoming[0])) as conn:
            conn.execute("BEGIN IMMEDIATE")
            seed_in(conn, incoming[2], incoming[3])
            conn.execute(local_source_owners.SCHEMA)
            conn.execute(
                "CREATE TRIGGER fixture_original_failure BEFORE INSERT ON "
                "research_local_source_owners WHEN json_extract(NEW.owner_json,'$.paper_id')="
                "'receiver-later' BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
            )
            observed = observe_in(conn, incoming)
            before = list(conn.iterdump())
            with pytest.raises(sqlite3.IntegrityError, match="fixture failure"):
                publisher.publish_in(conn, incoming[5], observed)
            assert conn.in_transaction and list(conn.iterdump()) == before
            conn.rollback()
        with closing(sqlite3.connect(incoming[0])) as check:
            assert check.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0

    work(run)


@pytest.mark.parametrize(
    "change",
    [
        "file",
        "request-seal",
        "native",
        "report",
        "binding",
        "cancel",
        "history-budget",
        "source-budget",
        "action-budget",
        "corpus-budget",
    ],
)
def test_stale_cancelled_or_over_budget_import_never_installs_partial_research(
    incoming, change, monkeypatch
):
    def run():
        with closing(sqlite3.connect(incoming[0])) as conn:
            conn.execute("BEGIN IMMEDIATE")
            seed_in(conn, incoming[2], incoming[3])
            observed = observe_in(conn, incoming)
            staged = incoming[5]
            if change == "file":
                path = staged._files[0][2]
                from pathlib import Path

                Path(path).write_bytes(b"damaged original")
            elif change == "request-seal":
                staged = replace(staged, _request=str(uuid4()))
            elif change == "native":
                staged = replace(staged, _native=(-1, -1))
            elif change == "report":
                conn.execute(lineage_sets.SCHEMA)
                row = dict(observed.rows[0], written_at="2026-10-01T00:00:00+00:00")
                conn.execute(
                    "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?)",
                    [row[k] for k in lineage_sets.COLUMNS.split()],
                )
            elif change == "binding":
                conn.execute("CREATE TABLE paperfact_sync_identity(workspace TEXT,device TEXT)")
                conn.execute("INSERT INTO paperfact_sync_identity VALUES('bound','fixture')")
            elif change == "history-budget":
                monkeypatch.setattr(publisher, "MAX_HISTORY", 1)
            elif change == "source-budget":
                monkeypatch.setattr(source_snapshots, "MAX_RECEIPTS", 1)
            elif change == "action-budget":
                monkeypatch.setattr(publisher, "MAX_ACTIONS", 0)
            elif change == "corpus-budget":
                monkeypatch.setattr(lineage_sets, "MAX_SETS", 0)
            before = list(conn.iterdump())
            with pytest.raises(ValueError):
                publisher.publish_in(conn, staged, observed, cancelled=lambda: change == "cancel")
            assert conn.in_transaction and list(conn.iterdump()) == before
            conn.rollback()

    work(run)


def test_current_conflict_is_kept_until_explicit_replacement_and_displaced_row_is_retained(
    incoming,
):
    work(apply, incoming)
    original_stage = incoming[5]
    second = work(
        publisher.stage,
        incoming[0],
        incoming[4],
        incoming[3],
        request_id=str(uuid4()),
        expected_native=incoming[1],
    )

    def run():
        with closing(sqlite3.connect(incoming[0])) as conn:
            conn.execute("BEGIN IMMEDIATE")
            saved = targets._target_rows(
                conn, targets._mapping(targets._validated(incoming[4])["rows"], incoming[3])
            )[0]
            changed = dict(saved, written_at="2026-10-01T00:00:00+00:00")
            conn.execute("UPDATE paper_lineage_sets SET written_at=?", (changed["written_at"],))
            observed = observe_in(conn, incoming)
            with pytest.raises(ValueError, match="conflicts with saved research"):
                publisher.publish_in(conn, second, observed)
            assert targets._target_rows(conn, [saved]) == [changed]
            assert publisher.publish_in(conn, second, observed, replace=True)["state"] == "imported"
            body = publisher._read(conn, second._request)
            assert json.loads(body["records"][0]["before_json"]) == changed
            assert publisher._read(conn, original_stage._request) is not None
            assert (
                conn.execute("SELECT COUNT(*) FROM research_local_source_owners").fetchone()[0] == 6
            )
            conn.rollback()

    work(run)


def test_successful_request_cannot_replay_after_later_local_edit(incoming):
    _result, observed = work(apply, incoming)

    def run():
        with closing(sqlite3.connect(incoming[0])) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE paper_lineage_sets SET written_at='2026-10-01T00:00:00+00:00'")
            with pytest.raises(ValueError, match="reused or its published target changed"):
                publisher.publish_in(conn, incoming[5], observed, replace=True)
            assert (
                conn.execute("SELECT written_at FROM paper_lineage_sets").fetchone()[0]
                == "2026-10-01T00:00:00+00:00"
            )
            conn.rollback()

    work(run)


def test_publication_never_parses_or_hash_reads_pdfs_while_holding_sql(incoming, monkeypatch):
    from paper_daily import research_evidence

    def unexpected(*_a, **_k):
        pytest.fail("Verified file reads/parsing must stay outside SQL publication")

    monkeypatch.setattr(local_source_owners, "_read_pdf", unexpected)
    monkeypatch.setattr(research_evidence, "_extract", unexpected)
    work(apply, incoming)


def test_same_action_id_with_changed_real_package_refuses_without_replacing_saved_content(
    incoming, tmp_path
):
    work(apply, incoming)
    original = incoming[0].parent / "import.zip"
    with zipfile.ZipFile(original) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["manifest.json"])
    tables = json.loads(entries["tables.json"])
    tables["paper_lineage_sets"][0]["written_at"] = "2026-10-01T00:00:00+00:00"
    changed = tmp_path / "changed.zip"
    with zipfile.ZipFile(changed, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, json.dumps(tables).encode() if name == "tables.json" else data)
    with zipfile.ZipFile(changed) as archive:
        verified = work(targets.validate, archive, manifest, tables)
    staged = work(
        publisher.stage,
        incoming[0],
        verified,
        incoming[3],
        request_id=incoming[5]._request,
        expected_native=incoming[1],
    )

    def run():
        with closing(sqlite3.connect(incoming[0])) as conn:
            conn.execute("BEGIN IMMEDIATE")
            observed = targets.observe_in(conn, verified, incoming[3], expected_native=incoming[1])
            before = list(conn.iterdump())
            with pytest.raises(ValueError, match="reused or its published target changed"):
                publisher.publish_in(conn, staged, observed, replace=True)
            assert list(conn.iterdump()) == before
            conn.rollback()

    work(run)


def test_cancelled_staging_leaves_only_unowned_bytes_and_no_source_sql(
    incoming, monkeypatch, tmp_path
):
    import shutil

    database = tmp_path / "separate" / "receiver.sqlite"
    database.parent.mkdir()
    shutil.copyfile(incoming[0], database)
    native = research_generation._identity(database)
    before = database.read_bytes()
    written = False
    stage_file = publisher._stage_file

    def finish_first(*args):
        nonlocal written
        result = stage_file(*args)
        written = True
        return result

    monkeypatch.setattr(publisher, "_stage_file", finish_first)
    with pytest.raises(ValueError, match="cancelled"):
        work(
            publisher.stage,
            database,
            incoming[4],
            incoming[3],
            request_id=str(uuid4()),
            expected_native=native,
            cancelled=lambda: written,
        )
    assert database.read_bytes() == before
    assert len(list((database.parent / "pdf").rglob("*.pdf"))) == 1
    assert not list((database.parent / "pdf").rglob(".lineage-stage-*"))


def test_damaged_existing_cache_is_not_overwritten_as_a_retry_repair(incoming):
    from pathlib import Path

    selected = Path(incoming[5]._files[0][2])
    selected.write_bytes(b"damaged cached PDF")
    with pytest.raises(ValueError):
        work(
            publisher.stage,
            incoming[0],
            incoming[4],
            incoming[3],
            request_id=str(uuid4()),
            expected_native=incoming[1],
        )
    assert selected.read_bytes() == b"damaged cached PDF"


@pytest.mark.parametrize("kind", ["no-primary-key", "source-view"])
def test_native_table_shape_cannot_silently_remove_retry_or_owner_guards(incoming, kind):
    def run():
        with closing(sqlite3.connect(incoming[0])) as conn:
            conn.execute("BEGIN IMMEDIATE")
            seed_in(conn, incoming[2], incoming[3])
            if kind == "no-primary-key":
                conn.execute(
                    "CREATE TABLE research_lineage_imports(request_id TEXT,body_json TEXT)"
                )
            else:
                conn.execute(
                    "CREATE VIEW research_local_source_owners AS SELECT "
                    + ",".join("NULL AS " + k for k in local_source_owners.COLUMNS.split())
                    + " WHERE 0"
                )
            observed = observe_in(conn, incoming)
            before = list(conn.iterdump())
            with pytest.raises(ValueError, match="exact native table"):
                publisher.publish_in(conn, incoming[5], observed)
            assert list(conn.iterdump()) == before and conn.in_transaction
            conn.rollback()

    work(run)


@pytest.mark.parametrize("interruption", ["cancel", "original-change"])
def test_interruption_after_an_original_insert_rolls_back_report_and_earlier_associations(
    incoming, interruption
):
    from pathlib import Path

    def run():
        cancelled = False

        def interrupt():
            nonlocal cancelled
            if interruption == "cancel":
                cancelled = True
            else:
                Path(incoming[5]._files[-1][2]).write_bytes(b"changed during SQL publication")
            return 0

        with closing(sqlite3.connect(incoming[0])) as conn:
            conn.execute("BEGIN IMMEDIATE")
            seed_in(conn, incoming[2], incoming[3])
            conn.execute(local_source_owners.SCHEMA)
            conn.create_function("fixture_interrupt", 0, interrupt)
            conn.execute(
                "CREATE TRIGGER fixture_interrupt_source AFTER INSERT ON "
                "research_local_source_owners "
                "WHEN json_extract(NEW.owner_json,'$.paper_id')='receiver-focal' "
                "BEGIN SELECT fixture_interrupt(); END"
            )
            observed = observe_in(conn, incoming)
            before = list(conn.iterdump())
            with pytest.raises(ValueError):
                publisher.publish_in(conn, incoming[5], observed, cancelled=lambda: cancelled)
            assert list(conn.iterdump()) == before and conn.in_transaction
            conn.rollback()

    work(run)


def test_rehashed_receipt_cannot_transfer_a_focal_original_to_a_selected_peer(incoming):
    work(apply, incoming)
    with closing(sqlite3.connect(incoming[0])) as conn:
        body = publisher._read(conn, incoming[5]._request)
    original = body["records"][0]["sources"][0]
    owner = json.loads(original["owner_json"])
    owner["paper_id"] = owner["source_owner_id"] = "receiver-prior"
    owner["parent_lifecycle"] = next(
        p["parent_lifecycle"] for p in body["parents"] if p["paper_id"] == "receiver-prior"
    )
    original["owner_json"] = json.dumps(owner, sort_keys=True, separators=(",", ":"))
    local_source_owners.validate(original)
    body["fingerprint"] = publisher._fingerprint(body)
    record = dict(
        request_id=body["request_id"],
        body_json=json.dumps(body, sort_keys=True, separators=(",", ":")),
    )
    with pytest.raises(ValueError, match="differs from its receiver owner"):
        publisher.validate_record(record)


def test_empty_package_has_no_source_files_or_native_import_receipt(tmp_path):
    database = tmp_path / "empty.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
    native = research_generation._identity(database)
    manifest = {"format": 2, "capabilities": [], "pdfs_included": True, "file_hashes": {}}
    tables = {"papers": [], "cited_papers": []}
    path = tmp_path / "empty.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("tables.json", json.dumps(tables))
    with zipfile.ZipFile(path) as archive:
        validated = work(targets.validate, archive, manifest, tables)
    staged = work(
        publisher.stage, database, validated, {}, request_id=str(uuid4()), expected_native=native
    )

    def run():
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = list(conn.iterdump())
            assert publisher.publish_in(conn, staged, None) == dict(state="empty", reports=0)
            assert list(conn.iterdump()) == before and conn.in_transaction
            conn.rollback()

    work(run)
    assert not (tmp_path / "pdf").exists()


def test_import_history_is_preserved_by_the_source_complete_backup(incoming, tmp_path):
    from paper_daily import sync_recovery

    work(apply, incoming)
    destination = tmp_path / "pending-recovery.zip"
    with closing(sqlite3.connect(incoming[0])) as conn:
        before = list(conn.iterdump())
    manifest = sync_recovery.create(incoming[0], destination)
    assert destination.is_file() and sync_recovery.inspect(destination) == manifest
    with zipfile.ZipFile(destination) as archive:
        actions = [
            json.loads(line)
            for line in archive.read("tables/" + publisher.TABLE + ".jsonl").splitlines()
        ]
        assert len(actions) == 1
        body = publisher.validate_record(actions[0])
        for original in body["records"][0]["sources"]:
            assert (
                archive.read("objects/" + original["sha256"])
                == source_snapshots.source_path(incoming[0], original).read_bytes()
            )
    with closing(sqlite3.connect(incoming[0])) as conn:
        assert list(conn.iterdump()) == before


def test_staged_publication_releases_the_native_input_package_and_keeps_verified_results(incoming):
    import gc
    import weakref

    class TrackedPackage(targets.ValidatedPackage):
        pass

    original = incoming[4]
    tracked = TrackedPackage(original._json, original._files, original._seal)
    reference = weakref.ref(tracked)
    staged = work(
        publisher.stage,
        incoming[0],
        tracked,
        incoming[3],
        request_id=str(uuid4()),
        expected_native=incoming[1],
    )
    del tracked
    gc.collect()
    assert reference() is None
    assert work(apply, (*incoming[:5], staged))[0]["state"] == "imported"


def test_changed_staged_scientific_metadata_cannot_reuse_a_file_version_proof(incoming):
    staged = replace(incoming[5], _content="{}")

    def run():
        with closing(sqlite3.connect(incoming[0])) as conn:
            conn.execute("BEGIN IMMEDIATE")
            seed_in(conn, incoming[2], incoming[3])
            observed = observe_in(conn, incoming)
            before = list(conn.iterdump())
            with pytest.raises(ValueError, match="native staged originals"):
                publisher.publish_in(conn, staged, observed)
            assert list(conn.iterdump()) == before and conn.in_transaction
            conn.rollback()

    work(run)
