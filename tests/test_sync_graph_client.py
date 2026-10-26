"""Graph projection and operation behavior using isolated synthetic clients."""

import json
import sqlite3
from uuid import NAMESPACE_URL, uuid5

import pytest

from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_schema_v2 import membership_id
from paper_daily.sync_service import ReferenceService

PAPER = str(uuid5(NAMESPACE_URL, "paperfact-test-paper"))
OTHER_PAPER = str(uuid5(NAMESPACE_URL, "paperfact-test-other-paper"))
LIST = "list-graph"
MEMBER = membership_id(LIST, PAPER)


def paper_payload(title="Synthetic paper"):
    return {
        "title": title,
        "authors": ["Fixture Author"],
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


def membership_payload(citation="A useful paper"):
    return {
        "list_id": LIST,
        "paper_id": PAPER,
        "citation": citation,
        "added_at": "2026-10-26T00:00:00+00:00",
    }


def writer(conn, operation):
    key = (operation["entity_type"], operation["entity_id"])
    if operation["action"] == "delete":
        conn.execute("DELETE FROM research WHERE kind=? AND id=?", key)
        if key[0] == "list":
            for row in conn.execute(
                "SELECT id,body FROM research WHERE kind='membership'"
            ).fetchall():
                if json.loads(row[1])["list_id"] == key[1]:
                    conn.execute("DELETE FROM research WHERE kind='membership' AND id=?", (row[0],))
        return
    for parent in operation.get("parents", []):
        if (
            conn.execute(
                "SELECT 1 FROM research WHERE kind=? AND id=?", (parent["kind"], parent["id"])
            ).fetchone()
            is None
        ):
            raise ValueError("Visible parent must exist before child projection")
    conn.execute(
        "INSERT INTO research VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
        (*key, json.dumps(operation["payload"])),
    )


def client(path, device):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research (kind TEXT,id TEXT,body TEXT,PRIMARY KEY(kind,id))"
        )
    return SyncClient(Journal(path, workspace_id="workspace", device_id=device), writer)


def saved(side, kind, identity):
    with sqlite3.connect(side.journal.path) as conn:
        row = conn.execute(
            "SELECT body FROM research WHERE kind=? AND id=?", (kind, identity)
        ).fetchone()
    return json.loads(row[0]) if row else None


def save(side, kind, identity, payload, **kwargs):
    value = side.new_graph_operation(kind, identity, payload, **kwargs)
    side.save(value)
    return value


def seed(side):
    return [
        save(side, "list", LIST, {"name": "Reading", "note": ""}),
        save(side, "paper", PAPER, paper_payload()),
        save(side, "membership", MEMBER, membership_payload()),
        save(side, "note", "note-graph", {"paper_id": PAPER, "body": "An observation"}),
    ]


@pytest.fixture
def pair(tmp_path):
    server = ReferenceService(tmp_path / "service.sqlite")
    a, b = client(tmp_path / "a.sqlite", "a"), client(tmp_path / "b.sqlite", "b")
    return server, a, b, server.enroll("workspace", "a"), server.enroll("workspace", "b")


def test_offline_graph_and_latest_heads_apply_parents_before_children(pair):
    server, a, b, ta, tb = pair
    first = seed(a)
    rename = save(a, "list", LIST, {"name": "Renamed", "note": ""})
    assert rename["incarnation"] == first[0]["operation_id"]
    assert rename["depends_on"] == first[0]["operation_id"]
    a = client(a.journal.path, "a")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    for kind, identity in (
        ("list", LIST),
        ("paper", PAPER),
        ("membership", MEMBER),
        ("note", "note-graph"),
    ):
        assert saved(a, kind, identity) == saved(b, kind, identity)
    assert saved(b, "list", LIST)["name"] == "Renamed"
    assert b.status()["deferred"] == 0
    assert b.deferred_reasons() == []
    assert len(b.history()) == 5


