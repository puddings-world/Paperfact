import copy
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_service import ReferenceService


def writer(conn, operation):
    key = (operation["entity_type"], operation["entity_id"])
    if operation["action"] == "delete":
        conn.execute("DELETE FROM research WHERE kind=? AND id=?", key)
    else:
        import json

        conn.execute(
            "INSERT INTO research VALUES(?,?,?) ON CONFLICT(kind,id) "
            "DO UPDATE SET body=excluded.body",
            (*key, json.dumps(operation["payload"])),
        )


def client(path, device):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research (kind TEXT,id TEXT,body TEXT,PRIMARY KEY(kind,id))"
        )
    return SyncClient(Journal(path, workspace_id="workspace", device_id=device), writer)


def saved(client, kind="note", identity="note-1"):
    import json

    with closing(sqlite3.connect(client.journal.path)) as conn, conn:
        row = conn.execute(
            "SELECT body FROM research WHERE kind=? AND id=?", (kind, identity)
        ).fetchone()
    return json.loads(row[0]) if row else None


def edit(client, body="original", identity="note-1"):
    operation = client.new_operation("note", identity, {"paper_id": "paper", "body": body})
    client.save(operation)
    return operation


@pytest.fixture
def pair(tmp_path):
    server = ReferenceService(tmp_path / "remote.sqlite")
    a, b = client(tmp_path / "a.sqlite", "a"), client(tmp_path / "b.sqlite", "b")
    return server, a, b, server.enroll("workspace", "a"), server.enroll("workspace", "b")


def test_list_and_note_converge_after_restart_and_duplicate_transfer(pair):
    server, a, b, ta, tb = pair
    first = a.new_operation("list", "list-1", {"name": "Reading", "note": ""})
    a.save(first)
    a.save(a.new_operation("list", "list-1", {"name": "Renamed", "note": "Why"}))
    edit(a)
    a = client(a.journal.path, "a")
    assert a.status()["pending"] == 3
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(b, "list", "list-1") == {"name": "Renamed", "note": "Why"}
    assert saved(a) == saved(b) == {"paper_id": "paper", "body": "original"}
    assert (
        a.status()
        == b.status()
        == {"cursor": 3, "pending": 0, "conflicts": 0, "deferred": 0, "awaiting_receipts": 0}
    )
    assert server.push(ta, first)["sequence"] == 1
    assert b.receive(server.pull(tb))["received"] == 0
    assert len(b.history()) == 3


def test_offline_concurrent_note_edits_preserve_both_versions(pair):
    server, a, b, ta, tb = pair
    edit(a)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    edit(a, "Desktop interpretation")
    edit(b, "Phone interpretation")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    assert saved(a) == saved(b) == {"paper_id": "paper", "body": "Desktop interpretation"}
    for side in (a, b):
        conflicts = side.history(conflicts_only=True)
        assert len(conflicts) == 1
        assert conflicts[0]["operation"]["payload"]["body"] == "Phone interpretation"
        assert conflicts[0]["head"]["operation"]["payload"]["body"] == "Desktop interpretation"
        assert side.status()["pending"] == 0
    assert len(client(b.journal.path, "b").history(conflicts_only=True)) == 1


def test_timeout_after_remote_commit_retries_once(pair):
    server, a, b, ta, tb = pair
    edit(a)

    class TimeoutTransport:
        def push(self, token, operation):
            server.push(token, operation)
            raise TimeoutError("reply lost")

    with pytest.raises(TimeoutError):
        a.sync_once(TimeoutTransport(), ta)
    assert a.status()["pending"] == 1
    a = client(a.journal.path, "a")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert len(b.history()) == 1
    assert saved(b) == saved(a)


def test_remote_batch_rolls_back_cursor_and_content_if_writer_fails(pair):
    server, a, b, ta, tb = pair
    edit(a)
    edit(a, "second", "note-2")
    a.sync_once(server, ta)

    def fail(conn, operation):
        writer(conn, operation)
        if operation["entity_id"] == "note-2":
            raise RuntimeError("disk failure")

    b.writer = fail
    with pytest.raises(RuntimeError):
        b.sync_once(server, tb)
    assert saved(b) is None
    assert b.history() == []
    assert b.status()["cursor"] == 0
    b.writer = writer
    b.sync_once(server, tb)
    assert saved(b)["body"] == "original"
    assert saved(b, identity="note-2")["body"] == "second"


