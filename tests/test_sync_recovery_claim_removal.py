"""Typed report retirement preserves evidence, related research and later choices."""

import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from uuid import uuid4

import pytest
from test_sync_device_recovery import dump
from test_sync_files import drain
from test_sync_recovery_claim_group import app as app
from test_sync_recovery_claim_group import codec as codec
from test_sync_recovery_claim_group import content as reading_content
from test_sync_recovery_claim_group import group as group
from test_sync_recovery_claim_group import original_group as original_group
from test_sync_recovery_claim_group import pair as pair
from test_sync_recovery_claim_group import positioned as positioned
from test_sync_recovery_claim_group import prepare, refresh
from test_sync_recovery_note_original_group import peer
from test_sync_recovery_positioned_note import notes, source_file
from test_sync_recovery_target import attached

from paper_daily import sync_recovery_choices as choices
from paper_daily import sync_recovery_note_copy as native
from paper_daily import sync_recovery_target as target
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_authority_backup import BackupCancelled
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import CaptureConnection, suppress_capture
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_source_files import _inspection_paths

REPORTS = {"claims": "paper_claim_sets", "dive": "dives", "close_reading": "close_readings",
           "context": "paper_context"}


def content(path):
    result = reading_content(path)
    with closing(_readonly_connection(path)) as conn:
        result["paper_context"] = conn.execute("SELECT * FROM paper_context").fetchall()
    return result


def removal_case(group, feature="claims"):
    prepare(group).apply()
    old, _, _, path, root, *_ = group
    if feature == "context":
        from paper_daily.sync_content import content_id

        scope = root["payload"]["scope"]
        payload = dict(scope=scope, feature=feature, key="main", source_document_hash=None,
                       data=dict(summary=None, reading_json=[dict(
                           title="Earlier comparison", direction="background",
                           why="Study assumptions",
                       )], written_at="2026-11-14T00:00:00+00:00", edited=1))
        root = old.new_graph_operation("research_content", content_id(scope, feature, "main"),
                                       payload)
        old.save(root)
        client = attached(path)
        client.save(client.new_graph_operation("research_content", root["entity_id"], payload))
    elif feature != "claims":
        with closing(_readonly_connection(old.journal.path)) as conn:
            root = next(json.loads(row[0]) for row in conn.execute(
                "SELECT envelope FROM paperfact_sync_operations"
            ) if json.loads(row[0]).get("payload", {}).get("feature") == feature)
    deletion = old.new_graph_operation("research_content", root["entity_id"], {}, action="delete")
    old.save(deletion)
    return refresh(group, deletion)


def removal(group, request=None):
    _, source, change, path, *_ = group
    return choices.prepare(target.observe(source, path), change, "remove", request or str(uuid4()))


@pytest.mark.parametrize("feature", REPORTS)
def test_claim_removal_delivers_to_peer_and_retry_preserves_later_restore(
    group, monkeypatch, tmp_path_factory, feature,
):
    g = removal_case(group, feature)
    old, _, _, path, root, service, sha, data, token = g
    client = attached(path)
    current = target.observe(g[1], path).compare(g[2])["target"]["effective_operation"]
    preserved, old_notes, original = content(path), notes(path), dump(old.journal.path)
    monkeypatch.setattr(native, "_original", lambda *_a, **_k: pytest.fail("No original grant"))
    decision = removal(g)
    assert decision.claim_removal == (feature == "claims")
    assert decision.reading_removal == (feature != "claims")
    assert not decision.note_removal and not decision.manual_restore
    result = decision.apply()
    assert result["applied"] and result["choice"] == "remove" and not result["originals_verified"]
    assert content(path)[REPORTS[feature]] == []
    assert all(content(path)[table] == rows for table, rows in preserved.items()
               if table != REPORTS[feature])
    assert notes(path) == old_notes and dump(old.journal.path) == original
    assert source_file(path, sha, len(data)).read_bytes() == data
    pending = client.journal.pending()
    assert pending[-1]["entity_id"] == root["entity_id"] and pending[-1]["action"] == "delete"
    with closing(_readonly_connection(path)) as conn:
        store, versions = _inspection_paths(conn)
    transfer = FileTransfers(client, BlobStore(store.root), service,
        origin="https://recovery.fixture.invalid", token=token, version_root=versions)
    try:
        drain(lambda: transfer.upload(pending[0]), "uploaded")
        state = client.sync_once(service, token, prepare_push=transfer.ready_to_push)
        assert state["pending"] == state["conflicts"] == 0
    finally:
        transfer.close()
    other = peer(path, service, tmp_path_factory)
    assert content(other) == content(path) and notes(other) == old_notes
    assert source_file(other, sha, len(data)).read_bytes() == data
    client.save(client.new_graph_operation(
        "research_content", root["entity_id"], current["payload"], restore=True,
    ))
    later = dump(path)
    assert not decision.apply()["applied"]
    assert not removal(g, decision.request_id).apply()["applied"]
    assert dump(path) == later and content(path)[REPORTS[feature]]


