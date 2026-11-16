"""Explicit replacement preserves old originals and rejects delayed stale writes."""

import json
from contextlib import closing
from pathlib import Path

import pytest
from test_legacy_primary_migration import make as make
from test_legacy_primary_migration import pdf

from paper_daily import legacy_primary_migration as legacy
from paper_daily import native_primary_publication as native
from paper_daily import repdf, store
from paper_daily.document_reader import from_workspace, register_document_paths
from paper_daily.sync_blobs import BlobManifest
from paper_daily.sync_documents import applied_document
from paper_daily.workspace_service import Cancelled, Ticket


def enrolled(make):
    fixture = make()
    legacy.run(legacy.prepare(
        fixture.actions, fixture.document, fixture.blobs,
        request_id="324e334b-80cd-49b7-af8f-e72c27880b28",
    ))
    return fixture


def current(fixture):
    with closing(native._read(fixture.database)) as conn:
        return applied_document(conn, fixture.portable)


def selected(fixture, name="new.pdf"):
    path = fixture.root / name
    pdf(path, "New original " + name)
    return path


def test_replace_and_exact_retry_keep_prior_original_and_alias(make):
    fixture = enrolled(make)
    old = current(fixture)
    anchor = '{"p0":0,"o0":0,"p1":0,"o1":3}'
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at,kind,page,anchor) VALUES(?,?,?,?,?,?)",
            ("paper", "> prior original passage", "2026-11-16T00:00:00Z", "note", 1, anchor),
        )
    alias = fixture.path.read_bytes()
    source = native.observe(fixture.database, "paper")
    prepared = native.prepare(source, selected(fixture))
    result = native.run(prepared)
    assert native.run(prepared) == result
    assert current(fixture)["operation_id"] == result["operation_id"]
    assert current(fixture)["sha256"] != old["sha256"]
    assert fixture.path.read_bytes() == alias
    with store.connect() as conn:
        note = conn.execute("SELECT body,page,anchor FROM notes").fetchone()
        assert (note["body"], note["page"]) == ("> prior original passage", 1)
        assert json.loads(note["anchor"]) == json.loads(anchor)
    reader = from_workspace(fixture.database, legacy_root=fixture.path.parent)
    assert Path(reader.resolve("paper").path).read_bytes() == (
        fixture.root / "new.pdf"
    ).read_bytes()
    retained = fixture.blobs.verified_path(BlobManifest(old["sha256"], old["size"]))
    assert retained.read_bytes() == alias


def test_late_staging_and_retry_cannot_overwrite_newer_original(make):
    fixture = enrolled(make)
    late = native.observe(fixture.database, "paper")
    first = native.prepare(native.observe(fixture.database, "paper"), selected(fixture))
    native.run(first)
    latest = current(fixture)
    with pytest.raises(ValueError, match="changed"):
        native.prepare(late, selected(fixture, "late.pdf"))
    second = native.prepare(
        native.observe(fixture.database, "paper"), selected(fixture, "second.pdf"),
    )
    native.run(second)
    with pytest.raises(ValueError, match="cannot revive"):
        native.run(first)
    assert current(fixture)["sha256"] != latest["sha256"]


def test_cancellation_invalid_bytes_and_duplicate_activation_preserve_source(make):
    fixture = enrolled(make)
    before = current(fixture)
    ticket = Ticket()
    observed = native.observe(fixture.database, "paper", ticket=ticket)
    prepared = native.prepare(observed, selected(fixture))
    ticket.cancel()
    with pytest.raises(Cancelled):
        native.run(prepared)
    invalid = fixture.root / "invalid.pdf"
    invalid.write_bytes(b"%PDF-not-readable")
    prepared = native.prepare(native.observe(fixture.database, "paper"), invalid)
    with pytest.raises(ValueError):
        native.run(prepared)
    prepared.running.acquire()
    try:
        with pytest.raises(ValueError, match="already running"):
            native.run(prepared)
    finally:
        prepared.running.release()
    assert current(fixture) == before


