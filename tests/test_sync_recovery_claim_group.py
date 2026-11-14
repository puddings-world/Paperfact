"""Claim recovery preserves a complete source-pinned group, not mixed generations."""

import sqlite3
from contextlib import closing
from copy import deepcopy
from uuid import uuid4

import pytest
from test_sync_device_recovery import dump
from test_sync_files import PAPER
from test_sync_recovery_note_original_group import group as _original_group
from test_sync_recovery_note_original_group import peer, retire_source_before_review
from test_sync_recovery_positioned_note import notes, source_file
from test_sync_recovery_positioned_note import positioned as positioned
from test_sync_recovery_target import attached
from test_sync_recovery_target import codec as codec
from test_sync_recovery_target import pair as pair
from test_workspace_dialog import app as app
from test_workspace_dialog import wait

from paper_daily import claim_content, research_evidence
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_claim_group as recovery
from paper_daily import sync_recovery_target as target
from paper_daily.desktop.workspace_dialog import WorkspaceDialog
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_authority_backup import BackupCancelled
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_content import content_id
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_files import file_id
from paper_daily.sync_research import research_writer
from paper_daily.sync_source_files import FEATURE, _inspection_paths

original_group = _original_group

STAMP = "2026-11-14T00:00:00+00:00"


@pytest.fixture
def group(original_group):
    old, previous, _, path, _, service, sha, data, token = original_group
    scope = dict(kind="paper", id=PAPER)
    inputs = {}
    for feature, body in (("dive", "Pinned deep explanation"),
                          ("close_reading", "Pinned section-by-section argument")):
        fields = dict(body=body, spec="fixture", written_at=STAMP)
        payload = dict(scope=scope, feature=feature, key="main", data=fields,
                       source_document_hash=sha)
        old.save(old.new_graph_operation("research_content", content_id(scope, feature, "main"),
                                         payload))
        inputs[feature] = claim_content.input_digest(fields)
    source = dict(paper_id=PAPER, document_hash=sha)
    report = research_evidence._verify_bytes(data, source, dict(claims=[dict(
        text="The observation supports this comparison.",
        judgment=dict(status="unresolved", reason="Study assumptions still need expert review."),
        passages=[dict(quote="New post-backup source evidence", page=1, anchor=None)],
    )]), None)
    report.pop("id")
    report["verification_scope"] = "original_snapshot"
    report["id"] = research_evidence._hash(report)
    body = claim_content.validate(dict(format=claim_content.FORMAT, recipe=claim_content.RECIPE,
        inputs=inputs, generation=dict(task="claims", backend="fixture", requested_model=None,
                                      returned_model=None), report=report))
    payload = dict(scope=scope, feature="claims", key="main", source_document_hash=sha,
        data=dict(body_json=body, source_hash=claim_content.source_digest(inputs, sha),
                  document_hash=sha, written_at=STAMP))
    root = old.new_graph_operation("research_content", content_id(scope, "claims", "main"), payload)
    old.save(root)
    index = candidates.prepare(old.journal.path, previous.snapshot, previous.workspace)
    change = next(row["change_id"] for row in index.page()["items"]
                  if row["operation_id"] == root["operation_id"])
    return old, index, change, path, root, service, sha, data, token


def pin_dive(old, root, digest):
    payload = deepcopy(root["payload"])
    payload["data"]["body_json"]["inputs"]["dive"] = digest
    payload["data"]["source_hash"] = claim_content.source_digest(
        payload["data"]["body_json"]["inputs"], payload["source_document_hash"],
    )
    operation = old.new_graph_operation("research_content", root["entity_id"], payload)
    old.save(operation)
    return operation


def refresh(group, root):
    old, previous, _, path, _, service, sha, data, token = group
    source = candidates.prepare(old.journal.path, previous.snapshot, previous.workspace)
    change = next(row["change_id"] for row in source.page()["items"]
                  if row["operation_id"] == root["operation_id"])
    return old, source, change, path, root, service, sha, data, token


def prepare(group, request=None, *, replace=False):
    _, source, change, path, *_ = group
    return recovery.prepare(target.observe(source, path), change, request or str(uuid4()),
                            replace=replace)


def content(path):
    with closing(_readonly_connection(path)) as conn:
        return {table: conn.execute("SELECT * FROM " + table).fetchall()
                for table in ("dives", "close_readings", "paper_claim_sets")}


