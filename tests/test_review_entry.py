"""Actual desktop entry point keeps reviewed work bound to its workspace."""

import time

from PySide6.QtWidgets import QMessageBox
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import llm, store
from paper_daily.desktop.main import MainWindow

workspace = _workspace


def settle(app, dialog):
    deadline = time.monotonic() + 5
    while dialog.jobs and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not dialog.jobs


def test_menu_opens_single_workspace_review_and_parent_waits_for_close(workspace, monkeypatch):
    app, _ = workspace
    monkeypatch.setattr(
        llm, "complete", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("AI called"))
    )
    window = MainWindow()
    try:
        window.show()
        for _ in range(5):
            window.review_action.trigger()
        dialog = window._review_dialog
        settle(app, dialog)
        assert dialog.service.path == store.DB_PATH.resolve()
        assert "沒有" in dialog.status.text()
        assert not dialog.apply.isEnabled()
        window._review_retained()
        assert window._review_dialog is dialog
        assert not window.close()
        assert window.isVisible()
        dialog.reject()
        assert dialog.disposed and dialog.service.closed
        assert window.close()
    finally:
        if getattr(window, "_review_dialog", None):
            window._review_dialog.reject()
        window.close()
        window.deleteLater()


def test_workspace_change_closes_original_review_and_reopens_explicit_target(
    workspace, monkeypatch
):
    app, root = workspace
    window = MainWindow()
    try:
        window._review_retained()
        original = window._review_dialog
        settle(app, original)
        monkeypatch.setattr(store, "DB_PATH", root / "other.db")
        store.init_db()
        window._poll_external_lists()
        assert original.disposed and original.service.closed
        window._review_retained()
        fresh = window._review_dialog
        settle(app, fresh)
        assert fresh is not original
        assert fresh.service.path == store.DB_PATH.resolve()
    finally:
        window._review_dialog.reject()
        window.close()
        window.deleteLater()


def test_unavailable_workspace_explains_failure_and_can_retry(workspace, monkeypatch):
    app, root = workspace
    window = MainWindow()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    try:
        monkeypatch.setattr(store, "DB_PATH", root / "missing.db")
        window._review_retained()
        assert warnings and not getattr(window, "_review_dialog", None)
        store.init_db()
        window._review_retained()
        settle(app, window._review_dialog)
        assert window._review_dialog.service.path == store.DB_PATH.resolve()
    finally:
        if getattr(window, "_review_dialog", None):
            window._review_dialog.reject()
        window.close()
        window.deleteLater()
