"""Reference authority checks with synthetic workspaces and no network."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from paper_daily.sync_service import ReferenceService


def operation(
    identity="op-1",
    *,
    workspace="workspace-a",
    device="device-a",
    base=0,
    predecessor=None,
    entity="note-1",
    body="Research observation",
):
    return {
        "version": 1,
        "operation_id": identity,
        "workspace_id": workspace,
        "device_id": device,
        "entity_type": "note",
        "entity_id": entity,
        "action": "put",
        "base_revision": base,
        "depends_on": predecessor,
        "payload": {"paper_id": "paper-example", "body": body},
    }


@pytest.fixture
def service(tmp_path):
    return ReferenceService(tmp_path / "service.sqlite")


def test_retry_after_restart_returns_original_event_without_reverting_newer_edit(service):
    token = service.enroll("workspace-a", "device-a")
    original = operation()
    first = service.push(token, original)
    second = service.push(token, operation("op-2", predecessor="op-1", body="Later"))
    assert first == {
        "sequence": 1,
        "outcome": "accepted",
        "operation": original,
        "head": {"revision": 1, "operation": original},
    }
    restarted = ReferenceService(service.path)
    assert restarted.push(token, original) == first
    assert restarted.pull(token) == [first, second]
    assert restarted.pull(token, after=1) == [second]
    assert restarted.pull(token, after=2) == []
    with pytest.raises(ValueError, match="reused"):
        restarted.push(token, operation(body="Changed retry"))
    assert restarted.pull(token)[-1]["head"]["operation"]["payload"]["body"] == "Later"


def test_conflicts_preserve_both_versions_and_explicit_resolution(service):
    a = service.enroll("workspace-a", "device-a")
    b = service.enroll("workspace-a", "device-b")
    service.push(a, operation())
    accepted = service.push(a, operation("op-a", base=1, body="Desktop edit"))
    conflict = service.push(b, operation("op-b", device="device-b", base=1, body="Phone edit"))
    assert conflict["outcome"] == "conflict"
    assert conflict["operation"]["payload"]["body"] == "Phone edit"
    assert conflict["head"] == accepted["head"]
    resolved = service.push(
        b, operation("resolve", device="device-b", base=2, body="Desktop and phone observations")
    )
    assert resolved["outcome"] == "accepted"
    assert [event["outcome"] for event in service.pull(a)] == [
        "accepted",
        "accepted",
        "conflict",
        "accepted",
    ]
    assert service.pull(b)[2] == conflict


def test_offline_dependency_chain_survives_conflict_and_never_overwrites_head(service):
    a = service.enroll("workspace-a", "device-a")
    b = service.enroll("workspace-a", "device-b")
    service.push(a, operation())
    service.push(a, operation("a-2", predecessor="op-1", body="A second"))
    conflict = service.push(b, operation("b-1", device="device-b", body="B first"))
    child = service.push(
        b, operation("b-2", device="device-b", predecessor="b-1", body="B edited offline")
    )
    assert child["outcome"] == "conflict"
    assert child["head"] == conflict["head"]
    assert child["operation"]["payload"]["body"] == "B edited offline"
    assert child["sequence"] > conflict["sequence"]


def test_deletion_retains_tombstone_and_stale_edit_is_preserved_as_conflict(service):
    token = service.enroll("workspace-a", "device-a")
    service.push(token, operation())
    delete = operation("delete", base=1)
    delete.update(action="delete", payload={})
    removed = service.push(token, delete)
    stale = service.push(token, operation("stale", base=1, body="Unsynced text"))
    assert stale["outcome"] == "conflict"
    assert stale["head"] == removed["head"]
    assert stale["head"]["operation"]["action"] == "delete"
    assert stale["operation"]["payload"]["body"] == "Unsynced text"


def test_concurrent_retries_allocate_one_event(service):
    token = service.enroll("workspace-a", "device-a")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: ReferenceService(service.path).push(token, operation()), range(20))
        )
    assert all(event == results[0] for event in results)
    assert service.pull(token) == results[:1]


def test_concurrent_edits_accept_one_and_keep_other(service):
    a = service.enroll("workspace-a", "device-a")
    b = service.enroll("workspace-a", "device-b")
    pairs = [(a, operation("a", body="A")), (b, operation("b", device="device-b", body="B"))]
    with ThreadPoolExecutor(max_workers=2) as pool:
        events = list(pool.map(lambda pair: service.push(*pair), pairs))
    assert sorted(e["outcome"] for e in events) == ["accepted", "conflict"]
    assert {e["operation"]["payload"]["body"] for e in service.pull(a)} == {"A", "B"}


def test_workspace_and_device_authorization_is_checked_before_retry(service):
    a = service.enroll("workspace-a", "device-a")
    other_device = service.enroll("workspace-a", "device-b")
    other_workspace = service.enroll("workspace-b", "device-a")
    service.push(a, operation())
    for token in (other_device, other_workspace):
        with pytest.raises(PermissionError):
            service.push(token, operation())
    assert service.pull(other_workspace) == []
    other = service.push(other_workspace, operation(workspace="workspace-b", body="Other data"))
    assert other["sequence"] == 1
    assert service.pull(a)[0]["operation"]["payload"]["body"] == "Research observation"
    assert service.pull(other_device) == service.pull(a)


def test_revocation_blocks_reads_and_identical_replay_after_restart(service):
    token = service.enroll("workspace-a", "device-a")
    service.push(token, operation())
    service.revoke(token)
    service.revoke(token)
    restarted = ReferenceService(service.path)
    with pytest.raises(PermissionError):
        restarted.pull(token)
    with pytest.raises(PermissionError):
        restarted.push(token, operation())
    with pytest.raises(ValueError, match="already enrolled"):
        restarted.enroll("workspace-a", "device-a")
    replacement = restarted.enroll("workspace-a", "replacement")
    assert len(restarted.pull(replacement)) == 1


def test_duplicate_enrollment_keeps_original_credential_and_stores_hash_only(service):
    token = service.enroll("workspace-a", "device-a")
    with pytest.raises(ValueError, match="already enrolled"):
        service.enroll("workspace-a", "device-a")
    assert service.pull(token) == []
    with sqlite3.connect(service.path) as conn:
        rows = conn.execute("SELECT * FROM sync_devices").fetchall()
    assert len(rows) == 1
    assert token not in str(rows)
    assert token.encode() not in service.path.read_bytes()


@pytest.mark.parametrize("token", ["", "unknown", None, 123, "x" * 4097])
def test_invalid_credentials_cannot_read_or_mutate(service, token):
    with pytest.raises(PermissionError):
        service.pull(token)
    with pytest.raises(PermissionError):
        service.push(token, operation())


@pytest.mark.parametrize(
    "update",
    [
        {"depends_on": "missing"},
        {"depends_on": "op-1", "entity_id": "another-note"},
        {"depends_on": "op-1", "device_id": "device-b"},
    ],
)
def test_missing_or_unrelated_predecessor_has_no_event(service, update):
    a = service.enroll("workspace-a", "device-a")
    b = service.enroll("workspace-a", "device-b")
    original = service.push(a, operation())
    next_op = operation("op-2") | update
    token = b if next_op["device_id"] == "device-b" else a
    with pytest.raises(ValueError):
        service.push(token, next_op)
    assert service.pull(a) == [original]


@pytest.mark.parametrize(
    "update",
    [
        {"version": 2},
        {"base_revision": -1},
        {"entity_type": "credentials"},
        {"unexpected": "not allowed"},
        {"payload": {"paper_id": "paper-example", "body": "x" * (256 * 1024)}},
    ],
)
def test_invalid_payload_writes_nothing(service, update):
    token = service.enroll("workspace-a", "device-a")
    with pytest.raises(ValueError):
        service.push(token, operation() | update)
    assert service.pull(token) == []


@pytest.mark.parametrize("after,limit", [(-1, 1), (True, 1), (1, 1), (0, 0), (0, 1001), (0, True)])
def test_cursor_and_batch_bounds(service, after, limit):
    token = service.enroll("workspace-a", "device-a")
    with pytest.raises(ValueError):
        service.pull(token, after, limit)


def test_bounded_page_and_returned_data_are_detached(service):
    token = service.enroll("workspace-a", "device-a")
    first = service.push(token, operation())
    second = service.push(token, operation("second", entity="note-2"))
    page = service.pull(token, limit=1)
    assert page == [first]
    page[0]["operation"]["payload"]["body"] = "Mutated consumer copy"
    assert service.pull(token) == [first, second]


def test_receipt_failure_rolls_back_head_and_sequence(service):
    token = service.enroll("workspace-a", "device-a")
    with sqlite3.connect(service.path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_event BEFORE INSERT ON sync_events "
            "BEGIN SELECT RAISE(ABORT, 'disk failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="disk failure"):
        service.push(token, operation())
    assert service.pull(token) == []
    with sqlite3.connect(service.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sync_heads").fetchone()[0] == 0
        conn.execute("DROP TRIGGER reject_event")
    assert service.push(token, operation())["sequence"] == 1


def test_stale_create_without_existing_head_is_retained_as_conflict(service):
    token = service.enroll("workspace-a", "device-a")
    result = service.push(token, operation(base=99))
    assert result["outcome"] == "conflict"
    assert result["head"] == {"revision": 0, "operation": None}
    assert service.pull(token) == [result]


def test_resolution_link_is_validated_and_accepted_resolution_retains_conflict_history(service):
    a = service.enroll("workspace-a", "device-a")
    b = service.enroll("workspace-a", "device-b")
    service.push(a, operation())
    conflict = service.push(b, operation("conflict", device="device-b", body="Alternate"))
    resolution = operation("resolve", device="device-b", base=1, body="Merged")
    resolution["resolution_of"] = "conflict"
    accepted = service.push(b, resolution)
    assert accepted["outcome"] == "accepted"
    assert service.push(b, resolution) == accepted
    assert service.pull(a)[1] == conflict


@pytest.mark.parametrize(
    "target,entity", [("missing", "note-1"), ("op-1", "note-1"), ("conflict", "another-note")]
)
def test_resolution_requires_existing_conflict_for_same_entity(service, target, entity):
    token = service.enroll("workspace-a", "device-a")
    service.push(token, operation())
    service.push(token, operation("conflict", body="Alternate"))
    resolution = operation("resolve", base=1, entity=entity)
    resolution["resolution_of"] = target
    with pytest.raises(ValueError, match="Resolution"):
        service.push(token, resolution)
    assert len(service.pull(token)) == 2
