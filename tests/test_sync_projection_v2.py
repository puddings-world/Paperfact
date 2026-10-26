"""DTO2 preserves portable paper identity without silently upgrading DTO1 consumers."""

import json
import sqlite3
from uuid import NAMESPACE_URL, uuid5

import pytest

from paper_daily import sync_projection
from paper_daily.store import SCHEMA
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_projection import read_manifest
from paper_daily.sync_research import prepare, research_writer
from paper_daily.sync_schema_v2 import membership_id
from paper_daily.sync_service import ReferenceService

PAPER = str(uuid5(NAMESPACE_URL, "projection-v2:paper"))
NEW_PAPER = str(uuid5(NAMESPACE_URL, "projection-v2:replacement-paper"))
NOTE = str(uuid5(NAMESPACE_URL, "projection-v2:note"))
LIST = "reading"
ANCHOR = {"p0": 0, "o0": 1, "p1": 0, "o1": 3}


def database(path, local_id, device="device"):
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,venue,year,title,title_key,source) "
            "VALUES(?,'Fixture',2026,'Research','research','fixture')",
            (local_id,),
        )
        conn.execute("INSERT INTO lists VALUES('reading','Reading','Context','old')")
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,state,added_at) "
            "VALUES('reading',?,4,'read','old')",
            (local_id,),
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) VALUES(?,'Observation','old')", (local_id,)
        )
        conn.execute(
            "INSERT INTO pdf_highlights(paper_id,document_hash,anchor,quote,created_at) "
            "VALUES(?,?,?,'Quote','old')",
            (local_id, "a" * 64, json.dumps(ANCHOR)),
        )
    prepare(path, workspace_id="workspace", device_id=device)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE research_paper_identity SET sync_id=?", (PAPER,))
        conn.execute("UPDATE research_note_identity SET sync_id=?", (NOTE,))
    return path


def read(path, **kwargs):
    return read_manifest(path, workspace_id="workspace", schema_version=2, **kwargs)


def test_different_local_ids_produce_equivalent_portable_references_without_writes(tmp_path):
    a = database(tmp_path / "a.db", "private-local:desktop/paper", "a")
    b = database(tmp_path / "b.db", "private-local:phone/paper", "b")
    a_before, b_before = a.read_bytes(), b.read_bytes()
    first, second = read(a), read(b)
    assert first == second
    assert first["papers"][0]["id"] == PAPER
    assert first["lists"][0]["members"][0] == {
        "paper_id": PAPER,
        "position": 4,
        "state": "read",
        "id": membership_id(LIST, PAPER),
        "revision": None,
        "sync_state": "local",
        "graph": None,
        "reading_state": {
            "id": membership_id(LIST, PAPER),
            "state": "read",
            "delivered_at": None,
            "read_at": None,
            "revision": None,
            "sync_state": "local",
            "graph": None,
            "editable": False,
            "read_only_reason": "graph_unavailable",
        },
    }
    assert first["notes"][0]["id"] == NOTE and first["notes"][0]["paper_id"] == PAPER
    assert first["highlights"][0]["paper_id"] == PAPER
    assert first["notes"][0]["editable"] is False
    assert first["notes"][0]["read_only_reason"] == "graph_unavailable"
    assert first["capabilities"]["note_contract_version"] == 2
    assert first["capabilities"]["sync_bootstrap"] is False
    assert first["decks"] == first["assets"] == []
    assert "private-local:" not in json.dumps(first)
    assert a.read_bytes() == a_before and b.read_bytes() == b_before


def test_default_schema_1_shape_and_local_identity_remain_unchanged(tmp_path):
    path = database(tmp_path / "research.db", "local:paper")
    implicit = read_manifest(path, workspace_id="workspace")
    explicit = read_manifest(path, workspace_id="workspace", schema_version=1)
    assert implicit == explicit
    assert implicit["schema_version"] == 1
    assert implicit["papers"][0]["id"] == "local:paper"
    assert implicit["notes"][0]["editable"] is True
    assert "graph" not in implicit["notes"][0]
    assert "note_contract_version" not in implicit["capabilities"]
    assert read(path)["notes"][0]["id"] == implicit["notes"][0]["id"]


@pytest.mark.parametrize("problem", ["missing", "invalid"])
def test_portable_mapping_is_required_never_inferred_or_written(tmp_path, problem):
    path = database(tmp_path / "research.db", "local:paper")
    with sqlite3.connect(path) as conn:
        if problem == "missing":
            conn.execute("DELETE FROM research_paper_identity")
        else:
            conn.execute("UPDATE research_paper_identity SET sync_id='not-a-uuid'")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="unenrolled paper|portable paper identity"):
        read(path)
    assert path.read_bytes() == before
    # Existing DTO1 consumers do not acquire a new paper-mapping requirement.
    assert read_manifest(path, workspace_id="workspace")["papers"][0]["id"] == "local:paper"


