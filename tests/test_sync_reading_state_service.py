"""Reading-state service behavior uses isolated authority databases only."""

import copy
import itertools
import json
import sqlite3

import pytest

from paper_daily.sync_graph import apply_accepted, check_preconditions
from paper_daily.sync_journal import canonical_operation
from paper_daily.sync_schema_v2 import membership_id
from paper_daily.sync_service import ReferenceService

PAPER = "00000000-0000-0000-0000-000000000001"
MEMBER = membership_id("list", PAPER)
STAMP = "2026-10-26T12:00:00+00:00"


def ref(kind, identity, incarnation):
    return {"kind": kind, "id": identity, "incarnation": incarnation}


def roots(list_inc="list-create"):
    return [ref("list", "list", list_inc), ref("paper", PAPER, "paper-create")]


def op(
    identity,
    kind,
    entity,
    payload,
    *,
    parents=None,
    incarnation=None,
    base=0,
    structure=0,
    action="put",
    device="a",
):
    return {
        "version": 2,
        "operation_id": identity,
        "workspace_id": "workspace",
        "device_id": device,
        "entity_type": kind,
        "entity_id": entity,
        "action": action,
        "payload": payload,
        "base_revision": base,
        "depends_on": None,
        "incarnation": incarnation or identity,
        "parents": parents or [],
        "structure_revision": structure,
    }


def member(identity="member-create", *, list_inc="list-create", **kwargs):
    return op(
        identity,
        "membership",
        MEMBER,
        kwargs.pop(
            "payload", {"list_id": "list", "paper_id": PAPER, "citation": None, "added_at": STAMP}
        ),
        parents=roots(list_inc),
        **kwargs,
    )


def reading(
    identity="reading-create", *, member_inc="member-create", list_inc="list-create", **kwargs
):
    return op(
        identity,
        "reading_state",
        MEMBER,
        kwargs.pop(
            "payload",
            {
                "list_id": "list",
                "paper_id": PAPER,
                "state": "pending",
                "delivered_at": None,
                "read_at": None,
            },
        ),
        parents=[ref("membership", MEMBER, member_inc), *roots(list_inc)],
        **kwargs,
    )


def metadata(service, kind, identity):
    with sqlite3.connect(service.path) as conn:
        row = conn.execute(
            "SELECT metadata FROM sync_graph WHERE workspace='workspace' "
            "AND entity_type=? AND entity_id=?",
            (kind, identity),
        ).fetchone()
    return json.loads(row[0]) if row else None


@pytest.fixture
def ready(tmp_path):
    service = ReferenceService(tmp_path / "authority.sqlite")
    a, b = service.enroll("workspace", "a"), service.enroll("workspace", "b")
    service.push(a, op("list-create", "list", "list", {"name": "Reading", "note": ""}))
    service.push(
        a,
        op(
            "paper-create",
            "paper",
            PAPER,
            {
                "title": "Fixture",
                "authors": [],
                "year": None,
                "venue": None,
                "abstract": None,
                "doi": None,
                "arxiv_id": None,
                "s2_id": None,
                "page_url": None,
                "pdf_url": None,
                "source": None,
            },
        ),
    )
    service.push(a, member())
    return service, a, b


@pytest.mark.parametrize("state", ["pending", "delivered", "read", "skipped", "deferred"])
def test_states_round_trip_with_nullable_or_zoned_timestamps_and_retry(ready, state):
    service, a, _ = ready
    operation = reading(
        payload={
            "list_id": "list",
            "paper_id": PAPER,
            "state": state,
            "delivered_at": STAMP,
            "read_at": "2026-10-26T13:00:00Z",
        }
    )
    event = service.push(a, operation)
    assert event["outcome"] == "accepted"
    assert event["operation"]["payload"] == operation["payload"]
    restarted = ReferenceService(service.path)
    assert restarted.push(a, operation) == event
    assert restarted.pull(a)[-1] == event
    assert len(restarted.pull(a)) == 4


