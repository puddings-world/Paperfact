"""Lossless queue-pin copies retain orphan ownership and replace old authority."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_workspace_enrollment import source as source_fixture

from paper_daily import sync_recovery
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.workspace_enrollment import EnrollmentService

source = source_fixture
STAMP = "2026-10-30T09:12:34.123456+08:00"


def assert_pin(database):
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT * FROM pins").fetchall() == [("queue", "paper", STAMP)]
        assert conn.execute("SELECT * FROM queue").fetchall() == []
        assert conn.execute("SELECT * FROM list_papers").fetchall() == []
        assert conn.execute("SELECT id FROM lists").fetchall() == [("list",)]
        rows = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT envelope FROM paperfact_sync_operations "
                "WHERE entity_type='research_content'"
            )
        ]
        pin = next(op for op in rows if op["payload"].get("feature") == "queue_pin")
        assert pin["payload"]["data"] == {"pinned_at": STAMP}
        assert pin["payload"]["scope"]["kind"] == "paper"
        assert pin["payload"]["key"] == "main" and pin["payload"]["source_document_hash"] is None
        assert len(pin["parents"]) == 1 and pin["parents"][0]["kind"] == "paper"
        return pin


def test_orphan_initial_copy_then_repeated_backup_adoption_preserves_exact_pin(source, tmp_path):
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("DELETE FROM list_papers")
        conn.execute("INSERT INTO pins VALUES('queue','paper',?)", (STAMP,))
    before = source.read_bytes()
    service = EnrollmentService(source)
    assert service.plan()["supported"]
    result = service.prepare(
        tmp_path / "first", backup_output=tmp_path / "first.zip", request_id=str(uuid4())
    )
    prior = assert_pin(result["database"])
    assert source.read_bytes() == before
    for index in range(2):
        detached = tmp_path / f"detached-{index}"
        sync_recovery.restore_detached(result["backup"], detached)
        adoption = RecoveryAdoptionService(detached / "papers.db")
        inspection = adoption.inspect()
        assert inspection.report["supported"] and inspection.report["research_counts"]["pins"] == 1
        result = adoption.prepare(
            inspection,
            tmp_path / f"editable-{index}",
            backup_output=tmp_path / f"editable-{index}.zip",
            request_id=str(uuid4()),
        )
        fresh = assert_pin(result["database"])
        assert fresh["workspace_id"] != prior["workspace_id"]
        assert fresh["incarnation"] != prior["incarnation"]
        with closing(sqlite3.connect(result["database"])) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM research_recovery_provenance").fetchone()[0] > 0
            )
        prior = fresh
        assert (
            sync_recovery.inspect(Path(result["backup"]))["workspace_id"] == fresh["workspace_id"]
        )


@pytest.mark.parametrize("change", ["naive", "unknown-scope", "missing-owner"])
def test_invalid_pin_still_blocks_before_any_copy(source, tmp_path, change):
    scope = "future-pin" if change == "unknown-scope" else "queue"
    stamp = "2026-10-30T00:00:00" if change == "naive" else STAMP
    owner = "missing" if change == "missing-owner" else "paper"
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("INSERT INTO pins VALUES(?,?,?)", (scope, owner, stamp))
    before = source.read_bytes()
    assert not EnrollmentService(source).plan()["supported"]
    with pytest.raises(ValueError):
        EnrollmentService(source).prepare(
            tmp_path / "blocked", backup_output=tmp_path / "blocked.zip", request_id=str(uuid4())
        )
    assert source.read_bytes() == before
    assert not (tmp_path / "blocked").exists() and not (tmp_path / "blocked.zip").exists()
