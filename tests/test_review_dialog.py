"""Real Qt widgets with isolated research fixtures and delayed I/O, never AI."""

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog
from test_research_review import candidate, context, generation, output, query
from test_research_review import workspace as workspace  # noqa: F401

from paper_daily.desktop.review_dialog import ReviewDialog
from paper_daily.research_review import ResearchReview


@pytest.fixture
def app():
    from paper_daily.desktop import fonts

    current = QApplication.instance() or QApplication([])
    previous_font, previous_style = current.font(), current.styleSheet()
    fonts.load()
    current.setFont(fonts.font(pixels=fonts.UI_PIXELS))
    current.setStyleSheet("")
    yield current
    current.setFont(previous_font)
    current.setStyleSheet(previous_style)


def wait(app, condition, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Review UI did not reach its observable state")


def opened(app, path, **options):
    dialog = ReviewDialog(path, **options)
    dialog.show()
    wait(app, lambda: dialog.preview is not None)
    return dialog


def test_real_ui_apply_rapid_clicks_one_atomic_result(app, workspace):
    path, client = workspace
    candidate(path)
    before = len(client.journal.pending())
    dialog = opened(app, path, language="zh-TW")
    try:
        assert dialog.list.item(0).text() == "逐段精讀 · Paper"
        dialog.draft.setFocus()
        dialog.draft.selectAll()
        QTest.keyClicks(dialog.draft, "Reviewed in the dialog")
        for _ in range(10):
            dialog.apply.click()
        wait(app, lambda: not dialog.busy)
        assert query(path, "SELECT body FROM close_readings") == [("Reviewed in the dialog",)]
        assert len(client.journal.pending()) == before + 1
        assert query(path, "SELECT count(*) FROM research_review_receipts") == [(1,)]
        assert not dialog.apply.isEnabled()
        assert "已儲存於本機" in dialog.status.text()
        assert dialog.draft.hasFocus()
    finally:
        dialog.reject()


def test_ui_newer_write_retains_draft_and_failed_apply_can_retry_after_explicit_review(
    app, workspace
):
    path, _ = workspace
    candidate(path)
    dialog = opened(app, path)
    try:
        dialog.draft.setPlainText("User draft to preserve")
        generation.publish_generation(context(path), row=output("Other writer"))
        dialog.apply.click()
        wait(app, lambda: not dialog.busy)
        assert "changed" in dialog.status.text()
        assert dialog.draft.toPlainText() == "User draft to preserve"
        assert query(path, "SELECT body FROM close_readings") == [("Other writer",)]
        dialog.refresh.click()
        wait(app, lambda: dialog.preview is not None)
        assert dialog.current.toPlainText() == "Other writer"
        assert dialog.draft.toPlainText() == "User draft to preserve"
        dialog.apply.click()
        wait(app, lambda: not dialog.busy)
        assert query(path, "SELECT body FROM close_readings") == [("User draft to preserve",)]
    finally:
        dialog.reject()


def test_selection_navigation_preserves_draft_cursor_and_observed_base(app, workspace):
    path, _ = workspace
    candidate(path)
    initial = context(path)
    generation.publish_generation(context(path), row=output("Newer analysis"))
    generation.publish_generation(initial, row=output("Second candidate"))
    dialog = opened(app, path)
    try:
        token = dialog.preview.serialized
        dialog.draft.setPlainText("Keep my typed draft")
        cursor = dialog.draft.textCursor()
        cursor.setPosition(4)
        dialog.draft.setTextCursor(cursor)
        dialog.list.setFocus()
        QTest.keyClick(dialog.list, Qt.Key.Key_Down)
        wait(app, lambda: dialog.preview is not None)
        QTest.keyClick(dialog.list, Qt.Key.Key_Up)
        wait(app, lambda: dialog.preview is not None)
        assert dialog.preview.serialized == token
        assert dialog.draft.toPlainText() == "Keep my typed draft"
        assert dialog.draft.textCursor().position() == 4
        assert dialog.list.hasFocus()
    finally:
        dialog.reject()


def test_late_preview_does_not_replace_new_selection(app, workspace, monkeypatch):
    path, _ = workspace
    candidate(path)
    initial = context(path)
    generation.publish_generation(context(path), row=output("Newer"))
    generation.publish_generation(initial, row=output("Second"))
    service = ResearchReview(path)
    first, second = [item["id"] for item in service.page()["items"]]
    entered, release = threading.Event(), threading.Event()
    original = service.preview

    def delayed(origin, identity):
        if identity == first:
            entered.set()
            release.wait(5)
        return original(origin, identity)

    monkeypatch.setattr(service, "preview", delayed)
    dialog = ReviewDialog(service=service)
    dialog.show()
    try:
        wait(app, entered.is_set)
        dialog.list.setCurrentRow(1)
        wait(app, lambda: dialog.preview is not None)
        assert dialog.preview.data["id"] == second
        release.set()
        wait(app, lambda: not dialog.jobs)
        assert dialog.preview.data["id"] == second
    finally:
        release.set()
        dialog.reject()


def test_close_during_apply_cancels_before_transaction_and_never_writes_other_workspace(
    app, workspace, monkeypatch
):
    path, client = workspace
    candidate(path)
    service = ResearchReview(path)
    entered, release = threading.Event(), threading.Event()
    original = service.decide

    def delayed(*args, **kwargs):
        entered.set()
        release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "decide", delayed)
    dialog = opened(app, path, service=service)
    before = client.journal.pending()
    dialog.apply.click()
    wait(app, entered.is_set)
    future = dialog.jobs[-1][0]
    dialog.reject()
    release.set()
    with pytest.raises(ValueError, match="closed"):
        future.result(timeout=5)
    assert client.journal.pending() == before
    assert query(path, "SELECT body FROM close_readings") == [("Current saved analysis",)]


