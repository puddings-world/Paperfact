"""Real full list packages retain old source A independently from current primary B."""

import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from test_reading_positions import pdf_bytes, prepared, records, view
from test_sync_capture import seed

from paper_daily import bundle, enrollment_history, source_snapshots, store
from paper_daily import local_source_owners as owners
from paper_daily import reading_position_ops as operations
from paper_daily import reading_position_packages as packages
from paper_daily import reading_positions as positions
from paper_daily.package_import import PackageImporter
from paper_daily.sync_capture import CaptureConnection, install

STAMP = "2026-10-30T10:00:00+00:00"


def workspace(root, monkeypatch, *, existing=False, current=None):
    root.mkdir()
    database = root / "papers.db"
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    store.init_db()
    (root / "pdf").mkdir()
    if existing:
        seed()
    if current:
        (root / "pdf/local-paper.pdf").write_bytes(current)
    return database


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "fetch", lambda *a, **kw: pytest.fail("Package attempted network"))
    database = workspace(tmp_path / "source", monkeypatch, existing=True)
    path = database.parent / "pdf/local-paper.pdf"
    original = pdf_bytes()
    path.write_bytes(original)
    attempt = prepared(view(database, path), 4)
    operations.save(attempt)
    current = pdf_bytes(2, "Current B")
    path.write_bytes(current)
    with store.connect() as conn:
        conn.execute("INSERT INTO pins VALUES('queue','local-paper',?)", (STAMP,))
    archive = tmp_path / "research.zip"
    return database, path, original, current, archive, attempt


def exported(source):
    _database, _path, _original, _current, archive, _attempt = source
    bundle.export("list", archive)
    with zipfile.ZipFile(archive) as zipped:
        return json.loads(zipped.read("manifest.json"))


def test_default_full_package_has_exact_A_position_and_B_primary_with_union_capabilities(source):
    database, path, original, current, archive, attempt = source
    before = records(database, positions.TABLE)
    manifest = exported(source)
    assert manifest["capabilities"] == ["queue_pin", "reading_position"]
    item = manifest["position_sources"][0]
    assert item == dict(
        paper_id="local-paper",
        sha256=attempt.view.highlight.fingerprint,
        size=len(original),
        path=packages.relative("local-paper", attempt.view.highlight.fingerprint).as_posix(),
    )
    with zipfile.ZipFile(archive) as zipped:
        saved, tables, declared = bundle._validated(zipped)
        assert saved == manifest and tables[positions.TABLE][0]["page"] == 4
        assert zipped.read("files/" + item["path"]) == original
        assert zipped.read("files/pdf/local-paper.pdf") == current
        assert declared[item["path"]] == "local-paper"
    assert records(database, positions.TABLE) == before
    assert path.read_bytes() == current


def test_lightweight_mode_requires_explicit_PDF_choice_before_network_or_output(
    source, monkeypatch
):
    monkeypatch.setattr(bundle, "pdf_record", lambda *a: pytest.fail("No-PDF refusal was late"))
    with pytest.raises(ValueError, match="Include PDFs"):
        bundle.export("list", source[4], with_pdfs=False)
    assert not source[4].exists()


def test_unbound_import_installs_receiver_owned_A_without_replacing_existing_C_primary(
    source, tmp_path, monkeypatch
):
    exported(source)
    _database, _path, original, _current, archive, attempt = source
    other = pdf_bytes(3, "Receiver C")
    destination = workspace(tmp_path / "receiver", monkeypatch, existing=True, current=other)
    result = bundle.import_(archive, pdfs=False)
    assert result["pdf_conflicts"] == ["local-paper"]
    assert result["reading_positions"] == 1
    assert (destination.parent / "pdf/local-paper.pdf").read_bytes() == other
    rows = records(destination, positions.TABLE)
    assert rows == [("local-paper", attempt.view.highlight.fingerprint, 4, STAMP, "entered")]
    receipt = next(
        row
        for row in owners.list_owned(destination)
        if row["sha256"] == attempt.view.highlight.fingerprint
    )
    metadata = json.loads(receipt["owner_json"])
    assert metadata["format"] == "paperfact.position-source-owner.v2"
    assert (
        metadata["database_identity"]
        != json.loads(attempt.view.highlight.owner._json)["database_identity"]
    )
    assert source_snapshots.source_path(destination, receipt).read_bytes() == original
    assert result["queue_pins"] == 1
    assert bundle.import_(archive, pdfs=False)["reading_positions"] == 0
    assert len(owners.list_owned(destination)) == 1


