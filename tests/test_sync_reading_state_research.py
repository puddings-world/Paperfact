"""Reading progress is scoped to an enrolled membership incarnation."""

import sqlite3
from uuid import NAMESPACE_URL, uuid5

import pytest

from paper_daily.store import SCHEMA
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_writer
from paper_daily.sync_schema_v2 import membership_id

PAPER = str(uuid5(NAMESPACE_URL, "reading-state:paper"))
LIST = "reading"
MEMBER = membership_id(LIST, PAPER)
STAMP = "2026-01-01T00:00:00+00:00"
LATER = "2026-01-02T00:00:00+00:00"


def operation(kind, identity, payload, *, op_id=None, parents=None, action="put", incarnation="a"):
    return {
        "version": 2,
        "operation_id": op_id or f"{kind}-{identity}",
        "workspace_id": "workspace",
        "device_id": "device",
        "entity_type": kind,
        "entity_id": identity,
        "action": action,
        "payload": payload,
        "base_revision": 0,
        "depends_on": None,
        "incarnation": incarnation,
        "parents": parents or [],
        "structure_revision": 0,
    }


def ref(kind, identity, incarnation="a"):
    return {"kind": kind, "id": identity, "incarnation": incarnation}


def paper_payload():
    return {
        "title": "Research",
        "authors": [],
        "year": 2026,
        **{
            key: None
            for key in (
                "venue",
                "abstract",
                "doi",
                "arxiv_id",
                "s2_id",
                "page_url",
                "pdf_url",
                "source",
            )
        },
    }


def membership(list_id=LIST, *, incarnation="a", op_id=None, action="put"):
    return operation(
        "membership",
        membership_id(list_id, PAPER),
        {"list_id": list_id, "paper_id": PAPER, "citation": "Context", "added_at": STAMP}
        if action == "put"
        else {},
        op_id=op_id,
        incarnation=incarnation,
        action=action,
        parents=[ref("list", list_id), ref("paper", PAPER)],
    )


def reading(state="read", *, op_id="reading", action="put", member_incarnation="a"):
    return operation(
        "reading_state",
        MEMBER,
        {
            "list_id": LIST,
            "paper_id": PAPER,
            "state": state,
            "delivered_at": STAMP,
            "read_at": LATER if state == "read" else None,
        }
        if action == "put"
        else {},
        op_id=op_id,
        action=action,
        parents=[
            ref("membership", MEMBER, member_incarnation),
            ref("list", LIST),
            ref("paper", PAPER),
        ],
    )


def save(journal, value, writer=research_writer):
    pending = journal.pending()
    if not any(item["operation_id"] == value["operation_id"] for item in pending):
        for item in reversed(pending):
            if (item["entity_type"], item["entity_id"]) == (
                value["entity_type"],
                value["entity_id"],
            ):
                value = dict(value, depends_on=item["operation_id"])
                break
    else:
        value = next(item for item in pending if item["operation_id"] == value["operation_id"])
    return journal.apply(value, writer)


def database(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
    prepare(path, workspace_id="workspace", device_id="device")
    journal = Journal(path, workspace_id="workspace", device_id="device")
    save(journal, operation("paper", PAPER, paper_payload()), research_writer)
    for list_id in (LIST, "other"):
        save(journal, operation("list", list_id, {"name": list_id, "note": ""}), research_writer)
        save(journal, membership(list_id), research_writer)
    return journal


def stored(path):
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT list_id,state,delivered_at,read_at,position,citation,added_at "
            "FROM list_papers ORDER BY list_id"
        ).fetchall()


