"""Production-schema adapter behavior on isolated synthetic databases."""

import sqlite3

import pytest

from paper_daily.store import SCHEMA
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import initialize, note_identity, prepare, research_writer


def operation(
    op_id="op-1", *, kind="list", entity="list-a", predecessor=None, device="device-a", action="put"
):
    return {
        "version": 1,
        "operation_id": op_id,
        "workspace_id": "workspace-a",
        "device_id": device,
        "entity_type": kind,
        "entity_id": entity,
        "action": action,
        "base_revision": 0,
        "depends_on": predecessor,
        "payload": {}
        if action == "delete"
        else {"name": "Reading", "note": "Background"}
        if kind == "list"
        else {"paper_id": "paper-a", "body": "Research observation"},
    }


def make_database(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO papers(id,venue,year,title,title_key,source) VALUES(?,?,?,?,?,?)",
            [
                (identity, "Fixture", 2026, identity, identity, "fixture")
                for identity in ("paper-a", "paper-b")
            ],
        )
    return path


@pytest.fixture
def path(tmp_path):
    return make_database(tmp_path / "research.db")


def enrolled(path, device="device-a"):
    prepare(path, workspace_id="workspace-a", device_id=device)
    return Journal(path, workspace_id="workspace-a", device_id=device)


def rows(path, query, args=()):
    with sqlite3.connect(path) as conn:
        return conn.execute(query, args).fetchall()


def add_legacy_note(path, *, kind="note", page=None, anchor=None, body="Original"):
    with sqlite3.connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO notes(paper_id,body,created_at,kind,page,anchor) VALUES(?,?,?,?,?,?)",
            ("paper-a", body, "2020-01-01T00:00:00+00:00", kind, page, anchor),
        )
        return cursor.lastrowid


def test_prepare_preserves_legacy_notes_ids_anchors_and_other_data(path):
    plain_id = add_legacy_note(path)
    add_legacy_note(path, page=3, anchor='{"quote":"source"}')
    before = rows(path, "SELECT * FROM notes ORDER BY id")
    enrolled(path)
    first = rows(path, "SELECT * FROM research_note_identity ORDER BY local_id")
    enrolled(path)
    assert rows(path, "SELECT * FROM notes ORDER BY id") == before
    assert rows(path, "SELECT * FROM research_note_identity ORDER BY local_id") == first
    with sqlite3.connect(path) as conn:
        assert note_identity(conn, plain_id) == first[0][0]
    assert len(rows(path, "SELECT * FROM papers")) == 2


def test_legacy_integer_collisions_on_independent_devices_get_distinct_ids(tmp_path):
    first, second = (make_database(tmp_path / name) for name in ("a.db", "b.db"))
    assert add_legacy_note(first) == add_legacy_note(second) == 1
    enrolled(first, "device-a")
    enrolled(second, "device-b")
    first_id = rows(first, "SELECT sync_id FROM research_note_identity")[0][0]
    second_id = rows(second, "SELECT sync_id FROM research_note_identity")[0][0]
    assert first_id != second_id
    # A note from the other device receives a new local integer, preserving #1.
    incoming = operation(kind="note", entity=first_id)
    with sqlite3.connect(second) as conn:
        conn.execute("BEGIN IMMEDIATE")
        research_writer(conn, incoming)
    assert rows(second, "SELECT id,body FROM notes ORDER BY id") == [
        (1, "Original"),
        (2, "Research observation"),
    ]
    assert rows(
        second, "SELECT local_id FROM research_note_identity WHERE sync_id=?", (first_id,)
    ) == [(2,)]


