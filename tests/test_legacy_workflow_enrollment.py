"""Lossless migration and repeat detached adoption of queue/log/Markdown."""

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_workspace_enrollment import source as source_fixture

from paper_daily import sync_recovery
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.workspace_enrollment import EnrollmentService
from paper_daily.workspace_service import Cancelled, Ticket

source = source_fixture
STAMP = "2026-10-30T12:34:56.123456+08:00"
DATA = b"# Exact original brief\r\n\r\n<script>only text</script>\r\n"


def populate(source):
    path = source.parent / "briefs" / "2026-10-30" / "paper-pack.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(DATA)
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('orphan','Orphan','orphan','Fixture',2026,'fixture')"
        )
        conn.execute(
            "INSERT INTO queue VALUES(?,-2.75,'deferred','manual',?,?,?,NULL,?)",
            ("orphan", "paper", "Original reason", STAMP, STAMP),
        )
        conn.execute(
            "INSERT INTO reading_log VALUES(27,?,?,?,?,?)",
            ("orphan", STAMP, str(path), "manual", "Original note"),
        )
        conn.execute("INSERT INTO reading_log VALUES(91,?,?,NULL,NULL,NULL)", ("paper", STAMP))
    return path


def assert_content(database):
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT * FROM queue").fetchall() == [
            ("orphan", -2.75, "deferred", "manual", "paper", "Original reason", STAMP, None, STAMP)
        ]
        rows = conn.execute("SELECT * FROM reading_log ORDER BY id").fetchall()
        assert rows[0][:3] == (27, "orphan", STAMP)
        assert rows[0][4:] == ("manual", "Original note")
        assert rows[1] == (91, "paper", STAMP, None, None, None)
        path = Path(rows[0][3])
        assert path.read_bytes() == DATA
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM list_papers").fetchone()[0] == 1
        return conn.execute(
            "SELECT sync_key FROM research_content_identity "
            "WHERE feature='reading_event' AND local_id=27"
        ).fetchone()[0]


def test_initial_copy_and_two_restore_adopt_cycles_are_lossless(source, tmp_path):
    original = populate(source)
    before = source.read_bytes()
    service = EnrollmentService(source)
    assert service.plan()["supported"]
    first = service.prepare(
        tmp_path / "first", backup_output=tmp_path / "first.zip", request_id=str(uuid4())
    )
    key = assert_content(first["database"])
    assert original.read_bytes() == DATA and source.read_bytes() == before
    package = Path(first["backup"])
    for index in range(2):
        detached = tmp_path / f"detached-{index}"
        sync_recovery.restore_detached(package, detached)
        recovery = RecoveryAdoptionService(detached / "papers.db")
        inspected = recovery.inspect()
        assert inspected.report["supported"] and inspected.report["orphan_papers"] == 1
        result = recovery.prepare(
            inspected,
            tmp_path / f"copy-{index}",
            backup_output=tmp_path / f"copy-{index}.zip",
            request_id=str(uuid4()),
        )
        new_key = assert_content(result["database"])
        assert new_key != key  # fresh authority, original IDs/times/content are retained
        key, package = new_key, Path(result["backup"])
        with closing(sqlite3.connect(result["database"])) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM research_recovery_provenance").fetchone()[0] > 0
            )
        assert sync_recovery.inspect(package)["workspace_id"] == result["workspace_id"]


@pytest.mark.parametrize("relative", [False, True])
def test_unbound_recovery_retains_declared_brief_and_never_follows_sender_path(
    source, tmp_path, relative
):
    original = populate(source)
    if relative:
        with closing(sqlite3.connect(source)) as conn, conn:
            conn.execute(
                "UPDATE reading_log SET brief_path=? WHERE id=27",
                (original.relative_to(source.parent).as_posix(),),
            )
    package = tmp_path / "raw.zip"
    sync_recovery.create(source, package)
    detached = tmp_path / "restored"
    sync_recovery.restore_detached(package, detached)
    original.unlink()  # archive must own bytes, not need the sender file
    service = RecoveryAdoptionService(detached / "papers.db")
    inspection = service.inspect()
    result = service.prepare(
        inspection,
        tmp_path / "editable",
        backup_output=tmp_path / "editable.zip",
        request_id=str(uuid4()),
    )
    assert_content(result["database"])


def test_missing_or_unknown_brief_scope_blocks_before_output(source, tmp_path):
    original = populate(source)
    original.unlink()
    assert not EnrollmentService(source).plan()["supported"]
    with pytest.raises(ValueError):
        sync_recovery.create(source, tmp_path / "bad.zip")
    assert not (tmp_path / "bad.zip").exists()


def test_cancel_before_legacy_migration_leaves_source_unchanged(source, tmp_path):
    original = populate(source)
    before = source.read_bytes()
    ticket = Ticket()
    ticket.cancel()
    with pytest.raises(Cancelled):
        EnrollmentService(source).prepare(
            tmp_path / "candidate",
            backup_output=tmp_path / "backup.zip",
            request_id=str(uuid4()),
            ticket=ticket,
        )
    assert source.read_bytes() == before and original.read_bytes() == DATA
    assert not (tmp_path / "candidate").exists()


@pytest.mark.parametrize(
    "change", ["invalid-state", "naive-time", "outside-brief", "naive-queue-pin"]
)
def test_unsupported_legacy_semantics_still_refuse_lossy_copy(source, tmp_path, change):
    original = populate(source)
    with closing(sqlite3.connect(source)) as conn, conn:
        if change == "invalid-state":
            conn.execute("UPDATE queue SET state='future-state'")
        elif change == "naive-time":
            conn.execute("UPDATE reading_log SET delivered_at='2026-10-30T12:34:56'")
        elif change == "outside-brief":
            outside = tmp_path / "foreign.md"
            outside.write_bytes(DATA)
            conn.execute("UPDATE reading_log SET brief_path=? WHERE id=27", (str(outside),))
        else:
            conn.execute("INSERT INTO pins VALUES('queue','orphan',?)", ("2026-10-30T12:34:56",))
    before = source.read_bytes()
    plan = EnrollmentService(source).plan()
    assert not plan["supported"]
    with pytest.raises(ValueError):
        EnrollmentService(source).prepare(
            tmp_path / "blocked", backup_output=tmp_path / "blocked.zip", request_id=str(uuid4())
        )
    assert source.read_bytes() == before and original.read_bytes() == DATA
    assert not (tmp_path / "blocked").exists() and not (tmp_path / "blocked.zip").exists()


def test_declared_relative_legacy_brief_has_exact_owned_replacement(source, tmp_path):
    populate(source)
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute(
            "UPDATE reading_log SET brief_path='briefs/2026-10-30/paper-pack.md' WHERE id=27"
        )
    result = EnrollmentService(source).prepare(
        tmp_path / "relative", backup_output=tmp_path / "relative.zip", request_id=str(uuid4())
    )
    assert_content(result["database"])


def test_brief_changed_after_coverage_never_publishes_partial_candidate(source, tmp_path):
    original = populate(source)

    def mutate(message):
        if message == "Coverage checked; staging an isolated research copy":
            original.write_bytes(b"# Later writer")

    with pytest.raises(ValueError):
        EnrollmentService(source).prepare(
            tmp_path / "stale",
            backup_output=tmp_path / "stale.zip",
            request_id=str(uuid4()),
            progress=mutate,
        )
    assert not (tmp_path / "stale").exists() and not (tmp_path / "stale.zip").exists()
    with closing(sqlite3.connect(source)) as conn:
        assert (
            conn.execute("SELECT note FROM reading_log WHERE id=27").fetchone()[0]
            == "Original note"
        )
