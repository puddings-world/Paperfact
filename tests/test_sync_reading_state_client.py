"""Reading-state graph behavior using synthetic SQLite workspaces and a local peer."""

import json
import sqlite3
from uuid import NAMESPACE_URL, uuid5

import pytest

from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_schema_v2 import membership_id
from paper_daily.sync_service import ReferenceService

PAPER = str(uuid5(NAMESPACE_URL, "paperfact-reading-state-test"))
LIST = "reading-list"
MEMBER = membership_id(LIST, PAPER)
STAMP = "2026-10-26T00:00:00+00:00"


def paper_payload():
    return {
        "title": "Synthetic reading paper",
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


def membership_payload(citation="Reference"):
    return {"list_id": LIST, "paper_id": PAPER, "citation": citation, "added_at": STAMP}


def reading_payload(state="read"):
    return {
        "list_id": LIST,
        "paper_id": PAPER,
        "state": state,
        "delivered_at": STAMP if state in ("delivered", "read") else None,
        "read_at": STAMP if state == "read" else None,
    }


def writer(conn, operation):
    key = (operation["entity_type"], operation["entity_id"])
    if operation["action"] == "delete":
        conn.execute("DELETE FROM research WHERE kind=? AND id=?", key)
        if key[0] == "membership":
            conn.execute("DELETE FROM research WHERE kind='reading_state' AND id=?", (key[1],))
        elif key[0] == "list":
            members = conn.execute(
                "SELECT id,body FROM research WHERE kind='membership'"
            ).fetchall()
            for identity, body in members:
                if json.loads(body)["list_id"] == key[1]:
                    conn.execute(
                        "DELETE FROM research WHERE kind IN ('membership','reading_state') "
                        "AND id=?",
                        (identity,),
                    )
        return
    for parent in operation["parents"]:
        if (
            conn.execute(
                "SELECT 1 FROM research WHERE kind=? AND id=?", (parent["kind"], parent["id"])
            ).fetchone()
            is None
        ):
            raise ValueError("Research parent projection must exist first")
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


def saved(side, kind="reading_state", identity=MEMBER):
    with sqlite3.connect(side.journal.path) as conn:
        row = conn.execute(
            "SELECT body FROM research WHERE kind=? AND id=?", (kind, identity)
        ).fetchone()
    return json.loads(row[0]) if row else None


def save(side, kind, identity, payload, **options):
    operation = side.new_graph_operation(kind, identity, payload, **options)
    side.save(operation)
    return operation


def seed(side, *, with_state=True):
    result = [
        save(side, "list", LIST, {"name": "Reading", "note": ""}),
        save(side, "paper", PAPER, paper_payload()),
        save(side, "membership", MEMBER, membership_payload()),
    ]
    if with_state:
        result.append(save(side, "reading_state", MEMBER, reading_payload("pending")))
    return result


@pytest.fixture
def pair(tmp_path):
    server = ReferenceService(tmp_path / "service.sqlite")
    a, b = client(tmp_path / "a.sqlite", "a"), client(tmp_path / "b.sqlite", "b")
    return server, a, b, server.enroll("workspace", "a"), server.enroll("workspace", "b")


@pytest.mark.parametrize("phase", ["pending", "acknowledged", "accepted", "remote"])
def test_reading_builder_uses_exact_membership_closure_and_receives_dependency_order(pair, phase):
    server, a, b, ta, tb = pair
    original = seed(a, with_state=False)
    side, token = a, ta
    if phase == "acknowledged":
        for operation in a.journal.pending():
            event = server.push(ta, operation)
            a.journal.acknowledge(operation["operation_id"], event["sequence"])
    elif phase in ("accepted", "remote"):
        a.sync_once(server, ta)
        if phase == "remote":
            b.sync_once(server, tb)
            side, token = b, tb
    reading = save(side, "reading_state", MEMBER, reading_payload())
    refs = {parent["kind"]: parent for parent in reading["parents"]}
    assert refs == {
        "membership": {
            "kind": "membership",
            "id": MEMBER,
            "incarnation": original[2]["incarnation"],
        },
        **{parent["kind"]: parent for parent in original[2]["parents"]},
    }
    save(side, "membership", MEMBER, membership_payload("Late metadata update"))
    save(side, "list", LIST, {"name": "Latest list name", "note": ""})
    side.sync_once(server, token)
    other, other_token = (b, tb) if side is a else (a, ta)
    other.sync_once(server, other_token)
    assert saved(side) == saved(other) == reading_payload()
    assert saved(other, "list", LIST)["name"] == "Latest list name"
    assert saved(other, "membership")["citation"] == "Late metadata update"
    assert other.status()["deferred"] == 0


@pytest.mark.parametrize("ancestor", ["list", "membership"])
def test_pending_ancestor_edit_defers_reading_projection_without_erasing_current_state(
    pair, ancestor
):
    server, a, b, ta, tb = pair
    seed(a)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    if ancestor == "list":
        save(b, "list", LIST, {"name": "Unsent local name", "note": ""})
    else:
        save(b, "membership", MEMBER, membership_payload("Unsent citation"))
    save(a, "reading_state", MEMBER, reading_payload())
    a.sync_once(server, ta)
    b.receive(server.pull(tb, after=b.status()["cursor"]))
    assert saved(b) == reading_payload("pending")
    assert any(row["entity_type"] == "reading_state" for row in b.deferred_reasons())
    b.sync_once(server, tb)
    assert saved(b) == reading_payload()
    assert b.status()["deferred"] == 0


def deleted_parent_conflict(pair, ancestor):
    server, a, b, ta, tb = pair
    seed(a)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    pending = save(b, "reading_state", MEMBER, reading_payload())
    identity = LIST if ancestor == "list" else MEMBER
    save(a, ancestor, identity, {}, action="delete")
    a.sync_once(server, ta)
    b.receive(server.pull(tb, after=b.status()["cursor"]))
    return pending


@pytest.mark.parametrize("ancestor", ["list", "membership"])
def test_ancestor_removal_preserves_pending_read_until_its_conflict_is_received(pair, ancestor):
    server, _, b, _, tb = pair
    pending = deleted_parent_conflict(pair, ancestor)
    assert saved(b) == reading_payload()
    assert saved(b, "membership") is not None
    assert "pending_descendant" in {row["reason"] for row in b.deferred_reasons()}
    b.sync_once(server, tb)
    assert saved(b) is None
    assert saved(b, "membership") is None
    assert b.history(conflicts_only=True)[-1]["operation"] == pending
    assert saved(b, "paper", PAPER) is not None


@pytest.mark.parametrize("ancestor", ["list", "membership"])
def test_restore_never_resurrects_old_reading_state_without_explicit_new_incarnation(
    pair, ancestor
):
    server, a, b, ta, tb = pair
    original = seed(a)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    save(a, ancestor, LIST if ancestor == "list" else MEMBER, {}, action="delete")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    if ancestor == "list":
        save(a, "list", LIST, {"name": "Restored", "note": ""}, restore=True)
        a.sync_once(server, ta)
        with pytest.raises(ValueError, match="closure"):
            a.new_graph_operation("reading_state", MEMBER, reading_payload())
    save(a, "membership", MEMBER, membership_payload(), restore=True)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(b) is None
    assert saved(b, "membership") is not None
    with pytest.raises(ValueError, match="restore=True"):
        a.new_graph_operation("reading_state", MEMBER, reading_payload())
    restored = save(a, "reading_state", MEMBER, reading_payload(), restore=True)
    assert restored["incarnation"] != original[-1]["incarnation"]
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(b) == reading_payload()


@pytest.mark.parametrize("ref_kind", ["membership", "list", "paper"])
def test_raw_wrong_closure_cannot_mutate_local_state_or_outbox(pair, ref_kind):
    _, a, _, _, _ = pair
    seed(a)
    raw = a.new_graph_operation("reading_state", MEMBER, reading_payload())
    next(ref for ref in raw["parents"] if ref["kind"] == ref_kind)["incarnation"] = "forged"
    before = a.status(), a.journal.pending(), saved(a)
    with pytest.raises(ValueError, match="closure"):
        a.save(raw)
    assert (a.status(), a.journal.pending(), saved(a)) == before


def test_membership_retirement_does_not_silently_reparent_reading_state(pair):
    server, a, b, ta, tb = pair
    deleted_parent_conflict(pair, "membership")
    b.sync_once(server, tb)
    conflict = b.history(conflicts_only=True)[-1]
    b.resolve_conflict(conflict["sequence"], choice="canonical", operation_id="retire-state")
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    assert a.status()["conflicts"] == b.status()["conflicts"] == 0
    assert saved(b) is None
    assert saved(b, "membership") is None
    assert b.status()["deferred"] == 0


def test_custom_reading_resolution_preserves_payload_and_explicit_restore_requirement(pair):
    server, a, b, ta, tb = pair
    seed(a)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    save(a, "reading_state", MEMBER, reading_payload("read"))
    save(b, "reading_state", MEMBER, reading_payload("skipped"))
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    conflict = b.history(conflicts_only=True)[-1]
    chosen = reading_payload("deferred")
    b.resolve_conflict(conflict["sequence"], payload=chosen)
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    assert saved(a) == saved(b) == chosen
    assert b.status()["conflicts"] == 0


def test_reading_state_and_parent_chain_can_share_one_local_transaction(pair):
    server, a, b, ta, tb = pair
    with a.journal.transaction() as conn:
        operations = []
        for kind, identity, payload in (
            ("list", LIST, {"name": "Reading", "note": ""}),
            ("paper", PAPER, paper_payload()),
            ("membership", MEMBER, membership_payload()),
            ("reading_state", MEMBER, reading_payload()),
        ):
            operation = a.new_graph_operation_in(conn, kind, identity, payload)
            a.journal.apply_in(conn, operation, writer)
            operations.append(operation)
        deletion = a.new_graph_operation_in(conn, "membership", MEMBER, {}, action="delete")
        assert deletion["structure_depends_on"] == operations[-1]["operation_id"]
        root_delete = a.new_graph_operation_in(conn, "list", LIST, {}, action="delete")
        assert root_delete["structure_depends_on"] == operations[-1]["operation_id"]
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(b) == reading_payload()


def test_reading_projection_failure_rolls_back_all_dependencies_and_cursor(pair):
    server, a, b, ta, tb = pair
    seed(a)
    a.sync_once(server, ta)

    def fail(conn, operation):
        writer(conn, operation)
        if operation["entity_type"] == "reading_state":
            raise RuntimeError("simulated state persistence failure")

    b.writer = fail
    with pytest.raises(RuntimeError):
        b.sync_once(server, tb)
    assert b.history() == []
    assert b.status()["cursor"] == 0
    assert saved(b, "list", LIST) is None
    assert saved(b, "membership") is None
    b.writer = writer
    b.sync_once(server, tb)
    assert saved(b) == reading_payload("pending")


@pytest.mark.parametrize("state", ["pending", "delivered", "read", "skipped", "deferred"])
def test_supported_reading_states_survive_reopen_and_transfer(pair, state):
    server, a, b, ta, tb = pair
    seed(a, with_state=False)
    save(a, "reading_state", MEMBER, reading_payload(state))
    a = client(a.journal.path, "a")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(b) == reading_payload(state)


def test_incoming_read_resolution_requires_explicit_restore_of_new_membership_incarnation(pair):
    server, a, b, ta, tb = pair
    deleted_parent_conflict(pair, "membership")
    b.sync_once(server, tb)
    conflict = b.history(conflicts_only=True)[-1]
    save(a, "membership", MEMBER, membership_payload(), restore=True)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(b) is None
    with pytest.raises(ValueError, match="restore=True"):
        b.resolve_conflict(conflict["sequence"], choice="incoming")
    b.resolve_conflict(conflict["sequence"], choice="incoming", restore=True)
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    assert a.status()["conflicts"] == b.status()["conflicts"] == 0
    assert saved(a) == saved(b) == reading_payload()


def test_forged_retirement_reference_cannot_bypass_local_closure_validation(pair):
    server, _, b, _, tb = pair
    deleted_parent_conflict(pair, "membership")
    b.sync_once(server, tb)
    conflict = b.history(conflicts_only=True)[-1]
    raw = dict(conflict["head"]["operation"])
    raw.update(
        operation_id="forged-retirement",
        device_id="b",
        action="delete",
        payload={},
        base_revision=conflict["head"]["revision"],
        depends_on=None,
        resolution_of=conflict["operation"]["operation_id"],
    )
    raw["parents"] = [dict(ref) for ref in raw["parents"]]
    next(ref for ref in raw["parents"] if ref["kind"] == "list")["incarnation"] = "forged"
    before = b.status(), b.journal.pending(), saved(b)
    with pytest.raises(ValueError, match="retirement"):
        b.save(raw)
    assert (b.status(), b.journal.pending(), saved(b)) == before
