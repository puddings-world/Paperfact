"""Enrollment archives retain linked scientific evidence rather than loose rows."""

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_lineage_enrollment import corpus as corpus
from test_lineage_enrollment import selection
from test_lineage_lifecycle import active as active

from paper_daily import lineage_sets, sync_recovery
from paper_daily.workspace_enrollment import EnrollmentService


@pytest.mark.parametrize(
    "missing", ["research_lineage_publications", "research_generation_requests"]
)
def test_enrolled_archive_missing_linked_evidence_refuses_new_backup(
    active, corpus, tmp_path, missing
):
    owner, row = active
    result = EnrollmentService(owner.database).prepare(
        tmp_path / "enrolled",
        backup_output=tmp_path / "initial.zip",
        request_id=str(uuid4()),
        pdfs=selection(corpus),
    )
    database = Path(result["database"])
    sync_recovery.inspect(tmp_path / "initial.zip")
    with closing(sqlite3.connect(database)) as conn, conn:
        removed = conn.execute("DELETE FROM research_history_archive WHERE protocol=?", (missing,))
        assert removed.rowcount > 0
    before = database.read_bytes()
    output = tmp_path / "incomplete.zip"
    with pytest.raises(ValueError):
        sync_recovery.create(database, output)
    assert not output.exists()
    assert database.read_bytes() == before
    assert lineage_sets.saved(database, row["paper_id"]) == [row]
