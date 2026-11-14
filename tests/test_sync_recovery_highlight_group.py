"""Recovered highlights retain exact originals, full reasons and curated layers."""

from contextlib import closing
from copy import deepcopy
from uuid import uuid4

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

from paper_daily import pdf_highlights
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_highlight_group as recovery
from paper_daily import sync_recovery_target as target
from paper_daily.highlight_draft_verification import _source_text_hash
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_authority_backup import BackupCancelled
from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_content import content_id
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_research import research_writer
from paper_daily.sync_source_files import _inspection_paths

original_group = _original_group
STAMP = "2026-11-14T00:00:00+00:00"


@pytest.fixture
def group(original_group, pair):
    old, previous, _, path, _, service, sha, data, token = original_group
    items = [
        dict(
            text="New post-backup source evidence",
            page=1,
            kind="evidence",
            reason="A researcher-edited explanation of why this result matters.",
            source="page:1",
        ),
        dict(
            text="post-backup source evidence",
            page=1,
            kind="definition",
            reason="The complete definition is needed for later comparison.",
            source="page:1",
        ),
    ]
    body = dict(
        items=items, coverage=dict(pages=1, empty_pages=[], chunks=1, has_page_numbers=True)
    )
    source_hash = _source_text_hash(data, lambda: False)
    payload = dict(
        scope=dict(kind="paper", id=PAPER),
        feature="highlight_analysis",
        key="main",
        source_document_hash=sha,
        data=dict(body_json=body, source_hash=source_hash, document_hash=sha, written_at=STAMP),
    )
    root = old.new_graph_operation(
        "research_content", content_id(payload["scope"], payload["feature"], "main"), payload
    )
    old.save(root)
    _, located, unmatched = pdf_highlights.locate(
        pair[3].store._path(BlobManifest(sha, len(data))), body
    )
    assert not unmatched
    marks = []
    for index, (key, anchor, item) in enumerate(located):
        mark = dict(
            scope=payload["scope"],
            feature="ai_highlight",
            key=sha + ":" + key,
            source_document_hash=sha,
            data=dict(
                analysis_hash=source_hash,
                anchor=anchor,
                quote=item["text"],
                reason=item["reason"],
                hidden=1 if index == 0 else 0,
            ),
        )
        marks.append(mark)
        old.save(
            old.new_graph_operation(
                "research_content",
                content_id(
                    mark["scope"],
                    mark["feature"],
                    mark["key"],
                ),
                mark,
            )
        )
    source = candidates.prepare(old.journal.path, previous.snapshot, previous.workspace)
    change = next(
        r["change_id"] for r in source.page()["items"] if r["operation_id"] == root["operation_id"]
    )
    return dict(
        old=old,
        source=source,
        change=change,
        path=path,
        root=root,
        service=service,
        sha=sha,
        data=data,
        token=token,
        marks=marks,
    )


def plan(group, request=None, **kwargs):
    return recovery.prepare(
        target.observe(group["source"], group["path"]),
        group["change"],
        request or str(uuid4()),
        **kwargs,
    )


def rows(path):
    with closing(_readonly_connection(path)) as conn:
        return {
            table: conn.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall()
            for table in ("paper_highlight_analysis", "pdf_ai_highlights", "pdf_highlights")
        }


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


