"""Incomplete experimental capabilities refuse writes; upgrade makes a new copy."""

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_sync_capture import bound as bound_fixture
from test_sync_capture import make, seed

from paper_daily import store, sync_recovery
from paper_daily.legacy_briefs import record_pack
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.sync_service import ReferenceService

bound = bound_fixture
STAMP = "2026-10-30T12:34:56+08:00"


def old_prototype(bound, tmp_path):
    seed()
    path = bound.journal.path.parent / "briefs" / "2026-10-30" / "pack.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"# Exact legacy original")
    with bound.journal.transaction() as conn:
        conn.execute("DROP TABLE research_legacy_brief_targets")
        for table in ("queue", "reading_log"):
            for action in ("insert", "update", "delete"):
                conn.execute('DROP TRIGGER "capture_' + table + "_" + action + '"')
        conn.execute(
            "INSERT INTO queue(paper_id,rank,role,queued_at) VALUES('local-paper',9,'manual',?)",
            (STAMP,),
        )
        conn.execute(
            "INSERT INTO reading_log VALUES(27,?,?,?,?,?)",
            ("local-paper", STAMP, str(path), "manual", "Original note"),
        )
    return path


def test_old_enrolled_prototype_remains_readable_without_implicit_schema_or_writes(bound, tmp_path):
    path = old_prototype(bound, tmp_path)
    before = bound.journal.path.read_bytes()
    with store.connect() as conn:
        assert conn.execute("SELECT note FROM reading_log").fetchone()[0] == "Original note"
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_legacy_brief_targets'"
        ).fetchone()
        with pytest.raises(ValueError, match="Legacy workflow migration required"):
            record_pack(
                conn, "local-paper", STAMP, "manual", b"# New pack", legacy_day="2026-10-30"
            )
        with pytest.raises(sqlite3.DatabaseError, match="authorized"):
            conn.execute("UPDATE queue SET rank=10")
        assert conn.execute("SELECT rank FROM queue").fetchone()[0] == 9
    assert (
        bound.journal.path.read_bytes() == before
        and path.read_bytes() == b"# Exact legacy original"
    )


def test_actual_old_prototype_backup_restore_new_editable_copy_is_the_upgrade(bound, tmp_path):
    path = old_prototype(bound, tmp_path)
    before = bound.journal.path.read_bytes()
    package = tmp_path / "old.zip"
    sync_recovery.create(bound.journal.path, package)
    detached = tmp_path / "old-detached"
    sync_recovery.restore_detached(package, detached)
    service = RecoveryAdoptionService(detached / "papers.db")
    inspection = service.inspect()
    assert inspection.report["supported"]
    result = service.prepare(
        inspection,
        tmp_path / "new-editable",
        backup_output=tmp_path / "new.zip",
        request_id=str(uuid4()),
    )
    with closing(sqlite3.connect(result["database"])) as conn:
        assert conn.execute("SELECT rank,role,queued_at FROM queue").fetchall() == [
            (9, "manual", STAMP)
        ]
        row = conn.execute("SELECT id,delivered_at,brief_path,note FROM reading_log").fetchone()
        assert row[0:2] == (27, STAMP) and row[3] == "Original note"
        assert Path(row[2]).read_bytes() == path.read_bytes()
        assert conn.execute("SELECT COUNT(*) FROM research_legacy_brief_targets").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' "
                "AND name LIKE 'capture_reading_log_%'"
            ).fetchone()[0]
            == 3
        )
    assert bound.journal.path.read_bytes() == before
    assert sync_recovery.inspect(result["backup"])["workspace_id"] == result["workspace_id"]


def test_incomplete_receiver_capability_rolls_back_inbox_cursor_and_projection(bound, tmp_path):
    seed()
    with store.connect() as conn:
        record_pack(conn, "local-paper", STAMP, "manual", b"# Exact pack", legacy_day="2026-10-30")
    authority = ReferenceService(tmp_path / "authority.db")
    ta, tb = authority.enroll("workspace", "a"), authority.enroll("workspace", "b")
    for op in bound.journal.pending():
        if op["entity_type"] != "research_file":
            assert authority.push(ta, op)["outcome"] == "accepted"
    peer = make(tmp_path / "peer.db", "b")
    with peer.journal.transaction() as conn:
        conn.execute("DROP TABLE research_legacy_brief_targets")
    with pytest.raises(ValueError, match="Legacy workflow migration required"):
        peer.receive(authority.pull(tb))
    with peer.journal.transaction() as conn:
        assert conn.execute("SELECT sequence FROM paperfact_sync_cursor").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM paperfact_sync_inbox").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM reading_log").fetchone()[0] == 0
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_legacy_brief_targets'"
        ).fetchone()


@pytest.mark.parametrize("change", ["missing-trigger", "wrong-trigger", "missing-file-table"])
def test_partial_capability_is_refused_before_delivery_and_never_repaired(bound, change):
    seed()
    with bound.journal.transaction() as conn:
        if change in {"missing-trigger", "wrong-trigger"}:
            conn.execute("DROP TRIGGER capture_queue_update")
            if change == "wrong-trigger":
                conn.execute(
                    "CREATE TRIGGER capture_queue_update AFTER UPDATE ON queue BEGIN SELECT 1; END"
                )
        else:
            conn.execute("DROP TABLE research_file_intents")
    before = bound.journal.path.read_bytes()
    count = len(bound.journal.pending())
    with store.connect() as conn:
        with pytest.raises(ValueError, match="Legacy workflow migration required"):
            record_pack(
                conn, "local-paper", STAMP, "manual", b"# New pack", legacy_day="2026-10-30"
            )
        assert conn.execute("SELECT COUNT(*) FROM reading_log").fetchone()[0] == 0
    assert bound.journal.path.read_bytes() == before and len(bound.journal.pending()) == count


def test_explicit_repeat_install_does_not_bless_a_different_existing_capture_writer(bound):
    from paper_daily.sync_capture import install

    seed()
    with bound.journal.transaction() as conn:
        conn.execute("DROP TRIGGER capture_queue_update")
        conn.execute(
            "CREATE TRIGGER capture_queue_update AFTER UPDATE ON queue BEGIN SELECT 1; END"
        )
    before = bound.journal.path.read_bytes()
    with (
        pytest.raises(ValueError, match="Legacy workflow migration required"),
        store.connect() as conn,
    ):
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="a")
    assert bound.journal.path.read_bytes() == before
