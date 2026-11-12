"""Deferred deck generation preserves source evidence and cannot target another workspace."""

import json
import os
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest
from test_presentations import deck as deck
from test_presentations import reply
from test_presentations import research as research
from test_sync_files import LOCAL, save_current
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import llm, presentations, store
from paper_daily.ai_types import Completion, Settings


def generate(monkeypatch, calls):
    def complete(*args, **kwargs):
        calls.append(kwargs)
        return Completion(reply())

    monkeypatch.setattr(llm, "complete_result", complete)
    result, reason = presentations.generate(
        "ref:deck",
        mode="guide",
        audience="",
        minutes=10,
        slide_count=4,
        inputs={"original", "dive"},
        save=False,
    )
    assert reason == "ok"
    return result


def test_deferred_draft_writes_nothing_until_explicit_save_and_keeps_exact_evidence(
    research,
    deck,
    monkeypatch,
):
    presentations.save_deck(deck)
    before = {
        p.relative_to(presentations.DECK_DIR): p.read_bytes()
        for p in presentations.DECK_DIR.rglob("*")
        if p.is_file()
    }
    calls = []
    draft = generate(monkeypatch, calls)
    assert {
        p.relative_to(presentations.DECK_DIR): p.read_bytes()
        for p in presentations.DECK_DIR.rglob("*")
        if p.is_file()
    } == before
    assert draft.deck_id != deck.deck_id and len(calls) == 1
    assert not any(key.startswith("_") for key in draft.to_dict())
    expected = deepcopy(draft._generation_evidence)
    presentations.save_deck(draft)
    evidence = presentations._folder(draft.paper_id) / "evidence" / (draft.source_hash + ".json")
    assert json.loads(evidence.read_text(encoding="utf-8")) == expected
    assert presentations.load_deck(draft.paper_id, draft.mode).deck_id == draft.deck_id
    assert len(calls) == 1


def test_failed_deferred_save_preserves_previous_deck_and_retries_without_another_model(
    research,
    deck,
    monkeypatch,
):
    presentations.save_deck(deck)
    destination = presentations._path(deck.paper_id, deck.mode)
    before = destination.read_bytes()
    calls = []
    draft = generate(monkeypatch, calls)
    original = presentations._atomic_json
    with monkeypatch.context() as patch:

        def fail(path, data):
            if path == destination:
                raise OSError("synthetic write refusal")
            return original(path, data)

        patch.setattr(presentations, "_atomic_json", fail)
        with pytest.raises(OSError):
            presentations.save_deck(draft)
    assert destination.read_bytes() == before
    presentations.save_deck(draft)
    assert presentations.load_deck(deck.paper_id, deck.mode).deck_id == draft.deck_id
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["database", "folder", "native", "paper"])
def test_deferred_draft_refuses_changed_native_workspace_or_slot_without_writing(
    research,
    deck,
    monkeypatch,
    change,
):
    presentations.save_deck(deck)
    destination = presentations._path(deck.paper_id, deck.mode)
    before = destination.read_bytes()
    calls = []
    draft = generate(monkeypatch, calls)
    original_db = Path(store.DB_PATH)
    old = None
    with monkeypatch.context() as patch:
        if change == "database":
            other = research / "other.db"
            patch.setattr(store, "DB_PATH", other)
        elif change == "folder":
            patch.setattr(presentations, "DECK_DIR", research / "other-decks")
        elif change == "paper":
            draft.paper_id = "ref:other"
        else:
            replacement, old = research / "replacement.db", research / "original-held.db"
            assert all(
                path.resolve().is_relative_to(research.resolve())
                for path in [original_db, replacement, old]
            )
            with closing(sqlite3.connect(replacement)) as conn:
                conn.executescript(store.SCHEMA)
            os.replace(original_db, old)
            os.replace(replacement, original_db)
        try:
            with pytest.raises(ValueError, match="workspace|unavailable"):
                presentations.save_deck(draft)
            assert destination.read_bytes() == before
            assert not (research / "other.db").exists()
            assert not (research / "other-decks").exists()
        finally:
            if old is not None:
                os.replace(old, original_db)
            draft.paper_id = deck.paper_id
    presentations.save_deck(draft)
    assert presentations.load_deck(deck.paper_id, deck.mode).deck_id == draft.deck_id
    assert len(calls) == 1


