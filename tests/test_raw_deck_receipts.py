"""Byte-complete full-deck retention and explicit owned recovery, without Qt/AI."""

import copy
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
from contextlib import closing

import pymupdf
import pytest
from test_sync_files import LOCAL, PAPER, paper_payload
from test_sync_files import codec as codec  # noqa: F401

from paper_daily import llm, presentations, store, sync_recovery
from paper_daily import raw_deck_closure as raw
from paper_daily import raw_deck_receipts as receipts
from paper_daily import sync_deck_publication as publication
from paper_daily.research_review import ResearchReview
from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_client import SyncClient
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_writer


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("No network, process or model call is admitted")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(llm, "complete", deny)
    monkeypatch.setattr(llm, "complete_result", deny)


@pytest.fixture
def original(tmp_path, monkeypatch, codec):
    class InertTransport:
        def __getattr__(self, name):
            if name == "base_url":
                raise AttributeError(name)
            raise AssertionError("Fixture transport must never be called")

    values = []
    for device in ("a", "b"):
        database = tmp_path / (device + ".sqlite")
        with closing(sqlite3.connect(database)) as conn:
            conn.executescript(store.SCHEMA)
        prepare(database, workspace_id="workspace", device_id=device)
        client = SyncClient(
            Journal(database, workspace_id="workspace", device_id=device), research_writer
        )
        client.save(client.new_graph_operation("paper", PAPER, paper_payload()))
        transfer = FileTransfers(
            client,
            BlobStore(tmp_path / (device + "-blobs")),
            InertTransport(),
            origin="https://fixture.invalid",
            token=None,
        )
        values.append((client, transfer))
    a, fa = values[0]
    b, _fb = values[1]
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    monkeypatch.setattr(presentations, "DECK_DIR", tmp_path / "legacy-decks")
    value = copy.deepcopy(codec[0])
    value.paper_id = LOCAL
    value.title = "Unique raw scientific explanation"
    value.slides[0].speaker_notes = "Keep every word of this synthetic explanation"
    value.figures.append({"id": "figure:3", "label": "Unused image", "file": "unused.png"})
    images = {}
    for n, rgb in enumerate((b"\x11\x51\x91", b"\x31\x71\xb1", b"\x61\xa1\xe1"), 1):
        images[f"figure:{n}"] = pymupdf.Pixmap(
            pymupdf.csRGB, 32, 24, rgb * (32 * 24), False
        ).tobytes("png")
    value._revision_figures = images
    # Restore actual captured-byte resolution; codec's acquisition fake is not
    # allowed to substitute its own red/blue images for these unique bytes.
    monkeypatch.setattr(presentations, "figure_bytes", _ACTUAL_FIGURE_BYTES)
    evidence = {
        "sources": value.sources,
        "coverage": ["Methods"],
        "source_hash": hashlib.sha256(b"unique captured explanation").hexdigest(),
    }
    value.source_hash = evidence["source_hash"]
    observation = publication.observe_deck(LOCAL, "guide")
    return a, b, fa, value, images, evidence, observation


_ACTUAL_FIGURE_BYTES = presentations.figure_bytes


def retained(original, monkeypatch, *, blob_fail=False, receipt_fail=False):
    a, b, fa, deck, images, evidence, observation = original
    monkeypatch.setattr(store, "DB_PATH", b.journal.path)

    def fail(*_args, **_kwargs):
        raise OSError("Synthetic storage write failure before first mutation")

    if blob_fail:
        monkeypatch.setattr(BlobStore, "begin", fail)
    if receipt_fail:
        monkeypatch.setattr(receipts, "write_owned", fail)
    with pytest.raises(
        (publication.StaleDeckError, publication.IncompleteDraftRetention)
    ) as caught:
        publication.publish_deck(
            deck, observation=observation, evidence=evidence, request_id="owned-full-deck"
        )
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    return caught.value, getattr(caught.value, "retention", None)


