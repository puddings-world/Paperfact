"""The same intake action can be used by UI, CLI and MCP without invoking models."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from paper_daily import sync_operations
from paper_daily.store import SCHEMA
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_operations import ResearchOperations
from paper_daily.sync_research import prepare, research_writer
from paper_daily.sync_service import ReferenceService


def paper(title="Research paper"):
    return {
        "title": title,
        "authors": ["Fixture Author"],
        "year": 2026,
        **dict.fromkeys(
            ("venue", "abstract", "doi", "arxiv_id", "s2_id", "page_url", "pdf_url", "source")
        ),
    }


def client(path, device):
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
    prepare(path, workspace_id="workspace", device_id=device)
    return SyncClient(Journal(path, workspace_id="workspace", device_id=device), research_writer)


@pytest.fixture
def pair(tmp_path):
    a = client(tmp_path / "a.sqlite", "a")
    b = client(tmp_path / "b.sqlite", "b")
    return a, b


def query(client, sql, args=()):
    with sqlite3.connect(client.journal.path) as conn:
        return conn.execute(sql, args).fetchall()


def content(client):
    return {
        "lists": query(client, "SELECT id,name,note FROM lists ORDER BY id"),
        "papers": query(
            client,
            "SELECT m.sync_id,p.title,p.authors_json FROM papers p "
            "JOIN research_paper_identity m ON m.local_id=p.id ORDER BY m.sync_id",
        ),
        "members": query(
            client,
            "SELECT l.list_id,m.sync_id,l.citation,l.position,l.state,l.added_at "
            "FROM list_papers l JOIN research_paper_identity m "
            "ON m.local_id=l.paper_id ORDER BY l.list_id,l.position",
        ),
        "notes": query(
            client,
            "SELECT m.sync_id,n.body FROM notes n JOIN research_note_identity m "
            "ON m.local_id=n.id ORDER BY m.sync_id",
        ),
    }


def sync_all(a, b, tmp_path):
    service = ReferenceService(tmp_path / "server.sqlite")
    ta, tb = service.enroll("workspace", "a"), service.enroll("workspace", "b")
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    return service, ta, tb


def test_atomic_list_intake_reaches_empty_peer_with_papers_memberships_and_notes(
    pair, tmp_path, monkeypatch,
):
    # Deliberately differs from the receiving machine's wall clock.
    created = datetime(2026, 1, 2, tzinfo=UTC)
    monkeypatch.setattr(sync_operations, "datetime", SimpleNamespace(now=lambda _tz: created))
    a, b = pair
    operations = ResearchOperations(a)
    result = operations.create_list(
        "Research route",
        [
            {
                "paper": paper("Foundations"),
                "citation": "Start here",
                "notes": ["Important result"],
            },
            {"paper": paper("Follow-up"), "notes": ["Compare assumptions", "Inspect experiment"]},
        ],
        request_id="intake-one",
        note="A synthetic route",
    )
    assert len(result["operation_ids"]) == 8
    assert len(a.journal.pending()) == 8
    sync_all(a, b, tmp_path)
    assert content(a) == content(b)
    assert len(content(b)["papers"]) == 2
    assert len(content(b)["members"]) == 2
    assert len(content(b)["notes"]) == 3
    for side in (a, b):
        assert query(side, "SELECT kind,page,anchor,created_at FROM notes ORDER BY id") == [
            ("note", None, None, created.isoformat(timespec="seconds"))
        ] * 3
    assert a.status()["pending"] == b.status()["deferred"] == 0


def test_exact_intake_retry_after_transfer_does_not_revert_edits_or_add_records(pair, tmp_path):
    a, b = pair
    operations = ResearchOperations(a)
    entries = [{"paper": paper(), "notes": ["Original note"]}]
    first = operations.create_list("Original list", entries, request_id="intake-one")
    service, ta, tb = sync_all(a, b, tmp_path)
    timestamps = query(a, "SELECT created_at FROM notes ORDER BY id")
    a.save(a.new_graph_operation(
        "note", first["papers"][0]["note_ids"][0],
        dict(paper_id=first["papers"][0]["paper_id"], body="Later note interpretation"),
    ))
    a.save(a.new_graph_operation("list", first["list_id"], {"name": "Renamed", "note": ""}))
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    restarted = ResearchOperations(client(a.journal.path, "a"))
    assert restarted.create_list("Original list", entries, request_id="intake-one") == first
    assert content(a) == content(b)
    assert content(a)["lists"][0][1] == "Renamed"
    assert content(a)["notes"][0][1] == "Later note interpretation"
    assert query(a, "SELECT created_at FROM notes ORDER BY id") == timestamps
    assert query(b, "SELECT created_at FROM notes ORDER BY id") == timestamps
    assert a.journal.pending() == []
    with pytest.raises(ValueError, match="retry changed"):
        restarted.create_list("Changed retry", entries, request_id="intake-one")
    assert len(content(a)["lists"]) == 1


def test_concurrent_intake_retry_has_one_logical_result(pair):
    a, _ = pair
    ResearchOperations(a)

    def submit(_):
        local = client(a.journal.path, "a")
        return ResearchOperations(local).create_list(
            "Reading", [{"paper": paper()}], request_id="same-request"
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(12)))
    assert all(result == results[0] for result in results)
    assert len(content(a)["lists"]) == len(content(a)["papers"]) == len(content(a)["members"]) == 1
    assert len(a.journal.pending()) == 3


def test_add_to_list_reuses_explicit_paper_and_preserves_read_state(pair, monkeypatch):
    a, _ = pair
    operations = ResearchOperations(a)
    first = operations.create_list("First", [{"paper": paper()}], request_id="first")
    second = operations.create_list("Second", [], request_id="second")
    paper_id = first["papers"][0]["paper_id"]
    local_id = query(
        a, "SELECT local_id FROM research_paper_identity WHERE sync_id=?", (paper_id,)
    )[0][0]
    with sqlite3.connect(a.journal.path) as conn:
        conn.execute("UPDATE list_papers SET state='read' WHERE list_id=?", (first["list_id"],))
    created = datetime(2026, 1, 3, tzinfo=UTC)
    monkeypatch.setattr(sync_operations, "datetime", SimpleNamespace(now=lambda _tz: created))
    operations.add_papers(
        second["list_id"], [{"paper_id": paper_id, "notes": ["Reuse context"]}], request_id="reuse"
    )
    assert query(a, "SELECT body,created_at FROM notes") == [
        ("Reuse context", created.isoformat(timespec="seconds"))
    ]
    operations.add_papers(
        first["list_id"],
        [{"paper_id": paper_id, "citation": "Updated reason"}],
        request_id="reason",
    )
    assert len(content(a)["papers"]) == 1
    assert len(content(a)["members"]) == 2
    assert query(
        a,
        "SELECT state,citation FROM list_papers WHERE list_id=? AND paper_id=?",
        (first["list_id"], local_id),
    ) == [("read", "Updated reason")]


def test_compound_writer_failure_rolls_back_every_research_and_identity_row(pair):
    a, _ = pair
    operations = ResearchOperations(a)

    def fail(conn, value):
        research_writer(conn, value)
        if value["entity_type"] == "note":
            raise RuntimeError("Interrupted after note write")

    a.writer = fail
    with pytest.raises(RuntimeError):
        operations.create_list(
            "Reading", [{"paper": paper(), "notes": ["Observation"]}], request_id="interrupted"
        )
    assert all(not rows for rows in content(a).values())
    assert a.journal.pending() == []
    assert query(a, "SELECT * FROM research_action_receipts") == []
    assert query(a, "SELECT * FROM research_note_identity") == []
    assert query(a, "SELECT * FROM research_rich_note_projection") == []
    assert query(a, "SELECT * FROM research_paper_identity") == []
    a.writer = research_writer
    operations.create_list(
        "Reading", [{"paper": paper(), "notes": ["Observation"]}], request_id="interrupted"
    )
    assert len(content(a)["notes"]) == 1


def test_action_receipt_failure_rolls_back_all_outbox_and_research(pair):
    a, _ = pair
    operations = ResearchOperations(a)
    with sqlite3.connect(a.journal.path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_action BEFORE INSERT ON research_action_receipts "
            "BEGIN SELECT RAISE(ABORT,'receipt failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="receipt failure"):
        operations.create_list("Reading", [{"paper": paper()}], request_id="action")
    assert all(not rows for rows in content(a).values())
    assert a.journal.pending() == []


@pytest.mark.parametrize(
    "entries",
    [
        [{"paper": {"title": "incomplete"}}],
        [{"paper_id": "not-a-uuid"}],
        [{"paper": paper(), "credential": "forbidden"}],
        [{"paper": paper(), "notes": [None]}],
        [{"paper": paper(), "notes": ["x" * (201 * 1024)]}],
        [{"paper": paper()}] * 201,
    ],
)
def test_invalid_intake_has_no_side_effects(pair, entries):
    a, _ = pair
    operations = ResearchOperations(a)
    with pytest.raises(ValueError):
        operations.create_list("Reading", entries, request_id="invalid")
    assert all(not rows for rows in content(a).values())
    assert a.journal.pending() == []


def test_invalid_later_entry_does_not_leave_an_earlier_paper(pair):
    a, _ = pair
    bad = copy.deepcopy(paper())
    bad["title"] = ""
    with pytest.raises(ValueError):
        ResearchOperations(a).create_list(
            "Reading", [{"paper": paper()}, {"paper": bad}], request_id="invalid-second"
        )
    assert all(not rows for rows in content(a).values())


def test_same_name_is_allowed_for_distinct_lists_and_empty_list_syncs(pair, tmp_path):
    a, b = pair
    operations = ResearchOperations(a)
    one = operations.create_list("Reading", [], request_id="first")
    two = operations.create_list("Reading", [], request_id="second")
    assert one["list_id"] != two["list_id"]
    sync_all(a, b, tmp_path)
    assert content(a) == content(b)
    assert len(content(b)["lists"]) == 2


def test_deleted_list_addition_fails_without_new_paper_or_receipt(pair):
    a, _ = pair
    operations = ResearchOperations(a)
    result = operations.create_list("Reading", [], request_id="first")
    a.save(a.new_graph_operation("list", result["list_id"], {}, action="delete"))
    before = json.dumps(content(a), sort_keys=True)
    pending = a.journal.pending()
    with pytest.raises(ValueError, match="active"):
        operations.add_papers(result["list_id"], [{"paper": paper()}], request_id="late-add")
    assert json.dumps(content(a), sort_keys=True) == before
    assert a.journal.pending() == pending


def test_graph_intake_and_late_parent_rename_reach_empty_peer_over_paged_http(pair, tmp_path):
    import threading

    from paper_daily.sync_http import HttpTransport, make_server

    a, b = pair
    service = ReferenceService(tmp_path / "http-server.sqlite")
    ta, tb = service.enroll("workspace", "a"), service.enroll("workspace", "b")
    result = ResearchOperations(a).create_list(
        "Original",
        [
            {"paper": paper("First"), "notes": ["First note"]},
            {"paper": paper("Second"), "notes": ["Second note"]},
        ],
        request_id="http-intake",
    )
    a.save(a.new_graph_operation("list", result["list_id"], {"name": "Final name", "note": ""}))
    server = make_server(service)
    worker = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    worker.start()
    try:
        with HttpTransport(f"http://127.0.0.1:{server.server_port}") as transport:
            for _ in range(3):
                a.sync_once(transport, ta)
                b.sync_once(transport, tb)
            assert content(a) == content(b)
            assert content(b)["lists"][0][1] == "Final name"
            assert len(content(b)["members"]) == len(content(b)["notes"]) == 2
            assert a.status()["awaiting_receipts"] == b.status()["deferred"] == 0
            assert len(b.history()) == 8
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        assert not worker.is_alive()


def test_membership_update_preserves_creation_time_for_late_empty_peer(pair, tmp_path, monkeypatch):
    from datetime import datetime

    import paper_daily.sync_operations as operations_module

    class Clock:
        value = "2026-01-01T00:00:00+00:00"

        @classmethod
        def now(cls, timezone):
            return datetime.fromisoformat(cls.value)

    monkeypatch.setattr(operations_module, "datetime", Clock)
    a, b = pair
    operations = ResearchOperations(a)
    result = operations.create_list("Reading", [{"paper": paper()}], request_id="original")
    service, ta, tb = sync_all(a, b, tmp_path)
    Clock.value = "2026-02-01T00:00:00+00:00"
    operations.add_papers(
        result["list_id"],
        [{"paper_id": result["papers"][0]["paper_id"], "citation": "Updated context"}],
        request_id="later-update",
    )
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    c = client(tmp_path / "late.sqlite", "late")
    c.sync_once(service, service.enroll("workspace", "late"))
    assert content(a) == content(b) == content(c)
    assert content(c)["members"][0][-1] == "2026-01-01T00:00:00+00:00"
    assert content(c)["members"][0][2] == "Updated context"
