"""Late raw drafts keep their own byte closure, independent of global workspace."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_sync_files import LOCAL, png
from test_sync_files import codec as codec  # noqa: F401
from test_sync_files import pair as pair  # noqa: F401

from paper_daily import store
from paper_daily import sync_deck_publication as publication
from paper_daily.presentations import figure_bytes as captured_figure_bytes
from paper_daily.sync_files import validate_closure


def late(pair, codec, monkeypatch, *, request_id="raw-draft-one", unused=False):
    _, a, b, _, _, _, _ = pair
    deck = codec[0]
    deck.paper_id = LOCAL
    deck.title = "Late generated scientific explanation"
    deck.slides[0].speaker_notes = "Preserve my full explanation"
    deck._revision_figures = {"figure:1": png("red"), "figure:2": png("blue")}
    if unused:
        deck.figures.append({"id": "figure:3", "label": "Unused but retained", "file": "c.png"})
        import pymupdf

        deck._revision_figures["figure:3"] = pymupdf.Pixmap(
            pymupdf.csRGB, 32, 24, b"\x00\xff\x00" * (32 * 24), False).tobytes("png")
    monkeypatch.setattr("paper_daily.presentations.figure_bytes", captured_figure_bytes)
    observed = publication.observe_deck(LOCAL, "guide")
    deck.source_hash = "private-evidence-tag"
    evidence = {"sources": deck.sources, "coverage": ["Methods"],
                "source_hash": "private-evidence-tag"}
    monkeypatch.setattr(store, "DB_PATH", b.journal.path)
    raw = deck.to_dict()
    with pytest.raises(publication.StaleDeckError) as raised:
        publication.publish_deck(deck, observation=observed, evidence=evidence,
                                 request_id=request_id)
    return a, b, deck, raw, observed, evidence, raised.value.candidate_id


def test_raw_draft_pins_new_images_evidence_and_original_strings_in_original_only(
    pair, codec, monkeypatch
):
    a, b, deck, raw, observed, evidence, identity = late(pair, codec, monkeypatch)
    assert identity == "raw-draft-one"
    with closing(sqlite3.connect(a.journal.path)) as conn:
        conn.row_factory = sqlite3.Row
        saved = dict(conn.execute("SELECT * FROM research_file_drafts").fetchone())
        closure = dict(conn.execute("SELECT * FROM research_file_draft_closures").fetchone())
    assert json.loads(saved["deck"]) == raw
    assert json.loads(saved["observation"]) == observed
    assert closure["candidate_id"] == saved["candidate_id"]
    payload = json.loads(closure["payload"])
    from paper_daily.sync_blobs import BlobManifest
    blob_store = pair[3].store
    body = validate_closure(payload, lambda row: blob_store.verified_path(
        BlobManifest(row["sha256"], row["size"])).read_bytes())
    assert body["deck"]["title"] == raw["title"]
    assert body["deck"]["slides"][0]["speaker_notes"] == "Preserve my full explanation"
    assert body["evidence_asset"] is not None
    assert body["deck"]["source_hash"] == "private-evidence-tag"
    assert payload["source_document_hash"] is None
    assert "profile" not in body["deck"]["generation"]
    with closing(sqlite3.connect(b.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (0,)
    with pytest.raises(publication.StaleDeckError) as retried:
        publication.publish_deck(deck, observation=observed, evidence=evidence,
                                 request_id="raw-draft-one")
    assert retried.value.candidate_id == identity
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM research_file_draft_closures").fetchone() == (1,)


def test_unused_figure_is_also_pinned_without_adding_it_to_slides(pair, codec, monkeypatch):
    a, _, _, raw, _, _, identity = late(pair, codec, monkeypatch, unused=True)
    with closing(sqlite3.connect(a.journal.path)) as conn:
        stored, inventory = conn.execute(
            "SELECT payload,inventory FROM research_file_draft_closures WHERE candidate_id=?",
            (identity,)).fetchone()
    payload, images = json.loads(stored), json.loads(inventory)["images"]
    assert len(raw["figures"]) == 3
    assert {i["id"] for i in images} == {"figure:1", "figure:2", "figure:3"}
    assert {a["id"] for a in payload["assets"] if a["role"] == "figure"} == {
        "figure:1", "figure:2"}
    assert json.loads(stored)["source_document_hash"] is None


def test_changed_request_content_cannot_overwrite_retained_draft(pair, codec, monkeypatch):
    a, _, deck, raw, observed, evidence, _ = late(pair, codec, monkeypatch)
    deck.title = "Different output with a reused request ID"
    pending = a.journal.pending()
    with pytest.raises(ValueError, match="reused"):
        publication.publish_deck(deck, observation=observed, evidence=evidence,
                                 request_id="raw-draft-one")
    assert a.journal.pending() == pending
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert json.loads(conn.execute(
            "SELECT deck FROM research_file_drafts").fetchone()[0]) == raw
        assert conn.execute("SELECT count(*) FROM research_file_draft_closures").fetchone() == (1,)


def test_auxiliary_write_failure_rolls_back_raw_and_closure_then_exact_retry(
    pair, codec, monkeypatch
):
    from paper_daily import raw_deck_closure as closure
    a = pair[1]
    real_schema = closure._schema
    def fail(conn, *, create=False):
        real_schema(conn, create=create)
        if create:
            conn.execute("CREATE TRIGGER refuse_closure BEFORE INSERT ON "
                         "research_file_draft_closures BEGIN "
                         "SELECT RAISE(ABORT,'closure failure'); END")
    monkeypatch.setattr(closure, "_schema", fail)
    with pytest.raises(sqlite3.IntegrityError, match="closure failure"):
        late(pair, codec, monkeypatch)
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (0,)
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (closure.TABLE,)).fetchone()
    monkeypatch.setattr(closure, "_schema", real_schema)
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    late(pair, codec, monkeypatch)
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM research_file_draft_closures").fetchone() == (1,)


def test_restarted_raw_draft_review_preserves_original_and_publishes_once(pair, codec, monkeypatch):
    from paper_daily import presentations
    from paper_daily.research_review import ResearchReview
    a, _, _, raw, _, _, identity = late(pair, codec, monkeypatch)
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    review = ResearchReview(a.journal.path)
    item = next(item for item in review.page()["items"] if item["origin"] == "file_draft")
    assert item["id"] == identity
    initial = review.preview("file_draft", identity)
    assert not initial.data["apply"]
    from pathlib import Path
    with closing(sqlite3.connect(a.journal.path)) as conn:
        version_root = Path(conn.execute(
            "SELECT version_root FROM research_file_paths WHERE id=1").fetchone()[0])
    assert not version_root.exists()
    preview = review.prepare_file(initial)
    assert not version_root.exists()
    assert preview.data["apply"] and not preview.data["editable"]
    assert preview.data["retained"]["title"] == raw["title"]
    pending = a.journal.pending()
    result = review.decide(preview, request_id="review-raw-one", confirm_target=True)
    assert len(a.journal.pending()) == len(pending) + 1
    loaded = presentations.load_deck(LOCAL, "guide")
    assert loaded.title == raw["title"]
    assert loaded.slides[0].speaker_notes == "Preserve my full explanation"
    assert presentations.figure_bytes(loaded, "figure:1") == png("red")
    assert presentations.figure_bytes(loaded, "figure:2") == png("blue")
    assert review.decide(preview, request_id="review-raw-one", confirm_target=True) == result
    assert len(a.journal.pending()) == len(pending) + 1
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert json.loads(conn.execute(
            "SELECT deck FROM research_file_drafts").fetchone()[0]) == raw


def test_complete_backup_detached_reader_retains_raw_notes_all_images_and_evidence(
    pair, codec, monkeypatch, tmp_path
):
    from test_sync_recovery import archive_rows

    from paper_daily import raw_deck_closure as closure
    from paper_daily import sync_recovery
    a, _, _, raw, _, _, identity = late(pair, codec, monkeypatch, unused=True)
    package = tmp_path / "complete.zip"
    manifest = sync_recovery.create(a.journal.path, package, blob_store=pair[3].store)
    assert sync_recovery.inspect(package) == manifest
    saved = archive_rows(package, "research_file_drafts")[0]
    assets = archive_rows(package, closure.TABLE)[0]
    assert json.loads(saved["deck"]) == raw
    assert assets["candidate_id"] == identity
    destination = tmp_path / "detached"
    sync_recovery.restore_detached(package, destination)
    read = closure.read_detached(destination / "papers.db", identity)
    assert read["deck"]["title"] == raw["title"]
    assert read["deck"]["slides"][0]["speaker_notes"] == "Preserve my full explanation"
    assert len(read["images"]) == 3
    assert read["publish"] is False and read["sync"] is False
    assert read["requires_explicit_review"] is True
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?",
                                (closure.TABLE,)).fetchone()
        recovered = json.loads(conn.execute("SELECT data FROM recovery_records WHERE table_name=?",
                                           (closure.TABLE,)).fetchone()[0])
        assert recovered == assets


@pytest.mark.parametrize("change", ["evidence", "captured_image"])
def test_reused_raw_request_rejects_changed_scientific_inputs(pair, codec, monkeypatch, change):
    a, _, deck, _, observed, evidence, _ = late(pair, codec, monkeypatch)
    if change == "evidence":
        evidence = dict(evidence, coverage=["Different interpretation"])
    else:
        deck._revision_figures["figure:1"] = png("blue")
    pending = a.journal.pending()
    with pytest.raises(ValueError, match="reused|different"):
        publication.publish_deck(deck, observation=observed, evidence=evidence,
                                 request_id="raw-draft-one")
    assert a.journal.pending() == pending
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM research_file_draft_closures").fetchone() == (1,)


def test_simultaneous_raw_request_retention_is_atomic_and_idempotent(pair, codec, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from paper_daily import raw_deck_closure as closure
    a, b, deck = pair[1], pair[2], codec[0]
    deck.paper_id = LOCAL
    deck._revision_figures = {"figure:1": png("red"), "figure:2": png("blue")}
    monkeypatch.setattr("paper_daily.presentations.figure_bytes", captured_figure_bytes)
    observed = publication.observe_deck(LOCAL, "guide")
    monkeypatch.setattr(store, "DB_PATH", b.journal.path)
    barrier = threading.Barrier(2)
    encode = closure._encode
    def simultaneous(*args):
        result = encode(*args)
        barrier.wait(timeout=4)
        return result
    monkeypatch.setattr(closure, "_encode", simultaneous)
    def save():
        with pytest.raises(publication.StaleDeckError) as raised:
            publication.publish_deck(deck, observation=observed, request_id="simultaneous-raw")
        return raised.value.candidate_id
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda _: save(), range(2))) == ["simultaneous-raw"] * 2
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM research_file_draft_closures").fetchone() == (1,)


@pytest.mark.parametrize("change", ["payload", "inventory", "unused_bytes", "closed"])
def test_prepared_raw_closure_changes_cannot_publish(pair, codec, monkeypatch, change):
    from paper_daily.research_review import ResearchReview
    from paper_daily.sync_blobs import BlobManifest
    a, _, _, _, _, _, identity = late(pair, codec, monkeypatch, unused=True)
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    review = ResearchReview(a.journal.path)
    preview = review.prepare_file(review.preview("file_draft", identity))
    pending = a.journal.pending()
    if change == "closed":
        review.close()
    elif change == "unused_bytes":
        with closing(sqlite3.connect(a.journal.path)) as conn:
            inventory = json.loads(conn.execute(
                "SELECT inventory FROM research_file_draft_closures").fetchone()[0])
        image = next(i for i in inventory["images"] if i["id"] == "figure:3")
        pair[3].store.verified_path(BlobManifest(image["sha256"], image["size"])).unlink()
    else:
        with closing(sqlite3.connect(a.journal.path)) as conn, conn:
            row = json.loads(conn.execute(
                "SELECT " + change + " FROM research_file_draft_closures").fetchone()[0])
            if change == "payload":
                row["source_document_hash"] = "a" * 64
            else:
                row["images"][-1].update(row["images"][0], id="figure:3")
            conn.execute("UPDATE research_file_draft_closures SET " + change + "=?",
                         (publication.canonical_json(row).decode(),))
    with pytest.raises((ValueError, OSError)):
        review.decide(preview, request_id="reject-raw-change", confirm_target=True)
    assert a.journal.pending() == pending
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone() == (0,)


@pytest.mark.parametrize("change", ["raw_changed", "orphan", "unused_missing"])
def test_complete_backup_refuses_incomplete_or_mismatched_raw_closure(
    pair, codec, monkeypatch, tmp_path, change
):
    from paper_daily import sync_recovery
    from paper_daily.sync_blobs import BlobManifest
    a, _, _, _, _, _, _ = late(pair, codec, monkeypatch, unused=True)
    if change == "unused_missing":
        with closing(sqlite3.connect(a.journal.path)) as conn:
            image = json.loads(conn.execute(
                "SELECT inventory FROM research_file_draft_closures").fetchone()[0])["images"][-1]
        pair[3].store.verified_path(BlobManifest(image["sha256"], image["size"])).unlink()
    else:
        with closing(sqlite3.connect(a.journal.path)) as conn, conn:
            if change == "orphan":
                conn.execute("DELETE FROM research_file_drafts")
            else:
                raw = json.loads(conn.execute(
                    "SELECT deck FROM research_file_drafts").fetchone()[0])
                raw["title"] = "A changed scientific draft"
                conn.execute("UPDATE research_file_drafts SET deck=?", (json.dumps(raw),))
    package = tmp_path / "must-not-publish.zip"
    pending = a.journal.pending()
    with pytest.raises((ValueError, OSError)):
        sync_recovery.create(a.journal.path, package, blob_store=pair[3].store)
    assert not package.exists()
    assert a.journal.pending() == pending
