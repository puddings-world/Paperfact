"""Background first-original download uses verified native publication, not aliases."""

import json
import os
import shutil
import threading
from contextlib import closing, contextmanager
from pathlib import Path

import pytest
from test_legacy_primary_migration import make as make
from test_legacy_primary_migration import pdf
from test_pdf_downloads import transport

from paper_daily import native_primary_publication as native
from paper_daily import pdf_downloads as dl
from paper_daily import store
from paper_daily.document_reader import from_workspace, register_document_paths
from paper_daily.http import FetchError
from paper_daily.sync_documents import applied_document, desired_document

OLD_URL = "https://fixture.invalid/missing.pdf"
NEW_URL = "https://fixture.invalid/available.pdf"


def setup(make, monkeypatch, *, legacy=False):
    fixture = make()
    if not legacy:
        fixture.path.unlink()
    with fixture.client.journal.transaction() as conn:
        register_document_paths(
            conn, workspace_id="workspace", blob_root=fixture.blobs.root,
            projection_root=fixture.root / "reader-documents", legacy_root=fixture.path.parent,
        )
    with store.connect() as conn:
        conn.execute("UPDATE papers SET pdf_url=? WHERE id='paper'", (OLD_URL,))
        store.set_kv(conn, "analyze.failed.pdf.paper", "previous failure")
    monkeypatch.setattr(dl, "PDF_DIR", fixture.path.parent)
    monkeypatch.setattr(dl.pdf_sources, "known_links", lambda _: [OLD_URL])
    monkeypatch.setattr(dl.pdf_sources, "discover", lambda *a: iter([NEW_URL]))
    return fixture


def state(fixture):
    with closing(native._read(fixture.database)) as conn:
        return dict(
            desired=desired_document(conn, fixture.portable),
            applied=applied_document(conn, fixture.portable),
            url=conn.execute("SELECT pdf_url FROM papers WHERE id='paper'").fetchone()[0],
            failure=store.get_kv(conn, "analyze.failed.pdf.paper"),
            operations=list(conn.execute(
                "SELECT operation_id,fingerprint FROM paperfact_sync_operations ORDER BY sequence",
            )),
            receipts=list(conn.execute(
                "SELECT * FROM research_action_receipts ORDER BY request_id",
            )),
        )


def test_alternate_first_pdf_publishes_url_bytes_and_cache_atomically(make, monkeypatch):
    fixture = setup(make, monkeypatch)
    calls = []
    transport(monkeypatch, fixture.bytes, headers={"Content-Length": str(len(fixture.bytes))})
    stream = dl.stream_pdf
    def selected(url, *args):
        calls.append(url)
        if url == OLD_URL:
            raise FetchError("HTTP 403")
        return stream(url, *args)
    monkeypatch.setattr(dl, "stream_pdf", selected)
    events = []
    result = dl.download("paper", lambda *e: events.append(dl.State(*e)), threading.Event())
    after = state(fixture)
    assert after["desired"] == after["applied"] and after["applied"] is not None
    assert after["url"] == NEW_URL and after["failure"] is None
    assert Path(result).read_bytes() == fixture.bytes and not fixture.path.exists()
    assert from_workspace(fixture.database).resolve("paper").sha256 == after["applied"]["sha256"]
    assert calls == [OLD_URL, NEW_URL]
    assert any(event.phase == "downloading" for event in events)
    assert events[-1].phase == "verifying" and events[-1].percent is None
    reopened = dl.download("paper", lambda *a: None, threading.Event())
    assert Path(reopened).read_bytes() == Path(result).read_bytes()
    assert calls == [OLD_URL, NEW_URL]


@pytest.mark.parametrize("when", ["stream", "bind"])
def test_cancelled_download_does_not_publish_or_clear_failure(make, monkeypatch, when):
    fixture = setup(make, monkeypatch)
    before = state(fixture)
    cancel = threading.Event()
    def stream(url, dest, *args):
        dest.write_bytes(fixture.bytes)
        if when == "stream":
            cancel.set()
        return dest
    monkeypatch.setattr(dl, "stream_pdf", stream)
    bind = native.bind_verified_document
    def cancelling(*args):
        result = bind(*args)
        if when == "bind":
            cancel.set()
        return result
    monkeypatch.setattr(native, "bind_verified_document", cancelling)
    with pytest.raises(dl.Cancelled):
        dl.download("paper", lambda *a: None, cancel)
    assert state(fixture) == before
    assert not fixture.path.exists()


def test_source_published_during_stream_wins_over_late_download(make, monkeypatch):
    fixture = setup(make, monkeypatch)
    chosen = fixture.root / "chosen.pdf"
    pdf(chosen, "Explicit concurrent original")
    def stream(url, dest, *args):
        native.run(native.prepare(native.observe(fixture.database, "paper"), chosen))
        dest.write_bytes(fixture.bytes)
        return dest
    monkeypatch.setattr(dl, "stream_pdf", stream)
    with pytest.raises(FetchError, match="changed"):
        dl.download("paper", lambda *a: None, threading.Event())
    document = from_workspace(fixture.database).resolve("paper")
    assert Path(document.path).read_bytes() == chosen.read_bytes()
    assert state(fixture)["url"] == OLD_URL
    assert not fixture.path.exists()