def test_modified_pending_evidence_cannot_replace_the_saved_deck(research, deck, monkeypatch):
    presentations.save_deck(deck)
    destination = presentations._path(deck.paper_id, deck.mode)
    before = destination.read_bytes()
    draft = generate(monkeypatch, [])
    expected = deepcopy(draft._generation_evidence)
    draft._generation_evidence["sources"][0]["text"] = "different evidence"
    with pytest.raises(ValueError, match="evidence changed"):
        presentations.save_deck(draft)
    assert destination.read_bytes() == before
    draft._generation_evidence = expected
    presentations.save_deck(draft)
    assert presentations.load_deck(deck.paper_id, deck.mode).deck_id == draft.deck_id


def test_repair_keeps_the_original_resolved_model_after_configuration_changes(
    research, monkeypatch
):
    first = Settings("openai", model="first-model", profile="A", api_key="synthetic-first")
    later = Settings("openai", model="later-model", profile="B", api_key="synthetic-later")
    configurations, calls = [], []

    def selected(**_kwargs):
        configurations.append(True)
        return first if len(configurations) == 1 else later

    monkeypatch.setattr(llm, "settings", selected)
    raw = json.loads(reply())
    fixed = deepcopy(raw["slides"][1])
    raw["slides"][1]["bullets"] = ["x" * 121]

    def complete(prompt, **kwargs):
        calls.append(kwargs["cfg"])
        if len(calls) == 1:
            return Completion(json.dumps(raw))
        return Completion(json.dumps({"slides": [{"index": 1, "slide": fixed}]}))

    monkeypatch.setattr(llm, "complete_result", complete)
    draft, reason = presentations.generate(
        "ref:deck",
        mode="guide",
        audience="",
        minutes=10,
        slide_count=4,
        inputs={"original", "dive"},
        save=False,
    )
    assert reason == "ok" and draft.slides[1].bullets == fixed["bullets"]
    assert calls == [first, first] and len(configurations) == 1


@pytest.mark.parametrize("save", [None, 0, "false"])
def test_invalid_save_mode_refuses_before_spending_a_model_call(research, monkeypatch, save):
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("model requested"))
    draft, reason = presentations.generate(
        "ref:deck",
        mode="guide",
        audience="",
        minutes=10,
        slide_count=4,
        inputs={"original", "dive"},
        save=save,
    )
    assert draft is None and "save" in reason
    assert not list(presentations.DECK_DIR.rglob("*.json"))


def test_deferred_save_preserves_a_later_manual_edit_and_retains_generated_draft(
    research,
    deck,
    monkeypatch,
):
    presentations.save_deck(deck)
    draft = generate(monkeypatch, [])
    deck.slides[0].title = "A newer manual edit"
    presentations.save_deck(deck)
    before = presentations._path(deck.paper_id, deck.mode).read_bytes()
    candidate = draft.to_dict()
    with pytest.raises(ValueError, match="Saved deck changed"):
        presentations.save_deck(draft)
    assert presentations._path(deck.paper_id, deck.mode).read_bytes() == before
    assert draft.to_dict() == candidate


def test_retry_after_atomic_write_committed_does_not_duplicate_history_or_call_model(
    research,
    deck,
    monkeypatch,
):
    presentations.save_deck(deck)
    calls = []
    draft = generate(monkeypatch, calls)
    destination = presentations._path(deck.paper_id, deck.mode)
    atomic = presentations._atomic_json
    with monkeypatch.context() as patch:

        def commit_then_fail(path, data):
            atomic(path, data)
            if path == destination:
                raise OSError("lost success after atomic commit")

        patch.setattr(presentations, "_atomic_json", commit_then_fail)
        with pytest.raises(OSError):
            presentations.save_deck(draft)
    history = sorted((destination.parent / "history").glob("*.json"))
    assert len(history) == 1
    saved = destination.read_bytes()
    presentations.save_deck(draft)
    assert destination.read_bytes() == saved
    assert sorted((destination.parent / "history").glob("*.json")) == history
    assert len(calls) == 1
    assert not hasattr(draft, "_generation_workspace")