@pytest.mark.parametrize("parent", ["membership", "list"])
@pytest.mark.parametrize("read_first", [True, False])
def test_concurrent_parent_delete_and_read_preserve_both_versions(ready, parent, read_first):
    service, a, b = ready
    service.push(a, reading())
    edit = reading("mark-read", device="b", incarnation="reading-create", base=4)
    edit["payload"]["state"] = "read"
    edit["payload"]["read_at"] = STAMP
    if parent == "membership":
        deletion = member(
            "remove", incarnation="member-create", base=3, structure=4, action="delete", payload={}
        )
    else:
        deletion = op(
            "remove",
            "list",
            "list",
            {},
            incarnation="list-create",
            base=1,
            structure=4,
            action="delete",
        )
    first, second = ((edit, b), (deletion, a)) if read_first else ((deletion, a), (edit, b))
    assert service.push(first[1], first[0])["outcome"] == "accepted"
    conflict = service.push(second[1], second[0])
    assert conflict["outcome"] == "conflict"
    assert conflict["operation"] == second[0]
    current_read = next(
        e for e in reversed(service.pull(a)) if e["operation"]["entity_type"] == "reading_state"
    )
    assert current_read["head"]["operation"]["payload"]["state"] == (
        "read" if read_first else "pending"
    )
    parent_id = MEMBER if parent == "membership" else "list"
    assert metadata(service, parent, parent_id)["active"] is read_first


def test_each_parent_is_touched_once_without_recursive_double_updates(ready):
    service, a, _ = ready
    state = {
        (kind, identity): metadata(service, kind, identity)
        for kind, identity in [("list", "list"), ("paper", PAPER), ("membership", MEMBER)]
    }
    writes = []

    def get(kind, identity):
        return copy.deepcopy(state.get((kind, identity)))

    def put(kind, identity, value):
        writes.append((kind, identity))
        state[kind, identity] = value

    operation = reading()
    assert check_preconditions(get, lambda _: None, operation)
    apply_accepted(get, put, operation, 4)
    assert len(writes) == len(set(writes)) == 4
    assert all(value["structure_revision"] == 4 for value in state.values())
    service.push(a, operation)
    edit = reading("read", incarnation="reading-create", base=4)
    service.push(a, edit)
    assert metadata(service, "reading_state", MEMBER)["structure_revision"] == 4
    assert all(
        metadata(service, k, i)["structure_revision"] == 5
        for k, i in [("list", "list"), ("paper", PAPER), ("membership", MEMBER)]
    )


@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
def test_missing_parent_precondition_wins_over_stale_parent_in_every_order(ready, order):
    service, _, _ = ready
    state = {
        (kind, identity): metadata(service, kind, identity)
        for kind, identity in [("list", "list"), ("paper", PAPER)]
    }
    state["list", "list"]["active"] = False
    operation = reading()
    operation["parents"] = [operation["parents"][i] for i in order]
    with pytest.raises(ValueError, match="Missing graph parent"):
        check_preconditions(lambda k, i: state.get((k, i)), lambda _: None, operation)


def test_missing_membership_can_retry_after_creation_without_allocated_event(ready, tmp_path):
    seeded, a, _ = ready
    service = ReferenceService(tmp_path / "empty.sqlite")
    token = service.enroll("workspace", "a")
    for event in seeded.pull(a)[:2]:
        service.push(token, event["operation"])
    with pytest.raises(ValueError, match="Missing graph parent"):
        service.push(token, reading())
    assert len(service.pull(token)) == 2
    service.push(token, member())
    event = service.push(token, reading())
    assert event["outcome"] == "accepted"
    assert event["sequence"] == 4


