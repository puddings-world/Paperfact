"""Opt-in background sync exercises real captured operations and fixture authority."""

import threading

import pytest
from PySide6.QtWidgets import QApplication, QWidget
from test_sync_connection_dialog import wait
from test_workspace_sync import connect
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture

from paper_daily.desktop.continuous_sync import ContinuousSync, controller_for
from paper_daily.desktop.sync_connection_dialog import SyncConnectionDialog
from paper_daily.workspace_service import Ticket

research = research_fixture
enrolled = enrolled_fixture
service = service_fixture


@pytest.fixture
def control(service):
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.show()
    clock = [100.0]
    controller = ContinuousSync(service[0], parent, clock=lambda: clock[0])
    controller.timer.stop()
    yield app, parent, controller, clock
    controller.stop()
    wait(app, lambda: not controller.busy)
    parent.close()
    app.processEvents()


def run(control):
    app, _, controller, _ = control
    controller.tick()
    wait(app, lambda: not controller.busy)


def test_default_off_and_verified_login_never_upload_without_consent(control, service):
    _, _, controller, _ = control
    assert not controller.enable()
    connect(service)
    for _ in range(20):
        controller.tick()
        controller.local_changed()
    assert service[3] == ["session_info"]
    assert not controller.enabled and not controller.busy


def test_opt_in_syncs_actual_saved_research_and_repeat_calls_do_not_duplicate(control, service):
    _, _, controller, clock = control
    connect(service)
    assert controller.enable()
    run(control)
    published = service[1].pull(service[2])
    assert published and controller.summary()["result"]["pending"] == 0
    assert controller.state == "idle"
    for _ in range(30):
        assert controller.enable()
        controller.tick()
    assert service[1].pull(service[2]) == published
    clock[0] += 30
    run(control)
    assert service[1].pull(service[2]) == published
    assert controller.summary()["result"]["received"] == 0
    assert service[2] not in repr(controller.summary())


def test_local_change_debounces_without_delaying_due_poll(control, service):
    _, _, controller, clock = control
    connect(service)
    controller.enable()
    run(control)
    previous = len(service[3])
    controller.local_changed()
    for _ in range(50):
        controller.local_changed()
        controller.tick()
    assert len(service[3]) == previous
    clock[0] += 2
    run(control)
    assert len(service[3]) > previous


def test_busy_research_and_manual_session_block_an_automatic_pass(control, service):
    _, _, controller, _ = control
    connect(service)
    controller.enable()
    controller.blocked = lambda: True
    controller.tick()
    assert not controller.busy and service[3] == ["session_info"]
    controller.blocked = lambda: False
    with service[0]._job():
        controller.tick()
        assert not controller.busy
    run(control)
    assert controller.summary()["result"]["pending"] == 0


def test_offline_retry_preserves_outbox_uses_backoff_then_recovers(control, service, monkeypatch):
    _, _, controller, clock = control
    connect(service)
    original = service[0].sync
    before = service[0]._client(service[0].identity, lambda: None).journal.pending()
    def offline(*_a):
        raise ConnectionError("sensitive raw error must never become status")
    monkeypatch.setattr(service[0], "sync", offline)
    controller.enable()
    run(control)
    assert controller.enabled and controller.state == "offline"
    assert controller.summary()["retry_in"] == 10
    controller.local_changed()
    assert controller.summary()["retry_in"] == 10
    clock[0] += 10
    run(control)
    assert controller.summary()["retry_in"] == 20
    assert service[0]._client(service[0].identity, lambda: None).journal.pending() == before
    assert "sensitive" not in repr(controller.summary())
    monkeypatch.setattr(service[0], "sync", original)
    clock[0] += 20
    run(control)
    assert controller.state == "idle" and controller.summary()["result"]["pending"] == 0


@pytest.mark.parametrize("error", [PermissionError("private"), ValueError("private"),
                                 OSError("private"), RuntimeError("private")])
