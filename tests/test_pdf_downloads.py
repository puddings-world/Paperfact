import json
import threading
import time

import httpx
import pymupdf
import pytest
from test_research_plan import db as _db
from test_research_plan import fake_plan, paper

from paper_daily import fetch as fetcher
from paper_daily import pdf_downloads as dl
from paper_daily import pdf_sources as sources
from paper_daily import research_plan as rp
from paper_daily import store
from paper_daily.http import FetchError

db = _db


@pytest.fixture
def pdf():
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "Synthetic download fixture")
        return document.tobytes()


def transport(monkeypatch, blob, *, headers=None, status=200):
    original = httpx.Client

    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            yield blob[:20]
            yield blob[20:]

    wire = httpx.MockTransport(lambda request: httpx.Response(
        status, headers=headers or {}, stream=Chunks()))
    monkeypatch.setattr(dl.httpx, "Client", lambda **kw: original(transport=wire, **kw))
    monkeypatch.setattr(dl, "_throttle", lambda _: None)


@pytest.mark.parametrize("known", [True, False])
def test_stream_shows_real_bytes_and_publishes_only_after_validation(
    tmp_path, monkeypatch, pdf, known,
):
    transport(monkeypatch, pdf, headers={"Content-Length": str(len(pdf))} if known else {})
    dest, events = tmp_path / "paper.pdf", []

    def progress(*event):
        assert not dest.exists()
        events.append(dl.State(*event))

    dl.stream_pdf("https://example.org/paper.pdf", dest, progress, threading.Event())
    assert dest.read_bytes() == pdf and not list(tmp_path.glob("*.part"))
    downloading = [s for s in events if s.phase == "downloading"]
    assert downloading[-1].received == len(pdf)
    assert downloading[-1].percent == (99 if known else None)
    assert downloading[-1].total == (len(pdf) if known else None)


@pytest.mark.parametrize("blob,status,length", [
    (b"<html>sign in</html>", 200, None), (b"%PDF-broken", 200, None),
    (b"denied", 403, None), (b"%PDF-broken", 200, "1000"),
    (b"", 200, "200000000"),
    (b"%PDF-broken\n%%EOF", 200, None),
])
def test_failed_download_never_publishes_pdf_or_keeps_part(
    tmp_path, monkeypatch, blob, status, length,
):
    transport(monkeypatch, blob, headers={"Content-Length": length} if length else {},
              status=status)
    dest = tmp_path / "paper.pdf"
    with pytest.raises(FetchError):
        dl.stream_pdf("https://example.org/paper.pdf", dest, lambda *a: None, threading.Event())
    assert not dest.exists() and not list(tmp_path.glob("*.part"))


def test_cancel_discards_partial_bytes_and_preserves_existing_pdf(tmp_path, monkeypatch, pdf):
    transport(monkeypatch, pdf)
    cancel = threading.Event()
    dest = tmp_path / "paper.pdf"
    dest.write_bytes(b"curated original")

    def progress(phase, received, total, message):
        if received:
            cancel.set()

    with pytest.raises(dl.Cancelled):
        dl.stream_pdf("https://example.org/paper.pdf", dest, progress, cancel)
    assert dest.read_bytes() == b"curated original" and not list(tmp_path.glob("*.part"))


def test_truncated_pdf_is_rejected_even_when_size_is_unknown(tmp_path, monkeypatch, pdf):
    transport(monkeypatch, pdf[:pdf.rfind(b"%%EOF")])
    dest = tmp_path / "incomplete.pdf"
    with pytest.raises(FetchError, match="結尾不完整"):
        dl.stream_pdf("https://example.org/paper.pdf", dest, lambda *a: None, threading.Event())
    assert not dest.exists() and not list(tmp_path.glob("*.part"))


def seed(db):
    store.upsert_papers(db, [dict(id="fixture", title="Fixture paper", venue="test", year=2025,
                                pdf_url="https://example.org/broken.pdf", source="fixture")])
    db.commit()


