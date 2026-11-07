"""Default generation must not publish after its original workspace/slot changes."""

import json
import os
import sqlite3
from pathlib import Path

import pytest

from paper_daily import llm, store
from paper_daily import presentations as slides
from paper_daily.ai_types import Completion, Settings


@pytest.fixture
def research(tmp_path, monkeypatch):
    from test_presentations import research as original

    return original.__wrapped__(tmp_path, monkeypatch)


def tree(folder):
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in folder.rglob("*") if path.is_file()}


def database_rows(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return tuple(conn.iterdump())
    finally:
        conn.close()


def current_deck(title, identifier):
    from test_presentations import deck as original

    deck = original.__wrapped__()
    deck.title, deck.deck_id, deck.edited = title, identifier, True
    return deck


def generate(cfg):
    return slides.generate(
        "ref:deck", mode="guide", audience="New researchers", minutes=15,
        slide_count=4, inputs={"original", "dive"}, cfg=cfg,
    )


@pytest.mark.parametrize("changed", ["folder", "native_db", "slot"])
def test_default_generation_preserves_original_and_new_current_targets(
    research, monkeypatch, changed,
):
    from test_presentations import reply

    original_root = slides.DECK_DIR
    database = Path(store.DB_PATH)
    slides.save_deck(current_deck("Earlier historical draft", "earlier"))
    slides.save_deck(current_deck("Original current manual draft", "original"))
    other_root = research / "other-decks"
    other_root.mkdir()
    with monkeypatch.context() as other:
        other.setattr(slides, "DECK_DIR", other_root)
        slides.save_deck(current_deck("Other workspace's curated draft", "other"))
    baseline = {"original": tree(original_root), "other": tree(other_root)}
    before_rows = database_rows(database)
    cfg = Settings("gateway", model="requested-model")
    seen = []

    def model(prompt, **kwargs):
        seen.append(kwargs)
        assert json.loads(prompt)["requested_slides"] == 4
        if changed == "folder":
            monkeypatch.setattr(slides, "DECK_DIR", other_root)
        elif changed == "native_db":
            replacement = research / "replacement.db"
            source = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
            target = sqlite3.connect(replacement)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            before_identity = (database.stat().st_dev, database.stat().st_ino)
            os.replace(replacement, database)
            assert (database.stat().st_dev, database.stat().st_ino) != before_identity
        else:
            manual = slides.load_deck("ref:deck", "guide")
            manual.title = "A newer careful manual edit"
            manual.slides[0].speaker_notes = "Do not replace this newer explanation."
            slides.save_deck(manual)
            baseline["original"] = tree(original_root)
        return Completion(reply(), backend="fixture", model="returned-model", request_id="job")

    monkeypatch.setattr(llm, "complete_result", model)
    deck, reason = generate(cfg)
    # Assert the actual files and full version history before inspecting the return value.
    assert tree(original_root) == baseline["original"]
    assert tree(other_root) == baseline["other"]
    assert database_rows(database) == before_rows
    assert deck is None and reason != "ok"
    assert len(seen) == 1
    assert seen[0]["cfg"] is cfg and seen[0]["task"] == "slides"
    assert seen[0]["timeout"] == 600


@pytest.mark.parametrize("deferred", [False, True])
def test_changed_global_database_is_rejected_before_foreign_database_open(
    research, monkeypatch, deferred,
):
    from test_presentations import reply

    slides.save_deck(current_deck("Original manual deck", "manual"))
    original = tree(slides.DECK_DIR)
    other = research / "other.db"
    source = sqlite3.connect(store.DB_PATH)
    target = sqlite3.connect(other)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    before = database_rows(other)
    opened, calls = [], []
    connect = sqlite3.connect

    def observe(database, *args, **kwargs):
        opened.append(str(database).replace(chr(92), "/"))
        return connect(database, *args, **kwargs)

    def model(*args, **kwargs):
        calls.append(kwargs)
        if not deferred:
            monkeypatch.setattr(store, "DB_PATH", other)
        return Completion(reply())

    monkeypatch.setattr(llm, "complete_result", model)
    if deferred:
        draft, reason = slides.generate(
            "ref:deck", mode="guide", audience="", minutes=15, slide_count=4,
            inputs={"original", "dive"}, save=False, cfg=Settings("none"),
        )
        assert reason == "ok"
        monkeypatch.setattr(store, "DB_PATH", other)
    monkeypatch.setattr(sqlite3, "connect", observe)
    if deferred:
        with pytest.raises(ValueError, match="workspace"):
            slides.save_deck(draft)
    else:
        draft, reason = generate(Settings("none"))
        assert draft is None and reason != "ok"
    assert str(other.resolve()).replace(chr(92), "/") not in "\n".join(opened)
    assert tree(slides.DECK_DIR) == original
    assert database_rows(other) == before
    assert len(calls) == 1


@pytest.mark.parametrize("phase", ["evidence", "settings"])
def test_switched_scope_during_preparation_never_spends_a_model_call(
    research, monkeypatch, phase,
):
    slides.save_deck(current_deck("Original manual deck", "manual"))
    root = slides.DECK_DIR
    before = tree(root)
    other = research / "other-decks"
    collect = slides.collect_evidence

    def evidence(*args, **kwargs):
        value = collect(*args, **kwargs)
        if phase == "evidence":
            monkeypatch.setattr(slides, "DECK_DIR", other)
        return value

    def settings(**kwargs):
        monkeypatch.setattr(slides, "DECK_DIR", other)
        return Settings("none")

    monkeypatch.setattr(slides, "collect_evidence", evidence)
    monkeypatch.setattr(llm, "settings", settings)
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("model spent"))
    result, reason = generate(Settings("none") if phase == "evidence" else None)
    assert result is None and reason != "ok"
    assert tree(root) == before and not other.exists()


@pytest.mark.parametrize("changed", ["root", "same_bytes_slot"])
def test_native_deck_ownership_change_refuses_even_when_bytes_are_identical(
    research, monkeypatch, changed,
):
    from test_presentations import reply

    slides.save_deck(current_deck("Original manual deck", "manual"))
    root = slides.DECK_DIR
    baseline = tree(root)
    calls = []

    def model(*args, **kwargs):
        calls.append(kwargs)
        if changed == "root":
            old = research / "held-original-decks"
            os.replace(root, old)
            root.mkdir()
            for name, data in baseline.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            assert root.stat().st_ino != old.stat().st_ino
        else:
            destination = slides._path("ref:deck", "guide")
            old_inode = destination.stat().st_ino
            replacement = destination.with_suffix(".replacement")
            replacement.write_bytes(destination.read_bytes())
            os.replace(replacement, destination)
            assert old_inode != destination.stat().st_ino
        return Completion(reply())

    monkeypatch.setattr(llm, "complete_result", model)
    result, reason = generate(Settings("none"))
    assert tree(root) == baseline
    assert result is None and reason != "ok" and len(calls) == 1
