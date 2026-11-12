"""Native receiver resumption, with real target/confirmation dialogs and no AI."""

import threading

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from test_archived_draft_resumption import client_for, rows
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_review_dialog import app as app
from test_review_dialog import opened, wait

from paper_daily.desktop.review_dialog import TargetDialog


def choose_target():
    chooser = QApplication.activeModalWidget()
    assert isinstance(chooser, TargetDialog)
    assert chooser.list.count() > 0
    chooser.list.setCurrentRow(0)
    chooser.choose()


def answer(value):
    box = QApplication.activeModalWidget()
    assert isinstance(box, QMessageBox)
    box.button(value).click()


@pytest.mark.parametrize("language,label", [("en", "Continue editing…"), ("zh-TW", "繼續編輯…")])
def test_real_ui_resume_edit_cancel_confirm_reopen_without_duplicate_jobs(
    copied, app, monkeypatch, language, label
):
    copied["review"].close()
    path = copied["path"]
    before = client_for(path).journal.pending()
    view = opened(app, path, language=language)
    calls = []
    original = view.service.verify_resumed_draft

    def verified(preview):
        calls.append(preview.data["id"])
        return original(preview)

    monkeypatch.setattr(view.service, "verify_resumed_draft", verified)
    try:
        assert view.resume_button.isVisible() and view.resume_button.text() == label
        initial = view.draft.toPlainText()
        key = view.preview.data["id"]
        QTimer.singleShot(0, choose_target)
        view.resume_button.click()
        for _index in range(10):
            view.resume_button.click()
        wait(app, lambda: view.preview is not None and view.preview.data["apply"], timeout=15)
        assert calls == [key]
        assert view.preview.data["origin"] == "archived_resume"
        assert not view.draft.isReadOnly() and not view.resume_button.isVisible()
        assert copied["value"]["source_hash"] in view.source.text()
        assert copied["current"].sha256 in view.source.text()
        assert view.draft.toPlainText() == initial
        view.draft.setPlainText("Edited inside the receiver view")
        assert view._save_pending(all_items=True)
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
        view.apply.click()
        assert view.draft.toPlainText() == "Edited inside the receiver view"
        assert client_for(path).journal.pending() == before
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        view.apply.click()
        for _index in range(10):
            view.apply.click()
        wait(app, lambda: not view.busy, timeout=15)
        assert rows(path, "SELECT body FROM close_readings") == [
            ("Edited inside the receiver view",)
        ]
        assert len(client_for(path).journal.pending()) == len(before) + 2
        assert rows(path, "SELECT count(*) FROM research_review_receipts") == [(1,)]
        assert not view.apply.isEnabled()
    finally:
        view.close()
        wait(app, lambda: view.disposed)

    reopened = opened(app, path, language=language)
    try:
        assert reopened.draft.toPlainText() == "Edited inside the receiver view"
        assert not reopened.apply.isEnabled()
        assert len(client_for(path).journal.pending()) == len(before) + 2
    finally:
        reopened.close()
        wait(app, lambda: reopened.disposed)


def test_target_cancellation_keeps_readonly_draft_without_private_or_research_writes(copied, app):
    copied["review"].close()
    path = copied["path"]
    before = client_for(path).journal.pending()
    view = opened(app, path)
    try:
        text = view.draft.toPlainText()
        observed = view.preview
        QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
        view.resume_button.click()
        assert view.preview == observed and view.draft.toPlainText() == text
        assert view.draft.isReadOnly() and not view.apply.isEnabled()
        assert client_for(path).journal.pending() == before
        assert (
            rows(path, "SELECT name FROM sqlite_master WHERE name='research_review_drafts'") == []
        )
    finally:
        view.close()
        wait(app, lambda: view.disposed)


def test_source_failure_keeps_historical_text_and_retry_can_continue(copied, app):
    copied["review"].close()
    path = copied["path"]
    source = path.parent / "pdf" / ".history" / (copied["value"]["source_hash"] + ".pdf")
    original = source.read_bytes()
    source.unlink()
    before = client_for(path).journal.pending()
    view = opened(app, path)
    try:
        text = view.draft.toPlainText()
        QTimer.singleShot(0, choose_target)
        view.resume_button.click()
        wait(app, lambda: view.preview is not None and not view.jobs, timeout=15)
        assert view.preview.data["origin"] == "archived_draft"
        assert view.draft.toPlainText() == text and view.draft.isReadOnly()
        assert not view.apply.isEnabled() and "missing" in view.status.text()
        assert client_for(path).journal.pending() == before
        source.write_bytes(original)
        QTimer.singleShot(0, choose_target)
        view.resume_button.click()
        wait(app, lambda: view.preview is not None and view.preview.data["apply"], timeout=15)
        assert not view.draft.isReadOnly() and view.draft.toPlainText() == text
        assert client_for(path).journal.pending() == before
    finally:
        view.close()
        wait(app, lambda: view.disposed)


@pytest.mark.parametrize("action", ["close", "switch"])
def test_held_source_verification_cannot_deliver_to_closed_or_other_draft(
    copied, app, monkeypatch, action
):
    from paper_daily import sync_source_files

    copied["review"].close()
    path = copied["path"]
    before = client_for(path).journal.pending()
    entered, release = threading.Event(), threading.Event()
    original = sync_source_files.prepare_source

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return original(*args, **kwargs)

    monkeypatch.setattr(sync_source_files, "prepare_source", held)
    view = opened(app, path)
    try:
        initial = view.draft.toPlainText()
        QTimer.singleShot(0, choose_target)
        view.resume_button.click()
        wait(app, entered.is_set, timeout=15)
        future = next(job[0] for job in view.jobs if job[2] == "preview")
        if action == "close":
            view.close()
            assert view.disposed
        else:
            view.list.setCurrentRow(1)
            wait(app, lambda: view.preview is not None, timeout=15)
            assert view.draft.toPlainText() != initial
            other = view.draft.toPlainText()
        release.set()
        if action == "close":
            with pytest.raises(ValueError, match="closed"):
                future.result(timeout=15)
            app.processEvents()
            assert view.disposed and not view.isVisible()
        else:
            future.result(timeout=15)
            wait(app, lambda: not view.jobs, timeout=15)
            assert view.draft.toPlainText() == other and view.draft.isReadOnly()
            assert view.preview.data["origin"] == "archived_draft"
        assert client_for(path).journal.pending() == before
    finally:
        release.set()
        view.close()
        wait(app, lambda: view.disposed)
