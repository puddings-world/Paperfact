"""Claim packages/recovery keep original A inspectable when the reader uses B."""

import hashlib
import json
import zipfile
from contextlib import closing

import pytest
from test_claim_jobs import claims as _claims
from test_claim_jobs import job
from test_claim_jobs import ready as _ready
from test_claim_jobs import workspace as _workspace
from test_research_generation import pdf, rows

from paper_daily import (
    bundle,
    llm,
    store,
    sync_capture,
    sync_recovery,
)
from paper_daily import research_generation as generation
from paper_daily.research_review import ResearchReview
from paper_daily.sync_content import content_id, validate_payload
from paper_daily.workspace_enrollment import _files
from paper_daily.workspace_service import Ticket

claims = _claims
ready = _ready
workspace = _workspace


def source_setup(claims, monkeypatch):
    root = claims[0][0].parent
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    with (
        closing(generation._connect(claims[0][0])) as conn,
        conn,
        sync_capture.suppress_capture(conn),
    ):
        conn.execute(
            "INSERT INTO lists(id,name,created_at) "
            "VALUES('l','Research','2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('l','paper',0,'2026-01-01T00:00:00+00:00')"
        )
    return root


def replace_source(claims):
    original = claims[0][2].path.read_bytes()
    claims[0][2].path.unlink()
    pdf(claims[0][2].path, "A different current original paper version B")
    return original, claims[0][2].path.read_bytes()


def test_old_source_claims_roundtrip_with_current_b_and_explicit_required_capability(
    claims, monkeypatch, tmp_path
):
    root = source_setup(claims, monkeypatch)
    assert job(claims).run().status == "accepted"
    original_body = rows(claims[0][0], "SELECT body_json FROM paper_claim_sets")[0]["body_json"]
    original, current = replace_source(claims)
    package = root / "claims.zip"
    bundle.export("l", package, with_pdfs=True)
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == 2 and "claim_evidence" in manifest["capabilities"]
        selected = manifest["claim_sources"]["paper"]
        assert selected["sha256"] == hashlib.sha256(original).hexdigest()
        assert archive.read("files/" + selected["path"]) == original
        assert archive.read("files/pdf/paper.pdf") == current
    recipient = tmp_path / "recipient"
    recipient.mkdir()
    monkeypatch.setattr(store, "DB_PATH", recipient / "papers.db")
    monkeypatch.setattr(bundle, "DATA_DIR", recipient)
    monkeypatch.setattr(bundle, "PDF_DIR", recipient / "pdf")
    monkeypatch.setattr(llm, "complete_result", lambda *a, **kw: pytest.fail("No AI during import"))
    store.init_db()
    bundle.import_(package, pdfs=False)
    bundle.import_(package, pdfs=False)
    assert rows(store.DB_PATH, "SELECT body_json FROM paper_claim_sets") == [
        {"body_json": original_body}
    ]
    assert (recipient / selected["path"]).read_bytes() == original
    assert (recipient / "pdf/paper.pdf").read_bytes() == current
    again = recipient / "again.zip"
    bundle.export("l", again, with_pdfs=True)
    with zipfile.ZipFile(again) as archive:
        assert archive.read("files/" + selected["path"]) == original


def test_source_capability_or_declared_original_cannot_be_stripped(claims, monkeypatch):
    root = source_setup(claims, monkeypatch)
    assert job(claims).run().status == "accepted"
    package = root / "complete.zip"
    bundle.export("l", package)
    for mode in ("capability", "source", "bytes"):
        destination = root / (mode + ".zip")
        with zipfile.ZipFile(package) as incoming, zipfile.ZipFile(destination, "w") as outgoing:
            manifest = json.loads(incoming.read("manifest.json"))
            selected = manifest["claim_sources"]["paper"]["path"]
            if mode == "capability":
                manifest["capabilities"].remove("claim_evidence")
            elif mode == "source":
                manifest["claim_sources"]["paper"]["path"] = None
            for name in incoming.namelist():
                if mode == "bytes" and name == "files/" + selected:
                    continue
                outgoing.writestr(
                    name, json.dumps(manifest) if name == "manifest.json" else incoming.read(name)
                )
        with zipfile.ZipFile(destination) as archive, pytest.raises(ValueError):
            bundle._validated(archive)


