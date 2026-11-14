"""Confirmed manual-mark retirement uses native history, never PDF authority or replay."""

import sqlite3
from contextlib import closing
from copy import deepcopy
from uuid import uuid4

import pytest
from test_sync_device_recovery import dump
from test_sync_recovery_manual_highlight import app as app
from test_sync_recovery_manual_highlight import codec as codec
from test_sync_recovery_manual_highlight import group as group
from test_sync_recovery_manual_highlight import original_group as original_group
from test_sync_recovery_manual_highlight import pair as pair
from test_sync_recovery_manual_highlight import peer, rows, save, select
from test_sync_recovery_manual_highlight import positioned as positioned
from test_sync_recovery_target import attached

from paper_daily import sync_recovery_choices as choices
from paper_daily import sync_recovery_note_copy as native
from paper_daily import sync_recovery_target as target
from paper_daily.sync_capture import CaptureConnection, suppress_capture


@pytest.fixture
def removed(group):
    client = attached(group["path"])
    save(client, group["root"]["payload"])
    deleted = group["old"].new_graph_operation(
        "research_content",
        group["root"]["entity_id"],
        {},
        action="delete",
    )
    group["old"].save(deleted)
    selected = select(group, deleted)
    return dict(selected, client=client, created=group["root"])


def prepare(group, request=None):
    return choices.prepare(
        target.observe(group["source"], group["path"]),
        group["change"],
        "remove",
        request or str(uuid4()),
    )


def test_manual_removal_reaches_peer_and_retry_preserves_later_restore(
    removed,
    tmp_path_factory,
    monkeypatch,
):
    g = removed
    private = deepcopy(g["created"]["payload"])
    private["key"] = str(uuid4())
    private["data"]["anchor"]["o1"] = 1
    private["data"]["quote"] = "New post-backup"
    save(g["client"], private)
    before, old = rows(g["path"]), dump(g["old"].journal.path)
    monkeypatch.setattr(native, "_original", lambda *_a, **_k: pytest.fail("No original grant"))
    plan = prepare(g)
    result = plan.apply()
    assert result["choice"] == "remove" and result["applied"] and not result["replayed"]
    assert not result["originals_verified"] and len(rows(g["path"])) == len(before) - 1
    assert dump(g["old"].journal.path) == old
    pending = g["client"].journal.pending()
    assert pending[-1]["entity_id"] == g["root"]["entity_id"]
    assert pending[-1]["action"] == "delete" and pending[-1]["payload"] == {}
    state = g["client"].sync_once(g["service"], g["token"])
    assert state["pending"] == state["conflicts"] == 0
    other = peer(g["path"], g["service"], tmp_path_factory)
    assert sorted(tuple(r)[1:] for r in rows(other)) == sorted(
        tuple(r)[1:] for r in rows(g["path"])
    )
    restored = g["client"].new_graph_operation(
        "research_content",
        g["root"]["entity_id"],
        g["created"]["payload"],
        restore=True,
    )
    g["client"].save(restored)
    current = dump(g["path"])
    assert not plan.apply()["applied"] and dump(g["path"]) == current
    assert not prepare(g, plan.request_id).apply()["applied"]
    assert len(rows(g["path"])) == 2


def test_manual_removal_is_atomic_and_stale_comparison_cannot_delete_new_edits(removed):
    g = removed
    plan = prepare(g)
    with closing(sqlite3.connect(g["path"])) as conn, conn:
        conn.execute(
            "CREATE TRIGGER refuse_removal BEFORE INSERT ON integration_operations "
            "BEGIN SELECT RAISE(ABORT,'synthetic receipt failure'); END"
        )
    # Refresh after the explicit fixture schema change, then fail after native deletion.
    plan = prepare(g)
    before = dump(g["path"])
    with pytest.raises(sqlite3.IntegrityError, match="synthetic receipt failure"):
        plan.apply()
    assert dump(g["path"]) == before
    with closing(sqlite3.connect(g["path"])) as conn, conn:
        conn.execute("DROP TRIGGER refuse_removal")
    plan = prepare(g)
    newer = deepcopy(g["created"]["payload"])
    newer["data"]["quote"] = "Later private selection"
    save(g["client"], newer)
    before = dump(g["path"])
    with pytest.raises(ValueError, match="changed"):
        plan.apply()
    assert dump(g["path"]) == before and len(rows(g["path"])) == 1


def test_manual_removal_refuses_untracked_visible_content_and_absent_target(removed):
    g = removed
    # Deliberate external corruption, not a native write.
    with (
        closing(sqlite3.connect(g["path"], factory=CaptureConnection)) as conn,
        conn,
        suppress_capture(conn),
    ):
        conn.execute("UPDATE pdf_highlights SET quote='Untracked local edit'")
    before = dump(g["path"])
    with pytest.raises(ValueError, match="native history"):
        prepare(g)
    assert dump(g["path"]) == before
    with (
        closing(sqlite3.connect(g["path"], factory=CaptureConnection)) as conn,
        conn,
        suppress_capture(conn),
    ):
        conn.execute(
            "UPDATE pdf_highlights SET quote=?", (g["created"]["payload"]["data"]["quote"],)
        )
    prepare(g).apply()
    with pytest.raises(ValueError, match="active manual highlight"):
        prepare(g)


def test_manual_removal_never_converts_an_arbitrary_note_deletion(removed):
    g = removed
    note = g["old"].new_graph_operation(
        "note",
        str(uuid4()),
        dict(paper_id=g["created"]["payload"]["scope"]["id"], body="Keep my research note"),
    )
    g["old"].save(note)
    deleted = g["old"].new_graph_operation("note", note["entity_id"], {}, action="delete")
    g["old"].save(deleted)
    changed = select(g, deleted)
    before = dump(g["path"])
    with pytest.raises(ValueError, match="manual-highlight deletion"):
        prepare(changed)
    assert dump(g["path"]) == before


def test_actual_manual_removal_requires_confirmation_and_never_duplicates(
    removed, app, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox
    from test_workspace_dialog import wait

    from paper_daily.desktop.workspace_dialog import WorkspaceDialog

    g = removed
    owner = WorkspaceDialog(g["old"].journal.path, language="en")
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
        index = ui.action_select.findData("remove")
        assert index >= 0, ui.notice.text()
        ui.action_select.setCurrentIndex(index)
        assert g["created"]["payload"]["data"]["quote"] in ui.current.toPlainText()
        before = dump(g["path"])
        monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.No)
        ui.copy_button.click()
        assert dump(g["path"]) == before and not owner.busy
        monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.Yes)
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        assert len(rows(g["path"])) == 0, owner.status.text()
        pending = attached(g["path"]).journal.pending()
        assert sum(operation["action"] == "delete" for operation in pending) == 1
        assert not ui.copy_button.isEnabled()
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()
