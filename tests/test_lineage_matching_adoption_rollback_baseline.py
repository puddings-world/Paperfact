"""Rollback preserves the actual initialized baseline; never delete older metadata."""

import sqlite3
from contextlib import closing

import pytest
from test_lineage_observation import work
from test_lineage_projection import frame_for
from test_lineage_projection_writer import codec as codec
from test_lineage_projection_writer import pair as pair
from test_lineage_projection_writer import protected
from test_lineage_projection_writer import selected as selected

from paper_daily import lineage_projection as projection
from paper_daily import lineage_sets


def snapshot(client):
    with closing(client.journal._connect()) as conn:
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        return names, tuple(conn.iterdump())


def test_actual_late_failure_retains_preexisting_metadata_and_rolls_back_every_new_write(selected):
    client = selected[0][1]
    frame, _originals = frame_for(selected)
    before = snapshot(client)
    # selected's fixture explicitly creates lineage_sets.SCHEMA before observation.
    # Pin that actual empty baseline, rather than inventing schema absence.
    assert {projection.TABLE, projection.HISTORY, lineage_sets.TABLE} <= before[0]
    with closing(client.journal._connect()) as conn:
        for table in (projection.TABLE, projection.HISTORY, lineage_sets.TABLE):
            assert conn.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0

    def run():
        with client.journal.transaction() as conn:
            projection.initialize_in(conn)
            conn.execute("INSERT INTO kv VALUES('baseline-rollback-fixture','must not survive')")
            conn.execute(
                "CREATE TRIGGER fail_baseline_write BEFORE INSERT ON "
                + projection.TABLE
                + " BEGIN SELECT RAISE(ABORT,'late baseline rollback'); END"
            )
            protected(conn, client, frame)

    with pytest.raises(sqlite3.IntegrityError, match="late baseline rollback"):
        work(run)
    assert snapshot(client) == before