def test_workspace_switch_during_stream_cannot_publish_into_either_workspace(make, monkeypatch):
    fixture = setup(make, monkeypatch)
    before = state(fixture)
    other = fixture.root / "other.db"
    def stream(url, dest, *args):
        dest.write_bytes(fixture.bytes)
        monkeypatch.setattr(store, "DB_PATH", other)
        return dest
    monkeypatch.setattr(dl, "stream_pdf", stream)
    with pytest.raises(FetchError, match="changed"):
        dl.download("paper", lambda *a: None, threading.Event())
    assert not other.exists() and state(fixture) == before


def test_failure_after_url_operation_rolls_back_bytes_url_outbox_and_cache(make, monkeypatch):
    fixture = setup(make, monkeypatch)
    before = state(fixture)
    def stream(url, dest, *args):
        dest.write_bytes(fixture.bytes)
        return dest
    monkeypatch.setattr(dl, "stream_pdf", stream)
    final = native.PreparedNativePrimary._final
    def fail_after_url(self, conn, target, *, metadata=False):
        final(self, conn, target, metadata=metadata)
        if metadata:
            raise ValueError("Injected failure after URL publication")
    monkeypatch.setattr(native.PreparedNativePrimary, "_final", fail_after_url)
    with pytest.raises(FetchError, match="changed"):
        dl.download("paper", lambda *a: None, threading.Event())
    assert state(fixture) == before and not fixture.path.exists()


def test_existing_legacy_alias_is_not_implicitly_migrated(make, monkeypatch):
    fixture = setup(make, monkeypatch, legacy=True)
    before = state(fixture)
    monkeypatch.setattr(dl, "stream_pdf", lambda *a: pytest.fail("Unexpected download"))
    assert dl.download("paper", lambda *a: None, threading.Event()) == fixture.path
    assert state(fixture) == before


def test_managed_missing_original_does_not_search_for_a_different_version(make, monkeypatch):
    fixture = setup(make, monkeypatch)
    chosen = fixture.root / "chosen.pdf"
    chosen.write_bytes(fixture.bytes)
    prepared = native.prepare(native.observe(fixture.database, "paper"), chosen)
    native.run(prepared)
    fixture.blobs._path(prepared.manifest).unlink()
    monkeypatch.setattr(dl, "stream_pdf", lambda *a: pytest.fail("Unexpected source search"))
    with pytest.raises(FetchError, match="workspace attachment synchronization"):
        dl.download("paper", lambda *a: None, threading.Event())


def test_owned_url_publication_preserves_rich_metadata_and_exact_retry(make, monkeypatch):
    fixture = setup(make, monkeypatch)
    authors = json.dumps([dict(name="Fixture Author", affiliation="Synthetic university")])
    # Model pre-existing rich local metadata without normalizing it through a
    # new ordinary metadata edit before the PDF operation is even observed.
    with fixture.client.journal.transaction() as conn:
        conn.execute("UPDATE papers SET authors_json=? WHERE id='paper'", (authors,))
    chosen = fixture.root / "chosen.pdf"
    chosen.write_bytes(fixture.bytes)
    prepared = native.prepare(
        native.observe(fixture.database, "paper", first_only=True), chosen, pdf_url=NEW_URL,
    )
    result = native.run(prepared)
    assert native.run(prepared) == result
    with store.connect() as conn:
        assert conn.execute("SELECT authors_json FROM papers").fetchone()[0] == authors
    assert state(fixture)["url"] == NEW_URL
    with pytest.raises(ValueError, match="managed original appeared"):
        native.observe(fixture.database, "paper", first_only=True)


@pytest.mark.parametrize("switch", ["path", "replacement"])
def test_waiting_download_retains_its_entry_workspace(make, monkeypatch, switch):
    fixture = setup(make, monkeypatch)
    before = state(fixture)
    other = fixture.root / "other.db"
    @contextmanager
    def changed_lock(*args):
        if switch == "path":
            monkeypatch.setattr(store, "DB_PATH", other)
        else:
            shutil.copy2(fixture.database, other)
            os.replace(other, fixture.database)
        yield
    monkeypatch.setattr(dl, "paper_lock", changed_lock)
    monkeypatch.setattr(dl, "stream_pdf", lambda *a: pytest.fail("Late workspace was adopted"))
    with pytest.raises(FetchError, match="workspace changed"):
        dl.download("paper", lambda *a: None, threading.Event())
    assert state(fixture) == before and not other.exists()
    assert not fixture.path.exists()


def test_manually_supplied_legacy_file_during_download_is_retained(make, monkeypatch):
    fixture = setup(make, monkeypatch)
    before = state(fixture)
    def stream(url, dest, *args):
        pdf(fixture.path, "Independently supplied original")
        dest.write_bytes(fixture.bytes)
        return dest
    monkeypatch.setattr(dl, "stream_pdf", stream)
    with pytest.raises(FetchError, match="changed"):
        dl.download("paper", lambda *a: None, threading.Event())
    assert state(fixture) == before
    with dl.pymupdf.open(fixture.path) as document:
        assert "Independently supplied original" in document[0].get_text()
