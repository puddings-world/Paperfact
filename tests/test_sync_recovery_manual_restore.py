"""Restore a known manual identity using owned exact-PDF proofs and native receipts."""

import sqlite3
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from test_sync_device_recovery import dump
from test_sync_files import drain
from test_sync_recovery_manual_highlight import app as app
from test_sync_recovery_manual_highlight import codec as codec
from test_sync_recovery_manual_highlight import group as group
from test_sync_recovery_manual_highlight import original_group as original_group
from test_sync_recovery_manual_highlight import pair as pair
from test_sync_recovery_manual_highlight import peer, rows, save
from test_sync_recovery_manual_highlight import plan as copy_plan
from test_sync_recovery_manual_highlight import positioned as positioned
from test_sync_recovery_target import attached

from paper_daily import sync_recovery_choices as choices
from paper_daily import sync_recovery_target as target
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_source_files import _inspection_paths


@pytest.fixture
def retired(group):
    # The maintained copy/original transaction explicitly owns the exact target
    # PDF. Retire that distinct copy, then the actual identity being restored.
    copied = copy_plan(group).apply()
    client = attached(group["path"])
    client.save(
        client.new_graph_operation("research_content", copied["entity_id"], {}, action="delete")
    )
    save(client, group["root"]["payload"])
    client.save(
        client.new_graph_operation(
            "research_content", group["root"]["entity_id"], {}, action="delete"
        )
    )
    return dict(group, client=client)


def prepare(g, request=None):
    return choices.prepare(
        target.observe(g["source"], g["path"]), g["change"], "restore", request or str(uuid4())
    )


def test_manual_restore_keeps_identity_reaches_peer_and_retries_preserve_later_delete(
    retired,
    tmp_path_factory,
):
    g = retired
    before = len(g["client"].journal.pending())
    old = dump(g["old"].journal.path)
    plan = prepare(g)
    assert plan.manual_restore and plan._original is not None
    result = plan.apply()
    assert result["applied"] and result["originals_verified"] and not result["replayed"]
    assert result["entity_id"] == g["root"]["entity_id"]
    assert len(rows(g["path"])) == 1
    pending = g["client"].journal.pending()
    assert len(pending) == before + 1
    assert pending[-1]["payload"] == g["root"]["payload"]
    assert pending[-1]["incarnation"] == plan.request_id
    assert dump(g["old"].journal.path) == old
    with closing(_readonly_connection(g["path"])) as conn:
        store, root = _inspection_paths(conn)
    transfer = FileTransfers(
        g["client"],
        BlobStore(store.root),
        g["service"],
        origin="https://recovery.fixture.invalid",
        token=g["token"],
        version_root=root,
    )
    try:
        for operation in pending:
            if operation["entity_type"] == "research_file":
                drain(lambda operation=operation: transfer.upload(operation), "uploaded")
        status = g["client"].sync_once(
            g["service"], g["token"], prepare_push=transfer.ready_to_push
        )
        assert status["pending"] == status["conflicts"] == 0
    finally:
        transfer.close()
    other = peer(g["path"], g["service"], tmp_path_factory)
    assert sorted(tuple(row)[1:] for row in rows(other)) == sorted(
        tuple(row)[1:] for row in rows(g["path"])
    )
    g["client"].save(
        g["client"].new_graph_operation(
            "research_content", g["root"]["entity_id"], {}, action="delete"
        )
    )
    plan._original[0].unlink()  # Successful retry must not need lost original bytes again.
    current = dump(g["path"])
    assert not plan.apply()["applied"] and dump(g["path"]) == current
    reused = prepare(g, plan.request_id).apply()
    assert not reused["applied"] and reused["request_reused"] and reused["originals_verified"]
    assert dump(g["path"]) == current and not rows(g["path"])


def test_manual_restore_rejects_changed_pdf_and_forged_proof_without_writes(retired):
    g = retired
    plan = prepare(g)
    before = dump(g["path"])
    with pytest.raises(ValueError, match="original prepared"):
        replace(plan, _original=None).apply()
    plan._original[0].write_bytes(b"Changed owned PDF")
    with pytest.raises(ValueError, match="changed"):
        plan.apply()
    assert dump(g["path"]) == before and not rows(g["path"])


