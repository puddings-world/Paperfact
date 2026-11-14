"""Two desktop controllers continue actual research across an offline restart."""

import sqlite3
import threading

from PySide6.QtWidgets import QApplication
from test_sync_connection_dialog import wait
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture

from paper_daily import sync_bootstrap
from paper_daily.desktop.continuous_sync import ContinuousSync
from paper_daily.sync_capture import CaptureConnection, expecting, observe_note
from paper_daily.sync_http import make_server
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import SyncSession

research = research_fixture
enrolled = enrolled_fixture
service = service_fixture


def test_two_desktops_keep_offline_note_after_restart_and_retry_without_duplicates(
    service, enrolled, tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    origin, authority, origin_token, _calls = service
    server = make_server(authority)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    controllers = []
    clock = [100.0]

    def control(session):
        value = ContinuousSync(session, clock=lambda: clock[0])
        value.timer.stop()
        controllers.append(value)
        assert value.enable()
        return value

    def run(value):
        value.tick()
        wait(app, lambda: not value.busy)

    def notes(database):
        with sqlite3.connect(database) as conn:
            return conn.execute("SELECT body FROM notes ORDER BY id").fetchall()

    try:
        origin.connect(endpoint, "workspace", "origin-device", origin_token, Ticket())
        first = control(origin)
        run(first)
        assert first.state == "idle"
        token = authority.enroll("workspace", "travel-device")
        joining = SyncSession(enrolled[0])
        joining.connect(endpoint, "workspace", "travel-device", token, Ticket())
        destination = tmp_path / "travel"
        assert sync_bootstrap.join(joining, destination, Ticket())["state"] == "metadata_ready"
        database = destination / "papers.db"
        assert notes(database) == [("Saved research",)]
        travel = SyncSession(database)
        travel.connect(endpoint, "workspace", "travel-device", token, Ticket())
        second = control(travel)
        with sqlite3.connect(database, factory=CaptureConnection) as conn:
            note_id = conn.execute("SELECT id FROM notes").fetchone()[0]
            with expecting(conn, [observe_note(conn, note_id)]):
                conn.execute("UPDATE notes SET body=? WHERE id=?",
                             ("Offline travel interpretation", note_id))
                conn.commit()
        assert travel._client(travel.identity, lambda: None).journal.pending()
        second.local_changed()
        original_sync = travel.sync

        def offline(*_args, **_kwargs):
            raise ConnectionError("fixture offline")

        monkeypatch.setattr(travel, "sync", offline)
        run(second)
        assert second.state == "offline" and second.enabled
        assert notes(enrolled[0]) == [("Saved research",)]
        assert notes(database) == [("Offline travel interpretation",)]
        second.stop()
        travel.disconnect()
        # New session/controller reconstructs durable outbox, with explicit new consent.
        restarted = SyncSession(database)
        restarted.connect(endpoint, "workspace", "travel-device", token, Ticket())
        third = control(restarted)
        run(third)
        assert third.state == "idle" and third.summary()["result"]["pending"] == 0
        accepted = authority.pull(token)
        clock[0] += 30
        run(first)
        assert notes(enrolled[0]) == notes(database) == [("Offline travel interpretation",)]
        for _ in range(20):
            third.local_changed()
        clock[0] += 2
        run(third)
        assert authority.pull(token) == accepted
        assert not third.summary()["result"]["conflicts"]
        monkeypatch.setattr(travel, "sync", original_sync)
    finally:
        for value in controllers:
            value.stop()
        for value in controllers:
            wait(app, lambda value=value: not value.busy)
            value.timer.stop()
        server.shutdown()
        server.server_close()
        thread.join(5)