def test_group_and_original_commit_once_and_reach_an_independent_native_peer(
    group, tmp_path_factory,
):
    from test_sync_files import drain

    old, source, change, path, root, service, sha, data, token = group
    source, change = retire_source_before_review(old, source, root, sha)
    group = (old, source, change, *group[3:])
    before, original_notes = dump(old.journal.path), notes(path)
    request = str(uuid4())
    plan = prepare(group, request)
    assert [r["feature"] for r in plan.comparison] == list(recovery.FEATURES)
    receipt = plan.apply()
    assert receipt["applied"] and receipt["state"] == "saved_locally"
    assert receipt["semantic_validation"] == "not_performed"
    assert not receipt["remote_acceptance_checked"] and not receipt["replayed"]
    client = attached(path)
    pending = client.journal.pending()
    assert [op["entity_type"] for op in pending] == ["research_file"] + ["research_content"] * 3
    assert pending[-1]["payload"] == root["payload"]
    assert notes(path) == original_notes and dump(old.journal.path) == before
    assert not plan.apply()["applied"]
    assert not recovery.prepare(target.observe(source, path), change, request).apply()["applied"]
    with closing(_readonly_connection(path)) as conn:
        store, version_root = _inspection_paths(conn)
    transfer = FileTransfers(client, BlobStore(store.root), service,
                             origin="https://recovery.fixture.invalid", token=token,
                             version_root=version_root)
    try:
        drain(lambda: transfer.upload(pending[0]), "uploaded")
        synced = client.sync_once(service, token, prepare_push=transfer.ready_to_push)
        assert synced["pending"] == synced["conflicts"] == 0
    finally:
        transfer.close()
    other = peer(path, service, tmp_path_factory)
    assert content(other) == content(path)
    assert source_file(other, sha, len(data)).read_bytes() == data
    client.save(client.new_graph_operation("research_content", pending[1]["entity_id"], {
        **pending[1]["payload"], "data": {**pending[1]["payload"]["data"], "body": "Later edit"}}))
    later = dump(path)
    assert not prepare(group, request).apply()["applied"] and dump(path) == later
    with pytest.raises(ValueError, match="before replacement"):
        prepare(group)
    explicit = prepare(group, replace=True)
    assert explicit.comparison[0]["current"]["body"] == "Later edit"
    assert explicit.apply()["applied"]
    assert content(path)["dives"][0][1] == "Pinned deep explanation"
    assert not explicit.apply()["applied"] and notes(path) == original_notes
    with closing(sqlite3.connect(path)) as conn, conn:
        # Simulate an older writer that registered the trigger hook but did not journal.
        conn.create_function("paperfact_capture", 3, lambda *_: None)
        conn.execute("UPDATE dives SET body='Uncaptured private draft'")
    private = dump(path)
    with pytest.raises(ValueError, match="Visible research differs from native history"):
        prepare(group, replace=True)
    assert dump(path) == private
    assert not prepare(group, request).apply()["applied"] and dump(path) == private


@pytest.mark.parametrize("failure", ["exception", "cancel"])
def test_second_analysis_failure_rolls_back_original_all_rows_outbox_and_receipt(
    group, monkeypatch, failure,
):
    _, _, _, path, *_ = group
    plan, written = prepare(group), []
    activate = CaptureConnection._activate

    def failing(conn):
        activate(conn)

        def write(conn, operation):
            research_writer(conn, operation)
            written.append(operation["payload"].get("feature"))
            if operation["payload"].get("feature") == "close_reading" and failure == "exception":
                raise RuntimeError("simulated group child failure")

        conn._capture_client.writer = write

    monkeypatch.setattr(CaptureConnection, "_activate", failing)
    before = dump(path)
    with pytest.raises(RuntimeError if failure == "exception" else BackupCancelled):
        plan.apply(cancelled=lambda: failure == "cancel" and "close_reading" in written)
    assert written == [FEATURE, "dive", "close_reading"]
    assert dump(path) == before and attached(path).journal.pending() == []
    monkeypatch.setattr(CaptureConnection, "_activate", activate)
    assert plan.apply()["applied"] and len(attached(path).journal.pending()) == 4


