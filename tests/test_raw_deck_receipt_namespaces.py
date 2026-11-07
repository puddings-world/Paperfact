"""Independent research databases can share a parent without sharing receipts."""

import copy
import hashlib
import json
import sqlite3
from contextlib import closing

import pymupdf
import pytest
from test_raw_deck_receipts import codec as _codec
from test_raw_deck_receipts import no_external as _no_external
from test_raw_deck_receipts import original as _original

from paper_daily import raw_deck_closure as raw
from paper_daily import raw_deck_receipts as receipts
from paper_daily import store, sync_recovery
from paper_daily import sync_deck_publication as publication
from paper_daily.sync_blobs import BlobStore

codec = _codec
no_external = _no_external
original = _original


@pytest.fixture
def owners(original, monkeypatch):
    a, b, fa, deck_a, images_a, evidence_a, observation_a = original

    def refuse_primary(*_args, **_kwargs):
        raise OSError("Primary writes are unavailable; owned receipt must preserve the result")

    monkeypatch.setattr(BlobStore, "begin", refuse_primary)
    first = raw.retain_outcome(
        observation_a, deck_a, evidence=evidence_a, request_id="same-request"
    )
    monkeypatch.setattr(store, "DB_PATH", b.journal.path)
    deck_b = copy.deepcopy(deck_a)
    deck_b.slides[0].speaker_notes = "Different B evidence and explanation"
    images_b = {}
    for n, rgb in enumerate((b"\x21\x61\xa1", b"\x41\x81\xc1", b"\x71\xb1\xf1"), 1):
        images_b[f"figure:{n}"] = pymupdf.Pixmap(
            pymupdf.csRGB, 32, 24, rgb * (32 * 24), False
        ).tobytes("png")
    deck_b._revision_figures = images_b
    evidence_b = copy.deepcopy(evidence_a)
    evidence_b["coverage"] = ["Different B study material"]
    evidence_b["source_hash"] = hashlib.sha256(b"B captured evidence").hexdigest()
    deck_b.source_hash = evidence_b["source_hash"]
    observation_b = publication.observe_deck(deck_b.paper_id, deck_b.mode)
    second = raw.retain_outcome(
        observation_b, deck_b, evidence=evidence_b, request_id=first.candidate_id
    )
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    with closing(sqlite3.connect(b.journal.path)) as conn:
        fb, _registration = raw._storage(conn)
    assert first.durable and second.durable and first.state == second.state == "receipt"
    assert a.journal.path.parent == b.journal.path.parent
    return a, b, fa.store, fb, first, second, images_a, images_b, evidence_a, evidence_b


def own_record(database):
    with closing(sqlite3.connect(database)) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute("SELECT * FROM research_file_drafts").fetchone())


def owned_file(database, result):
    with closing(sqlite3.connect(database)) as conn:
        header, _objects, _files = receipts.read_owned(conn, own_record(database))
    return receipts.location(header["owner"], result.candidate_id)


def archive(database, blob_store, destination):
    manifest = sync_recovery.create(database, destination, blob_store=blob_store)
    assert sync_recovery.inspect(destination) == manifest
    return manifest


def test_same_parent_same_candidate_distinct_owners_each_backup_only_their_exact_result(
    owners, tmp_path
):
    a, b, fa, fb, first, second, images_a, images_b, evidence_a, evidence_b = owners
    assert first.candidate_id == second.candidate_id and images_a != images_b
    for name, client, blobs, result, images, evidence in (
        ("a", a, fa, first, images_a, evidence_a),
        ("b", b, fb, second, images_b, evidence_b),
    ):
        path = tmp_path / (name + ".zip")
        manifest = archive(client.journal.path, blobs, path)
        table = next(row for row in manifest["tables"] if row["name"] == receipts.TABLE)
        assert table["count"] == 1
        target = tmp_path / (name + "-detached")
        sync_recovery.restore_detached(path, target)
        recovered = receipts.read_detached(target / "papers.db", result.candidate_id)
        assert recovered["image_bytes"] == images
        assert recovered["evidence"] == evidence
        assert json.loads(recovered["raw"]["deck"]) == result.deck.to_dict()
        assert not recovered["publish"] and not recovered["sync"]
        assert recovered["requires_explicit_review"]


@pytest.mark.parametrize("damage", ["malformed", "oversized", "excess-count"])
def test_foreign_owner_damage_does_not_block_current_backup_or_new_retention(
    owners, original, monkeypatch, tmp_path, damage
):
    a, b, fa, fb, first, second, images_a, _images_b, evidence_a, _evidence_b = owners
    foreign = owned_file(b.journal.path, second)
    if damage == "malformed":
        foreign.write_bytes(b"{broken JSON")
    elif damage == "oversized":
        with foreign.open("wb") as stream:
            stream.truncate(receipts.MAX_RECEIPT + 1)
    else:
        for n in range(receipts.MAX_RECEIPTS):
            (foreign.parent / (hashlib.sha256(str(n).encode()).hexdigest() + ".json")).write_bytes(
                b"{}"
            )
    manifest = archive(a.journal.path, fa, tmp_path / "a-only.zip")
    assert next(row for row in manifest["tables"] if row["name"] == receipts.TABLE)["count"] == 1
    a_client, _b_client, _fa, deck_a, _images, _evidence, observation_a = original
    next_result = raw.retain_outcome(
        observation_a, deck_a, evidence=evidence_a, request_id="second-a-request"
    )
    assert next_result.durable and next_result.state == "receipt"
    assert next_result.candidate_id != first.candidate_id
    with closing(sqlite3.connect(a.journal.path)) as conn:
        kept, objects, _proof = receipts.read_owned(conn, own_record(a.journal.path))
    assert kept["evidence"] == evidence_a
    assert all(objects[hashlib.sha256(data).hexdigest()] == data for data in images_a.values())
    with pytest.raises(ValueError):
        archive(b.journal.path, fb, tmp_path / "b-must-refuse.zip")
    assert a_client is a


def test_changed_current_binding_never_adopts_the_old_or_other_namespace(owners, tmp_path):
    a, _b, fa, _fb, first, _second, _images_a, _images_b, _ea, _eb = owners
    saved = own_record(a.journal.path)
    original_path = owned_file(a.journal.path, first)
    before = original_path.read_bytes()
    with closing(sqlite3.connect(a.journal.path)) as conn, conn:
        conn.execute("UPDATE research_sync_binding SET origin='new-incarnation-device'")
    with closing(sqlite3.connect(a.journal.path)) as conn, pytest.raises(ValueError):
        receipts.read_owned(conn, saved)
    with pytest.raises(ValueError):
        archive(a.journal.path, fa, tmp_path / "must-refuse.zip")
    assert original_path.read_bytes() == before


def test_unbound_database_with_no_receipts_does_not_enroll_or_read_neighbor_namespaces(
    owners, tmp_path
):
    database = tmp_path / "unbound.sqlite"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        before = conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
    manifest = sync_recovery.create(database, tmp_path / "unbound.zip")
    assert manifest["workspace_id"] is None and manifest["origin_device_id"] is None
    assert receipts.TABLE not in {table["name"] for table in manifest["tables"]}
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        assert conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall() == before
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_sync_binding'"
        ).fetchone()