def test_pending_parent_defers_child_but_not_unrelated_research(pair):
    server, a, b, ta, tb = pair
    save(a, "list", LIST, {"name": "Reading", "note": ""})
    save(a, "paper", PAPER, paper_payload())
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    save(b, "list", LIST, {"name": "Local draft name", "note": ""})
    save(a, "membership", MEMBER, membership_payload())
    save(a, "paper", OTHER_PAPER, paper_payload("Independent paper"))
    a.sync_once(server, ta)
    b.receive(server.pull(tb, after=b.status()["cursor"]))
    assert saved(b, "membership", MEMBER) is None
    assert saved(b, "list", LIST)["name"] == "Local draft name"
    assert saved(b, "paper", OTHER_PAPER)["title"] == "Independent paper"
    assert {row["reason"] for row in b.deferred_reasons()} == {"pending_local", "parent_pending"}
    b.sync_once(server, tb)
    assert saved(b, "membership", MEMBER) == membership_payload()
    assert b.deferred_reasons() == []


def prepare_deleted_parent_conflict(pair):
    server, a, b, ta, tb = pair
    seed(a)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    save(b, "membership", MEMBER, membership_payload("Preserve this offline edit"))
    save(a, "list", LIST, {}, action="delete")
    a.sync_once(server, ta)
    b.receive(server.pull(tb, after=b.status()["cursor"]))
    return pair


def test_ancestor_delete_protects_pending_child_then_hides_obsolete_projection(pair):
    server, a, b, ta, tb = prepare_deleted_parent_conflict(pair)
    assert saved(b, "list", LIST) is not None
    assert saved(b, "membership", MEMBER)["citation"] == "Preserve this offline edit"
    assert "pending_descendant" in {row["reason"] for row in b.deferred_reasons()}
    b.sync_once(server, tb)
    assert saved(b, "list", LIST) is None
    assert saved(b, "membership", MEMBER) is None
    assert saved(b, "paper", PAPER) is not None
    assert saved(b, "note", "note-graph")["body"] == "An observation"
    conflicts = b.history(conflicts_only=True)
    assert conflicts[-1]["operation"]["payload"]["citation"] == "Preserve this offline edit"
    assert b.status()["pending"] == 0
    assert "parent_deleted" in {row["reason"] for row in b.deferred_reasons()}


def test_restore_changes_incarnation_and_never_reintroduces_old_membership(pair):
    server, a, b, ta, tb = pair
    original = seed(a)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    save(a, "list", LIST, {}, action="delete")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    with pytest.raises(ValueError, match="restore=True"):
        a.new_graph_operation("list", LIST, {"name": "Restored", "note": ""})
    restored = save(a, "list", LIST, {"name": "Restored", "note": ""}, restore=True)
    assert restored["incarnation"] != original[0]["incarnation"]
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(b, "list", LIST)["name"] == "Restored"
    assert saved(b, "membership", MEMBER) is None
    assert "parent_incarnation" in {row["reason"] for row in b.deferred_reasons()}
    with pytest.raises(ValueError, match="restore=True"):
        a.new_graph_operation("membership", MEMBER, membership_payload())
    save(a, "membership", MEMBER, membership_payload(), restore=True)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(b, "membership", MEMBER) == membership_payload()
    assert b.deferred_reasons() == []


def test_offline_parent_delete_tracks_latest_child_structural_dependency(pair):
    server, a, b, ta, tb = pair
    original = seed(a)
    deletion = save(a, "list", LIST, {}, action="delete")
    assert deletion["depends_on"] == original[0]["operation_id"]
    assert deletion["structure_depends_on"] == original[2]["operation_id"]
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert a.status()["conflicts"] == b.status()["conflicts"] == 0
    assert saved(b, "list", LIST) is None
    assert saved(b, "membership", MEMBER) is None
    assert saved(b, "note", "note-graph") is not None


