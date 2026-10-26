"""Full user ordering intents retain content and converge through shared actions."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_sync_operations import client, paper, query

from paper_daily.sync_client import SyncClient
from paper_daily.sync_operations import ResearchOperations
from paper_daily.sync_research import research_order_writer, research_writer
from paper_daily.sync_service import ReferenceService


def local(path, device):
    base = client(path, device)
    return SyncClient(base.journal, research_writer, order_writer=research_order_writer)


def ids(result):
    return [item["paper_id"] for item in result["papers"]]


def order(client, list_id):
    return [
        row[0]
        for row in query(
            client,
            "SELECT p.sync_id FROM list_papers lp JOIN research_paper_identity p "
            "ON p.local_id=lp.paper_id WHERE lp.list_id=? ORDER BY lp.position",
            (list_id,),
        )
    ]


def lists_order(client):
    rows = query(client, "SELECT value FROM kv WHERE key='lists.order'")
    return json.loads(rows[0][0]) if rows else None


@pytest.fixture
def setup(tmp_path):
    a, b = local(tmp_path / "a.db", "a"), local(tmp_path / "b.db", "b")
    actions = ResearchOperations(a)
    first = actions.create_list(
        "First", [{"paper": paper(str(i))} for i in range(3)], request_id="first"
    )
    second = actions.create_list("Second", [{"paper_id": ids(first)[0]}], request_id="second")
    service = ReferenceService(tmp_path / "server.db")
    ta, tb = service.enroll("workspace", "a"), service.enroll("workspace", "b")
    return a, b, actions, first, second, service, ta, tb


def transfer(setup):
    a, b, _, _, _, service, ta, tb = setup
    a.sync_once(service, ta)
    b.sync_once(service, tb)


def test_paper_and_workspace_orders_reach_empty_peer_without_changing_research(setup):
    a, b, actions, first, second, *_ = setup
    desired = list(reversed(ids(first)))
    actions.set_reading_state(first["list_id"], [desired[0]], "read", request_id="read")
    actions.reorder_papers(first["list_id"], desired, request_id="paper-order")
    actions.reorder_lists([second["list_id"], first["list_id"]], request_id="list-order")
    transfer(setup)
    assert order(a, first["list_id"]) == order(b, first["list_id"]) == desired
    assert lists_order(a) == lists_order(b) == [second["list_id"], first["list_id"]]
    assert order(a, second["list_id"]) == order(b, second["list_id"]) == [ids(first)[0]]
    assert query(
        a, "SELECT state FROM list_papers WHERE list_id=? ORDER BY position", (first["list_id"],)
    ) == [("read",), ("pending",), ("pending",)]
    assert len(query(b, "SELECT * FROM papers")) == 3
    assert a.status()["pending"] == b.status()["deferred"] == 0


def test_default_order_uses_creation_sequence_not_late_citation_head(setup):
    a, b, actions, first, _, *_ = setup
    actions.add_papers(
        first["list_id"],
        [{"paper_id": ids(first)[0], "citation": "New context"}],
        request_id="citation",
    )
    transfer(setup)
    assert order(a, first["list_id"]) == order(b, first["list_id"]) == ids(first)


def test_accepted_order_filters_removed_members_and_appends_new_members(setup):
    a, b, actions, first, _, service, ta, tb = setup
    desired = list(reversed(ids(first)))
    actions.reorder_papers(first["list_id"], desired, request_id="order")
    transfer(setup)
    removed = first["papers"][0]
    a.save(a.new_graph_operation("membership", removed["membership_id"], {}, action="delete"))
    added = actions.add_papers(first["list_id"], [{"paper": paper("New")}], request_id="new")
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    expected = [item for item in desired if item != removed["paper_id"]] + ids(added)
    assert order(a, first["list_id"]) == order(b, first["list_id"]) == expected


def test_retry_after_later_reorder_returns_receipt_without_reverting_current_order(setup):
    a, _, actions, first, *_ = setup
    desired = list(reversed(ids(first)))
    original = actions.reorder_papers(first["list_id"], desired, request_id="original-order")
    actions.reorder_papers(first["list_id"], ids(first), request_id="new-order")
    assert (
        actions.reorder_papers(first["list_id"], desired, request_id="original-order") == original
    )
    assert order(a, first["list_id"]) == ids(first)
    with pytest.raises(ValueError, match="retry changed"):
        actions.reorder_papers(first["list_id"], ids(first), request_id="original-order")


def test_repeated_concurrent_order_action_emits_one_operation(setup):
    a, _, actions, first, *_ = setup
    before = len(a.journal.pending())

    def submit(_):
        return actions.reorder_papers(
            first["list_id"], list(reversed(ids(first))), request_id="repeat"
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(12)))
    assert all(result == results[0] for result in results)
    assert len(a.journal.pending()) == before + 1
    assert order(a, first["list_id"]) == list(reversed(ids(first)))


@pytest.mark.parametrize(
    "case", ["empty", "partial", "duplicate", "unknown", "invalid", "too-many"]
)
def test_invalid_order_never_changes_positions_or_receipts(setup, case):
    a, _, actions, first, *_ = setup
    original = ids(first)
    choices = {
        "empty": [],
        "partial": original[:1],
        "duplicate": [original[0]] * 3,
        "unknown": ["00000000-0000-0000-0000-000000000099", *original[1:]],
        "invalid": ["invalid"],
        "too-many": [original[0]] * 2001,
    }
    before = a.journal.pending()
    with pytest.raises(ValueError):
        actions.reorder_papers(first["list_id"], choices[case], request_id="bad-order")
    assert order(a, first["list_id"]) == original and a.journal.pending() == before
    assert query(a, "SELECT * FROM research_action_receipts WHERE request_id='bad-order'") == []


def test_order_receipt_failure_rolls_back_positions(setup):
    a, _, actions, first, *_ = setup
    with sqlite3.connect(a.journal.path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_order BEFORE INSERT ON research_action_receipts "
            "WHEN NEW.request_id='bad-order' BEGIN SELECT RAISE(ABORT,'receipt failure'); END"
        )
    before = a.journal.pending()
    with pytest.raises(sqlite3.IntegrityError, match="receipt failure"):
        actions.reorder_papers(first["list_id"], list(reversed(ids(first))), request_id="bad-order")
    assert order(a, first["list_id"]) == ids(first) and a.journal.pending() == before


def test_empty_list_order_is_valid_and_deleted_scope_rejects_new_order(setup):
    a, b, actions, *_ = setup
    empty = actions.create_list("Empty", [], request_id="empty")
    actions.reorder_papers(empty["list_id"], [], request_id="empty-order")
    transfer(setup)
    assert order(a, empty["list_id"]) == order(b, empty["list_id"]) == []
    a.save(a.new_graph_operation("list", empty["list_id"], {}, action="delete"))
    before = a.journal.pending()
    with pytest.raises(ValueError, match="active"):
        actions.reorder_papers(empty["list_id"], [], request_id="deleted-order")
    assert a.journal.pending() == before


def test_workspace_order_does_not_overwrite_unrelated_kv_or_queue(setup):
    a, _, actions, first, second, *_ = setup
    with sqlite3.connect(a.journal.path) as conn:
        conn.execute("INSERT INTO kv(key,value) VALUES('ui.fixture','keep')")
    actions.reorder_lists([second["list_id"], first["list_id"]], request_id="workspace-order")
    assert query(a, "SELECT value FROM kv WHERE key='ui.fixture'") == [("keep",)]
    assert query(a, "SELECT * FROM queue") == []


@pytest.mark.parametrize("case", ["empty", "partial", "duplicate", "unknown", "non-list"])
def test_invalid_workspace_order_preserves_lists_and_prior_order(setup, case):
    a, _, actions, first, second, *_ = setup
    initial = [first["list_id"], second["list_id"]]
    actions.reorder_lists(initial, request_id="initial-workspace-order")
    choices = {
        "empty": [],
        "partial": initial[:1],
        "duplicate": [initial[0]] * 2,
        "unknown": [initial[0], "unknown-list"],
        "non-list": None,
    }
    before = a.journal.pending()
    with pytest.raises(ValueError):
        actions.reorder_lists(choices[case], request_id="invalid-workspace-order")
    assert lists_order(a) == initial and a.journal.pending() == before
    assert len(query(a, "SELECT * FROM lists")) == 2


def test_empty_workspace_accepts_empty_order_and_receipt_retry(tmp_path):
    a = local(tmp_path / "empty.db", "empty")
    actions = ResearchOperations(a)
    result = actions.reorder_lists([], request_id="empty-order")
    assert lists_order(a) == []
    assert actions.reorder_lists([], request_id="empty-order") == result
    assert len(a.journal.pending()) == 1


def test_workspace_order_receipt_failure_keeps_previous_kv_order(setup):
    a, _, actions, first, second, *_ = setup
    initial = [first["list_id"], second["list_id"]]
    actions.reorder_lists(initial, request_id="initial-workspace-order")
    with sqlite3.connect(a.journal.path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_workspace_order BEFORE INSERT ON research_action_receipts "
            "WHEN NEW.request_id='bad-order' BEGIN SELECT RAISE(ABORT,'receipt failure'); END"
        )
    before = a.journal.pending()
    with pytest.raises(sqlite3.IntegrityError, match="receipt failure"):
        actions.reorder_lists(list(reversed(initial)), request_id="bad-order")
    assert lists_order(a) == initial and a.journal.pending() == before
