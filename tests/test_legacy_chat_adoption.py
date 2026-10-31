"""Legacy migration base must preserve canonical explicit chat-link enrollment."""

import hashlib
import sqlite3
from contextlib import closing

from test_enrollment_chat_history import ask, prepare
from test_enrollment_chat_history import source as source_fixture
from test_recovery_adoption import prepared
from test_sync_source_files import pdf

from paper_daily import enrollment_chat_history, sync_recovery
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.workspace_service import Ticket

source = source_fixture


def test_actual_chat_history_A_primary_B_retains_explicit_links_during_adoption(
    source, tmp_path, monkeypatch
):
    primary, _job = ask(source, monkeypatch)
    original = primary.with_name("original.pdf")
    primary.rename(original)
    primary.write_bytes(pdf("Current primary B"))
    initial = prepare(source, tmp_path, primary)
    detached = tmp_path / "restored-chat"
    sync_recovery.restore_detached(initial["backup"], detached)
    with closing(sqlite3.connect(detached / "papers.db")) as conn:
        expected = enrollment_chat_history.live_inventory(conn, Ticket())["links"]
    service = RecoveryAdoptionService(detached / "papers.db")
    copied = prepared(service, service.inspect(), tmp_path, "-chat")
    with closing(sqlite3.connect(copied["database"])) as conn:
        actual = enrollment_chat_history.live_inventory(conn, Ticket())["links"]
        assert actual == expected and len(actual) == 2
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_chat_requests'"
        ).fetchone()
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
        ).fetchone()[0]
        from paper_daily.sync_source_files import resolved

        assert (
            resolved(
                conn, portable, hashlib.sha256(original.read_bytes()).hexdigest()
            ).read_bytes()
            == original.read_bytes()
        )
    assert sync_recovery.inspect(copied["backup"])["workspace_id"] == copied["workspace_id"]
