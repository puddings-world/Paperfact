"""Queue-pin packages are capability-gated and preserve receiver intent/history."""

import hashlib
import importlib.util
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_list_pins import LIST, STAMP, legacy
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import bundle, store, sync_recovery
from paper_daily.enrollment_history import archived, validate
from paper_daily.package_import import PackageImporter
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.sync_capture import CaptureConnection, expecting, install, observe_target


@pytest.fixture
def package(tmp_path, monkeypatch):
    database = legacy(tmp_path / "sharer", scope="queue")
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    monkeypatch.setattr(bundle, "DATA_DIR", database.parent)
    monkeypatch.setattr(bundle, "PDF_DIR", database.parent / "pdf")
    out = tmp_path / "shared.zip"
    bundle.export(LIST, out, with_pdfs=False)
    return out


def target(monkeypatch, root):
    root.mkdir()
    monkeypatch.setattr(store, "DB_PATH", root / "papers.db")
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    store.init_db()
    return root / "papers.db"


def test_raw_package_roundtrip_preserves_exact_pin_and_old_reader_rejects(
    package, tmp_path, monkeypatch
):
    with zipfile.ZipFile(package) as z:
        manifest, tables, _ = bundle._validated(z)
    assert manifest["capabilities"] == ["queue_pin"]
    assert tables["queue_pins"] == [{"paper_id": "paper", "pinned_at": STAMP}]
    assert tables["pins"] == []
    spec = importlib.util.spec_from_file_location(
        "old_package_reader", Path(__file__).parent / "fixtures/queue-pin-legacy-package-reader.py"
    )
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    with zipfile.ZipFile(package) as z, pytest.raises(ValueError, match="capabilities"):
        old._validated(z)
    database = target(monkeypatch, tmp_path / "raw")
    assert bundle.import_(package, pdfs=False)["queue_pins"] == 1
    assert bundle.import_(package, pdfs=False)["queue_pins"] == 0
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT * FROM pins").fetchall() == [("queue", "paper", STAMP)]
        assert conn.execute("SELECT * FROM queue").fetchall() == []


@pytest.mark.parametrize("change", ["owner", "naive", "extra", "duplicate"])
def test_malformed_queue_pin_package_fails_closed(package, tmp_path, change):
    with zipfile.ZipFile(package) as z:
        entries = {name: z.read(name) for name in z.namelist()}
    tables = json.loads(entries["tables.json"])
    pin = tables["queue_pins"][0]
    if change == "owner":
        pin["paper_id"] = "foreign"
    elif change == "naive":
        pin["pinned_at"] = "2026-10-30T00:00:00"
    elif change == "extra":
        pin["scope"] = "queue"
    else:
        tables["queue_pins"].append(dict(pin))
    entries["tables.json"] = json.dumps(tables).encode()
    changed = tmp_path / "invalid.zip"
    with zipfile.ZipFile(changed, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    with zipfile.ZipFile(changed) as z, pytest.raises(ValueError):
        bundle._validated(z)


def test_raw_import_conflict_keeps_receiver_and_archives_incoming_across_backup(
    package, tmp_path, monkeypatch
):
    database = target(monkeypatch, tmp_path / "raw")
    bundle.import_(package, pdfs=False)
    current = "2026-10-31T00:00:00+00:00"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE pins SET pinned_at=? WHERE scope='queue'", (current,))
    report = bundle.import_(package, pdfs=False, replace=True)
    assert report["queue_pins"] == 0 and len(report["queue_pin_preserved"]) == 1
    bundle.import_(package, pdfs=False, replace=True)
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT pinned_at FROM pins").fetchall() == [(current,)]
        rows = archived(conn)
        assert len(rows) == 1
        record, _ = validate(rows[0])
    assert record == {
        "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "source_owner": "paper",
        "receiver_owner": "paper",
        "incoming_pinned_at": STAMP,
        "receiver_pinned_at": current,
    }
    backup = tmp_path / "preserved.zip"
    sync_recovery.create(database, backup)
    sync_recovery.restore_detached(backup, tmp_path / "detached")
    with closing(sqlite3.connect(tmp_path / "detached/papers.db")) as conn:
        retained = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_history_archive'"
            )
        ]
        assert retained == rows


