"""Existing store callers capture atomically without opting into a new facade."""

import sqlite3

import pytest

from paper_daily import store
from paper_daily.sync_capture import (
    CaptureError,
    StaleCaptureError,
    capture_existing,
    expecting,
    install,
    observe_content,
    observe_note,
)
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_order_writer, research_writer
from paper_daily.sync_service import ReferenceService

STAMP = "2026-10-26T00:00:00+00:00"


def make(path, device="a"):
    with sqlite3.connect(path) as conn:
        conn.executescript(store.SCHEMA)
    prepare(path, workspace_id="workspace", device_id=device)
    return SyncClient(
        Journal(path, workspace_id="workspace", device_id=device),
        research_writer,
        order_writer=research_order_writer,
    )


@pytest.fixture
def bound(tmp_path, monkeypatch):
    path = tmp_path / "a.sqlite"
    client = make(path)
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="a")
    return client


def seed():
    with store.connect() as conn:
        conn.execute("INSERT INTO lists VALUES('list','Reading','',?)", (STAMP,))
        store.upsert_papers(
            conn,
            [
                {
                    "id": "local-paper",
                    "title": "Paper",
                    "year": 2026,
                    "venue": "Fixture",
                    "source": "fixture",
                }
            ],
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('list','local-paper',0,?)",
            (STAMP,),
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) VALUES('local-paper','first',?)", (STAMP,)
        )


def rows(sql):
    with sqlite3.connect(store.DB_PATH) as conn:
        return conn.execute(sql).fetchall()


def test_existing_store_mutations_and_inner_commit_capture(bound):
    seed()
    ops = bound.journal.pending()
    assert {o["entity_type"] for o in ops} == {
        "list",
        "paper",
        "membership",
        "reading_state",
        "note",
        "list_order",
        "workspace_list_order",
    }
    assert len(ops) == 7
    with store.connect() as conn:
        conn.execute("UPDATE lists SET name='Renamed' WHERE id='list'")
        conn.commit()
        assert len(bound.journal.pending()) == 8
    assert len(bound.journal.pending()) == 8
    assert rows("SELECT name FROM lists") == [("Renamed",)]


def test_round_trip_no_echo_after_remote_projection(bound, tmp_path):
    seed()
    service = ReferenceService(tmp_path / "server.sqlite")
    token = service.enroll("workspace", "a")
    for op in bound.journal.pending():
        event = service.push(token, op)
        bound.journal.acknowledge(op["operation_id"], event["sequence"])
    bound.receive(service.pull(token))
    assert bound.journal.pending() == []
    peer = make(tmp_path / "b.sqlite", "b")
    peer.receive(service.pull(service.enroll("workspace", "b")))
    with peer.journal._connect() as conn:
        assert conn.execute("SELECT body FROM notes").fetchall()[0][0] == "first"
        assert conn.execute("SELECT name FROM lists").fetchone()[0] == "Reading"
    with store.connect() as conn:
        conn.execute("UPDATE lists SET name='Next' WHERE id='list'")
    assert len(bound.journal.pending()) == 1


@pytest.mark.parametrize("sql", ["COMMIT", "END", "DROP TRIGGER capture_lists_insert"])
def test_raw_boundary_bypass_denied(bound, sql):
    with pytest.raises(sqlite3.DatabaseError), store.connect() as conn:
        conn.execute("INSERT INTO lists VALUES('list','Reading','',?)", (STAMP,))
        conn.execute(sql)
    assert rows("SELECT * FROM lists") == []
    assert bound.journal.pending() == []


def test_unmanaged_database_write_fails_closed(bound):
    with (
        sqlite3.connect(store.DB_PATH) as conn,
        pytest.raises(sqlite3.OperationalError, match="paperfact_capture"),
    ):
        conn.execute("INSERT INTO lists VALUES('list','Reading','',?)", (STAMP,))
    assert bound.journal.pending() == []


def test_script_bypass_and_failed_inner_commit_poison(bound):
    with store.connect() as conn, pytest.raises(CaptureError):
        conn.executescript("INSERT INTO lists VALUES('list','bad','','today');")
    with pytest.raises(CaptureError), store.connect() as conn:
        conn.execute("INSERT INTO lists VALUES('list',?,'',?)", ("x" * 201, STAMP))
        with pytest.raises(ValueError):
            conn.commit()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("INSERT INTO lists VALUES('second','Later','',?)", (STAMP,))
    assert rows("SELECT * FROM lists") == []
    assert bound.journal.pending() == []


def test_savepoint_rollback_and_nonresearch_changes(bound):
    seed()
    count = len(bound.journal.pending())
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("SAVEPOINT edit")
        conn.execute("UPDATE lists SET name='Discard'")
        conn.execute("ROLLBACK TO edit")
        conn.execute("RELEASE edit")
        conn.execute("UPDATE papers SET score=3")
        store.set_kv(conn, "ui.layout", "private-local-value")
    assert len(bound.journal.pending()) == count
    assert rows("SELECT name FROM lists") == [("Reading",)]
    assert rows("SELECT * FROM research_capture_dirty") == []


