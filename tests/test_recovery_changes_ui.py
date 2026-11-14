"""Actual Qt recovery navigation, native save, cancellation and stale delivery."""

import sqlite3
from contextlib import closing
from threading import Event
from uuid import uuid4

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QFileDialog
from test_sync_device_recovery import dump
from test_sync_files import PAPER
from test_sync_recovery_target import attached
from test_sync_recovery_target import codec as codec
from test_sync_recovery_target import pair as pair
from test_sync_recovery_target import prepared as prepared
from test_workspace_dialog import app as app
from test_workspace_dialog import wait

from paper_daily import sync_recovery_note_copy as note_copy
from paper_daily import sync_recovery_target as target
from paper_daily.desktop.workspace_dialog import WorkspaceDialog
from paper_daily.manual_highlight_ops import _readonly_connection


@pytest.fixture
def view(prepared, app):
    owner = WorkspaceDialog(prepared[0].journal.path, language="en")
    owner.show()
    wait(app, lambda: owner._ready and not owner.busy)
    owner.task_tabs.setCurrentIndex(2)
    owner.device_review.disclosure.setChecked(True)
    yield owner
    if owner.busy:
        owner.cancel()
        wait(app, lambda: not owner.busy)
    owner.close()
    app.processEvents()


def load(view, app, prepared):
    ui = view.device_review.changes
    assert view.device_review.inspect(prepared[1].snapshot)
    wait(app, lambda: not view.busy)
    assert ui.load(prepared[3].parent)
    wait(app, lambda: not view.busy)
    assert ui.rows.count() == 1, view.status.text()
    return ui


def compared(view, app, prepared):
    ui = load(view, app, prepared)
    assert ui.compare()
    wait(app, lambda: not view.busy)
    assert ui.copy_button.isEnabled(), view.status.text()
    return ui


def test_visible_native_review_copy_and_refresh_preserve_old_and_existing_notes(
    view,
    app,
    prepared,
    monkeypatch,
):
    old, _source, _change, path, _operation = prepared
    ui = view.device_review.changes
    assert not ui.choose_button.isEnabled() and not ui.copy_button.isEnabled()
    assert not ui.load("")
    before = dump(old.journal.path)
    ui = load(view, app, prepared)
    assert ui.rows.currentRow() == 0 and not ui.copy_button.isEnabled()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: "")
    observed = ui.observed
    assert not ui.choose() and ui.observed is observed
    assert ui.compare() and not ui.compare()
    wait(app, lambda: not view.busy)
    assert ui.old.toPlainText() == "Old device's unsent revision"
    assert ui.current.toPlainText() == "Backed up note"
    assert ui.copy_button.isEnabled()
    assert ui.copy() and not ui.copy()
    wait(app, lambda: not view.busy)
    assert "Saved a new note" in ui.notice.text() and "not been checked" in ui.notice.text()
    assert not ui.copy_button.isEnabled() and ui.refresh_button.isEnabled()
    assert dump(old.journal.path) == before
    with closing(_readonly_connection(path)) as conn:
        assert [row[0] for row in conn.execute("SELECT body FROM notes ORDER BY id")] == [
            "Backed up note",
            "Old device's unsent revision",
        ]
    assert len(attached(path).journal.pending()) == 1
    assert ui.reload()
    wait(app, lambda: not view.busy)
    assert ui.rows.count() == 1 and not ui.copy_button.isEnabled()


def test_failure_retry_keeps_one_payload_bound_copy(view, app, prepared, monkeypatch):
    ui = compared(view, app, prepared)
    original = note_copy.NoteCopy.apply
    attempts = []

    def fail_once(plan, **kwargs):
        attempts.append(plan.operation_json)
        if len(attempts) == 1:
            raise RuntimeError("simulated transient local failure")
        return original(plan, **kwargs)

    monkeypatch.setattr(note_copy.NoteCopy, "apply", fail_once)
    assert ui.copy()
    wait(app, lambda: not view.busy)
    assert "Could not finish" in ui.notice.text() and ui.copy_button.isEnabled()
    assert attached(prepared[3]).journal.pending() == []
    assert ui.copy()
    wait(app, lambda: not view.busy)
    assert attempts[0] == attempts[1]
    assert len(attached(prepared[3]).journal.pending()) == 1
    assert "Saved a new note" in ui.notice.text()


