"""Actual bounded device dialog guards repeated/late actions without vault or AI."""

import sqlite3
import threading
from contextlib import closing
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from test_sync_connection_dialog import connected, fill, wait
from test_workspace_sync import connect
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture

from paper_daily.desktop.devices_dialog import DevicesDialog, DeviceWorker
from paper_daily.desktop.sync_connection_dialog import SyncConnectionDialog
from paper_daily.workspace_service import Ticket

research = research_fixture
enrolled = enrolled_fixture
service = service_fixture


@pytest.fixture
def view(service, monkeypatch):
    from paper_daily import connection_vault, llm

    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("Devices called AI"))
    monkeypatch.setattr(
        connection_vault.ConnectionVault,
        "__init__",
        lambda *a, **k: pytest.fail("Devices opened native vault"),
    )
    app = QApplication.instance() or QApplication([])
    service[1].enroll("workspace", "peer")
    connect(service)
    dialog = DevicesDialog(service[0], language="en")
    dialog.show()
    wait(app, lambda: not dialog.busy and dialog.devices.topLevelItemCount() == 2)
    yield app, dialog
    if dialog.busy:
        dialog.cancel()
        wait(app, lambda: not dialog.busy)
    dialog.close()


def select(view, device_id):
    for index in range(view.devices.topLevelItemCount()):
        item = view.devices.topLevelItem(index)
        if item.text(0) == device_id:
            view.devices.setCurrentItem(item)
            return item
    raise AssertionError("Fixture device not found")


def test_list_label_clear_and_revoke_show_saved_state(view, service, monkeypatch):
    app, dialog = view
    current = select(dialog, "origin-device")
    assert current.text(2) == "This device" and not dialog.revoke_button.isEnabled()
    peer = select(dialog, "peer")
    dialog.label.setText("Reading phone")
    dialog.rename_button.click()
    wait(app, lambda: not dialog.busy)
    assert peer.text(1) == "Reading phone"
    assert service[1].device_catalog(service[2])["devices"][1]["label"] == "Reading phone"
    dialog.label.clear()
    dialog.rename_button.click()
    wait(app, lambda: not dialog.busy)
    assert peer.text(1) == ""
    assert service[1].device_catalog(service[2])["devices"][1]["label"] is None
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog.revoke_button.click()
    wait(app, lambda: not dialog.busy)
    assert peer.text(2) == "Revoked" and not dialog.revoke_button.isEnabled()
    assert service[1].device_catalog(service[2])["devices"][1]["revoked"]


def test_empty_selection_invalid_label_and_cancelled_revoke_send_nothing(
    view, service, monkeypatch
):
    _, dialog = view
    before = list(service[3])
    dialog.devices.setCurrentItem(None)
    assert not dialog.rename() and not dialog.revoke()
    assert not dialog.rename_button.isEnabled() and not dialog.revoke_button.isEnabled()
    select(dialog, "peer")
    dialog.label.setText(" invalid ")
    assert not dialog.rename() and "single-line" in dialog.status.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    assert not dialog.revoke()
    assert service[3] == before


def test_valid_non_bmp_label_is_not_truncated_by_qt_edit_limit(view, service):
    app, dialog = view
    label = "😀" * 64
    service[1].rename_device(service[2], "peer", label)
    dialog.refresh()
    wait(app, lambda: not dialog.busy)
    assert select(dialog, "peer").text(1) == label and dialog.label.text() == label
    dialog.rename_button.click()
    wait(app, lambda: not dialog.busy)
    assert service[1].device_catalog(service[2])["devices"][1]["label"] == label


def test_rapid_label_saves_create_one_worker_and_one_change(view, service, monkeypatch):
    app, dialog = view
    select(dialog, "peer")
    dialog.label.setText("Phone")
    entered, release, calls = threading.Event(), threading.Event(), []
    original = service[1].rename_device

    def held(*args):
        calls.append(1)
        entered.set()
        assert release.wait(8)
        return original(*args)

    monkeypatch.setattr(service[1], "rename_device", held)
    dialog.rename_button.click()
    wait(app, entered.is_set)
    try:
        for _ in range(30):
            assert not dialog.rename()
        assert not dialog.refresh() and not dialog.rename_button.isEnabled()
    finally:
        release.set()
    wait(app, lambda: not dialog.busy)
    assert calls == [1] and select(dialog, "peer").text(1) == "Phone"