def test_complete_group_keeps_manual_hidden_and_unrelated_marks_and_reaches_native_peer(
    group,
    tmp_path_factory,
    monkeypatch,
):
    from paper_daily import llm

    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Recovery called AI"))
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Recovery captured AI"))

    path, client = group["path"], attached(group["path"])
    manual = dict(
        scope=dict(kind="paper", id=PAPER),
        feature="manual_highlight",
        key=str(uuid4()),
        source_document_hash=group["sha"],
        data=dict(
            anchor=group["marks"][0]["data"]["anchor"],
            quote=group["marks"][0]["data"]["quote"],
            created_at=STAMP,
        ),
    )
    save(client, manual)
    chosen = deepcopy(group["marks"][1])
    chosen["data"]["hidden"] = 1
    save(client, chosen)
    unrelated = deepcopy(group["marks"][0])
    unrelated["key"] = group["sha"] + ":" + "e" * 64
    unrelated["data"].update(
        quote="source evidence", reason="Keep this separate annotation.", hidden=0
    )
    save(client, unrelated)
    before = rows(path)
    source_before = dump(group["old"].journal.path)
    request = str(uuid4())
    prepared = plan(group, request, replace=True)
    assert len(prepared.comparison) == 3 and prepared.comparison[2]["source"]["hidden"] == 1
    assert prepared.apply()["applied"]
    after = rows(path)
    assert after["pdf_highlights"] == before["pdf_highlights"]
    assert before["pdf_ai_highlights"][1] in after["pdf_ai_highlights"]
    assert len(after["pdf_ai_highlights"]) == 3
    assert dump(group["old"].journal.path) == source_before
    assert not prepared.apply()["applied"]
    assert not plan(group, request, replace=True).apply()["applied"]
    pending = client.journal.pending()
    assert [o["payload"]["feature"] for o in pending[-4:]] == [
        "original_source",
        "highlight_analysis",
        "ai_highlight",
        "ai_highlight",
    ]
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
        for item in pending:
            if item["entity_type"] == "research_file":
                drain(lambda item=item: transfer.upload(item), "uploaded")
        result = client.sync_once(
            group["service"], group["token"], prepare_push=transfer.ready_to_push
        )
        assert result["pending"] == result["conflicts"] == 0
    finally:
        transfer.close()
    other = peer(path, group["service"], tmp_path_factory)
    # Local integer IDs may differ; compare the portable row values.
    remote = rows(other)
    assert remote["paper_highlight_analysis"] == after["paper_highlight_analysis"]
    assert sorted(r[1:] for r in remote["pdf_ai_highlights"]) == sorted(
        r[1:] for r in after["pdf_ai_highlights"]
    )
    assert sorted(r[1:] for r in remote["pdf_highlights"]) == sorted(
        r[1:] for r in after["pdf_highlights"]
    )
    assert len(pdf_highlights.list_marks("sync:" + PAPER, group["sha"], database=other)) == 2


@pytest.mark.parametrize("failure", ["write", "cancel"])
def test_failure_after_first_mark_rolls_back_original_analysis_marks_outbox_and_receipt(
    group,
    monkeypatch,
    failure,
):
    prepared = plan(group)
    original, written = CaptureConnection._activate, []

    def activate(conn):
        original(conn)

        def writer(conn, operation):
            research_writer(conn, operation)
            written.append(operation["payload"].get("feature"))
            if written[-1] == "ai_highlight" and failure == "write":
                raise RuntimeError("simulated first highlight failure")

        conn._capture_client.writer = writer

    monkeypatch.setattr(CaptureConnection, "_activate", activate)
    before = dump(group["path"])
    with pytest.raises(RuntimeError if failure == "write" else BackupCancelled):
        prepared.apply(cancelled=lambda: failure == "cancel" and "ai_highlight" in written)
    assert written == ["original_source", "highlight_analysis", "ai_highlight"]
    assert dump(group["path"]) == before and not attached(group["path"]).journal.pending()
    monkeypatch.setattr(CaptureConnection, "_activate", original)
    assert prepared.apply()["applied"] and not prepared.apply()["applied"]


@pytest.mark.parametrize("damage", ["unlocated", "wrong_original_text", "changed_source_quote"])
def test_unverified_analysis_never_publishes_partial_highlights(group, damage):
    old, previous = group["old"], group["source"]
    payload = deepcopy(group["root"]["payload"])
    if damage == "unlocated":
        payload["data"]["body_json"]["items"][0]["text"] = (
            "A quotation absent from the original paper"
        )
    elif damage == "wrong_original_text":
        payload["data"]["source_hash"] = "f" * 64
    else:
        mark = deepcopy(group["marks"][0])
        mark["data"]["quote"] = "Another quote under the unchanged key"
        save(old, mark)
    root = save(old, payload)
    source = candidates.prepare(old.journal.path, previous.snapshot, previous.workspace)
    changed = dict(
        group,
        source=source,
        root=root,
        change=next(
            r["change_id"]
            for r in source.page()["items"]
            if r["operation_id"] == root["operation_id"]
        ),
    )
    before = dump(group["path"])
    with pytest.raises(
        ValueError,
        match={
            "unlocated": "Locate every",
            "wrong_original_text": "original text",
            "changed_source_quote": "source highlight quote",
        }[damage],
    ):
        plan(changed)
    assert dump(group["path"]) == before and not attached(group["path"]).journal.pending()


