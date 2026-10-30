"""Typed originals and private provenance survive enrollment without cloning authority."""

import hashlib
import json
import shutil
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from test_sync_source_files import pdf as pdf_bytes
from test_workspace_enrollment import pdf, prepare
from test_workspace_enrollment import source as source_fixture

from paper_daily import (
    annotation_content,
    claim_content,
    research_evidence,
    source_provenance,
    source_snapshots,
    sync_recovery,
)
from paper_daily.document_reader import DocumentReader
from paper_daily.sync_source_files import resolved
from paper_daily.workspace_enrollment import EnrollmentService

source = source_fixture


def claimed(database):
    original = pdf(database)
    reader = DocumentReader(database, projection_root=None, legacy_root=original.parent)
    document = reader.resolve("paper")
    report = research_evidence.verify_snapshot(
        research_evidence.capture(document),
        {
            "format": research_evidence.FORMAT,
            "source": {"paper_id": "paper", "document_hash": document.sha256},
            "claims": [
                {
                    "text": "The study tests a bounded comparison.",
                    "judgment": {"status": "unresolved", "reason": "Independent review needed."},
                    "passages": [{"quote": "A verified source paper", "page": 1, "anchor": None}],
                }
            ],
        },
    )
    inputs = {"dive": "a" * 64, "close_reading": "b" * 64}
    body = annotation_content.validate(
        "claims",
        {
            "format": claim_content.FORMAT,
            "recipe": claim_content.RECIPE,
            "inputs": inputs,
            "generation": {
                "task": "claims",
                "backend": "fixture",
                "requested_model": None,
                "returned_model": None,
            },
            "report": report,
        },
    )
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "INSERT INTO paper_claim_sets VALUES(?,?,?,?,?)",
            (
                "paper",
                json.dumps(body, ensure_ascii=False, sort_keys=True),
                claim_content.source_digest(inputs, document.sha256),
                document.sha256,
                "2026-10-30T00:00:00+00:00",
            ),
        )
    cache = (
        database.parent
        / "pdf/.claim-evidence"
        / claim_content.hashed(["claim-source-owner", "paper"])[:24]
    )
    cache.mkdir(parents=True)
    saved = cache / (document.sha256 + ".pdf")
    shutil.copyfile(original, saved)
    a = original.read_bytes()
    original.write_bytes(pdf_bytes("Current primary source B"))
    return original, saved, a


def test_enrollment_carries_claim_source_A_and_primary_B_plus_complete_backup(source, tmp_path):
    primary, cached, original = claimed(source)
    plan = EnrollmentService(source).plan(pdfs={"paper": primary})
    assert plan["supported"], plan["blockers"]
    assert plan["original_source_count"] == 1 and plan["claim_sources_covered_by_primary"] == 0
    result = prepare(source, tmp_path, pdfs={"paper": primary})
    db = Path(result["database"])
    current = DocumentReader.from_workspace(db).resolve("paper")
    assert current.available and current.path.read_bytes() == primary.read_bytes()
    with closing(sqlite3.connect(db)) as conn:
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
        ).fetchone()[0]
        source_pdf = resolved(conn, portable, hashlib.sha256(original).hexdigest())
        assert source_pdf.read_bytes() == original
    with zipfile.ZipFile(result["backup"]) as archive:
        assert archive.read("objects/" + hashlib.sha256(original).hexdigest()) == original
        assert (
            archive.read("objects/" + hashlib.sha256(primary.read_bytes()).hexdigest())
            == primary.read_bytes()
        )
    assert sync_recovery.inspect(result["backup"])["workspace_id"] == result["workspace_id"]
    # Unknown files remain blockers; source artifacts are not a blanket path allowlist.
    (cached.parent / "unowned.pdf").write_bytes(original)
    changed = EnrollmentService(source).plan(pdfs={"paper": primary})
    assert not changed["supported"] and any("unowned.pdf" in item for item in changed["blockers"])


def receipt(database, digest, size, request="failed-original"):
    return {
        "request_id": request,
        "owner_json": json.dumps(
            {
                "format": "paperfact.source-owner.v1",
                "database_identity": [17, 29],
                "binding": {"workspace_id": "old-workspace", "device_id": "old-device"},
                "paper_id": "retired-paper",
                "parent_lifecycle": "a" * 32,
                "source_owner_id": "retired-paper",
            }
        ),
        "sha256": digest,
        "size": size,
        "media_type": "application/pdf",
    }


