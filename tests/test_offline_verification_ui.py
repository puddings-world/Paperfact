"""Actual offscreen dialog resumes exact selected byte verification."""

import threading

import pytest
from PySide6.QtWidgets import QApplication
from test_offline_dialog import wait
from test_sync_files import codec as codec_fixture
from test_sync_transfers import attach
from test_sync_transfers import setup as transfer_setup_fixture
from test_workspace_offline import add_deck
from test_workspace_offline import prepared as prepared_fixture

from paper_daily import workspace_offline as offline
from paper_daily.desktop.offline_dialog import OfflineDialog
from paper_daily.workspace_offline_verification import OfflineVerification

codec = codec_fixture
transfer_setup = transfer_setup_fixture
prepared = prepared_fixture


@pytest.fixture
def window(prepared):
    app = QApplication.instance() or QApplication([])
    service, client, local, *_ = prepared
    view = OfflineDialog(
        client.journal.path, [local], language="en", service_factory=lambda *args, **kwargs: service
    )
    view.show()
    wait(app, lambda: view._plan is not None and not view.busy)
    yield app, view, service, local
    if view.busy:
        view.cancel()
        wait(app, lambda: not view.busy)
    view.close()
    view.deleteLater()
    app.processEvents()


def limited_passes(monkeypatch, service, local):
    plan = service.plan([local])
    budget = plan["required_bytes"] - plan["papers"][0]["pdf"]["target"]["size"]
    original = OfflineVerification.advance

    def advance(self, *args, **kwargs):
        kwargs["max_bytes"] = budget
        return original(self, *args, **kwargs)

    monkeypatch.setattr(OfflineVerification, "advance", advance)


def test_continue_button_accumulates_real_progress_and_completed_verify_starts_fresh(
    window,
    prepared,
    codec,
    monkeypatch,
):
    app, view, service, local = window
    add_deck(prepared, codec)
    view.refresh()
    wait(app, lambda: not view.busy)
    limited_passes(monkeypatch, service, local)
    calls = []
    original = offline.verify_document

    def counted(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(offline, "verify_document", counted)
    progress = []
    show = view._verification_progress

    def observed(event):
        progress.append(event.copy())
        show(event)

    monkeypatch.setattr(view, "_verification_progress", observed)
    view.verify_button.click()
    view.verify_button.click()
    wait(app, lambda: not view.busy)
    assert not view._plan["ready"] and view.last_verified_at is None
    assert view.verify_button.text() == view.t["resume"]
    assert "1/4" in view.status.text()
    first_session = view._verification_session
    view.verify_button.click()
    wait(app, lambda: not view.busy)
    assert view._plan["ready"] and view.last_verified_at is not None
    assert calls == [1] and view._verification_session is None
    assert first_session is not None
    assert any(event["verified_assets"] == event["required_assets"] == 4 for event in progress)
    assert all(0 < event["verified_assets"] <= event["required_assets"] for event in progress)
    assert view.verify_button.text() == view.t["verify"]
    # A deliberate new check must rehash bytes, unlike the unfinished session.
    view.verify_button.click()
    wait(app, lambda: not view.busy)
    assert calls == [1, 1] and view._verification_session is not None


def test_source_update_between_passes_invalidates_resume_without_activating_new_pdf(
    window,
    prepared,
    codec,
    transfer_setup,
    tmp_path,
    monkeypatch,
):
    app, view, service, local = window
    add_deck(prepared, codec)
    limited_passes(monkeypatch, service, local)
    view.verify()
    wait(app, lambda: not view.busy)
    assert view._verification_session is not None and not view._plan["ready"]
    attach(transfer_setup, tmp_path, request_id="changed-current", text="Replacement source")
    view.verify()
    wait(app, lambda: not view.busy)
    assert view._verification_session is None and view.last_verified_at is None
    assert "changed" in view.status.text().lower()
    assert not service.status([local])["ready"]


def test_close_waits_for_native_stage_and_cannot_leave_a_ready_flag(window, monkeypatch):
    app, view, service, _local = window
    entered, release = threading.Event(), threading.Event()
    original = offline.verify_document

    def controlled(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(offline, "verify_document", controlled)
    view.verify()
    wait(app, entered.is_set)
    assert not view.close() and view.busy
    release.set()
    wait(app, lambda: view.disposed)
    assert view.last_verified_at is None and view._verification_session is None
    assert not service.pins()