def test_pending_local_edit_is_not_overwritten_by_pull(pair):
    server, a, b, ta, tb = pair
    edit(a)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    edit(b, "Unsent local change")
    edit(a, "Remote change")
    a.sync_once(server, ta)
    b.receive(server.pull(tb, after=b.status()["cursor"]))
    assert saved(b)["body"] == "Unsent local change"
    assert b.status()["deferred"] == 1
    b.sync_once(server, tb)
    assert saved(b)["body"] == "Remote change"
    assert (
        b.history(conflicts_only=True)[0]["operation"]["payload"]["body"] == "Unsent local change"
    )
    assert b.status()["deferred"] == 0


def test_delete_against_offline_edit_keeps_edit_as_conflict(pair):
    server, a, b, ta, tb = pair
    edit(a)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    edit(b, "Still valuable")
    a.save(a.new_operation("note", "note-1", {}, action="delete"))
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(b) is None
    assert b.history(conflicts_only=True)[0]["operation"]["payload"]["body"] == "Still valuable"


def test_conflicting_offline_chain_preserves_every_edit(pair):
    server, a, b, ta, tb = pair
    edit(a)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    edit(a, "Accepted")
    edit(b, "First offline")
    edit(b, "Second offline")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(b)["body"] == "Accepted"
    assert [event["operation"]["payload"]["body"] for event in b.history(conflicts_only=True)] == [
        "First offline",
        "Second offline",
    ]


@pytest.mark.parametrize("problem", ["gap", "changed-replay", "foreign-workspace", "wrong-head"])
def test_invalid_remote_events_do_not_change_research(pair, problem):
    server, a, b, ta, tb = pair
    edit(a)
    a.sync_once(server, ta)
    events = server.pull(tb)
    bad = copy.deepcopy(events)
    if problem == "gap":
        bad[0]["sequence"] = bad[0]["head"]["revision"] = 2
    elif problem == "changed-replay":
        b.receive(events)
        bad[0]["operation"]["payload"]["body"] = "changed"
        bad[0]["head"]["operation"] = bad[0]["operation"]
    elif problem == "foreign-workspace":
        bad[0]["operation"]["workspace_id"] = "elsewhere"
    else:
        bad[0]["head"]["operation"]["entity_id"] = "different"
    before = saved(b), b.status(), b.history()
    with pytest.raises(ValueError):
        b.receive(bad)
    assert (saved(b), b.status(), b.history()) == before


def test_repeated_activation_reports_busy_without_duplicate_jobs(pair):
    server, a, _, ta, _ = pair
    edit(a)
    entered, release = threading.Event(), threading.Event()

    class SlowTransport:
        def push(self, token, operation):
            entered.set()
            assert release.wait(5)
            return server.push(token, operation)

        def pull(self, token, **kwargs):
            return server.pull(token, **kwargs)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(a.sync_once, SlowTransport(), ta)
        try:
            assert entered.wait(5)
            assert a.sync_once(server, ta) == {"busy": True}
        finally:
            release.set()
        assert future.result()["pushed"] == 1
    assert len(server.pull(ta)) == 1


def test_revoked_token_does_not_acknowledge_pending_content(pair):
    server, a, _, ta, _ = pair
    edit(a)
    server.revoke(ta)
    with pytest.raises(PermissionError):
        a.sync_once(server, ta)
    assert a.status()["pending"] == 1
    assert saved(a)["body"] == "original"


def test_bounded_batches_eventually_converge(pair):
    server, a, b, ta, tb = pair
    for index in range(5):
        edit(a, f"note {index}", f"note-{index}")
    for _ in range(5):
        a.sync_once(server, ta, limit=2)
        b.sync_once(server, tb, limit=2)
    assert (
        a.status()
        == b.status()
        == {"cursor": 5, "pending": 0, "conflicts": 0, "deferred": 0, "awaiting_receipts": 0}
    )
    assert saved(a, identity="note-4") == saved(b, identity="note-4")


def test_acknowledged_edit_remains_causal_parent_after_failed_pull_and_restart(pair):
    server, a, _, ta, _ = pair
    first = edit(a, "First accepted edit")

    class FailedPull:
        def push(self, token, operation):
            return server.push(token, operation)

        def pull(self, token, **kwargs):
            raise TimeoutError("pull interrupted after acknowledgment")

    with pytest.raises(TimeoutError):
        a.sync_once(FailedPull(), ta)
    a = client(a.journal.path, "a")
    second = a.new_operation("note", "note-1", {"paper_id": "paper", "body": "Second edit"})
    assert second["depends_on"] == first["operation_id"]
    assert a.status()["awaiting_receipts"] == 1
    assert a.status()["pending"] == 0
    a.save(second)
    a.sync_once(server, ta)
    assert saved(a)["body"] == "Second edit"
    assert a.status()["awaiting_receipts"] == 0
    assert a.status()["conflicts"] == 0


