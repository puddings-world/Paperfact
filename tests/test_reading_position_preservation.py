"""New-copy enrollment and independent recovery preserve positions and old source A."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_reading_positions import pdf_bytes, prepared, records, view
from test_sync_capture import seed

from paper_daily import enrollment_history, store, sync_recovery
from paper_daily import reading_position_ops as operations
from paper_daily import reading_positions as positions
from paper_daily.workspace_enrollment import EnrollmentService


@pytest.fixture
def local(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    database = root / "papers.db"
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    store.init_db()
    seed()
    folder = root / "pdf"
    folder.mkdir()
    path = folder / "loaded.pdf"
    original = pdf_bytes()
    path.write_bytes(original)
    attempt = prepared(view(database, path), 4)
    operations.save(attempt)
    path.write_bytes(pdf_bytes(2, "Current B"))
    return database, path, original, attempt


def test_initial_enrollment_preserves_source_A_position_while_primary_B_is_current(local, tmp_path):
    database, path, original, attempt = local
    before = records(database, positions.TABLE)
    service = EnrollmentService(database)
    selected = {"local-paper": path}
    plan = service.plan(pdfs=selected)
    assert plan["supported"], plan["blockers"]
    assert plan["original_source_count"] == 1
    assert plan["archived_history_by_protocol"]["research_reading_position_receipts"] == 1
    request = str(uuid4())
    result = service.prepare(
        tmp_path / "new-copy",
        backup_output=tmp_path / "backup.zip",
        request_id=request,
        pdfs=selected,
    )
    target = Path(result["database"])
    assert records(database, positions.TABLE) == before == records(target, positions.TABLE)
    assert records(target, positions.RECEIPTS) == []
    with closing(sqlite3.connect(target)) as conn:
        archived = enrollment_history.archived(conn)
        assert any(item["protocol"] == positions.RECEIPTS for item in archived)
        wire = [
            json.loads(row[0])
            for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        ]
        original_op = next(
            op for op in wire if op.get("payload", {}).get("feature") == "original_source"
        )
        assert original_op["payload"]["slot"] == attempt.view.highlight.fingerprint
        assert original_op["payload"]["assets"][0]["size"] == len(original)
        primary = next(op for op in wire if op["entity_type"] == "paper_document")
        assert primary["payload"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert primary["payload"]["sha256"] != attempt.view.highlight.fingerprint
        serialized = json.dumps(wire)
        assert str(database) not in serialized and "database_identity" not in serialized
    assert sync_recovery.inspect(tmp_path / "backup.zip")


@pytest.mark.parametrize("change", ["missing", "changed", "ownership", "page"])
def test_enrollment_refuses_missing_changed_or_unowned_old_original(local, change):
    database, path, _original, attempt = local
    if change == "missing":
        attempt.view.cached_path.unlink()
    elif change == "changed":
        attempt.view.cached_path.write_bytes(b"wrong")
    elif change == "ownership":
        with store.connect() as conn:
            conn.execute("DELETE FROM research_local_source_owners")
    else:
        with store.connect() as conn:
            conn.execute("UPDATE reading_positions SET page=500")
    with pytest.raises((ValueError, OSError)):
        EnrollmentService(database).plan(pdfs={"local-paper": path})


def test_independent_backup_restores_position_A_and_bytes_without_old_active_identity(
    local, tmp_path
):
    database, path, original, attempt = local
    output = tmp_path / "independent.zip"
    result = EnrollmentService(database).prepare(
        tmp_path / "enrolled",
        backup_output=output,
        request_id=str(uuid4()),
        pdfs={"local-paper": path},
    )
    enrolled = Path(result["database"])
    manifest = sync_recovery.inspect(output)
    with zipfile.ZipFile(output) as archive:
        assert archive.read("objects/" + attempt.view.highlight.fingerprint) == original
        assert positions.TABLE in [item["name"] for item in manifest["tables"]]
    destination = tmp_path / "restored"
    result = sync_recovery.restore_detached(output, destination)
    target = destination / "papers.db"
    assert records(target, positions.TABLE) == records(enrolled, positions.TABLE)
    assert records(target, positions.RECEIPTS) == []
    with closing(sqlite3.connect(target)) as conn:
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='research_capture_binding'"
        ).fetchall()
        history = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_history_archive'"
            )
        ]
        assert any(row["protocol"] == positions.RECEIPTS for row in history)
    assert result
