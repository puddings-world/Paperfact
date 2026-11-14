"""Explicit graph projectors receive immutable source and separate visibility."""

import copy
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from test_sync_graph_client import LIST, MEMBER, membership_payload, save, saved, seed, writer
from test_sync_graph_client import pair as pair

from paper_daily.sync_client import SyncClient


def with_projector(client, callback):
    return SyncClient.attach_existing(client.journal, client.writer, projection_writer=callback)


def recording(conn, operation, *, visible):
    conn.execute(
        "INSERT INTO projected_sources VALUES(?,?,?,?)",
        (operation["entity_type"], operation["entity_id"], json.dumps(operation), int(visible)),
    )
    value = copy.deepcopy(operation)
    if not visible:
        value.update(action="delete", payload={})
    writer(conn, value)


def record_table(client):
    with closing(client.journal._connect()) as conn, conn:
        conn.execute("CREATE TABLE projected_sources(kind TEXT,id TEXT,operation TEXT,visible INT)")


def test_actual_receive_keeps_hidden_put_and_separate_visibility_without_changing_events(pair):
    service, a, b, ta, tb = pair
    record_table(b)
    b = with_projector(b, recording)
    seed(a)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    save(a, "list", LIST, {}, action="delete")
    a.sync_once(service, ta)
    events = service.pull(tb, after=b.status()["cursor"])
    original_events = copy.deepcopy(events)
    b.receive(events)
    assert events == original_events
    assert saved(b, "membership", MEMBER) is None
    with closing(b.journal._connect()) as conn:
        hidden = conn.execute(
            "SELECT operation FROM projected_sources WHERE kind='membership' AND visible=0"
        ).fetchone()
    source = json.loads(hidden[0])
    assert source["action"] == "put" and source["payload"] == membership_payload()
    before = b.status(), b.history()
    assert b.receive(events)["received"] == 0
    assert (b.status(), b.history()) == before


@pytest.mark.parametrize("failure", ["late-write", "changed-operation", "transaction-control"])
def test_projector_failure_rolls_back_actual_events_rows_and_cursor_and_retry_works(pair, failure):
    service, a, b, ta, tb = pair
    record_table(b)
    seed(a)
    a.sync_once(service, ta)
    events = service.pull(tb)

    def broken(conn, operation, *, visible):
        recording(conn, operation, visible=visible)
        if operation["entity_type"] != "membership":
            return
        if failure == "late-write":
            raise RuntimeError("fixture late projection failure")
        if failure == "changed-operation":
            operation["payload"]["citation"] = "Unexpected mutation"
        else:
            conn.commit()

    failing = with_projector(b, broken)
    with pytest.raises((RuntimeError, ValueError, sqlite3.DatabaseError)):
        failing.receive(events)
    assert failing.status()["cursor"] == 0 and failing.history() == []
    with closing(b.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM research").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM projected_sources").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM paperfact_sync_graph").fetchone()[0] == 0
    restored = with_projector(b, recording)
    assert restored.receive(events)["received"] == len(events)
    assert saved(restored, "membership", MEMBER) == membership_payload()


@pytest.mark.parametrize("factory", [SyncClient, SyncClient.attach_existing])
def test_invalid_projector_is_rejected_before_opening_or_creating_the_database(tmp_path, factory):
    path = tmp_path / "must-not-create.db"

    def unexpected():
        pytest.fail("Invalid projector must fail before opening the journal")

    journal = SimpleNamespace(path=path, _connect=unexpected)
    with pytest.raises(ValueError, match="Projection writer"):
        factory(journal, writer, projection_writer="not-callable")
    assert not path.exists()


def test_attach_with_projector_performs_no_ddl_or_database_writes(pair):
    _service, _a, b, _ta, _tb = pair
    with closing(b.journal._connect()) as conn:
        before = list(conn.iterdump())
    attached = with_projector(b, recording)
    assert attached.projection_writer is recording
    with closing(b.journal._connect()) as conn:
        assert list(conn.iterdump()) == before
