"""Actual desktop pairing, native resume and cancellation/context fences."""

import sqlite3
from contextlib import closing
from threading import Event

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from test_sync_connection_dialog import wait
from test_sync_pairing_flow import receiver as receiver_fixture
from test_workspace_dialog import app as qt_app_fixture
from test_workspace_sync import connect
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture

from paper_daily.connection_vault import ConnectionVault
from paper_daily.desktop.devices_dialog import DevicesDialog
from paper_daily.desktop.sync_connection_dialog import SyncConnectionDialog
from paper_daily.sync_pairing import Invitation
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import SyncSession

research = research_fixture
enrolled = enrolled_fixture
service = service_fixture
receiver = receiver_fixture
qt_app = qt_app_fixture


@pytest.fixture(autouse=True)
def initialized_qt(qt_app):
    yield qt_app
    qt_app.processEvents()


def app():
    return QApplication.instance() or QApplication([])


def view_for(receiver, **kwargs):
    view = SyncConnectionDialog(receiver[0], language="en", vault=receiver[1], **kwargs)
    view.show()
    wait(app(), lambda: view._probed and not view.busy)
    return view


def sender_for(session, language="en"):
    view = DevicesDialog(session, language=language)
    view.show()
    wait(app(), lambda: not view.busy and view.devices.topLevelItemCount() > 0)
    return view


def pair(view, invitation):
    view.connection_details.setText(invitation.encoded())
    assert view.pair_device() and not view.pair_device()
    wait(app(), lambda: not view.busy)


def test_issued_clipboard_pairing_joins_and_remembers_only_the_new_workspace(
    receiver, service, tmp_path, monkeypatch
):
    connect(service)
    service[0].sync(Ticket())
    sender = sender_for(service[0])
    opened = []
    view = view_for(receiver, open_workspace=opened.append)
    try:
        QApplication.clipboard().setText("synthetic clipboard before pairing")
        assert sender.create_pairing() and not sender.create_pairing()
        wait(app(), lambda: not sender.busy)
        assert QApplication.clipboard().text() == "synthetic clipboard before pairing"
        assert sender.copy_pairing()
        packet = QApplication.clipboard().text()
        assert service[2] not in packet
        invitation = Invitation.decoded(packet)
        with service[1]._transaction() as conn:
            grants = conn.execute("SELECT count(*) FROM sync_pairings").fetchone()[0]
        monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.No)
        assert not sender.create_pairing()
        with service[1]._transaction() as conn:
            assert conn.execute("SELECT count(*) FROM sync_pairings").fetchone()[0] == grants
        pair(view, invitation)
        record = receiver[1].load()
        assert record is not None and record.token != service[2]
        assert receiver[1].load_pairing() is None
        assert not view.credential.text() and not view.connection_details.text()
        assert view.join_button.isVisible() and view.join_button.isEnabled()
        assert not view.advanced_panel.isVisible()
        destination = tmp_path / "joined"
        assert view.start_join(destination) and not view.start_join(destination)
        wait(app(), lambda: not view.busy)
        assert (destination / "papers.db").is_file(), view.status.text()
        assert view.created_destination is not None
        fresh = SyncSession(destination / "papers.db", transport_factory=receiver[4])
        stored = ConnectionVault(fresh.workspace, backend=lambda: receiver[2]).load()
        assert stored == record
        assert view.open_created() and not view.open_created()
        assert len(opened) == 1 and opened[0].database_path == destination / "papers.db"
        assert len(service[1].device_catalog(service[2])["devices"]) == 2
        with closing(sqlite3.connect(destination / "papers.db")) as conn:
            assert conn.execute("SELECT count(*) FROM papers").fetchone()[0] > 0
    finally:
        sender.close()
        view.close()
        wait(app(), lambda: not sender.busy and not view.busy)


