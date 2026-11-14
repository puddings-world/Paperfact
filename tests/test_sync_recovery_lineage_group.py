"""Exact multi-original native Lineage recovery; never replay an old source grant."""

import sqlite3
from contextlib import closing
from copy import deepcopy
from uuid import uuid4

import pytest
from test_lineage_live_journey import setup_publication
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_sync_authority_restore_native import publish
from test_sync_device_recovery import dump
from test_sync_recovery_target import attached
from test_workspace_dialog import app as app
from test_workspace_dialog import wait
from test_workspace_sync import Native

from paper_daily import (
    lineage_content,
    lineage_projection,
    lineage_sets,
    lineage_wire,
    sync_bootstrap,
)
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_lineage_group as recovery
from paper_daily import sync_recovery_target as target
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_authority_backup import BackupCancelled
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_research import research_writer
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import SyncSession


@pytest.fixture
def group(selected, monkeypatch, tmp_path, tmp_path_factory):
    original = selected[0]
    service = publish(original, tmp_path)
    token = service.enroll("fresh-research", "travel")
    old = original[1]
    session = SyncSession(old.journal.path, transport_factory=lambda url: Native(url, service, []))
    destination = tmp_path_factory.mktemp("lineage-recovery-target") / "workspace"
    session.connect("https://recovery.fixture.invalid", "fresh-research", "travel", token, Ticket())
    try:
        assert sync_bootstrap.join(session, destination, Ticket())["state"] == "metadata_ready"
    finally:
        session.disconnect()
    old, _candidate, _receipt, root, _files = setup_publication(selected, monkeypatch)
    source = candidates.prepare(old.journal.path, tmp_path / "authority-snapshot", "workspace")
    change = next(
        row["change_id"]
        for row in source.page(limit=50)["items"]
        if row["operation_id"] == root["operation_id"]
    )
    return dict(
        old=old,
        root=root,
        source=source,
        change=change,
        path=destination / "papers.db",
        service=service,
        token=token,
    )


def prepare(group, request=None, **kwargs):
    return recovery.prepare(
        target.observe(group["source"], group["path"]),
        group["change"],
        request or str(uuid4()),
        **kwargs,
    )


def portable(path):
    with closing(_readonly_connection(path)) as conn:
        row = conn.execute(
            "SELECT " + ",".join(lineage_sets.COLUMNS.split()) + " FROM " + lineage_sets.TABLE
        ).fetchone()
        return lineage_wire.encode_row(
            conn, dict(zip(lineage_sets.COLUMNS.split(), row, strict=True))
        )


