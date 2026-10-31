"""Real native saved-deck activation stays on worker proofs and preserves drafts."""

import hashlib
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QWidget
from shiboken6 import delete
from test_audit_decks import LOCAL, QUOTE, reader
from test_audit_decks import saved as saved_fixture
from test_audit_ui import wait

from paper_daily import manual_highlight_ops
from paper_daily.desktop.deck_audit import _LIVE, COPY, DeckAuditDialog
from paper_daily.desktop.presentation_pane import PresentationPane

saved = saved_fixture


@pytest.fixture
def panel(saved, monkeypatch):
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.language = "en"
    question, note = QLineEdit("Unsent question", parent), QPlainTextEdit("Unsent note", parent)
    pane = PresentationPane(parent)
    pane.paper_id = LOCAL
    pane._mode = "guide"
    pane._annotation_epoch = 1
    from contextlib import closing

    from paper_daily import research_generation, sync_capture

    with closing(research_generation._connect(saved.path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="device")
        conn.commit()
    pane._annotation_owner = manual_highlight_ops.capture_owner(saved.path, LOCAL)
    pane._show_deck(saved.deck)
    pane._update_controls()
    parent.show()
    pane.show()
    app.processEvents()
    value = SimpleNamespace(
        app=app, pane=pane, parent=parent, question=question, note=note, saved=saved
    )
    yield value
    dialog = getattr(pane, "_deck_audit_dialog", None)
    if dialog is not None and not dialog.disposed:
        dialog.close()
        wait(app, lambda: not dialog.busy)
        dialog.close()
    pane.close()
    parent.close()
    pane.deleteLater()
    parent.deleteLater()
    app.processEvents()


def guarded(monkeypatch):
    main = threading.get_ident()
    seen = []

    def guard(call, label):
        def invoke(*args, **kwargs):
            assert threading.get_ident() != main, "Saved-deck action did SQL/hash on Qt"
            seen.append(label)
            return call(*args, **kwargs)

        return invoke

    monkeypatch.setattr(sqlite3, "connect", guard(sqlite3.connect, "sql"))
    monkeypatch.setattr(hashlib, "sha256", guard(hashlib.sha256, "hash"))
    monkeypatch.setattr(hashlib, "file_digest", guard(hashlib.file_digest, "digest"))
    return seen


def test_actual_small_toolbar_entry_construct_poll_render_no_sql_hash_on_gui(panel, monkeypatch):
    seen = guarded(monkeypatch)
    action = panel.pane.deck_audit_action
    assert action in panel.pane.toolbar.actions() and action.isEnabled()
    action.trigger()
    dialog = panel.pane._deck_audit_dialog
    wait(panel.app, lambda: not dialog.busy and dialog.prepared is not None)
    dialog._check()
    assert QUOTE in dialog.text.toPlainText()
    assert COPY["en"]["located"] in dialog.text.toPlainText()
    for _ in range(15):
        action.trigger()
    assert panel.pane._deck_audit_dialog is dialog
    assert panel.question.text() == "Unsent question" and panel.note.toPlainText() == "Unsent note"
    assert {"sql", "hash"} <= set(seen)
    assert not panel.pane._dirty and not panel.pane._canvas_dirty


@pytest.mark.parametrize("field", ["_dirty", "_canvas_dirty", "_layout_reset"])
def test_unsaved_deck_draft_is_never_saved_discarded_or_submitted_by_audit(
    panel, field, monkeypatch
):
    monkeypatch.setattr(panel.pane, "save_changes", lambda *a: pytest.fail("Audit saved editor"))
    setattr(panel.pane, field, True)
    from paper_daily.desktop.deck_audit import open_selected

    assert not open_selected(panel.pane)
    assert getattr(panel.pane, field) and not hasattr(panel.pane, "_deck_audit_dialog")
    assert panel.pane.status.text() == COPY["en"]["draft"]
    setattr(panel.pane, field, False)


@pytest.mark.parametrize("mode", ["cancel_close", "switch", "failure", "parent_close"])
def test_pending_repeats_cancel_switch_failure_parent_close_preserve_reader(
    panel, monkeypatch, mode
):
    from paper_daily.desktop import deck_audit

    original = deck_audit.DeckAuditReader.prepare
    start, release = threading.Event(), threading.Event()
    calls = []

    def pending(service, ticket=None):
        calls.append(1)
        start.set()
        release.wait(10)
        if mode == "failure":
            raise ValueError("PRIVATE SOURCE DATA")
        return original(service, ticket)

    monkeypatch.setattr(deck_audit.DeckAuditReader, "prepare", pending)
    panel.pane.deck_audit_action.trigger()
    dialog = panel.pane._deck_audit_dialog
    wait(panel.app, start.is_set)
    try:
        for _ in range(12):
            panel.pane.deck_audit_action.trigger()
        assert not dialog.refresh()
        if mode == "cancel_close":
            assert not dialog.close() and not dialog.disposed
        elif mode == "switch":
            panel.pane._annotation_epoch += 1
        elif mode == "parent_close":
            assert not panel.parent.close() and not dialog.disposed
        release.set()
        wait(panel.app, lambda: not dialog.busy)
        assert calls == [1]
        assert (
            panel.question.text() == "Unsent question" and panel.note.toPlainText() == "Unsent note"
        )
        assert "PRIVATE SOURCE DATA" not in dialog.status.text()
        if mode in {"cancel_close", "parent_close"}:
            assert dialog.disposed
        elif mode == "switch":
            assert dialog.prepared is None and dialog.status.text() == COPY["en"]["changed"]
        else:
            assert dialog.prepared is None
            monkeypatch.setattr(deck_audit.DeckAuditReader, "prepare", original)
            assert dialog.refresh()
            wait(panel.app, lambda: not dialog.busy)
            assert dialog.prepared is not None
    finally:
        release.set()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_bilingual_readonly_full_output_and_close_release_modal(saved, language):
    app = QApplication.instance() or QApplication([])
    dialog = DeckAuditDialog(reader(saved), language=language)
    dialog.open()
    wait(app, lambda: not dialog.busy and dialog.prepared is not None)
    try:
        assert set(COPY["en"]) == set(COPY["zh-TW"])
        assert QUOTE in dialog.text.toPlainText()
        assert "Speaker notes stay complete." in dialog.text.toPlainText()
        assert dialog.text.isReadOnly() and not hasattr(dialog, "appraisal_button")
        assert dialog.close() and dialog.disposed and not dialog.isVisible()
        assert app.activeModalWidget() is not dialog
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_forced_owner_destruction_cancels_parentless_worker_without_late_widget_access(
    saved, monkeypatch
):
    from paper_daily.desktop import deck_audit

    app = QApplication.instance() or QApplication([])
    start, release = threading.Event(), threading.Event()
    original = deck_audit.DeckAuditReader.prepare

    def pending(service, ticket=None):
        start.set()
        release.wait(10)
        return original(service, ticket)

    monkeypatch.setattr(deck_audit.DeckAuditReader, "prepare", pending)
    dialog = DeckAuditDialog(reader(saved))
    dialog.open()
    wait(app, start.is_set)
    delete(dialog)
    release.set()
    wait(app, lambda: not _LIVE)


@pytest.mark.parametrize("change", ["source", "binding"])
def test_real_change_after_worker_completion_before_gui_delivery_preserves_prior_report(
    panel, monkeypatch, change
):
    from contextlib import closing

    from paper_daily.desktop import deck_audit

    panel.pane.deck_audit_action.trigger()
    dialog = panel.pane._deck_audit_dialog
    wait(panel.app, lambda: not dialog.busy and dialog.prepared is not None)
    prior, text = dialog.prepared, dialog.text.toPlainText()
    original = deck_audit.DeckAuditReader.prepare

    def changed(service, ticket=None):
        result = original(service, ticket)
        if change == "source":
            path = panel.saved.blobs.root / "objects" / panel.saved.document["sha256"]
            path.write_bytes(b"x" * path.stat().st_size)
        else:
            with closing(sqlite3.connect(panel.saved.path)) as conn, conn:
                conn.execute("UPDATE research_sync_binding SET origin='new-device'")
        return result

    monkeypatch.setattr(deck_audit.DeckAuditReader, "prepare", changed)
    assert dialog.refresh()
    wait(panel.app, lambda: not dialog.busy)
    assert dialog.prepared is prior and dialog.text.toPlainText() == text
    assert dialog.status.text() == COPY["en"]["changed"] and not dialog.selector.isEnabled()
    assert panel.question.text() == "Unsent question" and panel.note.toPlainText() == "Unsent note"


def test_loaded_deck_native_database_identity_is_checked_before_worker_admission(
    panel, monkeypatch
):
    from paper_daily.desktop.deck_audit import open_selected

    panel.saved.deck._file_observation["database_identity"] = [0, 999999]
    guarded(monkeypatch)
    assert not open_selected(panel.pane)
    assert not hasattr(panel.pane, "_deck_audit_dialog")
    assert panel.pane.status.text() == COPY["en"]["unavailable"]


def test_actual_configured_mainwindow_banner_refuses_install_before_audit_drains(
    saved, monkeypatch
):
    from contextlib import closing

    from paper_daily import research_generation, sync_capture, updates
    from paper_daily.desktop import deck_audit
    from paper_daily.desktop.main import MainWindow

    app = QApplication.instance() or QApplication([])
    with closing(research_generation._connect(saved.path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="device")
        conn.commit()
    # Keep automatic update discovery local too; only the real preparation callback is exercised.
    monkeypatch.setattr(updates, "check", lambda *a, **k: None)
    window = MainWindow()
    pane = window.reader_page.presentation_pane
    pane.paper_id, pane._mode = LOCAL, "guide"
    pane._annotation_epoch = 1
    pane._annotation_owner = manual_highlight_ops.capture_owner(saved.path, LOCAL)
    pane._show_deck(saved.deck)
    window.reader_page.ask_box.setText("Unsent question during update")
    window.reader_page.note_edit.setPlainText("Unsent note during update")
    start, release = threading.Event(), threading.Event()
    original = deck_audit.DeckAuditReader.prepare

    def pending(service, ticket=None):
        start.set()
        release.wait(10)
        return original(service, ticket)

    monkeypatch.setattr(deck_audit.DeckAuditReader, "prepare", pending)
    launched = []
    monkeypatch.setattr(updates, "launch_installer", launched.append)
    window.show()
    try:
        pane.deck_audit_action.trigger()
        dialog = pane._deck_audit_dialog
        wait(app, start.is_set)
        dialog.hide()
        app.processEvents()
        assert QApplication.activeModalWidget() is None
        assert pane.busy and pane._deck_audit_running == 1
        assert not window._prepare_restart() and not window._prepare_update()
        banner = window.update_banner
        assert banner._prepare_install.__self__ is window
        banner._ready = saved.root / "fixture-installer-never-launched.exe"
        banner._verified()
        assert launched == [] and not banner._installing
        assert window.reader_page.ask_box.text() == "Unsent question during update"
        assert window.reader_page.note_edit.toPlainText() == "Unsent note during update"
        release.set()
        wait(app, lambda: not dialog.busy and not pane.busy)
        assert pane._deck_audit_running == 0
        dialog.close()
        assert window._prepare_update()
        assert launched == []
    finally:
        release.set()
        dialog = getattr(pane, "_deck_audit_dialog", None)
        if dialog is not None:
            wait(app, lambda: not dialog.busy)
            dialog.close()
        window.reader_page.ask_box.clear()
        window.reader_page.note_edit.blockSignals(True)
        window.reader_page.note_edit.clear()
        window.reader_page.note_edit.blockSignals(False)
        window.reader_page._note_dirty = False
        window._closing_with_recovery = True
        window.close()
        window.deleteLater()
        app.processEvents()


def test_parent_pane_stays_busy_if_dialog_is_destroyed_before_worker_finishes(panel, monkeypatch):
    from paper_daily.desktop import deck_audit

    start, release = threading.Event(), threading.Event()
    original = deck_audit.DeckAuditReader.prepare

    def pending(service, ticket=None):
        start.set()
        release.wait(10)
        return original(service, ticket)

    monkeypatch.setattr(deck_audit.DeckAuditReader, "prepare", pending)
    panel.pane.deck_audit_action.trigger()
    dialog = panel.pane._deck_audit_dialog
    wait(panel.app, start.is_set)
    delete(dialog)
    assert panel.pane.busy and panel.pane._deck_audit_running == 1
    release.set()
    wait(panel.app, lambda: not panel.pane.busy)
    assert panel.pane._deck_audit_running == 0
    panel.pane._deck_audit_dialog = None


def test_native_worker_start_failure_releases_actual_pane_guard_and_retries(panel, monkeypatch):
    from paper_daily.desktop import deck_audit

    start = deck_audit._Worker.start

    def failed(_worker):
        raise RuntimeError("fixture thread admission failure")

    monkeypatch.setattr(deck_audit._Worker, "start", failed)
    panel.pane.deck_audit_action.trigger()
    dialog = panel.pane._deck_audit_dialog
    wait(panel.app, lambda: not dialog.busy and dialog.status.text() == COPY["en"]["failed"])
    assert not panel.pane.busy and panel.pane._deck_audit_running == 0
    assert not _LIVE
    monkeypatch.setattr(deck_audit._Worker, "start", start)
    assert dialog.refresh()
    wait(panel.app, lambda: not dialog.busy and dialog.prepared is not None)
    assert not panel.pane.busy and panel.pane._deck_audit_running == 0
