"""Explicit reading actions are atomic, per-list and retry-safe across devices."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4

import pytest
from test_sync_operations import client, paper, query, sync_all

from paper_daily.sync_operations import ResearchOperations
from paper_daily.sync_research import research_writer


class Clock:
    value = "2026-01-01T01:00:00+00:00"

    @classmethod
    def now(cls, timezone):
        return datetime.fromisoformat(cls.value)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr("paper_daily.sync_operations.datetime", Clock)
    Clock.value = "2026-01-01T01:00:00+00:00"
    a, b = client(tmp_path / "a.db", "a"), client(tmp_path / "b.db", "b")
    actions = ResearchOperations(a)
    first = actions.create_list(
        "First", [{"paper": paper("One")}, {"paper": paper("Two")}], request_id="first"
    )
    return a, b, actions, first


def states(client):
    return query(
        client,
        "SELECT lp.list_id,p.sync_id,lp.state,lp.delivered_at,lp.read_at "
        "FROM list_papers lp JOIN research_paper_identity p ON p.local_id=lp.paper_id "
        "ORDER BY lp.list_id,p.sync_id",
    )


def papers(result):
    return [entry["paper_id"] for entry in result["papers"]]


def test_reading_action_preserves_other_list_and_reaches_empty_peer(setup, tmp_path):
    a, b, actions, first = setup
    ids = papers(first)
    second = actions.create_list("Second", [{"paper_id": ids[0]}], request_id="second")
    actions.set_reading_state(first["list_id"], ids, "read", request_id="mark-read")
    sync_all(a, b, tmp_path)
    assert states(a) == states(b)
    first_rows = [row for row in states(b) if row[0] == first["list_id"]]
    assert len(first_rows) == 2
    assert all(row[2:] == ("read", None, Clock.value) for row in first_rows)
    assert [row[2:] for row in states(b) if row[0] == second["list_id"]] == [
        ("pending", None, None)
    ]
    assert a.status()["pending"] == b.status()["deferred"] == 0


def test_timestamps_follow_explicit_transitions_and_exact_retry_is_frozen(setup, tmp_path):
    a, b, actions, first = setup
    ids = papers(first)
    delivered = Clock.value
    actions.set_reading_state(first["list_id"], ids, "delivered", request_id="open")
    Clock.value = "2026-01-02T01:00:00+00:00"
    marked = actions.set_reading_state(first["list_id"], ids, "read", request_id="read")
    Clock.value = "2026-01-03T01:00:00+00:00"
    actions.set_reading_state(first["list_id"], ids, "pending", request_id="unread")
    assert all(row[2:] == ("pending", delivered, "2026-01-02T01:00:00+00:00") for row in states(a))
    before = states(a)
    assert actions.set_reading_state(first["list_id"], ids, "read", request_id="read") == marked
    assert states(a) == before
    sync_all(a, b, tmp_path)
    assert states(a) == states(b)
    restarted = ResearchOperations(client(a.journal.path, "a"))
    assert restarted.set_reading_state(first["list_id"], ids, "read", request_id="read") == marked
    assert states(a) == before
    with pytest.raises(ValueError, match="retry changed"):
        restarted.set_reading_state(first["list_id"], ids, "skipped", request_id="read")


def test_repeated_concurrent_read_action_has_one_result_and_one_change_per_paper(setup):
    a, _, actions, first = setup
    ids = papers(first)
    before = len(a.journal.pending())

    def submit(_):
        return actions.set_reading_state(first["list_id"], ids, "read", request_id="same-read")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(12)))
    assert all(result == results[0] for result in results)
    assert len(a.journal.pending()) == before + 2
    assert len(query(a, "SELECT * FROM research_action_receipts WHERE request_id='same-read'")) == 1


def test_later_paper_failure_rolls_back_earlier_state_and_retry_receipt(setup):
    a, _, actions, first = setup
    ids = papers(first)
    before, pending = states(a), a.journal.pending()

    def fail(conn, operation):
        research_writer(conn, operation)
        if (
            operation["entity_type"] == "reading_state"
            and operation["payload"]["paper_id"] == ids[1]
        ):
            raise RuntimeError("Interrupted second paper")

    a.writer = fail
    with pytest.raises(RuntimeError, match="second paper"):
        actions.set_reading_state(first["list_id"], ids, "read", request_id="interrupted-read")
    assert states(a) == before and a.journal.pending() == pending
    assert (
        query(a, "SELECT * FROM research_action_receipts WHERE request_id='interrupted-read'") == []
    )
    a.writer = research_writer
    actions.set_reading_state(first["list_id"], ids, "read", request_id="interrupted-read")
    assert all(row[2] == "read" for row in states(a))


@pytest.mark.parametrize(
    "selection,state",
    [
        ([], "read"),
        (None, "read"),
        (["bad"], "read"),
        ([str(uuid4())], "unknown"),
        ([str(uuid4())] * 201, "read"),
    ],
)
def test_invalid_selection_or_state_never_writes(setup, selection, state):
    a, _, actions, first = setup
    before, pending = states(a), a.journal.pending()
    with pytest.raises(ValueError):
        actions.set_reading_state(first["list_id"], selection, state, request_id="invalid-read")
    assert states(a) == before and a.journal.pending() == pending
    assert query(a, "SELECT * FROM research_action_receipts WHERE request_id='invalid-read'") == []


def test_duplicate_or_missing_membership_does_not_partially_mark_other_papers(setup):
    a, _, actions, first = setup
    ids = papers(first)
    before, pending = states(a), a.journal.pending()
    for selection in ([ids[0], ids[0]], [ids[0], str(uuid4())]):
        with pytest.raises(ValueError):
            actions.set_reading_state(
                first["list_id"], selection, "read", request_id="invalid-selection"
            )
        assert states(a) == before and a.journal.pending() == pending


def test_read_receipt_failure_leaves_state_unsaved(setup):
    a, _, actions, first = setup
    with sqlite3.connect(a.journal.path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_read BEFORE INSERT ON research_action_receipts "
            "WHEN NEW.request_id='bad-receipt' BEGIN SELECT RAISE(ABORT,'receipt failure'); END"
        )
    before, pending = states(a), a.journal.pending()
    with pytest.raises(sqlite3.IntegrityError, match="receipt failure"):
        actions.set_reading_state(first["list_id"], papers(first), "read", request_id="bad-receipt")
    assert states(a) == before and a.journal.pending() == pending


def test_delayed_state_retry_after_membership_removal_does_not_restore_it(setup, tmp_path):
    a, b, actions, first = setup
    ids = papers(first)
    result = actions.set_reading_state(
        first["list_id"], [ids[0]], "read", request_id="original-read"
    )
    member = first["papers"][0]["membership_id"]
    a.save(a.new_graph_operation("membership", member, {}, action="delete"))
    assert (
        actions.set_reading_state(first["list_id"], [ids[0]], "read", request_id="original-read")
        == result
    )
    assert len(states(a)) == 1
    with pytest.raises(ValueError, match="active"):
        actions.set_reading_state(first["list_id"], [ids[0]], "read", request_id="new-read")
    sync_all(a, b, tmp_path)
    assert states(a) == states(b) and len(states(b)) == 1


def test_mutating_caller_selection_during_save_cannot_change_the_fingerprinted_action(setup):
    a, _, actions, first = setup
    original_ids = papers(first)
    selection = original_ids.copy()
    changed = False

    def change_selection(conn, operation):
        nonlocal changed
        research_writer(conn, operation)
        if operation["entity_type"] == "reading_state" and not changed:
            changed = True
            selection.clear()

    a.writer = change_selection
    result = actions.set_reading_state(first["list_id"], selection, "read", request_id="frozen")
    assert changed and selection == []
    assert len(result["papers"]) == 2
    assert all(row[2] == "read" for row in states(a))
    assert (
        actions.set_reading_state(first["list_id"], original_ids, "read", request_id="frozen")
        == result
    )


def test_explicit_mark_on_restored_membership_creates_fresh_state_incarnation(setup, tmp_path):
    a, b, actions, first = setup
    paper_id = papers(first)[0]
    member_id = first["papers"][0]["membership_id"]
    old = actions.set_reading_state(first["list_id"], [paper_id], "read", request_id="old-read")
    service, ta, tb = sync_all(a, b, tmp_path)
    a.save(a.new_graph_operation("membership", member_id, {}, action="delete"))
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    Clock.value = "2026-02-01T01:00:00+00:00"
    a.save(
        a.new_graph_operation(
            "membership",
            member_id,
            {
                "list_id": first["list_id"],
                "paper_id": paper_id,
                "citation": None,
                "added_at": Clock.value,
            },
            restore=True,
        )
    )
    result = actions.set_reading_state(
        first["list_id"], [paper_id], "delivered", request_id="new-open"
    )
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert states(a) == states(b)
    row = next(row for row in states(b) if row[1] == paper_id)
    assert row[2:] == ("delivered", Clock.value, None)
    assert result["operation_ids"] != old["operation_ids"]
    assert a.status()["conflicts"] == b.status()["deferred"] == 0
