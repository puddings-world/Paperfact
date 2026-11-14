"""Offline saved-history repair uses the real dialog and accepted fixture events."""

import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from test_lineage_history_repair import compared as compared
from test_lineage_history_repair import corpus as corpus
from test_lineage_history_repair import dump, stable_snapshot
from test_lineage_history_repair import legacy as legacy
from test_lineage_history_repair import native_shared as native_shared
from test_lineage_history_repair import shared as shared
from test_lineage_jobs import routes
from test_package_review_dialog import app as app
from test_package_review_dialog import wait
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import llm, store
from paper_daily import research_generation as generation
from paper_daily.desktop.lineage_dialog import LineageDialog
from paper_daily.lineage_history_repair import HistoryRepair
from paper_daily.manual_highlight_ops import observe_owner


@pytest.fixture
def scene(app, legacy, monkeypatch, tmp_path):
    client, _files, receipt, _old = legacy
    local = receipt["identity_mapping"]["focal"]["local_id"]
    monkeypatch.setattr(store, "DB_PATH", client.journal.path)
    connections = routes()
    monkeypatch.setattr(llm, "settings", lambda task=None, **_k: connections.settings(task))
    monkeypatch.setattr(
        llm, "complete_result", lambda *_a, **_k: pytest.fail("No AI for index repair")
    )
    owner = observe_owner(
        client.journal.path, local, expected_native=generation._identity(client.journal.path)
    )
    view = ["loaded-paper"]
    widget = LineageDialog(
        client.journal.path,
        local,
        owner=owner,
        document=None,
        legacy_root=tmp_path,
        current_view=lambda: view[0],
        language="en",
    )
    widget.show()
    wait(app, lambda: not widget.busy)
    widget.mode.setCurrentIndex(1)
    wait(app, lambda: not widget.busy)
    assert len(widget.saved) == 1 and widget.repair_button.isEnabled()
    yield widget, client, view
    if widget.busy:
        widget.cancel()
        wait(app, lambda: not widget.busy)
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_actual_history_button_restores_two_saved_versions_once_without_ai_or_bytes(app, scene):
    widget, client, _view = scene
    before = stable_snapshot(client)
    for _ in range(20):
        widget.repair_button.click()
    wait(app, lambda: not widget.busy)
    assert len(widget.saved) == 2
    assert "Version index:" in widget.status.text() and "restored 1" in widget.status.text()
    assert stable_snapshot(client) == before
    image = Path(__file__).resolve().parents[1] / "build/lineage-history-index-repaired.png"
    assert widget.grab().save(str(image))
    assert not HistoryRepair(client).status()["more"]
    assert not widget.repair_button.isEnabled()


def test_cancel_held_index_job_then_retry_preserves_research(app, scene, monkeypatch):
    widget, client, _view = scene
    entered, release = threading.Event(), threading.Event()
    original = HistoryRepair.step

    def held(service, *args, **kwargs):
        entered.set()
        assert release.wait(20)
        return original(service, *args, **kwargs)

    before = dump(client)
    with monkeypatch.context() as patch:
        patch.setattr(HistoryRepair, "step", held)
        widget.repair_history()
        wait(app, entered.is_set)
        widget.cancel()
        release.set()
        wait(app, lambda: not widget.busy)
    assert dump(client) == before and len(widget.saved) == 1
    assert widget.repair_button.isEnabled()
    widget.repair_history()
    wait(app, lambda: not widget.busy)
    assert len(widget.saved) == 2


def test_close_held_repair_waits_for_cancel_and_worker_drain(app, scene, monkeypatch):
    widget, client, _view = scene
    entered, release = threading.Event(), threading.Event()
    original = HistoryRepair.step

    def held(service, *args, **kwargs):
        entered.set()
        assert release.wait(20)
        return original(service, *args, **kwargs)

    monkeypatch.setattr(HistoryRepair, "step", held)
    before = dump(client)
    widget.repair_history()
    wait(app, entered.is_set)
    widget.close()
    assert widget.busy and not widget.disposed
    release.set()
    wait(app, lambda: not widget.busy and widget.disposed)
    assert dump(client) == before


def test_changed_view_at_queued_delivery_does_not_replace_visible_saved_selection(app, scene):
    widget, client, view = scene
    original = list(widget.saved)
    widget.repair_history()
    worker = widget._worker
    deadline = time.monotonic() + 30
    while worker.isRunning():
        assert time.monotonic() < deadline
        time.sleep(0.005)
    view[0] = "another-paper"
    app.processEvents()
    wait(app, lambda: not widget.busy)
    assert widget._invalid and widget.saved == original
    assert not widget.repair_button.isEnabled()
    assert not HistoryRepair(client).status()["more"]