def test_alternate_download_saves_successful_url_and_clears_prior_pdf_failure(db, monkeypatch,
                                                                          tmp_path, pdf):
    seed(db)
    monkeypatch.setattr(dl, "PDF_DIR", tmp_path)
    store.set_kv(db, "analyze.failed.pdf.fixture", "old failure")
    db.commit()
    tried = []

    def stream(url, dest, progress, cancel):
        tried.append(url)
        if "broken" in url:
            raise FetchError("HTTP 403")
        dest.write_bytes(pdf)
        return dest

    monkeypatch.setattr(dl, "stream_pdf", stream)
    monkeypatch.setattr(sources, "discover", lambda *a: iter([
        "https://example.org/broken.pdf", "https://example.org/working.pdf"]))
    dest = dl.download("fixture", lambda *a: None, threading.Event())
    assert dest.read_bytes() == pdf and len(tried) == 2
    assert db.execute("SELECT pdf_url FROM papers").fetchone()[0].endswith("working.pdf")
    assert store.get_kv(db, "analyze.failed.pdf.fixture") is None
    dl.download("fixture", lambda *a: None, threading.Event())
    assert len(tried) == 2  # Existing content is never redownloaded.


def test_failure_is_visible_and_never_alters_saved_metadata(db, monkeypatch, tmp_path):
    seed(db)
    monkeypatch.setattr(dl, "PDF_DIR", tmp_path)
    monkeypatch.setattr(dl, "stream_pdf", lambda *a: (_ for _ in ()).throw(FetchError("HTTP 429")))
    monkeypatch.setattr(sources, "discover", lambda *a: iter([]))
    with pytest.raises(FetchError, match="429"):
        dl.download("fixture", lambda *a: None, threading.Event())
    assert db.execute("SELECT pdf_url FROM papers").fetchone()[0].endswith("broken.pdf")
    assert not list(tmp_path.glob("*.pdf"))


def test_reader_fetch_and_background_download_share_lock(db, monkeypatch, tmp_path, pdf):
    seed(db)
    monkeypatch.setattr(dl, "PDF_DIR", tmp_path)
    monkeypatch.setattr(fetcher, "PDF_DIR", tmp_path)
    monkeypatch.setattr(fetcher, "ensure_dirs", lambda: None)
    # Use a valid PDF larger than the legacy fetcher's minimum size.
    content = pdf + b"\n%" + b"x" * 1500
    entered, release = threading.Event(), threading.Event()
    calls = []

    def fetch(*a, **kw):
        calls.append(a)
        entered.set()
        assert release.wait(3)
        return content

    monkeypatch.setattr(fetcher, "fetch", fetch)
    monkeypatch.setattr(dl, "stream_pdf", lambda *a: pytest.fail("duplicate transfer"))
    row = dict(db.execute("SELECT * FROM papers").fetchone())
    first = threading.Thread(target=fetcher.ensure_pdf, args=(row,))
    outputs = []
    second = threading.Thread(target=lambda: outputs.append(
        dl.download("fixture", lambda *a: None, threading.Event())))
    first.start()
    assert entered.wait(2)
    second.start()
    release.set()
    first.join(3)
    second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert len(calls) == 1 and outputs[0].read_bytes() == content


def wait_until(predicate):
    until = time.monotonic() + 4
    while not predicate() and time.monotonic() < until:
        time.sleep(0.005)
    assert predicate()


def test_pool_limits_concurrency_deduplicates_shared_lists_and_retries_only_failed():
    release, lock = threading.Event(), threading.Lock()
    calls, active, maximum = [], 0, 0

    def work(pid, progress, cancel):
        nonlocal active, maximum
        with lock:
            calls.append(pid)
            active += 1
            maximum = max(maximum, active)
        assert release.wait(3)
        with lock:
            active -= 1
        if pid == "p4" and calls.count(pid) == 1:
            raise FetchError("temporary failure")
        return "saved.pdf"

    queue = dl.DownloadQueue(work)
    try:
        for _ in range(30):
            queue.submit(["p1", "p2", "p3", "p4", "p5"])
            queue.submit(["p2", "p4"], retry=True)
        wait_until(lambda: len(calls) == 3)
        assert maximum == 3 and queue.snapshot()["p5"].phase == "queued"
        release.set()
        wait_until(lambda: not queue.busy)
        assert len(calls) == 5 and queue.snapshot()["p4"].phase == "error"
        assert "temporary failure" in queue.snapshot()["p4"].label
        queue.submit(["p1", "p4"], retry=True)
        wait_until(lambda: not queue.busy)
        assert calls.count("p1") == 1 and calls.count("p4") == 2
        assert queue.snapshot()["p4"].percent == 100
    finally:
        release.set()
        queue.close()


