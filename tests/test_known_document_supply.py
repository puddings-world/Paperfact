"""Offline exact-byte supply retains original versions and stored research."""

import hashlib
from uuid import uuid4

import pytest
from test_legacy_primary_migration import make as make
from test_legacy_primary_migration import pdf
from test_native_pdf_downloads import setup, state
from test_native_primary_publication import enrolled

from paper_daily import cli, repdf, store
from paper_daily import known_document_supply as supply
from paper_daily import native_primary_publication as native
from paper_daily.document_reader import from_workspace
from paper_daily.sync_blobs import (
    BlobError,
    BlobManifest,
    BlobQuotaError,
    BlobSourceMismatch,
    BlobStore,
)
from paper_daily.sync_document_actions import stage_file
from paper_daily.workspace_service import Cancelled, Ticket, WorkspaceChanged


def missing(make, monkeypatch, *, unbound=False):
    if unbound:
        fixture = setup(make, monkeypatch)
        chosen = fixture.root / "known.pdf"
        chosen.write_bytes(fixture.bytes)
        manifest = stage_file(fixture.blobs, chosen)
        fixture.actions.attach_document(
            fixture.portable,
            manifest,
            store=fixture.blobs,
            request_id=str(uuid4()),
        )
    else:
        fixture = enrolled(make)
        chosen = fixture.path
        current = state(fixture)["desired"]
        manifest = BlobManifest(current["sha256"], current["size"])
    fixture.blobs._path(manifest).unlink()
    return fixture, chosen, manifest


@pytest.mark.parametrize("unbound", [False, True])
def test_exact_supply_restores_known_bytes_without_new_version_or_outbox(
    make, monkeypatch, unbound
):
    fixture, chosen, manifest = missing(make, monkeypatch, unbound=unbound)
    before = state(fixture)
    original = before["desired"]
    prepared = supply.prepare(native.observe(fixture.database, "paper"), chosen)
    result = supply.run(prepared)
    after = state(fixture)
    assert result["operation_id"] == original["operation_id"]
    assert after["desired"] == after["applied"] == original
    assert after["operations"] == before["operations"]
    assert len(after["receipts"]) == len(before["receipts"]) + 1
    document = from_workspace(fixture.database).resolve("paper")
    assert document.sha256 == manifest.sha256 and document.path.read_bytes() == chosen.read_bytes()
    assert supply.run(prepared) == result
    assert state(fixture) == after


def test_wrong_local_file_does_not_touch_cache_or_research(make, monkeypatch):
    fixture, chosen, manifest = missing(make, monkeypatch)
    before = state(fixture)
    wrong = fixture.root / "wrong.pdf"
    pdf(wrong, "Different original")
    usage = fixture.blobs.usage()
    with pytest.raises(BlobSourceMismatch):
        supply.prepare(native.observe(fixture.database, "paper"), wrong)
    assert state(fixture) == before and fixture.blobs.usage() == usage
    assert not fixture.blobs._path(manifest).exists()
    assert not list((fixture.blobs.root / "partial").glob("*.supply"))


def test_source_change_after_preparation_cannot_bind_or_revive_old_original(make, monkeypatch):
    fixture, chosen, manifest = missing(make, monkeypatch, unbound=True)
    prepared = supply.prepare(native.observe(fixture.database, "paper"), chosen)
    other = fixture.root / "other.pdf"
    pdf(other, "Newer original")
    native.run(native.prepare(native.observe(fixture.database, "paper"), other))
    before = state(fixture)
    with pytest.raises(ValueError, match="changed"):
        supply.run(prepared)
    assert state(fixture) == before
    assert fixture.blobs.verified_path(manifest).read_bytes() == chosen.read_bytes()


def test_cancel_before_binding_keeps_cache_but_not_a_new_reader_binding(make, monkeypatch):
    fixture, chosen, manifest = missing(make, monkeypatch, unbound=True)
    before = state(fixture)
    ticket = Ticket()
    source = native.observe(fixture.database, "paper", ticket=ticket)
    prepared = supply.prepare(source, chosen)
    ticket.cancel()
    with pytest.raises(Cancelled):
        supply.run(prepared)
    assert state(fixture) == before and fixture.blobs.available(manifest)