@pytest.mark.parametrize("state", ["pending", "delivered", "read", "skipped", "deferred"])
def test_state_only_changes_one_membership_and_survives_retry_citation_reopen(tmp_path, state):
    path = tmp_path / "research.db"
    journal = database(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO queue(paper_id,rank,state,read_at) VALUES(?,1,'read',?)",
            ("sync:" + PAPER, STAMP),
        )
    before = stored(path)
    change = reading(state)
    save(journal, change, research_writer)
    save(journal, change, research_writer)
    citation = membership(op_id="citation-edit")
    citation["payload"]["citation"] = "Updated citation"
    save(journal, citation, research_writer)
    prepare(path, workspace_id="workspace", device_id="device")
    assert stored(path) == [
        before[0],
        (LIST, state, STAMP, LATER if state == "read" else None, 0, "Updated citation", STAMP),
    ]
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT state,read_at FROM queue").fetchall() == [("read", STAMP)]
    assert len([op for op in journal.pending() if op["entity_type"] == "reading_state"]) == 1


def test_delete_resets_current_state_and_removed_membership_is_not_recreated(tmp_path):
    path = tmp_path / "research.db"
    journal = database(path)
    save(journal, reading(), research_writer)
    save(journal, reading(action="delete", op_id="reset"), research_writer)
    assert stored(path)[1][1:4] == ("pending", None, None)
    save(journal, membership(action="delete", op_id="remove-member"), research_writer)
    save(journal, reading(action="delete", op_id="reset-again"), research_writer)
    assert len(stored(path)) == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM papers").fetchone()[0] == 1


def test_archived_retirement_cannot_reset_restored_membership(tmp_path):
    path = tmp_path / "research.db"
    journal = database(path)
    save(journal, reading(), research_writer)
    save(journal, membership(action="delete", op_id="remove-member"), research_writer)
    save(journal, membership(incarnation="restored", op_id="restore-member"), research_writer)
    save(
        journal,
        reading("deferred", op_id="new-state", member_incarnation="restored"),
        research_writer,
    )
    before = stored(path)
    save(journal, reading(action="delete", op_id="retire-old"), research_writer)
    assert stored(path) == before
    with pytest.raises(ValueError, match="current projected membership"):
        save(journal, reading(op_id="old-put"), research_writer)
    assert stored(path) == before


def test_legacy_unmapped_reset_is_noop_and_put_rolls_back(tmp_path):
    path = tmp_path / "research.db"
    journal = database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM research_membership_projection")
        conn.execute("UPDATE list_papers SET state='skipped'")
    before = stored(path)
    save(journal, reading(action="delete", op_id="legacy-reset"), research_writer)
    with pytest.raises(ValueError, match="current projected membership"):
        save(journal, reading(), research_writer)
    assert stored(path) == before
    assert all(op["operation_id"] != "reading" for op in journal.pending())


@pytest.mark.parametrize("column", ["list_incarnation", "paper_incarnation"])
def test_old_root_incarnation_reset_preserves_current_progress(tmp_path, column):
    path = tmp_path / "research.db"
    journal = database(path)
    save(journal, reading(), research_writer)
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"UPDATE research_membership_projection SET {column}='restored-root' WHERE sync_id=?",
            (MEMBER,),
        )
    before = stored(path)
    save(journal, reading(action="delete", op_id="stale-root-reset"), research_writer)
    assert stored(path) == before


def test_removed_row_put_fails_and_interrupted_write_rolls_back(tmp_path):
    path = tmp_path / "research.db"
    journal = database(path)
    before = stored(path)

    def interrupted(conn, value):
        research_writer(conn, value)
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        save(journal, reading(), interrupted)
    assert stored(path) == before
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM list_papers WHERE list_id=?", (LIST,))
    with pytest.raises(ValueError, match="Membership must"):
        save(journal, reading(), research_writer)
    assert len(stored(path)) == 1
    assert all(op["operation_id"] != "reading" for op in journal.pending())


def test_prepare_migrates_marker_table_without_enrolling_legacy_memberships(tmp_path):
    path = tmp_path / "research.db"
    database(path)
    before = stored(path)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE research_membership_projection")
    prepare(path, workspace_id="workspace", device_id="device")
    prepare(path, workspace_id="workspace", device_id="device")
    assert stored(path) == before
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute("SELECT count(*) FROM research_membership_projection").fetchone()[0] == 0
        )
