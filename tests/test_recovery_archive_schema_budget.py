"""Archive entry points reuse metadata per operation, without skipping row checks."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_recovery_provenance_schema_budget import archive as _archive
from test_recovery_provenance_schema_budget import count_real_schema

from paper_daily import recovery_provenance as provenance
from paper_daily import sync_recovery as recovery

archive = _archive


@pytest.fixture
def retained(archive):
    with closing(sqlite3.connect(archive.database)) as conn, conn:
        conn.execute("BEGIN")
        provenance.retain_in(conn, archive.rows)
    return archive


def test_creating_archive_with_retained_history_has_bounded_schema_work(
    retained, monkeypatch, tmp_path
):
    before = retained.database.read_bytes()
    calls = count_real_schema(monkeypatch)
    package = tmp_path / "retained.zip"
    manifest = recovery.create(retained.database, package)
    assert retained.database.read_bytes() == before
    item = next(t for t in manifest["tables"] if t["name"] == provenance.TABLE)
    assert item["count"] == len(retained.rows)
    assert len(calls) <= 10, f"Schema rebuilt {len(calls)} times for one archive creation"
    assert provenance._SCHEMA_SCOPE.get() is None


@pytest.mark.parametrize("action", ["inspect", "restore"])
def test_archive_reads_retain_every_row_and_do_not_rebuild_schema_per_row(
    retained, monkeypatch, tmp_path, action
):
    package = tmp_path / "retained.zip"
    expected = recovery.create(retained.database, package)
    before = package.read_bytes()
    calls = count_real_schema(monkeypatch)
    for index in range(2):
        start = len(calls)
        if action == "inspect":
            assert recovery.inspect(package) == expected
        else:
            destination = tmp_path / ("restored-" + str(index))
            recovery.restore_detached(package, destination)
            with closing(sqlite3.connect(destination / "papers.db")) as conn:
                assert {r[0] for r in conn.execute("SELECT id FROM papers")} == {"0", "1", "2"}
                restored = [json.loads(r[0]) for r in conn.execute(
                    "SELECT data FROM recovery_records WHERE table_name=? ORDER BY row_number",
                    (provenance.TABLE,),
                )]
                assert restored == sorted(retained.rows, key=lambda r: r["record_id"])
                assert not conn.execute(
                    "SELECT name FROM sqlite_master WHERE name='paperfact_sync_identity'"
                ).fetchone()
        assert 0 < len(calls) - start <= 10
        assert provenance._SCHEMA_SCOPE.get() is None
    assert package.read_bytes() == before


def test_failed_inspect_releases_metadata_before_retry(retained, monkeypatch, tmp_path):
    package = tmp_path / "retained.zip"
    expected = recovery.create(retained.database, package)
    actual = recovery._research_schema
    calls = []

    def once():
        calls.append(True)
        if len(calls) == 2:
            raise RuntimeError("synthetic schema failure during retained-row validation")
        return actual()

    monkeypatch.setattr(recovery, "_research_schema", once)
    with pytest.raises(RuntimeError, match="synthetic schema failure"):
        recovery.inspect(package)
    assert provenance._SCHEMA_SCOPE.get() is None
    assert recovery.inspect(package) == expected
    assert len(calls) <= 12
    assert provenance._SCHEMA_SCOPE.get() is None
