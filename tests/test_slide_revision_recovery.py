"""Detached backup preserves completed slide work without reviving write authority."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from dataclasses import asdict

import pytest
from test_sync_files import LOCAL, PAPER, save_current
from test_sync_files import codec as codec_fixture
from test_sync_files import pair as pair_fixture

from paper_daily import llm, presentations, slide_revision, store
from paper_daily import sync_recovery as recovery
from paper_daily import sync_slide_recovery as slides
from paper_daily.ai_types import Completion
from paper_daily.sync_artifacts import paths
from paper_daily.sync_blobs import BlobManifest

codec = codec_fixture
pair = pair_fixture


@pytest.fixture
def revision(pair, codec, monkeypatch):
    source = pair[1].journal.path
    monkeypatch.setattr(presentations, "DECK_DIR", source.parent / "presentations")
    value = codec[0]
    save_current(pair, value)
    loaded = presentations.load_deck(LOCAL, "guide")
    calls = []

    def model(*args, **kwargs):
        calls.append(1)
        slide = asdict(loaded.slides[0])
        slide.update(title="Retained completed revision", elements=None)
        return Completion(json.dumps({"slide": slide, "summary": "Revised with evidence"}))

    monkeypatch.setattr(llm, "complete_result", model)
    with pair[1].journal.transaction() as conn:
        blob_store = paths(conn)[0]
    return source, pair[1], loaded, blob_store, calls


def archive(revision, tmp_path, name="backup.zip"):
    source, _, _, blob_store, _ = revision
    output = tmp_path / name
    recovery.create(source, output, blob_store=blob_store)
    return output


def detached_records(output, destination, identity):
    recovery.restore_detached(output, destination)
    result = slides.read_detached(destination / "papers.db", identity)
    assert result["capabilities"] == {
        "publish": False,
        "retry": False,
        "sync": False,
        "requires_explicit_review": True,
    }
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & {"paperfact_sync_identity", "research_sync_binding", slides.TABLE}
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM recovery_records WHERE table_name=?", (slides.TABLE,)
            ).fetchone()[0]
            == 1
        )
    assert not list(destination.rglob(".revision-requests"))
    return result["record"]


def test_completed_revision_roundtrip_preserves_prompt_original_result_and_pngs(revision, tmp_path):
    _, _, loaded, _, calls = revision
    job = slide_revision.begin(loaded, 0, "Explain this result for clinicians")
    assert slide_revision.run(job)[0]
    before = json.loads(job.receipt.read_text(encoding="utf-8"))
    output = archive(revision, tmp_path)
    restored = detached_records(output, tmp_path / "detached", job.request_id)
    assert restored == before
    assert restored["result"]["slides"][0]["title"] == "Retained completed revision"
    assert restored["original"]["slides"][0]["title"] == "Method"
    assert restored["prompt"] and restored["instruction"]
    assert len(restored["figures"]) == 2 and calls == [1]


def test_failed_storage_candidate_and_later_retry_are_distinct_complete_checkpoints(
    revision, tmp_path, monkeypatch
):
    _, _, loaded, _, calls = revision
    job = slide_revision.begin(loaded, 0, "Retain my result")
    with monkeypatch.context() as patch:
        patch.setattr(
            presentations,
            "save_deck",
            lambda *a, **k: (_ for _ in ()).throw(OSError("storage fixture")),
        )
        assert slide_revision.run(job)[0]
    assert job.record["status"] == "candidate"
    candidate_archive = archive(revision, tmp_path, "candidate.zip")
    assert slide_revision.publish(job) == "accepted"
    accepted_archive = archive(revision, tmp_path, "accepted.zip")
    old = detached_records(candidate_archive, tmp_path / "candidate", job.request_id)
    new = detached_records(accepted_archive, tmp_path / "accepted", job.request_id)
    assert old["status"] == "candidate" and new["status"] == "accepted"
    assert old["result"]["slides"] == new["result"]["slides"]
    assert old["instruction"] == new["instruction"] and calls == [1]


def test_stale_candidate_restores_without_overwriting_current_deck(revision, tmp_path, monkeypatch):
    _, _, loaded, _, _ = revision
    job = slide_revision.begin(loaded, 0, "Keep a late revision")
    model = llm.complete_result

    def concurrent(*args, **kwargs):
        changed = presentations.load_deck(LOCAL, "guide")
        changed.title = "Current human deck"
        presentations.save_deck(changed)
        return model(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", concurrent)
    assert slide_revision.run(job)[0] and job.record["status"] == "candidate"
    output = archive(revision, tmp_path)
    target = tmp_path / "detached"
    restored = detached_records(output, target, job.request_id)
    current = next((target / "presentations").glob("*/guide.json"))
    assert json.loads(current.read_text(encoding="utf-8"))["title"] == "Current human deck"
    assert restored["result"]["slides"][0]["title"] == "Retained completed revision"


@pytest.mark.parametrize("broken", ["receipt_png", "artifact_missing", "unknown_legacy"])
def test_incomplete_closure_never_creates_a_misleading_backup(revision, tmp_path, broken):
    _, _, loaded, blob_store, _ = revision
    job = slide_revision.begin(loaded, 0, "Keep all evidence")
    assert slide_revision.run(job)[0]
    if broken == "receipt_png":
        record = json.loads(job.receipt.read_text(encoding="utf-8"))
        record["figures"]["figure:1"]["base64"] = "YmFk"
        job.receipt.write_text(json.dumps(record), encoding="utf-8")
    elif broken == "artifact_missing":
        row = job.record["file_operation"]["payload"]["body"]
        blob_store.verified_path(BlobManifest(row["sha256"], row["size"])).unlink()
    else:
        (job.receipt.parent.parent / "unclassified-notes.txt").write_text(
            "Do not drop me", encoding="utf-8"
        )
    output = tmp_path / "incomplete.zip"
    with pytest.raises((ValueError, OSError)):
        archive(revision, tmp_path, output.name)
    assert not output.exists()


def add_source(revision):
    import pymupdf

    _, client, _, blob_store, _ = revision
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((50, 50), "Original source evidence")
        data = document.tobytes()
    target = BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    blob_store.begin(target)
    blob_store.append(target, 0, data)
    blob_store.finalize(target)
    client.save(
        client.new_graph_operation(
            "paper_document",
            PAPER,
            {
                "paper_id": PAPER,
                "sha256": target.sha256,
                "size": target.size,
                "media_type": "application/pdf",
            },
        )
    )
    return target


@pytest.mark.parametrize("missing", [False, True])
def test_original_pdf_source_is_required_and_retained(revision, tmp_path, missing):
    target = add_source(revision)
    job = slide_revision.begin(presentations.load_deck(LOCAL, "guide"), 0, "Explain the source")
    assert slide_revision.run(job)[0]
    if missing:
        revision[3].verified_path(target).unlink()
        with pytest.raises((ValueError, OSError)):
            archive(revision, tmp_path)
        assert not (tmp_path / "backup.zip").exists()
    else:
        output = archive(revision, tmp_path)
        destination = tmp_path / "detached"
        restored = detached_records(output, destination, job.request_id)
        assert restored["observation"]["desired_document"]["sha256"] == target.sha256
        assert (
            hashlib.sha256((destination / "objects" / target.sha256).read_bytes()).hexdigest()
            == target.sha256
        )


def test_archive_object_replacement_after_initial_inspect_fails_before_publish(
    revision, tmp_path, monkeypatch
):
    job = slide_revision.begin(revision[2], 0, "Keep verified bytes")
    assert slide_revision.run(job)[0]
    output = archive(revision, tmp_path)
    original = recovery.inspect

    def replace_after_check(path):
        result = original(path)
        with zipfile.ZipFile(path) as source:
            entries = {name: source.read(name) for name in source.namelist()}
        name = next(n for n in entries if n.startswith("objects/"))
        entries[name] = b"replacement"
        with zipfile.ZipFile(path, "w") as changed:
            for key, data in entries.items():
                changed.writestr(key, data)
        return result

    monkeypatch.setattr(recovery, "inspect", replace_after_check)
    target = tmp_path / "never-published"
    with pytest.raises(ValueError):
        recovery.restore_detached(output, target)
    assert not target.exists()


def test_same_path_replacement_does_not_claim_old_unbound_receipts(codec, tmp_path, monkeypatch):
    folder = tmp_path / "original"
    folder.mkdir()
    source = folder / "papers.db"
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,year,venue,source) VALUES(?,?,?,?,?,?)",
            (PAPER, "Paper", "paper", 2026, "Venue", "fixture"),
        )
    monkeypatch.setattr(store, "DB_PATH", source)
    monkeypatch.setattr(presentations, "DECK_DIR", folder / "presentations")
    value = codec[0]
    presentations.save_deck(value)
    job = slide_revision.begin(
        presentations.load_deck(PAPER, "guide"), 0, "Keep original workspace"
    )

    def model(*args, **kwargs):
        source.rename(folder / "original-moved.db")
        with closing(sqlite3.connect(source)) as conn, conn:
            conn.executescript(store.SCHEMA)
            store._migrate(conn)
        slide = asdict(value.slides[0])
        slide.update(title="Completed on the original paper", elements=None)
        return Completion(json.dumps({"slide": slide, "summary": "Retained"}))

    monkeypatch.setattr(llm, "complete_result", model)
    assert slide_revision.run(job)[0] and job.record["status"] == "candidate"
    with pytest.raises(ValueError, match="replaced|different"):
        recovery.create(source, tmp_path / "wrong-workspace.zip")
    output = tmp_path / "original.zip"
    recovery.create(folder / "original-moved.db", output)
    restored = detached_records(output, tmp_path / "detached", job.request_id)
    assert restored["status"] == "candidate"
    assert restored["result"]["slides"][0]["title"] == "Completed on the original paper"


def test_unknown_input_identity_stays_unknown_and_exact_evidence_can_be_exported(
    revision, tmp_path
):
    job = slide_revision.begin(revision[2], 0, "Keep original evidence identity")
    assert slide_revision.run(job)[0]
    before = job.record["result"]
    assert before["source_hash"] == ""
    output = archive(revision, tmp_path)
    destination = tmp_path / "detached"
    restored = detached_records(output, destination, job.request_id)
    raw = json.loads(
        next((destination / "presentations").glob("*/guide.json")).read_text(encoding="utf-8")
    )
    for name in ("title", "slides", "sources", "source_hash", "paper_title", "audience", "minutes"):
        assert raw[name] == before[name]
    assert restored == json.loads(job.receipt.read_text(encoding="utf-8"))
    evidence = slides.read_detached_evidence(destination / "papers.db", LOCAL, "guide")
    assert evidence["mapping"]["original_source_hash"] == ""
    assert evidence["historical_input_digest_known"] is False
    assert not evidence["capabilities"]["publish"]
    assert evidence["evidence"]["sources"] == job.record["evidence"]["sources"]
    exported = slides.export_detached_evidence(
        destination / "papers.db", LOCAL, "guide", tmp_path / "evidence.json"
    )
    assert exported.read_bytes() == evidence["bytes"]
    with pytest.raises(FileExistsError):
        slides.export_detached_evidence(destination / "papers.db", LOCAL, "guide", exported)


def test_detached_evidence_lookup_rejects_modified_mapping_or_bytes(revision, tmp_path):
    job = slide_revision.begin(revision[2], 0, "Keep original source")
    assert slide_revision.run(job)[0]
    output = archive(revision, tmp_path)
    destination = tmp_path / "detached"
    detached_records(output, destination, job.request_id)
    mapping_path = next((destination / "presentations").glob("*/recovery-evidence-guide.json"))
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    changed = dict(mapping, path="../outside.json")
    mapping_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        slides.read_detached_evidence(destination / "papers.db", LOCAL, "guide")
    changed = dict(mapping, deck_id="a-different-deck")
    mapping_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="provenance"):
        slides.read_detached_evidence(destination / "papers.db", LOCAL, "guide")
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    asset = mapping_path.parent / "recovered-evidence" / (mapping["asset"]["sha256"] + ".json")
    asset.write_bytes(b"changed")
    with pytest.raises(ValueError, match="size|hash"):
        slides.read_detached_evidence(destination / "papers.db", LOCAL, "guide")


def test_large_private_receipt_uses_blob_closure_not_oversized_sql_row(
    pair, codec, tmp_path, monkeypatch
):
    import struct
    import zlib

    from test_sync_files import png

    source = pair[1].journal.path
    monkeypatch.setattr(presentations, "DECK_DIR", source.parent / "presentations")
    large = {}
    for identity, color in (("figure:1", "red"), ("figure:2", "blue")):
        data = png(color)
        payload = b"Comment\0" + color.encode() + b"x" * (6 * 1024**2)
        chunk = struct.pack(">I", len(payload)) + b"tEXt" + payload
        chunk += struct.pack(">I", zlib.crc32(b"tEXt" + payload) & 0xFFFFFFFF)
        large[identity] = data[:-12] + chunk + data[-12:]
    monkeypatch.setattr(presentations, "figure_bytes", lambda _deck, identity: large[identity])
    save_current(pair, codec[0])
    loaded = presentations.load_deck(LOCAL, "guide")
    slide = asdict(loaded.slides[0])
    slide.update(title="Large retained closure", elements=None)
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **k: Completion(json.dumps({"slide": slide}))
    )
    job = slide_revision.begin(loaded, 0, "Preserve all image metadata")
    assert slide_revision.run(job)[0]
    assert job.receipt.stat().st_size > recovery.MAX_ROW
    with pair[1].journal.transaction() as conn:
        owned_store = paths(conn)[0]
    output = tmp_path / "large.zip"
    manifest = recovery.create(source, output, blob_store=owned_store)
    row = next(row for row in manifest["tables"] if row["name"] == slides.TABLE)
    assert row["size"] < recovery.MAX_ROW
    restored = detached_records(output, tmp_path / "large-detached", job.request_id)
    assert restored == json.loads(job.receipt.read_text(encoding="utf-8"))


def test_available_legacy_pdf_is_adopted_for_backup_without_live_enrollment(
    codec, tmp_path, monkeypatch
):
    """Archive verified source bytes without inventing a live document operation."""
    import pymupdf

    folder = tmp_path / "legacy"
    folder.mkdir()
    source = folder / "papers.db"
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,year,venue,source) VALUES(?,?,?,?,?,?)",
            (PAPER, "Paper", "paper", 2026, "Venue", "fixture"),
        )
    pdf_folder = folder / "pdf"
    pdf_folder.mkdir()
    pdf = pdf_folder / (PAPER + ".pdf")
    with pymupdf.open() as document:
        document.new_page()
        data = document.tobytes()
    pdf.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(store, "DB_PATH", source)
    monkeypatch.setattr(presentations, "DECK_DIR", folder / "presentations")
    value = codec[0]
    value.sources[0]["document_hash"] = digest
    presentations.save_deck(value)
    loaded = presentations.load_deck(PAPER, "guide")
    slide = asdict(loaded.slides[0])
    slide.update(title="Legacy source result", elements=None)
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **k: Completion(json.dumps({"slide": slide}))
    )
    job = slide_revision.begin(loaded, 0, "Preserve the existing PDF")
    assert slide_revision.run(job)[0]
    before = source.read_bytes()
    output = tmp_path / "archive-only-adoption.zip"
    manifest = recovery.create(source, output)
    assert any(row["name"] == "research_legacy_source_recovery" for row in manifest["tables"])
    assert source.read_bytes() == before and pdf.read_bytes() == data
    with closing(sqlite3.connect(source)) as conn:
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name IN "
            "('research_document_desired','research_sync_binding','research_legacy_source_recovery')"
        ).fetchall()
    destination = tmp_path / "adopted-detached"
    restored = detached_records(output, destination, job.request_id)
    assert restored == json.loads(job.receipt.read_text(encoding="utf-8"))
    assert (destination / "objects" / digest).read_bytes() == data