def test_nontransient_failures_pause_and_require_explicit_retry(
    control, service, monkeypatch, error
):
    _, _, controller, clock = control
    connect(service)
    calls = []
    def failed(*_a):
        calls.append(1)
        raise error
    monkeypatch.setattr(service[0], "sync", failed)
    controller.enable()
    run(control)
    assert not controller.enabled and controller.state == "paused"
    clock[0] += 1000
    controller.local_changed()
    controller.tick()
    assert calls == [1] and "private" not in repr(controller.summary())


def test_reconnect_same_identity_still_requires_new_opt_in(control, service):
    _, _, controller, _ = control
    connect(service)
    controller.enable()
    connect(service)
    controller.tick()
    assert not controller.enabled and controller.state == "changed"
    assert service[3] == ["session_info", "session_info"]


def test_disable_while_worker_waits_prevents_late_local_acceptance(control, service, monkeypatch):
    app, _, controller, _ = control
    connect(service)
    entered, release = threading.Event(), threading.Event()
    original = service[1].push
    def held(*a, **kw):
        entered.set()
        assert release.wait(8)
        return original(*a, **kw)
    monkeypatch.setattr(service[1], "push", held)
    controller.enable()
    controller.tick()
    wait(app, entered.is_set)
    for _ in range(30):
        controller.tick()
        controller.local_changed()
    controller.stop()
    release.set()
    wait(app, lambda: not controller.busy)
    assert not controller.enabled and controller.summary()["result"] is None
    # The server may have accepted one atomic prefix. Explicit retry deduplicates it.
    service[0].sync(Ticket())
    accepted = service[1].pull(service[2])
    service[0].sync(Ticket())
    assert accepted and service[1].pull(service[2]) == accepted
    assert len({row["head"]["operation"]["operation_id"] for row in accepted}) == len(accepted)


def test_owner_close_waits_for_worker_and_releases_window_safely(control, service, monkeypatch):
    app, parent, controller, _ = control
    connect(service)
    entered, release = threading.Event(), threading.Event()
    original = service[1].push
    def held(*a, **kw):
        entered.set()
        assert release.wait(8)
        return original(*a, **kw)
    monkeypatch.setattr(service[1], "push", held)
    controller.enable()
    controller.tick()
    wait(app, entered.is_set)
    assert not parent.close() and parent.isVisible()
    release.set()
    wait(app, lambda: not controller.busy and not parent.isVisible())
    assert not controller.enabled and controller.summary()["result"] is None


def test_connection_dialog_explicit_toggle_and_cancel_never_auto_enable(control, service):
    app, parent, controller, _ = control
    connect(service)
    view = SyncConnectionDialog(service[0], parent, language="en", automatic=controller)
    view.show()
    wait(app, lambda: view.binding is not None and not view.busy)
    assert view.automatic_box.isVisible() and not view.automatic_box.isChecked()
    assert service[3] == ["session_info"]
    view.automatic_box.click()
    assert controller.enabled and view.automatic_box.isChecked()
    view.automatic_box.click()
    assert not controller.enabled
    view.close()
    assert service[3] == ["session_info"]


def test_closing_settings_keeps_explicitly_enabled_sync_owned_by_window(control, service):
    app, parent, controller, _ = control
    connect(service)
    view = SyncConnectionDialog(service[0], parent, language="en", automatic=controller)
    view.show()
    wait(app, lambda: view.binding is not None and not view.busy)
    view.automatic_box.click()
    view.close()
    assert view.disposed and controller.enabled
    run(control)
    assert controller.summary()["result"]["pending"] == 0


def test_controller_reuse_never_duplicates_timers_or_implicitly_enables(service):
    app = QApplication.instance() or QApplication([])
    assert app
    parent = QWidget()
    try:
        first = controller_for(parent, service[0])
        assert controller_for(parent, service[0]) is first
        assert not first.enabled
    finally:
        parent.close()


def test_offline_backoff_is_capped_and_never_retried_by_event_flood(control, service, monkeypatch):
    _, _, controller, clock = control
    connect(service)
    def offline(*_a):
        raise TimeoutError()
    monkeypatch.setattr(service[0], "sync", offline)
    controller.enable()
    for expected in [10, 20, 40, 80, 160, 300, 300]:
        run(control)
        assert controller.summary()["retry_in"] == expected
        for _ in range(20):
            controller.local_changed()
        assert controller.summary()["retry_in"] == expected
        clock[0] += expected