def test_manual_restore_receipt_failure_rolls_back_and_native_edit_invalidates_plan(
    retired,
    monkeypatch,
):
    g = retired
    with closing(sqlite3.connect(g["path"])) as conn, conn:
        conn.execute(
            "CREATE TRIGGER refuse_restore BEFORE INSERT ON integration_operations "
            "BEGIN SELECT RAISE(ABORT,'restore receipt failure'); END"
        )
    plan = prepare(g)
    before = dump(g["path"])
    with pytest.raises(sqlite3.IntegrityError, match="restore receipt failure"):
        plan.apply()
    assert dump(g["path"]) == before and not rows(g["path"])
    with closing(sqlite3.connect(g["path"])) as conn, conn:
        conn.execute("DROP TRIGGER refuse_restore")
    plan = prepare(g)
    changed = deepcopy(g["root"]["payload"])
    changed["data"]["quote"] = "A later native manual interpretation"
    g["client"].save(
        g["client"].new_graph_operation(
            "research_content", g["root"]["entity_id"], changed, restore=True
        )
    )
    current = dump(g["path"])
    with pytest.raises(ValueError, match="changed"):
        plan.apply()
    assert dump(g["path"]) == current
    # Change owned bytes at the actual writer boundary, after research is written
    # but before commit. The post-write original fence must roll back all SQL.
    from paper_daily import sync_research

    g["client"].save(
        g["client"].new_graph_operation(
            "research_content",
            g["root"]["entity_id"],
            {},
            action="delete",
        )
    )
    plan = prepare(g)
    # CaptureConnection attaches a fresh client for each connection; patch the
    # maintained shared writer callback imported by those real connections.
    write = sync_research.research_writer
    changed = []

    def mutate(conn, operation):
        write(conn, operation)
        if operation["operation_id"] == plan.request_id:
            plan._original[0].write_bytes(b"PDF changed before commit")
            changed.append(True)

    monkeypatch.setattr(sync_research, "research_writer", mutate)
    current = dump(g["path"])
    with pytest.raises(ValueError, match="changed"):
        plan.apply()
    assert changed == [True] and dump(g["path"]) == current
    assert not rows(g["path"])


def test_active_duplicate_or_unavailable_target_never_becomes_a_restore(retired):
    g = retired
    proof = prepare(g)._original
    g["client"].save(
        g["client"].new_graph_operation(
            "research_content", g["root"]["entity_id"], g["root"]["payload"], restore=True
        )
    )
    before = dump(g["path"])
    with pytest.raises(ValueError, match="known retired target"):
        prepare(g)
    assert dump(g["path"]) == before
    g["client"].save(
        g["client"].new_graph_operation(
            "research_content", g["root"]["entity_id"], {}, action="delete"
        )
    )
    duplicate = deepcopy(g["root"]["payload"])
    duplicate["key"] = str(uuid4())
    operation = save(g["client"], duplicate)
    before = dump(g["path"])
    with pytest.raises(ValueError, match="already contains"):
        prepare(g)
    assert dump(g["path"]) == before
    g["client"].save(
        g["client"].new_graph_operation(
            "research_content", operation["entity_id"], {}, action="delete"
        )
    )
    proof[0].unlink()
    before = dump(g["path"])
    with pytest.raises((ValueError, OSError)):
        prepare(g)
    assert dump(g["path"]) == before and not rows(g["path"])


def test_actual_manual_identity_restore_is_explicit_confirmed_and_saved_once(
    retired, app, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox
    from test_workspace_dialog import wait

    from paper_daily.desktop.workspace_dialog import WorkspaceDialog

    g = retired
    owner = WorkspaceDialog(g["old"].journal.path, language="zh-TW")
    owner.show()
    try:
        wait(app, lambda: owner._ready and not owner.busy)
        owner.task_tabs.setCurrentIndex(2)
        owner.device_review.disclosure.setChecked(True)
        ui = owner.device_review.changes
        assert owner.device_review.inspect(g["source"].snapshot)
        wait(app, lambda: not owner.busy)
        assert ui.load(g["path"].parent)
        wait(app, lambda: not owner.busy)
        selected = next(
            row["change_id"]
            for row in ui.page["items"]
            if row["operation_id"] == g["root"]["operation_id"]
        )
        for index in range(ui.rows.count()):
            ui.rows.setCurrentRow(index)
            if ui.selected() == selected:
                break
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        index = ui.action_select.findData("restore")
        assert index >= 0, ui.notice.text()
        assert ui.action_select.currentData() != "restore"
        ui.action_select.setCurrentIndex(index)
        assert ui.plan.manual_restore
        assert "\u539f\u8eab\u5206" in ui.action_select.currentText()
        owned_original = ui.plan._original[0]
        before = dump(g["path"])
        monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.No)
        ui.copy_button.click()
        assert dump(g["path"]) == before and not owner.busy
        monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.Yes)
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        assert len(rows(g["path"])) == 1, owner.status.text()
        pending = attached(g["path"]).journal.pending()
        assert pending[-1]["entity_id"] == g["root"]["entity_id"]
        assert pending[-1]["payload"] == g["root"]["payload"]
        assert not ui.copy_button.isEnabled()
        g["client"].save(
            g["client"].new_graph_operation(
                "research_content",
                g["root"]["entity_id"],
                {},
                action="delete",
            )
        )
        owned_original.unlink()
        before = dump(g["path"])
        assert ui.load(g["path"].parent)
        wait(app, lambda: not owner.busy)
        for index in range(ui.rows.count()):
            ui.rows.setCurrentRow(index)
            if ui.selected() == selected:
                break
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        assert g["root"]["payload"]["data"]["quote"] in ui.old.toPlainText()
        assert ui.action_select.findData("restore") == -1
        assert ui.t["manual_restore_blocked"] in ui.notice.text()
        assert dump(g["path"]) == before
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()
