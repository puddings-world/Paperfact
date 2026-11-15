"""Real generated research can enroll with private history and fresh authority."""

import json
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
from test_workspace_enrollment import pdf as enrollment_pdf
from test_workspace_enrollment import source as enrollment_source

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


# Reuse the existing first-copy fixture rather than create another test workspace system.

source = enrollment_source


def resource_check(source, monkeypatch, *, legacy_text=False):
    from paper_daily import resources

    if legacy_text:
        original = source.parent / "text/paper.txt"
        original.parent.mkdir()
        original.write_bytes(
            "Recorded research text.\r\nOriginal: \u7814\u7a76\r\n".encode("utf-8")
        )
        pdf_root = source.parent / "pdf"
    else:
        original = enrollment_pdf(source)
        pdf_root = original.parent
    monkeypatch.setattr(resources, "PDF_DIR", pdf_root)
    monkeypatch.setattr(resources, "TEXT_DIR", source.parent / "text")
    monkeypatch.setattr(
        resources,
        "_collect",
        lambda *_: {
            "fixture": dict(
                url="https://example.org/research",
                kind="code",
                own=True,
                source="pdf",
                context="The paper releases this code.",
                stars=None,
                license=None,
                pushed_at=None,
                note=None,
                alive=None,
            )
        },
    )
    with closing(generation._connect(source)) as conn:
        assert resources.find(conn, "paper") == 1
    return original


def test_resource_check_enrolls_live_rows_but_keeps_completion_history_private(
    source, monkeypatch, tmp_path
):
    from paper_daily import sync_recovery

    original = resource_check(source, monkeypatch)
    with closing(sqlite3.connect(source)) as conn:
        record = conn.execute("SELECT * FROM research_compound_requests").fetchone()
        live = conn.execute("SELECT * FROM resources").fetchall()
    before = source.read_bytes()
    service = EnrollmentService(source)
    plan = service.plan(pdfs={"paper": original})
    assert plan["supported"], plan["blockers"]
    assert plan["archived_history_by_protocol"]["research_compound_requests"] == 1
    result = service.prepare(
        tmp_path / "candidate",
        backup_output=tmp_path / "backup.zip",
        request_id=str(uuid4()),
        pdfs={"paper": original},
    )
    assert source.read_bytes() == before
    assert result["adopted"] is False and result["uploaded"] is False
    destination = Path(result["database"])
    with closing(sqlite3.connect(destination)) as conn:
        assert conn.execute("SELECT * FROM resources").fetchall() == live
        archived = [
            r
            for r in enrollment_history.archived(conn)
            if r["protocol"] == "research_compound_requests"
        ]
        assert len(archived) == 1
        assert (
            tuple(
                json.loads(archived[0]["body_json"])[key]
                for key in enrollment_history.FORMATS["research_compound_requests"].split()
            )
            == record
        )
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_compound_requests'"
        ).fetchall()
        assert not conn.execute("SELECT 1 FROM kv WHERE key='resources:paper'").fetchall()
        wire = "\n".join(
            row[0] for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        )
        assert str(source) not in wire and "database_identity" not in wire
        assert any(
            json.loads(row[0]).get("payload", {}).get("feature") == "resource"
            for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        )
    restored = tmp_path / "restored"
    sync_recovery.restore_detached(result["backup"], restored)
    with closing(sqlite3.connect(restored / "papers.db")) as conn:
        assert conn.execute("SELECT * FROM resources").fetchall() == live
        recovered = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_history_archive'"
            )
        ]
        assert [
            row for row in recovered if row["protocol"] == "research_compound_requests"
        ] == archived
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_compound_requests'"
        ).fetchall()
    assert (restored / "pdf/paper.pdf").read_bytes() == original.read_bytes()


def test_resource_hint_without_matching_history_and_unknown_nested_inputs_still_block(
    source, monkeypatch
):
    import pytest

    from paper_daily import store

    original = resource_check(source, monkeypatch)
    fields = enrollment_history.FORMATS["research_compound_requests"].split()
    with closing(sqlite3.connect(source)) as conn:
        saved = dict(zip(fields, conn.execute(
            "SELECT * FROM research_compound_requests"
        ).fetchone(), strict=True))
        columns = [row[1] for row in conn.execute("PRAGMA table_info(resources)")]
        resource = dict(zip(
            columns, conn.execute("SELECT * FROM resources").fetchone(), strict=True
        ))
    for mode in ("duplicate", "authors", "foreign-row", "model-input", "legacy-text"):
        bad = dict(saved)
        context = json.loads(saved["context_json"])
        if mode == "authors":
            context["paper"]["authors_json"] = '[{"unknown":"private"}]'
        elif mode == "foreign-row":
            context["rows"] = [{**resource, "paper_id": "another-paper"}]
        elif mode == "model-input":
            context["prompts"] = ["unexpected input"]
        elif mode == "legacy-text":
            context["document"] = None
            context["text_source"] = {"path": "/not-a-capability/source.txt", "sha256": "a" * 64}
        bad["context_json"] = json.dumps(context)
        if mode == "duplicate":
            bad["context_json"] = '{"phase":"resources",' + bad["context_json"][1:]
        with pytest.raises(ValueError):
            enrollment_history.resource_sources(bad)
    with closing(sqlite3.connect(source)) as conn, conn:
        store.set_kv(conn, "resources:paper", "notext")
    assert not EnrollmentService(source).plan(pdfs={"paper": original})["supported"]
    with closing(sqlite3.connect(source)) as conn, conn:
        store.set_kv(conn, "resources:paper", "text")
        row = conn.execute(
            "SELECT request_id,context_json FROM research_compound_requests"
        ).fetchone()
        context = json.loads(row[1])
        context["paper"]["unknown_private"] = "must-not-be-promoted"
        conn.execute(
            "UPDATE research_compound_requests SET context_json=? WHERE request_id=?",
            (json.dumps(context), row[0]),
        )
    before = source.read_bytes()
    with pytest.raises(ValueError, match="Unexpected or missing research-file fields") as failure:
        EnrollmentService(source).plan(pdfs={"paper": original})
    assert "must-not-be-promoted" not in str(failure.value)
    assert source.read_bytes() == before


