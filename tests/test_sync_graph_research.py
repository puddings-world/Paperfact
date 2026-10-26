"""Version-2 graph operations preserve the existing production research schema."""

import json
import sqlite3
from uuid import NAMESPACE_URL, uuid5

import pytest

from paper_daily.store import SCHEMA
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import paper_identity, prepare, research_writer
from paper_daily.sync_schema_v2 import membership_id

PAPER = str(uuid5(NAMESPACE_URL, "fixture:portable-paper"))
OTHER_PAPER = str(uuid5(NAMESPACE_URL, "fixture:other-portable-paper"))
LIST = str(uuid5(NAMESPACE_URL, "fixture:portable-list"))
OTHER_LIST = str(uuid5(NAMESPACE_URL, "fixture:other-portable-list"))
NOTE = str(uuid5(NAMESPACE_URL, "fixture:portable-note"))
STAMP = "2026-01-01T00:00:00+00:00"


def metadata(title="Research paper"):
    return {
        "title": title,
        "authors": ["Ada", "Lin"],
        "year": 2026,
        "venue": "Fixture",
        "abstract": "Research abstract",
        "doi": "10.1234/fixture",
        "arxiv_id": None,
        "s2_id": None,
        "page_url": "https://example.org/paper",
        "pdf_url": "https://example.org/paper.pdf",
        "source": "fixture",
    }


def operation(kind, identity, payload, *, op_id=None, action="put", parents=None, predecessor=None):
    return {
        "version": 2,
        "operation_id": op_id or f"{kind}-{action}-{identity}",
        "workspace_id": "workspace",
        "device_id": "device",
        "entity_type": kind,
        "entity_id": identity,
        "action": action,
        "base_revision": 0,
        "depends_on": predecessor,
        "payload": payload,
        "incarnation": "incarnation-a",
        "parents": parents or [],
        "structure_revision": 0,
    }


def parent(kind, identity):
    return {"kind": kind, "id": identity, "incarnation": "incarnation-a"}


def membership(list_id=LIST, paper_id=PAPER, **kwargs):
    action = kwargs.get("action", "put")
    payload = {
        "list_id": list_id,
        "paper_id": paper_id,
        "citation": "Background",
        "added_at": STAMP,
    }
    return operation(
        "membership",
        membership_id(list_id, paper_id),
        {} if action == "delete" else payload,
        parents=[parent("list", list_id), parent("paper", paper_id)],
        **kwargs,
    )


def note(paper_id=PAPER, **kwargs):
    payload = (
        {} if kwargs.get("action") == "delete" else {"paper_id": paper_id, "body": "Observation"}
    )
    return operation("note", NOTE, payload, parents=[parent("paper", paper_id)], **kwargs)


@pytest.fixture
def path(tmp_path):
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
    return path


def journal(path):
    prepare(path, workspace_id="workspace", device_id="device")
    return Journal(path, workspace_id="workspace", device_id="device")


def rows(path, sql, args=()):
    with sqlite3.connect(path) as conn:
        return conn.execute(sql, args).fetchall()


def create_graph(journal):
    journal.apply(operation("paper", PAPER, metadata()), research_writer)
    journal.apply(operation("list", LIST, {"name": "Reading", "note": "Context"}), research_writer)
    journal.apply(membership(), research_writer)
    journal.apply(note(), research_writer)


def test_empty_receiver_accepts_paper_list_membership_and_note_once(path):
    sink = journal(path)
    create_graph(sink)
    assert rows(path, "SELECT id,title,year FROM papers") == [
        ("sync:" + PAPER, "Research paper", 2026)
    ]
    assert rows(path, "SELECT list_id,paper_id,position,state,citation FROM list_papers") == [
        (LIST, "sync:" + PAPER, 0, "pending", "Background")
    ]
    assert rows(path, "SELECT paper_id,body FROM notes") == [("sync:" + PAPER, "Observation")]
    mapping = rows(path, "SELECT * FROM research_paper_identity")
    note_mapping = rows(path, "SELECT * FROM research_note_identity")
    sink = journal(path)
    create_graph(sink)
    assert rows(path, "SELECT * FROM research_paper_identity") == mapping
    assert rows(path, "SELECT * FROM research_note_identity") == note_mapping
    assert len(sink.pending()) == 4


