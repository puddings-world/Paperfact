"""Optional annotation tables preserve old packages and carry new research intact."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_annotation_content import EXAMPLES

from paper_daily import annotation_content as annotations
from paper_daily import bundle, store, sync_capture, sync_recovery
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_writer


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    monkeypatch.setattr(bundle, "DATA_DIR", tmp_path)
    monkeypatch.setattr(bundle, "PDF_DIR", tmp_path / "pdf")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                {
                    "id": "p",
                    "title": "Research",
                    "source": "fixture",
                    "year": 2026,
                    "venue": "Fixture",
                }
            ],
        )
        conn.execute(
            "INSERT INTO lists(id,name,created_at) VALUES('l','Research',?)",
            ("2026-01-01T00:00:00+00:00",),
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES('l','p',0,?)",
            ("2026-01-01T00:00:00+00:00",),
        )
    return tmp_path, store.DB_PATH


def add(conn, feature):
    body = json.dumps(EXAMPLES[feature], ensure_ascii=False)
    conn.execute(
        f"INSERT INTO {annotations.FEATURES[feature]} VALUES(?,?,?,?,?)",
        ("p", body, "b" * 64, None, "2026-01-01T00:00:00+00:00"),
    )


def test_annotation_bundle_import_and_reexport_preserve_exact_rows(workspace, monkeypatch):
    root, original = workspace
    with store.connect() as conn:
        for feature in EXAMPLES:
            add(conn, feature)
    package = root / "share.zip"
    bundle.export("l", package, with_pdfs=False)
    recipient = root / "recipient"
    recipient.mkdir()
    monkeypatch.setattr(store, "DB_PATH", recipient / "papers.db")
    monkeypatch.setattr(bundle, "DATA_DIR", recipient)
    monkeypatch.setattr(bundle, "PDF_DIR", recipient / "pdf")
    store.init_db()
    bundle.import_(package, pdfs=False)
    bundle.import_(package, pdfs=False)
    with closing(sqlite3.connect(original)) as before, store.connect() as after:
        for table in annotations.FEATURES.values():
            assert before.execute(f"SELECT * FROM {table}").fetchall() == [
                tuple(row) for row in after.execute(f"SELECT * FROM {table}")
            ]
    bundle.export("l", recipient / "again.zip", with_pdfs=False)


@pytest.mark.parametrize("legacy", [False, True])
def test_optional_tables_restore_without_becoming_required_in_old_archives(workspace, legacy):
    root, path = workspace
    with store.connect() as conn:
        for feature, table in annotations.FEATURES.items():
            if legacy:
                conn.execute(f"DROP TABLE {table}")
            elif feature in EXAMPLES:
                # Original legacy fixtures remain unchanged; claim sets have their
                # own exact-PDF archive fixtures in test_claim_archives.py.
                add(conn, feature)
    package = root / "backup.zip"
    sync_recovery.create(path, package)
    manifest = sync_recovery.inspect(package)
    present = {table["name"] for table in manifest["tables"]}
    assert (set(annotations.FEATURES.values()) <= present) is not legacy
    destination = root / "restored"
    sync_recovery.restore_detached(package, destination)
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        for feature, table in annotations.FEATURES.items():
            rows = conn.execute(f"SELECT body_json FROM {table}").fetchall()
            assert len(rows) == (1 if not legacy and feature in EXAMPLES else 0)
            if rows:
                assert json.loads(rows[0][0]) == EXAMPLES[feature]


def test_explicit_migration_of_bound_workspace_installs_new_capture_triggers(workspace):
    _root, path = workspace
    prepare(path, workspace_id="workspace", device_id="device")
    client = SyncClient(
        Journal(path, workspace_id="workspace", device_id="device"), research_writer
    )
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="device")
        sync_capture.capture_existing(conn)
    # Simulate an already bound earlier schema with no annotation tables.
    with closing(sqlite3.connect(path)) as conn, conn:
        for table in annotations.FEATURES.values():
            conn.execute(f"DROP TABLE {table}")
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="device")
        add(conn, "research_questions")
    operations = [op for op in client.journal.pending() if op["entity_type"] == "research_content"]
    assert len(operations) == 1
    assert operations[0]["payload"]["data"]["body_json"] == EXAMPLES["research_questions"]