def test_mismatched_generation_and_corrupt_receipt_refuse_without_writes(group):
    old, source, change, path, root, *_ = group
    plan = prepare(group)
    assert plan.apply()["applied"]
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE integration_operations SET result='{}' WHERE id=?", (plan.request_id,))
    before = dump(path)
    with pytest.raises(ValueError, match="receipt changed"):
        plan.apply()
    assert dump(path) == before
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("DELETE FROM integration_operations WHERE id=?", (plan.request_id,))
    before = dump(path)
    with pytest.raises(ValueError, match="without their decision receipt"):
        prepare(group, plan.request_id)
    assert dump(path) == before
    scope = root["payload"]["scope"]
    old.save(old.new_graph_operation("research_content", content_id(scope, "dive", "main"), dict(
        scope=scope, feature="dive", key="main", source_document_hash=root["payload"][
            "source_document_hash"], data=dict(body="Another generation", spec="fixture",
                                             written_at=STAMP))))
    unavailable = pin_dive(old, root, "0" * 64)
    updated = candidates.prepare(old.journal.path, source.snapshot, source.workspace)
    selected = next(row["change_id"] for row in updated.page()["items"]
                    if row["operation_id"] == unavailable["operation_id"])
    with pytest.raises(ValueError, match="No native history matches"):
        recovery.prepare(target.observe(updated, path), selected, str(uuid4()), replace=True)
    assert dump(path) == before


@pytest.mark.parametrize("invalid_inputs", [False, True])
def test_desktop_reviews_all_inputs_confirms_once_and_preserves_manual_notes(
    group, app, monkeypatch, invalid_inputs,
):
    from PySide6.QtWidgets import QMessageBox

    old, source, _, path, root, *_ = group
    if invalid_inputs:
        scope = root["payload"]["scope"]
        old.save(old.new_graph_operation("research_content", content_id(scope, "dive", "main"),
            dict(scope=scope, feature="dive", key="main",
                 source_document_hash=root["payload"]["source_document_hash"],
                 data=dict(body="Another generation", spec="fixture", written_at=STAMP))))
        root = pin_dive(old, root, "0" * 64)
        source = candidates.prepare(old.journal.path, source.snapshot, source.workspace)
    owner = WorkspaceDialog(old.journal.path, language="en")
    owner.show()
    try:
        wait(app, lambda: owner._ready and not owner.busy)
        owner.task_tabs.setCurrentIndex(2)
        owner.device_review.disclosure.setChecked(True)
        ui = owner.device_review.changes
        assert owner.device_review.inspect(source.snapshot)
        wait(app, lambda: not owner.busy)
        assert ui.load(path.parent)
        wait(app, lambda: not owner.busy)
        selected = next(row["change_id"] for row in ui.page["items"]
                        if row["operation_id"] == root["operation_id"])
        for index in range(ui.rows.count()):
            ui.rows.setCurrentRow(index)
            if ui.selected() == selected:
                break
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        if invalid_inputs:
            assert ui.action_select.findData("claim_group") == -1
            assert "No native history matches" in ui.notice.text()
            assert ui.old.toPlainText() and attached(path).journal.pending() == []
            return
        assert ui.action_select.currentData() == "claim_group", owner.status.text()
        assert "Pinned deep explanation" in ui.old.toPlainText()
        assert "Pinned section-by-section argument" in ui.old.toPlainText()
        assert "Proposed judgment" in ui.old.toPlainText()
        before, original_notes = dump(path), notes(path)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
        ui.copy_button.click()
        assert dump(path) == before and not owner.busy
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        assert notes(path) == original_notes and len(attached(path).journal.pending()) == 4
        with closing(_readonly_connection(path)) as conn:
            assert desired_file(conn, file_id(PAPER, FEATURE, root["payload"][
                "source_document_hash"])) is not None
        assert "Decision saved locally" in ui.notice.text()
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()


def test_schema_valid_but_false_claim_location_cannot_be_recovered(group):
    old, source, _, path, root, *_ = group
    payload = deepcopy(root["payload"])
    report = payload["data"]["body_json"]["report"]
    passage = report["claims"][0]["passages"][0]
    passage["quote"] = "An invented passage absent from the original"
    passage["id"] = claim_content.hashed([
        "located-passage", report["source"], claim_content.normalize(passage["quote"]),
        passage["location"]["anchor"],
    ])
    report.pop("id")
    report["id"] = claim_content.hashed(report)
    claim_content.validate(payload["data"]["body_json"])
    forged = old.new_graph_operation("research_content", root["entity_id"], payload)
    old.save(forged)
    index = candidates.prepare(old.journal.path, source.snapshot, source.workspace)
    change = next(row["change_id"] for row in index.page()["items"]
                  if row["operation_id"] == forged["operation_id"])
    before = dump(path)
    with pytest.raises(ValueError, match="no longer matches its original"):
        recovery.prepare(target.observe(index, path), change, str(uuid4()))
    assert dump(path) == before and attached(path).journal.pending() == []


