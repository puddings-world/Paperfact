"""Manual highlight recovery is a distinct exact-source copy, never a note conversion."""

import hashlib
from contextlib import closing
from copy import deepcopy
from uuid import uuid4

import pymupdf
import pytest
from test_sync_device_recovery import dump
from test_sync_files import PAPER, drain
from test_sync_recovery_note_original_group import group as _original_group
from test_sync_recovery_note_original_group import peer
from test_sync_recovery_positioned_note import positioned as positioned
from test_sync_recovery_target import attached
from test_sync_recovery_target import codec as codec
from test_sync_recovery_target import pair as pair
from test_workspace_dialog import app as app
from test_workspace_dialog import wait

from paper_daily import manual_highlight_ops
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_note_copy as recovery
from paper_daily import sync_recovery_target as target
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_authority_backup import BackupCancelled
from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_content import content_id
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_research import research_writer
from paper_daily.sync_source_files import _inspection_paths, publish

original_group = _original_group


def select(group, operation):
    source = candidates.prepare(
        group["old"].journal.path, group["source"].snapshot, group["source"].workspace
    )
    change = next(
        r["change_id"]
        for r in source.page()["items"]
        if r["operation_id"] == operation["operation_id"]
    )
    return dict(group, source=source, change=change, root=operation)


def save(client, payload):
    operation = client.new_graph_operation(
        "research_content",
        content_id(
            payload["scope"],
            payload["feature"],
            payload["key"],
        ),
        payload,
    )
    client.save(operation)
    return operation


@pytest.fixture
def group(original_group):
    old, source, _, path, note, service, sha, data, token = original_group
    anchor = {key: value for key, value in note["payload"]["anchor"].items() if key != "selection"}
    payload = dict(
        scope=dict(kind="paper", id=PAPER),
        feature="manual_highlight",
        key=str(uuid4()),
        source_document_hash=sha,
        data=dict(
            anchor=anchor,
            quote=note["payload"]["anchor"]["selection"]["quote"],
            created_at="2026-11-14T00:00:00+00:00",
        ),
    )
    return select(
        dict(old=old, source=source, path=path, service=service, token=token, sha=sha, data=data),
        save(old, payload),
    )


def plan(group, request=None, **options):
    return recovery.prepare(
        target.observe(group["source"], group["path"]),
        group["change"],
        request or str(uuid4()),
        with_original=options.pop("with_original", True),
        **options,
    )


def rows(path):
    with closing(_readonly_connection(path)) as conn:
        return conn.execute("SELECT * FROM pdf_highlights ORDER BY id").fetchall()


def test_manual_copy_retains_old_and_existing_marks_reaches_peer_and_preserves_later_deletion(
    group,
    pair,
    tmp_path_factory,
):
    client, path = attached(group["path"]), group["path"]
    original = group["root"]["payload"]
    private = deepcopy(original)
    private["data"]["anchor"]["o1"] = 1
    private["data"]["quote"] = "New post-backup"
    save(client, private)
    before, old = rows(path), dump(group["old"].journal.path)
    request = str(uuid4())
    prepared = plan(group, request)
    assert prepared.manual_highlight
    result = prepared.apply()
    assert result["format"] == recovery.MANUAL_FORMAT and result["applied"]
    assert result["entity_id"] != group["root"]["entity_id"]
    after = rows(path)
    assert len(after) == 2 and before[0] in after and after[1][4] == original["data"]["quote"]
    assert dump(group["old"].journal.path) == old
    assert not prepared.apply()["applied"] and not plan(group, request).apply()["applied"]
    pending = client.journal.pending()
    assert [o["payload"]["feature"] for o in pending[-2:]] == [
        "original_source",
        "manual_highlight",
    ]
    copied = pending[-1]
    assert copied["payload"]["data"] == original["data"]
    assert copied["payload"]["key"] != original["key"]
    with closing(_readonly_connection(path)) as conn:
        store, root = _inspection_paths(conn)
    transfer = FileTransfers(
        client,
        BlobStore(store.root),
        group["service"],
        origin="https://recovery.fixture.invalid",
        token=group["token"],
        version_root=root,
    )
    try:
        drain(lambda: transfer.upload(pending[-2]), "uploaded")
        result = client.sync_once(
            group["service"], group["token"], prepare_push=transfer.ready_to_push
        )
        assert result["pending"] == result["conflicts"] == 0
    finally:
        transfer.close()
    other = peer(path, group["service"], tmp_path_factory)
    assert sorted(row[1:] for row in rows(other)) == sorted(row[1:] for row in after)
    client.save(
        client.new_graph_operation("research_content", copied["entity_id"], {}, action="delete")
    )
    current = dump(path)
    pair[3].store._path(BlobManifest(group["sha"], len(group["data"]))).unlink()
    assert not plan(group, request).apply()["applied"] and dump(path) == current
    # The independently owned target original can support an explicitly new copy.
    assert plan(group, with_original=False).apply()["applied"]
    assert len(rows(path)) == 2