def test_lost_reply_can_resume_from_the_connection_button_after_dialog_restart(
    receiver, service, monkeypatch
):
    original = service[1].redeem_pairing
    claimed = []

    def lost(*args, **kwargs):
        claimed.append(original(*args, **kwargs))
        raise ConnectionError("synthetic lost reply")

    monkeypatch.setattr(service[1], "redeem_pairing", lost)
    view = view_for(receiver)
    pair(view, receiver[3])
    assert receiver[1].load_pairing() is not None
    assert not receiver[0].summary()["authenticated"]
    assert view.close()
    fresh = SyncSession(receiver[0].workspace.path, transport_factory=receiver[4])
    vault = ConnectionVault(fresh.workspace, backend=lambda: receiver[2])
    resumed = SyncConnectionDialog(fresh, language="en", vault=vault)
    try:
        resumed.show()
        wait(app(), lambda: resumed._probed and not resumed.busy)
        assert resumed.reconnect_saved()
        wait(app(), lambda: not resumed.busy)
        assert fresh.summary()["authenticated"] and vault.load_pairing() is None
        assert len(claimed) == 1 and not resumed.credential.text()
        assert resumed.join_button.isVisible()
    finally:
        resumed.close()


def test_close_after_remote_claim_drains_worker_and_retains_secure_retry_state(
    receiver, service, monkeypatch
):
    entered, release = Event(), Event()
    original = service[1].redeem_pairing

    def held(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(8)
        return result

    monkeypatch.setattr(service[1], "redeem_pairing", held)
    view = view_for(receiver)
    view.connection_details.setText(receiver[3].encoded())
    try:
        assert view.pair_device()
        wait(app(), entered.is_set)
        assert not view.close()
    finally:
        release.set()
    wait(app(), lambda: not view.busy)
    assert view.disposed and not receiver[0].summary()["authenticated"]
    assert receiver[1].load_pairing() is not None
    assert len(service[1].device_catalog(service[2])["devices"]) == 2


def test_queued_invitation_cannot_be_copied_after_local_binding_changes(service):
    connect(service)
    view = sender_for(service[0])
    try:
        QApplication.clipboard().setText("synthetic unchanged clipboard")
        assert view.create_pairing()
        assert view._worker.wait(5000)
        with closing(sqlite3.connect(service[0].workspace.path)) as conn, conn:
            conn.execute("UPDATE paperfact_sync_identity SET device='changed-device'")
        wait(app(), lambda: not view.busy)
        assert view._invalid and view._invitation is None
        assert not view.copy_pairing()
        assert QApplication.clipboard().text() == "synthetic unchanged clipboard"
        assert view.status.text() == view.t["changed"]
    finally:
        view.close()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_pairing_controls_render_in_both_languages_without_secrets(receiver, service, language):
    from pathlib import Path

    from PySide6.QtGui import QRawFont

    from paper_daily.desktop import fonts, settings_style

    gui = app()
    previous = gui.font()
    fonts.load()
    gui.setFont(fonts.font(pixels=14))
    assert all(QRawFont.fromFont(gui.font()).glyphIndexesForString("Paperfact " + chr(37197)))
    connect(service)
    sender = DevicesDialog(service[0], language=language)
    receiver_view = SyncConnectionDialog(receiver[0], language=language, vault=receiver[1])
    try:
        for view in (sender, receiver_view):
            settings_style.apply(view)
            view.resize(700, 740)
            view.show()
            wait(
                gui,
                lambda view=view: (
                    not view.busy
                    and (
                        view.devices.topLevelItemCount() > 0
                        if isinstance(view, DevicesDialog)
                        else view._probed
                    )
                ),
            )
        sender.create_pairing()
        wait(gui, lambda: not sender.busy)
        for name, view in (("send", sender), ("receive", receiver_view)):
            target = Path.cwd() / "build" / f"pairing-{name}-{language}.png"
            assert view.grab().save(str(target))
    finally:
        sender.close()
        receiver_view.close()
        gui.setFont(previous)
