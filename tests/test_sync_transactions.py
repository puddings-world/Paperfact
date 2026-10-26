"""Compound actions commit research and all journal receipts on one connection."""

import sqlite3

import pytest

from paper_daily.sync_journal import Journal


def operation(identity="one"):
    return {
        "version": 1,
        "operation_id": identity,
        "workspace_id": "workspace",
        "device_id": "device",
        "entity_type": "list",
        "entity_id": "list-" + identity,
        "action": "put",
        "base_revision": 0,
        "depends_on": None,
        "payload": {"name": identity, "note": ""},
    }


def write(conn, value):
    conn.execute("INSERT INTO research VALUES(?,?)", (value["entity_id"], value["payload"]["name"]))


@pytest.fixture
def journal(tmp_path):
    path = tmp_path / "research.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE research(id TEXT PRIMARY KEY,body TEXT)")
        conn.execute("CREATE TABLE local_receipts(id TEXT PRIMARY KEY)")
    return Journal(path, workspace_id="workspace", device_id="device")


def rows(journal, table="research"):
    with sqlite3.connect(journal.path) as conn:
        return conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()


def test_compound_research_and_local_integration_receipt_commit_together(journal):
    with journal.transaction() as conn:
        journal.apply_in(conn, operation("one"), write)
        journal.apply_in(conn, operation("two"), write)
        conn.execute("INSERT INTO local_receipts VALUES('compound-action')")
        assert rows(journal) == []
        assert journal.pending() == []
    assert rows(journal) == [("list-one", "one"), ("list-two", "two")]
    assert rows(journal, "local_receipts") == [("compound-action",)]
    assert journal.pending() == [operation("one"), operation("two")]


@pytest.mark.parametrize("exception", [RuntimeError, KeyboardInterrupt])
def test_compound_failure_leaves_no_partial_research_or_receipts(journal, exception):
    def fail(conn, value):
        write(conn, value)
        raise exception("interrupted")

    with pytest.raises(exception), journal.transaction() as conn:
        journal.apply_in(conn, operation("one"), write)
        conn.execute("INSERT INTO local_receipts VALUES('compound-action')")
        journal.apply_in(conn, operation("two"), fail)
    assert rows(journal) == rows(journal, "local_receipts") == journal.pending() == []