def test_unbound_new_receiver_and_retained_conflicting_position_are_atomic_and_durable(
    source, tmp_path, monkeypatch
):
    exported(source)
    destination = workspace(tmp_path / "receiver", monkeypatch)
    first = bundle.import_(source[4], pdfs=False)
    assert first["reading_positions"] == 1
    with store.connect() as conn:
        conn.execute("UPDATE reading_positions SET page=2")
    result = bundle.import_(source[4], pdfs=False)
    assert result["reading_positions"] == 0 and result["reading_positions_kept"] == 1
    assert records(destination, positions.TABLE)[0][2] == 2
    with closing(sqlite3.connect(destination)) as conn:
        history = enrollment_history.archived(conn)
    retained = [row for row in history if row["protocol"] == "reading_position_import_v1"]
    assert len(retained) == 1
    assert bundle.import_(source[4], pdfs=False)["reading_positions_kept"] == 1
    with closing(sqlite3.connect(destination)) as conn:
        assert len(enrollment_history.archived(conn)) == len(history)
    from paper_daily import sync_recovery
    from paper_daily.workspace_enrollment import EnrollmentService

    output = tmp_path / "retained-import-backup.zip"
    service = EnrollmentService(destination)
    selected = {"local-paper": destination.parent / "pdf/local-paper.pdf"}
    assert service.plan(pdfs=selected)["supported"]
    service.prepare(
        tmp_path / "retained-import-new-copy",
        backup_output=output,
        request_id="eacb1399-7059-4aa6-8602-8cc02b329abb",
        pdfs=selected,
    )
    sync_recovery.restore_detached(output, tmp_path / "retained-import-restored")
    restored = tmp_path / "retained-import-restored/papers.db"
    assert records(restored, positions.TABLE)[0][2] == 2
    assert records(restored, positions.RECEIPTS) == []
    with closing(sqlite3.connect(restored)) as connection:
        preserved = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_history_archive'"
            )
        ]
    assert any(row["protocol"] == "reading_position_import_v1" for row in preserved)


def test_failure_after_file_install_rolls_back_position_and_owner_and_retry_succeeds(
    source, tmp_path, monkeypatch
):
    exported(source)
    destination = workspace(tmp_path / "receiver", monkeypatch)
    original = owners.register_import_in

    def late_failure(conn, prepared):
        original(conn, prepared)
        raise OSError("Fixture late package failure")

    monkeypatch.setattr(owners, "register_import_in", late_failure)
    with pytest.raises(OSError, match="late package"):
        bundle.import_(source[4], pdfs=False)
    assert records(destination, positions.TABLE) == []
    assert owners.list_owned(destination) == []
    assert records(destination, "papers") == []
    assert not (destination.parent / "pdf/local-paper.pdf").exists()
    monkeypatch.setattr(owners, "register_import_in", original)
    assert bundle.import_(source[4], pdfs=False)["reading_positions"] == 1


def rewrite(archive, destination, mutate):
    with zipfile.ZipFile(archive) as source:
        manifest = json.loads(source.read("manifest.json"))
        tables = json.loads(source.read("tables.json"))
        files = {name: source.read(name) for name in source.namelist() if name.startswith("files/")}
    mutate(manifest, tables, files)
    with zipfile.ZipFile(destination, "w") as target:
        target.writestr("manifest.json", json.dumps(manifest))
        target.writestr("tables.json", json.dumps(tables))
        for name, data in files.items():
            target.writestr(name, data)


@pytest.mark.parametrize(
    "change", ["missing", "hash", "bounds", "source_owner", "extra", "duplicate", "capability"]
)
def test_malformed_or_incomplete_position_packages_fail_before_research_writes(
    source, tmp_path, monkeypatch, change
):
    exported(source)
    changed = tmp_path / "changed.zip"

    def mutate(manifest, tables, files):
        item = manifest["position_sources"][0]
        if change == "missing":
            del files["files/" + item["path"]]
        elif change == "hash":
            files["files/" + item["path"]] = b"changed"
        elif change == "bounds":
            tables[positions.TABLE][0]["page"] = 500
        elif change == "source_owner":
            item["paper_id"] = "foreign"
        elif change == "extra":
            item["page_count"] = 10000
        elif change == "duplicate":
            tables[positions.TABLE].append(tables[positions.TABLE][0])
        else:
            manifest["capabilities"] = ["queue_pin"]

    rewrite(source[4], changed, mutate)
    destination = workspace(tmp_path / "receiver", monkeypatch)
    with pytest.raises((ValueError, KeyError)):
        bundle.import_(changed, pdfs=False)
    assert not records(destination, positions.TABLE)
    assert not records(destination, "papers")
    assert owners.list_owned(destination) == []