def test_cancel_and_close_never_start_pending_jobs_or_revive_on_refresh():
    started = threading.Event()
    calls = []

    def work(pid, progress, cancel):
        calls.append(pid)
        started.set()
        assert cancel.wait(3)
        dl.check_cancel(cancel)

    queue = dl.DownloadQueue(work, limit=1)
    queue.submit(["p1", "p2", "p3"])
    assert started.wait(2)
    queue.cancel()
    wait_until(lambda: not queue.busy)
    assert calls == ["p1"] and all(s.phase == "cancelled" for s in queue.snapshot().values())
    queue.submit(["p1", "p2"])
    assert not queue.busy
    queue.close()
    queue.submit(["p4"], retry=True)
    assert "p4" not in queue.snapshot()


def test_empty_and_unknown_length_states_are_honest():
    queue = dl.DownloadQueue(lambda *a: pytest.fail("empty list started work"))
    queue.submit([])
    assert not queue.busy and queue.snapshot() == {}
    assert dl.State("downloading", 1234).percent is None
    assert "未知" in dl.State("downloading", 1234).label
    assert dl.State("downloading", 200, 100).percent == 99
    queue.close()


def test_openalex_extracts_repository_landing_links_and_doi_arxiv():
    work = dict(id="https://openalex.org/W123", display_name="Fixture paper",
                primary_location=dict(landing_page_url="https://arxiv.org/abs/2501.12345v2"))
    converted = rp._openalex(work)
    assert converted["openAccessPdf"]["url"] == "https://arxiv.org/pdf/2501.12345v2"
    assert converted["externalIds"]["ArXiv"] == "2501.12345v2"
    assert sources.openalex_links(dict(doi="https://doi.org/10.48550/arXiv.2501.12345")) == [
        "https://arxiv.org/pdf/2501.12345"]
    assert sources.direct_link("https://openreview.net/forum?id=fixture") == (
        "https://openreview.net/pdf?id=fixture")


def test_discovery_rejects_similar_title_and_recovers_exact_arxiv_match(monkeypatch):
    responses = [dict(data=[dict(title="A different paper", openAccessPdf={
        "url": "https://example.org/wrong.pdf"})]), dict(results=[])]
    calls = []

    def fetch(url, **kwargs):
        calls.append(kwargs)
        if len(calls) <= 2:
            return json.dumps(responses[len(calls) - 1]).encode()
        return b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>http://arxiv.org/abs/2501.12345v2</id><title>Fixture paper</title></entry></feed>'''

    monkeypatch.setattr(sources, "fetch", fetch)
    assert list(sources.discover(dict(title="Fixture paper"))) == [
        "https://arxiv.org/pdf/2501.12345v2"]
    assert len(calls) == 3 and all(c["retries"] == 1 and c["timeout"] == 12 for c in calls)


def test_discovery_cancellation_prevents_further_requests(monkeypatch):
    monkeypatch.setattr(sources, "fetch", lambda *a, **kw: pytest.fail("cancelled lookup"))
    with pytest.raises(dl.Cancelled):
        list(sources.discover(dict(title="Fixture"), lambda: (_ for _ in ()).throw(dl.Cancelled())))


def test_research_commit_fills_missing_pdf_link_without_overwriting_existing_data(db, monkeypatch):
    fake_plan(monkeypatch)
    plan = rp.propose("Fixture research", "quick")
    row = rp.lists._paper_from_match(dict(title="A verified study"), paper())
    row["abstract"] = "Curated abstract"
    store.upsert_papers(db, [row])
    db.commit()
    plan["candidates"]["p1"]["openAccessPdf"] = {"url": "https://example.org/new.pdf"}
    rp.commit("Fixture", plan, ["p1"])
    saved = db.execute("SELECT pdf_url,abstract FROM papers").fetchone()
    assert tuple(saved) == ("https://example.org/new.pdf", "Curated abstract")
    plan["id"] = "another-list"
    plan["candidates"]["p1"]["openAccessPdf"]["url"] = "https://example.org/other.pdf"
    rp.commit("Other", plan, ["p1"])
    assert db.execute("SELECT pdf_url FROM papers").fetchone()[0].endswith("new.pdf")
