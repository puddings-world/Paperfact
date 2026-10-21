"""Exercise material gestures through Qt events, not direct insertion callbacks."""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from test_presentation_pane import pane as _pane_fixture

from paper_daily import materials

pane = _pane_fixture


def setup_material(pane):
    widget, deck, app, _tmp = pane
    widget.resize(1300, 850)
    widget.show()
    widget.materials_button.setChecked(True)
    widget.materials_panel.load(
        materials.Materials(
            deck.paper_id, sentences=[dict(text="Original evidence quote", page=2, kind="evidence")]
        )
    )
    tree = widget.materials_panel.tree
    item = tree.topLevelItem(2).child(0)
    tree.setCurrentItem(item)
    tree.scrollToItem(item)
    app.processEvents()
    return widget, app, tree, item


def test_double_click_material_row_inserts_selects_and_saves(pane):
    widget, app, tree, item = setup_material(pane)
    before = len(widget.canvas.objects)
    point = tree.visualItemRect(item).center()
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
    app.processEvents()
    assert len(widget.canvas.objects) == before + 1
    assert widget.canvas.objects[-1].isSelected()
    assert "Original evidence quote" in widget.canvas.objects[-1].text.toPlainText()
    assert widget.save_changes()


@pytest.mark.parametrize("target", ["canvas", "title", "bullets", "preview", "notes"])
def test_drop_material_into_each_content_view(pane, target):
    widget, app, tree, item = setup_material(pane)
    if target == "canvas":
        widget.views.setCurrentIndex(0)
        surface = widget.canvas.view.viewport()
    elif target == "preview":
        widget.views.setCurrentIndex(1)
        surface = widget.preview.viewport()
    elif target == "notes":
        widget.views.setCurrentIndex(3)
        surface = widget.speaker_notes.viewport()
    else:
        widget.views.setCurrentIndex(2)
        surface = widget.slide_title if target == "title" else widget.bullets.viewport()
    app.processEvents()
    before = len(widget.canvas.objects)
    old_title = widget.slide_title.text()
    old_notes = widget.speaker_notes.toPlainText()
    mime = tree.mimeData([item])
    pos = QPoint(40, 40)
    enter = QDragEnterEvent(
        pos,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(surface, enter)
    assert enter.isAccepted()
    move = QDragMoveEvent(
        pos,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(surface, move)
    assert move.isAccepted()
    drop = QDropEvent(
        QPointF(pos),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(surface, drop)
    assert drop.isAccepted()
    assert widget.views.currentIndex() == 0
    assert len(widget.canvas.objects) == before + 1
    assert widget.canvas.objects[-1].isSelected()
    assert widget.slide_title.text() == old_title
    assert widget.speaker_notes.toPlainText() == old_notes
    assert widget.save_changes()


def test_insert_button_reports_blocked_edits_beside_materials(pane):
    widget, app, tree, item = setup_material(pane)
    widget.slide_title.clear()
    before = len(widget.canvas.objects)
    widget.materials_panel.insert_button.click()
    assert len(widget.canvas.objects) == before
    assert not widget.materials_panel.feedback.isHidden()
    assert "未儲存" in widget.materials_panel.feedback.text()
    widget.slide_title.setText("Valid title")
    widget.materials_panel.insert_button.click()
    assert len(widget.canvas.objects) == before + 1
    assert "已加入" in widget.materials_panel.feedback.text()


def test_double_click_figure_preview_inserts_image(pane, monkeypatch, tmp_path):
    from PySide6.QtGui import QColor, QImage

    from paper_daily import presentations
    from paper_daily.fetch import _safe_name

    widget, deck, app, _tmp = pane
    folder = tmp_path / "figures" / _safe_name(deck.paper_id)
    folder.mkdir(parents=True)
    image = QImage(240, 100, QImage.Format.Format_RGB32)
    image.fill(QColor("#345678"))
    image.save(str(folder / "preview.png"))
    monkeypatch.setattr(materials, "FIG_DIR", folder.parent)
    monkeypatch.setattr(presentations, "FIG_DIR", folder.parent)
    widget.resize(1300, 850)
    widget.show()
    widget.materials_button.setChecked(True)
    panel = widget.materials_panel
    panel.load(
        materials.Materials(
            deck.paper_id,
            exhibits=[
                dict(
                    id="figure:preview",
                    file="preview.png",
                    label="Figure 1",
                    page=2,
                    caption="Evidence",
                )
            ],
        )
    )
    app.processEvents()
    points = [
        QPoint(x, y)
        for y in range(10, panel.detail.viewport().height(), 10)
        for x in range(10, panel.detail.viewport().width(), 10)
    ]
    point = next(
        p for p in points if panel.detail.cursorForPosition(p).charFormat().isImageFormat()
    )
    before = len(widget.canvas.objects)
    QTest.mouseDClick(panel.detail.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert len(widget.canvas.objects) == before + 1
    assert widget.canvas.objects[-1].spec["kind"] == "figure"
    assert widget.canvas.objects[-1].isSelected()
    assert widget.save_changes()
