"""Exact primary/original/deck byte closures survive fresh editable adoption."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from test_recovery_adoption import prepared
from test_slide_revision_recovery import archive
from test_slide_revision_recovery import revision as revision_fixture
from test_source_enrollment import claimed
from test_sync_files import LOCAL, png
from test_sync_files import codec as codec_fixture
from test_sync_files import pair as pair_fixture
from test_workspace_enrollment import prepare
from test_workspace_enrollment import source as source_fixture

from paper_daily import presentations, sync_recovery
from paper_daily.document_reader import DocumentReader
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.sync_artifacts import paths, version_directory
from paper_daily.sync_blobs import BlobManifest
from paper_daily.sync_source_files import resolved

source = source_fixture
pair = pair_fixture
codec = codec_fixture
revision = revision_fixture
NORMAL_FIGURE = presentations.figure_bytes


def test_claim_original_A_and_current_B_remain_distinct_and_complete(source, tmp_path):
    primary, _cache, original = claimed(source)
    initial = prepare(source, tmp_path, pdfs={"paper": primary})
    restored = tmp_path / "detached-claims"
    sync_recovery.restore_detached(initial["backup"], restored)
    service = RecoveryAdoptionService(restored / "papers.db")
    result = prepared(service, service.inspect(), tmp_path, "-claims")
    database = Path(result["database"])
    current = DocumentReader.from_workspace(database).resolve("paper")
    assert (
        current.path.read_bytes() == primary.read_bytes() and current.path.read_bytes() != original
    )
    with closing(sqlite3.connect(database)) as conn:
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
        ).fetchone()[0]
        actual = resolved(conn, portable, hashlib.sha256(original).hexdigest())
        assert actual.read_bytes() == original
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM research_file_versions "
                "WHERE json_extract(operation,'$.payload.feature')='original_source'"
            ).fetchone()[0]
            == 1
        )
    manifest = sync_recovery.inspect(result["backup"])
    old = sync_recovery.inspect(initial["backup"])
    assert {item["sha256"] for item in old["blobs"]} <= {
        item["sha256"] for item in manifest["blobs"]
    }


@pytest.mark.parametrize("with_evidence", [False, True])
def test_current_deck_layout_notes_figure_assets_and_evidence_are_editable_copy(
    revision, tmp_path, monkeypatch, with_evidence
):
    if with_evidence:
        presentations.save_deck(
            revision[2],
            evidence={
                "sources": revision[2].sources,
                "coverage": [],
                "source_hash": revision[2].source_hash,
            },
        )
    original = archive(revision, tmp_path)
    detached = tmp_path / "detached-deck"
    sync_recovery.restore_detached(original, detached)
    monkeypatch.setattr(presentations, "figure_bytes", NORMAL_FIGURE)
    service = RecoveryAdoptionService(detached / "papers.db")
    inspection = service.inspect()
    result = prepared(service, inspection, tmp_path, "-deck")
    database = Path(result["database"])
    with closing(sqlite3.connect(database)) as conn:
        operation = json.loads(
            conn.execute(
                "SELECT operation FROM research_file_applied "
                "WHERE json_extract(operation,'$.payload.feature')='deck'"
            ).fetchone()[0]
        )
        payload = operation["payload"]
        blobstore, versionroot = paths(conn)
    from paper_daily.sync_files import validate_closure

    body = validate_closure(
        payload,
        lambda item: blobstore.verified_path(
            BlobManifest(item["sha256"], item["size"])
        ).read_bytes(),
    )
    assert body["deck"]["slides"][0]["speaker_notes"] == "Speaker explanation"
    assert body["deck"]["slides"][0]["elements"] == revision[2].to_dict()["slides"][0]["elements"]
    assert payload["input_versions"]["complete"] is False
    assert payload["input_versions"]["entities"] == []
    assert payload["input_versions"]["documents"] == []
    assert payload["paper_id"] == operation["parents"][0]["id"]
    assert payload["paper_id"] != LOCAL
    assert (body["evidence_asset"] is not None) is with_evidence
    assert version_directory(versionroot, operation).is_dir()
    old_manifest = sync_recovery.inspect(original)
    new_manifest = sync_recovery.inspect(result["backup"])
    assert {item["sha256"] for item in old_manifest["blobs"]} <= {
        item["sha256"] for item in new_manifest["blobs"]
    }
    assert any(
        blobstore.verified_path(BlobManifest(item["sha256"], item["size"])).read_bytes()
        == png("red")
        for item in payload["assets"]
        if item["role"] == "figure"
    )

    # Verify real editor publication, not only that a fresh artifact materialized.
    from paper_daily import llm, store

    def forbidden(*_args, **_kwargs):
        pytest.fail("Manual recovered deck editing invoked AI")

    monkeypatch.setattr(llm, "complete_result", forbidden)
    monkeypatch.setattr(llm, "settings", forbidden)
    old_saved = next((detached / "presentations").glob("*/guide.json"))
    old_bytes = old_saved.read_bytes()
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(presentations, "DECK_DIR", database.parent / "presentations")
    editable = presentations.load_deck(LOCAL, "guide")
    assert editable is not None and not getattr(editable, "_recovery_deck", None)
    editable.title = "Manual edit in independent copy"
    editable.slides[0].speaker_notes += "\nA colleague's added explanation"
    evidence = None
    if body["evidence_asset"] is not None:
        asset = next(item for item in payload["assets"] if item["id"] == body["evidence_asset"])
        evidence = json.loads(
            blobstore.verified_path(BlobManifest(asset["sha256"], asset["size"])).read_bytes()
        )
    presentations.save_deck(editable, evidence=evidence)
    reopened = presentations.load_deck(LOCAL, "guide")
    assert reopened.title == "Manual edit in independent copy"
    assert reopened.slides[0].speaker_notes.endswith("A colleague's added explanation")
    assert presentations.figure_bytes(reopened, "figure:1") == png("red")
    assert old_saved.read_bytes() == old_bytes


@pytest.mark.parametrize("change", ["object", "projection"])
def test_damaged_retained_object_or_saved_projection_cannot_be_adopted(
    revision, tmp_path, monkeypatch, change
):
    original = archive(revision, tmp_path)
    detached = tmp_path / "damaged"
    sync_recovery.restore_detached(original, detached)
    monkeypatch.setattr(presentations, "figure_bytes", NORMAL_FIGURE)
    if change == "object":
        location = next((detached / "objects").iterdir())
        location.write_bytes(b"x" * location.stat().st_size)
    else:
        location = next((detached / "presentations").glob("*/guide.json"))
        raw = json.loads(location.read_bytes())
        raw["title"] = "Unrepresented newer deck"
        location.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        RecoveryAdoptionService(detached / "papers.db").inspect()
    assert not (tmp_path / "editable-deck").exists()
