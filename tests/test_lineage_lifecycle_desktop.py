"""Actual desktop removal/history/restoration, confirmations and pending-work guards."""

import sqlite3
import threading
from contextlib import closing

import pytest
from PySide6.QtWidgets import QMessageBox
from test_lineage_desktop import scene as scene
from test_lineage_desktop import until
from test_lineage_lifecycle import active as active
from test_research_lineage import corpus as corpus

from paper_daily import lineage_lifecycle, lineage_sets


def answer(monkeypatch, value):
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: value)


def test_real_confirmed_remove_history_restore_without_ai_and_cancel_does_nothing(
    active, scene, monkeypatch
):
    owner, row = active
    app, dialog, _view = scene
    assert dialog.saved == [row] and dialog.remove_button.isEnabled()
    answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    assert not dialog._change_analysis("retire")
    assert not dialog.busy and lineage_sets.saved(owner.database, owner.paper_id) == [row]
    answer(monkeypatch, QMessageBox.StandardButton.Yes)
    assert dialog._change_analysis("retire")
    assert not dialog._change_analysis("retire")
    assert not dialog.remove_button.isEnabled() and not dialog.restore_button.isEnabled()
    until(app, lambda: not dialog.busy)
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
    assert dialog.mode.currentIndex() == 1 and dialog.saved == [row]
    assert not dialog.remove_button.isEnabled() and dialog.restore_button.isEnabled()
    assert dialog.source_buttons and all(button.isEnabled() for button in dialog.source_buttons)
    assert dialog.status.text() == dialog.t["saved_local"]
    from pathlib import Path

    from PySide6.QtWidgets import QLabel

    until(
        app,
        lambda: any(
            label.text() == dialog.t["history_source"] and label.isVisible()
            for label in dialog.cards.findChildren(QLabel)
        ),
    )
    app.processEvents()
    image = Path(__file__).resolve().parents[1] / "build" / "lineage-history-desktop-20261113.png"
    assert dialog.grab().save(str(image))

    answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    assert not dialog._change_analysis("restore")
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
    answer(monkeypatch, QMessageBox.StandardButton.Yes)
    assert dialog._change_analysis("restore")
    assert not dialog._change_analysis("restore")
    until(app, lambda: not dialog.busy)
    assert lineage_sets.saved(owner.database, owner.paper_id) == [row]
    assert dialog.remove_button.isEnabled() and not dialog.restore_button.isEnabled()
    assert all(button.isEnabled() for button in dialog.source_buttons)
    with closing(sqlite3.connect(owner.database)) as conn:
        assert conn.execute("SELECT count(*) FROM research_lineage_actions").fetchone()[0] == 2
    dialog.mode.setCurrentIndex(0)
    until(app, lambda: not dialog.busy)
    assert dialog.saved == [row] and not dialog.older_button.isVisible()


@pytest.mark.parametrize("event", ["cancel", "view", "close"])
def test_held_lifecycle_cannot_apply_after_cancel_view_switch_or_close(
    active, scene, monkeypatch, event
):
    owner, row = active
    app, dialog, view = scene
    answer(monkeypatch, QMessageBox.StandardButton.Yes)
    original = lineage_lifecycle.change
    entered, release = threading.Event(), threading.Event()

    def delayed(*a, **kw):
        entered.set()
        assert release.wait(10)
        return original(*a, **kw)

    monkeypatch.setattr(lineage_lifecycle, "change", delayed)
    assert dialog._change_analysis("retire")
    until(app, entered.is_set)
    try:
        assert not dialog._change_analysis("retire")
        if event == "cancel":
            dialog.cancel()
        elif event == "view":
            view[0] = "different-paper"
            assert not dialog._check()
        else:
            assert not dialog.close()
            assert dialog.busy and not dialog.disposed
    finally:
        release.set()
    until(app, lambda: not dialog.busy)
    assert lineage_sets.saved(owner.database, owner.paper_id) == [row]
    if event == "close":
        until(app, lambda: dialog.disposed)
    elif event == "view":
        assert dialog.status.text() == dialog.t["changed"]
    else:
        assert dialog.status.text() == dialog.t["stopped"]


