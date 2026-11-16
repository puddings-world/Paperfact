"""Included package bytes repair private availability before observed import."""

import hashlib
import zipfile

import pytest
from test_package_import import importer as importer
from test_package_import import package as package
from test_package_import import rich_package as rich_package
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import presentations, store
from paper_daily.document_reader import from_workspace
from paper_daily.sync_artifacts import stage_bytes
from paper_daily.sync_blobs import BlobError, BlobManifest, BlobStore


@pytest.mark.parametrize("part", ["primary", "figure"])
def test_reviewed_package_supplies_missing_cached_bytes_and_keeps_import_retry(
    rich_package, importer, monkeypatch, part
):
    service, client = importer
    archive = rich_package[0]
    name = "files/pdf/ref_example.pdf" if part == "primary" else "files/figures/ref_example/a.png"
    with zipfile.ZipFile(archive) as z:
        data = z.read(name)
    manifest = BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    stage_bytes(service.store, {manifest.sha256: data})
    service.store._path(manifest).unlink()
    before = client.journal.pending(1000)
    prepared = service.prepare(archive, request_id="repair-import")
    assert client.journal.pending(1000) == before
    with client.journal.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0
    assert service.store.verified_path(manifest).read_bytes() == data
    report = service.apply(prepared)
    local = report["identity_mapping"]["ref:example"]["local_id"]
    document = from_workspace(service.database).resolve(local)
    assert document.available and document.sha256 == rich_package[1]
    with client.journal.transaction() as conn:
        assert (
            conn.execute("SELECT body FROM notes WHERE paper_id=?", (local,)).fetchone()[0]
            == "Personal note"
        )
    monkeypatch.setattr(store, "DB_PATH", service.database)
    deck = presentations.load_deck(local, "guide")
    assert deck.slides[0].speaker_notes == "Speaker explanation"
    assert deck.slides[0].elements[2]["text"] == "Editable"
    assert presentations.figure_bytes(deck, "figure:1")
    pending = client.journal.pending(1000)
    assert service.apply(service.prepare(archive, request_id="repair-import"))["replayed"]
    assert client.journal.pending(1000) == pending


def test_explicit_byte_staging_requires_exact_source_and_keeps_corrupt_final(tmp_path):
    storage = BlobStore(tmp_path / "blobs")
    data = b"known original content"
    digest = hashlib.sha256(data).hexdigest()
    manifest = BlobManifest(digest, len(data))
    stage_bytes(storage, {digest: data})
    path = storage._path(manifest)
    path.unlink()
    with pytest.raises(BlobError, match="missing"):
        stage_bytes(storage, {digest: data})
    with pytest.raises(BlobError, match="source"):
        stage_bytes(storage, {digest: b"x" * len(data)}, restore_missing=True)
    assert not path.exists()
    stage_bytes(storage, {digest: data}, restore_missing=True)
    assert path.read_bytes() == data
    path.write_bytes(b"damaged finalized object")
    with pytest.raises(BlobError):
        stage_bytes(storage, {digest: data}, restore_missing=True)
    assert path.read_bytes() == b"damaged finalized object"
