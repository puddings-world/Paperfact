"""Capacity reads preserve optional storage and fail closed on wrong schema kind."""

import sqlite3

import pytest

from paper_daily import lineage_capacity, lineage_sets


def test_absent_optional_report_store_has_room_without_creating_schema():
    with sqlite3.connect(":memory:") as conn:
        before = tuple(conn.iterdump())
        assert lineage_capacity.local_room_in(conn, "paper", "corpus")
        assert tuple(conn.iterdump()) == before
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (lineage_sets.TABLE,)
        ).fetchone()


def test_existing_wrong_schema_kind_is_not_silently_treated_as_empty():
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE VIEW paper_lineage_sets AS SELECT 'paper' AS paper_id")
        before = tuple(conn.iterdump())
        with pytest.raises(ValueError, match="actual report table"):
            lineage_capacity.local_room_in(conn, "paper", "corpus")
        assert tuple(conn.iterdump()) == before
