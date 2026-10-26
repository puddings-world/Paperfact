"""Two real research schemas synchronized through the isolated reference service."""

import sqlite3

import pytest

from paper_daily.store import SCHEMA
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import note_identity, prepare, research_writer
from paper_daily.sync_service import ReferenceService


def database(path, device):
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,venue,year,title,title_key,source) "
            "VALUES('paper-a','Fixture',2026,'Shared paper','sharedpaper','fixture')"
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at,kind,page,anchor) "
            "VALUES('paper-a',?,'old','note',3,'{" + '"quote":"keep source"' + "}')",
            (f"{device} anchored note",),
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) VALUES('paper-a',?,'old')",
            (f"{device} unrelated note",),
        )
    return reopen(path, device)


def reopen(path, device):
    prepare(path, workspace_id="workspace", device_id=device)
    return SyncClient(Journal(path, workspace_id="workspace", device_id=device), research_writer)


def query(client, sql, args=()):
    with sqlite3.connect(client.journal.path) as conn:
        return conn.execute(sql, args).fetchall()


def original_notes(client):
    return query(client, "SELECT * FROM notes WHERE id<=2 ORDER BY id")


def portable_note(client, identity):
    return query(
        client,
        "SELECT n.id,n.paper_id,n.body FROM research_note_identity AS m "
        "JOIN notes AS n ON n.id=m.local_id WHERE m.sync_id=?",
        (identity,),
    )


def save_note(client, body="Initial observation", identity="portable-note"):
    operation = client.new_operation("note", identity, {"paper_id": "paper-a", "body": body})
    client.save(operation)
    return operation


@pytest.fixture
def pair(tmp_path):
    a, b = database(tmp_path / "a.db", "a"), database(tmp_path / "b.db", "b")
    service = ReferenceService(tmp_path / "service.db")
    return service, a, b, service.enroll("workspace", "a"), service.enroll("workspace", "b")


def test_real_schema_list_and_note_roundtrip_retry_and_reopen(pair):
    service, a, b, token_a, token_b = pair
    a_original, b_original = original_notes(a), original_notes(b)
    a.save(a.new_operation("list", "reading", {"name": "First name", "note": ""}))
    a.save(a.new_operation("list", "reading", {"name": "Renamed research", "note": "Context"}))
    first = save_note(a)
    # A new preexisting peer note owns the same local integer allocated on A.
    with sqlite3.connect(b.journal.path) as conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) "
            "VALUES('paper-a','Peer-only third note','old')"
        )
    b = reopen(b.journal.path, "b")
    a = reopen(a.journal.path, "a")
    assert a.status()["pending"] == 3
    a.sync_once(service, token_a)
    b.sync_once(service, token_b)
    assert query(a, "SELECT id,name,note FROM lists") == query(b, "SELECT id,name,note FROM lists")
    assert query(b, "SELECT name,note FROM lists") == [("Renamed research", "Context")]
    assert portable_note(a, "portable-note") == [(3, "paper-a", "Initial observation")]
    assert portable_note(b, "portable-note") == [(4, "paper-a", "Initial observation")]
    assert query(b, "SELECT body FROM notes WHERE id=3") == [("Peer-only third note",)]
    assert service.push(token_a, first)["sequence"] == 3
    assert b.receive(service.pull(token_b))["received"] == 0
    a = reopen(a.journal.path, "a")
    b = reopen(b.journal.path, "b")
    save_note(b, "Read and edited on the second device")
    b.sync_once(service, token_b)
    a.sync_once(service, token_a)
    assert portable_note(a, "portable-note")[0][2] == "Read and edited on the second device"
    assert portable_note(b, "portable-note")[0][0] == 4
    a.save(a.new_operation("note", "portable-note", {}, action="delete"))
    a.sync_once(service, token_a)
    b.sync_once(service, token_b)
    for client, original in [(a, a_original), (b, b_original)]:
        assert original_notes(client) == original
        assert portable_note(client, "portable-note") == []
        assert client.status() == {
            "cursor": 5,
            "pending": 0,
            "awaiting_receipts": 0,
            "conflicts": 0,
            "deferred": 0,
        }
        assert query(
            client,
            "SELECT local_id FROM research_note_identity WHERE sync_id=?",
            ("portable-note",),
        ) == [(None,)]
    assert len(reopen(b.journal.path, "b").history()) == 5


