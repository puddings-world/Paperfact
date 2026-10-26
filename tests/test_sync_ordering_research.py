"""Ordering writes affect only existing research presentation, never membership."""

import json
import sqlite3
from uuid import NAMESPACE_URL, uuid5

import pytest
from test_sync_reading_state_research import (
    LIST,
    MEMBER,
    PAPER,
    STAMP,
    database,
    operation,
    paper_payload,
    ref,
    save,
)

from paper_daily.sync_ordering import observed_set
from paper_daily.sync_research import prepare, research_order_writer
from paper_daily.sync_schema_v2 import membership_id

SECOND = str(uuid5(NAMESPACE_URL, "ordering:second-paper"))
SECOND_MEMBER = membership_id(LIST, SECOND)


def item(identity, incarnation="a"):
    return {"id": identity, "incarnation": incarnation}


def scope(workspace=False, incarnation="a"):
    return {
        "kind": "workspace_list_order" if workspace else "list_order",
        "id": "workspace-lists" if workspace else LIST,
        "incarnation": None if workspace else incarnation,
        "workspace_id": "workspace",
    }


def ordered_operation(items, *, workspace=False, action="put", op_id="reorder"):
    value = operation(
        "workspace_list_order" if workspace else "list_order",
        "workspace-lists" if workspace else LIST,
        {},
        op_id=op_id,
        action=action,
        parents=[] if workspace else [ref("list", LIST)],
    )
    if action == "put":
        value["payload"] = {"items": items, "observed_set": observed_set(value, items)}
        if not workspace:
            value["payload"]["list_id"] = LIST
    return value


def seeded(path):
    journal = database(path)
    save(journal, operation("paper", SECOND, paper_payload()))
    save(
        journal,
        operation(
            "membership",
            SECOND_MEMBER,
            {"list_id": LIST, "paper_id": SECOND, "citation": "Second", "added_at": STAMP},
            parents=[ref("list", LIST), ref("paper", SECOND)],
        ),
    )
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE list_papers SET state='read',delivered_at=?,read_at=?", (STAMP, STAMP))
        conn.execute("INSERT INTO kv VALUES('private.setting','do-not-export')")
        conn.execute(
            "INSERT INTO queue(paper_id,rank,state) VALUES(?,42,'deferred')", ("sync:" + PAPER,)
        )
    return journal


def positions(path):
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT paper_id,position FROM list_papers WHERE list_id=? ORDER BY position",
            (LIST,),
        ).fetchall()


def content(path):
    with sqlite3.connect(path) as conn:
        return {
            "members": conn.execute(
                "SELECT list_id,paper_id,state,citation,added_at,delivered_at,read_at "
                "FROM list_papers ORDER BY list_id,paper_id"
            ).fetchall(),
            "papers": conn.execute("SELECT * FROM papers ORDER BY id").fetchall(),
            "lists": conn.execute("SELECT * FROM lists ORDER BY id").fetchall(),
            "queue": conn.execute("SELECT * FROM queue").fetchall(),
            "settings": conn.execute("SELECT * FROM kv WHERE key!='lists.order'").fetchall(),
        }


def test_local_reorder_retry_and_reopen_only_change_dense_positions(tmp_path):
    path = tmp_path / "research.db"
    journal = seeded(path)
    before = content(path)
    value = ordered_operation([item(SECOND_MEMBER), item(MEMBER)])
    save(journal, value)
    save(journal, value)
    prepare(path, workspace_id="workspace", device_id="device")
    assert positions(path) == [("sync:" + SECOND, 0), ("sync:" + PAPER, 1)]
    assert content(path) == before
    assert len([v for v in journal.pending() if v["entity_type"] == "list_order"]) == 1


def test_workspace_reorder_only_changes_allowlisted_setting(tmp_path):
    path = tmp_path / "research.db"
    journal = seeded(path)
    before, old_positions = content(path), positions(path)
    save(journal, ordered_operation([item("other"), item(LIST)], workspace=True))
    assert content(path) == before and positions(path) == old_positions
    with sqlite3.connect(path) as conn:
        assert json.loads(
            conn.execute("SELECT value FROM kv WHERE key='lists.order'").fetchone()[0]
        ) == ["other", LIST]


@pytest.mark.parametrize("problem", ["missing", "duplicate", "unknown", "stale", "digest"])
def test_invalid_local_order_rolls_back_without_outbox_receipt(tmp_path, problem):
    path = tmp_path / "research.db"
    journal = seeded(path)
    items = [item(SECOND_MEMBER), item(MEMBER)]
    if problem == "missing":
        items.pop()
    elif problem == "duplicate":
        items[1] = dict(items[0])
    elif problem == "unknown":
        items[1]["id"] = str(uuid5(NAMESPACE_URL, "unknown-member"))
    elif problem == "stale":
        items[1]["incarnation"] = "stale"
    if problem == "duplicate":
        value = ordered_operation([item(SECOND_MEMBER), item(MEMBER)])
        value["payload"]["items"] = items
    else:
        value = ordered_operation(items)
    if problem == "digest":
        value["payload"]["observed_set"] = "0" * 64
    before = positions(path)
    with pytest.raises(ValueError):
        save(journal, value)
    assert positions(path) == before
    assert all(v["entity_type"] != "list_order" for v in journal.pending())


