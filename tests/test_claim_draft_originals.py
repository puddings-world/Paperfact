"""Historical PDF reading is independent of claim Apply, but not source ownership."""

import hashlib
import os
import pickle
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_claim_conflict_intent import remote as remote
from test_claim_draft_storage import rows
from test_claim_review_continuity import claims as claims
from test_claim_review_continuity import ready as ready
from test_claim_review_continuity import receiver as receiver
from test_claim_review_continuity import scene as scene
from test_claim_review_continuity import source_pair as source_pair
from test_claim_review_continuity import workspace as workspace
from test_claim_review_operations import invoke

from paper_daily import claim_draft_originals as originals
from paper_daily import research_generation as generation
from paper_daily.document_reader import DocumentReader
from paper_daily.research_review import ResearchReview
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_files import file_id
from paper_daily.sync_source_files import FEATURE

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


@pytest.fixture
def accepted(remote):
    value = remote
    opened = invoke(
        "open", origin_id=value["origin"], target_id=value["local"], operation_id="read-open"
    )
    body = invoke("read", draft_id=opened["draft_id"])["draft"]
    body["claims"][0]["text"] = "Accepted interpretation remains readable after conflict closure."
    saved = invoke(
        "save", draft_id=opened["draft_id"], revision=1, draft=body, operation_id="read-save"
    )
    result = invoke(
        "apply",
        draft_id=opened["draft_id"],
        revision=saved["revision"],
        operation_id="read-apply",
        confirm=True,
    )
    value["b"].sync_once(value["service"], value["tb"], limit=1000)
    value["a"].sync_once(value["service"], value["ta"], limit=1000)
    service = ResearchReview(value["b"].journal.path)
    try:
        yield dict(
            value,
            review=service,
            reference=(result["draft_id"], result["revision"]),
            sha=value["value"]["source_hash"],
        )
    finally:
        service.close()


def prepare(value, **changes):
    arguments = dict(reference=value["reference"])
    arguments.update(changes)
    return originals.prepare(value["review"], None, value["sha"], **arguments)


def test_decided_draft_original_read_preserves_storage_primary_and_write_authority(accepted):
    value = accepted
    path = value["b"].journal.path
    root = rows(path, "SELECT blob_root FROM research_file_paths")[0]["blob_root"]
    from pathlib import Path

    index = Path(root) / "index.sqlite"
    before = path.read_bytes(), index.read_bytes()
    proof = prepare(value)
    assert hashlib.sha256(proof.data).hexdigest() == value["sha"]
    assert proof.pages > 0 and originals.gui_status(proof) == "ready"
    assert (path.read_bytes(), index.read_bytes()) == before
    assert not value["review"]._claim_revisions and not value["review"]._resume_sources
    with pytest.raises(ValueError):
        value["review"].apply_claim_draft(proof, "{}", request_id=str(uuid4()), confirm_target=True)
    assert not value["b"].journal.pending(1000)
    assert (
        DocumentReader.from_workspace(path).resolve(value["local"]).sha256
        == value["value"]["current"].sha256
    )


def test_read_proof_admission_is_sql_hash_pdf_free_and_not_serializable(accepted, monkeypatch):
    proof = prepare(accepted)

    def forbidden(*args, **kwargs):
        raise AssertionError("GUI source admission performed expensive work")

    with monkeypatch.context() as patch:
        import pymupdf

        patch.setattr(sqlite3, "connect", forbidden)
        patch.setattr(hashlib, "sha256", forbidden)
        patch.setattr(pymupdf, "open", forbidden)
        assert originals.gui_status(proof) == "ready"
    with pytest.raises(TypeError, match="process-only"):
        pickle.dumps(proof)
    accepted["review"].close()
    assert originals.gui_status(proof) == "revoked"


def test_new_title_and_note_revalidate_the_same_original_without_refreshing_claim_base(accepted):
    value = accepted
    proof = prepare(value)
    path = value["b"].journal.path
    with closing(generation._connect(path)) as conn, conn:
        conn.execute("UPDATE papers SET title='New readable title' WHERE id=?", (value["local"],))
        conn.execute(
            "INSERT INTO notes(paper_id,body,page,anchor,kind,created_at) "
            "VALUES(?,'Independent note',NULL,NULL,'note','2026-11-02T00:00:00+00:00')",
            (value["local"],),
        )
    assert originals.gui_status(proof) == "recheck"
    pending = value["b"].journal.pending(1000)
    refreshed = originals.revalidate(proof)
    assert refreshed.data == proof.data and originals.gui_status(refreshed) == "ready"
    assert value["b"].journal.pending(1000) == pending
    assert not value["review"]._claim_revisions