def source_row(database):
    with closing(sqlite3.connect(database)) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute("SELECT * FROM research_file_drafts").fetchone())


@pytest.mark.parametrize("mode", ["healthy", "primary-fails", "receipt-fails", "both-fail"])
def test_durable_outcome_retains_all_used_unused_bytes_or_actual_incomplete_result(
    original, monkeypatch, mode
):
    a, b, fa, deck, images, evidence, _observation = original
    before = a.journal.pending()
    error, result = retained(
        original,
        monkeypatch,
        blob_fail=mode in {"primary-fails", "both-fail"},
        receipt_fail=mode in {"receipt-fails", "both-fail"},
    )
    assert result.deck is deck and result.evidence == evidence
    assert a.journal.pending() == before
    with closing(sqlite3.connect(b.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (0,)
    saved = source_row(a.journal.path)
    assert json.loads(saved["deck"]) == deck.to_dict()
    if mode == "both-fail":
        assert isinstance(error, publication.IncompleteDraftRetention)
        assert not result.durable and result.state == "incomplete"
        assert "original draft retained" not in str(error)
        header, captured = receipts.decode(result._capture)
        assert header["evidence"] == evidence
        assert all(captured[hashlib.sha256(data).hexdigest()] == data for data in images.values())
    else:
        assert isinstance(error, publication.StaleDeckError) and result.durable
        assert result.state == ("receipt" if mode == "primary-fails" else "cas")
    if mode in {"healthy", "primary-fails"}:
        # Fresh reader holds no caller Deck/roots, only actual DB ownership.
        with closing(sqlite3.connect(a.journal.path.as_uri() + "?mode=ro", uri=True)) as conn:
            header, captured, _files = receipts.read_owned(conn, saved)
        assert header["evidence"] == evidence
        assert len(header["objects"]) >= 4
        assert all(captured[hashlib.sha256(data).hexdigest()] == data for data in images.values())
        assert {i["id"] for i in json.loads(header["closure"]["inventory"])["images"]} == set(
            images
        )
    if mode == "primary-fails":
        assert all(
            not fa.store.available(BlobManifest(hashlib.sha256(data).hexdigest(), len(data)))
            for data in images.values()
        )


def test_owned_receipt_backup_and_detached_recovery_preserve_exact_bytes_without_primary_writes(
    original, monkeypatch, tmp_path
):
    a, _b, fa, deck, images, evidence, _observed = original
    _error, result = retained(original, monkeypatch, blob_fail=True)
    archive = tmp_path / "private-complete.zip"
    manifest = sync_recovery.create(a.journal.path, archive, blob_store=fa.store)
    assert sync_recovery.inspect(archive) == manifest
    assert receipts.TABLE in {table["name"] for table in manifest["tables"]}
    target = tmp_path / "detached"
    sync_recovery.restore_detached(archive, target)
    recovered = receipts.read_detached(target / "papers.db", result.candidate_id)
    assert json.loads(recovered["raw"]["deck"]) == deck.to_dict()
    assert recovered["image_bytes"] == images
    assert recovered["evidence"] == evidence
    assert not recovered["publish"] and not recovered["sync"]
    assert recovered["requires_explicit_review"]
    with closing(sqlite3.connect(target / "papers.db")) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (receipts.TABLE,)
        ).fetchone()


def test_catalog_read_is_readonly_and_explicit_prepare_repairs_original_bytes_once(
    original, monkeypatch
):
    a, _b, fa, deck, images, _evidence, _observation = original
    real_begin = BlobStore.begin
    _error, result = retained(original, monkeypatch, blob_fail=True)
    saved = source_row(a.journal.path)
    with closing(sqlite3.connect(a.journal.path.as_uri() + "?mode=ro", uri=True)) as conn:
        before = conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
        conn.execute("PRAGMA query_only=ON")
        receipts.read_owned(conn, saved)
        assert conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall() == before
    review = ResearchReview(a.journal.path)
    try:
        before_pending = a.journal.pending()
        preview = review.preview("file_draft", result.candidate_id)
        assert not preview.data["apply"]
        with pytest.raises(OSError, match="Synthetic"):
            review.prepare_file(preview)
        monkeypatch.setattr(BlobStore, "begin", real_begin)
        prepared = review.prepare_file(preview)
        assert prepared.data["apply"]
        assert a.journal.pending() == before_pending
        again = review.prepare_file(preview)
        assert again.data["retained"] == prepared.data["retained"]
        assert prepared.data["retained"]["title"] == deck.title
        assert all(
            fa.store.available(BlobManifest(hashlib.sha256(data).hexdigest(), len(data)))
            for data in images.values()
        )
        with closing(sqlite3.connect(a.journal.path)) as conn:
            assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (1,)
            assert conn.execute("SELECT count(*) FROM " + raw.TABLE).fetchone() == (1,)
    finally:
        review.close()


def test_total_storage_failure_retry_uses_actual_captured_result_without_model(
    original, monkeypatch
):
    real_begin, real_write = BlobStore.begin, receipts.write_owned
    _error, outcome = retained(original, monkeypatch, blob_fail=True, receipt_fail=True)
    monkeypatch.setattr(BlobStore, "begin", real_begin)
    monkeypatch.setattr(receipts, "write_owned", real_write)
    # Explicit paths/owner are in the original capture; this retry performs no
    # settings lookup, model call, or source-filename lookup.
    result = raw.retry_retention(outcome)
    assert result.durable and result.state == "cas"
    assert result.candidate_id == outcome.candidate_id
    with closing(sqlite3.connect(original[0].journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM " + raw.TABLE).fetchone() == (1,)


@pytest.mark.parametrize("actor", ["image", "evidence", "raw", "receipt"])
def test_request_reuse_or_receipt_tampering_never_refreshes_original_authority(
    original, monkeypatch, actor
):
    a, _b, _fa, deck, images, evidence, observation = original
    _error, outcome = retained(original, monkeypatch, blob_fail=True)
    saved = source_row(a.journal.path)
    if actor == "image":
        deck._revision_figures["figure:1"] = images["figure:2"]
    elif actor == "evidence":
        evidence["coverage"] = ["Changed interpretation"]
    elif actor == "raw":
        deck.title = "Different draft"
    else:
        with closing(sqlite3.connect(a.journal.path)) as conn:
            header, _objects, _files = receipts.read_owned(conn, saved)
        path = receipts.location(header["owner"], outcome.candidate_id)
        value = json.loads(path.read_bytes())
        value["header"]["fingerprint"] = "0" * 64
        path.write_text(json.dumps(value), encoding="utf-8")
    before = a.journal.pending()
    with pytest.raises(ValueError):
        raw.retain_outcome(observation, deck, evidence=evidence, request_id=outcome.candidate_id)
    assert a.journal.pending() == before
    assert source_row(a.journal.path) == saved


@pytest.mark.parametrize("during", ["before-stage", "inside-begin"])
def test_foreign_transfer_binding_refuses_primary_writes_and_preserves_receipt(
    original, monkeypatch, during
):
    a, _b, fa, _deck, _images, _evidence, _observation = original
    index = fa.store.root / "index.sqlite"
    real_begin = BlobStore.begin

    def foreign():
        with closing(sqlite3.connect(index)) as conn, conn:
            conn.execute("UPDATE transfer_binding SET workspace='foreign-workspace'")

    if during == "before-stage":
        foreign()
    else:

        def switch_then_begin(self, manifest):
            foreign()
            return real_begin(self, manifest)

        monkeypatch.setattr(BlobStore, "begin", switch_then_begin)
    with closing(sqlite3.connect(index)) as conn:
        before = conn.execute("SELECT * FROM blobs").fetchall()
    error, result = retained(original, monkeypatch)
    assert isinstance(error, publication.StaleDeckError)
    assert result.durable and result.state == "receipt"
    with closing(sqlite3.connect(index)) as conn:
        assert conn.execute("SELECT * FROM blobs").fetchall() == before
        assert conn.execute("SELECT workspace FROM transfer_binding").fetchone() == (
            "foreign-workspace",
        )
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert (
            receipts.read_owned(conn, source_row(a.journal.path))[0]["raw"]["candidate_id"]
            == result.candidate_id
        )


@pytest.mark.parametrize("actor", ["cancel", "database-replaced", "binding"])
def test_explicit_repair_rejects_cancelled_or_replaced_original_without_new_authority(
    original, monkeypatch, tmp_path, actor
):
    a, _b, fa, _deck, _images, _evidence, _observation = original
    real_begin = BlobStore.begin
    _error, _outcome = retained(original, monkeypatch, blob_fail=True)
    monkeypatch.setattr(BlobStore, "begin", real_begin)
    saved = source_row(a.journal.path)
    if actor == "database-replaced":
        held = tmp_path / "original-held.sqlite"
        replacement = tmp_path / "replacement.sqlite"
        with closing(sqlite3.connect(replacement)) as conn:
            conn.execute("CREATE TABLE marker(value TEXT)")
        os.replace(a.journal.path, held)
        os.replace(replacement, a.journal.path)
    elif actor == "binding":
        with closing(sqlite3.connect(a.journal.path)) as conn, conn:
            conn.execute("UPDATE research_sync_binding SET origin='another-device'")
    with pytest.raises(ValueError):
        raw.repair(a.journal.path, saved, current=lambda: actor != "cancel")
    assert not list((fa.store.root / "objects").iterdir())


def test_owned_receipt_rejects_duplicate_nonfinite_and_unknown_fields(original, monkeypatch):
    a, _b, _fa, _deck, _images, _evidence, _observation = original
    _error, _outcome = retained(original, monkeypatch, blob_fail=True)
    with closing(sqlite3.connect(a.journal.path)) as conn:
        header, objects, _files = receipts.read_owned(conn, source_row(a.journal.path))
    for bad in (
        b'{"header":{},"header":{},"data":{}}',
        b'{"header":NaN,"data":{}}',
        b'{"header":{},"data":{},"new":1}',
    ):
        with pytest.raises(ValueError):
            receipts.decode(bad)
    assert header["objects"] and objects


def test_receipt_byte_bound_rejects_oversize_before_reading(original, tmp_path):
    database = original[0].journal.path
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        owner = receipts._database_owner(conn)
    root = receipts.location(owner, "limit-fixture").parent
    root.mkdir(parents=True)
    path = root / (("b" * 64) + ".json")
    with path.open("wb") as stream:
        stream.truncate(receipts.MAX_RECEIPT + 1)
    with pytest.raises(ValueError, match="bounded|160 MiB"):
        receipts.collect(database, tmp_path)
    path.unlink()


@pytest.mark.parametrize("bound", ["count", "collection-bytes"])
def test_collection_limits_fail_before_parsing_or_staging_unbounded_receipts(
    original, tmp_path, bound
):
    database = original[0].journal.path
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        owner = receipts._database_owner(conn)
    folder = receipts.location(owner, "limit-fixture").parent
    folder.mkdir(parents=True)
    if bound == "count":
        for n in range(receipts.MAX_RECEIPTS + 1):
            (folder / (hashlib.sha256(str(n).encode()).hexdigest() + ".json")).write_bytes(b"{}")
    else:
        for n in range(2):
            path = folder / (hashlib.sha256(str(n).encode()).hexdigest() + ".json")
            with path.open("wb") as stream:
                stream.truncate(receipts.MAX_COLLECTION // 2 + 1)
    with pytest.raises(ValueError, match="bounded"):
        receipts.collect(database, tmp_path)
    assert not list((tmp_path / "full-deck-draft-objects").iterdir())


def test_cancellation_after_real_staging_never_installs_closure_and_explicit_retry_succeeds(
    original, monkeypatch
):
    a, _b, _fa, _deck, _images, _evidence, _observation = original
    real_begin, real_finalize = BlobStore.begin, BlobStore.finalize
    _error, _result = retained(original, monkeypatch, blob_fail=True)
    monkeypatch.setattr(BlobStore, "begin", real_begin)
    saved = source_row(a.journal.path)
    alive = [True]

    def finish_then_cancel(self, manifest):
        value = real_finalize(self, manifest)
        alive[0] = False
        return value

    monkeypatch.setattr(BlobStore, "finalize", finish_then_cancel)
    before = a.journal.pending()
    with pytest.raises(ValueError, match="lifetime"):
        raw.repair(a.journal.path, saved, current=lambda: alive[0])
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (raw.TABLE,)).fetchone()
        assert receipts.read_owned(conn, saved) is not None
    assert a.journal.pending() == before and source_row(a.journal.path) == saved
    monkeypatch.setattr(BlobStore, "finalize", real_finalize)
    assert raw.repair(a.journal.path, saved) == saved["candidate_id"]


def test_inactive_archive_validation_rejects_unknown_partial_and_changed_object_bytes(
    original, monkeypatch, tmp_path
):
    a = original[0]
    _error, _result = retained(original, monkeypatch, blob_fail=True)
    rows, objects, _aliases = receipts.collect(a.journal.path, tmp_path)
    assert len(rows) == 1
    row = rows[0]
    before = a.journal.pending()
    for mutation in ("future", "missing", "unknown", "duplicate-object"):
        value = json.loads(row["manifest"])
        if mutation == "future":
            value["version"] = 2
        elif mutation == "missing":
            del value["body"]
        elif mutation == "unknown":
            value["new_authority"] = True
        else:
            value["objects"].append(copy.deepcopy(value["objects"][0]))
        with pytest.raises(ValueError):
            receipts.validate_manifest(
                {"candidate_id": row["candidate_id"], "manifest": json.dumps(value)}
            )
    with pytest.raises(ValueError, match="bytes|size"):
        receipts.read_retained(row, lambda _item: b"altered archive")
    recovered = receipts.read_retained(row, lambda item: objects[item["sha256"]].read_bytes())
    assert not recovered["publish"] and not recovered["sync"]
    assert recovered["requires_explicit_review"]
    assert a.journal.pending() == before


def test_all_three_storage_failures_keep_actual_complete_result(original, monkeypatch):
    real_begin, real_write = BlobStore.begin, receipts.write_owned
    a, _b, _fa, deck, images, evidence, _observation = original
    with closing(sqlite3.connect(a.journal.path)) as conn:
        conn.execute(
            "CREATE TRIGGER refuse_raw BEFORE INSERT ON research_file_drafts "
            "BEGIN SELECT RAISE(ABORT,'fixture metadata storage failure'); END"
        )
    _error, result = retained(original, monkeypatch, blob_fail=True, receipt_fail=True)
    assert not result.durable and result.state == "incomplete"
    assert result.deck is deck and result.evidence == evidence
    header, captured = receipts.decode(result._capture)
    assert header["evidence"] == evidence
    assert all(captured[hashlib.sha256(data).hexdigest()] == data for data in images.values())
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (0,)
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (raw.TABLE,)).fetchone()
    with closing(sqlite3.connect(a.journal.path)) as conn:
        conn.execute("DROP TRIGGER refuse_raw")
    monkeypatch.setattr(BlobStore, "begin", real_begin)
    monkeypatch.setattr(receipts, "write_owned", real_write)
    before = a.journal.pending()
    repaired = raw.retry_retention(result)
    assert repaired.durable and repaired.state == "cas"
    assert repaired.candidate_id == result.candidate_id and repaired.deck is deck
    assert a.journal.pending() == before
    assert json.loads(source_row(a.journal.path)["deck"]) == deck.to_dict()
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM " + raw.TABLE).fetchone() == (1,)
