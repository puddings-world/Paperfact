"""Unapplied Inbox union must coexist with queue-pin history and position refusal."""

import hashlib
import json
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_position_snapshot_guard import before, position_table
from test_position_snapshot_guard import database as _position_database
from test_queue_pin_packages import package as _package
from test_queue_pin_packages import target
from test_research_inbox import payload, rows, saved

from paper_daily import (
    bundle,
    enrollment_history,
    inbox_content,
    recovery_provenance,
    store,
    sync_recovery,
)
from paper_daily.list_pins import set_pinned
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.research_inbox import Inbox
from paper_daily.sync_files import canonical_json
from paper_daily.sync_projection import read_manifest
from paper_daily.workspace_service import Cancelled, Ticket

package = _package
position_database = _position_database
PIN = "2026-11-01T09:12:34.123456+08:00"


@pytest.fixture
def combined(package, tmp_path, monkeypatch):
    database = target(monkeypatch, tmp_path / "combined-source")
    assert bundle.import_(package, pdfs=False)["queue_pins"] == 1
    with store.connect() as conn:
        owner = conn.execute("SELECT paper_id FROM pins WHERE scope='queue'").fetchone()[0]
        set_pinned(conn, "queue", owner, False)
        conn.commit()
        set_pinned(conn, "queue", owner, True, pinned_at=PIN)
        conn.commit()
    report = bundle.import_(package, pdfs=False, replace=True)
    assert report["queue_pins"] == 0 and len(report["queue_pin_preserved"]) == 1
    bundle.import_(package, pdfs=False, replace=True)
    inbox = Inbox(database)
    _, request, live_id, _ = saved(inbox, payload("  DOI:10.1234/Union-Kept  ", "doi"))
    old = inbox.read()
    item = next(row for row in old.data["items"] if row["id"] == live_id)
    kept = payload("  Kept idea <script>literal text</script>  ", state="kept")
    inbox.save(
        old, request_id=str(uuid4()), item_id=live_id, payload=kept, observed=inbox.observe(item)
    )
    stale = inbox.save(
        old,
        request_id=str(uuid4()),
        item_id=live_id,
        payload=payload("  Retained offline proposal  "),
        observed=inbox.observe(item),
    )
    assert stale["status"] == "conflict"
    _, _, deleted_id, _ = saved(inbox, payload("  Deleted triage text is retained  "))
    view = inbox.read()
    deleted = next(row for row in view.data["items"] if row["id"] == deleted_id)
    inbox.save(
        view,
        request_id=str(uuid4()),
        item_id=deleted_id,
        payload=None,
        action="delete",
        observed=inbox.observe(deleted),
    )
    with closing(sqlite3.connect(database)) as conn:
        archives = enrollment_history.archived(conn)
        pin_history = [row for row in archives if row["protocol"] == "queue_pin_import_v1"]
        assert len(pin_history) == 1
        assert conn.execute("SELECT * FROM queue").fetchall() == []
    return SimpleNamespace(
        database=database,
        inbox=inbox,
        pin_owner=owner,
        pin_history=pin_history,
        live_id=live_id,
        deleted_id=deleted_id,
        sender_request=request,
        expected={
            row["id"]: {"payload": row["payload"], "active": bool(row["active"])}
            for row in inbox.read(include_deleted=True).data["items"]
        },
    )


def canonical_rows(database, table):
    return {json.dumps(row, sort_keys=True) for row in rows(database, table)}


def archived_evidence(conn):
    """Read exact original evidence only through the maintained closed validators."""
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    archives = enrollment_history.archived(conn)
    requests = []

    def collect(row, depth=0, ancestors=frozenset()):
        assert depth <= recovery_provenance.MAX_DEPTH
        assert row["record_id"] not in ancestors
        value = recovery_provenance.decode(row)
        if value["kind"] != "row":
            return
        name, record = value["table"], value["record"]
        if name == enrollment_history.TABLE:
            enrollment_history.validate(record)
            archives.append(record)
        elif name == inbox_content.REQUESTS:
            inbox_content.validate_row(name, record)
            requests.append(record)
        elif name == recovery_provenance.TABLE:
            collect(record, depth + 1, ancestors | {row["record_id"]})

    if recovery_provenance.TABLE in names:
        original = [
            {"record_id": row[0], "body_json": row[1]}
            for row in conn.execute("SELECT record_id,body_json FROM research_recovery_provenance")
        ]
        recovery_provenance.validate_groups(original)
        for row in original:
            collect(row)
    if "recovery_records" in names:
        grouped = []
        for name, data in conn.execute("SELECT table_name,data FROM recovery_records"):
            if name == inbox_content.REQUESTS:
                record = json.loads(data)
                inbox_content.validate_row(name, record)
                requests.append(record)
            elif name == enrollment_history.TABLE:
                row = json.loads(data)
                enrollment_history.validate(row)
                archives.append(row)
            elif name == recovery_provenance.TABLE:
                grouped.append(json.loads(data))
        recovery_provenance.validate_groups(grouped)
        for row in grouped:
            collect(row)
    for row in archives:
        if row["protocol"] == inbox_content.REQUESTS:
            requests.append(enrollment_history.validate(row)[0])
    return archives, requests