@pytest.mark.parametrize("workspace", [False, True])
def test_reset_uses_dedicated_default_projection_without_deleting_research(tmp_path, workspace):
    path = tmp_path / "research.db"
    journal = seeded(path)
    before = content(path)
    custom = [item("other"), item(LIST)] if workspace else [item(SECOND_MEMBER), item(MEMBER)]
    save(journal, ordered_operation(custom, workspace=workspace))
    save(journal, ordered_operation([], workspace=workspace, action="delete", op_id="reset"))
    default = [item(LIST), item("other")] if workspace else [item(MEMBER), item(SECOND_MEMBER)]
    with journal.transaction() as conn:
        research_order_writer(conn, scope(workspace), default)
    assert content(path) == before
    if workspace:
        with sqlite3.connect(path) as conn:
            assert json.loads(
                conn.execute("SELECT value FROM kv WHERE key='lists.order'").fetchone()[0]
            ) == [LIST, "other"]
    else:
        assert positions(path) == [("sync:" + PAPER, 0), ("sync:" + SECOND, 1)]


@pytest.mark.parametrize("problem", ["root", "workspace", "missing_marker", "extra_legacy"])
def test_callback_rejects_wrong_scope_or_incomplete_local_enrollment(tmp_path, problem):
    path = tmp_path / "research.db"
    journal = seeded(path)
    target = scope()
    with sqlite3.connect(path) as conn:
        if problem == "missing_marker":
            conn.execute("DELETE FROM research_membership_projection WHERE sync_id=?", (MEMBER,))
        elif problem == "extra_legacy":
            conn.execute(
                "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                "VALUES(?,'legacy',9,?)",
                (LIST, STAMP),
            )
    if problem == "root":
        target["incarnation"] = "old-root"
    elif problem == "workspace":
        target["workspace_id"] = "wrong-workspace"
    before = positions(path)
    with pytest.raises(ValueError), journal.transaction() as conn:
        research_order_writer(conn, target, [item(SECOND_MEMBER), item(MEMBER)])
    assert positions(path) == before


def test_workspace_callback_never_hides_unenrolled_list(tmp_path):
    path = tmp_path / "research.db"
    journal = seeded(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO lists VALUES('legacy','Legacy','','old')")
    with pytest.raises(ValueError, match="all current lists"), journal.transaction() as conn:
        research_order_writer(conn, scope(True), [item(LIST), item("other")])
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT value FROM kv WHERE key='lists.order'").fetchone() is None
        assert conn.execute("SELECT name FROM lists WHERE id='legacy'").fetchone()[0] == "Legacy"


def test_callback_requires_transaction_and_rolls_back_with_owner(tmp_path):
    path = tmp_path / "research.db"
    journal = seeded(path)
    before = positions(path)
    with sqlite3.connect(path) as conn, pytest.raises(ValueError, match="transaction"):
        research_order_writer(conn, scope(), [item(SECOND_MEMBER), item(MEMBER)])
    with pytest.raises(RuntimeError), journal.transaction() as conn:
        research_order_writer(conn, scope(), [item(SECOND_MEMBER), item(MEMBER)])
        raise RuntimeError("cancelled transaction")
    assert positions(path) == before


def test_prepare_does_not_enroll_legacy_list_markers_or_change_content(tmp_path):
    path = tmp_path / "research.db"
    journal = seeded(path)
    before = content(path)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE research_list_projection")
    prepare(path, workspace_id="workspace", device_id="device")
    prepare(path, workspace_id="workspace", device_id="device")
    assert content(path) == before
    with pytest.raises(ValueError, match="all current lists"), journal.transaction() as conn:
        research_order_writer(conn, scope(True), [item(LIST), item("other")])


@pytest.mark.parametrize("workspace", [False, True])
def test_repeated_projection_has_no_sqlite_changes(tmp_path, workspace):
    path = tmp_path / "research.db"
    journal = seeded(path)
    items = [item(LIST), item("other")] if workspace else [item(SECOND_MEMBER), item(MEMBER)]
    with journal.transaction() as conn:
        research_order_writer(conn, scope(workspace), items)
    if workspace:
        with sqlite3.connect(path) as conn:
            conn.execute(
                "UPDATE kv SET value=? WHERE key='lists.order'",
                (json.dumps([LIST, "other"], indent=2),),
            )
    before = path.read_bytes()
    with journal.transaction() as conn:
        changes = conn.total_changes
        research_order_writer(conn, scope(workspace), items)
        assert conn.total_changes == changes
    assert path.read_bytes() == before
