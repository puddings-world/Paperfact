"""Recorded note retirement preserves native history, other research and later decisions."""

import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_sync_device_recovery import dump
from test_sync_files import PAPER
from test_sync_recovery_choices import select
from test_sync_recovery_note_copy import capture_recovered_authority
from test_sync_recovery_target import attached
from test_sync_recovery_target import codec as codec
from test_sync_recovery_target import pair as pair
from test_sync_recovery_target import prepared as prepared
from test_workspace_dialog import app as app
from test_workspace_dialog import wait
from test_workspace_sync import Native

from paper_daily import sync_bootstrap
from paper_daily import sync_recovery_choices as choices
from paper_daily import sync_recovery_note_copy as native
from paper_daily import sync_recovery_target as target
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_authority_backup import BackupCancelled
from paper_daily.sync_capture import CaptureConnection, suppress_capture
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import SyncSession


def case(request, monkeypatch, *, positioned=False):
    hosted = capture_recovered_authority(monkeypatch)
    data = request.getfixturevalue("prepared")
    old, _, _, path, source = data
    client = attached(path)
    if positioned:
        payload = dict(
            paper_id=PAPER,
            body="Current positioned interpretation",
            kind="note",
            created_at="2026-11-14T00:00:00+00:00",
            page=1,
            anchor=dict(p0=0, o0=0, p1=0, o1=2, document_hash="a" * 64),
        )
        old.save(old.new_graph_operation("note", source["entity_id"], payload))
        client.save(client.new_graph_operation("note", source["entity_id"], payload))
    root = old.new_graph_operation("note", source["entity_id"], {}, action="delete")
    old.save(root)
    observed, change = select(data, root)
    return dict(
        old=old,
        path=path,
        client=client,
        observed=observed,
        change=change,
        root=root,
        hosted=hosted,
    )


def plan(g, request_id=None):
    observed = target.observe(g["observed"].source, g["path"])
    return choices.prepare(observed, g["change"], "remove", request_id or str(uuid4()))


def notes(path):
    with closing(_readonly_connection(path)) as conn:
        return [
            tuple(row)
            for row in conn.execute(
                "SELECT paper_id,body,kind,page,anchor,created_at FROM notes ORDER BY body"
            )
        ]


@pytest.mark.parametrize("positioned", [False, True])
def test_recorded_note_removal_syncs_and_retry_preserves_later_restore(
    request,
    monkeypatch,
    tmp_path_factory,
    positioned,
):
    g = case(request, monkeypatch, positioned=positioned)
    client = g["client"]
    client.save(
        client.new_graph_operation(
            "note",
            str(uuid4()),
            dict(
                paper_id=PAPER,
                body="Keep the unrelated note",
                kind="note",
                created_at="2026-11-14T00:00:00+00:00",
                page=None,
                anchor=None,
            ),
        )
    )
    original = dump(g["old"].journal.path)
    prior = notes(g["path"])
    monkeypatch.setattr(native, "_original", lambda *_a, **_k: pytest.fail("No PDF grant"))
    restorable = target.observe(g["observed"].source, g["path"]).compare(
        g["change"],
    )["target"]["effective_operation"]["payload"]
    decision = plan(g)
    assert decision.note_removal and not decision.manual_restore
    result = decision.apply()
    assert result["applied"] and result["choice"] == "remove" and not result["replayed"]
    assert not result["originals_verified"] and len(notes(g["path"])) == len(prior) - 1
    assert notes(g["path"])[0][1] == "Keep the unrelated note"
    assert dump(g["old"].journal.path) == original
    pending = client.journal.pending()
    assert pending[-1]["entity_id"] == g["root"]["entity_id"]
    assert pending[-1]["entity_type"] == "note" and pending[-1]["action"] == "delete"
    state = client.sync_once(g["hosted"]["service"], g["hosted"]["token"])
    assert state["pending"] == state["conflicts"] == 0
    service = g["hosted"]["service"]
    token = service.enroll("fresh-research", "note-removal-peer")
    destination = tmp_path_factory.mktemp("note-removal-peer") / "workspace"
    joining = SyncSession(g["path"], transport_factory=lambda url: Native(url, service, []))
    joining.connect(
        "https://recovery.fixture.invalid", "fresh-research", "note-removal-peer", token, Ticket()
    )
    try:
        assert sync_bootstrap.join(joining, destination, Ticket())["state"] == "metadata_ready"
    finally:
        joining.disconnect()
    assert notes(destination / "papers.db") == notes(g["path"])
    # Restore through the real native writer; a lost deletion response must not erase it.
    restored = client.new_graph_operation(
        "note",
        g["root"]["entity_id"],
        restorable,
        restore=True,
    )
    client.save(restored)
    latest = dump(g["path"])
    assert decision.apply()["request_reused"]
    assert plan(g, decision.request_id).apply()["request_reused"]
    assert dump(g["path"]) == latest and len(notes(g["path"])) == 2


