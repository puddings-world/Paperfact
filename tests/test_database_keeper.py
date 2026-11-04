"""The desktop's idle connection keeps the WAL alive without blocking anyone."""

import sqlite3
from contextlib import closing

from paper_daily import store


def write(database, value):
    with store.connect(path=database) as conn:
        conn.execute("INSERT INTO kv(key, value) VALUES(?, ?)", (value, value))


def wal(database):
    return database.with_name(database.name + "-wal")


def fresh(tmp_path):
    database = tmp_path / "papers.db"
    with store.connect(path=database) as conn:
        conn.execute("CREATE TABLE kv(key TEXT PRIMARY KEY, value TEXT)")
    return database


def test_short_connections_keep_the_wal_while_the_keeper_is_open(tmp_path):
    database = fresh(tmp_path)
    write(database, "before")
    # Without the keeper, the last close checkpoints and deletes the WAL every time.
    assert not wal(database).exists()

    keeper = store.keep_open(database)
    try:
        write(database, "during")
        assert wal(database).exists()
    finally:
        keeper.close()
    with closing(sqlite3.connect(database)) as conn:
        assert {row[0] for row in conn.execute("SELECT key FROM kv")} == {"before", "during"}
    assert not wal(database).exists()


def test_the_keeper_blocks_no_writer_and_no_checkpoint(tmp_path):
    database = fresh(tmp_path)
    keeper = store.keep_open(database)
    try:
        assert not keeper.in_transaction
        with closing(sqlite3.connect(database, timeout=0)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO kv VALUES('x', 'x')")
            conn.commit()
            busy, _log, _done = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        assert busy == 0
        assert keeper.execute("SELECT value FROM kv WHERE key='x'").fetchone() == ("x",)
    finally:
        keeper.close()