def test_binding_failure_rolls_back_receipt_and_failure_cache(make, monkeypatch):
    fixture, chosen, manifest = missing(make, monkeypatch, unbound=True)
    before = state(fixture)
    prepared = supply.prepare(native.observe(fixture.database, "paper"), chosen)

    def fail(*args):
        raise ValueError("Synthetic bind refusal")

    monkeypatch.setattr(supply, "bind_verified_document", fail)
    with pytest.raises(ValueError, match="Synthetic"):
        supply.run(prepared)
    assert state(fixture) == before and fixture.blobs.available(manifest)


def test_retirement_is_not_missing_bytes(make, monkeypatch):
    fixture, chosen, manifest = missing(make, monkeypatch)
    operation = fixture.client.new_graph_operation(
        "paper_document",
        fixture.portable,
        {},
        action="delete",
    )
    fixture.client.journal.apply(operation, fixture.client.writer)
    with pytest.raises(supply.NoKnownOriginal):
        supply.prepare(native.observe(fixture.database, "paper"), chosen)
    assert not fixture.blobs.available(manifest)


def test_retry_does_not_clear_a_later_analysis_failure(make, monkeypatch):
    fixture, chosen, _ = missing(make, monkeypatch)
    prepared = supply.prepare(native.observe(fixture.database, "paper"), chosen)
    result = supply.run(prepared)
    with store.connect() as conn:
        store.set_kv(conn, "analyze.failed.pdf.paper", "later analysis failure")
    assert supply.run(prepared) == result
    assert state(fixture)["failure"] == "later analysis failure"


def test_cli_intake_and_explicit_pdf_supply_repair_known_original_without_version_change(
    make, monkeypatch
):
    fixture, chosen, manifest = missing(make, monkeypatch)
    monkeypatch.setattr(repdf, "PDF_DIR", fixture.path.parent)
    before = state(fixture)
    assert cli._attach_pdf(dict(added=0, paper_ids=[], already=["paper"]), str(chosen))
    assert state(fixture)["desired"] == before["desired"]
    assert state(fixture)["operations"] == before["operations"]
    fixture.blobs._path(manifest).unlink()
    assert repdf.replace("paper", file=str(chosen), log=lambda _: None)
    assert state(fixture)["desired"] == before["desired"]
    assert state(fixture)["operations"] == before["operations"]


def test_explicit_blob_supply_restores_missing_final_but_preserves_corrupt_final(tmp_path):
    data = b"known immutable content"

    manifest = BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    blobs = BlobStore(tmp_path / "blobs", quota_bytes=len(data))
    chosen = tmp_path / "chosen.bin"
    chosen.write_bytes(data)
    path = blobs.import_file(manifest, chosen)
    assert path.read_bytes() == data
    path.unlink()
    with pytest.raises(BlobError, match="restore it explicitly"):
        blobs.begin(manifest)
    assert blobs.import_file(manifest, chosen).read_bytes() == data
    assert blobs.usage()["reserved_bytes"] == len(data)
    path.write_bytes(b"damaged")
    with pytest.raises(BlobError):
        blobs.import_file(manifest, chosen)
    assert path.read_bytes() == b"damaged"


def test_blob_restore_cancel_is_bounded_and_does_not_publish(tmp_path):

    data = b"x" * 1024
    manifest = BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    blobs = BlobStore(tmp_path / "blobs")
    chosen = tmp_path / "known.bin"
    chosen.write_bytes(data)
    calls = []

    def cancel():
        calls.append(1)
        if len(calls) == 3:
            raise Cancelled()

    with pytest.raises(Cancelled):
        blobs.import_file(manifest, chosen, check=cancel)
    assert not blobs.available(manifest) and blobs.usage()["reserved_bytes"] == 0
    assert not list((blobs.root / "partial").glob("*.supply"))


