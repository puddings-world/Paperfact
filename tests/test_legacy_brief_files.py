"""Exact Markdown closure bound to a current reading-event incarnation."""

import hashlib
import json

import pytest
from test_sync_capture import bound as bound_fixture
from test_sync_capture import seed

from paper_daily import legacy_workflow, store
from paper_daily.sync_artifacts import activate, materialize, paths
from paper_daily.sync_capture import suppress_capture

bound = bound_fixture
STAMP = "2026-10-30T12:34:56.123456+08:00"
DATA = b"# Exact brief\r\n\r\n<script>never execute</script>\r\n"


def captured(bound, tmp_path):
    with store.connect() as conn:
        exists = conn.execute("SELECT 1 FROM papers LIMIT 1").fetchone()
    if not exists:
        seed()
    root = tmp_path / "briefs"
    source = root / "2026-10-30" / "pack.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(DATA)
    prepared = legacy_workflow.read_brief(source, trusted_root=root)
    with store.connect() as conn:
        conn._legacy_brief_inputs = {27: prepared}
        conn.execute(
            "INSERT INTO reading_log VALUES(27,?,?,?,?,?)",
            ("local-paper", STAMP, str(source), "manual", "Exact note"),
        )
    event = next(
        op
        for op in bound.journal.pending()
        if op.get("payload", {}).get("feature") == "reading_event"
    )
    file = next(
        op
        for op in bound.journal.pending()
        if op.get("payload", {}).get("feature") == "legacy_brief"
    )
    return source, event, file


def installed(file):
    with store.connect() as conn:
        blob_store, root = paths(conn)
    return materialize(blob_store, root, file)


def test_actual_capture_materialize_binds_exact_owned_markdown(bound, tmp_path):
    source, event, file = captured(bound, tmp_path)
    assert event["payload"]["data"]["brief"] == {
        "sha256": hashlib.sha256(DATA).hexdigest(),
        "size": len(DATA),
        "media_type": "text/markdown",
    }
    result = installed(file)
    assert (
        json.loads((result.path / "brief.json").read_bytes())["event_incarnation"]
        == event["incarnation"]
    )
    with store.connect() as conn, suppress_capture(conn):
        conn.execute("BEGIN IMMEDIATE")
        assert activate(conn, file, result)
    with store.connect() as conn:
        path = conn.execute("SELECT brief_path FROM reading_log WHERE id=27").fetchone()[0]
        assert path != str(source)
        assert (result.path / "2026-10-30-brief.md").read_bytes() == DATA
        assert path == str(result.path / "2026-10-30-brief.md")
    count = len(bound.journal.pending())
    with store.connect() as conn, suppress_capture(conn):
        conn.execute("BEGIN IMMEDIATE")
        assert activate(conn, file, result)
    assert len(bound.journal.pending()) == count
    assert source.read_bytes() == DATA


@pytest.mark.parametrize("change", ["delete", "clear"])
def test_late_materialization_cannot_attach_to_deleted_or_cleared_event(bound, tmp_path, change):
    _source, _event, file = captured(bound, tmp_path)
    result = installed(file)
    if change == "clear":
        with store.connect() as conn, suppress_capture(conn):
            conn.execute("BEGIN IMMEDIATE")
            assert activate(conn, file, result)
    with store.connect() as conn:
        conn.execute(
            "DELETE FROM reading_log WHERE id=27"
            if change == "delete"
            else "UPDATE reading_log SET brief_path=NULL WHERE id=27"
        )
    with store.connect() as conn, suppress_capture(conn):
        conn.execute("BEGIN IMMEDIATE")
        assert activate(conn, file, result) is False
        assert (
            conn.execute("SELECT COUNT(*) FROM research_file_desired WHERE active=1").fetchone()[0]
            == 0
        )
        row = conn.execute("SELECT brief_path FROM reading_log WHERE id=27").fetchone()
        assert row is None if change == "delete" else row[0] is None


def test_pending_descriptor_survives_metadata_edit_without_bytes(bound, tmp_path):
    _source, event, _file = captured(bound, tmp_path)
    with store.connect() as conn, suppress_capture(conn):
        conn.execute("UPDATE reading_log SET brief_path=NULL WHERE id=27")
    with store.connect() as conn:
        conn.execute("UPDATE reading_log SET note='Edited before download' WHERE id=27")
    latest = [
        op
        for op in bound.journal.pending()
        if op.get("payload", {}).get("feature") == "reading_event"
    ][-1]
    assert latest["payload"]["data"]["brief"] == event["payload"]["data"]["brief"]
    assert latest["payload"]["data"]["note"] == "Edited before download"