def test_create_rename_retry_and_list_delete_preserve_paper_research(path):
    note_id = add_legacy_note(path)
    journal = enrolled(path)
    first = operation()
    journal.apply(first, research_writer)
    stamp = rows(path, "SELECT created_at FROM lists")[0][0]
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO lists VALUES('list-b','Other','Keep','earlier')")
        conn.executemany(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES(?,?,0,'earlier')",
            [("list-a", "paper-a"), ("list-b", "paper-a")],
        )
        conn.execute(
            "INSERT INTO dives(paper_id,body,written_at) VALUES('paper-a','Analysis','old')"
        )
    renamed = operation("op-2", predecessor="op-1")
    renamed["payload"]["name"] = "Updated name"
    journal.apply(renamed, research_writer)
    assert rows(path, "SELECT name,created_at FROM lists WHERE id='list-a'") == [
        ("Updated name", stamp)
    ]
    assert journal.apply(first, research_writer)["applied"] is False
    journal.apply(operation("op-3", predecessor="op-2", action="delete"), research_writer)
    assert rows(path, "SELECT id,name FROM lists") == [("list-b", "Other")]
    assert rows(path, "SELECT list_id,paper_id FROM list_papers") == [("list-b", "paper-a")]
    assert rows(path, "SELECT id,body FROM notes") == [(note_id, "Original")]
    assert rows(path, "SELECT body FROM dives") == [("Analysis",)]
    assert len(rows(path, "SELECT * FROM papers")) == 2


def test_existing_legacy_note_edits_keep_local_identity_and_creation_time(path):
    local_id = add_legacy_note(path)
    journal = enrolled(path)
    with sqlite3.connect(path) as conn:
        sync_id = note_identity(conn, local_id)
    incoming = operation(kind="note", entity=sync_id)
    journal.apply(incoming, research_writer)
    assert rows(path, "SELECT id,body,created_at FROM notes") == [
        (local_id, "Research observation", "2020-01-01T00:00:00+00:00")
    ]
    assert len(journal.pending()) == 1


def test_note_create_delete_and_explicit_restore_keep_portable_identity(path):
    journal = enrolled(path)
    incoming = operation(kind="note", entity="note-a")
    journal.apply(incoming, research_writer)
    first = rows(path, "SELECT id,created_at FROM notes")[0]
    journal.apply(
        operation("op-2", kind="note", entity="note-a", predecessor="op-1", action="delete"),
        research_writer,
    )
    assert rows(path, "SELECT * FROM notes") == []
    assert rows(path, "SELECT local_id FROM research_note_identity") == [(None,)]
    journal.apply(
        operation("op-3", kind="note", entity="note-a", predecessor="op-2"), research_writer
    )
    restored = rows(path, "SELECT id,created_at FROM notes")[0]
    assert restored[0] != first[0] and restored[1] == first[1]
    assert rows(path, "SELECT sync_id,local_id FROM research_note_identity") == [
        ("note-a", restored[0])
    ]


@pytest.mark.parametrize(
    "kind,page,anchor", [("quote", None, None), ("note", 0, None), ("note", None, "{}")]
)
@pytest.mark.parametrize("action", ["put", "delete"])
def test_unsupported_note_content_is_never_overwritten(path, kind, page, anchor, action):
    local_id = add_legacy_note(path, kind=kind, page=page, anchor=anchor)
    before = rows(path, "SELECT * FROM notes")
    journal = enrolled(path)
    with sqlite3.connect(path) as conn:
        sync_id = note_identity(conn, local_id)
    with pytest.raises(ValueError, match="not supported"):
        journal.apply(operation(kind="note", entity=sync_id, action=action), research_writer)
    assert rows(path, "SELECT * FROM notes") == before
    assert journal.pending() == []


def test_missing_paper_rejects_atomically_without_inventing_metadata(path):
    journal = enrolled(path)
    incoming = operation(kind="note", entity="note-a")
    incoming["payload"]["paper_id"] = "not-known"
    with pytest.raises(ValueError, match="metadata"):
        journal.apply(incoming, research_writer)
    assert rows(path, "SELECT * FROM notes") == []
    assert rows(path, "SELECT * FROM research_note_identity") == []
    assert len(rows(path, "SELECT * FROM papers")) == 2
    assert journal.pending() == []


