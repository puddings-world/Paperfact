"""Reader/analysis intake shares native downloads and retains exact source delivery."""

import shutil
import threading

import pytest
from test_legacy_primary_migration import make as make
from test_native_pdf_downloads import setup, state
from test_pdf_downloads import transport
from test_research_plan import db as db

from paper_daily import fetch, store
from paper_daily import native_primary_publication as native
from paper_daily import pdf_downloads as dl
from paper_daily.document_reader import from_workspace
from paper_daily.http import FetchError


def reader_fixture(make, monkeypatch):
    fixture = setup(make, monkeypatch)
    monkeypatch.setattr(fetch, "PDF_DIR", fixture.path.parent)
    monkeypatch.setattr(fetch, "TEXT_DIR", fixture.root / "text")
    monkeypatch.setattr(fetch, "ensure_dirs", lambda: None)
    transport(monkeypatch, fixture.bytes)
    with store.connect() as conn:
        row = dict(conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone())
    return fixture, row


def test_first_reader_download_extracts_from_exact_native_projection(make, monkeypatch):
    fixture, row = reader_fixture(make, monkeypatch)
    monkeypatch.setattr(fetch, "fetch", lambda *a, **k: pytest.fail("Legacy network fallback"))
    path, text = fetch.prepare(row)
    document = from_workspace(fixture.database).resolve("paper")
    assert path == document.path and path.suffix == ".pdf"
    assert text and "Current primary B" in text
    assert not fixture.path.exists()
    caches = list(fetch.TEXT_DIR.rglob("body.txt"))
    assert len(caches) == 1 and document.sha256 in str(caches[0])
    assert caches[0].read_text(encoding="utf-8") == text
    assert state(fixture)["applied"]["sha256"] == document.sha256


def test_partial_enrollment_cannot_trigger_legacy_reader_write(make, monkeypatch):
    fixture, row = reader_fixture(make, monkeypatch)
    with fixture.client.journal.transaction() as conn:
        conn.execute("DELETE FROM research_capture_binding")
    before = state(fixture)
    monkeypatch.setattr(fetch, "fetch", lambda *a, **k: pytest.fail("Legacy network fallback"))
    monkeypatch.setattr(dl, "stream_pdf", lambda *a: pytest.fail("Incomplete workspace downloaded"))
    assert fetch.ensure_pdf(row) is None
    assert state(fixture) == before and not fixture.path.exists()


def test_reader_handoff_cannot_adopt_another_database(make, monkeypatch):
    fixture, row = reader_fixture(make, monkeypatch)
    before = state(fixture)
    other = fixture.root / "other.db"
    shutil.copy2(fixture.database, other)
    original = dl.download
    def switched(*args, **kwargs):
        monkeypatch.setattr(store, "DB_PATH", other)
        return original(*args, **kwargs)
    monkeypatch.setattr(dl, "download", switched)
    assert fetch.ensure_pdf(row) is None
    assert state(fixture) == before and not fixture.path.exists()
    assert not from_workspace(other).resolve("paper").managed


def test_reader_and_list_prefetch_share_one_native_transfer(make, monkeypatch):
    fixture, row = reader_fixture(make, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    calls, outputs, failures = [], [], []
    stream = dl.stream_pdf
    def pending(*args):
        calls.append(args[0])
        entered.set()
        assert release.wait(5)
        return stream(*args)
    monkeypatch.setattr(dl, "stream_pdf", pending)
    def work(action):
        try:
            outputs.append(action())
        except BaseException as exc:
            failures.append(exc)
    reader = threading.Thread(target=work, args=(lambda: fetch.ensure_pdf(row),))
    queue = threading.Thread(target=work, args=(
        lambda: dl.download("paper", lambda *a: None, threading.Event()),
    ))
    try:
        reader.start()
        assert entered.wait(5)
        queue.start()
    finally:
        release.set()
        reader.join(10)
        if queue.ident is not None:
            queue.join(10)
    assert not reader.is_alive() and not queue.is_alive() and not failures
    assert len(calls) == 1 and len(outputs) == 2
    assert outputs[0] == outputs[1] and outputs[0].suffix == ".pdf"
    assert outputs[0].read_bytes() == fixture.bytes


@pytest.mark.parametrize("reason", ["projection", "cancel"])
def test_saved_original_delivery_failure_is_not_reported_as_rollback(make, monkeypatch, reason):
    fixture, row = reader_fixture(make, monkeypatch)
    original = fetch.capture_document
    def unavailable(*args, **kwargs):
        document = original(*args, **kwargs)
        if document is not None and document.managed:
            raise OSError("Synthetic projection failure")
        return document
    cancel = threading.Event()
    run = native.run
    def cancelled_after_commit(prepared):
        result = run(prepared)
        cancel.set()
        return result
    with monkeypatch.context() as context:
        if reason == "projection":
            context.setattr(fetch, "capture_document", unavailable)
        else:
            context.setattr(native, "run", cancelled_after_commit)
        with pytest.raises(FetchError, match="Original saved"):
            dl.download("paper", lambda *a: None, cancel)
    after = state(fixture)
    assert after["applied"] is not None and after["failure"] is None
    monkeypatch.setattr(dl, "stream_pdf", lambda *a: pytest.fail("Saved bytes redownloaded"))
    assert fetch.ensure_pdf(row).read_bytes() == fixture.bytes
    assert state(fixture) == after


def test_prepare_does_not_deliver_stale_text_after_source_invalidation(make, monkeypatch):
    fixture, row = reader_fixture(make, monkeypatch)
    original = fetch.extract_text
    def invalidated(*args, **kwargs):
        text = original(*args, **kwargs)
        assert kwargs["document"] is not None and text
        kwargs["document"]._owner.invalidate()
        return text
    monkeypatch.setattr(fetch, "extract_text", invalidated)
    assert fetch.prepare(row) == (None, None)
    assert state(fixture)["applied"] is not None


def legacy_row(db, monkeypatch, tmp_path):
    store.upsert_papers(db, [dict(
        id="legacy", title="Legacy fixture", venue="test", year=2026,
        source="fixture", pdf_url="https://fixture.invalid/original.pdf",
    )])
    db.commit()
    root = tmp_path / "legacy-pdf"
    root.mkdir()
    monkeypatch.setattr(fetch, "PDF_DIR", root)
    monkeypatch.setattr(fetch, "ensure_dirs", lambda: None)
    return dict(db.execute("SELECT * FROM papers").fetchone()), root / "legacy.pdf"


def test_unenrolled_reader_preserves_existing_legacy_fetch_behavior(db, monkeypatch, tmp_path):
    row, alias = legacy_row(db, monkeypatch, tmp_path)
    content = b"%PDF-legacy fixture" + b"x" * 1400
    monkeypatch.setattr(fetch, "fetch", lambda *a, **k: content)
    assert fetch.ensure_pdf(row) == alias and alias.read_bytes() == content
    monkeypatch.setattr(fetch, "fetch", lambda *a, **k: pytest.fail("Existing alias redownloaded"))
    assert fetch.ensure_pdf(row) == alias


def test_legacy_network_result_cannot_install_after_enrollment_starts(db, monkeypatch, tmp_path):
    row, alias = legacy_row(db, monkeypatch, tmp_path)
    def activating(*args, **kwargs):
        db.execute("CREATE TABLE research_capture_binding(id INTEGER PRIMARY KEY)")
        db.commit()
        return b"%PDF-late legacy fixture"
    monkeypatch.setattr(fetch, "fetch", activating)
    assert fetch.ensure_pdf(row) is None
    assert not alias.exists() and not list(alias.parent.glob("*.part"))