def test_enrollment_and_metadata_update_preserve_local_id_ranking_and_notes(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO papers(id,venue,year,title,title_key,source,score,crawled_at,"
            "score_parts_json,abstract,pdf_url) VALUES('legacy:paper','Old',2020,'Original',"
            "'original','legacy',19.5,'previous crawl','{\"rank\":1}','Previous abstract',"
            "'https://example.org/old.pdf')"
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at,kind,page,anchor) "
            "VALUES('legacy:paper','Preserved source note','old','note',1,'{\"p0\":0}')"
        )
    before = rows(path, "SELECT * FROM papers")
    notes = rows(path, "SELECT * FROM notes")
    sink = journal(path)
    with sqlite3.connect(path) as conn:
        portable = paper_identity(conn, "legacy:paper")
    assert rows(path, "SELECT * FROM papers") == before
    assert rows(path, "SELECT * FROM notes") == notes
    sink = journal(path)
    with sqlite3.connect(path) as conn:
        assert paper_identity(conn, "legacy:paper") == portable
    payload = metadata("New curated title")
    payload.update(year=None, venue=None, source=None)
    sink.apply(operation("paper", portable, payload), research_writer)
    assert rows(
        path, "SELECT id,title,title_key,year,venue,score,crawled_at,score_parts_json FROM papers"
    ) == [
        (
            "legacy:paper",
            "New curated title",
            "newcuratedtitle",
            0,
            "",
            19.5,
            "previous crawl",
            '{"rank":1}',
        )
    ]
    assert json.loads(rows(path, "SELECT authors_json FROM papers")[0][0]) == ["Ada", "Lin"]
    assert rows(path, "SELECT source FROM papers") == [("sync",)]
    assert rows(path, "SELECT * FROM notes") == notes


def test_new_paper_does_not_silently_merge_title_or_doi_matches(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO papers(id,venue,year,title,title_key,source,doi) "
            "VALUES('legacy','Fixture',2026,'Research paper','researchpaper','fixture',"
            "'10.1234/fixture')"
        )
    sink = journal(path)
    sink.apply(operation("paper", PAPER, metadata()), research_writer)
    assert rows(path, "SELECT id FROM papers ORDER BY id") == [("legacy",), ("sync:" + PAPER,)]
    assert len(rows(path, "SELECT * FROM research_paper_identity")) == 2


def test_incoming_local_id_collision_fails_without_overwriting(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO papers(id,venue,year,title,title_key,source) "
            "VALUES(?,'Fixture',2020,'Keep existing','keepexisting','fixture')",
            ("sync:" + PAPER,),
        )
    sink = journal(path)
    before = rows(path, "SELECT * FROM papers")
    mappings = rows(path, "SELECT * FROM research_paper_identity")
    with pytest.raises(ValueError, match="collides"):
        sink.apply(operation("paper", PAPER, metadata()), research_writer)
    assert rows(path, "SELECT * FROM papers") == before
    assert rows(path, "SELECT * FROM research_paper_identity") == mappings
    assert sink.pending() == []


def test_membership_updates_only_citation_and_removes_only_one_membership(path):
    sink = journal(path)
    create_graph(sink)
    sink.apply(operation("list", OTHER_LIST, {"name": "Other", "note": ""}), research_writer)
    sink.apply(membership(OTHER_LIST), research_writer)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE list_papers SET position=42,state='read',read_at='read timestamp' "
            "WHERE list_id=?",
            (LIST,),
        )
    original = membership()
    updated = membership(op_id="membership-edit", predecessor=original["operation_id"])
    updated["payload"].update(citation="Revised role", added_at="2026-02-01T00:00:00+00:00")
    sink.apply(updated, research_writer)
    assert rows(
        path,
        "SELECT position,state,read_at,added_at,citation FROM list_papers WHERE list_id=?",
        (LIST,),
    ) == [(42, "read", "read timestamp", STAMP, "Revised role")]
    sink.apply(
        membership(op_id="membership-remove", predecessor="membership-edit", action="delete"),
        research_writer,
    )
    assert rows(path, "SELECT list_id,paper_id FROM list_papers") == [(OTHER_LIST, "sync:" + PAPER)]
    assert rows(path, "SELECT body FROM notes") == [("Observation",)]
    assert len(rows(path, "SELECT * FROM papers")) == 1


