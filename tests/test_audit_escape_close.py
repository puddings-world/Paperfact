"""Escape follows the same guarded close path as the window close button."""

import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from test_appraisal_dialog import claims as claims_fixture
from test_appraisal_dialog import ready as ready_fixture
from test_appraisal_dialog import view as view_fixture
from test_appraisal_dialog import wait
from test_appraisal_dialog import workspace as workspace_fixture

from paper_daily.desktop.research_audit import AuditDialog

claims = claims_fixture
ready = ready_fixture
workspace = workspace_fixture
view = view_fixture


@pytest.mark.parametrize("kind", ["appraisal", "audit"])
def test_escape_disposes_idle_review_and_releases_captured_original(view, kind):
    dialog = (
        view.d
        if kind == "appraisal"
        else AuditDialog(
            view.capture.database,
            "paper",
            document=view.capture.snapshot._origin,
            owner=view.d.owner,
            language="en",
            parent=view.parent,
        )
    )
    try:
        dialog.open()
        wait(
            view.app, lambda: not dialog.busy and (kind == "appraisal" or dialog.report is not None)
        )
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        view.app.processEvents()
        assert dialog.disposed and not dialog.isVisible()
        assert (dialog.capture if kind == "appraisal" else dialog.captured) is None
        assert view.app.activeModalWidget() is not dialog
        assert view.calls == []
    finally:
        dialog.close()
        if kind == "audit":
            dialog.deleteLater()
        view.app.processEvents()


def test_escape_during_review_waits_and_preserves_completed_result(view, monkeypatch):
    from paper_daily import llm

    entered, release = threading.Event(), threading.Event()

    def pending(prompt, **kw):
        entered.set()
        assert release.wait(10)
        return view.complete(prompt, **kw)

    monkeypatch.setattr(llm, "complete_result", pending)
    try:
        assert view.d.review()
        wait(view.app, entered.is_set)
        QTest.keyClick(view.d, Qt.Key.Key_Escape)
        assert view.d.isVisible() and not view.d.disposed
        release.set()
        wait(view.app, lambda: view.d.disposed)
        assert view.d.report is not None and len(view.d.archive._files()) == 1
        assert view.d.capture is None and view.calls == [1]
    finally:
        release.set()
        wait(view.app, lambda: not view.d.busy)


def test_escape_cannot_silently_discard_unsaved_review(view, monkeypatch):
    def fail_save(*a, **kw):
        raise OSError("fixture disk failure")

    monkeypatch.setattr(view.d.archive, "save", fail_save)
    assert view.d.review()
    wait(view.app, lambda: not view.d.busy)
    report = view.d.unsaved
    assert report is not None
    choices = []

    def cancel(*args):
        choices.append(args[-1])
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)
    QTest.keyClick(view.d, Qt.Key.Key_Escape)
    assert choices == [QMessageBox.StandardButton.Cancel]
    assert view.d.isVisible() and not view.d.disposed and view.d.unsaved is report
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Discard)
    QTest.keyClick(view.d, Qt.Key.Key_Escape)
    assert view.d.disposed and view.d.capture is None and view.calls == [1]
