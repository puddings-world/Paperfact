"""Native note-copy transaction, retry, stale decision and failure behavior."""

from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pytest
from test_sync_device_recovery import dump
from test_sync_files import PAPER
from test_sync_files import codec as codec
from test_sync_recovery_target import attached
from test_sync_recovery_target import pair as pair
from test_sync_recovery_target import prepared as prepared

from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_note_copy as copy
from paper_daily import sync_recovery_target as target
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_authority_backup import BackupCancelled
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_research import research_writer


def decision(prepared, request=None):
    _old, source, change, path, _operation = prepared
    return copy.prepare(target.observe(source, path), change, request or str(uuid4()))


def bodies(path):
    with closing(_readonly_connection(path)) as conn:
        return [row[0] for row in conn.execute("SELECT body FROM notes ORDER BY id")]


def test_copy_preserves_old_and_target_notes_with_one_new_native_operation(prepared):
    old, _source, _change, path, source_op = prepared
    before = dump(old.journal.path)
    prepared_copy = decision(prepared)
    assert attached(path).journal.pending() == []
    result = prepared_copy.apply()
    assert result["applied"] and result["state"] == "saved_locally"
    assert not result["replayed"] and result["remote_accepted"] is None
    assert not result["remote_acceptance_checked"]
    pending = attached(path).journal.pending()
    assert len(pending) == 1
    assert pending[0]["workspace_id"] == "fresh-research"
    assert pending[0]["device_id"] == "travel"
    assert pending[0]["entity_id"] != source_op["entity_id"]
    assert pending[0]["operation_id"] != source_op["operation_id"]
    assert pending[0]["payload"] == source_op["payload"]
    assert pending[0]["parents"] == source_op["parents"]
    assert bodies(path) == ["Backed up note", "Old device's unsent revision"]
    assert dump(old.journal.path) == before and len(old.journal.pending()) == 1


def test_repeated_apply_and_restart_preparation_do_not_duplicate_or_overwrite(prepared):
    _old, source, change, path, _operation = prepared
    request = str(uuid4())
    prepared_copy = decision(prepared, request)
    first = prepared_copy.apply()
    client = attached(path)
    client.save(
        client.new_graph_operation(
            "note",
            first["entity_id"],
            dict(paper_id=PAPER, body="Later local edit to the copy"),
        )
    )
    before = dump(path)
    again = prepared_copy.apply()
    new_observation = target.observe(source, path)
    reconstructed = copy.prepare(new_observation, change, request).apply()
    assert not again["applied"] and not reconstructed["applied"]
    assert first["sequence"] == again["sequence"] == reconstructed["sequence"]
    assert len(client.journal.pending()) == 2 and dump(path) == before
    assert bodies(path) == ["Backed up note", "Later local edit to the copy"]


@pytest.mark.parametrize("side", ["old", "target"])
def test_edit_after_decision_refuses_without_losing_the_edit(prepared, side):
    old, _source, _change, path, _operation = prepared
    prepared_copy = decision(prepared)
    client = old if side == "old" else attached(path)
    client.save(
        client.new_graph_operation(
            "note",
            str(uuid4()),
            dict(paper_id=PAPER, body="Saved while recovery was pending"),
        )
    )
    before = dump(path), dump(old.journal.path)
    with pytest.raises(ValueError, match="changed"):
        prepared_copy.apply()
    assert before == (dump(path), dump(old.journal.path))
    assert "Old device's unsent revision" not in bodies(path)


@pytest.mark.parametrize("failure", ["exception", "cancel"])
def test_failure_after_research_write_rolls_back_research_outbox_and_receipt(
    prepared,
    monkeypatch,
    failure,
):
    _old, _source, _change, path, _operation = prepared
    prepared_copy = decision(prepared)
    activate = CaptureConnection._activate
    written = []

    def failing_activate(conn):
        activate(conn)

        def fail(conn, operation):
            research_writer(conn, operation)
            written.append(True)
            if failure == "exception":
                raise RuntimeError("simulated failure after note projection")

        conn._capture_client.writer = fail

    monkeypatch.setattr(CaptureConnection, "_activate", failing_activate)
    before = dump(path)
    error = RuntimeError if failure == "exception" else BackupCancelled
    with pytest.raises(error):
        prepared_copy.apply(cancelled=lambda: failure == "cancel" and bool(written))
    assert written and dump(path) == before and attached(path).journal.pending() == []
    monkeypatch.setattr(CaptureConnection, "_activate", activate)
    assert prepared_copy.apply()["applied"]
    assert len(attached(path).journal.pending()) == 1


def test_cancel_and_forged_decision_have_no_writes(prepared):
    _old, _source, _change, path, _operation = prepared
    prepared_copy = decision(prepared)
    before = dump(path)
    with pytest.raises(BackupCancelled):
        prepared_copy.apply(cancelled=lambda: True)
    with pytest.raises(ValueError, match="original prepared note-copy"):
        replace(prepared_copy, operation_json="{}").apply()
    assert dump(path) == before


