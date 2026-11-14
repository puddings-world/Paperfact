"""Native metadata/order recovery, explicit lifecycle choices and durable retries."""

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pytest
from test_sync_device_recovery import dump
from test_sync_files import PAPER, paper_payload
from test_sync_recovery_note_copy import capture_recovered_authority
from test_sync_recovery_target import attached
from test_sync_recovery_target import codec as codec
from test_sync_recovery_target import pair as pair
from test_sync_recovery_target import prepared as prepared

from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_choices as choices
from paper_daily import sync_recovery_target as target
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_authority_backup import BackupCancelled
from paper_daily.sync_schema_v2 import membership_id

STAMP = "2026-11-14T00:00:00+00:00"
MEMBER = membership_id("backed-list", PAPER)


@pytest.fixture
def populated(request, monkeypatch):
    import test_sync_recovery_target as fixtures

    original = fixtures.publish

    def publish(pair, folder):
        old = pair[1]
        old.save(
            old.new_graph_operation("list", "second-list", dict(name="Second list", note=None))
        )
        old.save(
            old.new_graph_operation(
                "membership",
                MEMBER,
                dict(
                    list_id="backed-list",
                    paper_id=PAPER,
                    citation=None,
                    added_at=STAMP,
                ),
            )
        )
        old.save(
            old.new_graph_operation(
                "reading_state",
                MEMBER,
                dict(
                    list_id="backed-list",
                    paper_id=PAPER,
                    state="pending",
                    delivered_at=None,
                    read_at=None,
                ),
            )
        )
        old.save(old.new_order_operation("list_order", "backed-list", [MEMBER]))
        old.save(
            old.new_order_operation(
                "workspace_list_order", "workspace-lists", ["backed-list", "second-list"]
            )
        )
        return original(pair, folder)

    monkeypatch.setattr(fixtures, "publish", publish)
    return request.getfixturevalue("prepared")


def select(data, operation):
    old, previous, _change, path, _operation = data
    source = candidates.prepare(old.journal.path, previous.snapshot, previous.workspace)
    change = next(
        row["change_id"]
        for row in source.page()["items"]
        if row["operation_id"] == operation["operation_id"]
    )
    return target.observe(source, path), change


def saved_metadata(path):
    with closing(_readonly_connection(path)) as conn:
        return (
            conn.execute("SELECT name,note FROM lists WHERE id='backed-list'").fetchone(),
            conn.execute("SELECT count(*) FROM integration_operations").fetchone()[0],
        )


@pytest.mark.parametrize(
    "kind",
    ["list", "paper", "membership", "reading_state", "note", "list_order", "workspace_list_order"],
)
def test_replace_emits_typed_new_native_operation_and_preserves_old_device(populated, kind):
    old, _source, _change, path, source_note = populated
    identity, payload = {
        "list": ("backed-list", dict(name="Old chosen name", note="Context")),
        "paper": (PAPER, dict(paper_payload(), title="Old chosen title")),
        "membership": (
            MEMBER,
            dict(
                list_id="backed-list", paper_id=PAPER, citation="A chosen citation", added_at=STAMP
            ),
        ),
        "reading_state": (
            MEMBER,
            dict(
                list_id="backed-list",
                paper_id=PAPER,
                state="read",
                delivered_at=None,
                read_at=STAMP,
            ),
        ),
        "note": (source_note["entity_id"], dict(paper_id=PAPER, body="Chosen old note")),
        "list_order": ("backed-list", [MEMBER]),
        "workspace_list_order": ("workspace-lists", ["second-list", "backed-list"]),
    }[kind]
    operation = (
        old.new_order_operation(kind, identity, payload)
        if kind in choices.ORDERS
        else old.new_graph_operation(kind, identity, payload)
    )
    old.save(operation)
    observed, change = select(populated, operation)
    before = dump(old.journal.path)
    request = str(uuid4())
    plan = choices.prepare(observed, change, "replace", request)
    result = plan.apply()
    assert result["applied"] and result["state"] == "saved_locally"
    assert not result["source_discarded"] and not result["recovery_complete"]
    assert result["remote_accepted"] is None
    pending = attached(path).journal.pending()
    assert len(pending) == 1
    assert pending[0]["entity_type"] == kind and pending[0]["entity_id"] == identity
    assert pending[0]["operation_id"] == request and pending[0]["workspace_id"] == "fresh-research"
    assert pending[0]["parents"] == operation["parents"]
    if kind in choices.ORDERS:
        assert pending[0]["payload"]["items"] == operation["payload"]["items"]
        assert pending[0]["payload"]["observed_set"] != operation["payload"]["observed_set"]
    else:
        assert pending[0]["payload"] == payload
    assert saved_metadata(path)[1] == 1 and dump(old.journal.path) == before
    assert not plan.apply()["applied"]
    fresh = target.observe(observed.source, path)
    assert choices.prepare(fresh, change, "replace", request).apply()["request_reused"]
    assert len(attached(path).journal.pending()) == 1


def test_new_list_add_requires_absence_and_preserves_existing_lists(populated):
    old, _source, _change, path, _operation = populated
    operation = old.new_graph_operation(
        "list", "new-old-list", dict(name="New research", note=None)
    )
    old.save(operation)
    observed, change = select(populated, operation)
    with pytest.raises(ValueError, match="active target"):
        choices.prepare(observed, change, "replace", str(uuid4()))
    result = choices.prepare(observed, change, "add", str(uuid4())).apply()
    assert result["applied"]
    with closing(_readonly_connection(path)) as conn:
        assert conn.execute("SELECT name FROM lists ORDER BY id").fetchall()
        assert conn.execute("SELECT count(*) FROM lists").fetchone()[0] == 3


def test_restoring_deleted_list_is_explicit_and_does_not_restore_children(populated):
    old, _source, _change, path, _operation = populated
    operation = old.new_graph_operation(
        "list", "backed-list", dict(name="Recover this list", note=None)
    )
    old.save(operation)
    client = attached(path)
    client.save(client.new_graph_operation("list", "backed-list", {}, action="delete"))
    observed, change = select(populated, operation)
    for choice in ("add", "replace"):
        with pytest.raises(ValueError):
            choices.prepare(observed, change, choice, str(uuid4()))
    result = choices.prepare(observed, change, "restore", str(uuid4())).apply()
    assert result["applied"]
    pending = client.journal.pending()
    assert [value["action"] for value in pending] == ["delete", "put"]
    assert pending[-1]["incarnation"] != operation["incarnation"]
    with closing(_readonly_connection(path)) as conn:
        assert (
            conn.execute("SELECT name FROM lists WHERE id='backed-list'").fetchone()[0]
            == "Recover this list"
        )
        assert (
            conn.execute("SELECT count(*) FROM list_papers WHERE list_id='backed-list'").fetchone()[
                0
            ]
            == 0
        )


def test_keep_current_records_only_local_decision_without_dropping_original_bound_note(populated):
    old, _source, _change, path, _operation = populated
    operation = old.new_graph_operation(
        "note",
        str(uuid4()),
        dict(
            paper_id=PAPER,
            body="Source-linked note",
            kind="note",
            created_at=STAMP,
            page=1,
            anchor=None,
        ),
    )
    old.save(operation)
    observed, change = select(populated, operation)
    before = dump(old.journal.path)
    with pytest.raises(ValueError, match="parent/source"):
        choices.prepare(observed, change, "add", str(uuid4()))
    plan = choices.prepare(observed, change, "keep", str(uuid4()))
    result = plan.apply()
    assert result["state"] == "kept_current" and not result["applied"]
    assert not result["source_discarded"] and not result["originals_verified"]
    assert result["operation_id"] is None and result["sequence"] is None
    assert attached(path).journal.pending() == [] and dump(old.journal.path) == before
    assert saved_metadata(path)[1] == 1 and plan.apply()["request_reused"]


@pytest.mark.parametrize("failure", ["exception", "cancel"])
def test_receipt_failure_after_native_write_rolls_back_both_and_retries_with_same_id(
    populated,
    monkeypatch,
    failure,
):
    old, _source, _change, path, _operation = populated
    operation = old.new_graph_operation(
        "list", "backed-list", dict(name="Atomic update", note=None)
    )
    old.save(operation)
    observed, change = select(populated, operation)
    request = str(uuid4())
    plan = choices.prepare(observed, change, "replace", request)
    original = choices._write_receipt
    written = []

    def fail(*args):
        original(*args)
        written.append(True)
        if failure == "exception":
            raise RuntimeError("fixture receipt failure")

    monkeypatch.setattr(choices, "_write_receipt", fail)
    before = dump(path)
    with pytest.raises(RuntimeError if failure == "exception" else BackupCancelled):
        plan.apply(cancelled=lambda: failure == "cancel" and bool(written))
    assert written and dump(path) == before and attached(path).journal.pending() == []
    monkeypatch.setattr(choices, "_write_receipt", original)
    again = choices.prepare(target.observe(observed.source, path), change, "replace", request)
    assert again.apply()["applied"] and saved_metadata(path)[1] == 1


def test_same_request_for_identical_payload_from_distinct_old_operations_is_rejected(populated):
    old, _source, _change, path, _operation = populated
    operations = []
    for _ in range(2):
        operation = old.new_graph_operation(
            "list", "backed-list", dict(name="Identical content", note=None)
        )
        old.save(operation)
        operations.append(operation)
    observed, first = select(populated, operations[0])
    second = next(
        row["change_id"]
        for row in observed.source.page()["items"]
        if row["operation_id"] == operations[1]["operation_id"]
    )
    request = str(uuid4())
    plans = [choices.prepare(observed, change, "replace", request) for change in (first, second)]
    plans[0].apply()
    before = dump(path)
    with pytest.raises(ValueError, match="different decision or source"):
        plans[1].apply()
    with pytest.raises(ValueError, match="different decision or source"):
        choices.prepare(target.observe(observed.source, path), second, "replace", request)
    assert dump(path) == before and len(attached(path).journal.pending()) == 1


def test_stale_target_and_forged_decision_cannot_overwrite_current_work(populated):
    old, _source, _change, path, _operation = populated
    operation = old.new_graph_operation(
        "list", "backed-list", dict(name="Older interpretation", note=None)
    )
    old.save(operation)
    observed, change = select(populated, operation)
    plan = choices.prepare(observed, change, "replace", str(uuid4()))
    with pytest.raises(ValueError, match="original prepared"):
        replace(plan, receipt_json="{}").apply()
    client = attached(path)
    client.save(
        client.new_graph_operation(
            "list", "backed-list", dict(name="New target interpretation", note=None)
        )
    )
    before = dump(path)
    with pytest.raises(ValueError, match="target changed"):
        plan.apply()
    assert dump(path) == before and saved_metadata(path)[0][0] == "New target interpretation"


def test_changed_order_members_are_not_silently_dropped(populated):
    old, _source, _change, path, _operation = populated
    operation = old.new_order_operation(
        "workspace_list_order", "workspace-lists", ["second-list", "backed-list"]
    )
    old.save(operation)
    client = attached(path)
    client.save(
        client.new_graph_operation("list", "added-on-mac", dict(name="Mac-only list", note=None))
    )
    observed, change = select(populated, operation)
    before = dump(path)
    with pytest.raises(ValueError):
        choices.prepare(observed, change, "replace", str(uuid4()))
    assert dump(path) == before and len(client.journal.pending()) == 1


def test_missing_application_receipt_schema_is_not_created_during_prepare(populated):
    old, _source, _change, path, operation = populated
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("DROP TABLE integration_operations")
    observed, change = select(populated, operation)
    before = dump(path)
    with pytest.raises(ValueError, match="existing native application schema"):
        choices.prepare(observed, change, "keep", str(uuid4()))
    assert dump(path) == before


@pytest.mark.parametrize("choice", ["replace", "keep"])
def test_corrupt_saved_provenance_cannot_be_reused_as_a_recovery_decision(populated, choice):
    old, _source, _change, path, _operation = populated
    operation = old.new_graph_operation(
        "list", "backed-list", dict(name="Verified old source", note=None)
    )
    old.save(operation)
    observed, change = select(populated, operation)
    request = str(uuid4())
    plan = choices.prepare(observed, change, choice, request)
    plan.apply()
    with closing(sqlite3.connect(path)) as conn:
        original = conn.execute(
            "SELECT result FROM integration_operations WHERE id=?", (request,)
        ).fetchone()[0]
    for field, value in [
        ("source_workspace_id", "another-workspace"),
        ("source_device_id", "another-device"),
        ("workspace_id", "another-target-workspace"),
        ("device_id", "another-target-device"),
        ("source_operation_id", "another-source-operation"),
        ("source_fingerprint", "0" * 64),
        ("entity_id", "another-list"),
        ("choice", []),
    ]:
        modified = json.loads(original)
        modified[field] = value
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute(
                "UPDATE integration_operations SET result=? WHERE id=?",
                (json.dumps(modified), request),
            )
        current = target.observe(observed.source, path)
        before = dump(path)
        with pytest.raises(ValueError):
            choices.prepare(current, change, choice, request)
        with pytest.raises(ValueError):
            plan.apply()
        assert dump(path) == before
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute(
                "UPDATE integration_operations SET result=? WHERE id=?", (original, request)
            )
    assert plan.apply()["request_reused"]


def new_list_membership(data):
    old = data[0]
    root = old.new_graph_operation(
        "list", "new-recovery-list", dict(name="New research list", note=None)
    )
    old.save(root)
    member = membership_id(root["entity_id"], PAPER)
    child = old.new_graph_operation(
        "membership",
        member,
        dict(
            list_id=root["entity_id"],
            paper_id=PAPER,
            citation=None,
            added_at=STAMP,
        ),
    )
    old.save(child)
    return root, child


def recover(data, operation, choice="add"):
    observed, change = select(data, operation)
    return choices.prepare(observed, change, choice, str(uuid4())).apply()


def test_receipt_proven_new_list_preserves_membership_reading_and_both_orders(
    request, monkeypatch, tmp_path_factory
):
    hosted = capture_recovered_authority(monkeypatch)
    populated = request.getfixturevalue("populated")
    old, _source, _change, path, _operation = populated
    root, child = new_list_membership(populated)
    reading = old.new_graph_operation(
        "reading_state",
        child["entity_id"],
        dict(
            list_id=root["entity_id"],
            paper_id=PAPER,
            state="read",
            delivered_at=None,
            read_at=STAMP,
        ),
    )
    old.save(reading)
    order = old.new_order_operation("list_order", root["entity_id"], [child["entity_id"]])
    old.save(order)
    lists = old.new_order_operation(
        "workspace_list_order", "workspace-lists", [root["entity_id"], "backed-list", "second-list"]
    )
    old.save(lists)
    before = dump(old.journal.path)
    recover(populated, root)
    for operation, choice in ((child, "add"), (reading, "add"), (order, "add"), (lists, "replace")):
        assert recover(populated, operation, choice)["applied"]
    pending = attached(path).journal.pending()
    assert len(pending) == 5 and dump(old.journal.path) == before
    assert [op["entity_type"] for op in pending] == [
        "list",
        "membership",
        "reading_state",
        "list_order",
        "workspace_list_order",
    ]
    assert pending[1]["parents"] != child["parents"]
    assert pending[1]["payload"] == child["payload"]
    assert pending[2]["payload"] == reading["payload"]
    assert pending[3]["payload"]["items"][0]["id"] == child["entity_id"]
    assert pending[3]["payload"]["items"][0]["incarnation"] == pending[1]["incarnation"]
    assert pending[3]["payload"]["items"] != order["payload"]["items"]
    assert pending[4]["payload"]["items"][0]["incarnation"] == pending[0]["incarnation"]
    with closing(_readonly_connection(path)) as conn:
        row = conn.execute(
            "SELECT l.name FROM lists l JOIN list_papers p ON p.list_id=l.id WHERE l.id=?",
            (root["entity_id"],),
        ).fetchone()
        assert row[0] == "New research list"
    from test_workspace_sync import Native

    from paper_daily import sync_bootstrap
    from paper_daily.workspace_service import Ticket
    from paper_daily.workspace_sync import SyncSession

    service = hosted["service"]
    synced = attached(path).sync_once(service, hosted["token"])
    assert synced["pending"] == synced["conflicts"] == 0
    token = service.enroll("fresh-research", "hierarchy-peer")
    session = SyncSession(path, transport_factory=lambda url: Native(url, service, []))
    destination = tmp_path_factory.mktemp("recovery-hierarchy-peer") / "workspace"
    session.connect(
        "https://recovery.fixture.invalid", "fresh-research", "hierarchy-peer", token, Ticket()
    )
    try:
        assert sync_bootstrap.join(session, destination, Ticket())["state"] == "metadata_ready"
    finally:
        session.disconnect()
    peer = attached(destination / "papers.db")
    assert peer.journal.pending() == []
    with closing(_readonly_connection(peer.journal.path)) as conn:
        row = conn.execute(
            "SELECT l.name,p.state,p.read_at,p.position FROM lists l "
            "JOIN list_papers p ON p.list_id=l.id WHERE l.id=?",
            (root["entity_id"],),
        ).fetchone()
        assert tuple(row) == ("New research list", "read", STAMP, 0)
        raw = conn.execute(
            "SELECT operation FROM paperfact_sync_heads "
            "WHERE entity_type='workspace_list_order' AND entity_id='workspace-lists'"
        ).fetchone()[0]
        received_order = json.loads(raw)["payload"]["items"]
        assert [item["id"] for item in received_order] == [
            root["entity_id"],
            "backed-list",
            "second-list",
        ]
        assert received_order[0]["incarnation"] == pending[0]["incarnation"]
    assert dump(old.journal.path) == before


