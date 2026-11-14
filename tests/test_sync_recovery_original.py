"""Explicit immutable-original use/retirement; never delete research or cache bytes."""

import hashlib
import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pymupdf
import pytest
from test_sync_authority_restore_native import publish
from test_sync_device_recovery import dump
from test_sync_files import PAPER
from test_sync_recovery_positioned_note import source_file
from test_sync_recovery_target import attached
from test_sync_recovery_target import codec as codec
from test_sync_recovery_target import pair as pair
from test_workspace_dialog import app as app
from test_workspace_dialog import wait
from test_workspace_sync import Native

from paper_daily import note_positions, sync_bootstrap
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_original as recovery
from paper_daily import sync_recovery_target as target
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_authority_backup import BackupCancelled
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_research import research_writer
from paper_daily.sync_source_files import publish as publish_source
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import SyncSession


@pytest.fixture
def group(pair, tmp_path, tmp_path_factory):
    """One real backup/join, no unrelated pre-backup PDF or offline download."""
    old, files = pair[1], pair[3]
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 60), "New post-backup source evidence")
        data = pdf.tobytes()
    sha = hashlib.sha256(data).hexdigest()
    original = tmp_path / "post-backup.pdf"
    original.write_bytes(data)
    with pymupdf.open(original) as pdf:
        anchor = note_positions.select(
            pdf,
            dict(p0=0, o0=0, p1=0, o1=2, document_hash=sha),
            sha,
        )
    # Real metadata may precede its original transfer. Preserve both note kinds.
    for fields in [
        dict(body="Backed up free-form note"),
        dict(
            body="Private interpretation, not a quotation",
            kind="note",
            created_at="2026-11-14T00:00:00+00:00",
            page=1,
            anchor=anchor,
        ),
    ]:
        old.save(old.new_graph_operation("note", str(uuid4()), dict(paper_id=PAPER, **fields)))
    service = publish(pair, tmp_path)
    token = service.enroll("fresh-research", "original-recovery")
    session = SyncSession(old.journal.path, transport_factory=lambda url: Native(url, service, []))
    destination = tmp_path_factory.mktemp("original-recovery-target") / "workspace"
    session.connect(
        "https://recovery.fixture.invalid", "fresh-research", "original-recovery", token, Ticket()
    )
    try:
        assert sync_bootstrap.join(session, destination, Ticket())["state"] == "metadata_ready"
    finally:
        session.disconnect()
    with old.journal.transaction() as conn:
        parent = old._optimistic_graph(conn)[0][("paper", PAPER)]["incarnation"]
    put = publish_source(
        old,
        PAPER,
        original,
        document_hash=sha,
        parent_incarnation=parent,
        store=files.store,
        version_root=files.root,
        request_id="post-backup-original",
    )
    source = candidates.prepare(old.journal.path, tmp_path / "authority-snapshot", "workspace")
    row = next(row for row in source.page()["items"] if row["operation_id"] == put["operation_id"])
    path = destination / "papers.db"
    # The fixture itself proves data preservation is non-vacuous.
    saved = notes(path)
    assert len(saved) == 2 and any(row[3] is not None for row in saved)
    return dict(
        old=old,
        source=source,
        change=row["change_id"],
        root=put,
        path=path,
        service=service,
        sha=sha,
        data=data,
        token=token,
        store=files.store,
    )


def notes(path):
    with closing(recovery._readonly_connection(path)) as conn:
        return [
            tuple(row) for row in conn.execute("SELECT id,body,page,anchor FROM notes ORDER BY id")
        ]


def selected(group, root):
    previous = group["source"]
    source = candidates.prepare(group["old"].journal.path, previous.snapshot, previous.workspace)
    row = next(row for row in source.page()["items"] if row["operation_id"] == root["operation_id"])
    return dict(group, source=source, change=row["change_id"], root=root)


def prepare(group, request=None):
    return recovery.prepare(
        target.observe(group["source"], group["path"]),
        group["change"],
        request or str(uuid4()),
        action="use_original" if group["root"]["action"] == "put" else "retire_original",
    )


def remove_source(group):
    old, root = group["old"], group["root"]
    deletion = old.new_graph_operation("research_file", root["entity_id"], {}, action="delete")
    old.save(deletion)
    return selected(group, deletion)