def test_retained_text_input_survives_first_copy_and_detached_restore_without_pdf_grant(
    source, monkeypatch, tmp_path
):
    import hashlib

    import pytest

    from paper_daily import sync_recovery

    text_file = resource_check(source, monkeypatch, legacy_text=True)
    raw = text_file.read_bytes()
    with closing(sqlite3.connect(source)) as conn:
        conn.row_factory = sqlite3.Row
        request = dict(conn.execute("SELECT * FROM research_compound_requests").fetchone())
    before = source.read_bytes()
    # A raw legacy backup must not silently drop input bytes it does not retain.
    with pytest.raises(
        ValueError, match="Extracted compound input requires reviewed archived bytes"
    ):
        sync_recovery.create(source, tmp_path / "incomplete.zip")
    assert not (tmp_path / "incomplete.zip").exists()
    plan = EnrollmentService(source).plan()
    assert plan["supported"], plan["blockers"]
    assert plan["archived_history_by_protocol"][enrollment_history.COMPOUND_TEXT] == 1
    assert "Recorded research text" not in repr(plan)
    result = EnrollmentService(source).prepare(
        tmp_path / "candidate", backup_output=tmp_path / "complete.zip", request_id=str(uuid4())
    )
    with closing(sqlite3.connect(result["database"])) as conn:
        archived = [
            row
            for row in enrollment_history.archived(conn)
            if row["protocol"] == enrollment_history.COMPOUND_TEXT
        ]
        assert len(archived) == 1
        saved, sources = enrollment_history.validate(archived[0])
        assert saved["request"] == request
        assert saved["text"].encode("utf-8") == raw and sources == set()
        with pytest.raises(ValueError, match="bytes differ from the observation"):
            enrollment_history.wrap(enrollment_history.COMPOUND_TEXT,
                                    {**saved, "text": saved["text"] + "changed"})
        for invalid in ({**saved, "request": None}, {**saved, "protocol": []}):
            with pytest.raises(ValueError):
                enrollment_history.validate_record(enrollment_history.COMPOUND_TEXT, invalid)
        assert (
            json.loads(request["context_json"])["text_source"]["sha256"]
            == hashlib.sha256(raw).hexdigest()
        )
        assert conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 1
        assert not conn.execute("SELECT 1 FROM kv WHERE key='resources:paper'").fetchall()
        operations = [
            json.loads(row[0])
            for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        ]
        assert all(
            op["entity_type"] not in {"paper_document", "research_file"} for op in operations
        )
        assert all("Recorded research text" not in json.dumps(op) for op in operations)
    restored = tmp_path / "restored"
    sync_recovery.restore_detached(result["backup"], restored)
    with closing(sqlite3.connect(restored / "papers.db")) as conn:
        old = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_history_archive'"
            )
        ]
        assert [
            row for row in old if row["protocol"] == enrollment_history.COMPOUND_TEXT
        ] == archived
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_compound_requests'"
        ).fetchall()
    assert source.read_bytes() == before and text_file.read_bytes() == raw


def test_retained_text_refuses_observed_external_path_and_changed_bytes(
    source, monkeypatch, tmp_path
):
    import pytest

    text_file = resource_check(source, monkeypatch, legacy_text=True)
    with closing(sqlite3.connect(source)) as conn:
        request_id, original = conn.execute(
            "SELECT request_id,context_json FROM research_compound_requests"
        ).fetchone()
    outside = tmp_path / "private-observation.txt"
    outside.write_text("Not an authorized input", encoding="utf-8")
    context = json.loads(original)
    context["text_source"]["path"] = str(outside)
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute(
            "UPDATE research_compound_requests SET context_json=? WHERE request_id=?",
            (json.dumps(context), request_id),
        )
    before = source.read_bytes()
    ordinary_open = Path.open

    def guarded(path, *args, **kwargs):
        if path == outside:
            pytest.fail("The observed external path became a read capability")
        return ordinary_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", guarded)
        with pytest.raises(ValueError, match="known workspace cache location") as failure:
            EnrollmentService(source).plan()
    assert str(outside) not in str(failure.value) and source.read_bytes() == before
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute(
            "UPDATE research_compound_requests SET context_json=? WHERE request_id=?",
            (original, request_id),
        )
    text_file.write_bytes(b"X" * len(text_file.read_bytes()))
    before = source.read_bytes()
    with pytest.raises(ValueError, match="bytes differ from their recorded observation"):
        EnrollmentService(source).plan()
    assert source.read_bytes() == before