def test_forged_membership_closure_rejects_identity_and_conflicts_incarnation(ready):
    service, a, _ = ready
    operation = reading()
    state = {
        (kind, identity): metadata(service, kind, identity)
        for kind, identity in [("list", "list"), ("paper", PAPER), ("membership", MEMBER)]
    }
    state["membership", MEMBER]["parents"][0]["id"] = "other-list"
    with pytest.raises(ValueError, match="root identities"):
        check_preconditions(lambda k, i: state.get((k, i)), lambda _: None, operation)
    operation["parents"][1]["incarnation"] = "invented-list-incarnation"
    conflict = service.push(a, operation)
    assert conflict["outcome"] == "conflict"
    assert conflict["head"] == {"revision": 0, "operation": None}


def test_live_root_cannot_retarget_membership_with_old_root_incarnation(ready):
    service, a, _ = ready
    service.push(
        a,
        op(
            "delete-list",
            "list",
            "list",
            {},
            incarnation="list-create",
            base=1,
            structure=3,
            action="delete",
        ),
    )
    service.push(a, op("restore-list", "list", "list", {"name": "Restored", "note": ""}, base=4))
    conflict = service.push(a, reading(list_inc="restore-list"))
    assert conflict["outcome"] == "conflict"
    assert metadata(service, "reading_state", MEMBER) is None


def test_delete_reset_requires_explicit_new_incarnation_to_restore(ready):
    service, a, _ = ready
    service.push(a, reading())
    removed = service.push(
        a,
        reading(
            "reset", incarnation="reading-create", base=4, structure=4, action="delete", payload={}
        ),
    )
    assert removed["outcome"] == "accepted"
    conflict = service.push(a, reading("silent-restore", incarnation="reading-create", base=5))
    assert conflict["outcome"] == "conflict"
    restored = service.push(a, reading("explicit-restore", base=5))
    assert restored["outcome"] == "accepted"
    assert metadata(service, "reading_state", MEMBER)["incarnation"] == "explicit-restore"
    assert metadata(service, "reading_state", MEMBER)["active"]


def test_membership_restore_requires_new_reading_incarnation_and_parent_reference(ready):
    service, a, _ = ready
    service.push(a, reading())
    service.push(
        a,
        member(
            "remove", incarnation="member-create", base=3, structure=4, action="delete", payload={}
        ),
    )
    service.push(a, member("member-restore", base=5))
    assert (
        service.push(a, reading("stale", incarnation="reading-create", base=4))["outcome"]
        == "conflict"
    )
    assert (
        service.push(
            a,
            reading("retarget", incarnation="reading-create", base=4, member_inc="member-restore"),
        )["outcome"]
        == "conflict"
    )
    restored = service.push(a, reading("reading-restore", base=4, member_inc="member-restore"))
    assert restored["outcome"] == "accepted"
    assert restored["head"]["operation"]["parents"][0]["incarnation"] == "member-restore"


@pytest.mark.parametrize("restore", [False, True])
def test_conflict_retirement_keeps_old_closure_without_touching_replacements(ready, restore):
    service, a, b = ready
    service.push(a, reading())
    service.push(
        a,
        op(
            "remove-list",
            "list",
            "list",
            {},
            incarnation="list-create",
            base=1,
            structure=4,
            action="delete",
        ),
    )
    conflict = service.push(
        b, reading("offline-read", incarnation="reading-create", base=4, device="b")
    )
    assert conflict["outcome"] == "conflict"
    if restore:
        service.push(a, op("new-list", "list", "list", {"name": "Restored", "note": ""}, base=5))
        service.push(a, member("new-member", list_inc="new-list", base=3))
    before_list = metadata(service, "list", "list")
    before_member = metadata(service, "membership", MEMBER)
    retirement = reading(
        "discard", incarnation="reading-create", base=4, structure=4, action="delete", payload={}
    )
    retirement["resolution_of"] = "offline-read"
    result = service.push(a, retirement)
    assert result["outcome"] == "accepted"
    assert not metadata(service, "reading_state", MEMBER)["active"]
    assert metadata(service, "list", "list") == before_list
    if restore:
        assert metadata(service, "membership", MEMBER) == before_member
    assert service.pull(a)[5]["operation"] == conflict["operation"]
    assert ReferenceService(service.path).push(a, retirement) == result