def test_stop_after_remote_label_commit_keeps_view_stale_until_explicit_refresh(
    view, service, monkeypatch
):
    app, dialog = view
    peer = select(dialog, "peer")
    dialog.label.setText("Phone")
    original = service[1].rename_device

    def late(*args):
        result = original(*args)
        dialog._worker.ticket.cancel()
        return result

    monkeypatch.setattr(service[1], "rename_device", late)
    dialog.rename()
    wait(app, lambda: not dialog.busy)
    assert "Refresh to check" in dialog.status.text() and peer.text(1) == ""
    monkeypatch.setattr(service[1], "rename_device", original)
    dialog.refresh()
    wait(app, lambda: not dialog.busy)
    assert select(dialog, "peer").text(1) == "Phone"


@pytest.mark.parametrize("change", ["disconnect", "workspace", "close"])
def test_late_list_does_not_repaint_changed_or_closed_context(
    view, service, tmp_path, monkeypatch, change
):
    app, dialog = view
    entered, release = threading.Event(), threading.Event()
    original = service[1].device_catalog

    def held(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(8)
        return result

    monkeypatch.setattr(service[1], "device_catalog", held)
    dialog.refresh()
    wait(app, entered.is_set)
    before = dialog.devices.topLevelItem(0)
    try:
        if change == "disconnect":
            service[0].disconnect()
        elif change == "workspace":
            service[0].workspace.current_path = lambda: tmp_path / "other.sqlite"
        else:
            assert not dialog.close() and not dialog.disposed
    finally:
        release.set()
    wait(app, lambda: not dialog.busy)
    if change == "close":
        wait(app, lambda: dialog.disposed)
    else:
        assert "changed" in dialog.status.text() and not dialog.refresh_button.isEnabled()
        assert dialog.devices.topLevelItem(0) is before
    assert not (tmp_path / "other.sqlite").exists()


def test_revoked_credential_disables_controls_and_requests_reconnect(view, service):
    app, dialog = view
    service[1].revoke(service[2])
    dialog.refresh()
    wait(app, lambda: not dialog.busy)
    assert "Reconnect" in dialog.status.text()
    assert not dialog.refresh_button.isEnabled() and not service[0].summary()["authenticated"]


def test_sql_binding_change_disables_view_before_device_request(view, service):
    app, dialog = view
    before = list(service[3])
    with closing(sqlite3.connect(service[0].workspace.path)) as conn, conn:
        conn.execute("UPDATE research_capture_binding SET workspace='foreign' WHERE id=1")
    dialog.refresh()
    wait(app, lambda: not dialog.busy)
    assert "changed" in dialog.status.text() and not dialog.refresh_button.isEnabled()
    assert service[3] == before


def test_changed_connection_during_confirmation_sends_no_revoke(view, service, monkeypatch):
    _, dialog = view
    select(dialog, "peer")
    before = list(service[3])

    def changed(*args, **kwargs):
        service[0].disconnect()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", changed)
    assert not dialog.revoke() and service[3] == before
    assert not service[1].device_catalog(service[2])["devices"][1]["revoked"]


def test_completed_old_worker_cannot_repaint_new_authenticated_connection(
    view, service, monkeypatch
):
    app, dialog = view
    entered, release = threading.Event(), threading.Event()
    original = DeviceWorker.run

    def held(worker):
        original(worker)  # Session job lock has been released; Qt delivery is still pending.
        entered.set()
        assert release.wait(8)

    monkeypatch.setattr(DeviceWorker, "run", held)
    before = dialog.devices.topLevelItem(0)
    dialog.refresh()
    wait(app, entered.is_set)
    token = service[1].enroll("workspace", "another-device")
    try:
        service[0].connect("http://127.0.0.1:8765", "workspace", "another-device", token, Ticket())
    finally:
        release.set()
    wait(app, lambda: not dialog.busy)
    assert dialog.devices.topLevelItem(0) is before and "changed" in dialog.status.text()
    assert service[0].summary()["identity"]["device_id"] == "another-device"
    assert service[0].summary()["authenticated"] and not dialog.refresh_button.isEnabled()


def test_service_failure_retry_keeps_previous_list(view, service, monkeypatch):
    app, dialog = view
    original = service[1].device_catalog

    def fail(*args, **kwargs):
        raise ConnectionError("private backend text")

    monkeypatch.setattr(service[1], "device_catalog", fail)
    dialog.refresh()
    wait(app, lambda: not dialog.busy)
    assert dialog.devices.topLevelItemCount() == 2 and dialog.refresh_button.isEnabled()
    assert "unavailable" in dialog.status.text() and "private" not in dialog.status.text()
    monkeypatch.setattr(service[1], "device_catalog", original)
    dialog.refresh()
    wait(app, lambda: not dialog.busy)
    assert dialog.status.text() == "Devices loaded."


def test_worker_start_failure_is_retryable(view, monkeypatch):
    app, dialog = view
    original = DeviceWorker.start

    def fail(_self):
        raise RuntimeError("thread unavailable")

    monkeypatch.setattr(DeviceWorker, "start", fail)
    assert not dialog.refresh() and not dialog.busy
    assert "did not complete" in dialog.status.text()
    monkeypatch.setattr(DeviceWorker, "start", original)
    assert dialog.refresh()
    wait(app, lambda: not dialog.busy)
    assert dialog.status.text() == "Devices loaded."


def test_paginated_dialog_retains_one_bounded_page(view, service):
    app, dialog = view
    for index in range(55):
        service[1].enroll("workspace", f"device-{index:03}")
    dialog.refresh()
    wait(app, lambda: not dialog.busy)
    assert dialog.devices.topLevelItemCount() == 50 and dialog.next_button.isEnabled()
    dialog.next_button.click()
    wait(app, lambda: not dialog.busy)
    assert dialog.devices.topLevelItemCount() == 7 and not dialog.next_button.isEnabled()
    assert not dialog.next_page()
    dialog.refresh_button.click()
    wait(app, lambda: not dialog.busy)
    assert dialog.devices.topLevelItemCount() == 50


def test_connection_devices_entry_is_current_bound_singleton_and_closes_active_child(service):
    app = QApplication.instance() or QApplication([])
    parent = SyncConnectionDialog(
        service[0], language="en", vault=SimpleNamespace(current=lambda: True)
    )
    parent.show()
    wait(app, lambda: parent.binding is not None and not parent.busy)
    assert not parent.devices_button.isEnabled() and not parent.open_devices()
    connected((app, parent), service)
    assert parent.devices_button.isEnabled()
    child = parent.open_devices()
    wait(app, lambda: not child.busy and child.devices.topLevelItemCount() == 1)
    assert parent.open_devices() is child
    child.close()
    fill(parent, service[1].enroll("foreign", "foreign-device"), "foreign-device")
    parent.workspace_id.setText("foreign")
    parent.connect_session()
    wait(app, lambda: not parent.busy)
    assert not parent.devices_button.isEnabled() and not parent.open_devices()
    parent.close()


def test_parent_close_waits_for_device_worker_and_late_result_is_not_applied(service, monkeypatch):
    app = QApplication.instance() or QApplication([])
    connect(service)
    parent = SyncConnectionDialog(
        service[0], language="en", vault=SimpleNamespace(current=lambda: True)
    )
    parent.show()
    wait(app, lambda: parent.binding is not None and not parent.busy)
    child = parent.open_devices()
    wait(app, lambda: not child.busy and child.devices.topLevelItemCount() == 1)
    entered, release = threading.Event(), threading.Event()
    original = service[1].device_catalog

    def held(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(8)
        return result

    monkeypatch.setattr(service[1], "device_catalog", held)
    child.refresh()
    wait(app, entered.is_set)
    try:
        assert parent.busy and not parent.close() and not parent.disposed
    finally:
        release.set()
    wait(app, lambda: parent.disposed and child.disposed)
    assert service[0].summary()["authenticated"]
