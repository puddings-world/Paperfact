"""Actual unbound import ownership, lifetime and exact historical source reads."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from test_claim_jobs import claims as claims
from test_claim_jobs import job
from test_claim_jobs import ready as ready
from test_claim_jobs import workspace as workspace
from test_package_import import package as package
from test_package_import import rewrite_package
from test_package_import import rich_package as rich_package

from paper_daily import bundle, source_provenance, source_snapshots, store
from paper_daily import local_source_owners as owners
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import capture_owner
from paper_daily.sync_documents import MAX_PDF_BYTES


@pytest.fixture
def receiver(tmp_path, monkeypatch):
    root = tmp_path / "receiver"
    root.mkdir()
    database = root / "papers.db"
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    store.init_db()
    return database, root


def displayed(database, paper_id="ref:example"):
    with closing(sqlite3.connect(database)) as conn:
        row = conn.execute(
            "SELECT body_json,source_hash,document_hash FROM paper_claim_sets WHERE paper_id=?",
            (paper_id,),
        ).fetchone()
    return dict(
        json.loads(row[0]), source_hash=row[1], document_hash=row[2], paper_id=paper_id, known=True
    )


def import_owned(rich_package, receiver):
    archive, current_hash, original_hash, body = rich_package
    report = bundle.import_(archive, pdfs=False)
    database, root = receiver
    owner = capture_owner(database, "ref:example")
    return report, owner, displayed(database), current_hash, original_hash, body, root


def test_unbound_import_opens_owned_A_while_current_B_stays_unchanged(rich_package, receiver):
    report, owner, expected, current, original, _body, root = import_owned(rich_package, receiver)
    before = (root / "pdf/ref_example.pdf").read_bytes()
    assert hashlib.sha256(before).hexdigest() == current
    snapshot = owners.prepare(owner, expected)
    assert snapshot.document_hash == original
    assert hashlib.sha256(snapshot.data).hexdigest() == original
    assert owners.metadata_current(snapshot)
    assert (root / "pdf/ref_example.pdf").read_bytes() == before
    assert report["owned_originals"] == 1
    rows = owners.list_owned(owner.database)
    assert len(rows) == 1
    metadata = json.loads(rows[0]["owner_json"])
    assert metadata["database_identity"] == generation._identity(owner.database)
    assert metadata["paper_id"] == metadata["source_owner_id"] == "ref:example"
    assert metadata["binding"] is None
    assert len(metadata["parent_lifecycle"]) == 32
    # Repeated archive import does not create a second receipt or change bytes.
    again = bundle.import_(rich_package[0], pdfs=False)
    assert again["owned_originals"] == 0 and owners.list_owned(owner.database) == rows
    assert owners.metadata_current(snapshot)


def test_import_rollback_has_no_active_owner_and_retry_succeeds(
    rich_package, receiver, monkeypatch
):
    database, _root = receiver
    original = owners.register_import_in

    def fail_after_ownership(conn, prepared):
        original(conn, prepared)
        raise OSError("fixture final write failed")

    monkeypatch.setattr(owners, "register_import_in", fail_after_ownership)
    with pytest.raises(OSError, match="final write"):
        bundle.import_(rich_package[0], pdfs=False)
    assert owners.list_owned(database) == []
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM paper_claim_sets").fetchone()[0] == 0
    monkeypatch.setattr(owners, "register_import_in", original)
    assert bundle.import_(rich_package[0], pdfs=False)["owned_originals"] == 1


def test_no_receipt_is_granted_by_claim_row_and_matching_filename_alone(rich_package, receiver):
    _report, owner, expected, _current, _original, _body, _root = import_owned(
        rich_package, receiver
    )
    with store.connect() as conn:
        conn.execute("DELETE FROM " + owners.TABLE)
    with pytest.raises(ValueError, match="no current receiver-owned"):
        owners.prepare(owner, expected)
    assert owners.list_owned(owner.database) == []


@pytest.mark.parametrize("change", ["claim", "delete_recreate", "receipt", "bytes", "database"])
def test_read_only_snapshot_rejects_stale_current_ownership(rich_package, receiver, change):
    import os
    import shutil

    _report, owner, expected, _current, _original, _body, _root = import_owned(
        rich_package, receiver
    )
    snapshot = owners.prepare(owner, expected)
    if change == "claim":
        with store.connect() as conn:
            changed = dict(expected)
            changed = {
                key: value
                for key, value in changed.items()
                if key not in {"known", "paper_id", "source_hash", "document_hash"}
            }
            changed["generation"] = dict(changed["generation"], requested_model="new-model")
            conn.execute(
                "UPDATE paper_claim_sets SET body_json=?,written_at=?",
                (json.dumps(changed), "2026-10-31T00:00:00+00:00"),
            )
    elif change == "delete_recreate":
        with store.connect() as conn:
            row = dict(conn.execute("SELECT * FROM papers WHERE id='ref:example'").fetchone())
            conn.execute("DELETE FROM papers WHERE id='ref:example'")
            conn.execute(
                "INSERT INTO papers("
                + ",".join(row)
                + ") VALUES("
                + ",".join("?" for _ in row)
                + ")",
                tuple(row.values()),
            )
    elif change == "receipt":
        with store.connect() as conn:
            conn.execute("DELETE FROM " + owners.TABLE)
    elif change == "bytes":
        before = snapshot.source.stat()
        data = bytearray(snapshot.data)
        data[-1] ^= 1
        snapshot.source.write_bytes(data)
        os.utime(snapshot.source, ns=(before.st_atime_ns, before.st_mtime_ns))
    else:
        replacement = owner.database.with_suffix(".replacement")
        shutil.copy2(owner.database, replacement)
        os.replace(replacement, owner.database)
    assert owners.metadata_current(snapshot) is False
    with pytest.raises((ValueError, OSError)):
        owners.prepare(owner, expected)


def test_empty_ordinary_import_keeps_private_table_lazy(package, receiver):
    database, _root = receiver
    bundle.import_(package[0], pdfs=False)
    with closing(sqlite3.connect(database)) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (owners.TABLE,)
        ).fetchone()
    assert owners.list_owned(database) == []


def test_size_policy_retains_generated32MiB_and_trusted_import150MiB():
    row = dict(
        request_id="import:fixture",
        owner_json=json.dumps(
            dict(
                format="paperfact.source-owner.v1",
                database_identity=[1, 2],
                binding=None,
                paper_id="paper",
                parent_lifecycle="a" * 32,
                source_owner_id="paper",
            )
        ),
        sha256="b" * 64,
        size=80 * 1024**2,
        media_type="application/pdf",
    )
    with pytest.raises(ValueError):
        source_snapshots.validate(row)
    assert owners.validate(row) == row
    assert source_provenance.validate(source_provenance.wrap(row)) == row
    assert (
        source_snapshots.source_path("C:/fixture/papers.db", row, max_pdf_bytes=MAX_PDF_BYTES).name
        == row["sha256"] + ".pdf"
    )
    for policy in (True, False, 0, -1, MAX_PDF_BYTES + 1, "150"):
        with pytest.raises(ValueError, match="policy"):
            source_snapshots.validate(row, max_pdf_bytes=policy)


def test_cancellation_never_adds_research_or_owner(rich_package, receiver):
    database, _root = receiver
    with zipfile.ZipFile(rich_package[0]) as archive:
        manifest, tables, _files = bundle._validated(archive)
        assert (
            owners.prepare_import(database, archive, manifest, tables, cancelled=lambda: True)
            is None
        )
    assert owners.list_owned(database) == []
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0


def test_actual_generated_receipt_uses_same_read_only_local_source_seam(claims):
    from paper_daily import annotation_reader

    current = job(claims)
    assert current.run().status == "accepted"
    database = claims[0][0]
    expected = annotation_reader.saved(database, "paper", "claims")
    owner = capture_owner(database, "paper")
    snapshot = owners.prepare(owner, expected)
    assert snapshot.document_hash == expected["document_hash"]
    assert snapshot.data == claims[0][2].path.read_bytes()
    assert snapshot.receipt_path is not None and owners.metadata_current(snapshot)
    with closing(sqlite3.connect(database)) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (owners.TABLE,)
        ).fetchone()
    snapshot.receipt_path.unlink()
    assert not owners.metadata_current(snapshot)
    with pytest.raises(ValueError, match="no current receiver-owned"):
        owners.prepare(owner, expected)


def test_mismatching_cached_original_is_never_overwritten(rich_package, receiver):
    database, root = receiver
    digest = rich_package[2]
    target = root / bundle._claim_source_relative("ref:example", digest)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"Keep this conflicting file")
    with pytest.raises(ValueError, match="size changed"):
        bundle.import_(rich_package[0], replace=True, pdfs=False)
    assert target.read_bytes() == b"Keep this conflicting file"
    assert owners.list_owned(database) == []
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0


def test_native_staged_source_change_aborts_sql_without_partial_owner(
    rich_package, receiver, monkeypatch
):
    database, _root = receiver
    original = owners.ensure_import_in

    def change(conn, prepared):
        prepared[0].path.write_bytes(b"Changed after verification")
        original(conn, prepared)

    monkeypatch.setattr(owners, "ensure_import_in", change)
    with pytest.raises(ValueError, match="changed before ownership"):
        bundle.import_(rich_package[0], pdfs=False)
    assert owners.list_owned(database) == []
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0


def test_reader_binding_change_while_staging_cannot_gain_ownership(rich_package, receiver):
    database, _root = receiver
    with zipfile.ZipFile(rich_package[0]) as archive:
        manifest, tables, _files = bundle._validated(archive)
        prepared = owners.prepare_import(database, archive, manifest, tables)
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE research_sync_binding(id INTEGER,workspace TEXT,origin TEXT)")
        conn.execute("INSERT INTO research_sync_binding VALUES(1,'new-workspace','new-device')")
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="workspace changed"):
            owners.ensure_import_in(conn, prepared)
    assert owners.list_owned(database) == []


def test_independent_recovery_archives_receipts_without_rebinding(rich_package, receiver, tmp_path):
    from paper_daily import sync_recovery

    original = rich_package[2]

    def receipt_only(manifest, _tables, values):
        source = values["files/" + manifest["claim_sources"]["ref:example"]["path"]]
        for name in list(values):
            if name.startswith("files/") and not name.startswith("files/pdf/"):
                del values[name]
        values["files/pdf/ref_example.pdf"] = source
        manifest["pdfs"]["ref:example"] = {"sha256": original, "bytes": len(source), "url": None}

    incoming = rewrite_package(
        rich_package[0], tmp_path / "receipt-only.zip", transform=receipt_only
    )
    bundle.import_(incoming, pdfs=False)
    owner = capture_owner(receiver[0], "ref:example")
    expected = displayed(receiver[0])
    before = owners.list_owned(owner.database)
    backup = tmp_path / "local-source-backup.zip"
    sync_recovery.create(owner.database, backup)
    with zipfile.ZipFile(backup) as archive:
        assert hashlib.sha256(archive.read("objects/" + original)).hexdigest() == original
    destination = tmp_path / "detached-local-owner"
    sync_recovery.restore_detached(backup, destination)
    database = destination / "papers.db"
    assert owners.list_owned(database) == []
    with closing(sqlite3.connect(database)) as conn:
        archived = conn.execute(
            "SELECT data FROM recovery_records WHERE table_name=?", (owners.TABLE,)
        ).fetchall()
        assert [json.loads(row[0]) for row in archived] == before
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (owners.TABLE,)
        ).fetchone()
    # A fresh viewed owner still cannot turn archive-only observations into active authority.
    detached = capture_owner(database, "ref:example")
    with pytest.raises(ValueError, match="no current receiver-owned"):
        owners.prepare(detached, expected)


def test_unrepresented_unbound_primary_or_deck_still_blocks_full_recovery(
    rich_package, receiver, tmp_path
):
    from paper_daily import sync_recovery

    import_owned(rich_package, receiver)
    with pytest.raises(sync_recovery.RecoveryError, match="complete migration"):
        sync_recovery.create(receiver[0], tmp_path / "must-not-be-partial.zip")
    assert not (tmp_path / "must-not-be-partial.zip").exists()


def test_selected_import_receipt_does_not_scan_unrelated_private_receipts(rich_package, receiver):
    _report, owner, expected, _current, _original, _body, _root = import_owned(
        rich_package, receiver
    )
    context = json.loads(owner._json)
    namespace = source_snapshots._namespace(context)
    root = owner.database.parent / ".paperfact-source-snapshots" / namespace
    root.mkdir(parents=True)
    (root / "unrelated.json").write_bytes(b"unrelated invalid private metadata")
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO " + owners.TABLE + " VALUES(?,?,?,?,?)",
            ("unrelated", "bad", "f" * 64, 1, "application/pdf"),
        )
    snapshot = owners.prepare(owner, expected)
    assert owners.metadata_current(snapshot)
    # A full archival inventory remains fail-closed for that unrelated bad row.
    with pytest.raises(ValueError):
        owners.list_owned(owner.database)


def test_viewer_resolution_is_read_only_and_requires_loaded_owner(rich_package, receiver):
    _report, owner, expected, _current, _original, _body, _root = import_owned(
        rich_package, receiver
    )
    with closing(sqlite3.connect(owner.database)) as conn:
        before = list(conn.iterdump())
    snapshot = owners.prepare(owner, expected)
    assert owners.metadata_current(snapshot)
    assert owners.prepare(owner, expected, cancelled=lambda: True) is None
    with pytest.raises(ValueError, match="actual loaded"):
        owners.prepare(object(), expected)
    assert not owners.metadata_current(object())
    with closing(sqlite3.connect(owner.database)) as conn:
        assert list(conn.iterdump()) == before


def test_cancel_after_byte_verification_does_not_return_a_ready_proof(
    rich_package, receiver, monkeypatch
):
    _report, owner, expected, _current, _original, _body, _root = import_owned(
        rich_package, receiver
    )
    cancelled = False
    original = owners._read_pdf

    def finish_then_cancel(*args, **kwargs):
        nonlocal cancelled
        value = original(*args, **kwargs)
        cancelled = True
        return value

    monkeypatch.setattr(owners, "_read_pdf", finish_then_cancel)
    assert owners.prepare(owner, expected, cancelled=lambda: cancelled) is None


@pytest.mark.parametrize("budget", ["bytes", "entries"])
def test_generated_receipt_scan_is_bounded_and_never_changes_source(claims, monkeypatch, budget):
    from paper_daily import annotation_reader

    assert job(claims).run().status == "accepted"
    database = claims[0][0]
    owner = capture_owner(database, "paper")
    expected = annotation_reader.saved(database, "paper", "claims")
    receipts = source_snapshots.list_owned(database)
    source = source_snapshots.source_path(database, receipts[0])
    before = source.read_bytes()
    if budget == "bytes":
        monkeypatch.setattr(owners, "MAX_METADATA", 1)
    else:
        monkeypatch.setattr(source_snapshots, "MAX_RECEIPTS", 1)
        receipt = source_snapshots.receipt_path(database, receipts[0])
        receipt.with_suffix(".part").write_bytes(b"pending unrelated stage")
    with pytest.raises(ValueError, match="budget"):
        owners.prepare(owner, expected)
    assert source.read_bytes() == before


def test_original_pdf_validation_failure_never_grants_sql_ownership(
    rich_package, receiver, monkeypatch
):
    database, _root = receiver

    def unreadable(_data):
        raise ValueError("Original source PDF is not readable")

    monkeypatch.setattr(owners, "validate_pdf", unreadable)
    with pytest.raises(ValueError, match="not readable"):
        bundle.import_(rich_package[0], pdfs=False)
    assert owners.list_owned(database) == []
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_claim_sets").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
