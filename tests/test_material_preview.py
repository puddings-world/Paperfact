"""Material previews show actual content and panel toggles follow visible state."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage, QTextDocument
from test_presentation_pane import pane as _pane_fixture

from paper_daily import materials
from paper_daily.fetch import _safe_name

pane = _pane_fixture


def test_exhibit_preview_loads_image_and_fits_resizing_without_editing_deck(pane, monkeypatch):
    widget, deck, app, tmp = pane
    monkeypatch.setattr(materials, "FIG_DIR", tmp / "figures")
    folder = materials.FIG_DIR / _safe_name(deck.paper_id)
    folder.mkdir(parents=True)
    image = QImage(1200, 500, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.green)
    image.save(str(folder / "table.png"))
    panel = widget.materials_panel
    panel.load(
        materials.Materials(
            deck.paper_id,
            exhibits=[
                dict(
                    id="figure:1",
                    file="table.png",
                    label="Table 4",
                    caption="Actual table caption",
                    page=7,
                    rows=[["Name", "Result"], ["A", "42"], ["B", "73"]],
                )
            ],
        )
    )
    panel.resize(400, 700)
    panel.show()
    app.processEvents()
    panel._render_preview()
    assert not panel._preview_image.isNull()
    resource = panel.detail.document().resource(
        QTextDocument.ResourceType.ImageResource, QUrl("paperfact-material:preview")
    )
    assert isinstance(resource, QImage) and resource.width() == 1200
    assert "Actual table caption" in panel.detail.toPlainText()
    assert "73" in panel.detail.toPlainText() and "放大原圖" in panel.detail.toPlainText()
    assert "核對原圖" in panel.detail.toPlainText()
    panel._open_preview_image(QUrl("paperfact:full-image"))
    assert panel._image_dialog.isVisible()
    panel._image_dialog.close()
    app.processEvents()
    assert panel._image_dialog is None
    assert widget.deck.to_dict() == deck.to_dict() and not widget._dirty


def test_table_child_shows_every_cell_and_escapes_markup(pane):
    widget, deck, app, tmp = pane
    panel = widget.materials_panel
    panel.load(
        materials.Materials(
            deck.paper_id,
            exhibits=[
                dict(
                    id="figure:1",
                    file="missing.png",
                    label="Table 4",
                    caption="Caption",
                    page=7,
                    rows=[
                        ["Name", "Value"],
                        ["<img src='https://example.org/track'>", "Last cell"],
                    ],
                )
            ],
        )
    )
    parent = panel.tree.topLevelItem(0).child(0)
    assert "找不到" in panel.detail.toPlainText()
    panel.tree.setCurrentItem(parent.child(0))
    text = panel.detail.toPlainText()
    assert "Last cell" in text and "<img src=" in text
    assert panel._preview_image.isNull()
    assert "<img src=" not in panel.detail.toHtml()


def test_detail_splitter_collapse_and_toggle_restore_agree(pane):
    widget, deck, app, tmp = pane
    widget.resize(1200, 800)
    widget.show()
    widget.materials_button.setChecked(True)
    app.processEvents()
    panel = widget.materials_panel
    panel.details_split.setSizes([400, 0])
    panel._sync_detail_toggle()
    assert not panel.detail_toggle.isChecked()
    panel.detail_toggle.click()
    app.processEvents()
    assert panel.detail_toggle.isChecked() and panel.details_split.sizes()[1] > 50
    panel.detail_toggle.click()
    assert panel.detail.isHidden()
    panel.detail_toggle.click()
    assert not panel.detail.isHidden()


def test_bold_state_follows_selection_and_normalizes_mixed_text(pane):
    widget, deck, app, tmp = pane
    canvas = widget.canvas
    assert not canvas.bold.isEnabled()
    title = canvas.objects[1]
    body = next(o for o in canvas.objects if o.text and not o.spec.get("bold"))
    title.setSelected(True)
    assert canvas.bold.isChecked()
    body.setSelected(True)
    assert not canvas.bold.isChecked() and "混合" in canvas.bold.toolTip()
    canvas.bold.click()
    assert title.spec["bold"] and body.spec["bold"] and canvas.bold.isChecked()
    canvas.bold.click()
    assert not title.spec["bold"] and not body.spec["bold"] and not canvas.bold.isChecked()
    canvas.scene.clearSelection()
    assert not canvas.bold.isEnabled()
