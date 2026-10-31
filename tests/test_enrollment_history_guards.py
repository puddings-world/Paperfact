"""Unknown or damaged archived observations never gain a migration/replay capability."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
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


def actual(claims):
    assert job(claims).run().status == "accepted"
    with closing(generation._connect(claims[0][0])) as conn:
        return dict(conn.execute("SELECT * FROM research_generation_requests").fetchone())


@pytest.mark.parametrize(
    "change",
    [
        "protocol",
        "extra",
        "status",
        "context_extra",
        "missing_input",
        "wrong_owner",
        "duplicate",
        "nonfinite",
    ],
)
def test_archive_rejects_malformed_or_unknown_typed_history(claims, change):
    record = actual(claims)
    protocol = "research_generation_requests"
    if change == "protocol":
        protocol = "research_unknown_requests"
    elif change == "extra":
        record["unknown_authority"] = True
    elif change == "status":
        record["status"] = "publish_me"
    elif change in {"context_extra", "missing_input", "wrong_owner"}:
        context = json.loads(record["context_json"])
        if change == "context_extra":
            context["execute"] = "never"
        elif change == "missing_input":
            context["inputs"]["missing"] = "unknown"
        else:
            context["inputs"]["dives"]["paper_id"] = "other-paper"
        record["context_json"] = generation._json(context)
    elif change == "duplicate":
        record["context_json"] = record["context_json"][:-1] + ',"owner_id":"paper"}'
    else:
        record["context_json"] = record["context_json"][:-1] + ',"unsupported_number":NaN}'
    with pytest.raises(ValueError):
        enrollment_history.wrap(protocol, record)


def test_unknown_source_lifecycle_trigger_is_not_whitelisted_by_name(claims):
    actual(claims)
    db = claims[0][0]
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("DROP TRIGGER paperfact_parent_papers_insert")
        conn.execute(
            "CREATE TRIGGER paperfact_parent_papers_insert AFTER INSERT ON papers "
            "BEGIN SELECT 1; END"
        )
    with pytest.raises(ValueError, match="lifecycle schema"):
        EnrollmentService(db).plan(pdfs={"paper": claims[0][2].path})


def test_archive_write_failure_publishes_nothing_and_preserves_source_observations(
    claims, tmp_path, monkeypatch
):
    original = actual(claims)
    if claims[0][1] is not None:
        return
    db = claims[0][0]
    keep = enrollment_history.retain_in

    def failed(conn, rows):
        keep(conn, rows)
        raise OSError("archive persistence failed after rows")

    monkeypatch.setattr(enrollment_history, "retain_in", failed)
    token = str(uuid4())
    output = tmp_path.parent / ("failed-" + token)
    backup = tmp_path.parent / (token + ".zip")
    with pytest.raises(OSError, match="archive persistence"):
        EnrollmentService(db).prepare(
            output, backup_output=backup, request_id=token, pdfs={"paper": claims[0][2].path}
        )
    assert not output.exists() and not backup.exists()
    with closing(generation._connect(db)) as conn:
        assert (
            dict(conn.execute("SELECT * FROM research_generation_requests").fetchone()) == original
        )
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='research_history_archive'"
        ).fetchall()


def test_context_document_path_is_preserved_text_never_a_source_lookup_capability(
    claims, tmp_path, monkeypatch
):
    original = actual(claims)
    if claims[0][1] is not None:
        return
    db = claims[0][0]
    foreign = tmp_path.parent / (str(uuid4()) + ".pdf")
    foreign.write_bytes(b"do not read foreign bytes")
    context = json.loads(original["context_json"])
    context["document"]["path"] = str(foreign)
    updated = generation._json(context)
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("UPDATE research_generation_requests SET context_json=?", (updated,))
    opened = Path.open

    def forbidden(self, *args, **kwargs):
        if self == foreign:
            pytest.fail("Migration followed archived source path")
        return opened(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbidden)
    token = str(uuid4())
    result = EnrollmentService(db).prepare(
        tmp_path.parent / ("safe-" + token),
        backup_output=tmp_path.parent / (token + ".zip"),
        request_id=token,
        pdfs={"paper": claims[0][2].path},
    )
    with closing(sqlite3.connect(result["database"])) as conn:
        archived = next(
            enrollment_history.validate(row)[0]
            for row in enrollment_history.archived(conn)
            if row["protocol"] == "research_generation_requests"
        )
        assert archived["context_json"] == updated
        wire = "\n".join(
            row[0] for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        )
        assert str(foreign) not in wire


def test_archive_overflow_or_unknown_protocol_never_initializes_a_table(monkeypatch):
    record = enrollment_history.wrap(
        "research_parent_lifecycle",
        {"kind": "paper", "entity_id": "paper", "token": "a" * 32, "active": 1},
    )
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("BEGIN")
        monkeypatch.setattr(enrollment_history, "MAX_TOTAL", 1)
        with pytest.raises(ValueError, match="byte bound"):
            enrollment_history.retain_in(conn, [record])
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []
    with pytest.raises(ValueError, match="protocol"):
        enrollment_history.wrap({"unknown": "not a protocol"}, {})


def test_oversized_history_SQL_field_is_rejected_before_JSON_or_sidecar_access(
    tmp_path, monkeypatch
):
    from paper_daily import store
    from paper_daily.workspace_service import Ticket

    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(store.SCHEMA)
        conn.execute(
            "CREATE TABLE research_generation_requests(request_id TEXT,context_json TEXT,"
            "row_json TEXT,status TEXT,candidate_id TEXT,reason TEXT)"
        )
        conn.execute(
            "INSERT INTO research_generation_requests VALUES(?,?,?,?,?,?)",
            ("record", "x" * 1024, "{}", "accepted", None, "fixture"),
        )
        monkeypatch.setattr(enrollment_history, "MAX_ROW", 32)
        with pytest.raises(ValueError, match="scalar type"):
            enrollment_history.collect(conn, tmp_path / "never-created.sqlite", Ticket())
        assert (
            conn.execute(
                "SELECT length(context_json) FROM research_generation_requests"
            ).fetchone()[0]
            == 1024
        )
        assert not (tmp_path / "never-created.sqlite").exists()