def test_remote_failure_rolls_back_real_notes_mappings_list_and_cursor(pair):
    service, a, b, token_a, token_b = pair
    before_notes = query(b, "SELECT * FROM notes ORDER BY id")
    before_mappings = query(b, "SELECT * FROM research_note_identity ORDER BY local_id")
    a.save(a.new_operation("list", "reading", {"name": "Reading", "note": ""}))
    save_note(a, identity="note-one")
    save_note(a, identity="note-two")
    a.sync_once(service, token_a)

    def interrupted(conn, operation):
        research_writer(conn, operation)
        if operation["entity_id"] == "note-two":
            raise RuntimeError("Simulated interruption after research write")

    b.writer = interrupted
    with pytest.raises(RuntimeError, match="interruption"):
        b.sync_once(service, token_b)
    assert query(b, "SELECT * FROM notes ORDER BY id") == before_notes
    assert query(b, "SELECT * FROM research_note_identity ORDER BY local_id") == before_mappings
    assert query(b, "SELECT * FROM lists") == []
    assert b.history() == []
    assert b.status() == {
        "cursor": 0,
        "pending": 0,
        "awaiting_receipts": 0,
        "conflicts": 0,
        "deferred": 0,
    }
    b = reopen(b.journal.path, "b")
    b.sync_once(service, token_b)
    assert len(portable_note(b, "note-one")) == len(portable_note(b, "note-two")) == 1
    assert query(b, "SELECT name FROM lists") == [("Reading",)]
    assert original_notes(b) == before_notes
    assert b.status()["cursor"] == 3


def test_enrolled_legacy_note_transfers_without_overwriting_peer_same_integer(pair):
    service, a, b, token_a, token_b = pair
    before_b = original_notes(b)
    with sqlite3.connect(a.journal.path) as conn:
        source_identity = note_identity(conn, 2)
    with sqlite3.connect(b.journal.path) as conn:
        peer_identity = note_identity(conn, 2)
    assert source_identity != peer_identity
    save_note(a, "Legacy note continued on desktop", source_identity)
    a.sync_once(service, token_a)
    b.sync_once(service, token_b)
    assert portable_note(a, source_identity)[0][0] == 2
    assert portable_note(b, source_identity)[0][0] == 3
    assert original_notes(b) == before_b
    assert query(b, "SELECT sync_id FROM research_note_identity WHERE local_id=2") == [
        (peer_identity,)
    ]
    b = reopen(b.journal.path, "b")
    assert portable_note(b, source_identity)[0][2] == "Legacy note continued on desktop"


def test_real_note_conflict_and_delete_retain_history_and_anchored_notes(pair):
    service, a, b, token_a, token_b = pair
    a_original, b_original = original_notes(a), original_notes(b)
    save_note(a)
    a.sync_once(service, token_a)
    b.sync_once(service, token_b)
    save_note(a, "Desktop interpretation")
    save_note(b, "Offline interpretation")
    a.sync_once(service, token_a)
    b.sync_once(service, token_b)
    a.sync_once(service, token_a)
    for client in (a, b):
        assert portable_note(client, "portable-note")[0][2] == "Desktop interpretation"
        assert client.history(conflicts_only=True)[0]["operation"]["payload"]["body"] == (
            "Offline interpretation"
        )
    save_note(b, "Edit retained despite deletion")
    a.save(a.new_operation("note", "portable-note", {}, action="delete"))
    a.sync_once(service, token_a)
    b.sync_once(service, token_b)
    a.sync_once(service, token_a)
    for client, original in [(a, a_original), (b, b_original)]:
        assert portable_note(client, "portable-note") == []
        assert original_notes(client) == original
        assert [
            event["operation"]["payload"]["body"] for event in client.history(conflicts_only=True)
        ] == ["Offline interpretation", "Edit retained despite deletion"]
        assert client.status()["pending"] == 0
    assert len(reopen(b.journal.path, "b").history(conflicts_only=True)) == 2


def test_real_research_pair_converges_and_resolves_conflict_over_loopback_http(pair):
    import threading

    from paper_daily.sync_http import HttpTransport, make_server

    service, a, b, token_a, token_b = pair
    originals = original_notes(a), original_notes(b)
    server = make_server(service)
    worker = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    worker.start()
    try:
        with HttpTransport(f"http://127.0.0.1:{server.server_port}") as transport:
            save_note(a, "Shared original")
            a.sync_once(transport, token_a)
            b.sync_once(transport, token_b)
            save_note(a, "Desktop interpretation")
            save_note(b, "Mobile interpretation")
            a.sync_once(transport, token_a)
            b.sync_once(transport, token_b)
            conflict = b.history(conflicts_only=True)[0]
            b.resolve_conflict(conflict["sequence"], choice="incoming", operation_id="http-resolve")
            b.sync_once(transport, token_b)
            a.sync_once(transport, token_a)
            assert portable_note(a, "portable-note")[0][2] == "Mobile interpretation"
            assert portable_note(b, "portable-note")[0][2] == "Mobile interpretation"
            assert a.status()["conflicts"] == b.status()["conflicts"] == 0
            assert len(a.history(conflicts_only=True)) == len(b.history(conflicts_only=True)) == 1
            assert original_notes(a) == originals[0]
            assert original_notes(b) == originals[1]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        assert not worker.is_alive()