def test_older_pull_page_never_replaces_newer_acknowledged_local_content(pair):
    server, a, _, ta, _ = pair
    edit(a, "First queued version")
    edit(a, "Latest queued version")

    class SmallPages:
        def push(self, token, operation):
            return server.push(token, operation)

        def pull(self, token, **kwargs):
            return server.pull(token, after=kwargs["after"], limit=1)

    a.sync_once(SmallPages(), ta)
    assert saved(a)["body"] == "Latest queued version"
    assert a.status() == {
        "cursor": 1,
        "pending": 0,
        "conflicts": 0,
        "deferred": 1,
        "awaiting_receipts": 1,
    }
    a = client(a.journal.path, "a")
    a.sync_once(server, ta)
    assert saved(a)["body"] == "Latest queued version"
    assert a.status()["deferred"] == a.status()["awaiting_receipts"] == 0
    assert len(a.history()) == 2


@pytest.mark.parametrize("absent", [True, False])
def test_conflict_cannot_introduce_an_unobserved_canonical_head(pair, absent):
    server, a, b, ta, tb = pair
    edit(a, "Existing canonical")
    edit(a, "Different entity", "note-2")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    identity = "never-created" if absent else "note-1"
    candidate = a.new_operation("note", identity, {"paper_id": "paper", "body": "Incoming"})
    candidate["base_revision"] = 99
    conflict = server.push(ta, candidate)
    assert conflict["outcome"] == "conflict"
    forged = copy.deepcopy(conflict)
    forged["head"]["revision"] = 2
    forged["head"]["operation"] = copy.deepcopy(server.pull(ta)[0]["operation"])
    forged["head"]["operation"]["entity_id"] = identity
    forged["head"]["operation"]["payload"]["body"] = "Never accepted"
    before = b.status(), b.history(), saved(b)
    with pytest.raises(ValueError, match="Conflict head"):
        b.receive([forged])
    assert (b.status(), b.history(), saved(b)) == before


def test_absent_canonical_head_removes_local_materialization_but_preserves_conflict(pair):
    server, a, b, ta, tb = pair
    candidate = a.new_operation("note", "note-1", {"paper_id": "paper", "body": "Keep this"})
    candidate["base_revision"] = 99
    a.save(candidate)
    assert saved(a)["body"] == "Keep this"
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(a) is saved(b) is None
    assert a.status()["deferred"] == b.status()["deferred"] == 0
    restarted = client(a.journal.path, "a")
    assert restarted.history(conflicts_only=True)[0]["operation"]["payload"]["body"] == "Keep this"
    assert restarted.history(conflicts_only=True)[0]["head"] == {"revision": 0, "operation": None}
    assert restarted.journal.pending() == []


def make_conflict(pair):
    server, a, b, ta, tb = pair
    edit(a, "Original")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    edit(a, "Desktop version")
    edit(b, "Phone version")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    return b.history(conflicts_only=True)[0]["sequence"]


@pytest.mark.parametrize(
    "choice,expected", [("incoming", "Phone version"), ("canonical", "Desktop version")]
)
def test_explicit_resolution_converges_and_closes_conflict_on_both_devices(pair, choice, expected):
    sequence = make_conflict(pair)
    server, a, b, ta, tb = pair
    before = b.history(conflicts_only=True)
    result = b.resolve_conflict(sequence, choice=choice, operation_id="resolve-one")
    assert result["applied"]
    assert saved(b)["body"] == expected
    assert b.status()["conflicts"] == 1
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    assert saved(a) == saved(b) == {"paper_id": "paper", "body": expected}
    assert a.status()["conflicts"] == b.status()["conflicts"] == 0
    assert a.history(conflicts_only=True) == b.history(conflicts_only=True) == before
    assert b.history()[-1]["operation"]["resolution_of"] == before[0]["operation"]["operation_id"]
    assert client(b.journal.path, "b").status()["conflicts"] == 0