def test_known_original_retirement_does_not_fall_back_to_primary_or_recovery_cache(accepted):
    value = accepted
    proof = prepare(value)
    with closing(generation._connect(value["b"].journal.path)) as conn:
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (value["local"],)
        ).fetchone()[0]
    identity = file_id(portable, FEATURE, value["sha"])
    value["b"].save(value["b"].new_graph_operation("research_file", identity, {}, action="delete"))
    with pytest.raises(ValueError, match="deleted or retired"):
        originals.revalidate(proof)
    with pytest.raises(ValueError, match="deleted or retired"):
        prepare(value)
    assert (
        DocumentReader.from_workspace(value["b"].journal.path).resolve(value["local"]).sha256
        == value["value"]["current"].sha256
    )


def test_same_size_original_mutation_and_restored_mtime_revoke_the_read(accepted):
    proof = prepare(accepted)
    before = proof.source_path.stat()
    modified = bytearray(proof.data)
    modified[-10] ^= 1
    proof.source_path.write_bytes(modified)
    os.utime(proof.source_path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert originals.gui_status(proof) == "revoked"
    with pytest.raises(ValueError):
        originals.revalidate(proof)
    with pytest.raises((ValueError, OSError)):
        prepare(accepted)


def test_native_database_replacement_cannot_receive_old_read_results(accepted):
    value = accepted
    proof = prepare(value)
    path = value["b"].journal.path
    replacement = path.with_suffix(".replacement")
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(replacement)) as target:
        source.backup(target)
    replacement.replace(path)
    before = path.read_bytes()
    assert originals.gui_status(proof) == "revoked"
    with pytest.raises(ValueError):
        originals.revalidate(proof)
    assert path.read_bytes() == before


def test_private_revision_change_requires_its_exact_source_reference_again(accepted):
    value = accepted
    proof = prepare(value)
    body = invoke("read", draft_id=value["reference"][0])["draft"]
    body["claims"][0]["text"] = "Another saved private interpretation after the read began."
    saved = invoke(
        "save",
        draft_id=value["reference"][0],
        revision=value["reference"][1],
        draft=body,
        operation_id="private-after-read",
    )
    with pytest.raises(ValueError, match="draft changed"):
        originals.revalidate(proof)
    fresh = prepare(value, reference=(value["reference"][0], saved["revision"]))
    assert fresh.data == proof.data and not value["b"].journal.pending(1000)


def test_independently_recovered_private_source_can_be_read_without_publication(receiver):
    value = receiver
    review = value["review"]
    data = value["preview"].data
    with closing(generation._connect(value["path"])) as conn:
        operation = desired_file(
            conn, file_id(data["expected"]["paper_sync_id"], FEATURE, value["source_hash"])
        )
    assert operation is None
    before = value["path"].read_bytes()
    proof = originals.prepare(review, value["preview"], value["source_hash"])
    assert proof.document_hash == value["source_hash"]
    assert value["path"].read_bytes() == before
    assert not review._claim_revisions and not review._resume_sources
    assert (
        DocumentReader.from_workspace(value["path"]).resolve(data["expected"]["paper_id"]).sha256
        == value["current"].sha256
    )


def test_bad_source_references_and_cancellation_never_write_or_select_a_fallback(accepted):
    value = accepted
    path = value["b"].journal.path
    before = path.read_bytes()
    for reference in (
        ("bad", 1),
        (value["reference"][0], True),
        (value["reference"][0], 0),
        (value["reference"][0], 999999),
        [value["reference"][0], 1],
    ):
        with pytest.raises(ValueError):
            prepare(value, reference=reference)
    with pytest.raises(ValueError, match="cancelled"):
        prepare(value, cancelled=lambda: True)
    with pytest.raises(ValueError, match="outside"):
        originals.prepare(value["review"], None, "a" * 64, reference=value["reference"])
    assert path.read_bytes() == before
