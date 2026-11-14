"""Real enrollment preserves Lineage science/history with fresh native source authority."""

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_lineage_jobs import work
from test_lineage_lifecycle import active as active
from test_research_lineage import corpus as make_corpus

from paper_daily import lineage_bound_originals, lineage_projection, lineage_sets, sync_recovery
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import observe_owner
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import research_projection_writer, research_writer
from paper_daily.workspace_enrollment import EnrollmentService


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    data = make_corpus.__wrapped__(root)
    from paper_daily import research_lineage, store

    with closing(sqlite3.connect(data[0])) as conn, conn:
        for identity, title in conn.execute("SELECT id,title FROM papers").fetchall():
            conn.execute(
                "UPDATE papers SET title_key=? WHERE id=?", (store.title_key(title), identity)
            )
    return (
        data[0],
        data[1],
        research_lineage.capture(data[0], "focal", ["prior", "later"], legacy_root=data[1]),
    )


def selection(corpus):
    return {paper: corpus[1] / (paper + ".pdf") for paper in ("focal", "prior", "later")}


def test_actual_lineage_enrollment_preserves_content_originals_and_history_without_ai(
    active, corpus, tmp_path
):
    owner, saved = active
    source = owner.database.read_bytes()
    service = EnrollmentService(owner.database)
    plan = work(service.plan, pdfs=selection(corpus))
    assert plan["supported"], plan["blockers"]
    assert owner.database.read_bytes() == source
    result = work(
        service.prepare,
        tmp_path / "candidate",
        backup_output=tmp_path / "backup.zip",
        request_id=str(uuid4()),
        pdfs=selection(corpus),
    )
    assert result["status"] == "prepared_for_review" and not result["uploaded"]
    database = Path(result["database"])
    assert lineage_sets.saved(database, owner.paper_id) == [saved]
    assert owner.database.read_bytes() == source
    client = SyncClient(
        Journal(database, workspace_id=result["workspace_id"], device_id=result["device_id"]),
        research_writer,
        projection_writer=research_projection_writer,
    )
    operations = client.journal.pending()
    scientific = [
        op for op in operations if op.get("content_address", {}).get("feature") == "lineage"
    ]
    assert len(scientific) == 1 and len(scientific[0]["source_dependencies"]) == 3
    assert (
        len(
            [
                op
                for op in operations
                if op["entity_type"] == "research_file"
                and op["payload"].get("feature") == "original_source"
            ]
        )
        == 3
    )
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT count(*) FROM " + lineage_projection.HISTORY).fetchone()[0] == 1
        protocols = {r[0] for r in conn.execute("SELECT protocol FROM research_history_archive")}
        assert {"research_lineage_publications", "research_generation_requests"} <= protocols
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_lineage_publications'"
        ).fetchone()
    loaded = observe_owner(database, owner.paper_id, expected_native=generation._identity(database))
    for selected in lineage_sets.decode(saved["body_json"])["report"]["sources"]:
        proof = work(lineage_bound_originals.prepare, loaded, saved, selected["id"])
        assert lineage_bound_originals.for_delivery(proof, loaded, saved, selected["id"])
    manifest = sync_recovery.inspect(tmp_path / "backup.zip")
    assert manifest["workspace_id"] == result["workspace_id"]


def test_removed_history_enrolls_as_readable_archive_without_scientific_or_source_grants(
    active, corpus, tmp_path
):
    from paper_daily import lineage_lifecycle, lineage_versions

    owner, row = active
    work(lineage_lifecycle.change, owner, row, request_id=str(uuid4()), action="retire")
    before = owner.database.read_bytes()
    result = work(
        EnrollmentService(owner.database).prepare,
        tmp_path / "removed-copy",
        backup_output=tmp_path / "removed-backup.zip",
        request_id=str(uuid4()),
        pdfs=selection(corpus),
    )
    database = Path(result["database"])
    assert lineage_sets.saved(database, owner.paper_id) == []
    client = SyncClient(
        Journal(database, workspace_id=result["workspace_id"], device_id=result["device_id"]),
        research_writer,
        projection_writer=research_projection_writer,
    )
    operations = client.journal.pending()
    assert not any(op.get("content_address", {}).get("feature") == "lineage" for op in operations)
    assert not any(
        op["entity_type"] == "research_file" and op["payload"].get("feature") == "original_source"
        for op in operations
    )
    loaded = observe_owner(database, owner.paper_id, expected_native=generation._identity(database))
    versions = work(lineage_versions.collect, loaded)
    assert versions["items"] == [dict(row=row, origin=None, current=False, occupied=False)]
    assert (
        sync_recovery.inspect(tmp_path / "removed-backup.zip")["workspace_id"]
        == result["workspace_id"]
    )
    assert owner.database.read_bytes() == before


