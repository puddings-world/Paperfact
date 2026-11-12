"""Real Qt note recovery, explicit source/target, cancellation and late delivery."""

import json
import threading

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from test_archived_draft_resume_ui import answer
from test_archived_draft_resumption import client_for, rows
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_note_draft_resumption import recovered_note as recovered_note
from test_note_draft_resumption_edges import note_rows
from test_resumed_draft_original_ui import source_view
from test_review_dialog import app as app
from test_review_dialog import opened, wait


def choose_target():
    from paper_daily.desktop.review_dialog import TargetDialog

    chooser = QApplication.activeModalWidget()
    assert isinstance(chooser, TargetDialog)
    row = next(
        index
        for index in range(chooser.list.count())
        if "Current anchored note B" in chooser.list.item(index).text()
    )
    chooser.list.setCurrentRow(row)
    chooser.choose()


def note_view(app, value, language="en"):
    value["review"].close()
    view = opened(app, value["path"], language=language)
    identity = value["archived"].data["id"]
    row = next(
        index
        for index in range(view.list.count())
        if tuple(view.list.item(index).data(Qt.ItemDataRole.UserRole))
        == ("archived_draft", identity)
    )
    view.list.setCurrentRow(row)
    wait(app, lambda: view.preview is not None and view.preview.data["id"] == identity, timeout=20)
    return view


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_note_ui_compare_sources_open_a_cancel_apply_confirm_and_reopen(
    recovered_note, app, language
):
    value = recovered_note
    before = client_for(value["path"]).journal.pending(1000)
    view = note_view(app, value, language)
    identity = value["archived"].data["id"]
    try:
        QTimer.singleShot(0, choose_target)
        view.resume_button.click()
        for _ in range(10):
            view.resume_button.click()
        wait(app, lambda: view.preview is not None and view.preview.data["apply"], timeout=25)
        assert view.preview.data["origin"] == "archived_note_resume"
        assert view.preview.data["expected"]["note_id"] == value["target_note_id"]
        assert not view.draft.isReadOnly() and view.apply.isEnabled()
        assert value["source_a"] in view.source.text() and value["source_b"] in view.source.text()
        assert view.words["current_note_source"].split("{")[0] in view.source.text()
        assert view.words["retained_note_source"].split("{")[0] in view.source.text()
        for _ in range(25):
            view.originals.button.click()
        viewer = source_view(app, view)
        assert viewer.snapshot.document_hash == value["source_a"]
        assert viewer.snapshot.data == value["original"]["value"]["original_bytes"]
        view.draft.setPlainText("Reviewed note from real desktop UI")
        assert view._save_pending(all_items=True)
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
        view.apply.click()
        assert note_rows(value, "body") == [("Current anchored note B",)]
        assert client_for(value["path"]).journal.pending(1000) == before
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        view.apply.click()
        for _ in range(10):
            view.apply.click()
        wait(app, lambda: not view.busy, timeout=20)
        row = note_rows(value, "body,anchor")[0]
        assert row[0] == "Reviewed note from real desktop UI", view.status.text()
        assert json.loads(row[1])["document_hash"] == value["source_a"]
        assert len(client_for(value["path"]).journal.pending(1000)) == len(before) + 2
        assert rows(value["path"], "SELECT count(*) FROM research_review_receipts") == [(1,)]
    finally:
        view.close()
        wait(app, lambda: view.disposed, timeout=20)
    reopened = note_view(app, value, language)
    try:
        assert reopened.preview.data["id"] == identity
        assert reopened.draft.toPlainText() == "Reviewed note from real desktop UI"
        assert not reopened.apply.isEnabled()
    finally:
        reopened.close()
        wait(app, lambda: reopened.disposed, timeout=20)


