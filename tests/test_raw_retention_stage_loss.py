"""Backend reproduction: unique captured draft bytes survive a staging failure."""

import copy
import hashlib
import json
import socket
import sqlite3
import subprocess
from contextlib import closing

import pymupdf
import pytest
from test_sync_files import LOCAL
from test_sync_files import codec as codec  # noqa: F401
from test_sync_files import pair as pair  # noqa: F401

from paper_daily import llm, presentations, raw_deck_closure, store, sync_recovery
from paper_daily import sync_deck_publication as publication
from paper_daily.ai_types import Completion, Settings
from paper_daily.presentations import figure_bytes as captured_figure_bytes
from paper_daily.research_review import ResearchReview
from paper_daily.sync_blobs import BlobManifest


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("No real provider, process or network is admitted")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(llm, "complete", deny)
    monkeypatch.setattr(llm, "complete_result", deny)


def captured_material(codec):
    deck = copy.deepcopy(codec[0])
    deck.paper_id = LOCAL
    deck.title = "Unique in-memory scientific draft"
    deck.slides[0].speaker_notes = "Full unique explanation, retained without abbreviation"
    deck.figures.append({"id": "figure:3", "label": "Unused original image", "file": "c.png"})
    images = {}
    for number, rgb in enumerate((b"\x11\x51\x91", b"\x31\x71\xb1", b"\x61\xa1\xe1"), 1):
        images[f"figure:{number}"] = pymupdf.Pixmap(
            pymupdf.csRGB, 32, 24, rgb * (32 * 24), False
        ).tobytes("png")
    deck._revision_figures = images
    evidence = {
        "paper": {"id": LOCAL, "title": "Paper", "year": 2026},
        "sources": [
            dict(item, text="Exact synthetic evidence, not a PDF quote") for item in deck.sources
        ],
        "figures": copy.deepcopy(deck.figures),
        "coverage": ["Methods"],
        "source_hash": hashlib.sha256(b"unique synthetic captured evidence").hexdigest(),
    }
    deck.source_hash = evidence["source_hash"]
    return deck, images, evidence


@pytest.mark.parametrize("path", ["publication", "generation"])
@pytest.mark.parametrize("fail_stage", [False, True], ids=["healthy", "before-first-write"])
def test_unique_used_and_unused_images_remain_durable_after_retention(
    pair, codec, monkeypatch, tmp_path, path, fail_stage
):
    _, a, b, fa, _, _, _ = pair
    deck, images, evidence = captured_material(codec)
    expected_raw = deck.to_dict()
    monkeypatch.setattr(presentations, "figure_bytes", captured_figure_bytes)
    observed = publication.observe_deck(LOCAL, "guide")
    before_pending = a.journal.pending()
    begin_calls, model_calls, produced = [], [], []
    real_begin = type(fa.store).begin

    def begin(store_instance, manifest):
        begin_calls.append(manifest.sha256)
        if fail_stage:
            raise OSError("Synthetic primary write failure before first mutation")
        return real_begin(store_instance, manifest)

    monkeypatch.setattr(type(fa.store), "begin", begin)
    actual_publish = publication.publish_deck
    if path == "publication":
        monkeypatch.setattr(store, "DB_PATH", b.journal.path)
        with pytest.raises(publication.StaleDeckError):
            actual_publish(
                deck, observation=observed, evidence=evidence, request_id="captured-stage-failure"
            )
        produced.append(deck)
    else:

        def fake_model(_prompt, **kwargs):
            model_calls.append(kwargs["task"])
            slides = [copy.deepcopy(deck.to_dict()["slides"][0]) for _ in range(4)]
            return Completion(
                json.dumps({"title": deck.title, "slides": slides}),
                model="simulated-returned",
                backend="fixture",
            )

        def publish_after_external_switch(value, **kwargs):
            value._revision_figures = dict(images)
            produced.append(value)
            monkeypatch.setattr(store, "DB_PATH", b.journal.path)
            return actual_publish(value, **kwargs)

        monkeypatch.setattr(llm, "complete_result", fake_model)
        monkeypatch.setattr(
            presentations, "collect_evidence", lambda *_args: copy.deepcopy(evidence)
        )
        monkeypatch.setattr(publication, "publish_deck", publish_after_external_switch)
        try:
            returned, _reason = presentations.generate(
                LOCAL,
                mode="guide",
                audience="Researchers",
                minutes=10,
                slide_count=4,
                inputs={"dive"},
                cfg=Settings("gateway", model="simulated", isolated=True),
            )
        except publication.StaleDeckError:
            returned = None
        assert returned is None and model_calls == ["slides"]

    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    with closing(sqlite3.connect(a.journal.path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute("SELECT * FROM research_file_drafts")]
    assert len(rows) == 1
    raw = rows[0]
    reopened = json.loads(raw["deck"])
    assert reopened["title"] == expected_raw["title"]
    assert reopened["slides"][0]["speaker_notes"] == expected_raw["slides"][0]["speaker_notes"]
    assert len(reopened["figures"]) == 3

    # This is the invariant in BOTH healthy and first-write-failure branches:
    # a fresh backup must retain every byte before any explicit storage repair.
    backup = tmp_path / "after-restart.zip"
    manifest = sync_recovery.create(a.journal.path, backup, blob_store=fa.store)
    assert sync_recovery.inspect(backup) == manifest
    target = tmp_path / "detached-recovery"
    sync_recovery.restore_detached(backup, target)
    for data in images.values():
        assert (target / "objects" / hashlib.sha256(data).hexdigest()).read_bytes() == data
    with closing(sqlite3.connect(target / "papers.db")) as conn:
        archived = json.loads(
            conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_file_drafts'"
            ).fetchone()[0]
        )
    assert archived == raw

    review = ResearchReview(a.journal.path)
    try:
        preview = review.preview("file_draft", raw["candidate_id"])
        assert not preview.data["apply"]
        if fail_stage:
            with pytest.raises((ValueError, OSError)):
                review.prepare_file(preview)
        else:
            assert review.prepare_file(preview).data["apply"]
        monkeypatch.setattr(type(fa.store), "begin", real_begin)
        retry_id = raw_deck_closure.retain(
            json.loads(raw["observation"]),
            produced[0],
            evidence=evidence,
            request_id=raw["candidate_id"],
        )
        assert retry_id == raw["candidate_id"]
        prepared = review.prepare_file(preview)
        assert prepared.data["apply"]
    finally:
        review.close()
    assert all(
        fa.store.available(BlobManifest(hashlib.sha256(data).hexdigest(), len(data)))
        for data in images.values()
    )
    with closing(sqlite3.connect(a.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM " + raw_deck_closure.TABLE).fetchone() == (1,)
    assert a.journal.pending() == before_pending
    with closing(sqlite3.connect(b.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_drafts").fetchone() == (0,)
    assert model_calls == (["slides"] if path == "generation" else [])