def test_graph_projection_failure_rolls_back_graph_cursor_and_content(pair):
    server, a, b, ta, tb = pair
    seed(a)
    a.sync_once(server, ta)

    def fail(conn, operation):
        writer(conn, operation)
        if operation["entity_type"] == "membership":
            raise RuntimeError("simulated research write failure")

    b.writer = fail
    with pytest.raises(RuntimeError):
        b.sync_once(server, tb)
    assert b.status()["cursor"] == 0
    assert b.history() == []
    assert b.deferred_reasons() == []
    assert saved(b, "paper", PAPER) is None
    b.writer = writer
    b.sync_once(server, tb)
    assert saved(b, "membership", MEMBER) == membership_payload()


def test_acknowledged_parent_before_pull_still_supplies_child_incarnation(pair):
    server, a, b, ta, tb = pair
    paper = save(a, "paper", PAPER, paper_payload())
    accepted = server.push(ta, paper)
    a.journal.acknowledge(paper["operation_id"], accepted["sequence"])
    note = save(a, "note", "note-graph", {"paper_id": PAPER, "body": "After acknowledgment"})
    assert note["parents"] == [{"kind": "paper", "id": PAPER, "incarnation": paper["incarnation"]}]
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(b, "note", "note-graph")["body"] == "After acknowledgment"


def test_compound_builder_observes_uncommitted_parent_and_rolls_back_as_one(pair):
    _, a, _, _, _ = pair
    with pytest.raises(RuntimeError), a.journal.transaction() as conn:
        paper = a.new_graph_operation_in(conn, "paper", PAPER, paper_payload())
        a.journal.apply_in(conn, paper, writer)
        note = a.new_graph_operation_in(
            conn, "note", "note-graph", {"paper_id": PAPER, "body": "Atomic"}
        )
        a.journal.apply_in(conn, note, writer)
        assert note["parents"][0]["incarnation"] == paper["incarnation"]
        raise RuntimeError("roll back whole action")
    assert saved(a, "paper", PAPER) is None
    assert saved(a, "note", "note-graph") is None
    assert a.journal.pending() == []


def test_transaction_builder_rejects_inactive_or_other_database_connection(pair):
    _, a, b, _, _ = pair
    conn = a.journal._connect()
    try:
        with pytest.raises(ValueError, match="transaction"):
            a.new_graph_operation_in(conn, "paper", PAPER, paper_payload())
    finally:
        conn.close()
    with b.journal.transaction() as conn, pytest.raises(ValueError, match="another research"):
        a.new_graph_operation_in(conn, "paper", PAPER, paper_payload())


def test_canonical_conflict_retirement_closes_without_reviving_deleted_parent(pair):
    server, a, b, ta, tb = prepare_deleted_parent_conflict(pair)
    b.sync_once(server, tb)
    conflict = b.history(conflicts_only=True)[-1]
    result = b.resolve_conflict(conflict["sequence"], choice="canonical", operation_id="retirement")
    assert result["applied"]
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    assert a.status()["conflicts"] == b.status()["conflicts"] == 0
    assert saved(b, "list", LIST) is None
    assert saved(b, "membership", MEMBER) is None
    assert b.status()["deferred"] == 0
    assert b.deferred_reasons() == []
    assert (
        b.resolve_conflict(conflict["sequence"], choice="canonical", operation_id="retirement")[
            "applied"
        ]
        is False
    )


def test_incoming_child_resolution_requires_explicit_restore_after_parent_restore(pair):
    server, a, b, ta, tb = prepare_deleted_parent_conflict(pair)
    b.sync_once(server, tb)
    conflict = b.history(conflicts_only=True)[-1]
    save(a, "list", LIST, {"name": "Restored", "note": ""}, restore=True)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    with pytest.raises(ValueError, match="restore=True"):
        b.resolve_conflict(conflict["sequence"])
    b.resolve_conflict(conflict["sequence"], restore=True)
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    assert b.status()["conflicts"] == 0
    assert saved(a, "membership", MEMBER)["citation"] == "Preserve this offline edit"


