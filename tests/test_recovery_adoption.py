"""Actual detached recovery sources, never owner research or real accounts."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_sync_recovery import archive_rows
from test_sync_recovery import research as research_fixture

from paper_daily import recovery_provenance, sync_recovery
from paper_daily.recovery_adoption import RecoveryAdoptionService, RecoveryInspection
from paper_daily.workspace_service import Cancelled, Ticket

research = research_fixture


@pytest.fixture
def restored(research, tmp_path):
    package = tmp_path / "original.zip"
    manifest = sync_recovery.create(research[0], package)
    folder = tmp_path / "restored"
    sync_recovery.restore_detached(package, folder)
    return folder, package, manifest


def test_sealed_inspection_preserves_all_canonical_research_and_source(restored):
    folder, _package, manifest = restored
    database = folder / "papers.db"
    before = database.read_bytes()
    service = RecoveryAdoptionService(database)
    result = service.inspect()
    assert isinstance(result, RecoveryInspection)
    assert result.report["backup_id"] == manifest["backup_id"]
    assert result.report["research_counts"]["notes"] == 1
    assert result.report["history_counts"]["paperfact_sync_operations"] > 0
    assert database.read_bytes() == before
    assert not result.report["uploaded"] and not result.report["adopted"]
    result.report["research_counts"]["notes"] = 99
    assert result.report["research_counts"]["notes"] == 1


@pytest.mark.parametrize("change", ["research", "protocol", "extra-file", "unknown-record"])
def test_incomplete_or_changed_recovery_is_not_silently_flattened(restored, change):
    folder, _, _ = restored
    with closing(sqlite3.connect(folder / "papers.db")) as conn, conn:
        if change == "research":
            conn.execute("UPDATE notes SET body='later edit'")
        elif change == "protocol":
            conn.execute(
                "DELETE FROM recovery_records WHERE rowid=(SELECT MIN(rowid) FROM recovery_records)"
            )
        elif change == "unknown-record":
            conn.execute("INSERT INTO recovery_records VALUES('future_lineage_protocol',0,'{}')")
    if change == "extra-file":
        (folder / "private-future.bin").write_bytes(b"do not silently omit")
    with pytest.raises(ValueError):
        RecoveryAdoptionService(folder / "papers.db").inspect()


def test_cancelled_inspection_creates_no_authority_or_outputs(restored):
    folder, _, _ = restored
    before = (folder / "papers.db").read_bytes()
    ticket = Ticket()
    ticket.cancel()
    with pytest.raises(Cancelled):
        RecoveryAdoptionService(folder / "papers.db").inspect(ticket=ticket)
    assert (folder / "papers.db").read_bytes() == before


def test_archive_only_provenance_roundtrips_without_old_live_authority(
    research, restored, tmp_path
):
    _, package, manifest = restored
    tables = {table["name"]: archive_rows(package, table["name"]) for table in manifest["tables"]}
    rows = recovery_provenance.encode(manifest, tables)
    groups = recovery_provenance.validate_groups(rows)
    assert len(groups) == 1
    assert len(groups[0].pending) > 0
    with closing(sqlite3.connect(research[0])) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        recovery_provenance.retain_in(conn, rows)
    second = tmp_path / "preserved.zip"
    copied = sync_recovery.create(research[0], second)
    assert sync_recovery.inspect(second) == copied
    destination = tmp_path / "second-restore"
    sync_recovery.restore_detached(second, destination)
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM recovery_records WHERE table_name=?", (recovery_provenance.TABLE,)
        ).fetchone()[0] == len(rows)
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (recovery_provenance.TABLE,)
        ).fetchone()


def test_provenance_missing_row_or_tampered_closed_snapshot_rejected(restored):
    _, package, manifest = restored
    tables = {table["name"]: archive_rows(package, table["name"]) for table in manifest["tables"]}
    rows = recovery_provenance.encode(manifest, tables)
    with pytest.raises(ValueError, match="Incomplete"):
        recovery_provenance.validate_groups(rows[:-1])
    value = json.loads(rows[-1]["body_json"])
    value["record"]["unexpected"] = True
    changed = recovery_provenance.wrap(
        value["backup_id"],
        "row",
        table=value["table"],
        index=value["index"],
        record=value["record"],
    )
    with pytest.raises(ValueError):
        recovery_provenance.validate_groups(rows[:-1] + [changed])


def prepared(service, inspection, tmp_path, suffix="", **kwargs):
    from uuid import uuid4

    return service.prepare(
        inspection,
        tmp_path / ("editable" + suffix),
        backup_output=tmp_path / ("editable" + suffix + ".zip"),
        request_id=str(uuid4()),
        **kwargs,
    )


def test_actual_editable_copy_has_fresh_authority_complete_history_and_backup(restored, tmp_path):
    folder, original, manifest = restored
    source = folder / "papers.db"
    before = source.read_bytes()
    service = RecoveryAdoptionService(source)
    inspection = service.inspect()
    result = prepared(service, inspection, tmp_path)
    assert result["status"] == "prepared_for_review" and result["editable_copy"]
    assert result["recovered_from"] == manifest["backup_id"]
    assert not result["adopted"] and not result["uploaded"]
    assert result["device_id"] != manifest["origin_device_id"]
    assert result["workspace_id"] != manifest["workspace_id"]
    assert source.read_bytes() == before
    with closing(sqlite3.connect(result["database"])) as conn:
        assert conn.execute("SELECT body FROM notes").fetchall() == [("Saved research",)]
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='recovery_records'"
        ).fetchone()
        assert conn.execute("SELECT COUNT(*) FROM " + recovery_provenance.TABLE).fetchone()[0] > 0
        active = {
            row[0] for row in conn.execute("SELECT operation_id FROM paperfact_sync_operations")
        }
    old = {row["operation_id"] for row in archive_rows(original, "paperfact_sync_operations")}
    assert active.isdisjoint(old)
    assert sync_recovery.inspect(result["backup"])["workspace_id"] == result["workspace_id"]
    second_root = tmp_path / "restored-again"
    sync_recovery.restore_detached(result["backup"], second_root)
    second_service = RecoveryAdoptionService(second_root / "papers.db")
    second = prepared(second_service, second_service.inspect(), tmp_path, "-again")
    assert sync_recovery.inspect(second["backup"])["workspace_id"] == second["workspace_id"]
    assert second["workspace_id"] != result["workspace_id"]


@pytest.mark.parametrize("change", ["cancel", "source-edit", "late-source-edit", "late-cancel"])
def test_preparation_cancel_or_late_change_publishes_neither_copy_nor_backup(
    restored, tmp_path, change
):
    folder, _, _ = restored
    service = RecoveryAdoptionService(folder / "papers.db")
    inspection = service.inspect()
    ticket = Ticket()

    def mutate(_text):
        if (
            _text == "Verified candidate ready for explicit review and adoption"
            and change == "late-cancel"
        ):
            ticket.cancel()
        if (
            _text == "Verified candidate ready for explicit review and adoption"
            and change == "late-source-edit"
        ):
            with closing(sqlite3.connect(folder / "papers.db")) as conn, conn:
                conn.execute("UPDATE notes SET body='newer research'")

    if change == "cancel":
        ticket.cancel()
    elif change == "source-edit":

        def mutate(_text):
            return None

        with closing(sqlite3.connect(folder / "papers.db")) as conn, conn:
            conn.execute("UPDATE notes SET body='newer research'")
    with pytest.raises((ValueError, Cancelled)):
        prepared(service, inspection, tmp_path, ticket=ticket, progress=mutate)
    assert not (tmp_path / "editable").exists()
    assert not (tmp_path / "editable.zip").exists()


def test_caller_json_or_other_services_inspection_cannot_grant_editability(restored, tmp_path):
    folder, _, _ = restored
    service = RecoveryAdoptionService(folder / "papers.db")
    other = RecoveryAdoptionService(folder / "papers.db")
    inspection = other.inspect()
    for value in (inspection.report, inspection, object()):
        with pytest.raises(ValueError, match="inspected snapshot"):
            prepared(service, value, tmp_path)


def test_publish_failure_rolls_back_own_backup_and_retry_keeps_single_fresh_workspace(
    restored, tmp_path, monkeypatch
):
    from uuid import uuid4

    from paper_daily import workspace_enrollment

    folder, _, _ = restored
    service = RecoveryAdoptionService(folder / "papers.db")
    inspection = service.inspect()
    request = str(uuid4())
    output, backup = tmp_path / "retry-copy", tmp_path / "retry-backup.zip"
    original = workspace_enrollment.publish_directory

    def fail(*_args):
        raise OSError("fixture disk error")

    monkeypatch.setattr(workspace_enrollment, "publish_directory", fail)
    with pytest.raises(OSError, match="fixture disk"):
        service.prepare(inspection, output, backup_output=backup, request_id=request)
    assert not output.exists() and not backup.exists()
    monkeypatch.setattr(workspace_enrollment, "publish_directory", original)
    result = service.prepare(inspection, output, backup_output=backup, request_id=request)
    assert sync_recovery.inspect(backup)["workspace_id"] == result["workspace_id"]
    with pytest.raises(ValueError, match="new paths"):
        service.prepare(inspection, output, backup_output=backup, request_id=request)


def test_duplicate_prepare_is_deduplicated_while_first_stages(restored, tmp_path):
    import threading

    folder, _, _ = restored
    service = RecoveryAdoptionService(folder / "papers.db")
    inspection = service.inspect()
    started, release = threading.Event(), threading.Event()
    results, errors = [], []

    def progress(_text):
        started.set()
        assert release.wait(10)

    def first():
        try:
            results.append(prepared(service, inspection, tmp_path, progress=progress))
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=first)
    worker.start()
    try:
        assert started.wait(10)
        with pytest.raises(ValueError, match="already active"):
            prepared(service, inspection, tmp_path, "-duplicate")
    finally:
        release.set()
        worker.join(15)
    assert not worker.is_alive() and errors == [] and len(results) == 1
    assert not (tmp_path / "editable-duplicate").exists()
    assert not (tmp_path / "editable-duplicate.zip").exists()


def test_workspace_switch_after_inspection_never_publishes_to_old_context(restored, tmp_path):
    folder, _, _ = restored
    current = [folder / "papers.db"]
    service = RecoveryAdoptionService(current[0], current_path=lambda: current[0])
    inspection = service.inspect()
    current[0] = tmp_path / "other.db"
    with pytest.raises(ValueError, match="changed"):
        prepared(service, inspection, tmp_path)
    assert not (tmp_path / "editable").exists() and not (tmp_path / "editable.zip").exists()


def test_unlisted_paper_all_lists_order_and_notes_survive_without_per_list_flattening(
    research, tmp_path
):
    source = research[0]
    with closing(sqlite3.connect(source)) as conn, conn:
        existing = conn.execute("SELECT id FROM lists").fetchone()[0]
        paper = dict(
            zip(
                [row[1] for row in conn.execute("PRAGMA table_info(papers)")],
                conn.execute("SELECT * FROM papers").fetchone(),
                strict=True,
            )
        )
        paper.update(id="orphan", title="Unlisted research", title_key="unlistedresearch")
        conn.execute(
            "INSERT INTO papers ("
            + ",".join(paper)
            + ") VALUES("
            + ",".join("?" for _ in paper)
            + ")",
            tuple(paper.values()),
        )
        conn.execute(
            "INSERT INTO lists VALUES('second','Another list',NULL,'2026-10-30T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) "
            "VALUES('orphan','Unlisted saved note','2026-10-30T00:00:00+00:00')"
        )
        conn.execute("INSERT INTO kv VALUES('lists.order',?)", (json.dumps(["second", existing]),))
    package = tmp_path / "all-research.zip"
    sync_recovery.create(source, package)
    folder = tmp_path / "all-detached"
    sync_recovery.restore_detached(package, folder)
    service = RecoveryAdoptionService(folder / "papers.db")
    inspection = service.inspect()
    assert inspection.report["orphan_papers"] == 1
    result = prepared(service, inspection, tmp_path, "-all")
    with closing(sqlite3.connect(result["database"])) as conn:
        assert (
            conn.execute("SELECT title FROM papers WHERE id='orphan'").fetchone()[0]
            == "Unlisted research"
        )
        assert (
            conn.execute("SELECT body FROM notes WHERE paper_id='orphan'").fetchone()[0]
            == "Unlisted saved note"
        )
        assert conn.execute("SELECT name,note FROM lists WHERE id='second'").fetchone() == (
            "Another list",
            None,
        )
        assert json.loads(
            conn.execute("SELECT value FROM kv WHERE key='lists.order'").fetchone()[0]
        ) == ["second", existing]


@pytest.mark.parametrize("mode", ["queue", "reading_log"])
def test_registered_legacy_workflow_has_fresh_editable_authority_without_dropping_rows(
    research, tmp_path, mode
):
    source = research[0]
    with closing(sqlite3.connect(source)) as conn, conn:
        local = conn.execute("SELECT id FROM papers").fetchone()[0]
        if mode == "queue":
            conn.execute(
                "INSERT INTO queue(paper_id,rank,state,role,reason,queued_at) "
                "VALUES(?,2.5,'deferred','canon','Keep exact workflow',"
                "'2026-10-30T00:00:00+00:00')",
                (local,),
            )
        else:
            conn.execute(
                "INSERT INTO reading_log(paper_id,delivered_at,role,note) "
                "VALUES(?,'2026-10-30T00:00:00+00:00','companion','Keep exact delivery log')",
                (local,),
            )
    package = tmp_path / "legacy.zip"
    sync_recovery.create(source, package)
    original = archive_rows(package, mode)
    folder = tmp_path / "legacy-detached"
    sync_recovery.restore_detached(package, folder)
    before = (folder / "papers.db").read_bytes()
    service = RecoveryAdoptionService(folder / "papers.db")
    inspection = service.inspect()
    assert inspection.report["supported"]
    assert inspection.report["research_counts"][mode] == 1
    result = prepared(service, inspection, tmp_path, "-legacy")
    with closing(sqlite3.connect(result["database"])) as conn:
        columns = [row[1] for row in conn.execute('PRAGMA table_info("' + mode + '")')]
        copied = [
            dict(zip(columns, row, strict=True))
            for row in conn.execute('SELECT * FROM "' + mode + '"')
        ]
        assert copied == original
        feature = "queue_entry" if mode == "queue" else "reading_event"
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM research_content_projection WHERE feature=?", (feature,)
            ).fetchone()[0]
            == 1
        )
        old_operations = {
            row["operation_id"] for row in archive_rows(package, "paperfact_sync_operations")
        }
        fresh = {
            row[0] for row in conn.execute("SELECT operation_id FROM paperfact_sync_operations")
        }
        assert fresh.isdisjoint(old_operations)
    assert (folder / "papers.db").read_bytes() == before
    with closing(sqlite3.connect(folder / "papers.db")) as conn:
        actual = [
            dict(
                zip(
                    [row[1] for row in conn.execute('PRAGMA table_info("' + mode + '")')],
                    row,
                    strict=True,
                )
            )
            for row in conn.execute('SELECT * FROM "' + mode + '"')
        ]
        assert actual == original
    assert (tmp_path / "editable-legacy").is_dir()
    assert (
        sync_recovery.inspect(tmp_path / "editable-legacy.zip")["workspace_id"]
        == result["workspace_id"]
    )


@pytest.mark.parametrize(
    "value",
    [
        {"version": 1, "backup_id": 17, "kind": "manifest", "manifest": {}},
        {"version": 1, "backup_id": "not-a-uuid", "kind": "manifest", "manifest": {}},
        {
            "version": 1,
            "backup_id": "11111111-1111-4111-8111-111111111111",
            "kind": "row",
            "table": [],
            "index": 0,
            "record": {},
        },
    ],
)
def test_closed_provenance_rejects_bad_scalar_types_as_value_errors(value):
    import hashlib

    from paper_daily.sync_files import canonical_json

    body = canonical_json(value)
    row = {"record_id": hashlib.sha256(body).hexdigest(), "body_json": body.decode()}
    with pytest.raises(ValueError):
        recovery_provenance.decode(row)