def test_pending_supply_cannot_bind_after_caller_or_workspace_changes(make, monkeypatch):
    fixture, chosen, manifest = missing(make, monkeypatch, unbound=True)
    active = [True]
    source = native.observe(fixture.database, "paper", current=lambda: active[0])
    before = state(fixture)
    prepared = supply.prepare(source, chosen)
    active[0] = False
    with pytest.raises(ValueError, match="lifetime changed"):
        supply.run(prepared)
    assert state(fixture) == before and fixture.blobs.available(manifest)


def test_metadata_edit_does_not_relabel_or_block_the_same_known_original(make, monkeypatch):
    fixture, chosen, _ = missing(make, monkeypatch, unbound=True)
    prepared = supply.prepare(native.observe(fixture.database, "paper"), chosen)
    with store.connect() as conn:
        conn.execute("UPDATE papers SET title='Curated title' WHERE id='paper'")
    before = state(fixture)
    supply.run(prepared)
    assert state(fixture)["operations"] == before["operations"]
    with store.connect() as conn:
        assert conn.execute("SELECT title FROM papers WHERE id='paper'").fetchone()[0] == (
            "Curated title"
        )


def test_changed_cache_after_verification_cannot_create_a_reader_binding(make, monkeypatch):
    fixture, chosen, manifest = missing(make, monkeypatch, unbound=True)
    before = state(fixture)
    prepared = supply.prepare(native.observe(fixture.database, "paper"), chosen)
    fixture.blobs._path(manifest).write_bytes(b"damaged after verification")
    with pytest.raises(ValueError, match="Verified original changed"):
        supply.run(prepared)
    assert state(fixture) == before


def test_explicit_retired_replacement_can_reuse_missing_historical_bytes(make, monkeypatch):
    fixture, chosen, manifest = missing(make, monkeypatch)
    original = state(fixture)["desired"]
    operation = fixture.client.new_graph_operation(
        "paper_document",
        fixture.portable,
        {},
        action="delete",
    )
    fixture.client.journal.apply(operation, fixture.client.writer)
    monkeypatch.setattr(repdf, "PDF_DIR", fixture.path.parent)
    assert repdf.replace("paper", file=str(chosen), log=lambda _: None)
    restored = state(fixture)["desired"]
    assert restored["operation_id"] != original["operation_id"]
    assert restored["incarnation"] != original["incarnation"]
    assert restored["sha256"] == manifest.sha256
    assert state(fixture)["applied"] == restored


def test_local_blob_supply_checks_quota_before_copying(tmp_path):

    data = b"known large content"
    manifest = BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    blobs = BlobStore(tmp_path / "blobs", quota_bytes=1)
    chosen = tmp_path / "known.bin"
    chosen.write_bytes(data)
    with pytest.raises(BlobQuotaError):
        blobs.import_file(manifest, chosen)
    assert not blobs.available(manifest) and blobs.usage()["reserved_bytes"] == 0
    assert not list((blobs.root / "partial").iterdir())


def test_explicit_legacy_conversion_can_restore_missing_identical_cache_bytes(make):
    from paper_daily import legacy_primary_migration as migration

    fixture = make()
    manifest = stage_file(fixture.blobs, fixture.path)
    fixture.blobs._path(manifest).unlink()
    prepared = migration.prepare(
        fixture.actions,
        fixture.document,
        fixture.blobs,
        request_id=str(uuid4()),
    )
    result = migration.run(prepared)
    assert result["status"] == "migrated"
    assert fixture.blobs.verified_path(manifest).read_bytes() == fixture.bytes
    assert from_workspace(fixture.database).resolve("paper").sha256 == manifest.sha256


def test_url_supply_of_exact_known_bytes_keeps_original_version(make, monkeypatch):
    fixture, chosen, manifest = missing(make, monkeypatch)
    monkeypatch.setattr(repdf, "PDF_DIR", fixture.path.parent)
    before = state(fixture)
    monkeypatch.setattr(repdf.fetch, "fetch", lambda *a, **k: chosen.read_bytes())
    logs = []
    assert repdf.replace("paper", "https://fixture.invalid/original.pdf", log=logs.append)
    assert state(fixture)["desired"] == before["desired"]
    assert state(fixture)["operations"] == before["operations"]
    assert "version and citations retained" in logs[-1]
    assert fixture.blobs.verified_path(manifest).read_bytes() == chosen.read_bytes()