def graph_client(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
    prepare(path, workspace_id="workspace", device_id="device")
    return SyncClient(Journal(path, workspace_id="workspace", device_id="device"), research_writer)


def graph_seed(client):
    paper = {
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
    values = [
        ("paper", PAPER, paper),
        ("list", LIST, {"name": "Reading", "note": ""}),
        (
            "membership",
            membership_id(LIST, PAPER),
            {
                "list_id": LIST,
                "paper_id": PAPER,
                "citation": None,
                "added_at": "2026-01-01T00:00:00+00:00",
            },
        ),
        ("note", NOTE, {"paper_id": PAPER, "body": "Original"}),
    ]
    for kind, identity, payload in values:
        client.save(client.new_graph_operation(kind, identity, payload))


def test_graph_metadata_and_editability_require_received_applied_parent_state(tmp_path):
    path = tmp_path / "research.db"
    client = graph_client(path)
    service = ReferenceService(tmp_path / "service.db")
    token = service.enroll("workspace", "device")
    graph_seed(client)
    pending = read(path)
    assert pending["notes"][0]["body"] == "Original"
    assert pending["notes"][0]["graph"] is None and not pending["notes"][0]["editable"]
    client.sync_once(service, token)
    complete = read(path)
    note, paper = complete["notes"][0], complete["papers"][0]
    assert complete["cursor"] == 4
    assert paper["graph"]["structure_revision"] == 4  # Updated by its child, not old put payload.
    assert complete["lists"][0]["graph"]["structure_revision"] == 3
    assert note["graph"]["parents"] == [
        {"kind": "paper", "id": PAPER, "incarnation": paper["graph"]["incarnation"]}
    ]
    assert note["editable"] is True and note["read_only_reason"] is None
    change = client.new_graph_operation("note", NOTE, {"paper_id": PAPER, "body": "Pending edit"})
    client.save(change)
    assert read(path)["notes"][0]["sync_state"] == "pending"
    event = service.push(token, change)
    client.journal.acknowledge(change["operation_id"], event["sequence"])
    awaiting = read(path)
    assert awaiting["notes"][0]["body"] == "Pending edit"
    assert awaiting["notes"][0]["sync_state"] == "awaiting"
    assert awaiting["notes"][0]["graph"] is None and not awaiting["notes"][0]["editable"]
    client.receive(service.pull(token, after=client.status()["cursor"]))
    assert read(path)["notes"][0]["editable"] is True
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE paperfact_sync_heads SET applied_revision=-1 WHERE entity_type='paper'"
        )
    deferred = read(path)
    assert deferred["papers"][0]["revision"] is None and deferred["papers"][0]["graph"] is None
    assert deferred["notes"][0]["read_only_reason"] == "paper_graph_unavailable"
    assert deferred["notes"][0]["editable"] is False


def test_identity_mapping_and_cursor_share_one_snapshot_during_concurrent_commit(
    tmp_path, monkeypatch
):
    path = database(tmp_path / "research.db", "local:paper")
    SyncClient(Journal(path, workspace_id="workspace", device_id="device"), research_writer)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("UPDATE paperfact_sync_cursor SET sequence=1")
    original_connect, changed = sqlite3.connect, False

    def connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)

        def trace(statement):
            nonlocal changed
            if not changed and "SELECT p.id,m.sync_id" in statement:
                changed = True
                with original_connect(path) as writer:
                    writer.execute("UPDATE research_paper_identity SET sync_id=?", (NEW_PAPER,))
                    writer.execute("UPDATE paperfact_sync_cursor SET sequence=2")

        conn.set_trace_callback(trace)
        return conn

    monkeypatch.setattr(sync_projection.sqlite3, "connect", connect)
    first = read(path)
    assert changed and first["cursor"] == 1 and first["papers"][0]["id"] == PAPER
    second = read(path)
    assert second["cursor"] == 2 and second["papers"][0]["id"] == NEW_PAPER
    assert second["notes"][0]["paper_id"] == NEW_PAPER


@pytest.mark.parametrize("version", [0, 3, True, "2", None])
def test_projection_schema_version_is_explicit_and_closed(tmp_path, version):
    with pytest.raises(ValueError, match="version"):
        read_manifest(tmp_path / "not-created.db", workspace_id="workspace", schema_version=version)
    assert not (tmp_path / "not-created.db").exists()
