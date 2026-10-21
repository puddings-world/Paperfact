"""AI materials stay source-grounded and attached to their original paper."""

from test_presentation_pane import pane as _pane_fixture

from paper_daily import materials
from paper_daily.desktop import presentation_pane

pane = _pane_fixture


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