def test_repdf_uses_native_path_without_deleting_derivatives_or_reanchoring(make, monkeypatch):
    fixture = enrolled(make)
    old = current(fixture)
    def forbidden(*args, **kwargs):
        pytest.fail("Native replacement attempted legacy derivative/anchor mutation")
    monkeypatch.setattr(repdf, "reanchor", forbidden)
    monkeypatch.setattr(repdf.fetch, "extract_text", forbidden)
    logs = []
    assert repdf.replace("paper", file=str(selected(fixture)), log=logs.append)
    assert current(fixture)["sha256"] != old["sha256"]
    assert "prior originals retained" in logs[-1]


def test_repdf_observes_before_download_and_rejects_race(make, monkeypatch):
    fixture = enrolled(make)
    other = selected(fixture)
    def download(*args, **kwargs):
        native.run(native.prepare(native.observe(fixture.database, "paper"), other))
        return fixture.bytes
    monkeypatch.setattr(repdf.fetch, "fetch", download)
    logs = []
    assert not repdf.replace("paper", "https://fixture.invalid/paper.pdf", log=logs.append)
    assert "changed" in logs[-1]
    reader = from_workspace(fixture.database, legacy_root=fixture.path.parent)
    assert Path(reader.resolve("paper").path).read_bytes() == other.read_bytes()


def test_partial_binding_never_falls_back_to_legacy_filesystem(make):
    fixture = enrolled(make)
    before = fixture.path.read_bytes()
    with fixture.client.journal.transaction() as conn:
        conn.execute("DELETE FROM research_capture_binding")
    logs = []
    assert not repdf.replace("paper", file=str(selected(fixture)), log=logs.append)
    assert fixture.path.read_bytes() == before
    assert "refused" in logs[-1]


def test_workspace_switch_after_staging_preserves_original(make):
    fixture = enrolled(make)
    before = current(fixture)
    active = [True]
    prepared = native.prepare(
        native.observe(fixture.database, "paper", current=lambda: active[0]), selected(fixture),
    )
    active[0] = False
    with pytest.raises(ValueError, match="lifetime changed"):
        native.run(prepared)
    assert current(fixture) == before


def test_enrolled_first_pdf_uses_owned_store_without_creating_legacy_alias(make):
    fixture = make()
    fixture.path.unlink()
    with fixture.client.journal.transaction() as conn:
        register_document_paths(
            conn, workspace_id="workspace", blob_root=fixture.blobs.root,
            projection_root=fixture.root / "reader-documents", legacy_root=fixture.path.parent,
        )
    chosen = selected(fixture)
    assert repdf.replace("paper", file=str(chosen), log=lambda _: None)
    assert not fixture.path.exists()
    reader = from_workspace(fixture.database, legacy_root=fixture.path.parent)
    assert Path(reader.resolve("paper").path).read_bytes() == chosen.read_bytes()


def test_failure_during_binding_rolls_back_document_outbox_and_receipt(make, monkeypatch):
    fixture = enrolled(make)
    before = current(fixture)
    prepared = native.prepare(native.observe(fixture.database, "paper"), selected(fixture))
    with fixture.client.journal.transaction() as conn:
        count = conn.execute("SELECT count(*) FROM research_action_receipts").fetchone()[0]
    def refuse(*args, **kwargs):
        raise ValueError("simulated binding failure")
    monkeypatch.setattr(native, "bind_verified_document", refuse)
    with pytest.raises(ValueError, match="simulated binding failure"):
        native.run(prepared)
    assert current(fixture) == before
    with fixture.client.journal.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM research_action_receipts").fetchone()[0] == count
        assert conn.execute(
            "SELECT count(*) FROM paperfact_sync_operations WHERE operation_id=?",
            (fixture.actions._id(prepared.request_id, "document-op"),),
        ).fetchone()[0] == 0