def test_stale_note_keeps_candidate_and_newer_projection(bound):
    seed()
    with store.connect() as conn:
        stale = observe_note(conn, 1)
    with store.connect() as conn, expecting(conn, [stale]):
        conn.execute("UPDATE notes SET body='newer' WHERE id=1")
        conn.commit()
    count = len(bound.journal.pending())
    with (
        pytest.raises(StaleCaptureError) as failure,
        store.connect() as conn,
        expecting(conn, [stale]),
    ):
        conn.execute("UPDATE notes SET body='stale draft' WHERE id=1")
        conn.execute("UPDATE lists SET name='must roll back'")
        conn.commit()
    assert rows("SELECT body FROM notes") == [("newer",)]
    assert rows("SELECT name FROM lists") == [("Reading",)]
    candidate = rows("SELECT id,content FROM research_capture_candidates")
    assert candidate[0][0] == failure.value.candidate_id
    assert "stale draft" in candidate[0][1]
    assert len(bound.journal.pending()) == count


def test_unsupported_research_write_rolls_back(bound):
    seed()
    count = len(bound.journal.pending())
    with pytest.raises(sqlite3.OperationalError), store.connect() as conn:
        conn.execute("UPDATE lists SET name='must roll back'")
        conn.execute("INSERT INTO pins VALUES('queue','local-paper',?)", (STAMP,))
    assert rows("SELECT name FROM lists") == [("Reading",)]
    assert bound.journal.pending() and len(bound.journal.pending()) == count


def test_unbound_legacy_is_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "legacy.sqlite"
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    store.init_db()
    with store.connect() as conn:
        assert observe_note(conn, 1) is None
        with expecting(conn, [None]):
            conn.execute("INSERT INTO lists VALUES('list','Reading','',?)", (STAMP,))
            conn.commit()
    assert rows("SELECT name FROM lists") == [("Reading",)]


def test_bound_init_db_is_read_only(bound):
    seed()
    count = len(bound.journal.pending())
    store.init_db()
    assert len(bound.journal.pending()) == count


def test_deletion_keeps_paper_and_captures_child_lifecycle(bound):
    from paper_daily import lists

    seed()
    lists.delete_list("list")
    pending = bound.journal.pending()
    deleted = {op["entity_type"] for op in pending if op["action"] == "delete"}
    assert {"list", "membership", "reading_state", "list_order"} <= deleted
    assert rows("SELECT title FROM papers") == [("Paper",)]


def test_restart_binding_and_changed_payload_no_partial_capture(bound):
    seed()
    count = len(bound.journal.pending())
    with pytest.raises(ValueError), store.connect() as conn:
        conn.execute("UPDATE lists SET name='temporary'")
        conn.execute("UPDATE list_papers SET added_at='2026-11-01T00:00:00+00:00'")
    assert len(bound.journal.pending()) == count
    assert rows("SELECT name FROM lists") == [("Reading",)]
    assert rows("SELECT added_at FROM list_papers") == [(STAMP,)]


@pytest.mark.parametrize("use_cursor", [False, True])
def test_autocommit_script_cannot_bypass_capture(bound, use_cursor):
    with store.connect() as conn:
        target = conn.cursor() if use_cursor else conn
        with pytest.raises((sqlite3.DatabaseError, CaptureError)):
            target.executescript("INSERT INTO lists VALUES('bad','Bad','','2026-10-26');")
    assert rows("SELECT * FROM lists") == []
    assert bound.journal.pending() == []


def test_primary_identity_cannot_be_silently_rekeyed(bound):
    seed()
    count = len(bound.journal.pending())
    with pytest.raises(sqlite3.DatabaseError), store.connect() as conn:
        conn.execute("UPDATE lists SET id='renamed-id' WHERE id='list'")
    assert rows("SELECT id FROM lists") == [("list",)]
    assert len(bound.journal.pending()) == count


def test_real_integration_receipt_retries_remain_atomic(bound):
    from paper_daily import local_operations

    proposal = local_operations.propose("Intake", [{"title": "Shared paper", "year": 2026}])
    first = local_operations.commit(proposal["preview_id"], "request-1", ["0"])
    count = len(bound.journal.pending())
    second = local_operations.commit(proposal["preview_id"], "request-1", ["0"])
    assert second == first
    assert len(bound.journal.pending()) == count
    assert rows("SELECT COUNT(*) FROM lists") == [(1,)]
    assert rows("SELECT COUNT(*) FROM integration_operations") == [(1,)]
    assert {op["entity_type"] for op in bound.journal.pending()} >= {"list", "paper", "membership"}


