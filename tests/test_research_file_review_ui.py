"""Retained slides have an explicit verification/review flow in the actual dialog."""

import threading

import pytest
from PySide6.QtWidgets import QMessageBox
from test_research_file_review import codec as codec  # noqa: F401
from test_research_file_review import pair as pair  # noqa: F401
from test_research_file_review import retained as retained  # noqa: F401
from test_review_dialog import app as app  # noqa: F401
from test_review_dialog import wait
from test_sync_files import LOCAL

from paper_daily import presentations
from paper_daily.desktop.review_dialog import ReviewDialog
from paper_daily.research_review import ResearchReview


def open_review(app, retained, **options):
    client, _ = retained
    dialog = ReviewDialog(client.journal.path, **options)
    dialog.show()
    wait(app, lambda: dialog.preview is not None)
    return dialog


def test_file_review_ui_verifies_confirms_then_applies_once(app, retained, monkeypatch):
    client, _ = retained
    before = client.journal.pending()
    dialog = open_review(app, retained, language="en")
    try:
        assert dialog.refresh.text() == "Verify retained slides"
        assert not dialog.apply.isEnabled()
        assert "sha256" not in dialog.draft.toPlainText()
        for _ in range(10):
            dialog.refresh.click()
        wait(app, lambda: dialog.preview is not None and dialog.apply.isEnabled())
        assert dialog.draft.isReadOnly()
        assert "Retained reviewed version" in dialog.draft.toPlainText()
        assert "Retained explanation" in dialog.draft.toPlainText()
        assert "Current manual version" in dialog.current.toPlainText()
        assert "asset_id" not in dialog.draft.toPlainText()
        assert not dialog.target_button.isEnabled()
        assert not dialog.draft_history.isVisible()
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Cancel)
        dialog.apply.click()
        assert client.journal.pending() == before
        assert dialog.apply.isEnabled()
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
        for _ in range(15):
            dialog.apply.click()
        wait(app, lambda: not dialog.busy)
        assert len(client.journal.pending()) == len(before) + 1
        assert presentations.load_deck(LOCAL, "guide").title == "Retained reviewed version"
        assert not dialog.apply.isEnabled()
    finally:
        dialog.reject()


def test_file_review_ui_stale_base_requires_explicit_new_review(app, retained, monkeypatch):
    dialog = open_review(app, retained)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    try:
        dialog.refresh.click()
        wait(app, lambda: dialog.preview is not None and dialog.apply.isEnabled())
        current = presentations.load_deck(LOCAL, "guide")
        current.title = "Newer while reviewing"
        presentations.save_deck(current)
        dialog.apply.click()
        wait(app, lambda: not dialog.busy)
        assert "changed" in dialog.status.text()
        assert presentations.load_deck(LOCAL, "guide").title == "Newer while reviewing"
        dialog.refresh.click()
        wait(app, lambda: dialog.preview is not None)
        assert "Newer while reviewing" in dialog.current.toPlainText()
        dialog.apply.click()
        wait(app, lambda: not dialog.busy)
        assert presentations.load_deck(LOCAL, "guide").title == "Retained reviewed version"
    finally:
        dialog.reject()


def test_closed_view_during_file_verification_cannot_deliver_or_write(app, retained, monkeypatch):
    client, _ = retained
    service = ResearchReview(client.journal.path)
    original = service.prepare_file
    entered, release = threading.Event(), threading.Event()
    def delayed(preview):
        entered.set()
        assert release.wait(4)
        return original(preview)
    monkeypatch.setattr(service, "prepare_file", delayed)
    dialog = open_review(app, retained, service=service)
    before = client.journal.pending()
    try:
        dialog.refresh.click()
        wait(app, entered.is_set)
        dialog.reject()
        assert dialog.disposed and service.closed
        release.set()
        wait(app, lambda: all(job[0].done() for job in dialog.jobs))
        assert client.journal.pending() == before
        assert presentations.load_deck(LOCAL, "guide").title == "Current manual version"
    finally:
        release.set()
        dialog.reject()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_deleted_slides_ui_names_restoration_and_cancel_preserves_deletion(
    app, retained, monkeypatch, language
):
    from test_sync_files import PAPER

    from paper_daily.sync_files import file_id
    client, _ = retained
    entity = file_id(PAPER, "deck", "guide")
    client.save(client.new_graph_operation("research_file", entity, {}, action="delete"))
    before = client.journal.pending()
    dialog = open_review(app, retained, language=language)
    prompts = []
    try:
        dialog.refresh.click()
        wait(app, lambda: dialog.preview is not None and dialog.apply.isEnabled())
        if language == "en":
            assert dialog.apply.text() == "Restore reviewed slides"
            assert "deleted" in dialog.status.text()
        else:
            assert dialog.apply.text() == "恢復已審閱簡報"
            assert "已刪除" in dialog.status.text()
        def cancel(*args):
            prompts.append(args[2])
            return QMessageBox.StandardButton.Cancel
        monkeypatch.setattr(QMessageBox, "question", cancel)
        dialog.apply.click()
        if language == "en":
            assert "Restore these deleted slides" in prompts[-1]
        else:
            assert "已刪除" in prompts[-1] and "恢復" in prompts[-1]
        assert client.journal.pending() == before
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
        dialog.apply.click()
        wait(app, lambda: not dialog.busy)
        assert len(client.journal.pending()) == len(before) + 1
        assert presentations.load_deck(LOCAL, "guide").title == "Retained reviewed version"
    finally:
        dialog.reject()