def test_native_lineage_baseline_exact_retry_does_not_duplicate_scientific_events(
    active, corpus, tmp_path, monkeypatch
):
    from paper_daily import lineage_enrollment

    owner, row = active
    original = lineage_enrollment.publish_in
    results = []

    def twice(conn, client, rows, **kwargs):
        first = original(conn, client, rows, **kwargs)
        count = conn.execute("SELECT count(*) FROM paperfact_sync_operations").fetchone()[0]
        assert original(conn, client, rows, **kwargs) == first
        assert conn.execute("SELECT count(*) FROM paperfact_sync_operations").fetchone()[0] == count
        results.append(first)
        return first

    monkeypatch.setattr(lineage_enrollment, "publish_in", twice)
    result = work(
        EnrollmentService(owner.database).prepare,
        tmp_path / "retry-copy",
        backup_output=tmp_path / "retry-backup.zip",
        request_id=str(uuid4()),
        pdfs=selection(corpus),
    )
    assert len(results) == 1 and results[0]["lineage_reports"] == 1
    assert lineage_sets.saved(result["database"], owner.paper_id) == [row]


def test_late_scientific_failure_keeps_copied_row_and_caller_work_and_publishes_nothing(
    active, corpus, tmp_path, monkeypatch
):
    from paper_daily import lineage_enrollment

    owner, row = active
    before = owner.database.read_bytes()
    original = lineage_enrollment.publish_in
    verified = []

    def fail(conn, client, rows, **kwargs):
        conn.execute("INSERT INTO kv VALUES('fixture-earlier-work','keep')")
        pending = conn.execute("SELECT count(*) FROM paperfact_sync_operations").fetchone()[0]
        writer = client.writer

        def late(c, operation):
            writer(c, operation)
            if operation.get("content_address", {}).get("feature") == "lineage":
                raise ValueError("fixture late science failure")

        client.writer = late
        with pytest.raises(ValueError, match="late science failure"):
            original(conn, client, rows, **kwargs)
        assert (
            conn.execute("SELECT value FROM kv WHERE key='fixture-earlier-work'").fetchone()[0]
            == "keep"
        )
        assert (
            conn.execute("SELECT count(*) FROM paperfact_sync_operations").fetchone()[0] == pending
        )
        assert conn.execute("SELECT count(*) FROM research_lineage_sync_history").fetchone()[0] == 0
        assert (
            lineage_sets.validate_row(
                dict(conn.execute("SELECT * FROM paper_lineage_sets").fetchone())
            )
            == row
        )
        verified.append(True)
        raise ValueError("fixture enrollment aborted")

    monkeypatch.setattr(lineage_enrollment, "publish_in", fail)
    with pytest.raises(ValueError, match="enrollment aborted"):
        work(
            EnrollmentService(owner.database).prepare,
            tmp_path / "failed-copy",
            backup_output=tmp_path / "failed-backup.zip",
            request_id=str(uuid4()),
            pdfs=selection(corpus),
        )
    assert verified == [True]
    assert not (tmp_path / "failed-copy").exists() and not (tmp_path / "failed-backup.zip").exists()
    assert owner.database.read_bytes() == before


def test_cancel_after_staging_creates_no_candidate_or_backup_and_preserves_source(
    active, corpus, tmp_path
):
    from paper_daily.workspace_service import Cancelled, Ticket

    owner, _row = active
    before = owner.database.read_bytes()
    ticket = Ticket()

    def progress(message):
        if message == "Creating and inspecting independent recovery backup":
            ticket.cancel()

    with pytest.raises(Cancelled):
        work(
            EnrollmentService(owner.database).prepare,
            tmp_path / "cancelled-copy",
            backup_output=tmp_path / "cancelled-backup.zip",
            request_id=str(uuid4()),
            pdfs=selection(corpus),
            ticket=ticket,
            progress=progress,
        )
    assert (
        not (tmp_path / "cancelled-copy").exists()
        and not (tmp_path / "cancelled-backup.zip").exists()
    )
    assert owner.database.read_bytes() == before


def test_multiple_corpora_enroll_with_shared_exact_originals_and_distinct_science(
    active, corpus, tmp_path, monkeypatch
):
    from test_lineage_recovery import published

    from paper_daily import llm

    owner, _first = active
    published(corpus, monkeypatch)
    expected = lineage_sets.saved(owner.database, owner.paper_id)
    assert len(expected) == 2
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No enrollment AI"))
    result = work(
        EnrollmentService(owner.database).prepare,
        tmp_path / "multiple-copy",
        backup_output=tmp_path / "multiple-backup.zip",
        request_id=str(uuid4()),
        pdfs=selection(corpus),
    )
    assert lineage_sets.saved(result["database"], owner.paper_id) == expected
    client = SyncClient(
        Journal(
            result["database"], workspace_id=result["workspace_id"], device_id=result["device_id"]
        ),
        research_writer,
        projection_writer=research_projection_writer,
    )
    scientific = [
        op
        for op in client.journal.pending()
        if op.get("content_address", {}).get("feature") == "lineage"
    ]
    assert len(scientific) == 2 and scientific[0]["entity_id"] != scientific[1]["entity_id"]
    assert scientific[0]["source_dependencies"] == scientific[1]["source_dependencies"]