def assert_content(database, original, history, candidates):
    current = Inbox(database)
    assert {
        row["id"]: {"payload": row["payload"], "active": bool(row["active"])}
        for row in current.read(include_deleted=True).data["items"]
    } == original.expected
    assert history <= canonical_rows(database, inbox_content.HISTORY)
    assert candidates <= canonical_rows(database, inbox_content.CANDIDATES)
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT scope,paper_id,pinned_at FROM pins").fetchall() == [
            ("queue", original.pin_owner, PIN)
        ]
        assert conn.execute("SELECT * FROM queue").fetchall() == []
    return current


def test_combined_backup_detached_editable_copy_preserves_both_histories_and_archives_authority(
    combined, tmp_path
):
    original = combined
    source = original.database
    history = canonical_rows(source, inbox_content.HISTORY)
    candidates = canonical_rows(source, inbox_content.CANDIDATES)
    requests = rows(source, inbox_content.REQUESTS)
    owners = {rows(source, inbox_content.OWNER)[0]["token"]}
    initial_incarnations = {row["incarnation"] for row in rows(source, inbox_content.ITEMS)}
    first_bytes = source.read_bytes()
    backup = tmp_path / "source.zip"
    sync_recovery.create(source, backup)
    assert source.read_bytes() == first_bytes
    for index in range(2):
        detached = tmp_path / f"detached-{index}"
        sync_recovery.restore_detached(backup, detached)
        detached_db = detached / "papers.db"
        service = assert_content(detached_db, original, history, candidates)
        assert rows(detached_db, inbox_content.REQUESTS) == []
        token = rows(detached_db, inbox_content.OWNER)[0]["token"]
        assert token not in owners
        owners.add(token)
        with closing(sqlite3.connect(detached_db)) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
            assert "paperfact_sync_identity" not in tables
            _, archived_requests = archived_evidence(conn)
            assert all(row in archived_requests for row in requests)

        adopter = RecoveryAdoptionService(detached_db)
        inspection = adopter.inspect()
        assert inspection.report["supported"], inspection.report["blockers"]
        prepared = adopter.prepare(
            inspection,
            tmp_path / f"editable-{index}",
            backup_output=tmp_path / f"independent-{index}.zip",
            request_id=str(uuid4()),
        )
        database = Path(prepared["database"])
        service = assert_content(database, original, history, candidates)
        assert rows(database, inbox_content.REQUESTS) == []
        token = rows(database, inbox_content.OWNER)[0]["token"]
        assert token not in owners
        owners.add(token)
        assert initial_incarnations.isdisjoint(
            {row["incarnation"] for row in rows(database, inbox_content.ITEMS)}
        )
        with closing(sqlite3.connect(database)) as conn:
            archive, incoming = archived_evidence(conn)
            assert all(row in archive for row in original.pin_history)
            assert all(row in incoming for row in requests)
            workspace, device = conn.execute(
                "SELECT workspace,device FROM paperfact_sync_identity"
            ).fetchone()
            operations = [
                json.loads(row[0])
                for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
            ]
            inbox_ops = [op for op in operations if op["entity_type"] == "inbox_item"]
            assert {op["entity_id"] for op in inbox_ops} == set(original.expected)
            assert all(
                op["parents"] == []
                and op["workspace_id"] == workspace
                and op["device_id"] == device
                for op in inbox_ops
            )
            assert all(
                op["operation_id"]
                not in {row["version"] for row in rows(source, inbox_content.HISTORY)}
                for op in inbox_ops
            )
        projection = read_manifest(database, workspace_id=workspace, schema_version=2)
        assert projection["required_capabilities"] == ["inbox", "queue_pin"]
        # Sender request IDs are not live replay authority on the new receiver.
        outcome = service.save(
            service.read(),
            request_id=original.sender_request,
            item_id=original.live_id,
            payload=payload("Sender replay must not win"),
        )
        assert outcome["status"] == "conflict"
        assert_content(database, original, history, candidates)
        backup = Path(prepared["backup"])
        assert sync_recovery.inspect(backup)["workspace_id"] == workspace
    assert source.read_bytes() == first_bytes