@pytest.mark.parametrize("origin", [
    "journal", "accepted_peer", "conflicting_peer", "corrupt_cache",
])
def test_pinned_history_recovers_exact_input_and_rejects_unaccepted_foreign_versions(
    group, pair, tmp_path, origin,
):
    from paper_daily import sync_admin

    old, _, _, path, root, _, sha, *_ = group
    scope = root["payload"]["scope"]
    identity = content_id(scope, "dive", "main")
    chosen_id = None
    expected = "Pinned deep explanation"
    if origin == "journal":
        old.save(old.new_graph_operation("research_content", identity, dict(
            scope=scope, feature="dive", key="main", source_document_hash=sha,
            data=dict(body="A newer source-side analysis", spec="fixture", written_at=STAMP))))
        old.save(old.new_graph_operation("research_content", identity, {}, action="delete"))
    else:
        service = sync_admin.authority(tmp_path / "marked-authority")
        sender = pair[2]
        token = service.enroll("workspace", "b")
        chosen_data = dict(body="Earlier accepted peer analysis", spec="fixture", written_at=STAMP)
        wanted = dict(scope=scope, feature="dive", key="main", source_document_hash=sha,
                      data=chosen_data)
        if origin in {"accepted_peer", "corrupt_cache"}:
            chosen = sender.new_graph_operation("research_content", identity, wanted)
            sender.save(chosen)
            assert sender.sync_once(service, token)["pending"] == 0
            newer = sender.new_graph_operation("research_content", identity, {
                **wanted, "data": {**chosen_data, "body": "Newer accepted peer analysis"}})
            sender.save(newer)
            assert sender.sync_once(service, token)["pending"] == 0
        else:
            accepted = sender.new_graph_operation("research_content", identity, {
                **wanted, "data": {**chosen_data, "body": "A different accepted peer input"}})
            assert service.push(token, accepted)["outcome"] == "accepted"
            chosen = sender.new_graph_operation("research_content", identity, wanted)
            assert service.push(token, chosen)["outcome"] == "conflict"
        chosen_id = chosen["operation_id"]
        old.receive(service.pull(token, after=old.status()["cursor"]))
        if origin == "accepted_peer":
            # A missing derived graph receipt must not erase authoritative inbox history.
            with closing(sqlite3.connect(old.journal.path)) as conn, conn:
                conn.execute("DELETE FROM paperfact_sync_graph_receipts WHERE operation_id=?",
                             (chosen_id,))
        elif origin == "corrupt_cache":
            with closing(sqlite3.connect(old.journal.path)) as conn, conn:
                conn.execute(
                    "UPDATE paperfact_sync_graph_receipts SET event=(SELECT event FROM "
                    "paperfact_sync_graph_receipts WHERE operation_id=?) WHERE operation_id=?",
                    (newer["operation_id"], chosen_id),
                )
        else:
            with closing(_readonly_connection(old.journal.path)) as conn:
                assert conn.execute(
                    "SELECT 1 FROM paperfact_sync_graph_receipts WHERE operation_id=?",
                    (chosen_id,),
                ).fetchone()
        root = pin_dive(old, root, claim_content.input_digest(chosen_data))
        expected = chosen_data["body"]
    updated = refresh(group, root)
    before, destination = dump(old.journal.path), dump(path)
    if origin in {"conflicting_peer", "corrupt_cache"}:
        reason = ("No native history matches" if origin == "conflicting_peer"
                  else "another operation")
        with pytest.raises(ValueError, match=reason):
            prepare(updated)
        assert dump(path) == destination and dump(old.journal.path) == before
        return
    plan = prepare(updated)
    assert plan.comparison[0]["source"]["body"] == expected
    receipt = plan.apply()
    assert receipt["applied"] and not receipt["remote_acceptance_checked"]
    if chosen_id:
        assert receipt["sources"][0]["id"] == chosen_id
    assert content(path)["dives"][0][1] == expected
    assert not plan.apply()["applied"]
    assert dump(old.journal.path) == before
    assert len(attached(path).journal.pending()) == 4
