"""Complete explanation-link recovery through the native shared operation boundary."""

import sqlite3
from contextlib import closing
from copy import deepcopy
from uuid import uuid4

import pytest
from test_sync_device_recovery import dump
from test_sync_recovery_highlight_group import original_group as original_group
from test_sync_recovery_highlight_group import positioned as positioned
from test_sync_recovery_reading_context import group as group
from test_sync_recovery_reading_context import highlights as highlights
from test_sync_recovery_reading_context import linked
from test_sync_recovery_target import attached
from test_sync_recovery_target import codec as codec
from test_sync_recovery_target import pair as pair
from test_workspace_dialog import app as app
from test_workspace_dialog import wait

from paper_daily import sync_recovery_reading_group as recovery
from paper_daily import sync_recovery_target as target
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_authority_backup import BackupCancelled
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_research import research_writer


def prepare(group, request=None, **kwargs):
    return recovery.prepare(
        target.observe(group["source"], group["path"]),
        group["change"],
        request or str(uuid4()),
        **kwargs,
    )


def content(path):
    with closing(_readonly_connection(path)) as conn:
        return {
            table: conn.execute("SELECT * FROM " + table).fetchall()
            for table in (
                "dives",
                "close_readings",
                "paper_highlight_analysis",
                "paper_reading_links",
            )
        }


