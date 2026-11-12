"""Pinned raw drafts use the actual retained-work review UI after restart."""

import threading

from PySide6.QtWidgets import QMessageBox
from test_raw_deck_closure import codec as codec  # noqa: F401
from test_raw_deck_closure import late
from test_raw_deck_closure import pair as pair  # noqa: F401
from test_review_dialog import app as app  # noqa: F401
from test_review_dialog import wait
from test_sync_files import LOCAL, png

from paper_daily import presentations, store
from paper_daily.desktop.review_dialog import ReviewDialog
from paper_daily.research_review import ResearchReview


def test_restarted_raw_draft_ui_verifies_cancel_then_applies_once(app, pair, codec, monkeypatch):
    a, _, _, _, _, _, _ = late(pair, codec, monkeypatch, unused=True)
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    pending = a.journal.pending()
    dialog = ReviewDialog(a.journal.path, language="zh-TW")
    dialog.show()
    try:
        wait(app, lambda: dialog.preview is not None)
        assert dialog.preview.data["origin"] == "file_draft"
        assert dialog.refresh.text() == "核對保留簡報"
        assert not dialog.apply.isEnabled()
        for _ in range(8):
            dialog.refresh.click()
        wait(app, lambda: dialog.preview is not None and dialog.apply.isEnabled())
        assert "Preserve my full explanation" in dialog.draft.toPlainText()
        assert dialog.draft.isReadOnly()
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Cancel)
        dialog.apply.click()
        assert a.journal.pending() == pending
        monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
        for _ in range(8):
            dialog.apply.click()
        wait(app, lambda: not dialog.busy)
        assert len(a.journal.pending()) == len(pending) + 1
        deck = presentations.load_deck(LOCAL, "guide")
        assert deck.title == "Late generated scientific explanation"
        assert presentations.figure_bytes(deck, "figure:1") == png("red")
        assert presentations.figure_bytes(deck, "figure:2") == png("blue")
    finally:
        dialog.reject()


def test_raw_verification_closed_before_delivery_keeps_original_and_no_publication(
    app, pair, codec, monkeypatch
):
    a, _, _, _, _, _, _ = late(pair, codec, monkeypatch)
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    service = ResearchReview(a.journal.path)
    entered, release = threading.Event(), threading.Event()
    prepare = service.prepare_file
    def delayed(preview):
        entered.set()
        assert release.wait(4)
        return prepare(preview)
    monkeypatch.setattr(service, "prepare_file", delayed)
    pending = a.journal.pending()
    dialog = ReviewDialog(service=service)
    dialog.show()
    try:
        wait(app, lambda: dialog.preview is not None)
        dialog.refresh.click()
        wait(app, entered.is_set)
        dialog.reject()
        release.set()
        wait(app, lambda: all(job[0].done() for job in dialog.jobs))
        assert a.journal.pending() == pending
        assert dialog.disposed and service.closed
    finally:
        release.set()
        dialog.reject()
