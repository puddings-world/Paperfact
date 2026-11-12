"""Owner-local text icon reuse never becomes authority for source assets."""
import sqlite3
from contextlib import closing

from PySide6.QtGui import QColor, QImage
from test_progressive_slide_thumbnails import deck_view as _deck_view
from test_progressive_slide_thumbnails import drain, icon, saved_rows, track

from paper_daily import presentations, slide_layout, store
from paper_daily.desktop import slide_thumbnails
from paper_daily.desktop.presentation_pane import PresentationPane
from paper_daily.desktop.window_workspace import WindowWorkspace

deck_view = _deck_view


def test_another_pane_has_no_access_to_the_first_panes_remembered_icons(deck_view, monkeypatch):
    first, deck, app, _root = deck_view
    drain(first, app)
    calls = track(monkeypatch)
    second = PresentationPane()
    try:
        second.load(deck.paper_id, deck.paper_title)
        assert not calls
        drain(second, app)
        assert len(calls) == len(deck.slides)
        assert all(not second.outline.item(i).icon().isNull() for i in range(len(deck.slides)))
    finally:
        second.close()
        second.deleteLater()
        app.processEvents()


def test_native_workspace_replacement_cannot_restore_remembered_icons(deck_view, monkeypatch):
    widget, deck, app, root = deck_view
    drain(widget, app)
    widget._workspace_owner = WindowWorkspace.capture()
    database = store.DB_PATH
    replacement = root / "replacement.sqlite"
    with closing(sqlite3.connect(replacement)) as conn, conn:
        conn.execute("CREATE TABLE marker(value TEXT)")
    before = replacement.read_bytes()
    replacement.replace(database)
    calls = track(monkeypatch)
    widget._show_deck(presentations.deck_from_dict(deck.to_dict()))
    drain(widget, app)
    assert calls == [] and database.read_bytes() == before
    assert all(widget.outline.item(i).toolTip() for i in range(len(deck.slides)))


def test_remembered_text_images_have_a_per_pane_bound_without_research_writes(
    deck_view, monkeypatch,
):
    widget, deck, app, _root = deck_view
    before = saved_rows(store.DB_PATH)
    monkeypatch.setattr(slide_thumbnails, "MAX_TEXT_ICONS", 3)
    drain(widget, app)
    assert len(widget._thumbnails._images) == 3
    assert saved_rows(store.DB_PATH) == before
    assert presentations.load_deck(deck.paper_id, deck.mode).to_dict() == deck.to_dict()


def test_returning_to_a_figure_page_revalidates_actual_asset_bytes(deck_view):
    widget, deck, app, _root = deck_view
    drain(widget, app)
    value = presentations.deck_from_dict(deck.to_dict())
    value.sources.append(dict(id="figure:1", label="Chart", kind="figure", page=1))
    value.figures.append(dict(id="figure:1", label="Chart", caption="Chart", asset="chart.png"))
    value.slides[0].sources.append("figure:1")
    value.slides[0].elements = [dict(kind="figure", figure="figure:1", x=100, y=100,
                                    w=1000, h=450)]
    target = presentations._folder(deck.paper_id) / "assets" / "chart.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    def put(color):
        image = QImage(32, 24, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        assert image.save(str(target), "PNG")
    put("red")
    presentations.save_deck(value)
    widget.load(value.paper_id, value.paper_title)
    drain(widget, app)
    assert icon(widget).pixelColor(144, 81) == QColor("red")
    saved = presentations.load_deck(value.paper_id, value.mode).to_dict()
    rows = saved_rows(store.DB_PATH)
    widget.mode.setCurrentIndex(widget.mode.findData("notes"))
    put("blue")
    widget.mode.setCurrentIndex(widget.mode.findData("guide"))
    drain(widget, app)
    assert icon(widget).pixelColor(144, 81) == QColor("blue")
    assert saved_rows(store.DB_PATH) == rows
    assert presentations.load_deck(value.paper_id, value.mode).to_dict() == saved


def test_large_text_save_defers_icon_paint_but_keeps_saved_content(deck_view, monkeypatch):
    widget, deck, app, _root = deck_view
    drain(widget, app)
    # A page whose canvas holds more text than the small-icon limit (2,500 characters
    # in slide_thumbnails.render_selected_if_small), built only from valid fields:
    # one canvas text box within its 12,000-character limit, and bullets within
    # their per-line and per-page limits.
    value = presentations.deck_from_dict(deck.to_dict())
    value.slides[0].elements = slide_layout.elements_for(value.slides[0]) + [
        slide_layout.text_box("Long passage. " * 200, 56, 600, 1088, 60, 12)
    ]
    presentations.save_deck(value)
    widget.load(value.paper_id, value.paper_title)
    drain(widget, app)
    calls = track(monkeypatch)
    bullets = [f"Point {i}: " + "x" * 70 for i in range(1, 6)]
    widget.bullets.setPlainText("\n".join(bullets))
    assert widget.save_changes()
    assert calls == []
    saved = presentations.load_deck(deck.paper_id, deck.mode).to_dict()
    assert saved["slides"][0]["bullets"] == bullets
    assert sum(len(o.get("text", "")) for o in saved["slides"][0]["elements"]) > 2500
    drain(widget, app)
    assert calls == [(deck.paper_id, 0, "Page 1")]
    assert presentations.load_deck(deck.paper_id, deck.mode).to_dict() == saved
