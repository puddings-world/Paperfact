"""Valid queue pins are supported; invalid list scopes remain visible blockers."""

import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_workspace_enrollment import source as source_fixture

from paper_daily import sync_recovery
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.workspace_enrollment import EnrollmentBlocked

source = source_fixture


def test_unknown_pin_scope_is_preserved_and_reported_unsupported_before_prepare(source, tmp_path):
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute(
            "INSERT INTO pins VALUES('unknown-scope','paper',?)", ("2026-10-30T00:00:00+00:00",)
        )
    package = tmp_path / "backup.zip"
    sync_recovery.create(source, package)
    detached = tmp_path / "detached"
    sync_recovery.restore_detached(package, detached)
    database = detached / "papers.db"
    before = database.read_bytes()
    service = RecoveryAdoptionService(database)
    inspection = service.inspect()
    assert inspection.report["supported"] is False
    assert "list pin requires an existing list membership" in inspection.report["blockers"]
    assert inspection.report["research_counts"]["pins"] == 1
    with pytest.raises(EnrollmentBlocked):
        service.prepare(
            inspection,
            tmp_path / "editable",
            backup_output=tmp_path / "editable.zip",
            request_id=str(uuid4()),
        )
    assert database.read_bytes() == before
    assert not (tmp_path / "editable").exists() and not (tmp_path / "editable.zip").exists()
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT scope,paper_id FROM pins").fetchall() == [
            ("unknown-scope", "paper")
        ]