def test_actual_revocation_preserves_pending_research_and_stops_polling(control, service):
    _, _, controller, clock = control
    connect(service)
    before = service[0]._client(service[0].identity, lambda: None).journal.pending()
    controller.enable()
    service[1].revoke(service[2])
    run(control)
    assert not controller.enabled and controller.state == "paused"
    assert service[0]._client(service[0].identity, lambda: None).journal.pending() == before
    calls = list(service[3])
    clock[0] += 1000
    controller.tick()
    assert service[3] == calls and "push" not in calls


def test_workspace_switch_stops_before_research_transport(control, service, tmp_path):
    _, _, controller, _ = control
    connect(service)
    controller.enable()
    service[0].workspace.current_path = lambda: tmp_path / "different.sqlite"
    run(control)
    assert not controller.enabled and controller.state == "paused"
    assert service[3] == ["session_info"]


def test_unbound_workspace_toggle_fails_closed_before_private_remote_research(
    tmp_path, monkeypatch
):
    import sqlite3

    from test_workspace_sync import Native

    from paper_daily import store
    from paper_daily.sync_service import ReferenceService
    from paper_daily.workspace_sync import SyncSession

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "unbound.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(store.SCHEMA)
    authority = ReferenceService(tmp_path / "remote.sqlite")
    token = authority.enroll("workspace", "device")
    calls = []
    session = SyncSession(path, transport_factory=lambda url: Native(url, authority, calls))
    session.connect("http://127.0.0.1:8765", "workspace", "device", token, Ticket())
    controller = ContinuousSync(session)
    controller.timer.stop()
    try:
        before = path.read_bytes()
        assert controller.enable()
        controller.timer.stop()
        controller.tick()
        wait(app, lambda: not controller.busy)
        assert controller.state == "paused" and not controller.enabled
        assert path.read_bytes() == before and calls == ["session_info"]
    finally:
        controller.stop()
        controller.timer.stop()


def test_hiding_settings_during_sync_does_not_destroy_window_worker(control, service, monkeypatch):
    app, parent, controller, _ = control
    connect(service)
    view = SyncConnectionDialog(service[0], parent, language="en", automatic=controller)
    view.show()
    wait(app, lambda: view.binding is not None and not view.busy)
    entered, release = threading.Event(), threading.Event()
    original = service[1].push
    def held(*a, **kw):
        entered.set()
        assert release.wait(8)
        return original(*a, **kw)
    monkeypatch.setattr(service[1], "push", held)
    view.automatic_box.click()
    controller.tick()
    wait(app, entered.is_set)
    assert not view.sync_button.isEnabled() and not view.connect_button.isEnabled()
    assert view.automatic_box.isEnabled()
    assert view.close()
    assert view.disposed and controller.busy
    release.set()
    wait(app, lambda: not controller.busy)
    assert controller.enabled and controller.summary()["result"]["pending"] == 0


def test_restart_waits_for_active_sync_without_invoking_installer():
    from paper_daily.desktop.main import MainWindow

    class Automatic:
        busy = True
        stopped = False
        def stop(self):
            self.stopped = True
    class Window:
        _continuous_sync = Automatic()
    window = Window()
    assert not MainWindow._prepare_restart(window)
    assert window._continuous_sync.stopped


def test_bilingual_status_labels_remain_real_text():
    from paper_daily.desktop.continuous_sync import COPY
    assert COPY["zh-TW"]["off"] == "自動同步已關閉"
    assert "本機變更" in COPY["zh-TW"]["offline"]
    assert all("?" not in text for locale in COPY.values() for text in locale.values())


def test_new_committed_change_shows_waiting_not_a_stale_synced_state(control, service):
    _, _, controller, _ = control
    connect(service)
    controller.enable()
    run(control)
    assert controller.state == "idle"
    previous = dict(controller.summary()["result"])
    controller.local_changed()
    assert controller.state == "waiting"
    assert controller.summary()["result"] == previous