def test_external_tuple_connection_keeps_transaction_ownership(journal):
    conn = sqlite3.connect(journal.path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        journal.apply_in(conn, operation(), write)
        assert conn.in_transaction
        assert conn.row_factory is None
        assert rows(journal) == []
        conn.rollback()
    finally:
        conn.close()
    assert rows(journal) == journal.pending() == []


def test_savepoint_failure_can_preserve_deliberately_retained_outer_work(journal):
    def fail(conn, value):
        write(conn, value)
        raise ValueError("bad second item")

    with journal.transaction() as conn:
        journal.apply_in(conn, operation("one"), write)
        with pytest.raises(ValueError, match="second item"):
            journal.apply_in(conn, operation("two"), fail)
        assert conn.in_transaction
        journal.apply_in(conn, operation("three"), write)
    assert rows(journal) == [("list-one", "one"), ("list-three", "three")]
    assert journal.pending() == [operation("one"), operation("three")]


def test_retry_in_same_outer_transaction_is_once_and_changed_retry_is_rejected(journal):
    with journal.transaction() as conn:
        first = journal.apply_in(conn, operation(), write)
        again = journal.apply_in(conn, operation(), lambda *_: pytest.fail("duplicate writer"))
        assert again == {"applied": False, "sequence": first["sequence"]}
        bad = operation()
        bad["payload"]["name"] = "changed"
        with pytest.raises(ValueError, match="reused"):
            journal.apply_in(conn, bad, write)
        assert conn.in_transaction
    assert rows(journal) == [("list-one", "one")]
    assert journal.pending() == [operation()]


def test_inactive_connection_is_rejected_without_implicit_begin(journal):
    with sqlite3.connect(journal.path) as conn:
        with pytest.raises(ValueError, match="transaction"):
            journal.apply_in(conn, operation(), write)
        assert not conn.in_transaction
    assert rows(journal) == journal.pending() == []


def test_connection_to_other_database_cannot_use_this_journal(journal, tmp_path):
    other = Journal(tmp_path / "other.sqlite", workspace_id="workspace", device_id="device")
    with (
        other.transaction() as conn,
        pytest.raises(ValueError, match="another research database"),
    ):
        journal.apply_in(conn, operation(), write)
    assert rows(journal) == journal.pending() == other.pending() == []


@pytest.mark.parametrize(
    "statement",
    [
        "COMMIT",
        "ROLLBACK",
        "CREATE TABLE surprise(id TEXT)",
        "DELETE FROM paperfact_sync_operations",
    ],
)
def test_writer_transaction_escape_keeps_entire_compound_action_atomic(journal, statement):
    def fail(conn, value):
        write(conn, value)
        conn.execute(statement)

    with pytest.raises(sqlite3.DatabaseError), journal.transaction() as conn:
        journal.apply_in(conn, operation("one"), write)
        journal.apply_in(conn, operation("two"), fail)
    assert rows(journal) == journal.pending() == []


def test_writer_cannot_write_to_previously_attached_database(journal, tmp_path):
    other = tmp_path / "unrelated.sqlite"
    with sqlite3.connect(other) as conn:
        conn.execute("CREATE TABLE research(id TEXT PRIMARY KEY,body TEXT)")
    conn = sqlite3.connect(journal.path)
    try:
        conn.execute("ATTACH DATABASE ? AS other", (str(other),))
        conn.execute("BEGIN IMMEDIATE")

        def cross_workspace(conn, value):
            write(conn, value)
            conn.execute("INSERT INTO other.research VALUES('bad','cross-workspace')")

        with pytest.raises(sqlite3.DatabaseError):
            journal.apply_in(conn, operation(), cross_workspace)
        conn.commit()
    finally:
        conn.close()
    with sqlite3.connect(other) as conn:
        assert conn.execute("SELECT * FROM research").fetchall() == []
    assert rows(journal) == journal.pending() == []


def test_outer_commit_constraint_failure_rolls_back_research_and_journal(journal):
    with sqlite3.connect(journal.path) as conn:
        conn.execute("CREATE TABLE parents(id INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE children(parent INTEGER REFERENCES parents(id) "
            "DEFERRABLE INITIALLY DEFERRED)"
        )
    conn = sqlite3.connect(journal.path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        journal.apply_in(conn, operation(), write)
        conn.execute("INSERT INTO children VALUES(99)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.commit()
        conn.rollback()
    finally:
        conn.close()
    assert rows(journal) == journal.pending() == []


def abort_writer(conn, value):
    conn.execute("INSERT OR ROLLBACK INTO research VALUES('list-one','duplicate')")


def test_database_abort_preserves_original_failure_and_rolls_back_entire_action(journal):
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"), journal.transaction() as conn:
        journal.apply_in(conn, operation("one"), write)
        journal.apply_in(conn, operation("two"), abort_writer)
    assert rows(journal) == journal.pending() == []


@pytest.mark.parametrize("write_after_abort", [False, True])
def test_caught_database_abort_cannot_report_compound_transaction_success(
    journal, write_after_abort
):
    with (
        pytest.raises(RuntimeError, match="transaction.*ended|transaction.*interrupted"),
        journal.transaction() as conn,
    ):
        journal.apply_in(conn, operation("one"), write)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            journal.apply_in(conn, operation("two"), abort_writer)
        if write_after_abort:
            conn.execute("INSERT INTO local_receipts VALUES('must-not-commit')")
    assert rows(journal) == rows(journal, "local_receipts") == journal.pending() == []