def test_enrolled_import_pin_and_conflict_archive_are_atomic_and_retry_safe(
    package, pair, tmp_path
):
    _server, a, _b, _fa, _fb, _ta, _tb = pair
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id=a.journal.workspace_id, device_id=a.journal.device_id)
        conn.commit()
    (tmp_path / "managed").mkdir()
    importer = PackageImporter(a.journal.path, tmp_path / "managed")
    prepared = importer.prepare(package, request_id=str(uuid4()))
    report = importer.apply(prepared)
    assert report["queue_pins"] == 1
    mapping = report["identity_mapping"]["paper"]
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert conn.execute("SELECT scope,paper_id,pinned_at FROM pins").fetchall() == [
            ("queue", mapping["local_id"], STAMP)
        ]

    # Existing receiver curation wins even with replace=True; incoming provenance is durable.
    current = "2026-11-01T00:00:00+00:00"
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        observed = observe_target(conn, "paper", mapping["local_id"], "queue_pin")
        with expecting(conn, [observed]):
            conn.execute(
                "UPDATE pins SET pinned_at=? WHERE scope='queue' AND paper_id=?",
                (current, mapping["local_id"]),
            )
            conn.commit()
    request = str(uuid4())
    prepared = importer.prepare(package, request_id=request, replace=True)
    conflict = importer.apply(prepared)
    assert conflict["queue_pins"] == 0 and len(conflict["queue_pin_preserved"]) == 1
    retry = importer.apply(importer.prepare(package, request_id=request, replace=True))
    assert retry["replayed"] is True
    importer.apply(importer.prepare(package, request_id=str(uuid4()), replace=True))
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert conn.execute("SELECT pinned_at FROM pins").fetchall() == [(current,)]
        rows = archived(conn)
        assert len(rows) == 1
        retained, _ = validate(rows[0])
    assert retained == {
        "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "source_owner": "paper",
        "receiver_owner": mapping["portable_id"],
        "incoming_pinned_at": STAMP,
        "receiver_pinned_at": current,
    }
    # A failed atomic retention cannot leak its new archive row or a portable job.
    from paper_daily import queue_pins

    later = "2026-11-02T00:00:00+00:00"
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        observation = observe_target(conn, "paper", mapping["local_id"], "queue_pin")
        with expecting(conn, [observation]):
            conn.execute("UPDATE pins SET pinned_at=? WHERE scope='queue'", (later,))
            conn.commit()
    pending = a.journal.pending()
    original = queue_pins.retain_imports_in

    def fail_after_retention(conn, records):
        original(conn, records)
        raise RuntimeError("simulated storage failure")

    retry_id = str(uuid4())
    prepared = importer.prepare(package, request_id=retry_id, replace=True)
    queue_pins.retain_imports_in = fail_after_retention
    try:
        with pytest.raises(RuntimeError, match="simulated storage"):
            importer.apply(prepared)
    finally:
        queue_pins.retain_imports_in = original
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert archived(conn) == rows
        assert conn.execute("SELECT pinned_at FROM pins").fetchall() == [(later,)]
    assert a.journal.pending() == pending
    importer.apply(importer.prepare(package, request_id=retry_id, replace=True))
    with closing(sqlite3.connect(a.journal.path)) as conn:
        retained_rows = archived(conn)
        assert len(retained_rows) == 2 and rows[0] in retained_rows
    rows = retained_rows
    backup = tmp_path / "managed-preserved.zip"
    sync_recovery.create(a.journal.path, backup)
    with zipfile.ZipFile(backup) as z:
        assert [
            json.loads(row) for row in z.read("tables/research_history_archive.jsonl").splitlines()
        ] == rows

    detached = tmp_path / "managed-detached"
    sync_recovery.restore_detached(backup, detached)
    for index in range(2):
        adopter = RecoveryAdoptionService(detached / "papers.db")
        inspected = adopter.inspect()
        assert inspected.report["supported"]
        copy = adopter.prepare(
            inspected,
            tmp_path / f"managed-copy-{index}",
            backup_output=tmp_path / f"managed-copy-{index}.zip",
            request_id=str(uuid4()),
        )
        with closing(sqlite3.connect(copy["database"])) as conn:
            assert conn.execute("SELECT pinned_at FROM pins").fetchall() == [(later,)]
        with zipfile.ZipFile(copy["backup"]) as z:
            provenance = [
                json.loads(row)
                for row in z.read("tables/research_recovery_provenance.jsonl").splitlines()
            ]

        def contains(value, expected):
            if value == expected:
                return True
            if isinstance(value, dict):
                return any(contains(item, expected) for item in value.values())
            if isinstance(value, list):
                return any(contains(item, expected) for item in value)
            if isinstance(value, str):
                try:
                    decoded = json.loads(value)
                except ValueError:
                    return False
                return contains(decoded, expected) if decoded != value else False
            return False

        assert all(any(contains(item, row) for item in provenance) for row in rows)
        detached = tmp_path / f"managed-detached-{index}"
        sync_recovery.restore_detached(copy["backup"], detached)