def test_completed_stale_candidate_backup_carries_exact_original_a_after_replacement(
    claims, monkeypatch
):
    current = job(claims)
    original = claims[0][2].path.read_bytes()
    complete = llm.complete_result

    def replaced(*args, **kwargs):
        output = complete(*args, **kwargs)
        replace_source(claims)
        return output

    monkeypatch.setattr(llm, "complete_result", replaced)
    assert current.run().status == "candidate"
    # Existing complete-backup policy refuses unowned legacy PDFs. Declare B
    # through an actual observed current-source publication; A must still survive
    # independently through the completed stale claim receipt and source cache.
    from paper_daily.document_reader import from_workspace

    document = from_workspace(claims[0][0], legacy_root=claims[0][2].path.parent).resolve("paper")
    with closing(generation._connect(claims[0][0])) as conn:
        observed = generation.begin_generation(conn, table="close_readings", owner_id="paper")
    observed = generation.bind_inputs(observed, document=document)
    assert (
        generation.publish_generation(
            observed,
            row={
                "paper_id": "paper",
                "body": "Current B close reading",
                "spec": "fixture",
                "written_at": observed.started_at,
            },
        ).status
        == "accepted"
    )
    package = claims[0][0].parent / "backup.zip"
    sync_recovery.create(claims[0][0], package)
    with zipfile.ZipFile(package) as archive:
        manifest = sync_recovery.inspect(package)
        digest = hashlib.sha256(original).hexdigest()
        assert digest in {row["sha256"] for row in manifest["blobs"]}
        assert archive.read("objects/" + digest) == original
    destination = claims[0][0].parent / "restored"
    sync_recovery.restore_detached(package, destination)
    records = rows(
        destination / "papers.db",
        "SELECT data FROM recovery_records WHERE table_name='research_generation_requests'",
    )
    assert any(
        json.loads(json.loads(record["data"])["row_json"]).get("document_hash") == digest
        for record in records
    )


def test_claim_review_is_keep_export_only_even_with_explicit_target(claims, monkeypatch):
    current = job(claims)
    complete = llm.complete_result

    def edited(*args, **kwargs):
        output = complete(*args, **kwargs)
        with (
            closing(generation._connect(claims[0][0])) as conn,
            conn,
            sync_capture.suppress_capture(conn),
        ):
            conn.execute("UPDATE dives SET body='Later edit' WHERE paper_id='paper'")
        return output

    monkeypatch.setattr(llm, "complete_result", edited)
    outcome = current.run()
    assert outcome.status == "candidate"
    review = ResearchReview(claims[0][0])
    shown = review.preview("generation", current.context.request_id)
    assert not shown.data["apply"] and not shown.data["editable"]
    explicit = review.target_preview(shown, "paper")
    assert not explicit.data["apply"]
    with pytest.raises(ValueError, match="source-aware review"):
        review.decide(explicit, request_id="no-partial", confirm_target=True)
    text = review.export_text(shown)
    assert "Independent observations isolate the comparison" in text and "quote" in text
    assert "requested_model" not in text and "inputs" not in text and str(claims[0][0]) not in text
    assert review.decide(shown, keep=True, request_id="keep")["decision"] == "kept"


def test_remote_payload_cannot_claim_a_different_pdf_than_its_report(claims):
    assert job(claims).run().status == "accepted"
    row = rows(claims[0][0], "SELECT * FROM paper_claim_sets")[0]
    payload = {
        "scope": {"kind": "paper", "id": "11111111-1111-4111-8111-111111111111"},
        "feature": "claims",
        "key": "main",
        "source_document_hash": row["document_hash"],
        "data": {
            key: json.loads(value) if key == "body_json" else value
            for key, value in row.items()
            if key != "paper_id"
        },
    }
    validate_payload(payload, entity_id=content_id(payload["scope"], "claims", "main"))
    payload["source_document_hash"] = payload["data"]["document_hash"] = "f" * 64
    with pytest.raises(ValueError, match="different original source"):
        validate_payload(payload)


def test_enrollment_claim_alias_requires_validated_owner_exact_primary_and_bytes(claims):
    assert job(claims).run().status == "accepted"
    row = rows(claims[0][0], "SELECT * FROM paper_claim_sets")[0]
    root = claims[0][0].parent
    selected = {"paper": claims[0][2].path}
    _manifests, _files_metadata, blockers = _files(
        root, claims[0][0], selected, {"paper"}, Ticket(), claim_sources=[row]
    )
    assert not [item for item in blockers if ".claim-evidence" in item]
    replace_source(claims)
    _manifests, _files_metadata, blockers = _files(
        root, claims[0][0], selected, {"paper"}, Ticket(), claim_sources=[row]
    )
    assert not any("claim source requires its exact selected original" in item for item in blockers)
    assert not any(".claim-evidence" in item for item in blockers)
    # Historical originals now have a typed wire artifact, independent of B.
    cache = next((root / "pdf/.claim-evidence").rglob("*.pdf"))
    cache.write_bytes(b"changed original")
    with pytest.raises(ValueError, match="changed"):
        _files(root, claims[0][0], selected, {"paper"}, Ticket(), claim_sources=[row])