def test_retained_source_restores_with_fresh_lifetime_and_old_retirement_retry_is_safe(
    group,
    tmp_path_factory,
):
    from copy import deepcopy

    from paper_daily import sync_artifacts
    from paper_daily.sync_files import descriptor

    old, path, put = group["old"], group["path"], group["root"]
    # Wire metadata alone does not prove a valid artifact JSON body.
    body = json.dumps(
        dict(version=1, paper_id=put["payload"]["paper_id"], document_hash=group["sha"]), indent=2
    ).encode()
    payload = deepcopy(put["payload"])
    payload["body"] = descriptor(body, "application/json")
    sync_artifacts.stage_bytes(group["store"], {payload["body"]["sha256"]: body})
    invalid = old.new_graph_operation("research_file", put["entity_id"], payload)
    old.save(invalid)
    invalid_group = selected(group, invalid)
    untouched = dump(path)
    with pytest.raises(ValueError, match="canonical encoding"):
        prepare(invalid_group)
    assert dump(path) == untouched
    # Repair from the real retained canonical manifest, then retry the same workflow.
    put = old.new_graph_operation("research_file", put["entity_id"], put["payload"])
    old.save(put)
    group = selected(invalid_group, put)
    before, words = dump(old.journal.path), notes(path)
    plan = prepare(group)
    assert plan.comparison[0]["state"] == "absent" and plan.comparison[0]["source_action"] == "put"
    assert plan.apply()["applied"]
    client = attached(path)
    first = client.journal.pending()[-1]
    assert first["payload"] == put["payload"]
    assert first["incarnation"] != put["incarnation"]
    assert source_file(path, group["sha"], len(group["data"])).read_bytes() == group["data"]
    assert not plan.apply()["applied"] and dump(old.journal.path) == before
    from test_sync_files import drain
    from test_workspace_sync import Native

    from paper_daily import sync_bootstrap
    from paper_daily.sync_blobs import BlobStore
    from paper_daily.sync_file_transfers import FileTransfers
    from paper_daily.sync_source_files import _inspection_paths
    from paper_daily.workspace_service import Ticket
    from paper_daily.workspace_sync import SyncSession

    def sync_owner():
        with closing(recovery._readonly_connection(path)) as conn:
            store, versions = _inspection_paths(conn)
        transport = FileTransfers(
            client,
            BlobStore(store.root),
            group["service"],
            origin="https://recovery.fixture.invalid",
            token=group["token"],
            version_root=versions,
        )
        try:
            for operation in client.journal.pending():
                if operation["action"] == "put":
                    drain(lambda op=operation: transport.upload(op), "uploaded")
            result = client.sync_once(
                group["service"], group["token"], prepare_push=transport.ready_to_push
            )
            assert result["pending"] == result["conflicts"] == 0
        finally:
            transport.close()

    sync_owner()
    service, device = group["service"], "original-decision-peer"
    peer_token = service.enroll("fresh-research", device)
    session = SyncSession(path, transport_factory=lambda url: Native(url, service, []))
    folder = tmp_path_factory.mktemp("original-decision-peer") / "workspace"
    session.connect(
        "https://recovery.fixture.invalid", "fresh-research", device, peer_token, Ticket()
    )
    try:
        assert sync_bootstrap.join(session, folder, Ticket())["state"] == "metadata_ready"
    finally:
        session.disconnect()
    other = folder / "papers.db"
    peer = attached(other)

    def download_peer():
        with closing(recovery._readonly_connection(other)) as conn:
            store, versions = _inspection_paths(conn)
        transport = FileTransfers(
            peer,
            BlobStore(store.root),
            service,
            origin="https://recovery.fixture.invalid",
            token=peer_token,
            version_root=versions,
        )
        try:
            drain(lambda: transport.download(put["entity_id"]), "bound")
        finally:
            transport.close()
        assert source_file(other, group["sha"], len(group["data"])).read_bytes() == group["data"]

    download_peer()
    group = remove_source(group)
    deleted_source = dump(old.journal.path)
    old_bytes = source_file(old.journal.path, group["sha"], len(group["data"]))
    unavailable = old_bytes.with_name(old_bytes.name + ".unavailable-fixture")
    old_bytes.rename(unavailable)
    try:
        # Metadata retirement must work offline; restoration still requires real bytes.
        retirement = prepare(group)
        assert retirement.comparison[0]["source_action"] == "delete"
        assert retirement.apply()["applied"]
        before_missing = dump(path)
        with pytest.raises((OSError, ValueError)):
            prepare(selected(group, put))
        assert dump(path) == before_missing
    finally:
        unavailable.rename(old_bytes)
    sync_owner()
    assert peer.sync_once(service, peer_token)["conflicts"] == 0
    with closing(sqlite3.connect(other)) as conn:
        assert desired_file(conn, put["entity_id"]) is None
    assert source_file(other, group["sha"], len(group["data"])).read_bytes() == group["data"]
    with closing(sqlite3.connect(path)) as conn:
        assert desired_file(conn, put["entity_id"]) is None
    # Retirement keeps immutable local bytes and every unrelated note/history row.
    assert notes(path) == words and dump(old.journal.path) == deleted_source
    assert source_file(path, group["sha"], len(group["data"])).read_bytes() == group["data"]
    from paper_daily.sync_source_files import prepare_source, publish_source_in

    with closing(recovery._readonly_connection(path)) as conn:
        store, versions = _inspection_paths(conn)
    cached = source_file(path, group["sha"], len(group["data"]))
    for request, explicit in [(str(uuid4()), False), (first["operation_id"], True)]:
        staged = prepare_source(
            client,
            put["payload"]["paper_id"],
            cached,
            document_hash=group["sha"],
            parent_incarnation=first["parents"][0]["incarnation"],
            store=BlobStore(store.root),
            version_root=versions,
            request_id=request,
        )
        with (
            client.journal.transaction() as conn,
            pytest.raises(ValueError, match="explicit source restoration|new explicit restoration"),
        ):
            publish_source_in(conn, client, staged, restore=explicit)
    restore_group = selected(group, put)
    restore = prepare(restore_group)
    assert restore.comparison[0]["state"] == "retired"
    assert restore.apply()["applied"]
    restored = attached(path).journal.pending()[-1]
    assert restored["action"] == "put" and restored["incarnation"] != first["incarnation"]
    sync_owner()
    assert peer.sync_once(service, peer_token)["conflicts"] == 0
    download_peer()
    with closing(sqlite3.connect(other)) as conn:
        assert desired_file(conn, put["entity_id"])["incarnation"] == restored["incarnation"]
    later = dump(path)
    assert not prepare(group, retirement.request_id).apply()["applied"]
    assert dump(path) == later and notes(path) == words


