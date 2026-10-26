"""Private v2 graph semantics with fixture workspaces and persisted service metadata."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from paper_daily.sync_graph import apply_accepted, check_preconditions
from paper_daily.sync_journal import canonical_operation
from paper_daily.sync_schema_v2 import membership_id
from paper_daily.sync_service import ReferenceService

PAPER = "00000000-0000-0000-0000-000000000001"


def paper_payload():
    return {
        "title": "Synthetic research",
        "authors": ["Example Author"],
        "year": 2026,
        "venue": None,
        "abstract": None,
        "doi": None,
        "arxiv_id": None,
        "s2_id": None,
        "page_url": None,
        "pdf_url": None,
        "source": "fixture",
    }


def operation(
    identity,
    kind="list",
    *,
    entity=None,
    incarnation=None,
    base=0,
    structure=0,
    parents=None,
    payload=None,
    action="put",
    device="a",
):
    if entity is None:
        entity = PAPER if kind == "paper" else "list-1"
    if payload is None:
        payload = paper_payload() if kind == "paper" else {"name": "Reading", "note": ""}
    return {
        "version": 2,
        "operation_id": identity,
        "workspace_id": "workspace",
        "device_id": device,
        "entity_type": kind,
        "entity_id": entity,
        "action": action,
        "base_revision": base,
        "depends_on": None,
        "payload": payload,
        "incarnation": incarnation or identity,
        "parents": parents or [],
        "structure_revision": structure,
    }


def refs(list_inc="list-create", paper_inc="paper-create"):
    return [
        {"kind": "list", "id": "list-1", "incarnation": list_inc},
        {"kind": "paper", "id": PAPER, "incarnation": paper_inc},
    ]


def member(identity="member-create", **kwargs):
    payload = {
        "list_id": "list-1",
        "paper_id": PAPER,
        "citation": None,
        "added_at": "2026-10-26T12:00:00+00:00",
    }
    return operation(
        identity,
        "membership",
        entity=membership_id("list-1", PAPER),
        parents=kwargs.pop("parents", refs()),
        payload=kwargs.pop("payload", payload),
        **kwargs,
    )


def deletion(identity="delete-list", **kwargs):
    return operation(identity, action="delete", payload={}, incarnation="list-create", **kwargs)


def graph(service, kind, identity):
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
    service.push(a, operation("list-create"))
    service.push(a, operation("paper-create", "paper"))
    return service, a, b


def test_paper_and_membership_contract_preserves_v1_and_explicit_identity(ready):
    service, a, _ = ready
    created = service.push(a, member())
    assert created["outcome"] == "accepted"
    assert graph(service, "list", "list-1")["structure_revision"] == 3
    assert graph(service, "paper", PAPER)["structure_revision"] == 3
    assert graph(service, "membership", membership_id("list-1", PAPER)) == {
        "incarnation": "member-create",
        "structure_revision": 3,
        "active": True,
        "parents": refs(),
    }
    assert service.push(a, member()) == created
    assert ReferenceService(service.path).pull(a)[-1] == created


def test_parent_rename_does_not_invalidate_child_or_change_structural_marker(ready):
    service, a, _ = ready
    renamed = operation(
        "rename", incarnation="list-create", base=1, payload={"name": "New name", "note": ""}
    )
    service.push(a, renamed)
    assert graph(service, "list", "list-1")["structure_revision"] == 1
    child = service.push(a, member())
    assert child["outcome"] == "accepted"
    assert graph(service, "list", "list-1")["structure_revision"] == child["sequence"]


def test_missing_parent_is_retryable_without_allocating_event(tmp_path):
    service = ReferenceService(tmp_path / "authority.sqlite")
    a = service.enroll("workspace", "a")
    with pytest.raises(ValueError, match="Missing graph parent"):
        service.push(a, member())
    assert service.pull(a) == []
    service.push(a, operation("list-create"))
    service.push(a, operation("paper-create", "paper"))
    assert service.push(a, member())["outcome"] == "accepted"


def test_parent_delete_wins_then_child_edit_is_preserved(ready):
    service, a, b = ready
    removed = service.push(a, deletion(base=1, structure=1))
    conflicted = service.push(b, member(device="b"))
    assert removed["outcome"] == "accepted"
    assert conflicted["outcome"] == "conflict"
    assert conflicted["operation"]["payload"]["paper_id"] == PAPER
    assert graph(service, "membership", member()["entity_id"]) is None
    assert not graph(service, "list", "list-1")["active"]


def test_child_edit_wins_then_stale_parent_delete_is_preserved(ready):
    service, a, b = ready
    child = service.push(b, member(device="b"))
    stale_delete = service.push(a, deletion(base=1, structure=1))
    assert child["outcome"] == "accepted"
    assert stale_delete["outcome"] == "conflict"
    assert graph(service, "list", "list-1")["active"]
    assert stale_delete["operation"]["action"] == "delete"


def test_concurrent_delete_and_child_create_accept_one_and_keep_other(ready):
    service, a, b = ready
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda pair: service.push(*pair)["outcome"],
                [(a, deletion(base=1, structure=1)), (b, member(device="b"))],
            )
        )
    assert sorted(outcomes) == ["accepted", "conflict"]
    assert len(service.pull(a)) == 4


def test_offline_create_child_delete_uses_structural_predecessor(ready):
    service, a, _ = ready
    child = service.push(a, member())
    remove = deletion(base=0)
    remove.update(depends_on="list-create", structure_depends_on="member-create")
    accepted = service.push(a, remove)
    assert accepted["outcome"] == "accepted"
    assert accepted["sequence"] > child["sequence"]
    assert not graph(service, "list", "list-1")["active"]
    assert graph(service, "membership", member()["entity_id"])["active"]


def test_structural_predecessor_does_not_override_a_later_child_edit(ready):
    service, a, b = ready
    service.push(a, member())
    changed = member("member-edit", incarnation="member-create", base=3, device="b")
    changed["payload"]["citation"] = "Updated on another device"
    service.push(b, changed)
    remove = deletion(base=1)
    remove["structure_depends_on"] = "member-create"
    assert service.push(a, remove)["outcome"] == "conflict"


@pytest.mark.parametrize("dependency", ["paper-create", "rename", "missing"])
def test_invalid_structural_predecessor_cannot_authorize_delete(ready, dependency):
    service, a, _ = ready
    service.push(a, operation("rename", incarnation="list-create", base=1))
    remove = deletion(base=3)
    remove["structure_depends_on"] = dependency
    with pytest.raises(ValueError, match="structural predecessor"):
        service.push(a, remove)
    assert len(service.pull(a)) == 3


def test_parent_restore_requires_new_incarnation_and_old_child_conflicts(ready):
    service, a, b = ready
    service.push(a, member())
    service.push(a, deletion(base=1, structure=3))
    stale_restore = operation("old-restore", incarnation="list-create", base=4)
    assert service.push(a, stale_restore)["outcome"] == "conflict"
    restored = service.push(a, operation("list-restored", base=4))
    assert restored["outcome"] == "accepted"
    stale_child = member("old-child", incarnation="member-create", base=3, device="b")
    assert service.push(b, stale_child)["outcome"] == "conflict"
    new_child = member("member-restored", parents=refs(list_inc="list-restored"), base=3)
    assert service.push(a, new_child)["outcome"] == "accepted"
    assert graph(service, "membership", member()["entity_id"])["incarnation"] == "member-restored"


def test_retirement_resolution_under_deleted_parent_does_not_resurrect_parent(ready):
    service, a, b = ready
    service.push(a, member())
    service.push(a, deletion(base=1, structure=3))
    conflicted = member("old-child", incarnation="member-create", base=3, device="b")
    service.push(b, conflicted)
    retire = member(
        "retire",
        incarnation="member-create",
        base=3,
        structure=3,
        action="delete",
        payload={},
        device="b",
    )
    retire["resolution_of"] = "old-child"
    assert service.push(b, retire)["outcome"] == "accepted"
    assert not graph(service, "membership", member()["entity_id"])["active"]
    assert not graph(service, "list", "list-1")["active"]
    assert graph(service, "list", "list-1")["structure_revision"] == 4


def test_retirement_does_not_touch_restored_parent_incarnation(ready):
    service, a, b = ready
    service.push(a, member())
    service.push(a, deletion(base=1, structure=3))
    service.push(a, operation("new-list", base=4))
    service.push(b, member("obsolete", incarnation="member-create", base=3, device="b"))
    before = graph(service, "list", "list-1")
    retire = member(
        "retire",
        incarnation="member-create",
        base=3,
        structure=3,
        action="delete",
        payload={},
        device="b",
    )
    retire["resolution_of"] = "obsolete"
    assert service.push(b, retire)["outcome"] == "accepted"
    assert graph(service, "list", "list-1") == before


@pytest.mark.parametrize("wrong", ["incarnation", "parents"])
def test_retirement_cannot_retarget_or_change_child_incarnation(ready, wrong):
    service, a, b = ready
    service.push(a, member())
    service.push(a, deletion(base=1, structure=3))
    service.push(b, member("obsolete", incarnation="member-create", base=3, device="b"))
    retire = member(
        "retire",
        incarnation="member-create",
        base=3,
        structure=3,
        action="delete",
        payload={},
        device="b",
    )
    retire["resolution_of"] = "obsolete"
    if wrong == "incarnation":
        retire["incarnation"] = "retire"
    else:
        retire["parents"][0]["incarnation"] = "different-list"
    assert service.push(b, retire)["outcome"] == "conflict"
    assert graph(service, "membership", member()["entity_id"])["active"]


def test_absent_child_conflict_can_be_retired_using_original_incarnation(ready):
    service, a, b = ready
    service.push(a, deletion(base=1, structure=1))
    service.push(b, member(device="b"))
    retire = member("retire", incarnation="member-create", action="delete", payload={}, device="b")
    retire["resolution_of"] = "member-create"
    assert service.push(b, retire)["outcome"] == "accepted"
    assert not graph(service, "membership", member()["entity_id"])["active"]


def test_v1_upgrade_preserves_existing_head_and_prevents_downgrade(tmp_path):
    service = ReferenceService(tmp_path / "authority.sqlite")
    token = service.enroll("workspace", "a")
    legacy = operation("legacy")
    legacy["version"] = 1
    for key in ("incarnation", "parents", "structure_revision"):
        del legacy[key]
    assert service.push(token, legacy)["outcome"] == "accepted"
    upgrade = operation("upgrade", base=1)
    assert service.push(token, upgrade)["outcome"] == "accepted"
    downgrade = dict(legacy, operation_id="downgrade", base_revision=2)
    with pytest.raises(ValueError, match="Version 1"):
        service.push(token, downgrade)
    assert service.push(token, legacy)["sequence"] == 1


def test_v1_note_cannot_bypass_graphed_paper_parent(ready):
    service, a, _ = ready
    legacy = operation(
        "legacy-note", "note", entity="note-1", payload={"paper_id": PAPER, "body": "X"}
    )
    legacy["version"] = 1
    for key in ("incarnation", "parents", "structure_revision"):
        del legacy[key]
    with pytest.raises(ValueError, match="Version 1"):
        service.push(a, legacy)


def test_wrong_workspace_never_reuses_graph_parent(ready):
    service, _, _ = ready
    other = service.enroll("other", "a")
    with pytest.raises(PermissionError):
        service.push(other, member())
    isolated = member()
    isolated["workspace_id"] = "other"
    with pytest.raises(ValueError, match="Missing graph parent"):
        service.push(other, isolated)
    assert service.pull(other) == []


def test_receipt_failure_rolls_back_graph_and_head(ready):
    service, a, _ = ready
    before = graph(service, "list", "list-1")
    with sqlite3.connect(service.path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_graph_event BEFORE INSERT ON sync_events "
            "BEGIN SELECT RAISE(ABORT,'storage failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="storage failure"):
        service.push(a, member())
    assert graph(service, "list", "list-1") == before
    assert graph(service, "membership", member()["entity_id"]) is None
    assert len(service.pull(a)) == 2


def test_shared_graph_helpers_do_not_mutate_inputs_and_match_service(ready):
    service, a, _ = ready
    events = service.pull(a)
    state, receipts = {}, {}

    def get(kind, identity):
        return state.get((kind, identity))

    def put(kind, identity, value):
        state[(kind, identity)] = value

    for event in events:
        value = copy.deepcopy(event["operation"])
        before = copy.deepcopy(value)
        assert check_preconditions(get, receipts.get, value)
        apply_accepted(get, put, value, event["sequence"])
        receipts[value["operation_id"]] = event
        assert value == before
    old_root = copy.deepcopy(state[("list", "list-1")])
    event = service.push(a, member())
    assert check_preconditions(get, receipts.get, event["operation"])
    apply_accepted(get, put, event["operation"], event["sequence"])
    assert old_root["structure_revision"] == 1
    assert state[("list", "list-1")] == graph(service, "list", "list-1")


@pytest.mark.parametrize(
    "change",
    [
        {"entity_id": "not-a-uuid"},
        {"action": "delete", "payload": {}},
        {"structure_revision": True},
        {"incarnation": "../escape"},
        {"parents": [{"kind": "list", "id": "other", "incarnation": "x"}]},
    ],
)
def test_invalid_paper_graph_contract(change):
    with pytest.raises(ValueError):
        canonical_operation(operation("paper-create", "paper") | change)


@pytest.mark.parametrize(
    "key,value",
    [
        ("title", " "),
        ("authors", "not-an-array"),
        ("year", True),
        ("pdf_url", "file:///local.pdf"),
        ("page_url", "https://name:pass@example.org/paper"),
        ("extra", "not allowed"),
    ],
)
def test_paper_payload_is_closed_and_bounded(key, value):
    op = operation("paper-create", "paper")
    op["payload"][key] = value
    with pytest.raises(ValueError):
        canonical_operation(op)


@pytest.mark.parametrize("change", ["wrong-id", "wrong-parent", "missing-parent", "date"])
def test_membership_payload_and_parent_identity_agree(change):
    op = member()
    if change == "wrong-id":
        op["entity_id"] = PAPER
    elif change == "wrong-parent":
        op["payload"]["list_id"] = "other"
    elif change == "missing-parent":
        op["parents"].pop()
    else:
        op["payload"]["added_at"] = "2026-10-26"
    with pytest.raises(ValueError):
        canonical_operation(op)


def test_note_parent_and_payload_must_match_and_edits_touch_paper_structure(ready):
    service, a, _ = ready
    note = operation(
        "note-create",
        "note",
        entity="note-1",
        parents=[refs()[1]],
        payload={"paper_id": PAPER, "body": "Observation"},
    )
    result = service.push(a, note)
    assert result["outcome"] == "accepted"
    assert graph(service, "paper", PAPER)["structure_revision"] == result["sequence"]
    changed = copy.deepcopy(note)
    changed["operation_id"] = "note-change"
    changed["payload"]["paper_id"] = "00000000-0000-0000-0000-000000000002"
    with pytest.raises(ValueError, match="paper parent"):
        service.push(a, changed)


def test_legacy_note_delete_checks_its_previous_paper_parent(tmp_path):
    service = ReferenceService(tmp_path / "authority.sqlite")
    token = service.enroll("workspace", "a")
    legacy = operation(
        "legacy-note", "note", entity="note-1", payload={"paper_id": PAPER, "body": "Existing note"}
    )
    legacy["version"] = 1
    for key in ("incarnation", "parents", "structure_revision"):
        del legacy[key]
    service.push(token, legacy)
    service.push(token, operation("paper-create", "paper"))
    remove = dict(
        legacy, operation_id="legacy-delete", action="delete", payload={}, base_revision=1
    )
    with pytest.raises(ValueError, match="Version 1"):
        service.push(token, remove)
    assert len(service.pull(token)) == 2


@pytest.mark.parametrize("reverse", [False, True])
def test_missing_parent_error_does_not_depend_on_parent_order(tmp_path, reverse):
    service = ReferenceService(tmp_path / "authority.sqlite")
    token = service.enroll("workspace", "a")
    service.push(token, operation("list-create"))
    service.push(token, deletion(base=1, structure=1))
    pending = member()
    if reverse:
        pending["parents"].reverse()
    with pytest.raises(ValueError, match="Missing graph parent"):
        service.push(token, pending)
    assert len(service.pull(token)) == 2
    assert graph(service, "membership", pending["entity_id"]) is None


def test_membership_added_at_is_immutable_until_explicit_new_incarnation(ready):
    service, a, _ = ready
    first = service.push(a, member())
    changed = member("edit", incarnation="member-create", base=first["sequence"])
    changed["payload"]["citation"] = "Updated explanation"
    changed["payload"]["added_at"] = "2026-11-01T12:00:00+00:00"
    before = service.pull(a), graph(service, "list", "list-1")
    with pytest.raises(ValueError, match="added_at is immutable"):
        service.push(a, changed)
    assert (service.pull(a), graph(service, "list", "list-1")) == before
    changed["payload"]["added_at"] = first["operation"]["payload"]["added_at"]
    accepted = service.push(a, changed)
    assert accepted["outcome"] == "accepted"
    removed = member(
        "remove-member",
        incarnation="member-create",
        base=accepted["sequence"],
        structure=first["sequence"],
        action="delete",
        payload={},
    )
    removed_event = service.push(a, removed)
    restored = member("restore-member", base=removed_event["sequence"])
    restored["payload"]["added_at"] = "2026-11-02T12:00:00+00:00"
    assert service.push(a, restored)["outcome"] == "accepted"


def test_immutable_membership_time_uses_creation_receipt_not_latest_edit(ready):
    service, a, _ = ready
    first = service.push(a, member())
    edit = member("edit-one", incarnation="member-create", base=first["sequence"])
    edit["payload"]["citation"] = "First revision"
    accepted = service.push(a, edit)
    later = member("edit-two", incarnation="member-create", base=accepted["sequence"])
    later["payload"]["citation"] = "Second revision"
    assert service.push(a, later)["outcome"] == "accepted"
    assert (
        service.pull(a)[-1]["operation"]["payload"]["added_at"]
        == first["operation"]["payload"]["added_at"]
    )
