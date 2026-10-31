"""Optional page records must not break the existing partial note migration."""

from contextlib import closing

import pytest
from test_notes_anchor import old_db as original_old_db

from paper_daily import reading_positions, store


@pytest.fixture
def legacy(tmp_path):
    with closing(original_old_db.__wrapped__(tmp_path)) as conn:
        yield conn


def names(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def bodies(conn):
    return [tuple(row) for row in conn.execute(
        "SELECT paper_id,body,created_at FROM notes ORDER BY id"
    )]


@pytest.mark.parametrize("parent_first", [False, True])
def test_optional_position_install_preserves_legacy_rows_and_caller_rollback(legacy, parent_first):
    original = bodies(legacy)
    legacy.execute("BEGIN")
    if parent_first:
        legacy.execute("CREATE TABLE papers(id TEXT PRIMARY KEY)")
    legacy.execute(
        "INSERT INTO notes(paper_id,body,created_at) VALUES('pending','unsaved','2026-01-02')"
    )
    store._migrate(legacy)
    assert legacy.in_transaction
    assert bodies(legacy)[:-1] == original
    if parent_first:
        assert reading_positions.ready(legacy)
    else:
        assert "papers" not in names(legacy)
        assert reading_positions.TABLE not in names(legacy)
        assert reading_positions.RECEIPTS not in names(legacy)
        legacy.execute("CREATE TABLE papers(id TEXT PRIMARY KEY)")
        store._migrate(legacy)
        assert reading_positions.ready(legacy)
    legacy.rollback()
    assert bodies(legacy) == original
    assert "papers" not in names(legacy)
    assert reading_positions.TABLE not in names(legacy)
    assert "anchor" not in {row[1] for row in legacy.execute("PRAGMA table_info(notes)")}

    legacy.execute("BEGIN")
    legacy.execute("CREATE TABLE papers(id TEXT PRIMARY KEY)")
    store._migrate(legacy)
    assert legacy.in_transaction and reading_positions.ready(legacy)
    legacy.commit()
    store._migrate(legacy)
    assert bodies(legacy) == original
    assert reading_positions.ready(legacy)
    assert legacy.execute("SELECT anchor,kind FROM notes").fetchone()[:] == (None, "note")
    legacy.rollback()


def test_parent_presence_does_not_hide_malformed_optional_position_schema(legacy):
    original = bodies(legacy)
    legacy.execute("CREATE TABLE papers(id TEXT PRIMARY KEY)")
    legacy.execute("CREATE TABLE reading_positions(bogus TEXT)")
    legacy.commit()
    legacy.execute("BEGIN")
    legacy.execute(
        "INSERT INTO notes(paper_id,body,created_at) VALUES('pending','unsaved','2026-01-02')"
    )
    with pytest.raises(ValueError, match="explicit migration"):
        store._migrate(legacy)
    assert legacy.in_transaction
    legacy.rollback()
    assert bodies(legacy) == original
    assert [row[1] for row in legacy.execute("PRAGMA table_info(reading_positions)")] == ["bogus"]
    assert "anchor" not in {row[1] for row in legacy.execute("PRAGMA table_info(notes)")}
