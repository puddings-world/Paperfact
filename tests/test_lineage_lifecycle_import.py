"""Imported report lifecycle retains the receiver's exact source and import identity."""

import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from lineage_package_fixture import lineage_archive as lineage_archive
from test_lineage_import_originals import loaded as loaded
from test_lineage_jobs import work
from test_lineage_package_publish import incoming as incoming

from paper_daily import lineage_lifecycle as lifecycle
from paper_daily import lineage_sets


def change(owner, row, action, origin=None):
    return work(lifecycle.change, owner, row, request_id=str(uuid4()), action=action, origin=origin)


def test_imported_report_removes_and_restores_exact_receipt_without_new_grants(loaded):
    _incoming, owner, row = loaded
    with closing(sqlite3.connect(owner.database)) as conn:
        sources = conn.execute(
            "SELECT * FROM research_local_source_owners ORDER BY request_id"
        ).fetchall()
    assert change(owner, row, "retire")["applied"]
    item = work(lifecycle.history, owner)["items"][0]
    assert item["origin"]["kind"] == "import" and item["row"] == row
    assert change(owner, row, "restore", item["origin"])["applied"]
    assert lineage_sets.saved(owner.database, owner.paper_id) == [row]
    with closing(sqlite3.connect(owner.database)) as conn:
        assert (
            conn.execute(
                "SELECT * FROM research_local_source_owners ORDER BY request_id"
            ).fetchall()
            == sources
        )


@pytest.mark.parametrize("broken", ["association", "parent"])
def test_imported_restore_refuses_lost_source_or_recreated_parent(loaded, broken):
    _incoming, owner, row = loaded
    change(owner, row, "retire")
    item = work(lifecycle.history, owner)["items"][0]
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        if broken == "association":
            conn.execute("DELETE FROM research_local_source_owners")
        else:
            old = conn.execute("SELECT * FROM papers WHERE id='receiver-prior'").fetchone()
            assert old is not None
            conn.execute("DELETE FROM papers WHERE id='receiver-prior'")
            conn.execute("INSERT INTO papers VALUES(" + ",".join("?" for _ in old) + ")", old)
    with pytest.raises(ValueError, match="association|lifetime"):
        change(owner, row, "restore", item["origin"])
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
    assert len(work(lifecycle.history, owner)["items"]) == 1