def test_resolution_can_edit_payload_and_retry_after_ack_without_duplicate(pair):
    sequence = make_conflict(pair)
    server, _, b, _, tb = pair
    payload = {"paper_id": "paper", "body": "Combined interpretation"}
    first = b.resolve_conflict(sequence, payload=payload, operation_id="combined")
    second = b.resolve_conflict(sequence, payload=payload, operation_id="combined")
    assert not second["applied"] and first["sequence"] == second["sequence"]
    b.sync_once(server, tb)
    b = client(b.journal.path, "b")
    assert not b.resolve_conflict(sequence, payload=payload, operation_id="combined")["applied"]
    assert len(server.pull(tb)) == 4
    assert saved(b)["body"] == "Combined interpretation"
    with pytest.raises(ValueError, match="retry changed"):
        b.resolve_conflict(sequence, choice="canonical", payload=payload, operation_id="combined")
    with pytest.raises(ValueError, match="already resolved"):
        b.resolve_conflict(sequence)


def test_repeated_pending_resolution_without_id_reuses_intent(pair):
    sequence = make_conflict(pair)
    _, _, b, _, _ = pair
    first = b.resolve_conflict(sequence)
    second = b.resolve_conflict(sequence)
    assert first["operation_id"] == second["operation_id"]
    assert not second["applied"]
    assert b.status()["pending"] == 1
    with pytest.raises(ValueError, match="retry changed"):
        b.resolve_conflict(sequence, choice="canonical")
    with pytest.raises(ValueError, match="already pending"):
        b.resolve_conflict(sequence, operation_id="another-id")


def test_concurrent_resolution_retries_with_same_id_create_one_operation(pair):
    sequence = make_conflict(pair)
    _, _, b, _, _ = pair
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: client(b.journal.path, "b").resolve_conflict(
                    sequence, operation_id="same-id"
                ),
                range(12),
            )
        )
    assert sum(result["applied"] for result in results) == 1
    assert b.status()["pending"] == 1
    assert saved(b)["body"] == "Phone version"


def test_resolution_racing_new_edit_retains_old_and_new_conflicts(pair):
    sequence = make_conflict(pair)
    server, a, b, ta, tb = pair
    b.resolve_conflict(sequence, operation_id="resolution-race")
    edit(a, "Newer independent observation")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    assert saved(a)["body"] == saved(b)["body"] == "Newer independent observation"
    assert a.status()["conflicts"] == b.status()["conflicts"] == 2
    assert [event["sequence"] for event in b.history(conflicts_only=True)] == [3, 5]
    assert b.history()[-1]["operation"]["payload"]["body"] == "Phone version"


def test_two_racing_resolutions_close_original_but_retain_losing_resolution(pair):
    sequence = make_conflict(pair)
    server, a, b, ta, tb = pair
    a.resolve_conflict(sequence, choice="incoming", operation_id="a-resolution")
    b.resolve_conflict(sequence, choice="canonical", operation_id="b-resolution")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    assert a.status()["conflicts"] == b.status()["conflicts"] == 1
    assert len(b.history(conflicts_only=True)) == 2
    assert saved(a)["body"] == saved(b)["body"] == "Phone version"
    assert b.history(conflicts_only=True)[-1]["operation"]["payload"]["body"] == "Desktop version"


def test_resolution_writer_failure_rolls_back_intent_content_and_outbox(pair):
    sequence = make_conflict(pair)
    _, _, b, _, _ = pair
    before = saved(b), b.status(), b.history()

    def fail(conn, operation):
        writer(conn, operation)
        raise RuntimeError("cannot save")

    b.writer = fail
    with pytest.raises(RuntimeError, match="cannot save"):
        b.resolve_conflict(sequence, operation_id="retry-after-failure")
    assert (saved(b), b.status(), b.history()) == before
    with sqlite3.connect(b.journal.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_resolution_intents").fetchone()[0] == 0
    b.writer = writer
    assert b.resolve_conflict(sequence, operation_id="retry-after-failure")["applied"]


def test_ordinary_edit_never_implicitly_resolves_conflict_and_canonical_choice_uses_current_head(
    pair,
):
    sequence = make_conflict(pair)
    server, a, b, ta, tb = pair
    edit(a, "Current canonical")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert b.status()["conflicts"] == 1
    b.resolve_conflict(sequence, choice="canonical")
    assert saved(b)["body"] == "Current canonical"
    b.sync_once(server, tb)
    assert b.status()["conflicts"] == 0


def test_resolution_rejects_outstanding_local_edits(pair):
    sequence = make_conflict(pair)
    _, _, b, _, _ = pair
    edit(b, "Unsent draft")
    with pytest.raises(ValueError, match="outstanding"):
        b.resolve_conflict(sequence)
    assert saved(b)["body"] == "Unsent draft"
    assert b.status()["pending"] == 1


def test_resolution_rechecks_head_before_atomic_write(pair, monkeypatch):
    sequence = make_conflict(pair)
    server, a, b, ta, tb = pair
    original_apply = b.journal.apply

    def race(operation, write):
        edit(a, "Arrived during resolution")
        a.sync_once(server, ta)
        b.receive(server.pull(tb, after=b.status()["cursor"]))
        return original_apply(operation, write)

    monkeypatch.setattr(b.journal, "apply", race)
    with pytest.raises(ValueError, match="Canonical content changed"):
        b.resolve_conflict(sequence, choice="canonical")
    assert saved(b)["body"] == "Arrived during resolution"
    assert b.status()["pending"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sequence": 0},
        {"sequence": True},
        {"sequence": "3"},
        {"sequence": 999},
        {"sequence": 1},
        {"choice": "unknown"},
        {"payload": []},
        {"payload": {"body": "missing paper"}},
        {"operation_id": ""},
    ],
)
def test_invalid_resolution_does_not_change_content_or_history(pair, kwargs):
    sequence = make_conflict(pair)
    _, _, b, _, _ = pair
    before = saved(b), b.status(), b.history()
    options = {"sequence": sequence, **kwargs}
    with pytest.raises(ValueError):
        b.resolve_conflict(**options)
    assert (saved(b), b.status(), b.history()) == before


