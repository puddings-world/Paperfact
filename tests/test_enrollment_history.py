"""Real generated research can enroll with private history and fresh authority."""

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from test_claim_jobs import (
    claims as claims_fixture,
)
from test_claim_jobs import (
    job,
)
from test_claim_jobs import (
    ready as ready_fixture,
)
from test_claim_jobs import (
    workspace as workspace_fixture,
)

from paper_daily import enrollment_history
from paper_daily import research_generation as generation
from paper_daily.workspace_enrollment import EnrollmentService

claims = claims_fixture
ready = ready_fixture
workspace = workspace_fixture


def test_real_claim_generation_history_archives_before_first_enrollment(claims, tmp_path):
    assert job(claims).run().status == "accepted"
    db = claims[0][0]
    service = EnrollmentService(db)
    plan = service.plan(pdfs={"paper": claims[0][2].path})
    if claims[0][1] is not None:
        assert not plan["supported"]  # Already-enrolled protocol is a different migration.
        return
    assert plan["supported"], plan["blockers"]
    assert plan["archived_history_by_protocol"]["research_generation_requests"] == 1
    assert plan["archived_history_records"] >= 2
    with closing(sqlite3.connect(db)) as conn:
        original = conn.execute(
            "SELECT token FROM research_parent_lifecycle WHERE entity_id='paper'"
        ).fetchone()[0]
    token = str(uuid4())
    result = service.prepare(
        tmp_path.parent / ("candidate-" + token),
        backup_output=tmp_path.parent / (token + ".zip"),
        request_id=token,
        pdfs={"paper": claims[0][2].path},
    )
    destination = Path(result["database"])
    with closing(sqlite3.connect(destination)) as conn:
        fresh = conn.execute(
            "SELECT token FROM research_parent_lifecycle WHERE entity_id='paper'"
        ).fetchone()[0]
        assert fresh != original
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='research_generation_requests'"
        ).fetchall()
        records = enrollment_history.archived(conn)
        assert any(row["protocol"] == "research_generation_requests" for row in records)
        wire = "\n".join(
            row[0] for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        )
        assert str(db) not in wire and "database_identity" not in wire and original not in wire


def test_semantic_json_comparison_preserves_numeric_types_order_unicode_and_prose():
    import pytest

    compare = enrollment_history.canonical_research_rows
    assert compare([{"body_json": '{"b":2, "a":["x"]}', "body": "exact prose"}]) == compare(
        [{"body_json": '{ "a" : ["x"],"b":2 }', "body": "exact prose"}]
    )
    for left, right in [
        ("true", "1"),
        ("1", "1.0"),
        ("[1,2]", "[2,1]"),
        ('"a"', '" a"'),
        ('"\\u00e9"', '"e\\u0301"'),
    ]:
        assert compare([{"body_json": left}]) != compare([{"body_json": right}])
    assert compare([{"body_json": "{}", "body": "text"}]) != compare(
        [{"body_json": "{}", "body": "text "}]
    )
    for invalid in ('{"x":1,"x":2}', "NaN", "Infinity", "{broken}"):
        with pytest.raises(ValueError):
            compare([{"body_json": invalid}])


def test_idle_WAL_checkpoint_is_not_a_source_change_but_SQL_mutation_is(claims, tmp_path):
    import pytest

    from paper_daily.workspace_service import SnapshotChanged

    assert job(claims).run().status == "accepted"
    if claims[0][1] is not None:
        return
    db = claims[0][0]
    service = EnrollmentService(db)

    def checkpoint(_message):
        with closing(sqlite3.connect(db)) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    token = str(uuid4())
    result = service.prepare(
        tmp_path.parent / ("checkpoint-" + token),
        backup_output=tmp_path.parent / (token + ".zip"),
        request_id=token,
        pdfs={"paper": claims[0][2].path},
        progress=checkpoint,
    )
    assert result["status"] == "prepared_for_review"
    changed = False

    def mutate(message):
        nonlocal changed
        if message.startswith("Creating") and not changed:
            changed = True
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.execute(
                    "UPDATE research_generation_requests SET reason='new private observation'"
                )

    token = str(uuid4())
    output = tmp_path.parent / ("changed-" + token)
    backup = tmp_path.parent / (token + ".zip")
    with pytest.raises(SnapshotChanged):
        service.prepare(
            output,
            backup_output=backup,
            request_id=token,
            pdfs={"paper": claims[0][2].path},
            progress=mutate,
        )
    assert changed and not output.exists() and not backup.exists()


def test_active_and_unknown_job_locks_do_not_hide_research_content(claims, tmp_path):
    import pytest

    from paper_daily.research_job_lock import claim

    assert job(claims).run().status == "accepted"
    if claims[0][1] is not None:
        return
    db = claims[0][0]
    service = EnrollmentService(db)
    with claim(db, "claims", "paper") as owned:
        assert owned
        with pytest.raises(ValueError, match="active research"):
            service.plan(pdfs={"paper": claims[0][2].path})
    assert service.plan(pdfs={"paper": claims[0][2].path})["supported"]
    (db.parent / ".research-jobs" / "unknown.json").write_text("not disposable")
    with pytest.raises(ValueError, match="Unknown local research job lock"):
        service.plan(pdfs={"paper": claims[0][2].path})


def test_history_archive_is_lazy_validates_batch_before_schema_and_obeys_rollback(claims):
    import pytest

    assert job(claims).run().status == "accepted"
    with closing(generation._connect(claims[0][0])) as source:
        row = dict(source.execute("SELECT * FROM research_generation_requests").fetchone())
    record = enrollment_history.wrap("research_generation_requests", row)
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("BEGIN")
        enrollment_history.retain_in(conn, [])
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []
        with pytest.raises(ValueError):
            enrollment_history.retain_in(conn, [record, {"record_id": "bad"}])
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []
        enrollment_history.retain_in(conn, [record])
        assert enrollment_history.archived(conn) == [record]
        conn.rollback()
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []
