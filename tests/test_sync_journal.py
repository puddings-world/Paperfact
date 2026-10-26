"""Behavioral checks for the opt-in journal, using synthetic research databases."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from paper_daily.sync_journal import Journal


def operation(identity="op-1", *, predecessor=None, kind="list", entity="entity-1"):
    return {
        "version": 1,
        "operation_id": identity,
        "workspace_id": "workspace-a",
        "device_id": "device-a",
        "entity_type": kind,
        "entity_id": entity,
        "action": "put",
        "base_revision": 0,
        "depends_on": predecessor,
        "payload": {"name": "Reading", "note": "Background"}
        if kind == "list"
        else {"paper_id": "paper-example", "body": "First observation"},
    }


def writer(conn, value):
    table = "lists" if value["entity_type"] == "list" else "notes"
    if value["action"] == "delete":
        conn.execute(f"DELETE FROM {table} WHERE id=?", (value["entity_id"],))
    elif table == "lists":
        conn.execute(
            "INSERT INTO lists VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "name=excluded.name,note=excluded.note",
            (value["entity_id"], value["payload"]["name"], value["payload"]["note"]),
        )
    else:
        conn.execute(
            "INSERT INTO notes VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "paper=excluded.paper,body=excluded.body",
            (value["entity_id"], value["payload"]["paper_id"], value["payload"]["body"]),
        )


@pytest.fixture
def journal(tmp_path):
    path = tmp_path / "research.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE lists(id TEXT PRIMARY KEY,name TEXT,note TEXT)")
        conn.execute("CREATE TABLE notes(id TEXT PRIMARY KEY,paper TEXT,body TEXT)")
    return Journal(path, workspace_id="workspace-a", device_id="device-a")


def content(journal, table="lists"):
    with sqlite3.connect(journal.path) as conn:
        return conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()


def reopen(journal):
    return Journal(journal.path, workspace_id="workspace-a", device_id="device-a")


def test_offline_chain_survives_restart_and_acknowledgment(journal):
    first = operation()
    second = operation("op-2", predecessor="op-1")
    second["payload"]["name"] = "Renamed"
    journal.apply(first, writer)
    journal.apply(second, writer)
    restarted = reopen(journal)
    assert content(restarted) == [("entity-1", "Renamed", "Background")]
    assert restarted.pending() == [first, second]
    assert restarted.pending(limit=1) == [first]
    with pytest.raises(ValueError, match="predecessor"):
        restarted.acknowledge("op-2", 2)
    restarted.acknowledge("op-1", 1)
    restarted.acknowledge("op-1", 1)
    restarted.acknowledge("op-2", 2)
    assert reopen(journal).pending() == []
    assert not restarted.apply(first, lambda *_: pytest.fail("replayed acknowledged write"))[
        "applied"
    ]
    assert content(journal)[0][1] == "Renamed"
    with pytest.raises(ValueError, match="revision changed"):
        restarted.acknowledge("op-1", 3)


def test_note_edit_and_delete_preserve_pending_history(journal):
    first = operation(kind="note")
    journal.apply(first, writer)
    edit = operation("op-2", predecessor="op-1", kind="note")
    edit["payload"]["body"] = "Updated research note"
    journal.apply(edit, writer)
    assert content(journal, "notes") == [("entity-1", "paper-example", "Updated research note")]
    delete = operation("op-3", predecessor="op-2", kind="note")
    delete.update(action="delete", payload={})
    journal.apply(delete, writer)
    assert content(journal, "notes") == []
    assert reopen(journal).pending() == [first, edit, delete]


def test_concurrent_replays_write_once_and_changed_replay_is_rejected(journal):
    calls = []

    def write(conn, value):
        calls.append(value["operation_id"])
        writer(conn, value)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: reopen(journal).apply(operation(), write), range(20)))
    assert calls == ["op-1"]
    assert sum(result["applied"] for result in results) == 1
    assert len({result["sequence"] for result in results}) == 1
    changed = operation()
    changed["payload"]["name"] = "Different content"
    with pytest.raises(ValueError, match="reused"):
        journal.apply(changed, write)
    assert content(journal) == [("entity-1", "Reading", "Background")]
    assert journal.pending() == [operation()]


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_writer_failure_rolls_back_research_and_can_retry(journal, failure):
    def fail(conn, value):
        writer(conn, value)
        raise failure("interrupted")

    with pytest.raises(failure):
        journal.apply(operation(), fail)
    assert content(journal) == []
    assert journal.pending() == []
    assert journal.apply(operation(), writer)["applied"]
    assert len(content(journal)) == 1


def test_outbox_storage_failure_rolls_back_research(journal):
    with sqlite3.connect(journal.path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_outbox BEFORE INSERT ON paperfact_sync_operations "
            "BEGIN SELECT RAISE(ABORT, 'storage failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="storage failure"):
        journal.apply(operation(), writer)
    assert content(journal) == []
    assert reopen(journal).pending() == []


@pytest.mark.parametrize(
    "escape",
    [
        lambda conn: conn.commit(),
        lambda conn: conn.executescript("DELETE FROM lists;"),
        lambda conn: conn.execute("CREATE TABLE surprise(id TEXT)"),
        lambda conn: conn.execute("DELETE FROM paperfact_sync_operations"),
        lambda conn: conn.execute("ATTACH DATABASE ':memory:' AS other"),
    ],
)
def test_writer_cannot_accidentally_escape_atomic_transaction(journal, escape):
    def fail(conn, value):
        writer(conn, value)
        escape(conn)

    with pytest.raises(sqlite3.DatabaseError):
        journal.apply(operation(), fail)
    assert content(journal) == []
    assert journal.pending() == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", 2),
        ("version", True),
        ("base_revision", -1),
        ("workspace_id", "other"),
        ("device_id", "other"),
        ("entity_type", "credentials"),
        ("operation_id", "../escape"),
        ("depends_on", "op-1"),
        ("action", "unknown"),
        ("payload", {"name": " ", "note": ""}),
        ("payload", {"name": "Reading", "note": "", "credential": "excluded"}),
        ("payload", {"name": "Reading", "note": "x" * (256 * 1024)}),
    ],
)
def test_invalid_operation_never_calls_writer(journal, field, value):
    invalid = operation()
    invalid[field] = value
    with pytest.raises(ValueError):
        journal.apply(invalid, lambda *_: pytest.fail("invalid operation reached writer"))
    assert content(journal) == []
    assert journal.pending() == []


@pytest.mark.parametrize(
    "predecessor,entity", [(None, "entity-1"), ("missing", "entity-1"), ("op-1", "another-entity")]
)
def test_missing_or_unrelated_dependency_is_rejected(journal, predecessor, entity):
    journal.apply(operation(), writer)
    with pytest.raises(ValueError):
        journal.apply(operation("op-2", predecessor=predecessor, entity=entity), writer)
    assert len(content(journal)) == 1
    assert journal.pending() == [operation()]


def test_binding_mismatch_never_reassigns_existing_workspace(journal):
    journal.apply(operation(), writer)
    with pytest.raises(ValueError, match="binding"):
        Journal(journal.path, workspace_id="another-workspace", device_id="device-a")
    with pytest.raises(ValueError, match="binding"):
        Journal(journal.path, workspace_id="workspace-a", device_id="another-device")
    assert reopen(journal).pending() == [operation()]
    with sqlite3.connect(journal.path) as conn:
        conn.execute("UPDATE paperfact_sync_identity SET device='replacement'")
    with pytest.raises(ValueError, match="binding"):
        journal.apply(operation("op-2", predecessor="op-1"), writer)
    with pytest.raises(ValueError, match="binding"):
        journal.pending()
    with pytest.raises(ValueError, match="binding"):
        journal.acknowledge("op-1", 1)
    assert content(journal) == [("entity-1", "Reading", "Background")]


@pytest.mark.parametrize("limit", [0, -1, 1001, True])
def test_pending_batch_is_bounded(journal, limit):
    with pytest.raises(ValueError):
        journal.pending(limit)


def test_returned_pending_payload_cannot_modify_saved_operation(journal):
    original = operation()
    journal.apply(original, writer)
    original["payload"]["name"] = "caller changed"
    batch = journal.pending()
    batch[0]["payload"]["name"] = "consumer changed"
    assert journal.pending() == [operation()]
    assert content(journal)[0][1] == "Reading"


@pytest.mark.parametrize("target", [None, "", "../other", "op-1"])
def test_invalid_resolution_reference_never_writes(journal, target):
    value = operation()
    value["resolution_of"] = target
    with pytest.raises(ValueError):
        journal.apply(value, writer)
    assert content(journal) == []
    assert journal.pending() == []


def test_resolution_reference_is_preserved_in_atomic_outbox(journal):
    value = operation()
    value["resolution_of"] = "conflicting-operation"
    journal.apply(value, writer)
    assert journal.pending() == [value]
    assert content(journal) == [("entity-1", "Reading", "Background")]