def test_graph_metadata_backfills_once_from_retained_event_history(pair):
    server, a, b, ta, tb = pair
    seed(a)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    with sqlite3.connect(b.journal.path) as conn:
        for name in (
            "paperfact_sync_graph",
            "paperfact_sync_graph_projection",
            "paperfact_sync_graph_receipts",
        ):
            conn.execute(f"DROP TABLE {name}")
    reopened = client(b.journal.path, "b")
    reopened.receive([])
    assert saved(reopened, "membership", MEMBER) == membership_payload()
    assert reopened.status()["cursor"] == 4
    assert reopened.deferred_reasons() == []
    again = client(b.journal.path, "b")
    assert again.receive([])["applied"] == 0


@pytest.mark.parametrize("limit", [0, 1001, True, -1])
def test_deferred_diagnostics_are_bounded(pair, limit):
    with pytest.raises(ValueError):
        pair[1].deferred_reasons(limit)


def test_rebuilt_projection_defers_restored_parent_while_old_child_is_pending(pair):
    server, a, b, ta, tb = pair
    seed(a)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    save(b, "membership", MEMBER, membership_payload("Protected local content"))
    with sqlite3.connect(b.journal.path) as conn:
        for name in (
            "paperfact_sync_graph",
            "paperfact_sync_graph_projection",
            "paperfact_sync_graph_receipts",
        ):
            conn.execute(f"DROP TABLE {name}")
    b = client(b.journal.path, "b")
    save(a, "list", LIST, {}, action="delete")
    a.sync_once(server, ta)
    save(a, "list", LIST, {"name": "A new incarnation", "note": ""}, restore=True)
    a.sync_once(server, ta)
    b.receive(server.pull(tb, after=b.status()["cursor"]))
    assert saved(b, "list", LIST)["name"] == "Reading"
    assert saved(b, "membership", MEMBER)["citation"] == "Protected local content"
    assert "pending_descendant" in {row["reason"] for row in b.deferred_reasons()}
    b.sync_once(server, tb)
    assert saved(b, "list", LIST)["name"] == "A new incarnation"
    assert saved(b, "membership", MEMBER) is None
    assert b.history(conflicts_only=True)[-1]["operation"]["payload"]["citation"] == (
        "Protected local content"
    )


@pytest.mark.parametrize("accepted", [False, True])
def test_legacy_builder_cannot_downgrade_pending_or_accepted_graph_entities(pair, accepted):
    server, a, _, ta, _ = pair
    seed(a)
    if accepted:
        a.sync_once(server, ta)
    before = a.journal.pending()
    with pytest.raises(ValueError, match="version-2"):
        a.new_operation("list", LIST, {"name": "Bypass", "note": ""})
    with pytest.raises(ValueError, match="version-2"):
        a.new_operation("note", "a-new-legacy-note", {"paper_id": PAPER, "body": "Bypass"})
    assert a.journal.pending() == before


@pytest.mark.parametrize("accepted", [False, True])
def test_supplied_legacy_envelope_cannot_bypass_graph_save_guard(pair, accepted):
    server, a, _, ta, _ = pair
    legacy = a.new_operation("list", LIST, {"name": "Bypass", "note": ""})
    legacy_note = a.new_operation("note", "raw-legacy-note", {"paper_id": PAPER, "body": "Bypass"})
    created = seed(a)
    if not accepted:
        # Make the raw envelope satisfy journal causality so this specifically
        # exercises the client guard inside the trusted writer transaction.
        legacy["depends_on"] = created[0]["operation_id"]
    if accepted:
        a.sync_once(server, ta)
    before = a.status(), a.journal.pending(), saved(a, "list", LIST)
    for operation in (legacy, legacy_note):
        with pytest.raises(ValueError, match="version-2"):
            a.save(operation)
        assert (a.status(), a.journal.pending(), saved(a, "list", LIST)) == before
    assert saved(a, "note", "raw-legacy-note") is None


