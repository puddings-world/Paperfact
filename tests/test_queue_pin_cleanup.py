"""Queue pins survive the reserved-name list; schema repair is explicit and closed."""

import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_queue_pins import STAMP, toggle
from test_reference_edges import SOURCE, query, write
from test_reference_edges import pair as pair

from paper_daily.sync_capture import CaptureConnection, install
from paper_daily.sync_content import pin_cleanup_ready
from paper_daily.sync_schema_v2 import membership_id

PREVIOUS = (
    "CREATE TRIGGER IF NOT EXISTS paperfact_pin_membership_delete "
    "AFTER DELETE ON list_papers BEGIN DELETE FROM pins "
    "WHERE scope=OLD.list_id AND paper_id=OLD.paper_id; END"
)


def actual_queue_list(a):
    a.save(a.new_graph_operation("list", "queue", {"name": "Actual user list", "note": ""}))
    a.save(
        a.new_graph_operation(
            "membership",
            membership_id("queue", SOURCE),
            {"list_id": "queue", "paper_id": SOURCE, "citation": None, "added_at": STAMP},
        )
    )


@pytest.mark.parametrize("mode", ["raw-membership", "typed-membership", "raw-list"])
def test_actual_queue_list_removal_keeps_global_pin_and_never_emits_pin_tombstone(pair, mode):
    a, b, service, ta, tb = pair
    actual_queue_list(a)
    toggle(a)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    before = a.history()
    if mode == "raw-membership":
        write(a, "DELETE FROM list_papers WHERE list_id='queue'")
    elif mode == "raw-list":
        write(a, "DELETE FROM lists WHERE id='queue'")
    else:
        a.save(
            a.new_graph_operation("membership", membership_id("queue", SOURCE), {}, action="delete")
        )
    assert query(a, "SELECT scope,paper_id,pinned_at FROM pins") == [("queue", "a-source", STAMP)]
    assert not any(op["entity_type"] == "research_content" for op in a.journal.pending())
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert query(b, "SELECT scope,paper_id,pinned_at FROM pins") == [("queue", "b-source", STAMP)]
    assert len(a.history()) > len(before)


def old_cleanup(a, sql=PREVIOUS):
    with a.journal.transaction() as conn:
        conn.execute("DROP TRIGGER paperfact_pin_membership_delete")
        conn.execute(sql)


def cleanup_sql(a):
    return query(a, "SELECT sql FROM sqlite_master WHERE name='paperfact_pin_membership_delete'")[
        0
    ][0]


def test_known_previous_cleanup_requires_explicit_install_and_rolls_back_or_retries(pair):
    a, *_ = pair
    old_cleanup(a)
    original = cleanup_sql(a)
    before = a.journal.pending()
    with pytest.raises(ValueError, match="cleanup"):
        toggle(a)
    assert (
        cleanup_sql(a) == original
        and a.journal.pending() == before
        and query(a, "SELECT * FROM pins") == []
    )
    with pytest.raises(sqlite3.OperationalError):
        write(a, "INSERT INTO pins VALUES('queue','a-source',?)", (STAMP,))
    assert (
        cleanup_sql(a) == original
        and a.journal.pending() == before
        and query(a, "SELECT * FROM pins") == []
    )
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="a")
        assert pin_cleanup_ready(conn)
        conn.rollback()
    assert cleanup_sql(a) == original
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="a")
        assert pin_cleanup_ready(conn)
        conn.commit()
    assert a.journal.pending() == before
    assert toggle(a)["changed"]


@pytest.mark.parametrize("variant", ["unrelated", "literal-case", "literal-space"])
def test_unknown_cleanup_is_not_rewritten_by_explicit_install(pair, variant):
    a, *_ = pair
    from paper_daily.sync_content import PIN_CLEANUP_SQL, pin_cleanup_recognized

    sql = (
        "CREATE TRIGGER paperfact_pin_membership_delete "
        "AFTER DELETE ON list_papers BEGIN SELECT 1; END"
        if variant == "unrelated"
        else PIN_CLEANUP_SQL.replace(
            "'queue'", "'QUEUE'" if variant == "literal-case" else "'qu eue'"
        )
    )
    old_cleanup(a, sql)
    with a.journal.transaction() as conn:
        assert not pin_cleanup_recognized(conn)

    original = cleanup_sql(a)
    before = a.journal.pending()
    with closing(sqlite3.connect(a.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="a")
        conn.commit()
    assert cleanup_sql(a) == original
    with pytest.raises(ValueError, match="cleanup"):
        toggle(a)
    assert a.journal.pending() == before and query(a, "SELECT * FROM pins") == []


def test_exact_previous_source_can_prepare_fresh_safe_copy_without_source_repair(tmp_path):
    from test_list_pins import legacy

    from paper_daily.workspace_enrollment import EnrollmentService

    database = legacy(tmp_path / "old", scope="queue", member=False)
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("DROP TRIGGER paperfact_pin_membership_delete")
        conn.execute(PREVIOUS)
    before = database.read_bytes()
    from paper_daily.list_pins import set_pinned

    with closing(sqlite3.connect(database)) as conn, pytest.raises(ValueError, match="cleanup"):
        set_pinned(conn, "queue", "paper", True, pinned_at=STAMP)
    assert database.read_bytes() == before
    service = EnrollmentService(database)
    assert service.plan()["supported"]
    assert database.read_bytes() == before
    result = service.prepare(
        tmp_path / "fresh", backup_output=tmp_path / "fresh.zip", request_id=str(uuid4())
    )
    with closing(sqlite3.connect(result["database"])) as conn:
        assert pin_cleanup_ready(conn)
        assert conn.execute("SELECT * FROM pins").fetchall() == [("queue", "paper", STAMP)]
    assert database.read_bytes() == before


def test_remote_queue_pin_refuses_unsafe_schema_without_advancing_cursor_then_explicit_retry(pair):
    a, b, service, ta, tb = pair
    old_cleanup(b)
    before_sql = cleanup_sql(b)
    toggle(a)
    a.sync_once(service, ta)
    cursor = b.status()["cursor"]
    events = service.pull(tb, after=cursor)
    with pytest.raises(ValueError, match="cleanup"):
        b.receive(events)
    assert b.status()["cursor"] == cursor and query(b, "SELECT * FROM pins") == []
    assert cleanup_sql(b) == before_sql
    with closing(sqlite3.connect(b.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="b")
        conn.commit()
    b.receive(events)
    assert query(b, "SELECT scope,paper_id,pinned_at FROM pins") == [("queue", "b-source", STAMP)]