def test_an_edited_saved_generated_deck_can_be_saved_again(research, monkeypatch):
    draft = generate(monkeypatch, [])
    presentations.save_deck(draft)
    draft.slides[0].title = "A later deliberate edit"
    presentations.save_deck(draft)
    saved = presentations.load_deck(draft.paper_id, draft.mode)
    assert saved.slides[0].title == "A later deliberate edit"


@pytest.mark.parametrize("change_inputs", [False, True])
def test_managed_deferred_save_uses_actual_evidence_and_retains_changed_input_candidate(
    pair,
    codec,
    monkeypatch,
    change_inputs,
):
    from paper_daily.sync_artifacts import desired_file, paths
    from paper_daily.sync_blobs import BlobManifest
    from paper_daily.sync_deck_publication import StaleDeckError

    _server, client, _other, _fa, _fb, _ta, _tb = pair
    original = save_current(pair, codec[0])
    note = "An actual reader observation used for this generated draft."
    with client.journal.transaction() as conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) VALUES(?,?,?,?)",
            (LOCAL, note, "note", "2026-10-31T00:00:00Z"),
        )
    with client.journal.transaction() as conn:
        conn.execute(
            "INSERT INTO dives(paper_id,body,written_at) VALUES(?,?,?)",
            (LOCAL, "Stored fixture background and method explanation.", "2026-10-31T00:00:00Z"),
        )
    calls = []

    def complete(prompt, **kwargs):
        calls.append(kwargs)
        payload = json.loads(prompt)
        source = next(row for row in payload["sources"] if row["kind"] == "notes")
        assert note in source["text"]
        slide = presentations.Slide(
            "Reader observation",
            "Notes",
            "Review this observation",
            ["This is a reader observation."],
            "Verify against the paper.",
            [source["id"]],
        )
        return Completion(
            json.dumps(
                {"title": "Deferred managed draft", "slides": [slide.__dict__ for _ in range(4)]}
            )
        )

    monkeypatch.setattr(llm, "complete_result", complete)
    draft, reason = presentations.generate(
        LOCAL,
        mode="guide",
        audience="Researchers",
        minutes=10,
        slide_count=4,
        inputs={"notes", "dive"},
        save=False,
    )
    assert reason == "ok"
    evidence = deepcopy(draft._generation_evidence)
    with client.journal.transaction() as conn:
        assert desired_file(conn, original["entity_id"]) == original
        if change_inputs:
            conn.execute("UPDATE notes SET body=? WHERE paper_id=?", ("A newer observation", LOCAL))
    if change_inputs:
        with pytest.raises(StaleDeckError):
            presentations.save_deck(draft)
        with client.journal.transaction() as conn:
            assert desired_file(conn, original["entity_id"]) == original
            assert conn.execute("SELECT COUNT(*) FROM research_file_candidates").fetchone()[0] == 1
    else:
        presentations.save_deck(draft)
        with client.journal.transaction() as conn:
            latest = desired_file(conn, original["entity_id"])
            blobs, _version_root = paths(conn)
        assert latest != original
        asset = next(row for row in latest["payload"]["assets"] if row["role"] == "evidence")
        stored = json.loads(
            blobs.verified_path(BlobManifest(asset["sha256"], asset["size"])).read_bytes()
        )
        assert stored["source_hash"] == draft.source_hash
        assert stored["sources"] == evidence["sources"]
        assert presentations.load_deck(LOCAL, "guide").deck_id == draft.deck_id
    assert len(calls) == 1