def test_group_rebinds_all_three_originals_and_retry_preserves_later_versions(
    group,
    tmp_path_factory,
):
    from test_lineage_live_conflicts import edit

    old, path, root = group["old"], group["path"], group["root"]
    before = dump(old.journal.path), dump(path)
    plan = prepare(group)
    assert len(plan.comparison[0]["originals"]) == 3
    assert (dump(old.journal.path), dump(path)) == before
    result = plan.apply()
    assert result["applied"] and result["choice"] == "lineage_group"
    assert not result["recovery_complete"] and not result["remote_acceptance_checked"]
    client = attached(path)
    pending = client.journal.pending()
    assert [op["entity_type"] for op in pending] == ["research_file"] * 3 + ["research_content"]
    assert pending[-1]["payload"] == root["payload"] == portable(path)
    assert pending[-1]["source_dependencies"] != root["source_dependencies"]
    assert pending[-1]["workspace_id"] != root["workspace_id"]
    assert dump(old.journal.path) == before[0]
    assert not plan.apply()["applied"]
    assert not prepare(group, plan.request_id).apply()["applied"]
    from test_sync_files import drain

    from paper_daily.sync_blobs import BlobStore
    from paper_daily.sync_file_transfers import FileTransfers
    from paper_daily.sync_source_files import _inspection_paths

    with closing(_readonly_connection(path)) as conn:
        store, versions = _inspection_paths(conn)
    transfer = FileTransfers(
        client,
        BlobStore(store.root),
        group["service"],
        origin="https://recovery.fixture.invalid",
        token=group["token"],
        version_root=versions,
    )
    try:
        for original in pending[:-1]:
            drain(lambda op=original: transfer.upload(op), "uploaded")
        for _ in range(4):
            synced = client.sync_once(
                group["service"], group["token"], prepare_push=transfer.ready_to_push
            )
            if not synced["pending"]:
                break
        assert synced["pending"] == synced["conflicts"] == 0
    finally:
        transfer.close()
    device, service = "lineage-independent-peer", group["service"]
    token = service.enroll("fresh-research", device)
    session = SyncSession(path, transport_factory=lambda url: Native(url, service, []))
    destination = tmp_path_factory.mktemp("lineage-independent-peer") / "workspace"
    session.connect("https://recovery.fixture.invalid", "fresh-research", device, token, Ticket())
    try:
        assert sync_bootstrap.join(session, destination, Ticket())["state"] == "metadata_ready"
    finally:
        session.disconnect()
    other = destination / "papers.db"
    assert portable(other) == root["payload"]
    peer = attached(other)
    with closing(_readonly_connection(other)) as conn:
        store, versions = _inspection_paths(conn)
    transfer = FileTransfers(
        peer,
        BlobStore(store.root),
        service,
        origin="https://recovery.fixture.invalid",
        token=token,
        version_root=versions,
    )
    try:
        for original in pending[:-1]:
            drain(lambda op=original: transfer.download(op["entity_id"]), "bound")
    finally:
        transfer.close()
    with closing(_readonly_connection(other)) as conn:
        for original in pending[:-1]:
            asset = original["payload"]["assets"][0]
            proof = recovery.native.inspect_original(
                conn,
                original["payload"]["paper_id"],
                original["parents"][0],
                asset["sha256"],
                lambda: None,
            )
            assert proof[0].stat().st_size == asset["size"]
    from test_lineage_jobs import work

    from paper_daily import lineage_bound_originals
    from paper_daily import research_generation as generation
    from paper_daily.manual_highlight_ops import observe_owner
    from paper_daily.sync_content import _local_scope

    with closing(_readonly_connection(other)) as conn:
        local = _local_scope(conn, root["payload"]["scope"], required=True)
        row = lineage_projection._current(conn, local, root["payload"]["key"])
    owner = observe_owner(other, local, expected_native=generation._identity(other))
    for source in lineage_sets.decode(row["body_json"])["report"]["sources"]:
        verified = work(lineage_bound_originals.prepare, owner, row, source["id"])
        assert lineage_bound_originals.for_delivery(verified, owner, row, source["id"])
    later = edit(client, pending[-1], "2026-11-14T03:00:00+00:00")
    changed = dump(path)
    assert not prepare(group, plan.request_id).apply()["applied"] and dump(path) == changed
    with pytest.raises(ValueError, match="before replacement"):
        prepare(group)
    assert portable(path) == later["payload"]
    assert prepare(group, replace=True).apply()["applied"]
    assert portable(path) == root["payload"]
    with closing(_readonly_connection(path)) as conn:
        assert conn.execute("SELECT count(*) FROM " + lineage_projection.HISTORY).fetchone()[0] >= 3


@pytest.mark.parametrize("failure", ["exception", "cancel"])
def test_child_failure_rolls_back_all_originals_report_schema_outbox_and_receipt(
    group,
    monkeypatch,
    failure,
):
    path, written = group["path"], []
    plan = prepare(group)
    activate = CaptureConnection._activate

    def failing(conn):
        activate(conn)

        def write(conn, operation):
            research_writer(conn, operation)
            written.append(operation["entity_type"])
            if len(written) == 2 and failure == "exception":
                raise RuntimeError("simulated multi-original failure")

        conn._capture_client.writer = write

    monkeypatch.setattr(CaptureConnection, "_activate", failing)
    before = dump(path)
    with pytest.raises(RuntimeError if failure == "exception" else BackupCancelled):
        plan.apply(cancelled=lambda: failure == "cancel" and len(written) == 2)
    assert written == ["research_file"] * 2
    assert dump(path) == before and attached(path).journal.pending() == []
    monkeypatch.setattr(CaptureConnection, "_activate", activate)
    assert plan.apply()["applied"] and portable(path) == group["root"]["payload"]


