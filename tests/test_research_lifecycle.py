"""Offline epochs distinguish identical delete/recreate without requiring sync."""

import sqlite3
from contextlib import closing

import pytest
from test_research_review import candidate, query
from test_research_review import workspace as workspace  # noqa: F401

from paper_daily import store, sync_capture
from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle
from paper_daily.research_review import ResearchReview


def legacy(path):
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(store.SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('paper','Paper','paper','Fixture',2026,'fixture')"
        )
        conn.execute("INSERT INTO lists(id,name,note,created_at) VALUES('list','List','','now')")
        conn.commit()


@pytest.mark.parametrize(
    "kind,table,identity", [("paper", "papers", "paper"), ("list", "lists", "list")]
)
def test_lifecycle_metadata_replace_delete_recreate_and_rename(tmp_path, kind, table, identity):
    path = tmp_path / "local.db"
    legacy(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        first = parent_lifecycle(conn, kind, identity)
        ensure_lifecycle(conn)
        assert parent_lifecycle(conn, kind, identity) == first
        row = dict(conn.execute(f"SELECT * FROM {table} WHERE id=?", (identity,)).fetchone())
        column = "title" if kind == "paper" else "name"
        conn.execute(f"UPDATE {table} SET {column}='metadata' WHERE id=?", (identity,))
        assert parent_lifecycle(conn, kind, identity) == first
        columns = ",".join(row)
        marks = ",".join("?" for _ in row)
        conn.execute(
            f"INSERT OR REPLACE INTO {table}({columns}) VALUES({marks})", tuple(row.values())
        )
        replaced = parent_lifecycle(conn, kind, identity)
        assert replaced != first
        conn.execute(f"DELETE FROM {table} WHERE id=?", (identity,))
        assert parent_lifecycle(conn, kind, identity) is None
        conn.execute(f"INSERT INTO {table}({columns}) VALUES({marks})", tuple(row.values()))
        restored = parent_lifecycle(conn, kind, identity)
        assert restored not in {first, replaced}
        conn.execute(f"UPDATE {table} SET id='renamed' WHERE id=?", (identity,))
        assert parent_lifecycle(conn, kind, identity) is None
        assert parent_lifecycle(conn, kind, "renamed") not in {first, replaced, restored}
        conn.rollback()
        assert parent_lifecycle(conn, kind, identity) is None  # installation also rolled back


def test_epochs_persist_and_rollback_restores_original_token(tmp_path):
    path = tmp_path / "local.db"
    legacy(path)
    with closing(sqlite3.connect(path)) as conn:
        with pytest.raises(ValueError, match="transaction"):
            ensure_lifecycle(conn)
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        token = parent_lifecycle(conn, "paper", "paper")
        conn.commit()
    with closing(sqlite3.connect(path)) as conn:
        assert parent_lifecycle(conn, "paper", "paper") == token
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        conn.execute("DELETE FROM papers WHERE id='paper'")
        assert parent_lifecycle(conn, "paper", "paper") is None
        conn.rollback()
        assert parent_lifecycle(conn, "paper", "paper") == token
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('paper','Changed','paper','Fixture',2026,'fixture') "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title"
        )
        assert parent_lifecycle(conn, "paper", "paper") == token


def test_capture_allows_only_lifecycle_trigger_writes(workspace):
    path, _ = workspace
    with closing(sync_capture.CaptureConnection(path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.DatabaseError, match="authorized"):
            conn.execute("UPDATE research_parent_lifecycle SET token='forged'")
        conn.execute(
            "INSERT INTO lists(id,name,note,created_at) VALUES('second','Second','','now')"
        )
        assert parent_lifecycle(conn, "list", "second")
        conn.commit()
        assert conn.execute("SELECT count(*) FROM paperfact_sync_operations").fetchone()[0] >= 2


def test_offline_explicit_target_confirmation_applies_and_preserves_provenance(tmp_path):
    path = tmp_path / "local.db"
    legacy(path)
    identity = candidate(path, source_hash="b" * 64)
    review = ResearchReview(path)
    preview = review.preview("generation", identity)
    assert not preview.data["apply"]
    assert review.targets(preview)["items"] == [{"id": "paper", "title": "Paper"}]
    selected = review.target_preview(preview, "paper")
    assert selected.data["requires_confirmation"]
    assert selected.data["source_hash"] == "b" * 64
    with pytest.raises(ValueError, match="Confirm"):
        review.decide(selected, request_id="unconfirmed")
    result = review.decide(
        selected, body="Offline reviewed text", confirm_target=True, request_id="confirmed"
    )
    assert result["decision"] == "applied"
    assert query(path, "SELECT body FROM close_readings") == [("Offline reviewed text",)]
    assert (
        review.decide(
            selected, body="Offline reviewed text", confirm_target=True, request_id="confirmed"
        )
        == result
    )
    assert not query(path, "SELECT name FROM sqlite_master WHERE name='paperfact_sync_operations'")


def test_offline_delete_recreate_identical_target_blocks_shown_review(tmp_path):
    path = tmp_path / "local.db"
    legacy(path)
    review = ResearchReview(path)
    selected = review.target_preview(review.preview("generation", candidate(path)), "paper")
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone())
        conn.execute("DELETE FROM papers WHERE id='paper'")
        conn.execute(
            "INSERT INTO papers(" + ",".join(row) + ") VALUES(" + ",".join("?" for _ in row) + ")",
            tuple(row.values()),
        )
        conn.commit()
    with pytest.raises(ValueError, match="lifecycle changed"):
        review.decide(selected, body="Do not lose", confirm_target=True)
    assert query(path, "SELECT body FROM close_readings") == [("Current saved analysis",)]


def test_explicit_different_target_does_not_modify_original(tmp_path):
    path = tmp_path / "local.db"
    legacy(path)
    identity = candidate(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('chosen','Selected paper','chosen','Fixture',2026,'fixture')"
        )
        conn.commit()
    review = ResearchReview(path)
    selected = review.target_preview(review.preview("generation", identity), "chosen")
    assert selected.data["current"] is None
    review.decide(selected, confirm_target=True)
    assert query(path, "SELECT paper_id,body FROM close_readings ORDER BY paper_id") == [
        ("chosen", "Retained generated analysis"),
        ("paper", "Current saved analysis"),
    ]


def test_concurrent_installers_observe_one_epoch_and_deleted_parent_is_absent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "concurrent.db"
    legacy(path)

    def install_once():
        with closing(sqlite3.connect(path, timeout=10)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            ensure_lifecycle(conn)
            token = parent_lifecycle(conn, "paper", "paper")
            conn.commit()
            return token

    with ThreadPoolExecutor(max_workers=4) as pool:
        tokens = list(pool.map(lambda _: install_once(), range(8)))
    assert len(set(tokens)) == 1
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("DELETE FROM papers WHERE id='paper'")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        assert parent_lifecycle(conn, "paper", "paper") is None


def test_incomplete_lifecycle_schema_is_not_silently_reseeded(tmp_path):
    path = tmp_path / "damaged.db"
    legacy(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        token = parent_lifecycle(conn, "paper", "paper")
        conn.execute("DROP TRIGGER paperfact_parent_papers_insert")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="incomplete"):
            ensure_lifecycle(conn)
        assert parent_lifecycle(conn, "paper", "paper") == token