def test_existing_research_baseline_uses_same_capture_path(tmp_path, monkeypatch):
    path = tmp_path / "legacy.sqlite"
    client = make(path)
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    seed()
    assert client.journal.pending() == []
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="a")
        capture_existing(conn)
    assert len(client.journal.pending()) == 7
    assert rows("SELECT body FROM notes") == [("first",)]


def test_explicit_journal_on_store_connection_does_not_echo(bound):
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        operation = bound.new_graph_operation_in(
            conn, "list", "list", {"name": "Typed", "note": ""}
        )
        bound.journal.apply_in(conn, operation, bound.writer)
    assert len(bound.journal.pending()) == 1
    assert rows("SELECT name FROM lists") == [("Typed",)]
    assert rows("SELECT * FROM research_capture_dirty") == []


def test_authorizer_trusted_statement_cannot_be_reused_by_caller(bound):
    with store.connect() as conn:
        conn.execute("INSERT INTO lists VALUES('list','Reading','',?)", (STAMP,))
        conn.commit()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM research_capture_dirty")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("PRAGMA writable_schema=ON")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("PRAGMA recursive_triggers=OFF")


def test_rich_dive_store_writer_round_trip(bound, tmp_path):
    seed()
    draft = {
        "paper_id": "local-paper",
        "body": "Detailed explanation",
        "written_at": STAMP,
        "spec": "fixture-spec",
    }
    with store.connect() as conn, expecting(conn, [observe_content(conn, "dives", draft)]):
        conn.execute(
            "INSERT INTO dives(paper_id,body,written_at,spec) VALUES(?,?,?,?)",
            tuple(draft.values()),
        )
        conn.commit()
    service = ReferenceService(tmp_path / "server.sqlite")
    token = service.enroll("workspace", "a")
    for operation in bound.journal.pending():
        service.push(token, operation)
    peer = make(tmp_path / "peer.sqlite", "b")
    peer.receive(service.pull(service.enroll("workspace", "b")))
    with peer.journal._connect() as conn:
        assert conn.execute("SELECT body,spec FROM dives").fetchall()[0][:] == (
            "Detailed explanation",
            "fixture-spec",
        )


def test_unobserved_note_replacement_is_retained_not_applied(bound):
    seed()
    count = len(bound.journal.pending())
    with pytest.raises(StaleCaptureError), store.connect() as conn:
        conn.execute("UPDATE notes SET body='unobserved AI output'")
    assert rows("SELECT body FROM notes") == [("first",)]
    assert len(bound.journal.pending()) == count
    assert "unobserved AI output" in rows("SELECT content FROM research_capture_candidates")[0][0]


def test_new_ai_result_also_requires_start_observation(bound):
    seed()
    with pytest.raises(StaleCaptureError), store.connect() as conn:
        conn.execute(
            "INSERT INTO dives VALUES(?,?,?,?)", ("local-paper", "Generated", STAMP, "fixture")
        )
    assert rows("SELECT * FROM dives") == []
    assert "Generated" in rows("SELECT content FROM research_capture_candidates")[0][0]


def test_top_level_savepoint_cannot_commit_without_capture(bound):
    with store.connect() as conn, pytest.raises(sqlite3.DatabaseError):
        conn.execute("SAVEPOINT root")
    assert bound.journal.pending() == []


def test_bulk_capture_replays_pending_graph_once(bound, monkeypatch):
    from paper_daily import local_operations

    calls = []
    original = SyncClient._pending_graph

    def counted(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SyncClient, "_pending_graph", counted)
    preview = local_operations.propose(
        "Bulk", [{"title": f"Paper {i}", "year": 2026} for i in range(50)]
    )
    local_operations.commit(preview["preview_id"], "bulk-request", [str(i) for i in range(50)])
    assert rows("SELECT COUNT(*) FROM papers") == [(50,)]
    assert rows("SELECT COUNT(*) FROM paperfact_sync_operations") == [(153,)]
    assert len(calls) <= 3


def test_graph_cache_does_not_survive_rollback_or_inner_commit(bound):
    seed()
    with store.connect() as conn:
        conn.execute("UPDATE lists SET name='discarded'")
        conn.rollback()
        conn.execute("UPDATE lists SET name='second'")
        conn.commit()
        conn.execute("UPDATE lists SET name='third'")
        conn.commit()
    operations = [op for op in bound.journal.pending() if op["entity_type"] == "list"]
    assert [op["payload"]["name"] for op in operations] == ["Reading", "second", "third"]
    assert operations[-1]["depends_on"] == operations[-2]["operation_id"]


def test_replace_cannot_silently_rebind_integer_note_identity(bound):
    seed()
    count = len(bound.journal.pending())
    with pytest.raises(sqlite3.DatabaseError), store.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO notes(id,paper_id,body,created_at) VALUES(1,?,?,?)",
            ("local-paper", "different identity", "2026-11-02T00:00:00+00:00"),
        )
    assert rows("SELECT body,created_at FROM notes") == [("first", STAMP)]
    assert len(bound.journal.pending()) == count
