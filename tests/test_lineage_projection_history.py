"""Immutable staged projection history survives retirement and rolls back with content."""

import copy
import sqlite3
from uuid import uuid4

import pytest
from test_lineage_observation import work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import CallerRollback, frame_for, project, rows

from paper_daily import lineage_projection as projection
from paper_daily import lineage_sets


def test_history_preserves_put_revisions_and_retirement_without_duplicate_retry(selected):
    client = selected[0][1]
    first, _operations = frame_for(selected)
    work(project, client, first)
    second = copy.deepcopy(first)
    second["operation_id"] = str(uuid4())
    second["payload"]["data"]["written_at"] = "2026-11-13T01:00:00+00:00"
    work(project, client, second)
    retired = dict(
        second, operation_id=str(uuid4()), action="delete", payload={}, source_dependencies=[]
    )
    work(project, client, retired)
    work(project, client, retired)
    history = rows(client, projection.HISTORY)
    assert {r["operation_id"] for r in history} == {
        first["operation_id"],
        second["operation_id"],
        retired["operation_id"],
    }
    assert [projection.validate_history(r) for r in history] == [first, second, retired]
    assert rows(client, lineage_sets.TABLE) == []


def test_changed_operation_identity_never_overwrites_saved_content_or_history(selected):
    client = selected[0][1]
    frame, _operations = frame_for(selected)
    work(project, client, frame)
    before = (
        rows(client, lineage_sets.TABLE),
        rows(client, projection.TABLE),
        rows(client, projection.HISTORY),
    )
    changed = copy.deepcopy(frame)
    changed["payload"]["data"]["written_at"] = "2026-11-13T01:00:00+00:00"
    with pytest.raises(ValueError, match="identity cannot be reused"):
        work(project, client, changed)
    assert (
        rows(client, lineage_sets.TABLE),
        rows(client, projection.TABLE),
        rows(client, projection.HISTORY),
    ) == before


def test_history_and_scientific_projection_share_caller_rollback(selected):
    client = selected[0][1]
    frame, _operations = frame_for(selected)
    with pytest.raises(CallerRollback):
        work(project, client, frame, rollback=True)
    assert rows(client, projection.HISTORY) == []
    work(project, client, frame)
    assert len(rows(client, projection.HISTORY)) == 1


def test_late_projection_failure_rolls_back_earlier_history_but_not_caller_work(selected):
    client = selected[0][1]
    frame, _operations = frame_for(selected)
    with client.journal.transaction() as conn:
        projection.initialize_in(conn)
        conn.execute("CREATE TABLE caller_work(value TEXT)")
        conn.execute("INSERT INTO caller_work VALUES('keep')")
        conn.execute(
            "CREATE TRIGGER fixture_history_failure BEFORE INSERT ON "
            + projection.TABLE
            + " BEGIN SELECT RAISE(ABORT, 'fixture late failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="late failure"):
            projection.write_in(conn, frame)
        assert conn.execute("SELECT value FROM caller_work").fetchone()[0] == "keep"
        assert not conn.execute("SELECT 1 FROM " + projection.HISTORY).fetchone()
        assert not conn.execute("SELECT 1 FROM " + lineage_sets.TABLE).fetchone()