def test_note_reassignment_is_rejected_without_losing_content(path):
    journal = enrolled(path)
    journal.apply(operation(kind="note", entity="note-a"), research_writer)
    changed = operation("op-2", kind="note", entity="note-a", predecessor="op-1")
    changed["payload"]["paper_id"] = "paper-b"
    with pytest.raises(ValueError, match="reassigned"):
        journal.apply(changed, research_writer)
    assert rows(path, "SELECT paper_id,body FROM notes") == [("paper-a", "Research observation")]
    assert len(journal.pending()) == 1


def test_external_reuse_of_integer_identity_requires_reconciliation(path):
    local_id = add_legacy_note(path)
    journal = enrolled(path)
    with sqlite3.connect(path) as conn:
        sync_id = note_identity(conn, local_id)
        conn.execute("UPDATE notes SET created_at='different creation',body='Keep new note'")
    with pytest.raises(ValueError, match="reconciliation"):
        journal.apply(operation(kind="note", entity=sync_id), research_writer)
    assert rows(path, "SELECT body FROM notes") == [("Keep new note",)]
    assert journal.pending() == []


def test_journal_failure_rolls_back_note_and_portable_mapping(path):
    journal = enrolled(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TRIGGER fail_receipt BEFORE INSERT ON paperfact_sync_operations "
            "BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="fixture failure"):
        journal.apply(operation(kind="note", entity="note-a"), research_writer)
    assert rows(path, "SELECT * FROM notes") == []
    assert rows(path, "SELECT * FROM research_note_identity") == []
    assert journal.pending() == []


def test_initializer_and_writer_do_not_commit_the_callers_transaction(path):
    local_id = add_legacy_note(path)
    with sqlite3.connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        initialize(conn, workspace_id="workspace-a", device_id="device-a")
        assert note_identity(conn, local_id)
        research_writer(conn, operation())
        assert conn.in_transaction
        conn.rollback()
    assert rows(path, "SELECT * FROM lists") == []
    assert rows(path, "SELECT name FROM sqlite_master WHERE name='research_note_identity'") == []
    assert rows(path, "SELECT body FROM notes") == [("Original",)]


def test_prepare_wrong_binding_preserves_all_research_and_mapping(path):
    add_legacy_note(path)
    enrolled(path)
    before = rows(path, "SELECT * FROM research_note_identity")
    for workspace_id, device_id in [("wrong", "device-a"), ("workspace-a", "wrong")]:
        with pytest.raises(ValueError, match="binding"):
            prepare(path, workspace_id=workspace_id, device_id=device_id)
    assert rows(path, "SELECT * FROM research_note_identity") == before
    assert rows(path, "SELECT body FROM notes") == [("Original",)]


def test_unbound_writer_and_wrong_workspace_are_rejected(path):
    enrolled(path)
    with sqlite3.connect(path) as conn:
        with pytest.raises(ValueError, match="transaction"):
            research_writer(conn, operation())
        conn.execute("BEGIN IMMEDIATE")
        wrong = operation()
        wrong["workspace_id"] = "wrong"
        with pytest.raises(ValueError, match="workspace"):
            research_writer(conn, wrong)
    assert rows(path, "SELECT * FROM lists") == []


def test_prepare_missing_path_never_creates_database(tmp_path):
    path = tmp_path / "typo.db"
    with pytest.raises(sqlite3.OperationalError):
        prepare(path, workspace_id="workspace-a", device_id="device-a")
    assert not path.exists()


def test_incompatible_schema_is_not_partially_enrolled(tmp_path):
    path = tmp_path / "wrong.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE notes(id INTEGER)")
    with pytest.raises(ValueError, match="compatible"):
        prepare(path, workspace_id="workspace-a", device_id="device-a")
    assert rows(path, "SELECT name FROM sqlite_master WHERE type='table'") == [("notes",)]