def test_claim_removal_failure_cancel_and_stale_target_preserve_everything(group, monkeypatch):
    g = removal_case(group)
    path = g[3]
    decision = removal(g)
    original = choices._write_receipt
    for failure in ("write", "cancel"):
        changed = []

        def fail(conn, *args, changed=changed, failure=failure):
            original(conn, *args)
            changed.append(True)
            if failure == "write":
                raise RuntimeError("Synthetic receipt failure")

        monkeypatch.setattr(choices, "_write_receipt", fail)
        before = dump(path)
        with pytest.raises(RuntimeError if failure == "write" else BackupCancelled):
            decision.apply(cancelled=lambda failure=failure, changed=changed:
                           failure == "cancel" and bool(changed))
        assert changed and dump(path) == before
    monkeypatch.setattr(choices, "_write_receipt", original)
    client = attached(path)
    current = target.observe(g[1], path).compare(g[2])["target"]["effective_operation"]
    updated = deepcopy(current["payload"])
    updated["data"]["written_at"] = "2026-11-15T00:00:00+00:00"
    client.save(client.new_graph_operation("research_content", current["entity_id"], updated))
    before = dump(path)
    with pytest.raises(ValueError, match="changed"):
        decision.apply()
    assert dump(path) == before


@pytest.mark.parametrize("feature", REPORTS)
def test_claim_removal_refuses_untracked_visible_analysis(group, feature):
    g = removal_case(group, feature)
    path = g[3]
    if feature == "context":
        changed_fields = ("summary", "reading_json", "edited")
    else:
        changed_fields = ("written_at",) if feature == "claims" else ("spec",)
    table = REPORTS[feature]
    with closing(_readonly_connection(path)) as conn:
        original = dict(zip(changed_fields, conn.execute(
            "SELECT " + ",".join(changed_fields) + " FROM " + table,
        ).fetchone(), strict=True))
    label = "claim analysis" if feature == "claims" else "saved reading"
    for column in changed_fields:
        invalid = "2026-11-16T00:00:00+00:00" if feature == "claims" else "x" * (256 * 1024 + 1)
        with (closing(sqlite3.connect(path, factory=CaptureConnection)) as conn,
              conn, suppress_capture(conn)):
            conn.execute("UPDATE " + table + " SET " + column + "=?", (invalid,))
        before = dump(path)
        with pytest.raises(ValueError, match=f"Visible {label} differs"):
            removal(g)
        assert dump(path) == before
        with (closing(sqlite3.connect(path, factory=CaptureConnection)) as conn,
              conn, suppress_capture(conn)):
            conn.execute("UPDATE " + table + " SET " + column + "=?", (original[column],))



@pytest.mark.parametrize("feature", REPORTS)
def test_desktop_claim_removal_is_explicit_cancelable_and_single_flight(
    group, app, monkeypatch, feature,
):
    from PySide6.QtWidgets import QMessageBox
    from test_workspace_dialog import wait

    from paper_daily.desktop.workspace_dialog import WorkspaceDialog

    g = removal_case(group, feature)
    owner = WorkspaceDialog(g[0].journal.path, language="zh-TW")
    owner.show()
    try:
        wait(app, lambda: owner._ready and not owner.busy)
        owner.task_tabs.setCurrentIndex(2)
        owner.device_review.disclosure.setChecked(True)
        ui = owner.device_review.changes
        assert owner.device_review.inspect(g[1].snapshot)
        wait(app, lambda: not owner.busy)
        assert ui.load(g[3].parent)
        wait(app, lambda: not owner.busy)
        for index in range(ui.rows.count()):
            ui.rows.setCurrentRow(index)
            if ui.selected() == g[2]:
                break
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        index = ui.action_select.findData("remove")
        assert index >= 0, ui.notice.text()
        ui.action_select.setCurrentIndex(index)
        key = "remove_claims" if feature == "claims" else "remove_reading"
        assert ui.action_select.currentText() == ui.t[key]
        assert ui.notice.text() == ui.t["ready_" + key]
        before, prompts = dump(g[3]), []

        def answer(*args):
            prompts.append(args)
            return QMessageBox.No if len(prompts) == 1 else QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", answer)
        ui.copy_button.click()
        assert not owner.busy and dump(g[3]) == before
        assert prompts[0][2] == ui.t["confirm_" + key]
        assert prompts[0][-1] == QMessageBox.No
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        assert content(g[3])[REPORTS[feature]] == []
        assert sum(op["action"] == "delete" for op in attached(g[3]).journal.pending()) == 1
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()
