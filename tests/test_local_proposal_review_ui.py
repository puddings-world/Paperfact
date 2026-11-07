"""Actual local-only review UI: named paper, explicit confirmation and closed-worker safety."""

import sqlite3
import threading
import time
from contextlib import closing

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from test_local_deck_proposals import local as local
from test_local_deck_proposals import prepared
from test_portable_deck_proposal import scientific as scientific

from paper_daily import local_deck_proposals as catalog
from paper_daily import presentations
from paper_daily.desktop.review_dialog import ReviewDialog
from paper_daily.research_review import ResearchReview


def settle(app, predicate, timeout=15):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate()


def open_review(local, language):
    database, _manifest, _blobs, saved, _before = local
    identity = catalog.retain(prepared(local))
    app = QApplication.instance() or QApplication([])
    service = ResearchReview(database, presentation_root=saved.parents[1])
    dialog = ReviewDialog(service=service, language=language)
    dialog.show()
    settle(app, lambda: dialog.preview is not None and not dialog.jobs)
    assert dialog.selection_key == ("local_deck", identity)
    return app, dialog


def dispose(app, dialog):
    if not dialog.disposed:
        settle(app, lambda: not dialog.jobs and not dialog.busy)
        dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_named_local_review_cancel_then_apply_once_preserves_all_images_and_history(
    local, scientific, monkeypatch, language
):
    database, _manifest, _blobs, saved, before = local
    app, dialog = open_review(local, language)
    try:
        assert "Local receiver" in dialog.list.currentItem().text()
        assert scientific[0].title in dialog.draft.toPlainText()
        assert dialog.draft.isReadOnly() and not dialog.apply.isEnabled()
        assert dialog.status.text() == dialog.words["local_slides"]
        dialog.refresh.click()
        settle(app, lambda: dialog.preview is not None and not dialog.jobs)
        assert dialog.apply.isEnabled(), dialog.status.text()
        assert "Prior saved deck" in dialog.current.toPlainText()
        assert "Local receiver" in dialog.source.text()
        confirmations = []

        def cancel(*args, **kwargs):
            confirmations.append(args[2])
            return QMessageBox.StandardButton.Cancel

        monkeypatch.setattr(QMessageBox, "question", cancel)
        dialog.apply.click()
        assert confirmations and "Local receiver" in confirmations[0]
        assert saved.read_bytes() == before and dialog.apply.isEnabled()
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes
        )
        for _ in range(25):
            dialog.apply.click()
        settle(app, lambda: not dialog.busy and not dialog.jobs)
        assert dialog.status.text() == dialog.words["saved_local"]
        loaded = presentations.load_deck("local-paper", "guide")
        assert loaded.title == scientific[0].title
        assert loaded.slides[0].speaker_notes == scientific[0].slides[0].speaker_notes
        for key, value in scientific[2].items():
            assert presentations.figure_bytes(loaded, key) == value
        history = list((saved.parent / "history").glob("guide-review-*.json"))
        assert len(history) == 1 and history[0].read_bytes() == before
        with closing(sqlite3.connect(database)) as conn:
            assert conn.execute("SELECT count(*) FROM research_review_receipts").fetchone() == (1,)
            assert not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='research_sync_binding'"
            ).fetchone()
    finally:
        dispose(app, dialog)


def test_closing_local_review_during_held_verification_does_not_apply_or_change_research(
    local, monkeypatch
):
    database, _manifest, _blobs, saved, before = local
    app, dialog = open_review(local, "zh-TW")
    admitted, release = threading.Event(), threading.Event()
    original = dialog.service.prepare_file

    def held(*args, **kwargs):
        admitted.set()
        assert release.wait(15)
        return original(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "prepare_file", held)
    try:
        dialog.refresh.click()
        settle(app, admitted.is_set)
        jobs = [job[0] for job in dialog.jobs]
        assert jobs and saved.read_bytes() == before
        dialog.close()
        assert dialog.disposed and dialog.service.closed and not dialog.isVisible()
        release.set()
        settle(app, lambda: all(future.done() for future in jobs))
        assert saved.read_bytes() == before
        with closing(sqlite3.connect(database)) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='research_review_receipts'"
            ).fetchone()
            assert not exists or conn.execute(
                "SELECT count(*) FROM research_review_receipts"
            ).fetchone() == (0,)
    finally:
        release.set()
        dispose(app, dialog)