def test_changed_target_during_confirmation_is_not_overwritten(active, scene, monkeypatch):
    owner, row = active
    app, dialog, _view = scene

    def question(*_a, **_k):
        with closing(sqlite3.connect(owner.database)) as conn, conn:
            conn.execute("UPDATE paper_lineage_sets SET written_at='2026-11-20T00:00:00+00:00'")
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", question)
    assert dialog._change_analysis("retire")
    until(app, lambda: not dialog.busy)
    assert dialog.status.text() == dialog.t["lifecycle_failed"]
    saved = lineage_sets.saved(owner.database, owner.paper_id)
    assert len(saved) == 1 and saved[0]["written_at"] != row["written_at"]
    assert not dialog._change_analysis("restore")


def test_empty_selection_never_confirms_or_starts_action(scene, monkeypatch):
    _app, dialog, _view = scene
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: pytest.fail("No selection"))
    assert not dialog._change_analysis("retire")
    assert not dialog._change_analysis("restore")
    assert not dialog.remove_button.isEnabled() and not dialog.restore_button.isEnabled()


def test_failed_restore_preserves_history_and_explicit_retry_after_source_repair(
    active, scene, monkeypatch
):
    owner, row = active
    app, dialog, _view = scene
    answer(monkeypatch, QMessageBox.StandardButton.Yes)
    assert dialog._change_analysis("retire")
    until(app, lambda: not dialog.busy)
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        sources = conn.execute("SELECT * FROM research_local_source_owners").fetchall()
        conn.execute("DELETE FROM research_local_source_owners")
    assert dialog._change_analysis("restore")
    until(app, lambda: not dialog.busy)
    assert dialog.status.text() == dialog.t["lifecycle_failed"]
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
    assert dialog.saved == [row] and dialog.restore_button.isEnabled()
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        for source in sources:
            conn.execute(
                "INSERT INTO research_local_source_owners VALUES("
                + ",".join("?" for _ in source)
                + ")",
                source,
            )
    assert dialog._change_analysis("restore")
    until(app, lambda: not dialog.busy)
    assert lineage_sets.saved(owner.database, owner.paper_id) == [row]
    with closing(sqlite3.connect(owner.database)) as conn:
        assert conn.execute("SELECT count(*) FROM research_lineage_actions").fetchone()[0] == 2


def test_commit_succeeds_but_refresh_fails_reports_saved_instead_of_unchanged(
    active, scene, monkeypatch
):
    owner, row = active
    app, dialog, _view = scene
    answer(monkeypatch, QMessageBox.StandardButton.Yes)

    def failed_refresh(*_a, **_k):
        raise ValueError("fixture post-commit read failure")

    original = dialog._read
    monkeypatch.setattr(dialog, "_read", failed_refresh)
    assert dialog._change_analysis("retire")
    until(app, lambda: not dialog.busy)
    assert dialog.status.text() == dialog.t["refresh_needed"]
    assert not dialog.remove_button.isEnabled() and not dialog.restore_button.isEnabled()
    assert all(not button.isEnabled() for button in dialog.source_buttons)
    assert not dialog._change_analysis("retire")
    assert not dialog._change_analysis("restore")
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
    monkeypatch.setattr(dialog, "_read", original)
    assert dialog.refresh()
    until(app, lambda: not dialog.busy)
    assert dialog.saved == [row] and dialog.restore_button.isEnabled()


def test_history_without_further_pages_cannot_jump_beyond_results(active, scene):
    _owner, row = active
    app, dialog, _view = scene
    dialog.mode.setCurrentIndex(1)
    until(app, lambda: not dialog.busy)
    assert dialog.saved == [row]
    assert not dialog._page_history(100) and not dialog._page_history(-100)
    assert not dialog.busy and dialog.history_offset == 0


@pytest.mark.parametrize("change", ["view", "selection"])
def test_changed_context_during_confirmation_starts_no_action(active, scene, monkeypatch, change):
    owner, row = active
    _app, dialog, view = scene

    def question(*_a, **_k):
        if change == "view":
            view[0] = "another-paper"
            dialog._check()
        else:
            dialog.results.setCurrentIndex(-1)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", question)
    assert not dialog._change_analysis("retire")
    assert not dialog.busy
    assert lineage_sets.saved(owner.database, owner.paper_id) == [row]