def test_archive_is_private_validated_original_observation_not_runtime_identity(source, tmp_path):
    data = pdf_bytes("Failed attempt original retained as private provenance")
    digest = hashlib.sha256(data).hexdigest()
    row = source_provenance.wrap(receipt(source, digest, len(data)))
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        source_provenance.retain_in(conn, [row, row])
        assert source_provenance.archived(conn) == [row]
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='paperfact_sync_identity'"
        ).fetchall()
    folder = source.parent / "pdf"
    folder.mkdir(exist_ok=True)
    (folder / "original.pdf").write_bytes(data)
    package = tmp_path / "archive.zip"
    sync_recovery.create(source, package)
    manifest = sync_recovery.inspect(package)
    assert (
        next(item for item in manifest["tables"] if item["name"] == source_provenance.TABLE)[
            "count"
        ]
        == 1
    )
    with zipfile.ZipFile(package) as archive:
        assert archive.read("objects/" + digest) == data
        recorded = json.loads(archive.read("tables/research_source_archive.jsonl"))
        assert json.loads(recorded["body_json"]) == json.loads(row["body_json"])
    sync_recovery.restore_detached(package, tmp_path / "detached")
    detached = tmp_path / "detached/papers.db"
    with closing(sqlite3.connect(detached)) as conn:
        assert conn.execute("SELECT body FROM notes").fetchall() == [("A research note",)]
        assert conn.execute("SELECT count(*) FROM research_source_archive").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT count(*) FROM recovery_records WHERE table_name=?",
                (source_provenance.TABLE,),
            ).fetchone()[0]
            == 1
        )
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='paperfact_sync_identity'"
        ).fetchall()


@pytest.mark.parametrize("change", ["id", "unknown", "hash", "body"])
def test_archived_provenance_rejects_unknown_or_changed_content(source, change):
    row = source_provenance.wrap(receipt(source, "c" * 64, 100))
    if change == "id":
        row["record_id"] = "d" * 64
    elif change == "unknown":
        row["wire_authority"] = True
    elif change == "hash":
        body = json.loads(row["body_json"])
        body["sha256"] = "invalid"
        row["body_json"] = json.dumps(body)
    else:
        row["body_json"] = "[]"
    with pytest.raises(ValueError):
        source_provenance.validate(row)


def test_enrollment_retains_failed_attempt_originals_privately_and_in_backup(source, tmp_path):
    primary, _cached, original = claimed(source)
    failed = pdf_bytes("Original from an unsuccessful previous generation")
    sha = hashlib.sha256(failed).hexdigest()
    observation = receipt(source, sha, len(failed))
    record = source_provenance.wrap(observation)
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        source_provenance.retain_in(conn, [record])
    location = source_snapshots.source_path(source, observation)
    location.parent.mkdir(parents=True, exist_ok=True)
    location.write_bytes(failed)
    plan = EnrollmentService(source).plan(pdfs={"paper": primary})
    assert plan["supported"], plan["blockers"]
    assert plan["archived_source_receipts"] == 1
    result = prepare(source, tmp_path, pdfs={"paper": primary})
    db = Path(result["database"])
    with closing(sqlite3.connect(db)) as conn:
        assert source_provenance.archived(conn) == [record]
        envelopes = [
            json.loads(item[0])
            for item in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        ]
        assert not any(
            "old-device" in json.dumps(item) or "database_identity" in json.dumps(item)
            for item in envelopes
        )
        declared = [
            item["payload"]["slot"]
            for item in envelopes
            if item["entity_type"] == "research_file"
            and item["payload"]["feature"] == "original_source"
        ]
        assert declared == [hashlib.sha256(original).hexdigest()]
        assert sha not in declared
    assert source_snapshots.list_owned(db) == []
    with zipfile.ZipFile(result["backup"]) as archive:
        assert archive.read("objects/" + sha) == failed
        rows = archive.read("tables/research_source_archive.jsonl").splitlines()
        assert [json.loads(item) for item in rows] == [record]
    assert sync_recovery.inspect(result["backup"])["workspace_id"] == result["workspace_id"]