@pytest.mark.parametrize("change", ["own-incarnation", "root-incarnation", "member-incarnation"])
def test_retirement_cannot_forge_own_or_parent_incarnation(ready, change):
    service, a, b = ready
    service.push(a, reading())
    service.push(
        a,
        member(
            "remove", incarnation="member-create", base=3, structure=4, action="delete", payload={}
        ),
    )
    service.push(b, reading("offline", incarnation="reading-create", base=4, device="b"))
    retirement = reading(
        "discard", incarnation="reading-create", base=4, structure=4, action="delete", payload={}
    )
    retirement["resolution_of"] = "offline"
    if change == "own-incarnation":
        retirement["incarnation"] = "forged"
    elif change == "root-incarnation":
        retirement["parents"][1]["incarnation"] = "forged"
    else:
        retirement["parents"][0]["incarnation"] = "forged"
    assert service.push(a, retirement)["outcome"] == "conflict"
    assert metadata(service, "reading_state", MEMBER)["active"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("state", "unknown"),
        ("state", None),
        ("state", []),
        ("read_at", "2026-10-26"),
        ("read_at", "2026-10-26T00:00:00"),
        ("read_at", "not-a-time"),
        ("read_at", 123),
        ("read_at", "x" * 65),
        ("delivered_at", "2026-02-30T12:00:00Z"),
        ("delivered_at", False),
        ("list_id", "other"),
        ("paper_id", "other"),
        ("unknown", "value"),
    ],
)
def test_invalid_reading_payload_has_no_receipt_or_graph_mutation(ready, key, value):
    service, a, _ = ready
    operation = reading()
    operation["payload"][key] = value
    before = service.pull(a)
    with pytest.raises(ValueError):
        service.push(a, operation)
    assert service.pull(a) == before
    assert metadata(service, "reading_state", MEMBER) is None


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-field",
        "extra-parent",
        "wrong-member",
        "missing-parent",
        "delete-payload",
        "wrong-id",
    ],
)
def test_closed_reading_envelope_rejects_invalid_fields_and_parents(mutation):
    operation = reading()
    if mutation == "missing-field":
        del operation["payload"]["read_at"]
    elif mutation == "extra-parent":
        operation["parents"].append(copy.deepcopy(operation["parents"][0]))
    elif mutation == "wrong-member":
        operation["parents"][0]["id"] = PAPER
    elif mutation == "missing-parent":
        operation["parents"].pop()
    elif mutation == "delete-payload":
        operation["action"] = "delete"
    else:
        operation["entity_id"] = PAPER
    with pytest.raises(ValueError):
        canonical_operation(operation)


def test_three_parents_remain_invalid_for_other_kinds():
    operation = member()
    operation["parents"].append(ref("membership", MEMBER, "member-create"))
    with pytest.raises(ValueError, match="parent"):
        canonical_operation(operation)


def test_conflicted_initial_reading_can_be_retired_without_canonical_content(ready):
    service, a, b = ready
    service.push(
        a,
        member(
            "remove", incarnation="member-create", base=3, structure=3, action="delete", payload={}
        ),
    )
    conflict = service.push(b, reading("offline-create", device="b"))
    assert conflict["outcome"] == "conflict"
    assert conflict["head"] == {"revision": 0, "operation": None}
    retirement = reading("discard", incarnation="offline-create", action="delete", payload={})
    retirement["resolution_of"] = "offline-create"
    result = service.push(a, retirement)
    assert result["outcome"] == "accepted"
    assert not metadata(service, "reading_state", MEMBER)["active"]
    assert not metadata(service, "membership", MEMBER)["active"]
    assert ReferenceService(service.path).pull(a)[4] == conflict


