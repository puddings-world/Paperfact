"""Completed multi-row work must survive detached backup without replaying jobs."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_research_generation import workspace as _workspace

from paper_daily import research_compound as compound
from paper_daily import research_generation as generation
from paper_daily import sync_recovery

workspace = _workspace


def begin(path):
    with closing(generation._connect(path)) as conn:
        return compound.begin(conn, phase="fetch", owner_id="paper")


def test_compound_rows_candidates_and_sidecars_survive_detached_backup(
    workspace, tmp_path, monkeypatch
):
    path, _, document = workspace
    document.path.unlink()  # This metadata-only fixture has no retained PDF operations.
    stale = begin(path)
    current = begin(path)
    live = compound.row(current, "one", title="Accepted research")
    assert compound.publish(current, puts=[live]).status == "accepted"
    late = compound.row(stale, "two", title="Retained group")
    assert compound.publish(stale, puts=[late]).status == "candidate"
    failed = begin(path)
    missing = compound.row(failed, "three", title="Storage failure output")
    with monkeypatch.context() as patch:

        def fail(*args, **kwargs):
            raise sqlite3.OperationalError("fixture storage failure")

        patch.setattr(compound, "_publish", fail)
        assert compound.publish(failed, puts=[missing]).status == "candidate"
    package = tmp_path / "backup.zip"
    sync_recovery.create(path, package)
    checked = sync_recovery.inspect(package)
    counts = {table["name"]: table["count"] for table in checked["tables"]}
    assert counts["research_compound_requests"] == 2
    assert counts["research_compound_recovery"] == 1
    destination = tmp_path / "detached"
    sync_recovery.restore_detached(package, destination)
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        assert conn.execute("SELECT work_id,title FROM followups").fetchall() == [
            ("one", "Accepted research")
        ]
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name IN "
                "('research_compound_requests','research_capture_binding')"
            ).fetchall()
            == []
        )
        records = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name IN "
                "('research_compound_requests','research_compound_recovery')"
            )
        ]
    assert len(records) == 3
    assert sorted(compound.validate_request_record(row)["status"] for row in records) == [
        "accepted",
        "candidate",
        "candidate",
    ]
    retained = {json.loads(row["mutations_json"])["puts"][0]["title"] for row in records}
    assert retained == {"Accepted research", "Retained group", "Storage failure output"}


def test_compound_source_hash_without_retained_pdf_cannot_claim_complete_backup(
    workspace, tmp_path
):
    path, _, document = workspace
    original, _text, _first = compound.read_text(
        begin(path), pdf_root=document.path.parent, text_root=tmp_path / "text"
    )
    value = compound.row(original, "one", title="Output using original source")
    document.path.unlink()
    assert compound.publish(original, puts=[value]).status == "candidate"
    package = tmp_path / "incomplete.zip"
    with pytest.raises(sync_recovery.RecoveryError, match="source PDF"):
        sync_recovery.create(path, package)
    assert not package.exists()