def test_reused_request_for_different_source_is_refused_without_extra_note(prepared):
    old, source, _change, path, _operation = prepared
    another = old.new_graph_operation(
        "note", str(uuid4()), dict(paper_id=PAPER, body="Second note")
    )
    old.save(another)
    source = candidates.prepare(old.journal.path, source.snapshot, source.workspace)
    entries = source.page()["items"]
    observed = target.observe(source, path)
    request = str(uuid4())
    first = copy.prepare(observed, entries[0]["change_id"], request)
    second = copy.prepare(observed, entries[1]["change_id"], request)
    first.apply()
    before = dump(path)
    with pytest.raises(ValueError, match="reused with different content"):
        second.apply()
    with pytest.raises(ValueError, match="reused with different content"):
        copy.prepare(target.observe(source, path), entries[1]["change_id"], request)
    assert dump(path) == before and len(attached(path).journal.pending()) == 1


def test_deleted_original_note_can_be_copied_without_resurrection(prepared):
    _old, _source, _change, path, operation = prepared
    client = attached(path)
    client.save(client.new_graph_operation("note", operation["entity_id"], {}, action="delete"))
    result = decision(prepared).apply()
    assert result["applied"] and result["entity_id"] != operation["entity_id"]
    assert bodies(path) == ["Old device's unsent revision"]
    assert [op["action"] for op in client.journal.pending()] == ["delete", "put"]


@pytest.mark.parametrize("variant", ["anchored_note", "other_domain", "delete"])
def test_unsupported_inputs_remain_pending_without_generic_flattening(prepared, variant):
    old, source, _change, path, operation = prepared
    if variant == "anchored_note":
        op = old.new_graph_operation(
            "note",
            str(uuid4()),
            dict(
                paper_id=PAPER,
                body="An original-bound note",
                kind="note",
                created_at="2026-11-14T00:00:00+00:00",
                page=1,
                anchor=None,
            ),
        )
    elif variant == "other_domain":
        op = old.new_graph_operation("list", "new-old-list", dict(name="Old list", note=None))
    else:
        op = old.new_graph_operation("note", operation["entity_id"], {}, action="delete")
    old.save(op)
    source = candidates.prepare(old.journal.path, source.snapshot, source.workspace)
    change = next(
        row["change_id"]
        for row in source.page()["items"]
        if row["operation_id"] == op["operation_id"]
    )
    before = dump(path), dump(old.journal.path)
    with pytest.raises(ValueError, match="original verification|note puts only"):
        copy.prepare(target.observe(source, path), change, str(uuid4()))
    assert before == (dump(path), dump(old.journal.path))


def test_rapid_parallel_confirmation_creates_exactly_one_note(prepared):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    _old, _source, _change, path, _operation = prepared
    prepared_copy = decision(prepared)
    ready = Barrier(2)

    def apply():
        ready.wait(timeout=5)
        return prepared_copy.apply()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: apply(), range(2)))
    assert sorted(value["applied"] for value in results) == [False, True]
    assert results[0]["entity_id"] == results[1]["entity_id"]
    assert len(attached(path).journal.pending()) == 1
    assert bodies(path) == ["Backed up note", "Old device's unsent revision"]


def test_copy_syncs_through_recovered_authority_to_another_native_client(
    request,
    monkeypatch,
    tmp_path_factory,
):
    import test_sync_recovery_target as fixtures
    from test_workspace_sync import Native

    from paper_daily import sync_bootstrap
    from paper_daily.workspace_service import Ticket
    from paper_daily.workspace_sync import SyncSession

    publish = fixtures.publish
    hosted = {}

    def capture(*args, **kwargs):
        service = publish(*args, **kwargs)
        enroll = service.enroll

        def tracked(workspace, device):
            token = enroll(workspace, device)
            if device == "travel":
                hosted.update(service=service, token=token)
            return token

        monkeypatch.setattr(service, "enroll", tracked)
        return service

    monkeypatch.setattr(fixtures, "publish", capture)
    prepared = request.getfixturevalue("prepared")
    old, source, _change, path, source_op = prepared
    before = dump(old.journal.path)

    def check_source(_stage):
        source._check(lambda: None)

    copied = decision(prepared)
    check_source("decision")
    saved = copied.apply()
    check_source("first apply")
    service = hosted["service"]
    client = attached(path)
    synced = client.sync_once(service, hosted["token"])
    assert synced["pending"] == synced["conflicts"] == 0
    check_source("sync")
    # Force deferred finalizers at the point that reproduced a leaked fixture handle.
    __import__("gc").collect()
    check_source("explicit collection after sync")
    token = service.enroll("fresh-research", "observer")
    check_source("enroll")
    joining = SyncSession(path, transport_factory=lambda url: Native(url, service, []))
    destination = tmp_path_factory.mktemp("recovery-note-peer") / "workspace"
    joining.connect(
        "https://recovery.fixture.invalid", "fresh-research", "observer", token, Ticket()
    )
    try:
        assert sync_bootstrap.join(joining, destination, Ticket())["state"] == "metadata_ready"
    finally:
        joining.disconnect()
    check_source("join peer")
    peer = destination / "papers.db"
    assert bodies(peer) == ["Backed up note", "Old device's unsent revision"]
    with closing(_readonly_connection(peer)) as conn:
        row = conn.execute(
            "SELECT operation FROM paperfact_sync_heads WHERE entity_type=? AND entity_id=?",
            ("note", saved["entity_id"]),
        ).fetchone()
    assert row is not None
    assert source_op["entity_id"] != saved["entity_id"]
    check_source("before retry")
    assert not copied.apply()["applied"]
    assert client.journal.pending() == [] and dump(old.journal.path) == before
    assert source.details(prepared[2])["operation"] == source_op
