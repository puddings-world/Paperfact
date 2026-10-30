"""AI materials stay source-grounded and attached to their original paper."""

import sqlite3
from contextlib import closing

import pytest
from test_presentation_pane import pane as _pane_fixture

from paper_daily import llm, materials, store
from paper_daily.desktop import presentation_pane, reading_annotation_ui

presentation = _pane_fixture


@pytest.fixture
def pane(presentation, monkeypatch):
    widget, deck, app, root = presentation
    database = root / "research.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
        store.upsert_papers(conn, [
            {"id": deck.paper_id, "title": deck.paper_title,
             "venue": "Fixture", "year": 2026, "source": "fixture"},
            {"id": "another-paper", "title": "Another paper",
             "venue": "Fixture", "year": 2026, "source": "fixture"},
        ])
        conn.commit()
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(llm, "capture_connections", lambda: {})
    monkeypatch.setattr("paper_daily.config.PDF_DIR", root / "pdf")
    reading_annotation_ui.bind(widget)
    assert widget._annotation_owner is not None
    return widget, deck, app, root


def test_highlight_selection_shows_reason_and_adds_missing_original_citation(pane):
    widget, deck, app, _tmp = pane
    item = dict(
        text="The original result is conditional on the sampled population.",
        page=91,
        kind="limitation",
        source="page:91",
        reason="界定結果的適用範圍。",
    )
    widget.materials_panel.load(
        materials.Materials(
            deck.paper_id,
            sentences=[item],
            highlights={"coverage": {"empty_pages": [], "has_page_numbers": True}},
        )
    )
    group = widget.materials_panel.tree.topLevelItem(2)
    widget.materials_panel.tree.setCurrentItem(group.child(0))
    assert item["text"] in widget.materials_panel.detail.toPlainText()
    assert item["reason"] in widget.materials_panel.detail.toPlainText()
    widget._insert_material(dict(item, kind="sentence"))
    assert widget.save_changes(), widget.status.text()
    assert "page:91" in widget.deck.slides[0].sources
    assert any(s["id"] == "page:91" and s["kind"] == "original" for s in widget.deck.sources)
    assert not any(item["reason"] in o.get("text", "") for o in widget.canvas.snapshot())


def test_background_analysis_cannot_update_another_papers_panel(pane, monkeypatch):
    widget, deck, app, _tmp = pane
    callbacks, loaded = {}, []
    monkeypatch.setattr(presentation_pane.llm, "available", lambda **kwargs: True)
    monkeypatch.setattr(presentation_pane.llm, "settings", lambda **kwargs: "chosen-profile")
    monkeypatch.setattr(
        widget.runner,
        "start",
        lambda prompt, done, fail, **kwargs: callbacks.update(done=done, fail=fail, **kwargs),
    )
    monkeypatch.setattr(widget, "_load_materials", lambda: loaded.append(widget.paper_id))
    widget._analyze_highlights()
    assert widget.busy and not widget.materials_panel.analyze.isEnabled()
    assert callbacks["task"] == "paper_highlights"
    widget.paper_id = "another-paper"
    callbacks["done"]("{}")
    assert not widget.busy and loaded == []
    # Changing an ID is not a new loaded owner. Use the real paper-load action.
    widget.load("another-paper", "Another paper")
    assert widget._annotation_owner.paper_id == "another-paper"
    assert loaded == []  # The materials panel is collapsed during paper load.
    widget._analyze_highlights()
    callbacks["done"]("{}")
    assert loaded == ["another-paper"]


def test_analysis_failure_keeps_visible_previous_quotes(pane, monkeypatch):
    widget, deck, app, _tmp = pane
    item = dict(
        text="The original result is conditional on the sampled population.",
        page=1,
        kind="limitation",
        source="page:1",
        reason="範圍限制",
    )
    widget.materials_panel.load(materials.Materials(deck.paper_id, sentences=[item]))
    callbacks = {}
    monkeypatch.setattr(presentation_pane.llm, "available", lambda **kwargs: True)
    monkeypatch.setattr(presentation_pane.llm, "settings", lambda **kwargs: "chosen-profile")
    monkeypatch.setattr(
        widget.runner, "start", lambda prompt, done, fail, **kwargs: callbacks.update(fail=fail)
    )
    widget._analyze_highlights()
    callbacks["fail"]("network unavailable")
    assert widget.materials_panel.tree.topLevelItem(2).childCount() == 1
    assert "舊結果保留" in widget.materials_panel.analysis_status.text()
    assert widget.materials_panel.analyze.isEnabled()


def test_analysis_refuses_an_unbound_pane_without_starting_a_job(pane, monkeypatch):
    widget, _deck, _app, _root = pane
    calls = []
    widget._annotation_owner = None
    monkeypatch.setattr(widget.runner, "start", lambda *a, **k: calls.append((a, k)))
    widget._analyze_highlights()
    assert not calls and not widget.busy
    assert widget.materials_panel.analyze.isEnabled()
