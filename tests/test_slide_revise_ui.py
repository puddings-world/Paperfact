import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from test_presentation_pane import pane as pane_fixture

from paper_daily import presentations, slide_revise
from paper_daily.ai_types import Completion

pane = pane_fixture


def setup_revision(pane, monkeypatch, success=True):
    widget, deck, app, tmp = pane
    monkeypatch.setattr(presentations, "FIG_DIR", tmp / "figures")
    folder = tmp / "figures" / "ref_paper"
    folder.mkdir(parents=True)
    image = QImage(300, 100, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    image.save(str(folder / "table.png"))
    widget.deck.sources += [
        dict(id="page:4", kind="original", label="p4", page=4),
        dict(id="figure:2", kind="figure", label="Table 2", page=4),
    ]
    widget.deck.figures = [
        dict(id="figure:2", label="Table 2", file="table.png", caption="Results")
    ]
    monkeypatch.setattr(
        slide_revise, "evidence", lambda d: dict(sources=d.sources, figures=d.figures)
    )
    monkeypatch.setattr(
        slide_revise.llm,
        "complete_result",
        lambda *a, **kw: Completion(
            json.dumps(
                dict(
                    slide=dict(
                        title="Clinical result",
                        section="Results",
                        takeaway="New result",
                        bullets=["A measured result"],
                        sources=["page:4", "figure:2"],
                        figure="figure:2",
                        speaker_notes="Explain the evidence",
                    ),
                    summary="Revised for clinicians",
                )
            )
            if success
            else None,
            reason="test unavailable" if not success else "ok",
        ),
    )
    callbacks = {}
    monkeypatch.setattr(
        widget.runner,
        "start",
        lambda prompt, done, fail, **kw: callbacks.update(done=done, fail=fail, **kw),
    )
    widget.resize(1350, 900)
    widget.show()
    widget.canvas.revise_instruction.setPlainText("改給臨床醫師聽，換成 Table 2")
    app.processEvents()
    return widget, callbacks, app


def finish(callbacks):
    answer, reason = callbacks["call"]("")
    callbacks["done"](answer) if answer is not None else callbacks["fail"](reason)


def test_revise_replaces_sources_figure_layout_and_can_undo_redo(pane, monkeypatch):
    widget, callbacks, app = setup_revision(pane, monkeypatch)
    widget.canvas.objects[0].moveBy(50, 30)
    widget._canvas_changed()
    assert widget.save_changes()
    before = widget.deck.to_dict()
    widget.canvas.revise_button.click()
    assert widget._revising and not widget.canvas.revise_button.isEnabled()
    finish(callbacks)
    assert widget.deck.slides[0].title == "Clinical result", widget.status.text()
    assert widget.deck.slides[0].figure == "figure:2"
    assert set(widget.deck.slides[0].sources) == {"figure:2", "page:4"}
    assert widget.deck.slides[0].elements is None
    assert widget.deck.to_dict()["slides"][1:] == before["slides"][1:]
    assert "Clinical result" in widget.preview.toPlainText()
    assert presentations.load_deck(widget.paper_id, "guide").slides[0].title == "Clinical result"
    app.processEvents()
    widget.canvas.view.setFocus()
    QTest.keyClick(widget.canvas.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert widget.deck.to_dict() == before
    QTest.keyClick(widget.canvas.view, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert widget.deck.slides[0].title == "Clinical result"


def test_failed_revise_keeps_the_entire_original(pane, monkeypatch):
    widget, callbacks, app = setup_revision(pane, monkeypatch, success=False)
    before = widget.deck.to_dict()
    widget.canvas.revise_button.click()
    finish(callbacks)
    assert widget.deck.to_dict() == before
    assert "test unavailable" in widget.status.text()
    assert widget.canvas.revise_button.isEnabled()


@pytest.mark.parametrize("switch", ["page", "paper", "edit"])
def test_late_revision_cannot_replace_a_different_target(pane, monkeypatch, switch):
    widget, callbacks, app = setup_revision(pane, monkeypatch)
    widget.canvas.revise_button.click()
    if switch == "page":
        widget._selected(1)
    elif switch == "paper":
        widget.paper_id = "another-paper"
    else:
        widget.slide_title.setText("New manual edit")
        widget._dirty = True
    before = widget.deck.to_dict()
    finish(callbacks)
    assert widget.deck.to_dict() == before


def test_canvas_standard_clipboard_select_delete_and_undo_shortcuts(pane):
    widget, deck, app, _tmp = pane
    widget.resize(1300, 850)
    widget.show()
    app.processEvents()
    canvas = widget.canvas
    canvas.view.setFocus()
    canvas.scene.clearSelection()
    canvas.objects[0].setSelected(True)
    count = len(canvas.objects)
    ctrl = Qt.KeyboardModifier.ControlModifier
    QTest.keyClick(canvas.view, Qt.Key.Key_C, ctrl)
    QTest.keyClick(canvas.view, Qt.Key.Key_V, ctrl)
    assert len(canvas.objects) == count + 1
    QTest.keyClick(canvas.view, Qt.Key.Key_X, ctrl)
    assert len(canvas.objects) == count
    QTest.keyClick(canvas.view, Qt.Key.Key_V, ctrl)
    assert len(canvas.objects) == count + 1
    QTest.keyClick(canvas.view, Qt.Key.Key_Delete)
    assert len(canvas.objects) == count
    assert widget.save_changes()
    QTest.keyClick(canvas.view, Qt.Key.Key_Z, ctrl)
    assert len(canvas.objects) == count + 1
    QTest.keyClick(canvas.view, Qt.Key.Key_Y, ctrl)
    assert len(canvas.objects) == count
    QTest.keyClick(canvas.view, Qt.Key.Key_A, ctrl)
    assert len(canvas.scene.selectedItems()) == count
    QTest.keyClick(canvas.view, Qt.Key.Key_Delete)
    assert not canvas.objects
    QTest.keyClick(canvas.view, Qt.Key.Key_Z, ctrl)
    assert len(canvas.objects) == count
    QTest.keyClick(canvas.view, Qt.Key.Key_Y, ctrl)
    assert not canvas.objects
    # The copy above left the canvas's data on the system clipboard; offscreen Qt
    # crashes flushing it at interpreter exit, after every test has passed.
    app.clipboard().clear()
    app.processEvents()