def test_actual_combined_snapshot_is_accepted_by_independent_mobile_parser(combined, tmp_path):
    from paper_daily.workspace_enrollment import EnrollmentService

    service = EnrollmentService(combined.database)
    assert service.plan()["supported"]
    copied = service.prepare(
        tmp_path / "snapshot-copy",
        backup_output=tmp_path / "snapshot-copy.zip",
        request_id=str(uuid4()),
    )
    database = Path(copied["database"])
    with closing(sqlite3.connect(database)) as conn:
        workspace = conn.execute("SELECT workspace FROM paperfact_sync_identity").fetchone()[0]
        portable_pin_owner = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (combined.pin_owner,)
        ).fetchone()[0]
    before_bytes = database.read_bytes()
    snapshot = read_manifest(database, workspace_id=workspace, schema_version=2)
    assert snapshot["required_capabilities"] == ["inbox", "queue_pin"]
    assert database.read_bytes() == before_bytes
    fixture = tmp_path / "combined-projection.json"
    fixture.write_text(
        json.dumps(
            {
                "snapshot": snapshot,
                "pin_owner": portable_pin_owner,
                "pin": PIN,
                "items": combined.expected,
            }
        ),
        encoding="utf-8",
    )
    node = shutil.which("node")
    assert node, "Node is required for the independent mobile contract check"
    script = Path(__file__).resolve().parents[1] / "mobile/inbox-union-check.mjs"
    result = subprocess.run(
        [node, str(script), str(fixture)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS combined Python snapshot" in result.stdout


@pytest.mark.parametrize("schema", [1, 2])
def test_inbox_and_pin_do_not_hide_nonempty_position_snapshot_refusal(position_database, schema):
    service = Inbox(position_database)
    saved(service, payload("Inbox must not bypass the position guard"))
    good = read_manifest(position_database, workspace_id="workspace", schema_version=schema)
    assert good["required_capabilities"] == ["inbox", "queue_pin"]
    position_table(position_database, ["paper", "a" * 64, 2, "2026-10-30T12:00:00Z", "entered"])
    original = before(position_database)
    with pytest.raises(ValueError, match="Source-bound reading positions are not supported"):
        read_manifest(position_database, workspace_id="workspace", schema_version=schema)
    assert before(position_database) == original
    with closing(sqlite3.connect(position_database)) as conn:
        assert conn.execute("SELECT sequence FROM paperfact_sync_cursor").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM reading_positions").fetchone()[0] == 1
    assert (
        service.read().data["items"][0]["payload"]["text"]
        == "Inbox must not bypass the position guard"
    )


@pytest.mark.parametrize(
    "change",
    [
        "original_item",
        "original_history",
        "missing_original",
        "current_item",
        "extra_history",
        "owner",
        "seed",
        "sender_request",
        "oversized",
        "owner_table",
    ],
)
def test_tampered_detached_inbox_never_prepares_an_editable_copy(combined, tmp_path, change):
    package = tmp_path / "source.zip"
    sync_recovery.create(combined.database, package)
    restored = tmp_path / "detached"
    sync_recovery.restore_detached(package, restored)
    database = restored / "papers.db"
    adopter = RecoveryAdoptionService(database)
    inspection = adopter.inspect()
    source_bytes = combined.database.read_bytes()
    with closing(sqlite3.connect(database)) as conn, conn:
        if change in {"original_item", "original_history"}:
            table = inbox_content.ITEMS if change == "original_item" else inbox_content.HISTORY
            index, raw = conn.execute(
                "SELECT row_number,data FROM recovery_records WHERE table_name=? LIMIT 1", (table,)
            ).fetchone()
            record = json.loads(raw)
            record["body_json"] = inbox_content.encode(payload("Tampered original text"))
            conn.execute(
                "UPDATE recovery_records SET data=? WHERE table_name=? AND row_number=?",
                (json.dumps(record), table, index),
            )
        elif change == "missing_original":
            conn.execute("DELETE FROM recovery_records WHERE table_name=?", (inbox_content.ITEMS,))
        elif change in {"current_item", "oversized"}:
            value = (
                inbox_content.encode(payload("Changed current text"))
                if change == "current_item"
                else "x" * (1024 * 1024)
            )
            conn.execute(
                f"UPDATE {inbox_content.ITEMS} SET body_json=? WHERE id=?",
                (value, combined.live_id),
            )
        elif change == "extra_history":
            row = conn.execute(
                f"SELECT item_id,body_json,incarnation,active FROM {inbox_content.HISTORY} LIMIT 1"
            ).fetchone()
            conn.execute(
                f"INSERT INTO {inbox_content.HISTORY} VALUES(?,?,?,?,?)", (str(uuid4()), *row)
            )
        elif change == "owner":
            conn.execute(f"UPDATE {inbox_content.OWNER} SET token=?", (str(uuid4()),))
        elif change == "seed":
            conn.execute("UPDATE recovery_identity SET recovery_device=?", (str(uuid4()),))
        elif change == "owner_table":
            conn.execute(f"DROP TABLE {inbox_content.OWNER}")
        else:
            row = rows(combined.database, inbox_content.REQUESTS)[0]
            fields = inbox_content.COLUMNS[inbox_content.REQUESTS].split()
            conn.execute(
                f"INSERT INTO {inbox_content.REQUESTS} VALUES("
                + ",".join("?" for _ in fields)
                + ")",
                [row[key] for key in fields],
            )
    output, backup = tmp_path / "must-not-exist", tmp_path / "must-not-exist.zip"
    with pytest.raises(ValueError):
        adopter.prepare(inspection, output, backup_output=backup, request_id=str(uuid4()))
    assert not output.exists() and not backup.exists()
    assert combined.database.read_bytes() == source_bytes


def test_failed_receiver_materialization_rolls_back_then_retry_is_fresh(
    combined, tmp_path, monkeypatch
):
    from paper_daily import inbox_recovery

    package = tmp_path / "source.zip"
    sync_recovery.create(combined.database, package)
    before = combined.database.read_bytes()
    destination = tmp_path / "retry-detached"
    original = inbox_recovery.content.write
    calls = []

    def fail_after_write(conn, operation):
        result = original(conn, operation)
        calls.append(operation["operation_id"])
        if len(calls) == 1:
            raise RuntimeError("Storage interrupted after first receiver item")
        return result

    monkeypatch.setattr(inbox_recovery.content, "write", fail_after_write)
    with pytest.raises(RuntimeError, match="Storage interrupted"):
        sync_recovery.restore_detached(package, destination)
    assert not destination.exists() and combined.database.read_bytes() == before
    sync_recovery.restore_detached(package, destination)
    assert len(calls) == 3
    database = destination / "papers.db"
    assert rows(database, inbox_content.REQUESTS) == []
    assert (
        len(rows(database, inbox_content.HISTORY))
        == len(rows(combined.database, inbox_content.HISTORY)) + 2
    )
    assert RecoveryAdoptionService(database).inspect().report["supported"]
    assert combined.database.read_bytes() == before


def test_cancelled_editable_adoption_keeps_source_and_can_retry(combined, tmp_path):
    package = tmp_path / "source.zip"
    sync_recovery.create(combined.database, package)
    destination = tmp_path / "detached"
    sync_recovery.restore_detached(package, destination)
    service = RecoveryAdoptionService(destination / "papers.db")
    inspection = service.inspect()
    ticket = Ticket()
    ticket.cancel()
    output, backup = tmp_path / "editable", tmp_path / "independent.zip"
    request = str(uuid4())
    with pytest.raises(Cancelled):
        service.prepare(inspection, output, backup_output=backup, request_id=request, ticket=ticket)
    assert not output.exists() and not backup.exists()
    prepared = service.prepare(inspection, output, backup_output=backup, request_id=request)
    assert prepared["editable_copy"] and Path(prepared["backup"]).is_file()
    assert rows(prepared["database"], inbox_content.REQUESTS) == []


def test_nested_original_evidence_keeps_strict_format_and_depth_limits(combined):
    row = recovery_provenance.wrap(
        str(uuid4()),
        "row",
        table=inbox_content.ITEMS,
        index=0,
        record=rows(combined.database, inbox_content.ITEMS)[0],
    )
    assert recovery_provenance.decode(row)["kind"] == "row"
    data = json.loads(row["body_json"])
    data["version"] = 2
    raw = canonical_json(data)
    invalid = {"record_id": hashlib.sha256(raw).hexdigest(), "body_json": raw.decode()}
    with pytest.raises(ValueError, match="version"):
        recovery_provenance.decode(invalid)
    with pytest.raises(ValueError, match="nesting"):
        recovery_provenance.validate_groups([], depth=recovery_provenance.MAX_DEPTH)