def test_canonical_absence_can_be_explicitly_confirmed(pair):
    server, a, b, ta, tb = pair
    operation = a.new_operation("note", "note-1", {"paper_id": "paper", "body": "Rejected"})
    operation["base_revision"] = 99
    a.save(operation)
    a.sync_once(server, ta)
    a.resolve_conflict(1, choice="canonical")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert saved(a) is saved(b) is None
    assert a.status()["conflicts"] == b.status()["conflicts"] == 0
    assert a.history()[-1]["operation"]["action"] == "delete"


def test_receiver_rejects_resolution_of_an_unknown_or_wrong_entity_conflict(pair):
    sequence = make_conflict(pair)
    server, a, b, ta, tb = pair
    b.resolve_conflict(sequence, operation_id="valid-resolution")
    b.sync_once(server, tb)
    events = server.pull(ta, after=a.status()["cursor"])
    malformed = copy.deepcopy(events)
    malformed[0]["operation"]["resolution_of"] = "missing-conflict"
    malformed[0]["head"]["operation"] = malformed[0]["operation"]
    before = a.status(), a.history(), saved(a)
    with pytest.raises(ValueError, match="unknown conflict"):
        a.receive(malformed)
    assert (a.status(), a.history(), saved(a)) == before


def test_outbox_failure_rolls_back_resolution_intent_and_content(pair):
    sequence = make_conflict(pair)
    _, _, b, _, _ = pair
    before = saved(b), b.status()
    with sqlite3.connect(b.journal.path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_resolution BEFORE INSERT ON paperfact_sync_operations "
            "WHEN NEW.operation_id='resolution-fails' "
            "BEGIN SELECT RAISE(ABORT, 'outbox unavailable'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="outbox unavailable"):
        b.resolve_conflict(sequence, operation_id="resolution-fails")
    assert (saved(b), b.status()) == before
    with sqlite3.connect(b.journal.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_resolution_intents").fetchone()[0] == 0


def test_failed_received_resolution_does_not_mark_conflict_resolved(pair):
    sequence = make_conflict(pair)
    server, a, b, ta, tb = pair
    a.resolve_conflict(sequence)
    a.sync_once(server, ta)
    before = saved(b), b.status(), b.history()

    def fail(conn, operation):
        writer(conn, operation)
        raise RuntimeError("materialization failed")

    b.writer = fail
    with pytest.raises(RuntimeError, match="materialization failed"):
        b.sync_once(server, tb)
    assert (saved(b), b.status(), b.history()) == before
    b.writer = writer
    b.sync_once(server, tb)
    assert b.status()["conflicts"] == 0


def test_conflict_index_migration_preserves_resolved_history(pair):
    sequence = make_conflict(pair)
    server, _, b, _, tb = pair
    b.resolve_conflict(sequence)
    b.sync_once(server, tb)
    before = b.status(), b.history()
    with sqlite3.connect(b.journal.path) as conn:
        conn.execute("DROP TABLE paperfact_sync_conflicts")
    migrated = client(b.journal.path, "b")
    assert (migrated.status(), migrated.history()) == before
    restarted = client(b.journal.path, "b")
    assert (restarted.status(), restarted.history()) == before
