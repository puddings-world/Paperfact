"""Completed research stays available when every persistence path fails."""

import json
from copy import deepcopy

import pytest
from test_raw_deck_receipts import codec as _codec
from test_raw_deck_receipts import no_external as _no_external
from test_raw_deck_receipts import original as _original
from test_raw_deck_receipts import retained

from paper_daily import raw_deck_closure, raw_deck_receipts
from paper_daily.pending_deck_result import PendingDeckResults, read_export
from paper_daily.sync_blobs import BlobStore

codec = _codec
no_external = _no_external
original = _original


def test_total_failure_keeps_actual_result_and_retries_without_another_model(original, monkeypatch):
    real_begin, real_write = BlobStore.begin, raw_deck_receipts.write_owned
    _error, result = retained(original, monkeypatch, blob_fail=True, receipt_fail=True)
    pool = PendingDeckResults()
    key = pool.hold(result)
    assert pool.items()[0][1] is result and pool.pending
    assert pool.hold(result) == key and len(pool.items()) == 1
    again = pool.retry(key)
    assert not again.durable and pool.items()[0][1] is again and pool.pending
    monkeypatch.setattr(BlobStore, "begin", real_begin)
    monkeypatch.setattr(raw_deck_receipts, "write_owned", real_write)
    repaired = pool.retry(key)
    assert repaired.durable and repaired.deck is result.deck and not pool.pending
    assert pool.items() == []


def test_failed_retry_and_changed_result_do_not_release_held_research(original, monkeypatch):
    _error, result = retained(original, monkeypatch, blob_fail=True, receipt_fail=True)
    pool = PendingDeckResults()
    key = pool.hold(result)

    def fail(_outcome):
        raise OSError("still unavailable")

    monkeypatch.setattr(raw_deck_closure, "retry_retention", fail)
    with pytest.raises(OSError):
        pool.retry(key)
    assert pool.items() == [(key, result)]
    altered = deepcopy(result)
    altered.deck.title = "Different result"
    with pytest.raises(ValueError):
        pool.hold(altered)
    assert pool.items() == [(key, result)]
    pool.discard(key, expected=result)
    assert not pool.pending


def test_complete_export_preserves_all_images_without_sender_writer_authority(
    original, monkeypatch, tmp_path
):
    _error, result = retained(original, monkeypatch, blob_fail=True, receipt_fail=True)
    pool = PendingDeckResults()
    key = pool.hold(result)
    destination = tmp_path / "research.paperfact-draft.json"
    exported = pool.export(key, destination)
    read = read_export(destination.read_bytes())
    assert exported == destination and not pool.pending
    assert read["deck"]["title"] == result.deck.title
    assert read["image_bytes"] == original[4]
    assert not read["publish"] and not read["sync"] and read["requires_explicit_review"]
    raw = destination.read_text("utf-8")
    assert "database_identity" not in raw and "workspace_id" not in raw
    assert "observation" not in raw and "profile" not in raw


@pytest.mark.parametrize("failure", ["existing", "write", "corrupt"])
def test_failed_export_keeps_pending_result_and_existing_files(
    original, monkeypatch, tmp_path, failure
):
    _error, result = retained(original, monkeypatch, blob_fail=True, receipt_fail=True)
    pool = PendingDeckResults()
    key = pool.hold(result)
    destination = tmp_path / "research.paperfact-draft.json"
    if failure == "existing":
        destination.write_bytes(b"never overwrite")
    elif failure == "write":
        destination = tmp_path / "missing" / "research.json"
    else:
        capture = json.loads(result._capture)
        sha = next(iter(capture["data"]))
        capture["data"][sha] = "AAAA"
        object.__setattr__(result, "_capture", json.dumps(capture).encode())
    with pytest.raises((ValueError, OSError)):
        pool.export(key, destination)
    assert pool.items() == [(key, result)]
    if failure == "existing":
        assert destination.read_bytes() == b"never overwrite"


def test_same_request_name_in_two_original_workspaces_preserves_both_results(original, monkeypatch):
    from copy import deepcopy

    from paper_daily import store
    from paper_daily import sync_deck_publication as publication

    _error, first = retained(original, monkeypatch, blob_fail=True, receipt_fail=True)
    a, b, fa, deck, images, evidence, observation = original
    monkeypatch.setattr(store, "DB_PATH", b.journal.path)
    second_deck = deepcopy(deck)
    second_observation = publication.observe_deck(second_deck.paper_id, second_deck.mode)
    second = raw_deck_closure.retain_outcome(
        second_observation, second_deck, evidence=evidence, request_id=first.candidate_id
    )
    assert not second.durable
    pool = PendingDeckResults()
    key_a, key_b = pool.hold(first), pool.hold(second)
    assert key_a != key_b and len(pool.items()) == 2
    assert pool.hold(first) == key_a and pool.hold(second) == key_b
    pool.discard(key_a, expected=first)
    assert pool.items() == [(key_b, second)]


def test_rescue_export_preserves_unused_figure_metadata_and_full_research_evidence(
    original, monkeypatch, tmp_path
):
    from copy import deepcopy

    a, b, fa, deck, images, evidence, observation = original
    deck.figures[-1].update(
        caption="Unique unused experimental detail", page=17, document_hash="3" * 64
    )
    evidence.update(
        paper={
            "id": deck.paper_id,
            "title": deck.paper_title,
            "authors_json": '["Synthetic Author"]',
        },
        figures=deepcopy(deck.figures),
    )
    _error, result = retained(original, monkeypatch, blob_fail=True, receipt_fail=True)
    pool = PendingDeckResults()
    key = pool.hold(result)
    target = tmp_path / "complete.paperfact-draft.json"
    pool.export(key, target)
    recovered = read_export(target.read_bytes())
    unused = next(row for row in recovered["deck"]["figures"] if row["id"] == "figure:3")
    assert unused["caption"] == "Unique unused experimental detail"
    assert unused["page"] == 17 and unused["document_hash"] == "3" * 64
    assert recovered["evidence"]["paper"] == evidence["paper"]
    assert recovered["evidence"]["figures"][-1]["caption"] == unused["caption"]
    assert recovered["image_bytes"] == images
    assert not pool.pending


@pytest.mark.parametrize("extra", ["figure", "evidence", "paper"])
def test_unsupported_research_metadata_refuses_lossy_export_and_keeps_actual_result(
    original, monkeypatch, tmp_path, extra
):
    a, b, fa, deck, images, evidence, observation = original
    if extra == "figure":
        deck.figures[-1]["unknown_scientific_detail"] = "Preserve this observation"
    elif extra == "paper":
        evidence["paper"] = {"unknown_scientific_detail": "Preserve this observation"}
    else:
        evidence["unknown_scientific_detail"] = "Preserve this observation"
    _error, result = retained(original, monkeypatch, blob_fail=True, receipt_fail=True)
    pool = PendingDeckResults()
    key = pool.hold(result)
    target = tmp_path / "must-not-be-lossy.json"
    with pytest.raises(ValueError, match="Unsupported"):
        pool.export(key, target)
    assert pool.items() == [(key, result)] and not target.exists()