def test_interrupted_local_copy_retains_one_bounded_resumable_reservation(tmp_path):
    data = b"x" * (1024**2 + 1024)
    manifest = BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    blobs = BlobStore(tmp_path / "blobs", quota_bytes=len(data))
    chosen = tmp_path / "known.bin"
    chosen.write_bytes(data)
    partial = blobs._path(manifest, partial=True)

    def interrupt():
        if partial.exists() and partial.stat().st_size >= 1024**2:
            raise Cancelled()

    with pytest.raises(Cancelled):
        blobs.import_file(manifest, chosen, check=interrupt)
    assert not blobs.available(manifest)
    assert blobs.usage()["reserved_bytes"] == len(data)
    assert blobs.begin(manifest) == {"offset": 1024**2, "complete": False}
    assert blobs.import_file(manifest, chosen).read_bytes() == data
    assert blobs.usage()["reserved_bytes"] == len(data)
    assert not list((blobs.root / "partial").iterdir())


def test_supply_never_truncates_or_deletes_its_selected_partial_source(tmp_path):
    data = b"known immutable bytes"
    manifest = BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    blobs = BlobStore(tmp_path / "blobs")
    blobs.begin(manifest)
    blobs.append(manifest, 0, data)
    partial = blobs._path(manifest, partial=True)
    with pytest.raises(BlobError, match="external file"):
        blobs.import_file(manifest, partial)
    assert partial.read_bytes() == data and not blobs.available(manifest)


@pytest.mark.parametrize("phase", ["source", "staged", "cached"])
@pytest.mark.parametrize("failure", [Cancelled, WorkspaceChanged])
def test_local_supply_hashing_stops_at_first_chunk_and_retries(
    tmp_path, monkeypatch, phase, failure,
):
    from contextlib import contextmanager
    from pathlib import Path

    data = b"x" * (3 * 1024**2 + 17)
    manifest = BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    blobs = BlobStore(tmp_path / "blobs", quota_bytes=len(data))
    chosen = tmp_path / "known.bin"
    chosen.write_bytes(data)
    final = blobs._path(manifest)
    part = blobs._path(manifest, partial=True)
    if phase == "cached":
        blobs.import_file(manifest, chosen)
    watched = {"source": chosen, "staged": part, "cached": final}[phase]
    original = Path.open
    read_bytes = []

    @contextmanager
    def tracking(path, mode="r", *args, **kwargs):
        with original(path, mode, *args, **kwargs) as stream:
            class Reader:
                def read(self, size):
                    value = stream.read(size)
                    read_bytes.append(len(value))
                    return value
            yield Reader()

    def opened(path, mode="r", *args, **kwargs):
        if path == watched and mode == "rb":
            return tracking(path, mode, *args, **kwargs)
        return original(path, mode, *args, **kwargs)

    def check():
        if sum(read_bytes) >= 1024**2:
            raise failure("Synthetic cancelled or replaced workspace")

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(failure):
        blobs.import_file(manifest, chosen, check=check)
    assert sum(read_bytes) == 1024**2
    monkeypatch.setattr(Path, "open", original)
    assert chosen.read_bytes() == data
    if phase == "source":
        assert blobs.usage()["reserved_bytes"] == 0
        assert not final.exists() and not part.exists()
    elif phase == "staged":
        assert not final.exists() and part.read_bytes() == data
        assert blobs.begin(manifest) == {"offset": len(data), "complete": False}
    else:
        assert final.read_bytes() == data
        assert blobs.begin(manifest) == {"offset": len(data), "complete": True}
    assert blobs.import_file(manifest, chosen).read_bytes() == data
    assert blobs.usage()["objects"] == 1