def test_raw_package_changed_during_import_rolls_back_new_history(package, tmp_path, monkeypatch):
    from paper_daily import queue_pins

    database = target(monkeypatch, tmp_path / "raw")
    bundle.import_(package, pdfs=False)
    current = "2026-11-03T00:00:00+00:00"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE pins SET pinned_at=?", (current,))
    retain = queue_pins.retain_imports_in

    def changed_package(conn, records):
        retain(conn, records)
        with package.open("ab") as stream:
            stream.write(b"changed package snapshot")

    monkeypatch.setattr(queue_pins, "retain_imports_in", changed_package)
    with pytest.raises(ValueError, match="package changed"):
        bundle.import_(package, pdfs=False, replace=True)
    with closing(sqlite3.connect(database)) as conn:
        assert archived(conn) == []
        assert conn.execute("SELECT pinned_at FROM pins").fetchall() == [(current,)]


def test_raw_import_refuses_unsafe_cleanup_without_modifying_receiver(
    package, tmp_path, monkeypatch
):
    from test_queue_pin_cleanup import PREVIOUS

    database = target(monkeypatch, tmp_path / "old-runtime")
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("DROP TRIGGER paperfact_pin_membership_delete")
        conn.execute(PREVIOUS)
    before = database.read_bytes()
    with pytest.raises(ValueError, match="cleanup"):
        bundle.import_(package, pdfs=False)
    assert database.read_bytes() == before
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT * FROM pins").fetchall() == []
        assert archived(conn) == []


def test_enrolled_import_refuses_late_unsafe_cleanup_then_explicit_install_retry(
    package, pair, tmp_path
):
    from test_queue_pin_cleanup import old_cleanup

    _server, a, _b, _fa, _fb, _ta, _tb = pair
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="a")
        conn.commit()
    root = tmp_path / "guarded-import"
    root.mkdir()
    importer = PackageImporter(a.journal.path, root)
    request = str(uuid4())
    prepared = importer.prepare(package, request_id=request)
    old_cleanup(a)
    before = a.journal.pending()
    with pytest.raises(ValueError, match="cleanup"):
        importer.apply(prepared)
    with pytest.raises(ValueError, match="cleanup"):
        importer.prepare(package, request_id=request)
    assert a.journal.pending() == before
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert conn.execute("SELECT * FROM pins").fetchall() == []
        assert archived(conn) == []
    assert list(root.glob(".package-import-*")) == []
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="a")
        conn.commit()
    result = importer.apply(importer.prepare(package, request_id=request))
    assert result["queue_pins"] == 1