def test_enrolled_import_fresh_mapping_retains_exact_A_and_B_without_replaying_sender_owner(
    source, tmp_path, monkeypatch
):
    from test_reading_positions import make

    exported(source)
    receiver = tmp_path / "bound"
    receiver.mkdir()
    client = make(receiver / "papers.db", "b")
    with closing(sqlite3.connect(client.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="b")
        conn.commit()
    importer = PackageImporter(client.journal.path, receiver)
    prepared = importer.prepare(source[4])
    report = importer.apply(prepared)
    mapping = report["identity_mapping"]["local-paper"]
    assert mapping["local_id"] != "local-paper"
    rows = records(client.journal.path, positions.TABLE)
    assert rows == [
        (mapping["local_id"], source[5].view.highlight.fingerprint, 4, STAMP, "entered")
    ]
    from paper_daily.sync_source_files import resolved

    with client.journal.transaction() as conn:
        original = resolved(conn, mapping["portable_id"], source[5].view.highlight.fingerprint)
    assert original.read_bytes() == source[2]
    wire = json.dumps(client.journal.pending())
    assert str(source[0]) not in wire and "database_identity" not in wire
    before = client.journal.pending()
    again = importer.prepare(source[4])
    assert importer.apply(again)["replayed"]
    assert client.journal.pending() == before


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_missing_or_changed_A_never_exports_B_as_the_position_source(source, change):
    target = source[5].view.cached_path
    if change == "missing":
        target.unlink()
    else:
        data, stamp = target.read_bytes(), target.stat()
        target.write_bytes(b"X" + data[1:])
        import os

        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    source[4].write_bytes(b"previous export remains")
    with pytest.raises((ValueError, OSError)):
        bundle.export("list", source[4])
    assert source[4].read_bytes() == b"previous export remains"
    assert source[1].read_bytes() == source[3]


def test_position_change_during_packing_keeps_previous_output_and_new_local_position(
    source, monkeypatch
):
    check = packages.check_export

    def edited(proof):
        with store.connect() as conn:
            conn.execute("UPDATE reading_positions SET page=3")
        check(proof)

    monkeypatch.setattr(packages, "check_export", edited)
    source[4].write_bytes(b"prior complete export")
    with pytest.raises(ValueError, match="changed during export"):
        bundle.export("list", source[4])
    assert source[4].read_bytes() == b"prior complete export"
    assert records(source[0], positions.TABLE)[0][2] == 3


@pytest.mark.parametrize("change", ["position", "parent", "database"])
def test_receiver_change_after_staging_refuses_late_position_and_source_grant(
    source, tmp_path, monkeypatch, change
):
    import os

    exported(source)
    destination = workspace(tmp_path / "receiver", monkeypatch, existing=True, current=source[2])
    real = packages.prepare_import

    def staged(*args, **kwargs):
        proof = real(*args, **kwargs)
        if change == "position":
            with store.connect() as conn:
                conn.execute(
                    "INSERT INTO reading_positions VALUES(?,?,?,?,?)",
                    ("local-paper", source[5].view.highlight.fingerprint, 2, STAMP, "entered"),
                )
        elif change == "parent":
            with store.connect() as conn:
                conn.execute("DELETE FROM papers WHERE id='local-paper'")
                store.upsert_papers(
                    conn,
                    [
                        dict(
                            id="local-paper",
                            title="New lifetime",
                            venue="Fixture",
                            year=2026,
                            source="fixture",
                        )
                    ],
                )
        else:
            replacement = destination.with_name("replacement.db")
            with (
                closing(sqlite3.connect(destination)) as old,
                closing(sqlite3.connect(replacement)) as new,
            ):
                old.backup(new)
            os.replace(replacement, destination)
        return proof

    monkeypatch.setattr(packages, "prepare_import", staged)
    with pytest.raises(ValueError, match="changed"):
        bundle.import_(source[4], pdfs=False)
    assert owners.list_owned(destination) == []
    expected = 1 if change == "position" else 0
    assert len(records(destination, positions.TABLE)) == expected


def test_source_preparation_cancel_never_grants_position_ownership(source, tmp_path, monkeypatch):
    exported(source)
    destination = workspace(tmp_path / "receiver", monkeypatch)
    with zipfile.ZipFile(source[4]) as archive:
        manifest, tables, _declared = bundle._validated(archive)
        assert (
            packages.prepare_import(destination, archive, manifest, tables, cancelled=lambda: True)
            is None
        )
    assert owners.list_owned(destination) == []
    assert records(destination, positions.TABLE) == []


@pytest.mark.parametrize("change", ["missing", "changed", "ownership"])
def test_original_change_during_packing_preserves_previous_output(source, monkeypatch, change):
    database, _path, _original, _current, archive, attempt = source
    exported(source)
    previous = archive.read_bytes()
    real_check = packages.check_export

    def changed(proof):
        if change == "missing":
            attempt.view.cached_path.unlink()
        elif change == "changed":
            attempt.view.cached_path.write_bytes(b"changed original")
        else:
            with store.connect() as connection:
                connection.execute("DELETE FROM research_local_source_owners")
        return real_check(proof)

    monkeypatch.setattr(packages, "check_export", changed)
    with pytest.raises((OSError, ValueError)):
        bundle.export("list", archive)
    assert archive.read_bytes() == previous
    assert records(database, positions.TABLE)[0][2] == 4


@pytest.mark.parametrize("change", ["extra", "nested", "boolean", "unaware", "oversized", "same"])
def test_retained_import_history_is_closed_bounded_and_archive_only(change):
    incoming = dict(page=4, recorded_at=STAMP, method="entered")
    record = dict(
        package_sha256="b" * 64,
        source_owner="sender",
        receiver_owner="receiver",
        document_hash="a" * 64,
        incoming_json=json.dumps(incoming),
        receiver_json=json.dumps(dict(incoming, page=2)),
    )
    assert enrollment_history.validate_record("reading_position_import_v1", record) == {"a" * 64}
    if change == "extra":
        record["database_path"] = "must never be followed"
    elif change == "nested":
        record["incoming_json"] = json.dumps(dict(incoming, page_count=999))
    elif change == "boolean":
        record["incoming_json"] = json.dumps(dict(incoming, page=True))
    elif change == "unaware":
        record["incoming_json"] = json.dumps(dict(incoming, recorded_at="2026-10-30T10:00:00"))
    elif change == "oversized":
        record["receiver_json"] = " " * 4097
    else:
        record["receiver_json"] = record["incoming_json"]
    with pytest.raises(ValueError):
        enrollment_history.validate_record("reading_position_import_v1", record)


def test_retained_import_history_preserves_original_JSON_text_bytes_without_executing_it():
    incoming = '{ "method": "entered", "page": 4, "recorded_at": "2026-10-30T10:00:00+00:00" }'
    receiver = '{"page":2, "recorded_at":"2026-10-30T10:00:00+00:00", "method":"entered"}'
    record = dict(
        package_sha256="b" * 64,
        source_owner="sender",
        receiver_owner="receiver",
        document_hash="a" * 64,
        incoming_json=incoming,
        receiver_json=receiver,
    )
    envelope = enrollment_history.wrap("reading_position_import_v1", record)
    saved = json.loads(envelope["body_json"])
    assert saved["incoming_json"].encode() == incoming.encode()
    assert saved["receiver_json"].encode() == receiver.encode()
    assert enrollment_history.validate_record("reading_position_import_v1", saved) == {"a" * 64}


@pytest.mark.parametrize(
    "nested",
    [
        '{"page":4,"page":2,"recorded_at":"2026-10-30T10:00:00+00:00","method":"entered"}',
        '{"page":Infinity,"recorded_at":"2026-10-30T10:00:00+00:00","method":"entered"}',
    ],
)
def test_retained_import_historical_decoder_still_refuses_duplicates_and_nonfinite_values(nested):
    record = dict(
        package_sha256="b" * 64,
        source_owner="sender",
        receiver_owner="receiver",
        document_hash="a" * 64,
        incoming_json=nested,
        receiver_json=json.dumps(dict(page=2, recorded_at=STAMP, method="entered")),
    )
    with pytest.raises(ValueError):
        enrollment_history.validate_record("reading_position_import_v1", record)