def test_file_stage_failure_rolls_back_row_and_journal_then_retry(bound, tmp_path, monkeypatch):
    from paper_daily import sync_artifacts

    real = sync_artifacts.stage_bytes
    before = len(bound.journal.pending())
    monkeypatch.setattr(
        sync_artifacts, "stage_bytes", lambda *_: (_ for _ in ()).throw(OSError("fixture storage"))
    )
    with pytest.raises(OSError, match="fixture storage"):
        captured(bound, tmp_path)
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reading_log").fetchone()[0] == 0
    # Seed independently committed, but neither event nor file intent survived.
    assert all(
        op.get("payload", {}).get("feature") not in {"reading_event", "legacy_brief"}
        for op in bound.journal.pending()[before:]
    )
    monkeypatch.setattr(sync_artifacts, "stage_bytes", real)
    captured(bound, tmp_path)
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reading_log").fetchone()[0] == 1


def test_generated_pack_is_immutable_owned_and_rollback_does_not_deliver(bound, tmp_path):
    from paper_daily.legacy_briefs import record_pack

    seed()
    with store.connect() as conn:
        first = record_pack(conn, "local-paper", STAMP, "manual", DATA, legacy_day="2026-10-30")
    assert first.read_bytes() == DATA
    count = len(bound.journal.pending())
    with pytest.raises(RuntimeError, match="rollback"), store.connect() as conn:
        second = record_pack(
            conn,
            "local-paper",
            "2026-10-30T13:00:00+08:00",
            "manual",
            b"# Second pack",
            legacy_day="2026-10-30",
        )
        assert second != first
        raise RuntimeError("rollback")
    assert first.read_bytes() == DATA
    assert len(bound.journal.pending()) == count
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reading_log").fetchone()[0] == 1
        retry = record_pack(
            conn,
            "local-paper",
            "2026-10-30T13:00:00+08:00",
            "manual",
            b"# Second pack",
            legacy_day="2026-10-30",
        )
    assert retry.read_bytes() == b"# Second pack"
    assert retry != first and first.read_bytes() == DATA


def test_caught_generated_binding_failure_cannot_commit_partial_event(bound, monkeypatch):
    from paper_daily import sync_artifacts
    from paper_daily.legacy_briefs import record_pack
    from paper_daily.sync_capture import CaptureError

    seed()
    before = len(bound.journal.pending())

    def fail(*_args):
        raise OSError("fixture install failure")

    monkeypatch.setattr(sync_artifacts, "materialize", fail)
    with pytest.raises(CaptureError, match="failed"), store.connect() as conn:
        with pytest.raises(OSError, match="fixture install failure"):
            record_pack(conn, "local-paper", STAMP, "manual", DATA, legacy_day="2026-10-30")
        assert conn.execute("SELECT COUNT(*) FROM reading_log").fetchone()[0] == 0
    assert len(bound.journal.pending()) == before
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reading_log").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM research_legacy_brief_targets").fetchone()[0] == 0


def test_actual_daily_delivery_keeps_behavior_and_uses_owned_file_only_when_enrolled(
    bound, tmp_path, monkeypatch
):
    from paper_daily import brief

    seed()
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO queue(paper_id,rank,role,queued_at) VALUES('local-paper',1,'manual',?)",
            (STAMP,),
        )
    monkeypatch.setattr(brief, "BRIEF_DIR", tmp_path / "legacy-briefs")
    monkeypatch.setattr(brief, "ensure_dirs", lambda: None)
    monkeypatch.setattr(brief, "pack_text", lambda *_: ("# Exact prepared pack", None))
    with store.connect() as conn:
        row, path = brief.deliver_next(conn)
        assert row["id"] == "local-paper"
        assert path.read_bytes() == b"# Exact prepared pack"
        assert brief.deliver_next(conn) is None
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reading_log").fetchone()[0] == 1
        state = conn.execute("SELECT state,delivered_at FROM queue").fetchone()
        assert state[0] == "delivered" and state[1]
    assert "research-versions" in str(path) and not list(
        (tmp_path / "legacy-briefs").rglob("*-pack.md")
    )


def test_unbound_daily_pack_still_writes_original_local_file(tmp_path, monkeypatch):
    import sqlite3
    from contextlib import closing

    from paper_daily import brief

    monkeypatch.setattr(brief, "BRIEF_DIR", tmp_path / "briefs")
    monkeypatch.setattr(brief, "ensure_dirs", lambda: None)
    monkeypatch.setattr(brief, "pack_text", lambda *_: ("# Original local pack", None))
    with closing(sqlite3.connect(tmp_path / "unbound.db")) as conn, conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('paper','Paper','paper','Fixture',2026,'fixture')"
        )
        conn.execute(
            "INSERT INTO queue(paper_id,rank,role,queued_at) VALUES('paper',1,'manual',?)", (STAMP,)
        )
        row, path = brief.deliver_next(conn)
        assert row["id"] == "paper" and path.name == "paper-pack.md"
        assert path.read_text(encoding="utf-8") == "# Original local pack"
        assert conn.execute("SELECT brief_path FROM reading_log").fetchone()[0] == str(path)
        assert brief.deliver_next(conn) is None
