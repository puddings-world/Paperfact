"""A joined workspace retains both offline edits and retries one explicit resolution."""

import json
import sqlite3
from datetime import datetime

import pytest
from test_workspace_sync import Native
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture

from paper_daily import sync_bootstrap, sync_recovery
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import CaptureConnection, expecting, observe_note
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import SyncSession

research = research_fixture
enrolled = enrolled_fixture
service = service_fixture


@pytest.mark.parametrize("rich_baseline", [False, True])
def test_joined_desktops_keep_both_edits_and_resolve_exactly_once(
    service, enrolled, tmp_path, monkeypatch, rich_baseline
):
    origin, authority, token, _ = service
    endpoint = "http://127.0.0.1:8765"
    origin.connect(endpoint, "workspace", "origin-device", token, Ticket())

    def edit(path, body):
        with sqlite3.connect(path, factory=CaptureConnection) as conn:
            identity = conn.execute("SELECT id FROM notes").fetchone()[0]
            with expecting(conn, [observe_note(conn, identity)]):
                conn.execute("UPDATE notes SET body=? WHERE id=?", (body, identity))
                conn.commit()

    def body(path):
        with sqlite3.connect(path) as conn:
            return conn.execute("SELECT body FROM notes").fetchone()[0]

    # Establish one shared rich creation identity before two independent edits.
    if rich_baseline:
        edit(enrolled[0], "Shared research baseline")
    origin.sync(Ticket())
    remote_token = authority.enroll("workspace", "travel-device")
    remote = SyncSession(
        enrolled[0], transport_factory=lambda url: Native(url, authority, [])
    )
    remote.connect(endpoint, "workspace", "travel-device", remote_token, Ticket())
    destination = tmp_path / "travel"
    from paper_daily import sync_research

    class ReceiverClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2030, 1, 1, tzinfo=tz)

    with monkeypatch.context() as patch:
        patch.setattr(sync_research, "datetime", ReceiverClock)
        assert sync_bootstrap.join(remote, destination, Ticket())["state"] == "metadata_ready"
    path = destination / "papers.db"
    travel = SyncSession(path, transport_factory=lambda url: Native(url, authority, []))
    travel.connect(endpoint, "workspace", "travel-device", remote_token, Ticket())
    edit(enrolled[0], "Desktop interpretation")
    edit(path, "Offline travel interpretation")
    assert body(enrolled[0]) == "Desktop interpretation"
    assert body(path) == "Offline travel interpretation"
    origin.sync(Ticket())
    result = travel.sync(Ticket())
    assert result["conflicts"] == 1
    client = travel._client(travel.identity, lambda: None)
    with client.journal.transaction() as conn:
        rows = conn.execute(
            "SELECT c.sequence,i.event FROM paperfact_sync_conflicts c "
            "JOIN paperfact_sync_inbox i ON i.sequence=c.sequence WHERE c.resolved_by IS NULL"
        ).fetchall()
    assert len(rows) == 1
    event = json.loads(rows[0][1])
    assert event["operation"]["payload"]["body"] == "Offline travel interpretation"
    assert body(path) == body(enrolled[0]) == "Desktop interpretation"
    archive = tmp_path / "conflict-backup.zip"
    sync_recovery.create(path, archive, blob_store=BlobStore(path.parent / "blobs"))
    restored = tmp_path / "restored-conflict"
    sync_recovery.restore_detached(archive, restored)
    assert body(restored / "papers.db") == "Desktop interpretation"
    with sqlite3.connect(restored / "papers.db") as conn:
        records = conn.execute(
            "SELECT table_name,data FROM recovery_records "
            "WHERE table_name IN ('paperfact_sync_conflicts','paperfact_sync_inbox')"
        ).fetchall()
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paperfact_sync_identity'"
        ).fetchone() is None
    conflicts = [json.loads(data) for table, data in records
                 if table == "paperfact_sync_conflicts"]
    inbox = [json.loads(data) for table, data in records if table == "paperfact_sync_inbox"]
    unresolved = [row for row in conflicts if row["resolved_by"] is None]
    assert len(unresolved) == 1
    retained = next(row for row in inbox if row["sequence"] == unresolved[0]["sequence"])
    assert json.loads(retained["event"])["operation"]["payload"]["body"] == (
        "Offline travel interpretation"
    )
    payload = dict(event["operation"]["payload"], body="Desktop and travel interpretations")
    first = client.resolve_conflict(rows[0][0], payload=payload, operation_id="reviewed-merge")
    repeated = client.resolve_conflict(rows[0][0], payload=payload, operation_id="reviewed-merge")
    assert first["operation_id"] == repeated["operation_id"]
    travel.sync(Ticket())
    origin.sync(Ticket())
    assert body(path) == body(enrolled[0]) == "Desktop and travel interpretations"
    accepted = authority.pull(token)
    travel.sync(Ticket())
    origin.sync(Ticket())
    assert authority.pull(token) == accepted
    assert not travel.sync(Ticket())["conflicts"]