def test_later_deletion_and_lost_source_bytes_do_not_reapply_a_successful_decision(group, pair):
    request = str(uuid4())
    assert plan(group, request).apply()["applied"]
    client = attached(group["path"])
    mark = group["marks"][0]
    identity = content_id(mark["scope"], mark["feature"], mark["key"])
    client.save(client.new_graph_operation("research_content", identity, {}, action="delete"))
    before = dump(group["path"])
    assert not plan(group, request).apply()["applied"] and dump(group["path"]) == before
    with pytest.raises(ValueError, match="before replacement"):
        plan(group)
    restored = plan(group, replace=True)
    assert restored.apply()["applied"]
    pair[3].store._path(BlobManifest(group["sha"], len(group["data"]))).unlink()
    before = dump(group["path"])
    assert not plan(group, request).apply()["applied"] and dump(group["path"]) == before


@pytest.mark.parametrize("side", ["old", "target"])
def test_uncaptured_private_highlight_words_refuse_without_overwrite(group, side):
    import sqlite3

    if side == "target":
        save(attached(group["path"]), group["marks"][0])
    path = group["old"].journal.path if side == "old" else group["path"]
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.create_function("paperfact_capture", 3, lambda *_: None)
        conn.execute("UPDATE pdf_ai_highlights SET reason='Uncaptured private reasoning'")
    if side == "old":
        previous = group["source"]
        source = candidates.prepare(path, previous.snapshot, previous.workspace)
        change = next(
            r["change_id"]
            for r in source.page()["items"]
            if r["operation_id"] == group["root"]["operation_id"]
        )
        group = dict(group, source=source, change=change)
    before = dump(path), dump(group["path"])
    with pytest.raises(ValueError, match="highlights differ from native history"):
        plan(group, replace=True)
    assert (dump(path), dump(group["path"])) == before


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_native_review_shows_complete_reasons_and_confirms_one_highlight_group(
    group,
    app,
    monkeypatch,
    language,
):
    from PySide6.QtWidgets import QMessageBox

    from paper_daily.desktop.workspace_dialog import WorkspaceDialog

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
        assert ui.action_select.currentData() == "highlight_group", owner.status.text()
        assert "A researcher-edited explanation" in ui.old.toPlainText()
        assert "definition" in ui.old.toPlainText()
        assert "body_json" not in ui.old.toPlainText()
        if language == "zh-TW":
            assert "\u91cd\u9ede" in ui.action_select.currentText()
        before = dump(group["path"])
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
        ui.copy_button.click()
        assert dump(group["path"]) == before and not owner.busy
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        assert len(attached(group["path"]).journal.pending()) == 4, owner.status.text()
        current = rows(group["path"])
        assert len(current["paper_highlight_analysis"]) == 1
        assert len(current["pdf_ai_highlights"]) == 2
        assert not ui.copy_button.isEnabled()
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()


def test_target_change_requires_new_comparison_and_corrupt_receipt_never_restarts(group):
    import sqlite3
    from dataclasses import replace

    prepared = plan(group)
    with pytest.raises(ValueError, match="original prepared"):
        replace(prepared, replace=True).apply()
    client = attached(group["path"])
    client.save(
        client.new_graph_operation(
            "note", str(uuid4()), dict(paper_id=PAPER, body="New work after the comparison")
        )
    )
    before = dump(group["path"])
    with pytest.raises(ValueError, match="target changed"):
        prepared.apply()
    assert dump(group["path"]) == before
    assert plan(group, prepared.request_id).apply()["applied"]
    with closing(sqlite3.connect(group["path"])) as conn, conn:
        conn.execute(
            "UPDATE integration_operations SET result='{}' WHERE id=?", (prepared.request_id,)
        )
    before = dump(group["path"])
    with pytest.raises(ValueError, match="receipt or request changed"):
        plan(group, prepared.request_id)
    assert dump(group["path"]) == before and len(client.journal.pending()) == 5