@pytest.mark.parametrize("action", ["close", "switch"])
def test_note_verification_completion_does_not_enter_closed_or_other_draft(
    recovered_note, app, monkeypatch, action
):
    value = recovered_note
    view = note_view(app, value)
    before = client_for(value["path"]).journal.pending(1000)
    entered, release = threading.Event(), threading.Event()
    original = view.service.verify_resumed_draft

    def held(*args):
        entered.set()
        assert release.wait(20)
        return original(*args)

    monkeypatch.setattr(view.service, "verify_resumed_draft", held)
    try:
        QTimer.singleShot(0, choose_target)
        view.resume_button.click()
        wait(app, entered.is_set, timeout=15)
        future = next(job[0] for job in view.jobs if job[2] == "preview")
        if action == "close":
            view.close()
            assert view.disposed
        else:
            other = next(
                index
                for index in range(view.list.count())
                if tuple(view.list.item(index).data(Qt.ItemDataRole.UserRole))
                == ("archived_draft", value["items"][1]["id"])
            )
            view.list.setCurrentRow(other)
            wait(app, lambda: view.preview is not None, timeout=15)
            text = view.draft.toPlainText()
        release.set()
        if action == "close":
            with pytest.raises(ValueError, match="closed"):
                future.result(timeout=20)
            app.processEvents()
            assert not view.isVisible()
        else:
            future.result(timeout=20)
            wait(app, lambda: not view.jobs, timeout=20)
            assert view.draft.toPlainText() == text and view.draft.isReadOnly()
            assert view.preview.data["origin"] == "archived_draft"
        assert view.originals.viewer is None
        assert client_for(value["path"]).journal.pending(1000) == before
        assert note_rows(value, "body") == [("Current anchored note B",)]
    finally:
        release.set()
        view.close()
        wait(app, lambda: view.disposed, timeout=20)


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_rebound_source_invalidates_native_view_and_failed_recheck_disables_apply_until_retry(
    recovered_note, app, language
):
    import sqlite3
    from contextlib import closing

    from paper_daily import research_generation as generation
    from paper_daily.sync_artifacts import paths

    value = recovered_note
    view = note_view(app, value, language)
    before = client_for(value["path"]).journal.pending(1000)
    try:
        QTimer.singleShot(0, choose_target)
        view.resume_button.click()
        wait(app, lambda: view.preview is not None and view.preview.data["apply"], timeout=25)
        view.draft.setPlainText("Private note through source-owner change")
        assert view._save_pending(all_items=True)
        view.originals.button.click()
        viewer = source_view(app, view)
        with closing(generation._connect(value["path"])) as conn:
            store, _versions = paths(conn)
        index = store.root / "index.sqlite"
        with closing(sqlite3.connect(index)) as conn, conn:
            binding = tuple(
                conn.execute(
                    "SELECT workspace,device,research_path FROM transfer_binding"
                ).fetchone()
            )
            conn.execute("UPDATE transfer_binding SET device='other-device'")
        viewer.check()
        wait(app, lambda: viewer.disposed, timeout=20)
        assert viewer.snapshot is None and view.originals.viewer is None
        assert view.draft.toPlainText() == "Private note through source-owner change"
        view.refresh.click()
        wait(app, lambda: view.preview is not None and not view.jobs, timeout=25)
        assert not view.apply.isEnabled() and not view.preview.data["apply"]
        assert not view.originals.button.isEnabled()
        assert view.draft.toPlainText() == "Private note through source-owner change"
        assert client_for(value["path"]).journal.pending(1000) == before
        assert note_rows(value, "body") == [("Current anchored note B",)]
        with closing(sqlite3.connect(index)) as conn, conn:
            conn.execute(
                "UPDATE transfer_binding SET workspace=?,device=?,research_path=?", binding
            )
        view.refresh.click()
        wait(app, lambda: view.preview is not None and view.preview.data["apply"], timeout=25)
        assert view.apply.isEnabled() and view.originals.button.isEnabled()
        assert view.draft.toPlainText() == "Private note through source-owner change"
        assert view.service.load_draft(view.preview.data["origin"], view.preview.data["id"])[
            "body"
        ] == ("Private note through source-owner change")
        assert client_for(value["path"]).journal.pending(1000) == before
    finally:
        view.close()
        wait(app, lambda: view.disposed, timeout=20)