@pytest.mark.parametrize("damage", ["quote", "position", "document", "existing_selection"])
def test_forged_or_unavailable_source_never_publishes_a_manual_mark(group, damage):
    payload = deepcopy(group["root"]["payload"])
    if damage == "quote":
        payload["data"]["quote"] = "Words absent from these selected coordinates"
    elif damage == "position":
        payload["data"]["anchor"].update(p0=9000, p1=9000)
    elif damage == "existing_selection":
        save(attached(group["path"]), payload)
    else:
        payload["source_document_hash"] = "f" * 64
        payload["data"]["anchor"]["document_hash"] = "f" * 64
    changed = select(group, save(group["old"], payload))
    before = dump(group["path"])
    with pytest.raises(ValueError):
        plan(changed)
    assert dump(group["path"]) == before
    expected = 1 if damage == "existing_selection" else 0
    assert len(attached(group["path"]).journal.pending()) == expected


@pytest.mark.parametrize("failure", ["write", "cancel"])
def test_manual_mark_failure_rolls_back_original_ownership_outbox_and_copy(
    group, monkeypatch, failure
):
    prepared = plan(group)
    activate, written = CaptureConnection._activate, []

    def failing(conn):
        activate(conn)

        def writer(conn, operation):
            research_writer(conn, operation)
            written.append(operation["payload"].get("feature"))
            if written[-1] == "manual_highlight" and failure == "write":
                raise RuntimeError("simulated manual copy failure")

        conn._capture_client.writer = writer

    monkeypatch.setattr(CaptureConnection, "_activate", failing)
    before = dump(group["path"])
    with pytest.raises(RuntimeError if failure == "write" else BackupCancelled):
        prepared.apply(cancelled=lambda: failure == "cancel" and "manual_highlight" in written)
    assert written == ["original_source", "manual_highlight"]
    assert dump(group["path"]) == before and not attached(group["path"]).journal.pending()
    monkeypatch.setattr(CaptureConnection, "_activate", activate)
    assert prepared.apply()["applied"] and not prepared.apply()["applied"]


def test_hyphenated_multiline_manual_quote_keeps_normal_drawing_semantics(group, pair, tmp_path):
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 50), "A controlled experi-")
        page.insert_text((40, 70), "ment used twenty subjects")
        anchor = dict(p0=0, o0=0, p1=0, o1=len(page.get_text("words")) - 1)
        quote = "A controlled experiment used twenty subjects"
        assert manual_highlight_ops.selection_quote(pdf, anchor) == quote
        data = pdf.tobytes()
    sha = hashlib.sha256(data).hexdigest()
    source = tmp_path / "hyphenated.pdf"
    source.write_bytes(data)
    publish(
        group["old"],
        PAPER,
        source,
        document_hash=sha,
        parent_incarnation=group["root"]["parents"][0]["incarnation"],
        store=pair[3].store,
        version_root=pair[3].root,
        request_id="hyphenated-original",
    )
    payload = deepcopy(group["root"]["payload"])
    payload["key"] = str(uuid4())
    payload["source_document_hash"] = sha
    payload["data"].update(anchor=anchor, quote=quote)
    changed = select(group, save(group["old"], payload))
    assert plan(changed).apply()["applied"]
    assert rows(group["path"])[0][4] == quote


@pytest.mark.parametrize("language,duplicate", [("en", False), ("zh-TW", False), ("en", True)])
def test_native_review_copies_a_readable_manual_selection_once_or_explains_collision(
    group,
    app,
    monkeypatch,
    language,
    duplicate,
):
    from PySide6.QtWidgets import QMessageBox

    from paper_daily.desktop.workspace_dialog import WorkspaceDialog

    if duplicate:
        save(attached(group["path"]), group["root"]["payload"])
    owner = WorkspaceDialog(group["old"].journal.path, language=language)
    owner.show()
    try:
        wait(app, lambda: owner._ready and not owner.busy)
        owner.task_tabs.setCurrentIndex(2)
        owner.device_review.disclosure.setChecked(True)
        ui = owner.device_review.changes
        assert owner.device_review.inspect(group["source"].snapshot)
        wait(app, lambda: not owner.busy)
        assert ui.load(group["path"].parent)
        wait(app, lambda: not owner.busy)
        selected = next(
            r["change_id"]
            for r in ui.page["items"]
            if r["operation_id"] == group["root"]["operation_id"]
        )
        for index in range(ui.rows.count()):
            ui.rows.setCurrentRow(index)
            if ui.selected() == selected:
                break
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        assert group["root"]["payload"]["data"]["quote"] in ui.old.toPlainText()
        assert "scope" not in ui.old.toPlainText()
        if duplicate:
            assert ui.action_select.findData("copy") == -1
            assert not ui.copy_button.isEnabled()
            assert "already contains" in ui.notice.text()
            assert len(rows(group["path"])) == 1
            return
        assert ui.action_select.currentData() == "copy", owner.status.text()
        assert ui.plan.manual_highlight and ui.plan.with_original
        if language == "zh-TW":
            assert "\u756b\u7dda" in ui.action_select.currentText()
        before = dump(group["path"])
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
        ui.copy_button.click()
        assert dump(group["path"]) == before and not owner.busy
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        assert len(rows(group["path"])) == 1, owner.status.text()
        assert len(attached(group["path"]).journal.pending()) == 2
        assert not ui.copy_button.isEnabled()
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()