def test_complete_group_preserves_original_inputs_and_retry_never_overwrites_later_edits(
    group,
    tmp_path_factory,
):
    old, path = group["old"], group["path"]
    source_before = dump(old.journal.path)
    plan = prepare(group)
    assert [m["feature"] for m in plan.comparison] == list(recovery.FEATURES)
    result = plan.apply()
    assert result["applied"] and result["choice"] == "reading_group"
    assert not result["recovery_complete"] and not result["remote_acceptance_checked"]
    client = attached(path)
    pending = client.journal.pending()
    assert [o["entity_type"] for o in pending] == ["research_file"] + ["research_content"] * 4
    assert [o["payload"] for o in pending[1:]] == [
        o["payload"] for o in [*group["inputs"], group["root"]]
    ]
    assert dump(old.journal.path) == source_before
    # Keep independently curated PDF layers separate from explanation-group recovery.
    from paper_daily.sync_content import content_id

    marker = deepcopy(group["marks"][0])
    client.save(
        client.new_graph_operation(
            "research_content",
            content_id(marker["scope"], marker["feature"], marker["key"]),
            marker,
        )
    )
    manual = dict(
        scope=marker["scope"],
        feature="manual_highlight",
        key=str(uuid4()),
        source_document_hash=group["sha"],
        data=dict(
            anchor=marker["data"]["anchor"],
            quote=marker["data"]["quote"],
            created_at="2026-11-14T00:00:00+00:00",
        ),
    )
    client.save(
        client.new_graph_operation(
            "research_content",
            content_id(manual["scope"], manual["feature"], manual["key"]),
            manual,
        )
    )
    with closing(_readonly_connection(path)) as conn:
        layers = [
            conn.execute("SELECT * FROM " + table).fetchall()
            for table in ("pdf_highlights", "pdf_ai_highlights")
        ]
    assert all(layers)
    from test_sync_files import drain
    from test_sync_recovery_note_original_group import peer
    from test_sync_recovery_positioned_note import source_file

    from paper_daily.sync_blobs import BlobStore
    from paper_daily.sync_file_transfers import FileTransfers
    from paper_daily.sync_source_files import _inspection_paths

    with closing(_readonly_connection(path)) as conn:
        store, version_root = _inspection_paths(conn)
    transfer = FileTransfers(
        client,
        BlobStore(store.root),
        group["service"],
        origin="https://recovery.fixture.invalid",
        token=group["token"],
        version_root=version_root,
    )
    try:
        drain(lambda: transfer.upload(pending[0]), "uploaded")
        synced = client.sync_once(
            group["service"], group["token"], prepare_push=transfer.ready_to_push
        )
        assert synced["pending"] == synced["conflicts"] == 0
    finally:
        transfer.close()
    other = peer(path, group["service"], tmp_path_factory)
    assert content(other) == content(path)
    assert source_file(other, group["sha"], len(group["data"])).read_bytes() == group["data"]
    assert not plan.apply()["applied"]
    current = pending[1]
    payload = deepcopy(current["payload"])
    payload["data"]["body"] = "Later private explanation"
    client.save(client.new_graph_operation("research_content", current["entity_id"], payload))
    later = dump(path)
    assert not prepare(group, plan.request_id).apply()["applied"]
    assert dump(path) == later
    original_path = source_file(old.journal.path, group["sha"], len(group["data"]))
    unavailable = original_path.with_name(original_path.name + ".unavailable-fixture")
    original_path.rename(unavailable)
    try:
        assert not prepare(group, plan.request_id).apply()["applied"]
        assert dump(path) == later
    finally:
        unavailable.rename(original_path)
    with pytest.raises(ValueError, match="before replacement"):
        prepare(group)
    assert dump(path) == later
    explicit = prepare(group, replace=True)
    assert explicit.apply()["applied"]
    with closing(_readonly_connection(path)) as conn:
        assert [
            conn.execute("SELECT * FROM " + table).fetchall()
            for table in ("pdf_highlights", "pdf_ai_highlights")
        ] == layers
    # Native original ownership is retained without changing the active PDF.
    with closing(_readonly_connection(path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] >= 1


def test_optional_absence_requires_explicit_choice_and_retries_preserve_later_explanation(group):
    old, path = group["old"], group["path"]
    dive = group["inputs"][0]
    old.save(old.new_graph_operation("research_content", dive["entity_id"], {}, action="delete"))
    group = linked(group, bodies=[None, group["inputs"][1]["payload"]["data"]["body"]])
    client = attached(path)
    client.save(client.new_graph_operation("research_content", dive["entity_id"], dive["payload"]))
    before = dump(path)
    with pytest.raises(ValueError, match="before replacement"):
        prepare(group)
    assert dump(path) == before
    plan = prepare(group, replace=True)
    assert plan.comparison[0]["source"] is None
    assert plan.comparison[0]["current"]["body"] == dive["payload"]["data"]["body"]
    assert plan.apply()["applied"] and content(path)["dives"] == []
    assert not plan.apply()["applied"]
    client.save(
        client.new_graph_operation(
            "research_content", dive["entity_id"], dive["payload"], restore=True
        )
    )
    later = dump(path)
    assert not prepare(group, plan.request_id, replace=True).apply()["applied"]
    assert dump(path) == later


@pytest.mark.parametrize("failure", ["exception", "cancel"])
def test_partial_write_failure_rolls_back_original_contents_outbox_and_receipt(
    group, monkeypatch, failure
):
    plan, written, path = prepare(group), [], group["path"]
    activate = CaptureConnection._activate

    def failing(conn):
        activate(conn)

        def write(conn, operation):
            research_writer(conn, operation)
            written.append(operation["payload"].get("feature"))
            if operation["payload"].get("feature") == "close_reading" and failure == "exception":
                raise RuntimeError("simulated reading child failure")

        conn._capture_client.writer = write

    monkeypatch.setattr(CaptureConnection, "_activate", failing)
    before = dump(path)
    with pytest.raises(RuntimeError if failure == "exception" else BackupCancelled):
        plan.apply(cancelled=lambda: failure == "cancel" and "close_reading" in written)
    assert written[-2:] == ["dive", "close_reading"]
    assert dump(path) == before and attached(path).journal.pending() == []
    monkeypatch.setattr(CaptureConnection, "_activate", activate)
    assert plan.apply()["applied"]


def test_corrupt_receipt_and_uncaptured_private_content_refuse_without_writes(group):
    path = group["path"]
    plan = prepare(group)
    assert plan.apply()["applied"]
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE integration_operations SET result='{}' WHERE id=?", (plan.request_id,))
    before = dump(path)
    with pytest.raises(ValueError, match="receipt changed"):
        plan.apply()
    assert dump(path) == before
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.create_function("paperfact_capture", 3, lambda *_: None)
        conn.execute("UPDATE dives SET body='Uncaptured private explanation'")
    before = dump(path)
    with pytest.raises(ValueError, match="Visible research differs"):
        prepare(group, replace=True)
    assert dump(path) == before


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_native_confirmation_cancels_then_saves_absence_and_all_members_once(
    group,
    app,
    monkeypatch,
    language,
):
    from PySide6.QtWidgets import QMessageBox

    from paper_daily.desktop.workspace_dialog import WorkspaceDialog

    old, path = group["old"], group["path"]
    dive = group["inputs"][0]
    old.save(old.new_graph_operation("research_content", dive["entity_id"], {}, action="delete"))
    group = linked(group, bodies=[None, group["inputs"][1]["payload"]["data"]["body"]])
    client = attached(path)
    client.save(client.new_graph_operation("research_content", dive["entity_id"], dive["payload"]))
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
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        assert ui.action_select.currentData() == "reading_group", owner.status.text()
        assert ui.t["absent"] in ui.old.toPlainText()
        assert "The original problem and assumptions." in ui.current.toPlainText()
        assert "New post-backup source evidence" in ui.old.toPlainText()
        before = dump(path)
        prompts = []

        def answer(*args, **kwargs):
            prompts.append(args[2])
            return QMessageBox.No

        monkeypatch.setattr(QMessageBox, "question", answer)
        ui.copy_button.click()
        assert prompts == [ui.t["confirm_reading_group"]]
        assert ("clears" if language == "en" else "\u6e05\u9664") in prompts[0]
        assert dump(path) == before and not owner.busy
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        assert content(path)["dives"] == []
        assert all(
            content(path)[table]
            for table in (
                "close_readings",
                "paper_highlight_analysis",
                "paper_reading_links",
            )
        )
        with closing(_readonly_connection(path)) as conn:
            assert (
                conn.execute(
                    "SELECT count(*) FROM integration_operations WHERE "
                    "json_extract(result,'$.format')=?",
                    (recovery.FORMAT,),
                ).fetchone()[0]
                == 1
            )
        from paper_daily import sync_recovery_reading_context as source_context

        monkeypatch.setattr(
            source_context,
            "resolve",
            lambda *a, **k: pytest.fail("Saved UI decision reparsed the source original"),
        )
        # Saving invalidates the old target observation; use the actual reload flow.
        assert ui.load(path.parent)
        wait(app, lambda: not owner.busy)
        for index in range(ui.rows.count()):
            ui.rows.setCurrentRow(index)
            if ui.selected() == selected:
                break
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        assert ui.t["already_action"] == ui.notice.text()
        assert ui.action_plans["reading_group"][0].already
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()
