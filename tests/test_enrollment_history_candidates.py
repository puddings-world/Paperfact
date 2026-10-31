"""Cancelled/stale completed output stays private with exact original input bytes."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
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
from test_sync_source_files import pdf

from paper_daily import enrollment_history, llm
from paper_daily import research_generation as generation
from paper_daily.workspace_enrollment import EnrollmentService

claims = claims_fixture
ready = ready_fixture
workspace = workspace_fixture


@pytest.mark.parametrize("kind", ["sql_candidate", "sidecar_candidate"])
def test_original_A_active_and_completed_B_candidate_keep_both_sources_and_raw_inputs(
    claims, tmp_path, monkeypatch, kind
):
    a = claims[0][2].path.read_bytes()
    assert job(claims).run().status == "accepted"
    claims[0][2].path.write_bytes(pdf("Original source B for a private completed candidate"))
    b = claims[0][2].path.read_bytes()
    current = job(claims)
    if kind == "sql_candidate":
        complete = llm.complete_result

        def changed(*args, **kwargs):
            output = complete(*args, **kwargs)
            with closing(generation._connect(claims[0][0])) as conn, conn:
                from paper_daily.sync_capture import suppress_capture

                with suppress_capture(conn):
                    conn.execute("UPDATE dives SET body='A newer human interpretation'")
            return output

        monkeypatch.setattr(llm, "complete_result", changed)
        outcome = current.run()
    else:
        outcome = current.run(cancelled=lambda: len(claims[2]) > 1)
    assert outcome.status == "candidate"
    if claims[0][1] is not None:
        return
    db = claims[0][0]
    service = EnrollmentService(db)
    report = service.plan(pdfs={"paper": claims[0][2].path})
    assert report["supported"], report["blockers"]
    assert report["history_original_sources"] == 2
    assert report["archived_history_records"] >= 3
    token = str(uuid4())
    result = service.prepare(
        tmp_path.parent / ("retained-" + token),
        backup_output=tmp_path.parent / (token + ".zip"),
        request_id=token,
        pdfs={"paper": claims[0][2].path},
    )
    with closing(sqlite3.connect(result["database"])) as conn:
        records = enrollment_history.archived(conn)
        decoded = [(row["protocol"], enrollment_history.validate(row)[0]) for row in records]
        retained = next(
            row for protocol, row in decoded if row.get("request_id") == current.context.request_id
        )
        assert retained["context_json"] == current.context._json
        assert json.loads(retained["row_json"]) == current.result
        assert retained["status"] == "candidate"
        canonical = json.loads(
            conn.execute(
                "SELECT body_json FROM paper_claim_sets WHERE paper_id='paper'"
            ).fetchone()[0]
        )
        assert canonical["report"]["source"]["document_hash"] == hashlib.sha256(a).hexdigest()
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='research_generation_requests'"
        ).fetchall()
    with zipfile.ZipFile(result["backup"]) as archive:
        assert archive.read("objects/" + hashlib.sha256(a).hexdigest()) == a
        assert archive.read("objects/" + hashlib.sha256(b).hexdigest()) == b


def test_prior_target_only_original_is_preserved_by_hash_without_current_receipt(claims, tmp_path):
    from paper_daily import claim_content, research_evidence
    from paper_daily.document_reader import DocumentReader

    assert job(claims).run().status == "accepted"
    if claims[0][1] is not None:
        return
    db = claims[0][0]
    primary = claims[0][2].path
    original = primary.read_bytes()
    c = pdf("A third original cohort with independent assignment was reported.")
    extra = primary.parent / "prior-target-only.pdf"
    extra.write_bytes(c)
    primary.write_bytes(c)
    document = DocumentReader.from_workspace(db, legacy_root=primary.parent).resolve("paper")
    report = research_evidence.verify_snapshot(
        research_evidence.capture(document),
        {
            "format": research_evidence.FORMAT,
            "source": {"paper_id": "paper", "document_hash": document.sha256},
            "claims": [
                {
                    "text": "A prior cohort was described.",
                    "judgment": {"status": "unresolved", "reason": "Prior observation only."},
                    "passages": [
                        {
                            "quote": (
                                "A third original cohort with independent assignment was reported."
                            ),
                            "page": 1,
                            "anchor": None,
                        }
                    ],
                }
            ],
        },
    )
    primary.write_bytes(original)
    with closing(generation._connect(db)) as conn, conn:
        receipt = dict(conn.execute("SELECT * FROM research_generation_requests").fetchone())
        row = dict(conn.execute("SELECT * FROM paper_claim_sets").fetchone())
        body = json.loads(row["body_json"])
        body["report"] = report
        row.update(
            body_json=generation._json(body),
            document_hash=report["source"]["document_hash"],
            source_hash=claim_content.source_digest(
                body["inputs"], report["source"]["document_hash"]
            ),
        )
        context = json.loads(receipt["context_json"])
        context["target"] = row
        changed = generation._json(context)
        conn.execute("UPDATE research_generation_requests SET context_json=?", (changed,))
    plan = EnrollmentService(db).plan(pdfs={"paper": primary})
    assert plan["supported"] and plan["history_original_sources"] == 2
    token = str(uuid4())
    result = EnrollmentService(db).prepare(
        tmp_path.parent / ("target-" + token),
        backup_output=tmp_path.parent / (token + ".zip"),
        request_id=token,
        pdfs={"paper": primary},
    )
    with zipfile.ZipFile(result["backup"]) as archive:
        assert archive.read("objects/" + hashlib.sha256(c).hexdigest()) == c
        assert archive.read("objects/" + hashlib.sha256(original).hexdigest()) == original
    with closing(sqlite3.connect(result["database"])) as conn:
        wire = [
            json.loads(row[0])
            for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        ]
        sources = [row["payload"]["slot"] for row in wire if row["entity_type"] == "research_file"]
        assert hashlib.sha256(c).hexdigest() not in sources
        records = enrollment_history.archived(conn)
        stored = next(
            enrollment_history.validate(row)[0]
            for row in records
            if row["protocol"] == "research_generation_requests"
        )
        assert stored["context_json"] == changed