def test_schema_valid_false_passage_and_corrupt_receipt_refuse_without_writes(group):
    plan = prepare(group)
    assert plan.apply()["applied"]
    with closing(sqlite3.connect(group["path"])) as conn, conn:
        conn.execute("UPDATE integration_operations SET result='{}' WHERE id=?", (plan.request_id,))
    before = dump(group["path"])
    with pytest.raises(ValueError, match="receipt changed"):
        plan.apply()
    assert dump(group["path"]) == before
    root = group["root"]
    payload = deepcopy(root["payload"])
    report = payload["data"]["body_json"]["report"]
    passage = report["statements"][0]["passages"][0]
    passage["quote"] = "A fabricated quotation absent from every selected PDF."
    passage["id"] = lineage_content.passage_id(passage)
    report["id"] = lineage_content.hashed({k: v for k, v in report.items() if k != "id"})
    lineage_wire.validate_payload(payload)
    old = group["old"]
    with old.journal.transaction() as conn:
        op = old._new_graph_operation(
            conn, "research_content", root["entity_id"], payload, lineage_template=root
        )
        old.journal.apply_in(conn, op, old.writer)
    index = candidates.prepare(old.journal.path, group["source"].snapshot, "workspace")
    change = next(
        row["change_id"]
        for row in index.page(limit=50)["items"]
        if row["operation_id"] == op["operation_id"]
    )
    with pytest.raises(ValueError, match="passage no longer matches"):
        recovery.prepare(target.observe(index, group["path"]), change, str(uuid4()), replace=True)
    assert dump(group["path"]) == before


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_native_lineage_comparison_cancel_confirm_and_repeated_click_save_once(
    group,
    app,
    monkeypatch,
    language,
):
    from PySide6.QtWidgets import QMessageBox

    from paper_daily.desktop.workspace_dialog import WorkspaceDialog

    old, path = group["old"], group["path"]
    owner = WorkspaceDialog(old.journal.path, language=language)
    owner.show()
    try:
        wait(app, lambda: owner._ready and not owner.busy)
        owner.task_tabs.setCurrentIndex(2)
        owner.device_review.disclosure.setChecked(True)
        ui = owner.device_review.changes
        assert owner.device_review.inspect(group["source"].snapshot)
        wait(app, lambda: not owner.busy)
        assert ui.load(path.parent)
        wait(app, lambda: not owner.busy)
        selected = next(
            row["change_id"]
            for row in ui.page["items"]
            if row["operation_id"] == group["root"]["operation_id"]
        )
        for index in range(ui.rows.count()):
            ui.rows.setCurrentRow(index)
            if ui.selected() == selected:
                break
        before = dump(path)
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        assert ui.action_select.currentData() == "lineage_group", owner.status.text()
        assert "The focal study supplies a concrete change." in ui.old.toPlainText()
        assert "Actual selected original 0." in ui.old.toPlainText()
        assert "Prior selected paper" in ui.old.toPlainText()
        assert "body_json" not in ui.old.toPlainText() and dump(path) == before
        if language == "zh-TW":
            assert "\u5df2\u6838\u5c0d" in ui.notice.text()
        else:
            assert "not certified" in ui.notice.text()
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
        ui.copy_button.click()
        assert dump(path) == before and not owner.busy
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        assert portable(path) == group["root"]["payload"]
        with closing(_readonly_connection(path)) as conn:
            assert (
                conn.execute(
                    "SELECT count(*) FROM integration_operations WHERE "
                    "json_extract(result,'$.format')=?",
                    (recovery.FORMAT,),
                ).fetchone()[0]
                == 1
            )
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()