@pytest.mark.parametrize("damage", ["unrecorded", "corrupt_receipt", "recreated", "receipt_budget"])
def test_parent_mapping_requires_valid_receipt_and_current_exact_lifetime(
    populated, damage, monkeypatch
):
    _old, _source, _change, path, _operation = populated
    root, child = new_list_membership(populated)
    client = attached(path)
    if damage == "unrecorded":
        client.save(client.new_graph_operation("list", root["entity_id"], root["payload"]))
    else:
        result = recover(populated, root)
        if damage == "corrupt_receipt":
            with closing(sqlite3.connect(path)) as conn, conn:
                row = conn.execute(
                    "SELECT result FROM integration_operations WHERE id=?", (result["request_id"],)
                ).fetchone()[0]
                receipt = json.loads(row)
                receipt["source_fingerprint"] = "0" * 64
                conn.execute(
                    "UPDATE integration_operations SET result=? WHERE id=?",
                    (
                        json.dumps(receipt, sort_keys=True, separators=(",", ":")),
                        result["request_id"],
                    ),
                )
        elif damage == "receipt_budget":
            monkeypatch.setattr(choices, "MAX_RECEIPT", 1)
        else:
            client.save(client.new_graph_operation("list", root["entity_id"], {}, action="delete"))
            client.save(
                client.new_graph_operation("list", root["entity_id"], root["payload"], restore=True)
            )
    observed, change = select(populated, child)
    before = dump(path)
    with pytest.raises(ValueError):
        choices.prepare(observed, change, "add", str(uuid4()))
    assert dump(path) == before


def test_parent_proof_is_rechecked_at_apply_and_refresh_preserves_later_root_edit(populated):
    _old, _source, _change, path, _operation = populated
    root, child = new_list_membership(populated)
    recover(populated, root)
    observed, change = select(populated, child)
    decision = choices.prepare(observed, change, "add", str(uuid4()))
    client = attached(path)
    client.save(
        client.new_graph_operation(
            "list", root["entity_id"], dict(name="Later target name", note=None)
        )
    )
    before = dump(path)
    with pytest.raises(ValueError, match="target changed"):
        decision.apply()
    assert dump(path) == before
    assert recover(populated, child)["applied"]
    with closing(_readonly_connection(path)) as conn:
        row = conn.execute("SELECT name FROM lists WHERE id=?", (root["entity_id"],)).fetchone()
        assert row[0] == "Later target name"


def test_reusing_old_incarnation_without_a_recovery_receipt_does_not_prove_parent(populated):
    _old, _source, _change, path, _operation = populated
    root, child = new_list_membership(populated)
    client = attached(path)
    client.save(
        client.new_graph_operation(
            "list", root["entity_id"], root["payload"], operation_id=root["incarnation"]
        )
    )
    observed, change = select(populated, child)
    before = dump(path)
    with pytest.raises(ValueError):
        choices.prepare(observed, change, "add", str(uuid4()))
    assert dump(path) == before


def test_explicit_root_restore_preserves_historical_proofs_for_child_restore(populated):
    old, _source, _change, path, _operation = populated
    root, child = new_list_membership(populated)
    reading = old.new_graph_operation(
        "reading_state",
        child["entity_id"],
        dict(
            list_id=root["entity_id"],
            paper_id=PAPER,
            state="read",
            delivered_at=None,
            read_at=STAMP,
        ),
    )
    old.save(reading)
    order = old.new_order_operation("list_order", root["entity_id"], [child["entity_id"]])
    old.save(order)
    before = dump(old.journal.path)
    operations = (root, child, reading, order)
    for operation in operations:
        assert recover(populated, operation)["applied"]
    client = attached(path)
    client.save(client.new_graph_operation("list", root["entity_id"], {}, action="delete"))
    for operation in operations:
        assert recover(populated, operation, "restore")["applied"]
    assert len(client.journal.pending()) == 9 and dump(old.journal.path) == before
    with closing(_readonly_connection(path)) as conn:
        row = conn.execute(
            "SELECT state,read_at FROM list_papers WHERE list_id=?", (root["entity_id"],)
        ).fetchone()
        assert tuple(row) == ("read", STAMP)