@pytest.mark.parametrize("parent", ["membership", "list"])
def test_offline_read_then_parent_delete_uses_structural_predecessor(ready, parent):
    service, a, _ = ready
    service.push(a, reading())
    if parent == "membership":
        deletion = member(
            "remove", incarnation="member-create", base=3, structure=3, action="delete", payload={}
        )
    else:
        deletion = op(
            "remove",
            "list",
            "list",
            {},
            incarnation="list-create",
            base=1,
            structure=3,
            action="delete",
        )
    deletion["structure_depends_on"] = "reading-create"
    assert service.push(a, deletion)["outcome"] == "accepted"


def test_reading_state_cannot_use_another_workspace_parent_graph(ready):
    service, _, _ = ready
    other = service.enroll("other", "a")
    operation = reading()
    operation["workspace_id"] = "other"
    with pytest.raises(ValueError, match="Missing graph parent"):
        service.push(other, operation)
    assert service.pull(other) == []


@pytest.mark.parametrize("canonical_child", [False, True])
@pytest.mark.parametrize("deleted_list", [False, True])
def test_rejected_parent_lineage_retirement_is_bounded_to_its_own_child(
    ready, canonical_child, deleted_list
):
    service, a, b = ready
    existing_child = service.push(a, reading()) if canonical_child else None
    if deleted_list:
        service.push(
            a,
            op(
                "remove-list",
                "list",
                "list",
                {},
                incarnation="list-create",
                base=1,
                structure=metadata(service, "list", "list")["structure_revision"],
                action="delete",
            ),
        )

    # A competing creation has its own retained receipt but never becomes a head.
    rejected_parent = service.push(b, member("rejected-member", device="b"))
    attempted_child = reading("rejected-child", member_inc="rejected-member", device="b")
    attempted_child["payload"]["state"] = "read"
    rejected_child = service.push(b, attempted_child)
    assert rejected_parent["outcome"] == rejected_child["outcome"] == "conflict"
    keys = [("membership", MEMBER), ("list", "list"), ("paper", PAPER)]
    before = {key: metadata(service, *key) for key in keys}
    before_child = metadata(service, "reading_state", MEMBER)

    retirement = reading(
        "discard-rejected-child",
        member_inc="rejected-member",
        incarnation="rejected-child",
        device="b",
        action="delete",
        payload={},
        base=existing_child["sequence"] if existing_child else 0,
        structure=before_child["structure_revision"] if before_child else 0,
    )
    retirement["resolution_of"] = "rejected-child"
    result = service.push(b, retirement)

    # The rejected parent incarnation cannot modify the accepted membership.
    assert metadata(service, "membership", MEMBER) == before["membership", MEMBER]
    assert metadata(service, "list", "list")["active"] is not deleted_list
    if canonical_child:
        # Even an up-to-date base/structure cannot delete another incarnation.
        assert result["outcome"] == "conflict"
        assert result["head"] == existing_child["head"]
        assert metadata(service, "reading_state", MEMBER) == before_child
        assert {key: metadata(service, *key) for key in keys} == before
    else:
        assert result["outcome"] == "accepted"
        assert not metadata(service, "reading_state", MEMBER)["active"]
        assert result["head"]["operation"] == retirement
        for kind, identity in [("list", "list"), ("paper", PAPER)]:
            expected = copy.deepcopy(before[kind, identity])
            if expected["active"]:
                expected["structure_revision"] = result["sequence"]
            assert metadata(service, kind, identity) == expected

    # Discarding does not erase rejected research content or create retry events.
    restarted = ReferenceService(service.path)
    assert restarted.push(b, retirement) == result
    retained = {event["operation"]["operation_id"]: event for event in restarted.pull(a)}
    assert retained["rejected-member"] == rejected_parent
    assert retained["rejected-child"] == rejected_child