def test_original_failure_and_retirement_cancellation_rollback_and_retry(group, monkeypatch):
    path, written = group["path"], []
    plan = prepare(group)
    activate = CaptureConnection._activate

    def failing(conn):
        activate(conn)

        def write(conn, operation):
            research_writer(conn, operation)
            written.append(operation)
            raise RuntimeError("simulated original write failure")

        conn._capture_client.writer = write

    monkeypatch.setattr(CaptureConnection, "_activate", failing)
    before = dump(path)
    with pytest.raises(RuntimeError, match="simulated original"):
        plan.apply()
    assert len(written) == 1 and dump(path) == before
    monkeypatch.setattr(CaptureConnection, "_activate", activate)
    assert plan.apply()["applied"]
    group = remove_source(group)
    retirement = prepare(group)
    before = dump(path)
    written.clear()

    def cancelling(conn):
        activate(conn)

        def write(conn, operation):
            research_writer(conn, operation)
            written.append(operation)

        conn._capture_client.writer = write

    monkeypatch.setattr(CaptureConnection, "_activate", cancelling)
    with pytest.raises(BackupCancelled):
        retirement.apply(cancelled=lambda: bool(written))
    assert len(written) == 1 and dump(path) == before
    monkeypatch.setattr(CaptureConnection, "_activate", activate)
    assert retirement.apply()["applied"]


def test_tampered_decision_and_stale_target_refuse_without_research_writes(group):
    path = group["path"]
    plan = prepare(group)
    client = attached(path)
    source = group["root"]
    client.save(
        client.new_graph_operation(
            "note",
            str(uuid4()),
            dict(paper_id=source["payload"]["paper_id"], body="Later private words"),
        )
    )
    before = dump(path)
    with pytest.raises(ValueError, match="target changed"):
        plan.apply()
    assert dump(path) == before
    plan = prepare(group)
    assert plan.apply()["applied"]
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE integration_operations SET result='{}' WHERE id=?", (plan.request_id,))
    before = dump(path)
    with pytest.raises(ValueError, match="receipt changed"):
        plan.apply()
    assert dump(path) == before


@pytest.mark.parametrize("language,retire", [("en", False), ("zh-TW", True)])
def test_native_original_confirmation_cancels_then_saves_one_decision(
    group,
    app,
    monkeypatch,
    language,
    retire,
):
    from PySide6.QtWidgets import QMessageBox

    from paper_daily.desktop.workspace_dialog import WorkspaceDialog

    if retire:
        assert prepare(group).apply()["applied"]
        group = remove_source(group)
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
        wanted = next(
            row["change_id"]
            for row in ui.page["items"]
            if row["operation_id"] == group["root"]["operation_id"]
        )
        for index in range(ui.rows.count()):
            ui.rows.setCurrentRow(index)
            if ui.selected() == wanted:
                break
        before, words = dump(path), notes(path)
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        action = "retire_original" if retire else "use_original"
        assert ui.action_select.currentData() == action, owner.status.text()
        assert group["sha"] in ui.old.toPlainText()
        assert "source_document_hash" not in ui.old.toPlainText()
        if retire:
            assert "\u539f\u6587\u5feb\u53d6" in ui.notice.text()
        else:
            assert "Verified the exact retained PDF" in ui.notice.text()
        prompts = []

        def no(*args, **kwargs):
            prompts.append(args[2])
            return QMessageBox.No

        monkeypatch.setattr(QMessageBox, "question", no)
        ui.copy_button.click()
        assert prompts == [ui.t["confirm_" + action]]
        assert dump(path) == before and not owner.busy
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        with closing(sqlite3.connect(path)) as conn:
            assert (desired_file(conn, group["root"]["entity_id"]) is None) == retire
            count = conn.execute(
                "SELECT count(*) FROM integration_operations WHERE "
                "json_extract(result,'$.format')=? AND "
                "json_extract(result,'$.choice')=?",
                (recovery.FORMAT, action),
            ).fetchone()[0]
            assert count == 1
        assert notes(path) == words
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()
