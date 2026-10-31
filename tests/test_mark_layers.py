"""AI marks and your own marks are separate layers you can show or hide per paper."""

from dataclasses import replace

from test_manual_highlight_ops import QUOTE, ai
from test_manual_highlight_ui import loaded as _loaded
from test_manual_highlight_ui import select
from test_research_generation import rows
from test_research_generation import workspace as _workspace

from paper_daily.desktop import ui_state

workspace, loaded = _workspace, _loaded


def _both_layers(w):
    select(w).highlight.emit()
    ai(w.widget._highlight_view)
    w.widget._load_highlights(w.paper.pdf_path)
    return w.widget.pdf.selection


def _shown(selection):
    return sorted(selection.layer(record) for record, _words in selection._marks)


def test_hiding_a_layer_leaves_the_other_and_deletes_nothing(loaded):
    w = loaded
    selection = _both_layers(w)
    stored = rows(w.database, "SELECT quote FROM pdf_highlights")
    assert _shown(selection) == ["ai", "mine"]

    w.widget.layer_actions["ai"].setChecked(False)
    assert _shown(selection) == ["mine"]
    assert w.widget.layers_button.text() == "顯示標記：只有我的"
    # A hidden mark cannot be picked, so erasing the passage only touches what is shown.
    assert all(mark > 0 for mark in select(w).selected_highlights())

    w.widget.layer_actions["mine"].setChecked(False)
    assert _shown(selection) == []
    # The counts still describe what is stored, and say what is out of sight.
    status = w.widget.highlight_status.text()
    assert "AI 1 段" in status and "AI 已隱藏" in status and "手動已隱藏" in status

    w.widget.layer_actions["ai"].setChecked(True)
    w.widget.layer_actions["mine"].setChecked(True)
    assert _shown(selection) == ["ai", "mine"]
    assert rows(w.database, "SELECT quote FROM pdf_highlights") == stored == [{"quote": QUOTE}]
    assert rows(w.database, "SELECT hidden FROM pdf_ai_highlights") == [{"hidden": 0}]


def test_the_choice_is_remembered_for_that_paper(loaded):
    w = loaded
    w.widget.win.remember = lambda key, value: ui_state.save(f"ui.{key}", value)
    selection = _both_layers(w)
    w.widget.layer_actions["ai"].setChecked(False)
    ui_state.flush()

    w.widget._show_layers(set())
    w.widget._load_highlights(w.paper.pdf_path)
    assert _shown(selection) == ["mine"]
    assert not w.widget.layer_actions["ai"].isChecked()

    paper = w.widget.paper
    w.widget.paper = replace(paper, id="another-paper")
    try:
        assert w.widget._restore_layers() == set()
    finally:
        w.widget.paper = paper


def test_turning_on_the_pen_shows_your_own_marks(loaded):
    w = loaded
    selection = _both_layers(w)
    w.widget.layer_actions["mine"].setChecked(False)
    w.widget.highlight_button.setChecked(True)
    assert _shown(selection) == ["ai", "mine"]


def test_reveal_lands_on_the_passage_a_search_result_points_at(loaded):
    import json

    w = loaded
    selection = w.widget.pdf.selection
    anchor = json.dumps(selection.find(0, QUOTE))
    selection.clear()
    w.widget.reveal(anchor, 1)
    assert selection.selected_text() == QUOTE
    assert "第 1 頁" in w.widget.pdf_note.text()


def test_the_ruler_dims_all_but_the_lines_under_the_pointer(loaded):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from paper_daily.desktop import pdfselect

    selection = loaded.widget.pdf.selection
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(50, 200),
        QPointF(50, 200),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    selection.mouseMoveEvent(move)
    assert selection.ruler_band() is None
    selection.set_ruler(True)
    selection.mouseMoveEvent(move)
    top, bottom = selection.ruler_band()
    assert top < 200 < bottom and bottom - top == pdfselect.RULER_HEIGHT
    # Above the band is dimmed; inside it the page shows as it is.
    frame = loaded.widget.pdf.grab().toImage()
    origin = selection.mapTo(loaded.widget.pdf, selection.rect().topLeft())
    above = frame.pixelColor(origin.x() + 5, origin.y() + top - 10).lightness()
    inside = frame.pixelColor(origin.x() + 5, origin.y() + 200).lightness()
    assert above < inside
    selection.set_ruler(False)
    assert selection.ruler_band() is None