@pytest.mark.parametrize("action", ["cancel", "close", "switch", "rebind"])
def test_held_apply_refuses_after_cancel_close_workspace_or_binding_change(
    view,
    app,
    prepared,
    monkeypatch,
    tmp_path,
    action,
):
    ui = compared(view, app, prepared)
    entered, release = Event(), Event()
    original = note_copy.NoteCopy.apply

    def held(plan, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(plan, **kwargs)

    monkeypatch.setattr(note_copy.NoteCopy, "apply", held)
    assert ui.copy() and entered.wait(3)
    assert not ui.copy() and not ui.compare() and not ui.reload()
    try:
        if action == "cancel":
            view.cancel()
        elif action == "close":
            assert not view.close()
        elif action == "switch":
            view.service.current_path = lambda: tmp_path / "another.sqlite"
        else:
            with closing(sqlite3.connect(prepared[0].journal.path)) as conn, conn:
                conn.execute("UPDATE paperfact_sync_identity SET workspace='different'")
    finally:
        release.set()
    wait(app, lambda: not view.busy)
    assert attached(prepared[3]).journal.pending() == []
    assert "Saved a new note" not in ui.notice.text()
    if action == "close":
        assert view.disposed


def test_changed_target_at_queued_comparison_delivery_cannot_enable_copy(
    view,
    app,
    prepared,
):
    ui = load(view, app, prepared)
    assert ui.compare()
    worker = view._worker
    assert worker.wait(10000)
    assert not ui.copy_button.isEnabled()
    client = attached(prepared[3])
    client.save(
        client.new_graph_operation(
            "note", str(uuid4()), dict(paper_id=PAPER, body="New target edit")
        )
    )
    wait(app, lambda: not view.busy)
    assert "review changed" in ui.notice.text()
    assert not ui.copy_button.isEnabled() and not ui.compare_button.isEnabled()
    assert len(client.journal.pending()) == 1


def test_source_binding_at_queued_index_delivery_is_rechecked(view, app, prepared):
    ui = view.device_review.changes
    ui.reset_source(prepared[1].snapshot)
    assert ui.load(prepared[3].parent)
    worker = view._worker
    assert worker.wait(10000)
    with closing(sqlite3.connect(prepared[0].journal.path)) as conn, conn:
        conn.execute("UPDATE paperfact_sync_identity SET workspace='changed-at-delivery'")
    wait(app, lambda: not view.busy)
    assert ui.rows.count() == 0 and not ui.copy_button.isEnabled()
    assert "review changed" in ui.notice.text() or "review changed" in view.status.text()


def test_comparison_and_apply_run_off_gui_thread(view, app, prepared, monkeypatch):
    calls = []
    original_compare, original_apply = target.TargetObservation.compare, note_copy.NoteCopy.apply

    def compare(observed, *args, **kwargs):
        calls.append(QThread.currentThread() != app.thread())
        return original_compare(observed, *args, **kwargs)

    def apply(plan, **kwargs):
        calls.append(QThread.currentThread() != app.thread())
        return original_apply(plan, **kwargs)

    monkeypatch.setattr(target.TargetObservation, "compare", compare)
    monkeypatch.setattr(note_copy.NoteCopy, "apply", apply)
    ui = compared(view, app, prepared)
    assert ui.copy()
    wait(app, lambda: not view.busy)
    assert len(calls) >= 3 and all(calls)


def test_cancel_after_commit_keeps_honest_saved_status(view, app, prepared):
    ui = compared(view, app, prepared)
    assert ui.copy()
    assert view._worker.wait(10000)
    view.cancel()
    wait(app, lambda: not view.busy)
    assert "Saved a new note" in ui.notice.text()
    assert len(attached(prepared[3]).journal.pending()) == 1
    assert not ui.copy_button.isEnabled()


def test_target_rebound_after_commit_before_delivery_does_not_claim_current_review(
    view,
    app,
    prepared,
):
    ui = compared(view, app, prepared)
    assert ui.copy()
    assert view._worker.wait(10000)
    with closing(sqlite3.connect(prepared[3])) as conn, conn:
        conn.execute("UPDATE paperfact_sync_identity SET workspace='rebound-after-save'")
    wait(app, lambda: not view.busy)
    assert "copy was saved" in ui.notice.text() and "review changed" in ui.notice.text()
    assert not ui.copy_button.isEnabled() and not ui.compare_button.isEnabled()
    with closing(sqlite3.connect(prepared[3])) as conn:
        assert conn.execute("SELECT count(*) FROM notes").fetchone()[0] == 2


def test_next_and_previous_pages_keep_all_changes_reachable(view, app, prepared):
    old, _source, _change, _path, _operation = prepared
    for number in range(21):
        old.save(
            old.new_graph_operation(
                "note", str(uuid4()), dict(paper_id=PAPER, body=f"Finding {number}")
            )
        )
    ui = view.device_review.changes
    assert view.device_review.inspect(prepared[1].snapshot)
    wait(app, lambda: not view.busy)
    assert ui.load(prepared[3].parent)
    wait(app, lambda: not view.busy)
    assert ui.rows.count() == 20 and ui.page["change_count"] == 22
    first = ui.selected()
    assert not ui.previous_button.isEnabled() and ui.next_button.isEnabled()
    assert ui.next_page() and not ui.next_page()
    wait(app, lambda: not view.busy)
    assert ui.rows.count() == 2 and ui.selected() != first
    assert not ui.next_button.isEnabled() and ui.previous_button.isEnabled()
    assert ui.previous_page()
    wait(app, lambda: not view.busy)
    assert ui.rows.count() == 20 and ui.selected() == first
    assert not ui.copy_button.isEnabled()
    assert attached(prepared[3]).journal.pending() == []


def test_unavailable_target_refuses_without_creation_and_allows_selection_retry(
    view,
    app,
    prepared,
    tmp_path,
):
    ui = view.device_review.changes
    ui.reset_source(prepared[1].snapshot)
    missing = tmp_path / "missing-workspace"
    assert ui.load(missing)
    wait(app, lambda: not view.busy)
    assert not missing.exists() and not ui.copy_button.isEnabled()
    assert "Could not finish" in ui.notice.text()
    assert ui.load(prepared[3].parent)
    wait(app, lambda: not view.busy)
    assert ui.rows.count() == 1


@pytest.mark.parametrize("kind", ["list", "anchored_note"])
def test_unsupported_change_has_clear_pending_state_without_enabling_copy(
    view, app, prepared, kind
):
    old, _source, _change, path, _operation = prepared
    if kind == "list":
        operation = old.new_graph_operation(
            "list", "old-list", dict(name="Retained content", note=None)
        )
    else:
        operation = old.new_graph_operation(
            "note", str(uuid4()), dict(
                paper_id=PAPER, body="Retained content", kind="note",
                created_at="2026-11-14T00:00:00+00:00", page=1, anchor=None,
            ),
        )
    old.save(operation)
    ui = view.device_review.changes
    ui.reset_source(prepared[1].snapshot)
    assert ui.load(path.parent)
    wait(app, lambda: not view.busy)
    ui.rows.setCurrentRow(1)
    assert ui.compare()
    wait(app, lambda: not view.busy)
    assert "Retained content" in ui.old.toPlainText()
    assert "remains pending" in ui.notice.text() and not ui.copy_button.isEnabled()
    assert attached(path).journal.pending() == []


def test_failed_backup_review_still_rechecks_binding_before_gui_delivery(
    view,
    app,
    prepared,
    monkeypatch,
):
    from paper_daily import sync_device_recovery

    def fail(*_args, **_kwargs):
        raise RuntimeError("simulated read failure before queued delivery")

    monkeypatch.setattr(sync_device_recovery, "review", fail)
    assert view.device_review.inspect(prepared[1].snapshot)
    assert view._worker.wait(10000)
    with closing(sqlite3.connect(prepared[0].journal.path)) as conn, conn:
        conn.execute("UPDATE paperfact_sync_identity SET workspace='changed-after-failure'")
    wait(app, lambda: not view.busy)
    assert view._invalid and view.status.text() == view.t["changed"]
    assert not view.device_review.button.isEnabled()


def test_reopening_review_cannot_copy_same_recorded_change_twice(view, app, prepared):
    ui = compared(view, app, prepared)
    assert ui.copy()
    wait(app, lambda: not view.busy)
    before = dump(prepared[3])
    assert ui.reload()
    wait(app, lambda: not view.busy)
    assert ui.compare()
    wait(app, lambda: not view.busy)
    assert "already copied" in ui.notice.text()
    assert not ui.copy_button.isEnabled() and not ui.copy()
    assert dump(prepared[3]) == before and len(attached(prepared[3]).journal.pending()) == 1


def test_fresh_review_window_recognizes_already_saved_copy(view, app, prepared):
    ui = compared(view, app, prepared)
    assert ui.copy()
    wait(app, lambda: not view.busy)
    assert view.close()
    reopened = WorkspaceDialog(prepared[0].journal.path, language="en")
    try:
        reopened.show()
        wait(app, lambda: reopened._ready and not reopened.busy)
        fresh = load(reopened, app, prepared)
        assert fresh.compare()
        wait(app, lambda: not reopened.busy)
        assert "already copied" in fresh.notice.text()
        assert not fresh.copy_button.isEnabled()
        assert len(attached(prepared[3]).journal.pending()) == 1
    finally:
        reopened.close()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_bilingual_compact_review_renders_and_enter_compares(app, prepared, language):
    from pathlib import Path

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from paper_daily.desktop import fonts, settings_style

    previous_font = app.font()
    fonts.load()
    app.setFont(fonts.font(pixels=14))
    from PySide6.QtGui import QRawFont

    face = QRawFont.fromFont(app.font())
    probe = "Paperfact " + chr(31558) + chr(35352)
    assert face.isValid() and all(face.glyphIndexesForString(probe)), (
        "Visual acceptance requires the pinned UI fonts; run paperfact fonts first."
    )
    dialog = WorkspaceDialog(prepared[0].journal.path, language=language)
    settings_style.apply(dialog)
    try:
        dialog.resize(920, 820)
        dialog.show()
        wait(app, lambda: dialog._ready and not dialog.busy)
        dialog.task_tabs.setCurrentIndex(2)
        dialog.device_review.disclosure.setChecked(True)
        ui = load(dialog, app, prepared)
        ui.rows.setFocus()
        QTest.keyClick(ui.rows, Qt.Key.Key_Return)
        wait(app, lambda: not dialog.busy)
        assert ui.copy_button.isEnabled()
        assert ui.old.toPlainText() == "Old device's unsent revision"
        assert ui.copy_button.text() == ui.t["copy"]
        expected = "Note" if language == "en" else "筆記"
        assert ui.rows.item(0).text().startswith("1. " + expected)
        assert "put" not in ui.rows.item(0).text()
        dialog.scroll.ensureWidgetVisible(ui)
        app.processEvents()
        ui.location.setText("Restored test workspace")
        artifact = Path.cwd() / "build" / f"recovery-changes-{language}.png"
        assert ui.grab().save(str(artifact))
    finally:
        dialog.close()
        app.setFont(previous_font)
