"""Maintenance connection optimizations must survive real DB replacement and capture."""

import os
import sqlite3
from contextlib import closing

from paper_daily import store
from paper_daily.sync_capture import CaptureConnection, install
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_writer


def prepared(path, device):
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
    prepare(path, workspace_id="fixture-workspace", device_id=device)
    SyncClient(Journal(path, workspace_id="fixture-workspace", device_id=device), research_writer)
    with closing(sqlite3.connect(path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="fixture-workspace", device_id=device)
        conn.commit()


def test_same_path_replacement_reestablishes_wal_and_captures_new_device(tmp_path, monkeypatch):
    database, replacement = tmp_path / "research.sqlite", tmp_path / "replacement.sqlite"
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    prepared(database, "old-device")
    with store.connect(path=database) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    prepared(replacement, "new-device")
    with closing(sqlite3.connect(replacement)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    os.replace(replacement, database)  # Real closed-handle boundary; no GC, retry or sleep.
    with store.connect(path=database) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        store.upsert_papers(
            conn,
            [
                {
                    "id": "paper",
                    "title": "New research",
                    "venue": "Fixture",
                    "year": 2026,
                    "source": "fixture",
                }
            ],
        )
    client = SyncClient.attach_existing(
        Journal.attach_existing(database, workspace_id="fixture-workspace", device_id="new-device"),
        research_writer,
    )
    operations = client.journal.pending()
    assert operations and all(operation["device_id"] == "new-device" for operation in operations)
    assert [
        operation["payload"]["title"]
        for operation in operations
        if operation["entity_type"] == "paper"
    ] == ["New research"]