def test_legacy_note_delete_cannot_bypass_new_graph_paper_parent(pair):
    server, a, _, ta, _ = pair
    a.save(a.new_operation("note", "legacy-note", {"paper_id": PAPER, "body": "Retain"}))
    a.sync_once(server, ta)
    deletion = a.new_operation("note", "legacy-note", {}, action="delete")
    save(a, "paper", PAPER, paper_payload())
    a.sync_once(server, ta)
    with pytest.raises(ValueError, match="version-2"):
        a.new_operation("note", "legacy-note", {}, action="delete")
    with pytest.raises(ValueError, match="version-2"):
        a.save(deletion)
    assert saved(a, "note", "legacy-note")["body"] == "Retain"
    assert a.journal.pending() == []


@pytest.mark.parametrize("phase", ["pending", "acknowledged", "accepted", "remote"])
def test_membership_added_at_cannot_change_in_builder_or_raw_save(pair, phase):
    server, a, b, ta, tb = pair
    seed(a)
    side = a
    if phase == "acknowledged":
        for operation in a.journal.pending():
            event = server.push(ta, operation)
            a.journal.acknowledge(operation["operation_id"], event["sequence"])
    elif phase in ("accepted", "remote"):
        a.sync_once(server, ta)
        if phase == "remote":
            b.sync_once(server, tb)
            side = b
    before = side.status(), side.journal.pending(), saved(side, "membership", MEMBER)
    changed = membership_payload("A different citation is allowed, a new time is not")
    changed["added_at"] = "2026-11-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="added_at is immutable"):
        side.new_graph_operation("membership", MEMBER, changed)
    raw = side.new_graph_operation("membership", MEMBER, membership_payload("New citation"))
    raw["payload"]["added_at"] = changed["added_at"]
    with pytest.raises(ValueError, match="added_at is immutable"):
        side.save(raw)
    assert (side.status(), side.journal.pending(), saved(side, "membership", MEMBER)) == before


def test_membership_timestamp_guard_reads_same_transaction_creation(pair):
    _, a, _, _, _ = pair
    with a.journal.transaction() as conn:
        for kind, identity, payload in (
            ("list", LIST, {"name": "Reading", "note": ""}),
            ("paper", PAPER, paper_payload()),
            ("membership", MEMBER, membership_payload()),
        ):
            operation = a.new_graph_operation_in(conn, kind, identity, payload)
            a.journal.apply_in(conn, operation, writer)
        changed = membership_payload()
        changed["added_at"] = "2026-11-01T00:00:00+00:00"
        with pytest.raises(ValueError, match="added_at is immutable"):
            a.new_graph_operation_in(conn, "membership", MEMBER, changed)
    assert saved(a, "membership", MEMBER) == membership_payload()
    assert len(a.journal.pending()) == 3


def test_new_membership_incarnation_can_have_its_own_creation_time(pair):
    server, a, b, ta, tb = pair
    original = seed(a)[2]
    a.sync_once(server, ta)
    save(a, "membership", MEMBER, {}, action="delete")
    a.sync_once(server, ta)
    changed = membership_payload("Restored membership")
    changed["added_at"] = "2026-11-01T00:00:00+00:00"
    restored = save(a, "membership", MEMBER, changed, restore=True)
    assert restored["incarnation"] != original["incarnation"]
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(a, "membership", MEMBER) == saved(b, "membership", MEMBER) == changed


def test_conflict_resolution_cannot_change_membership_creation_time(pair):
    server, a, b, ta, tb = pair
    seed(a)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    save(a, "membership", MEMBER, membership_payload("First interpretation"))
    save(b, "membership", MEMBER, membership_payload("Second interpretation"))
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    conflict = b.history(conflicts_only=True)[-1]
    changed = membership_payload("Merged interpretation")
    changed["added_at"] = "2026-11-01T00:00:00+00:00"
    before = b.status(), b.journal.pending(), saved(b, "membership", MEMBER)
    with pytest.raises(ValueError, match="added_at is immutable"):
        b.resolve_conflict(conflict["sequence"], payload=changed)
    assert (b.status(), b.journal.pending(), saved(b, "membership", MEMBER)) == before