def test_note_removal_receipt_failure_cancellation_and_stale_edit_are_atomic(request, monkeypatch):
    g = case(request, monkeypatch)
    original = choices._write_receipt
    for cancel in (False, True):
        written = []

        def fault(*args, cancel=cancel, written=written):
            original(*args)
            written.append(True)
            if not cancel:
                raise RuntimeError("synthetic receipt failure")

        monkeypatch.setattr(choices, "_write_receipt", fault)
        decision = plan(g)
        before = dump(g["path"])
        with pytest.raises(BackupCancelled if cancel else RuntimeError):
            decision.apply(
                cancelled=lambda cancel=cancel, written=written: cancel and bool(written)
            )
        assert written and dump(g["path"]) == before
    monkeypatch.setattr(choices, "_write_receipt", original)
    decision = plan(g)
    g["client"].save(
        g["client"].new_graph_operation(
            "note",
            g["root"]["entity_id"],
            dict(paper_id=PAPER, body="New target interpretation"),
        )
    )
    before = dump(g["path"])
    with pytest.raises(ValueError, match="changed"):
        decision.apply()
    assert dump(g["path"]) == before


def test_note_removal_refuses_untracked_rows_and_inactive_targets(request, monkeypatch):
    g = case(request, monkeypatch, positioned=True)
    original = notes(g["path"])[0][1]
    with (
        closing(sqlite3.connect(g["path"], factory=CaptureConnection)) as conn,
        conn,
        suppress_capture(conn),
    ):
        conn.execute("UPDATE notes SET body='Untracked interpretation'")
    before = dump(g["path"])
    with pytest.raises(ValueError, match="native history"):
        plan(g)
    assert dump(g["path"]) == before
    with (
        closing(sqlite3.connect(g["path"], factory=CaptureConnection)) as conn,
        conn,
        suppress_capture(conn),
    ):
        conn.execute("UPDATE notes SET body=?", (original,))
    decision = plan(g)
    decision.apply()
    before = dump(g["path"])
    with pytest.raises(ValueError, match="active native note"):
        plan(g)
    assert dump(g["path"]) == before


def test_actual_note_removal_confirmation_is_note_specific_and_repeated_clicks_are_safe(
    request,
    monkeypatch,
    app,
):
    from PySide6.QtWidgets import QMessageBox

    from paper_daily.desktop.workspace_dialog import WorkspaceDialog

    g = case(request, monkeypatch)
    owner = WorkspaceDialog(g["old"].journal.path, language="zh-TW")
    owner.show()
    try:
        wait(app, lambda: owner._ready and not owner.busy)
        owner.task_tabs.setCurrentIndex(2)
        owner.device_review.disclosure.setChecked(True)
        ui = owner.device_review.changes
        assert owner.device_review.inspect(g["observed"].source.snapshot)
        wait(app, lambda: not owner.busy)
        assert ui.load(g["path"].parent)
        wait(app, lambda: not owner.busy)
        for index in range(ui.rows.count()):
            ui.rows.setCurrentRow(index)
            if ui.selected() == g["change"]:
                break
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        index = ui.action_select.findData("remove")
        assert index >= 0, ui.notice.text()
        ui.action_select.setCurrentIndex(index)
        assert ui.action_select.currentText() == "\u79fb\u9664\u76ee\u524d\u7b46\u8a18"
        assert "\u7b46\u8a18" in ui.notice.text()
        before = dump(g["path"])
        prompts = []

        def answer(*args):
            prompts.append(args)
            return QMessageBox.No if len(prompts) == 1 else QMessageBox.Yes

        monkeypatch.setattr(QMessageBox, "question", answer)
        ui.copy_button.click()
        assert not owner.busy and dump(g["path"]) == before
        assert prompts[0][2] == ui.t["confirm_remove_note"]
        assert "\u7b46\u8a18" in prompts[0][2]
        assert prompts[0][-1] == QMessageBox.No
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        assert notes(g["path"]) == []
        assert sum(op["action"] == "delete" for op in g["client"].journal.pending()) == 1
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()
