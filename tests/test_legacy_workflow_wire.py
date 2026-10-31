"""Real SQL capture and two-peer legacy metadata projection, no inferred lists."""

import sqlite3

import pytest
from test_sync_capture import bound as bound_fixture
from test_sync_capture import make, seed

from paper_daily import store
from paper_daily.sync_capture import StaleCaptureError, expecting, observe_content
from paper_daily.sync_service import ReferenceService

bound = bound_fixture
STAMP = "2026-10-30T12:34:56.123456+08:00"


def populate():
    seed()
    with store.connect() as conn:
        store.upsert_papers(
            conn, [dict(id="parent", title="Parent", venue="Fixture", year=2026, source="fixture")]
        )
        conn.execute(
            "INSERT INTO queue VALUES(?,?,'deferred','manual',?,?,?,NULL,?)",
            ("local-paper", -2.75, "parent", "Exact reason", STAMP, STAMP),
        )
        conn.execute(
            "INSERT INTO reading_log VALUES(27,?,?,NULL,NULL,?)",
            ("local-paper", STAMP, "Original event note"),
        )


def test_real_queue_event_capture_preserves_source_values_and_fresh_portable_identity(
    bound, tmp_path
):
    populate()
    events = [
        item
        for item in bound.journal.pending()
        if item.get("payload", {}).get("feature") == "reading_event"
    ]
    queue = [
        item
        for item in bound.journal.pending()
        if item.get("payload", {}).get("feature") == "queue_entry"
    ]
    assert len(events) == len(queue) == 1
    assert events[0]["payload"]["key"] != "27"
    assert queue[0]["payload"]["data"]["rank"] == -2.75
    assert queue[0]["payload"]["data"]["role"] == "manual"
    assert len(queue[0]["parents"]) == 2
    service = ReferenceService(tmp_path / "server.db")
    ta = service.enroll("workspace", "a")
    peer = make(tmp_path / "b.sqlite", "b")
    tb = service.enroll("workspace", "b")
    bound.sync_once(service, ta)
    peer.sync_once(service, tb)
    with peer.journal.transaction() as conn:
        paper = conn.execute(
            "SELECT local_id FROM research_paper_identity WHERE sync_id=?",
            (queue[0]["payload"]["scope"]["id"],),
        ).fetchone()[0]
        parent = conn.execute(
            "SELECT local_id FROM research_paper_identity WHERE sync_id=?",
            (queue[0]["payload"]["data"]["parent_id"],),
        ).fetchone()[0]
        actual = conn.execute(
            "SELECT rank,state,role,parent_id,reason,queued_at,delivered_at,read_at "
            "FROM queue WHERE paper_id=?",
            (paper,),
        ).fetchone()
        assert tuple(actual) == (
            -2.75,
            "deferred",
            "manual",
            parent,
            "Exact reason",
            STAMP,
            None,
            STAMP,
        )
        event = conn.execute(
            "SELECT id,paper_id,delivered_at,brief_path,role,note FROM reading_log"
        ).fetchone()
        assert tuple(event)[1:] == (paper, STAMP, None, None, "Original event note")
        mapped = conn.execute(
            "SELECT local_id FROM research_content_identity "
            "WHERE feature='reading_event' AND sync_key=?",
            (events[0]["payload"]["key"],),
        ).fetchone()[0]
        assert mapped == event[0]
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 1
    with store.connect() as conn:
        assert conn.execute("SELECT id FROM reading_log").fetchone()[0] == 27


def test_repeat_scalar_mutation_is_one_row_and_explicit_stale_token_still_retained(bound):
    populate()
    with store.connect() as conn:
        row = dict(conn.execute("SELECT * FROM queue WHERE paper_id='local-paper'").fetchone())
        old = observe_content(conn, "queue", row)
    with store.connect() as conn:
        conn.execute("UPDATE queue SET rank=-7.5 WHERE paper_id='local-paper'")
    count = len(bound.journal.pending())
    with store.connect() as conn:
        conn.execute("UPDATE queue SET rank=-7.5 WHERE paper_id='local-paper'")
    assert len(bound.journal.pending()) == count
    with pytest.raises(StaleCaptureError), store.connect() as conn, expecting(conn, [old]):
        conn.execute("UPDATE queue SET role='stale draft' WHERE paper_id='local-paper'")
    with store.connect() as conn:
        row = conn.execute("SELECT rank,role FROM queue WHERE paper_id='local-paper'").fetchone()
        assert tuple(row) == (-7.5, "manual")
        assert conn.execute("SELECT COUNT(*) FROM reading_log").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM research_capture_candidates").fetchone()[0] == 1


def test_delivery_identity_timestamp_cannot_be_rekeyed_by_update(bound):
    populate()
    count = len(bound.journal.pending())
    with pytest.raises(sqlite3.OperationalError), store.connect() as conn:
        conn.execute("UPDATE reading_log SET delivered_at='2026-11-01T00:00:00+00:00' WHERE id=27")
    assert len(bound.journal.pending()) == count
    with store.connect() as conn:
        assert (
            conn.execute("SELECT delivered_at FROM reading_log WHERE id=27").fetchone()[0] == STAMP
        )
