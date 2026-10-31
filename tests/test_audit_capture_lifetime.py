"""Closing a saved view releases its large PDF capture without deleting its result."""

import weakref
from dataclasses import replace

from PySide6.QtCore import QCoreApplication, QEvent
from test_appraisal_dialog import claims as claims_fixture
from test_appraisal_dialog import ready as ready_fixture
from test_appraisal_dialog import view as view_fixture
from test_appraisal_dialog import wait
from test_appraisal_dialog import workspace as workspace_fixture

from paper_daily.desktop.appraisal_dialog import TEXT, AppraisalDialog

claims = claims_fixture
ready = ready_fixture
workspace = workspace_fixture
view = view_fixture


def test_closed_idle_appraisal_releases_capture_and_keeps_saved_result(view):
    capture = replace(view.capture)
    reference = weakref.ref(capture)
    dialog = AppraisalDialog(capture, archive_root=view.d.archive.root, language="en")
    del capture
    try:
        dialog.show()
        wait(view.app, lambda: not dialog.busy and dialog.status.text() != TEXT["en"]["loading"])
        assert dialog.review()
        wait(view.app, lambda: not dialog.busy)
        saved = dialog.report
        assert saved is not None
        assert dialog.close() and dialog.disposed
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        view.app.processEvents()
        assert reference() is None
        assert dialog.report is saved and len(dialog.archive._files()) == 1
        assert not dialog.review() and view.calls == [1]
    finally:
        dialog.close()
        dialog.deleteLater()
        view.app.processEvents()


def test_closed_evidence_parent_releases_its_captured_original(view):
    from paper_daily.desktop.research_audit import AuditDialog

    dialog = AuditDialog(
        view.capture.database,
        "paper",
        document=view.capture.snapshot._origin,
        owner=view.d.owner,
        language="en",
    )
    try:
        dialog.show()
        wait(view.app, lambda: dialog.report is not None and not dialog.busy)
        reference = weakref.ref(dialog.captured)
        report = dialog.report
        assert dialog.close() and dialog.disposed
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        view.app.processEvents()
        assert reference() is None and dialog.report is report
        assert not dialog.refresh() and view.calls == []
    finally:
        dialog.close()
        dialog.deleteLater()
        view.app.processEvents()


def test_close_waits_for_completed_review_before_releasing_capture(view, monkeypatch):
    import threading

    from paper_daily import llm

    entered, release = threading.Event(), threading.Event()
    capture = replace(view.capture)
    reference = weakref.ref(capture)
    dialog = AppraisalDialog(capture, archive_root=view.d.archive.root, language="en")
    del capture

    def pending(prompt, **kw):
        entered.set()
        assert release.wait(10)
        return view.complete(prompt, **kw)

    monkeypatch.setattr(llm, "complete_result", pending)
    try:
        dialog.show()
        wait(view.app, lambda: not dialog.busy and dialog.status.text() != TEXT["en"]["loading"])
        assert dialog.review()
        wait(view.app, entered.is_set)
        assert dialog.close() is False and not dialog.disposed and reference() is not None
        release.set()
        wait(view.app, lambda: dialog.disposed)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        view.app.processEvents()
        assert reference() is None
        assert dialog.report is not None and len(dialog.archive._files()) == 1
        assert view.calls == [1]
    finally:
        release.set()
        if dialog.busy:
            wait(view.app, lambda: not dialog.busy)
        dialog.close()
        dialog.deleteLater()
        view.app.processEvents()


def test_unsaved_cancel_retains_capture_and_explicit_discard_releases_it(view, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    capture = replace(view.capture)
    reference = weakref.ref(capture)
    dialog = AppraisalDialog(capture, archive_root=view.d.archive.root, language="en")
    del capture
    monkeypatch.setattr(dialog.archive, "save", lambda *a, **kw: (_ for _ in ()).throw(OSError()))
    try:
        dialog.show()
        wait(view.app, lambda: not dialog.busy and dialog.status.text() != TEXT["en"]["loading"])
        assert dialog.review()
        wait(view.app, lambda: not dialog.busy)
        assert dialog.unsaved is not None
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Cancel
        )
        assert not dialog.close() and not dialog.disposed and reference() is not None
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Discard
        )
        assert dialog.close() and dialog.disposed
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        view.app.processEvents()
        assert reference() is None and view.calls == [1]
    finally:
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Discard
        )
        dialog.close()
        dialog.deleteLater()
        view.app.processEvents()
