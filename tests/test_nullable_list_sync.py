"""Nullable legacy list metadata survives v2 capture, sync and packaging exactly."""

import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from test_enrollment_history_peer import peer
from test_sync_journal import operation
from test_workspace_enrollment import pdf, prepare
from test_workspace_enrollment import source as source

from paper_daily import bundle, store, sync_recovery
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_journal import canonical_operation
from paper_daily.sync_projection import read_manifest


@pytest.mark.parametrize("value", [None, "", " ", "Background research"])
def test_unbound_note_enroll_peer_export_and_recovery_are_lossless(
    source, tmp_path, monkeypatch, value
):
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE lists SET note=?", (value,))
    primary = pdf(source)
    result = prepare(source, tmp_path, pdfs={"paper": primary})
    database = Path(result["database"])
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT note FROM lists").fetchone()[0] == value
        list_op = next(json.loads(row[0]) for row in conn.execute(
            "SELECT envelope FROM paperfact_sync_operations")
            if json.loads(row[0])["entity_type"] == "list")
        assert list_op["payload"]["note"] == value
    a, b, service, ta, tb, _portable, _local, _artifacts = peer(result, tmp_path)
    with closing(sqlite3.connect(b.journal.path)) as conn:
        assert conn.execute("SELECT note FROM lists").fetchone()[0] == value
    projected = read_manifest(b.journal.path, workspace_id=result["workspace_id"], schema_version=2)
    assert projected["lists"][0]["note"] == value
    # Renaming emits another captured put; it must not normalize the unchanged note.
    with closing(sqlite3.connect(database, factory=CaptureConnection)) as conn, conn:
        conn.execute("UPDATE lists SET name='Renamed route'")
    pending = a.journal.pending()
    assert any(op["entity_type"] == "list" and op["payload"]["note"] == value for op in pending)
    a.sync_once(service, ta, limit=1000)
    b.sync_once(service, tb, limit=1000)
    with closing(sqlite3.connect(b.journal.path)) as conn:
        assert conn.execute("SELECT name,note FROM lists").fetchone() == ("Renamed route", value)
    monkeypatch.setattr(store, "DB_PATH", b.journal.path)
    monkeypatch.setattr(bundle, "DATA_DIR", b.journal.path.parent)
    monkeypatch.setattr(bundle, "PDF_DIR", tmp_path / "peer-reader")
    package = tmp_path / "list.zip"
    bundle.export("list", package)
    with zipfile.ZipFile(package) as z:
        assert json.loads(z.read("manifest.json"))["list"]["note"] == value
    with zipfile.ZipFile(result["backup"]) as z:
        assert json.loads(z.read("tables/lists.jsonl"))["note"] == value
    restored = tmp_path / "restored"
    sync_recovery.restore_detached(result["backup"], restored)
    with closing(sqlite3.connect(restored / "papers.db")) as conn:
        assert conn.execute("SELECT note FROM lists").fetchone()[0] == value


def test_only_v2_closed_list_note_contract_allows_null():
    first = operation()
    first["payload"]["note"] = None
    with pytest.raises(ValueError):
        canonical_operation(first)
    modern = dict(first, version=2, incarnation="list-epoch", parents=[], structure_revision=0)
    assert json.loads(canonical_operation(modern))["payload"]["note"] is None
    for value in (False, 0, 1.0, [], {}, "x" * (128 * 1024 + 1)):
        with pytest.raises(ValueError):
            canonical_operation(dict(modern, payload={"name": "Reading", "note": value}))
    with pytest.raises(ValueError):
        canonical_operation(dict(modern, payload={"name": "Reading", "note": None, "unknown": 1}))
