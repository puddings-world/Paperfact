"""Isolated first-enrollment candidates never rewrite the source or upload it."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest

from paper_daily import store, sync_recovery
from paper_daily.document_reader import DocumentReader
from paper_daily.workspace_enrollment import EnrollmentBlocked, EnrollmentService
from paper_daily.workspace_service import Cancelled, SnapshotChanged, Ticket
from paper_daily.workspace_sync import local_binding

STAMP = "2026-10-30T00:00:00+00:00"


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    database = root / "papers.db"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('paper','Research paper','researchpaper','Fixture',2026,'fixture')"
        )
        conn.execute("INSERT INTO lists VALUES('list','Reading route','Curated',?)", (STAMP,))
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('list','paper',0,?)",
            (STAMP,),
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) VALUES('paper','A research note',?)",
            (STAMP,),
        )
        conn.execute("INSERT INTO kv VALUES('ui.theme','dark')")
        conn.execute("INSERT INTO kv VALUES('auth.secret','must-not-leak-token')")
    (root / "credentials.json").write_text('{"secret":"must-not-leak-file"}')
    return database


def pdf(source):
    folder = source.parent / "pdf"
    folder.mkdir(exist_ok=True)
    path = folder / "paper.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((50, 50), "A verified source paper")
        document.save(path)
    return path


def prepare(source, tmp_path, **kwargs):
    return EnrollmentService(source).prepare(
        tmp_path / "candidate",
        backup_output=tmp_path / "backup.zip",
        request_id=str(uuid4()),
        **kwargs,
    )


def rows(database, sql):
    with closing(sqlite3.connect(database)) as conn, conn:
        return conn.execute(sql).fetchall()


def test_plan_has_no_side_effects_and_supports_paper_scoped_queue_pins(source, tmp_path):
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("INSERT INTO refs VALUES('paper','paper',0)")
        conn.execute("INSERT INTO pins VALUES('queue','paper',?)", (STAMP,))
    before = source.read_bytes()
    plan = EnrollmentService(source).plan()
    assert plan["supported"]
    assert "unsupported writer scope: refs" not in plan["blockers"]
    assert plan["research_counts"]["refs"] == 1
    assert plan["research_counts"]["pins"] == 1
    assert plan["blockers"] == []
    assert plan["excluded_private_kv"] == 2
    assert not plan["runtime_enrollment_complete"]
    assert source.read_bytes() == before
    assert not (tmp_path / "candidate").exists()
    assert not rows(source, "SELECT name FROM sqlite_master WHERE name='paperfact_sync_identity'")


def test_supported_copy_preserves_research_and_excludes_credentials(source, tmp_path):
    before = source.read_bytes()
    result = prepare(source, tmp_path)
    assert result["status"] == "prepared_for_review"
    assert not result["uploaded"] and not result["adopted"]
    assert not result["runtime_enrollment_complete"]
    destination = Path(result["database"])
    binding = local_binding(destination)
    assert binding["workspace_id"] == result["workspace_id"]
    assert rows(destination, "SELECT body FROM notes") == [("A research note",)]
    assert rows(destination, "SELECT name,note FROM lists") == [("Reading route", "Curated")]
    assert rows(destination, "SELECT id FROM papers") == [("paper",)]
    assert not rows(destination, "SELECT value FROM kv WHERE key IN ('auth.secret','ui.theme')")
    assert source.read_bytes() == before
    assert not rows(source, "SELECT name FROM sqlite_master WHERE name='paperfact_sync_identity'")
    assert not (tmp_path / "candidate" / "credentials.json").exists()
    assert sync_recovery.inspect(result["backup"])["workspace_id"] == result["workspace_id"]
    with zipfile.ZipFile(result["backup"]) as archive:
        body = b"\n".join(archive.read(name) for name in archive.namelist())
    assert b"must-not-leak" not in body
    assert b"auth.secret" not in body
    restored = sync_recovery.restore_detached(result["backup"], tmp_path / "restored")
    assert restored["detached"]
    assert rows(tmp_path / "restored/papers.db", "SELECT body FROM notes") == [("A research note",)]


def test_explicit_pdf_is_verified_bound_and_in_independent_backup(source, tmp_path):
    original = pdf(source)
    data = original.read_bytes()
    result = prepare(source, tmp_path, pdfs={"paper": original})
    target = rows(result["database"], "SELECT target FROM research_document_applied")[0][0]
    assert json.loads(target)["sha256"] == hashlib.sha256(data).hexdigest()
    with zipfile.ZipFile(result["backup"]) as archive:
        assert archive.read("objects/" + hashlib.sha256(data).hexdigest()) == data
    reader = DocumentReader.from_workspace(result["database"])
    resolved = reader.resolve("paper")
    assert resolved.available
    assert resolved.path.read_bytes() == data
    assert str(tmp_path / "candidate") in str(resolved.path)
    assert not list((tmp_path / "candidate").glob("**/*enrollment*"))


@pytest.mark.parametrize(
    "kind",
    [
        "unmapped-pdf",
        "deck",
        "derived-json",
        "unknown-table",
        "unknown-kv",
        "already-bound",
        "queue",
        "reading-log",
    ],
)
def test_incomplete_coverage_blocks_without_outputs(source, tmp_path, kind):
    if kind == "unmapped-pdf":
        pdf(source)
    elif kind in {"deck", "derived-json"}:
        folder = source.parent / ("presentations" if kind == "deck" else "reading-links")
        folder.mkdir()
        (folder / "paper.json").write_text("{}")
    else:
        with closing(sqlite3.connect(source)) as conn, conn:
            if kind == "unknown-table":
                conn.execute("CREATE TABLE hidden_research(value TEXT)")
                conn.execute("INSERT INTO hidden_research VALUES('must preserve')")
            elif kind == "already-bound":
                conn.execute("CREATE TABLE paperfact_sync_identity(id,workspace,device)")
            elif kind == "unknown-kv":
                conn.execute("INSERT INTO kv VALUES('my.research','must preserve')")
            elif kind == "queue":
                conn.execute("INSERT INTO queue(paper_id,rank) VALUES('paper',1)")
            else:
                conn.execute(
                    "INSERT INTO reading_log(paper_id,delivered_at) VALUES('paper',?)", (STAMP,)
                )
    if kind in {"queue", "reading-log"}:
        # Typed legacy workflow is now supported; all other incomplete scopes
        # retain their original fail-closed assertions below.
        table = "queue" if kind == "queue" else "reading_log"
        expected = rows(source, "SELECT * FROM " + table)
        original = source.read_bytes()
        result = prepare(source, tmp_path)
        assert result["supported"]
        assert rows(result["database"], "SELECT * FROM " + table) == expected
        feature = "queue_entry" if kind == "queue" else "reading_event"
        assert rows(
            result["database"],
            "SELECT COUNT(*) FROM research_content_projection WHERE feature='" + feature + "'",
        ) == [(1,)]
        assert source.read_bytes() == original
        return
    with pytest.raises(EnrollmentBlocked) as error:
        prepare(source, tmp_path)
    assert not error.value.plan["supported"]
    assert not (tmp_path / "candidate").exists()
    assert not (tmp_path / "backup.zip").exists()
    assert not list(tmp_path.glob(".paperfact-enrollment-*"))


@pytest.mark.parametrize(
    "path_kind", ["same-root", "exists", "backup-exists", "backup-inside-output"]
)
def test_explicit_paths_never_replace_source_or_existing_outputs(source, tmp_path, path_kind):
    output, backup = tmp_path / "candidate", tmp_path / "backup.zip"
    if path_kind == "same-root":
        output = source.parent
    elif path_kind == "exists":
        output.mkdir()
        (output / "keep").write_text("existing")
    elif path_kind == "backup-exists":
        backup.write_text("existing backup")
    else:
        backup = output / "backup.zip"
    with pytest.raises(ValueError):
        EnrollmentService(source).prepare(output, backup_output=backup, request_id=str(uuid4()))
    assert rows(source, "SELECT body FROM notes") == [("A research note",)]
    if path_kind == "exists":
        assert (output / "keep").read_text() == "existing"
    if path_kind == "backup-exists":
        assert backup.read_text() == "existing backup"


def test_cancellation_after_staging_leaves_original_and_no_outputs(source, tmp_path):
    ticket = Ticket()

    def progress(message):
        if message.startswith("Creating"):
            ticket.cancel()

    with pytest.raises(Cancelled):
        prepare(source, tmp_path, ticket=ticket, progress=progress)
    assert not (tmp_path / "candidate").exists()
    assert not (tmp_path / "backup.zip").exists()
    assert not list(tmp_path.glob(".paperfact-enrollment-*"))
    assert rows(source, "SELECT body FROM notes") == [("A research note",)]


@pytest.mark.parametrize("change", ["database", "pdf", "replace-source"])
def test_source_changes_during_staging_cannot_publish_old_baseline(source, tmp_path, change):
    original = pdf(source)
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    changed = False

    def progress(message):
        nonlocal changed
        if changed or not message.startswith("Verifying"):
            return
        changed = True
        if change == "database":
            with closing(sqlite3.connect(source)) as conn, conn:
                conn.execute("UPDATE notes SET body='Newer note'")
        elif change == "pdf":
            original.write_bytes(original.read_bytes() + b"changed")
        else:
            replacement = source.with_suffix(".replacement")
            with (
                closing(sqlite3.connect(source)) as incoming,
                closing(sqlite3.connect(replacement)) as out,
            ):
                incoming.backup(out)
            source.unlink()
            replacement.rename(source)

    with pytest.raises((SnapshotChanged, sqlite3.Error)):
        prepare(source, tmp_path, pdfs={"paper": original}, progress=progress)
    assert not (tmp_path / "candidate").exists()
    assert not (tmp_path / "backup.zip").exists()


def test_duplicate_activation_is_rejected_and_retry_preserves_identity(source, tmp_path):
    service = EnrollmentService(source)
    request = str(uuid4())
    repeats, staged = [], []
    ticket = Ticket()

    def progress(message):
        if message.startswith("Coverage"):
            with pytest.raises(ValueError, match="already running"):
                service.prepare(
                    tmp_path / "other", backup_output=tmp_path / "other.zip", request_id=request
                )
            repeats.append(True)
        if message.startswith("Verified"):
            candidate = next(tmp_path.glob(".paperfact-enrollment-*/workspace/papers.db"))
            staged.append(
                (local_binding(candidate), rows(candidate, "SELECT * FROM research_paper_identity"))
            )
            ticket.cancel()

    with pytest.raises(Cancelled):
        service.prepare(
            tmp_path / "candidate",
            backup_output=tmp_path / "backup.zip",
            request_id=request,
            progress=progress,
            ticket=ticket,
        )
    assert repeats == [True]
    assert not (tmp_path / "candidate").exists()
    result = service.prepare(
        tmp_path / "candidate", backup_output=tmp_path / "backup.zip", request_id=request
    )
    assert local_binding(Path(result["database"])) == staged[0][0]
    assert rows(result["database"], "SELECT * FROM research_paper_identity") == staged[0][1]
    with pytest.raises(ValueError):
        service.prepare(
            tmp_path / "candidate", backup_output=tmp_path / "backup.zip", request_id=request
        )


def test_bad_pdf_rolls_back_and_can_retry(source, tmp_path):
    original = pdf(source)
    valid = original.read_bytes()
    original.write_bytes(b"%PDF-broken")
    with pytest.raises(ValueError):
        prepare(source, tmp_path, pdfs={"paper": original})
    assert not (tmp_path / "candidate").exists()
    assert not (tmp_path / "backup.zip").exists()
    original.write_bytes(valid)
    assert prepare(source, tmp_path, pdfs={"paper": original})["status"] == "prepared_for_review"


def test_archive_failure_keeps_source_and_rolls_back_outputs(source, tmp_path, monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("simulated full disk")

    monkeypatch.setattr(sync_recovery, "create", fail)
    with pytest.raises(OSError, match="full disk"):
        prepare(source, tmp_path)
    assert rows(source, "SELECT body FROM notes") == [("A research note",)]
    assert not (tmp_path / "candidate").exists()
    assert not (tmp_path / "backup.zip").exists()


def test_empty_workspace_is_a_valid_reviewable_candidate(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    database = root / "papers.db"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
    plan = EnrollmentService(database).plan()
    assert plan["supported"] and plan["pdf_count"] == 0
    result = prepare(database, tmp_path)
    assert rows(result["database"], "SELECT * FROM papers") == []
    assert not result["runtime_enrollment_complete"]


@pytest.mark.parametrize("kind", ["trigger", "view", "columns"])
def test_unsupported_schema_writer_is_visible_in_read_only_plan(source, kind):
    with closing(sqlite3.connect(source)) as conn, conn:
        if kind == "trigger":
            conn.execute("CREATE TRIGGER custom_writer AFTER INSERT ON notes BEGIN SELECT 1; END")
        elif kind == "view":
            conn.execute("CREATE VIEW custom_research AS SELECT * FROM notes")
        else:
            conn.execute("ALTER TABLE notes ADD COLUMN private_research TEXT")
    plan = EnrollmentService(source).plan()
    assert not plan["supported"]
    assert any(kind in blocker or "schema writer/view" in blocker for blocker in plan["blockers"])


@pytest.mark.parametrize("kind", ["rows", "bytes", "invalid-selection"])
def test_bounded_inventory_fails_before_outputs(source, tmp_path, monkeypatch, kind):
    from paper_daily import workspace_enrollment as module

    pdfs = None
    if kind == "rows":
        monkeypatch.setattr(module, "MAX_ROWS", 1)
    elif kind == "bytes":
        pdfs = {"paper": pdf(source)}
        monkeypatch.setattr(module, "MAX_BYTES", 1)
    else:
        pdfs = []
    with pytest.raises(ValueError):
        prepare(source, tmp_path, pdfs=pdfs)
    assert not (tmp_path / "candidate").exists()
    assert not (tmp_path / "backup.zip").exists()


@pytest.mark.parametrize("kind", ["directory", "backup", "publish-failure"])
def test_publication_races_preserve_foreign_paths_and_source(source, tmp_path, monkeypatch, kind):
    from paper_daily import workspace_enrollment as module

    def progress(message):
        if not message.startswith("Verified"):
            return
        if kind == "directory":
            (tmp_path / "candidate").mkdir()
            (tmp_path / "candidate" / "foreign").write_text("keep")
        elif kind == "backup":
            (tmp_path / "backup.zip").write_text("foreign backup")

    if kind == "publish-failure":

        def fail(*_args):
            raise OSError("simulated directory publication failure")

        monkeypatch.setattr(module, "publish_directory", fail)
    with pytest.raises(OSError):
        prepare(source, tmp_path, progress=progress)
    assert rows(source, "SELECT body FROM notes") == [("A research note",)]
    if kind == "directory":
        assert (tmp_path / "candidate" / "foreign").read_text() == "keep"
    else:
        assert not (tmp_path / "candidate").exists()
    if kind == "backup":
        assert (tmp_path / "backup.zip").read_text() == "foreign backup"
    else:
        assert not (tmp_path / "backup.zip").exists()


def test_deep_analysis_and_linked_highlight_keep_actual_source_closure(source, tmp_path):
    original = pdf(source)
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    anchor = json.dumps(
        {"p0": 0, "o0": 1, "p1": 0, "o1": 4, "document_hash": digest}, sort_keys=True
    )
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute(
            "INSERT INTO dives(paper_id,body,written_at,spec) "
            "VALUES('paper','Detailed argument',?,'fixture')",
            (STAMP,),
        )
        conn.execute(
            "INSERT INTO close_readings(paper_id,body,written_at,spec) "
            "VALUES('paper','Section evidence',?,'fixture')",
            (STAMP,),
        )
        conn.execute(
            "INSERT INTO pdf_highlights(paper_id,document_hash,anchor,quote,created_at) "
            "VALUES('paper',?,?,'Core result',?)",
            (digest, anchor, STAMP),
        )
    result = prepare(source, tmp_path, pdfs={"paper": original})
    assert rows(result["database"], "SELECT body FROM dives") == [("Detailed argument",)]
    assert rows(result["database"], "SELECT body FROM close_readings") == [("Section evidence",)]
    assert rows(result["database"], "SELECT document_hash,quote FROM pdf_highlights") == [
        (digest, "Core result")
    ]
    with zipfile.ZipFile(result["backup"]) as archive:
        assert archive.read("objects/" + digest) == original.read_bytes()


def test_missing_recovery_coverage_for_capturable_data_blocks_preflight(source, monkeypatch):
    registry = sync_recovery._registry()
    del registry["notes"]
    monkeypatch.setattr(sync_recovery, "_registry", lambda: registry)
    plan = EnrollmentService(source).plan()
    assert not plan["supported"]
    assert "missing recovery coverage: notes" in plan["blockers"]


def test_absent_optional_recovery_table_does_not_require_source_migration(source, monkeypatch):
    monkeypatch.setattr(
        store, "SCHEMA", store.SCHEMA + "CREATE TABLE optional_fixture(value TEXT);"
    )
    monkeypatch.setattr(
        sync_recovery, "OPTIONAL_RESEARCH_TABLES", {"optional_fixture"}, raising=False
    )
    assert EnrollmentService(source).plan()["supported"]
