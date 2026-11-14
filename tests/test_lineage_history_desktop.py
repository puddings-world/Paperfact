"""Real Qt historical originals never activate analysis or borrow the current PDF."""

import hashlib
import sqlite3
import threading
from contextlib import closing

import pytest
from test_lineage_desktop import scene as scene
from test_lineage_desktop import until
from test_lineage_lifecycle import active as active
from test_research_lineage import corpus as corpus

from paper_daily import lineage_history_originals as history
from paper_daily import lineage_sets


@pytest.fixture
def historical(active, scene, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    owner, row = active
    app, dialog, view = scene
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    assert dialog._change_analysis("retire")
    until(app, lambda: not dialog.busy)
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
    return owner, row, app, dialog, view


def open_original(historical):
    owner, row, app, dialog, _view = historical
    assert dialog.source_buttons and all(button.isEnabled() for button in dialog.source_buttons)
    before = owner.database.read_bytes()
    dialog.source_buttons[0].click()
    assert not dialog.open_source(row, dialog._source_expected[1])
    until(app, lambda: not dialog.busy)
    viewer = dialog._original_viewer
    assert viewer is not None and viewer.isVisible() and not viewer.disposed
    assert viewer._module is history
    assert viewer.document.pageCount() >= 1
    source_id = dialog._source_expected[1]
    source = next(
        s
        for s in lineage_sets.decode(row["body_json"])["report"]["sources"]
        if s["id"] == source_id
    )
    assert hashlib.sha256(bytes(viewer.buffer.data())).hexdigest() == source["document_hash"]
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
    assert owner.database.read_bytes() == before
    assert dialog.document is None
    return viewer


def test_removed_analysis_opens_real_historical_pdf_without_restore_or_ai(historical):
    viewer = open_original(historical)
    viewer.close()
    assert viewer.disposed and viewer.buffer.size() == 0 and viewer._proof is None


@pytest.mark.parametrize("event", ["cancel", "view", "close", "selection", "origin"])
def test_late_historical_source_never_enters_cancelled_or_changed_view(
    historical, monkeypatch, event
):
    owner, row, app, dialog, view = historical
    entered, release = threading.Event(), threading.Event()
    original = history.prepare

    def delayed(*a, **kw):
        entered.set()
        assert release.wait(10)
        return original(*a, **kw)

    monkeypatch.setattr(history, "prepare", delayed)
    before = owner.database.read_bytes()
    dialog.source_buttons[0].click()
    until(app, entered.is_set)
    try:
        if event == "cancel":
            dialog.cancel()
        elif event == "view":
            view[0] = "a-different-paper"
            assert not dialog._check()
        elif event == "selection":
            dialog.results.setCurrentIndex(-1)
        elif event == "origin":
            dialog._entries[0]["origin"] = dict(
                kind="generated", id="00000000-0000-0000-0000-000000000000"
            )
        else:
            assert not dialog.close()
            assert dialog.busy and not dialog.disposed
    finally:
        release.set()
    until(app, lambda: not dialog.busy)
    assert dialog._original_viewer is None
    assert owner.database.read_bytes() == before
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
    if event == "close":
        until(app, lambda: dialog.disposed)


def test_open_historical_window_closes_on_source_grant_loss(historical):
    owner, row, _app, _dialog, _view = historical
    viewer = open_original(historical)
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        conn.execute("DELETE FROM research_local_source_owners")
    assert not viewer.check_current()
    assert viewer.disposed and viewer.buffer.size() == 0 and viewer._proof is None
    assert lineage_sets.saved(owner.database, owner.paper_id) == []


def test_missing_historical_pdf_requires_explicit_retry_without_model_or_restore(historical):
    owner, row, app, dialog, _view = historical
    viewer = open_original(historical)
    path = viewer._proof._path
    data = bytes(viewer.buffer.data())
    viewer.close()
    path.unlink()
    dialog.source_buttons[0].click()
    until(app, lambda: not dialog.busy)
    assert dialog.status.text() == dialog.t["source_unavailable"]
    assert dialog._original_viewer.disposed
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
    path.write_bytes(data)
    again = open_original(historical)
    assert bytes(again.buffer.data()) == data
    again.close()


@pytest.mark.parametrize("historical_mode", [False, True])
def test_cancel_after_worker_finished_before_gui_delivery_opens_no_pdf(
    active, scene, monkeypatch, historical_mode
):
    import time

    from PySide6.QtWidgets import QMessageBox

    owner, row = active
    app, dialog, _view = scene
    if historical_mode:
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes
        )
        assert dialog._change_analysis("retire")
        until(app, lambda: not dialog.busy)
    before = owner.database.read_bytes()
    dialog.source_buttons[0].click()
    worker = dialog._worker
    deadline = time.monotonic() + 15
    # Deliberately hold GUI event delivery while allowing actual file verification.
    while not worker.isFinished() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert worker.isFinished() and worker.result is not None and worker.error is None
    assert dialog.busy and dialog._original_viewer is None
    dialog.cancel()
    until(app, lambda: not dialog.busy)
    assert dialog._original_viewer is None
    assert dialog.status.text() == dialog.t["stopped"]
    assert owner.database.read_bytes() == before
    assert lineage_sets.saved(owner.database, owner.paper_id) == ([] if historical_mode else [row])