def test_export_cancel_and_copy_do_not_change_research(app, workspace, monkeypatch):
    path, client = workspace
    candidate(path)
    dialog = opened(app, path)
    try:
        before = client.journal.pending()
        dialog.draft.setPlainText("Copy this draft")
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
        dialog.export_button.click()
        dialog.copy.click()
        assert "Copy this draft" in app.clipboard().text()
        assert str(path) not in app.clipboard().text()
        assert client.journal.pending() == before
    finally:
        dialog.reject()


def test_empty_workspace_and_short_narrow_geometry_are_usable(app, workspace):
    path, _ = workspace
    dialog = ReviewDialog(path, language="zh-TW")
    dialog.resize(620, 520)
    dialog.show()
    try:
        wait(app, lambda: not dialog.jobs)
        assert "沒有" in dialog.status.text()
        assert not dialog.apply.isEnabled()
        assert dialog.height() <= 520
        assert dialog.close_button.isVisible()
        assert (
            dialog.close_button.mapTo(dialog, dialog.close_button.rect().bottomRight()).y()
            < dialog.height()
        )
    finally:
        dialog.reject()


def test_offline_target_confirmation_cancel_then_apply(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog, QMessageBox
    from test_research_lifecycle import legacy

    from paper_daily.desktop.review_dialog import TargetDialog

    path = tmp_path / "offline.db"
    legacy(path)
    candidate(path)
    dialog = opened(app, path)
    try:
        assert not dialog.apply.isEnabled()

        def choose_first(chooser):
            assert chooser.list.item(0).text() == "Paper\npaper"
            chooser.choose()
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(TargetDialog, "exec", choose_first)
        dialog.target_button.click()
        wait(app, lambda: dialog.preview is not None)
        assert dialog.preview.data["requires_confirmation"]
        assert dialog.apply.isEnabled()
        dialog.draft.setPlainText("Explicit offline reviewed draft")
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel
        )
        dialog.apply.click()
        assert not dialog.busy
        assert query(path, "SELECT body FROM close_readings") == [("Current saved analysis",)]
        assert dialog.draft.toPlainText() == "Explicit offline reviewed draft"
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        dialog.apply.click()
        wait(app, lambda: not dialog.busy)
        assert query(path, "SELECT body FROM close_readings") == [
            ("Explicit offline reviewed draft",)
        ]
    finally:
        dialog.reject()


def test_target_selection_cancel_does_not_recapture_or_change_preview(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from test_research_lifecycle import legacy

    from paper_daily.desktop.review_dialog import TargetDialog

    path = tmp_path / "offline.db"
    legacy(path)
    candidate(path)
    dialog = opened(app, path)
    try:
        original = dialog.preview
        monkeypatch.setattr(TargetDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
        dialog.target_button.click()
        assert dialog.preview == original
        assert not dialog.apply.isEnabled()
        assert query(path, "SELECT body FROM close_readings") == [("Current saved analysis",)]
    finally:
        dialog.reject()


def test_offline_refresh_preserves_selected_target_draft_and_failure_keeps_it(app, tmp_path):
    import sqlite3
    from contextlib import closing

    from test_research_lifecycle import legacy

    path = tmp_path / "offline.db"
    legacy(path)
    candidate(path)
    dialog = opened(app, path)
    try:
        selected = dialog.service.target_preview(dialog.preview, "paper")
        dialog._display(selected)
        dialog.draft.setPlainText("Keep the explicitly selected draft")
        generation.publish_generation(context(path), row=output("Newer local text"))
        dialog.refresh.click()
        assert dialog.draft.isReadOnly()
        wait(app, lambda: dialog.preview is not None)
        assert dialog.preview.data["requires_confirmation"]
        assert dialog.current.toPlainText() == "Newer local text"
        assert dialog.draft.toPlainText() == "Keep the explicitly selected draft"
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("DELETE FROM papers WHERE id='paper'")
            conn.commit()
        dialog.refresh.click()
        wait(app, lambda: dialog.preview is not None)
        assert "no longer exists" in dialog.status.text()
        assert dialog.draft.toPlainText() == "Keep the explicitly selected draft"
    finally:
        dialog.reject()