def test_membership_append_uses_existing_max_position(path):
    sink = journal(path)
    create_graph(sink)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE list_papers SET position=12 WHERE list_id=?", (LIST,))
    sink.apply(operation("paper", OTHER_PAPER, metadata("Another paper")), research_writer)
    sink.apply(membership(LIST, OTHER_PAPER), research_writer)
    assert rows(path, "SELECT position FROM list_papers ORDER BY position") == [(12,), (13,)]


@pytest.mark.parametrize("missing", ["paper", "list"])
def test_missing_membership_parent_rolls_back(path, missing):
    sink = journal(path)
    if missing != "paper":
        sink.apply(operation("paper", PAPER, metadata()), research_writer)
    if missing != "list":
        sink.apply(operation("list", LIST, {"name": "Reading", "note": ""}), research_writer)
    pending = sink.pending()
    with pytest.raises(ValueError, match="synchronized"):
        sink.apply(membership(), research_writer)
    assert rows(path, "SELECT * FROM list_papers") == []
    assert sink.pending() == pending


def test_note_requires_mapped_paper_and_cannot_reassign_its_parent(path):
    sink = journal(path)
    with pytest.raises(ValueError, match="metadata"):
        sink.apply(note(), research_writer)
    assert sink.pending() == []
    sink.apply(operation("paper", PAPER, metadata()), research_writer)
    first = note()
    sink.apply(first, research_writer)
    local_id = rows(path, "SELECT id FROM notes")[0][0]
    sink.apply(operation("paper", OTHER_PAPER, metadata("Other")), research_writer)
    changed = note(OTHER_PAPER, op_id="reassign", predecessor=first["operation_id"])
    with pytest.raises(ValueError, match="reassigned"):
        sink.apply(changed, research_writer)
    updated = note(op_id="note-edit", predecessor=first["operation_id"])
    updated["payload"]["body"] = "Updated"
    sink.apply(updated, research_writer)
    assert rows(path, "SELECT id,paper_id,body FROM notes") == [
        (local_id, "sync:" + PAPER, "Updated")
    ]
    sink.apply(note(op_id="note-remove", predecessor="note-edit", action="delete"), research_writer)
    assert rows(path, "SELECT * FROM notes") == []
    assert rows(path, "SELECT sync_id,local_id FROM research_note_identity") == [(NOTE, None)]


def test_list_deletion_preserves_papers_notes_and_identity_history(path):
    sink = journal(path)
    create_graph(sink)
    first = operation("list", LIST, {"name": "Reading", "note": "Context"})
    sink.apply(
        operation(
            "list",
            LIST,
            {},
            op_id="remove-list",
            action="delete",
            predecessor=first["operation_id"],
        ),
        research_writer,
    )
    assert rows(path, "SELECT * FROM lists") == []
    assert rows(path, "SELECT * FROM list_papers") == []
    assert rows(path, "SELECT id FROM papers") == [("sync:" + PAPER,)]
    assert rows(path, "SELECT body FROM notes") == [("Observation",)]
    assert rows(path, "SELECT sync_id FROM research_paper_identity") == [(PAPER,)]
    assert len(sink.pending()) == 5


def test_paper_mapping_and_metadata_rollback_if_receipt_storage_fails(path):
    sink = journal(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_receipt BEFORE INSERT ON paperfact_sync_operations "
            "BEGIN SELECT RAISE(ABORT,'fixture storage failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="storage failure"):
        sink.apply(operation("paper", PAPER, metadata()), research_writer)
    assert rows(path, "SELECT * FROM papers") == []
    assert rows(path, "SELECT * FROM research_paper_identity") == []
    assert sink.pending() == []
