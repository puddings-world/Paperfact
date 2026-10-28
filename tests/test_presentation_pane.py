"""Presentation editing, exports and late worker results stay on their paper."""

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from paper_daily import llm, presentations  # noqa: E402
from paper_daily.ai_types import Settings  # noqa: E402
from paper_daily.desktop import presentation_pane  # noqa: E402
from paper_daily.desktop.presentation_pane import PresentationPane  # noqa: E402


@pytest.fixture
def pane(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    if Path("C:/Windows/Fonts/msjh.ttc").exists():
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msjh.ttc")
        app.setFont(QFont("Microsoft JhengHei", 10))
    monkeypatch.setattr(presentations, "DECK_DIR", tmp_path / "decks")
    source = {"id": "original", "label": "原文第 2 頁", "kind": "original", "page": 2}
    slides = [
        presentations.Slide(
            f"段落 {i + 1}",
            "方法與證據",
            "本頁的核心理解",
            ["只呈現有原文支持的重點。"],
            "先交代背景，再說明方法如何處理問題。",
            ["original"],
        )
        for i in range(4)
    ]
    deck = presentations.Deck(
        "ref:paper",
        "測試論文",
        "論文導讀測試",
        "guide",
        "沒讀過這篇的研究者",
        15,
        slides,
        [source],
        [],
        [],
        "2026-10-12",
    )
    presentations.save_deck(deck)
    # Thumbnails are remembered by content for the whole session; each test starts cold.
    presentation_pane._thumbnails.clear()
    widget = PresentationPane()
    widget.load(deck.paper_id, deck.paper_title)
    yield widget, deck, app, tmp_path
    if widget.runner._thread:
        widget.runner._thread.quit()
        widget.runner._thread.wait(2000)
    widget.close()
    widget.deleteLater()
    # processEvents() alone does not deliver DeferredDelete without app.exec().
    # Otherwise an earlier canvas/shortcut can write into the next fixture's deck.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_hidden_deck_load_defers_thumbnails_until_the_tab_is_shown(pane, monkeypatch):
    widget, deck, app, _tmp = pane
    rendered = []
    monkeypatch.setattr(widget, "_thumbnail", rendered.append)
    widget.load(deck.paper_id, deck.paper_title, defer=True)
    assert widget.paper_id == deck.paper_id and widget.deck is None
    assert not rendered
    widget.show()
    drain(app, widget)
    assert widget.deck.paper_id == deck.paper_id
    assert sorted(rendered) == list(range(len(deck.slides)))
    widget.hide()


def drain(app, widget):
    for _ in range(500):
        app.processEvents()
        if not widget._thumbnail_timer.isActive():
            return


def drawn(widget, index):
    """A drawn thumbnail has the slide's blue edge; the placeholder is white."""
    image = widget.outline.item(index).icon().pixmap(QSize(288, 162)).toImage()
    edge = image.pixelColor(1, image.height() // 2)
    return edge.blue() > 150 and edge.red() < 100


def counting_thumbnail_loads(widget, monkeypatch):
    loads = []
    original = widget._thumbnail_canvas.load
    monkeypatch.setattr(
        widget._thumbnail_canvas, "load", lambda deck, i: (loads.append(i), original(deck, i))
    )
    return loads


def test_opening_a_deck_draws_its_thumbnails_after_showing_it(pane, monkeypatch):
    widget, deck, app, _tmp = pane
    presentation_pane._thumbnails.clear()
    monkeypatch.setattr(presentation_pane, "THUMBNAIL_BUDGET", 0)
    loads = counting_thumbnail_loads(widget, monkeypatch)
    widget._show_deck(None)
    widget.load(deck.paper_id, deck.paper_title)
    # Loading draws nothing itself; the list already holds every page, as placeholders.
    assert loads == [] and widget.outline.count() == len(deck.slides)
    assert not any(drawn(widget, i) for i in range(len(deck.slides)))
    app.processEvents()
    assert len(loads) < len(deck.slides)
    drain(app, widget)
    assert sorted(loads) == list(range(len(deck.slides)))
    assert all(drawn(widget, i) for i in range(len(deck.slides)))


def test_a_deck_seen_before_shows_its_thumbnails_at_once(pane, monkeypatch):
    widget, deck, app, _tmp = pane
    drain(app, widget)
    loads = counting_thumbnail_loads(widget, monkeypatch)
    widget.mode.setCurrentIndex(widget.mode.findData("notes"))
    widget.mode.setCurrentIndex(widget.mode.findData("guide"))
    assert all(drawn(widget, i) for i in range(len(deck.slides)))
    drain(app, widget)
    assert loads == []


def test_an_edited_or_moved_slide_gets_a_new_thumbnail(pane, monkeypatch):
    widget, deck, app, _tmp = pane
    drain(app, widget)
    loads = counting_thumbnail_loads(widget, monkeypatch)
    widget.slide_title.setText("新的標題")
    assert widget.save_changes()
    assert loads == [0]
    loads.clear()
    widget._move(1)
    drain(app, widget)
    # Only the two pages that changed place are drawn again: their page numbers moved.
    assert sorted(loads) == [0, 1]
    assert all(drawn(widget, i) for i in range(len(widget.deck.slides)))


def test_removing_a_slide_while_thumbnails_are_drawn_finishes_the_new_deck(pane, monkeypatch):
    widget, deck, app, _tmp = pane
    presentation_pane._thumbnails.clear()
    monkeypatch.setattr(presentation_pane, "THUMBNAIL_BUDGET", 0)
    widget._show_deck(presentations.load_deck(deck.paper_id, "guide"))
    app.processEvents()
    widget.outline.setCurrentRow(2)
    widget._remove()
    drain(app, widget)
    assert widget.outline.count() == len(deck.slides) - 1
    assert all(drawn(widget, i) for i in range(widget.outline.count()))


def test_editing_and_switching_modes_keeps_independent_decks(pane):
    widget, deck, _app, _tmp = pane
    widget.slide_title.setText("經過修改的標題")
    widget.speaker_notes.setPlainText("我的逐步講解")
    assert widget.save_changes()
    widget.mode.setCurrentIndex(widget.mode.findData("notes"))
    assert widget.deck is None
    widget.mode.setCurrentIndex(widget.mode.findData("guide"))
    assert widget.deck.slides[0].title == "經過修改的標題"
    assert widget.deck.slides[0].speaker_notes == "我的逐步講解"
    assert widget.deck.edited
    assert presentations.load_deck(deck.paper_id, "notes") is None


def test_invalid_edits_block_mode_switch_without_losing_saved_content(pane):
    widget, deck, _app, _tmp = pane
    widget.slide_title.clear()
    assert not widget.save_changes()
    widget.mode.setCurrentIndex(widget.mode.findData("notes"))
    assert widget.mode.currentData() == "guide"
    assert presentations.load_deck(deck.paper_id, "guide").slides[0].title == "段落 1"


def test_move_and_delete_are_saved_in_slide_order(pane):
    widget, deck, _app, _tmp = pane
    widget._move(1)
    saved = presentations.load_deck(deck.paper_id, "guide")
    assert [s.title for s in saved.slides[:2]] == ["段落 2", "段落 1"]
    widget._remove()
    saved = presentations.load_deck(deck.paper_id, "guide")
    assert len(saved.slides) == 3


def test_late_result_does_not_replace_the_paper_currently_on_screen(pane):
    widget, deck, _app, _tmp = pane
    other = presentations.deck_from_dict(deck.to_dict())
    other.paper_id = "ref:other"
    other.title = "另一篇論文的導讀"
    presentations.save_deck(other)
    widget.load(other.paper_id, other.paper_title)
    widget._generating = True
    widget._generated(json.dumps(deck.to_dict(), ensure_ascii=False))
    assert widget.paper_id == other.paper_id
    assert widget.deck.title == other.title
    assert "原論文" in widget.status.text()


def test_generation_uses_slides_profile_and_user_selected_sources(pane, monkeypatch):
    from PySide6.QtCore import QEventLoop, QTimer

    widget, deck, app, _tmp = pane
    cfg = Settings("gateway", model="research")
    monkeypatch.setattr(llm, "settings", lambda **kwargs: cfg)
    monkeypatch.setattr(llm, "available", lambda **kwargs: True)
    seen = {}

    def generate(paper_id, **kwargs):
        seen.update(kwargs)
        seen["paper_id"] = paper_id
        return deck, "ok"

    monkeypatch.setattr(presentations, "generate", generate)
    widget.inputs["notes"].setChecked(False)
    widget._generate()
    assert widget._generate_dialog is not None
    widget._generate_dialog.buttons()[0].click()
    assert not widget.generate_button.isEnabled()
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if not widget._generating else None)
    poll.start(10)
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
    app.processEvents()
    assert not widget._generating
    assert seen["cfg"] is cfg and seen["paper_id"] == deck.paper_id
    assert "notes" not in seen["inputs"]
    assert widget.deck.title == deck.title


def test_export_checkbox_omits_speaker_notes_and_preview_is_visible(pane, monkeypatch):
    from paper_daily.desktop import presentation_pane

    widget, _deck, app, tmp = pane
    dest = tmp / "talk.html"
    monkeypatch.setattr(
        presentation_pane.QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (str(dest), "HTML 投影片 (*.html)"),
    )
    monkeypatch.setattr(presentation_pane.QDesktopServices, "openUrl", lambda *a: True)
    widget.include_notes.setChecked(False)
    widget._export()
    assert dest.exists()
    assert "先交代背景" not in dest.read_text(encoding="utf-8")
    widget.resize(700, 850)
    widget.show()
    app.processEvents()
    assert "段落 1" in widget.preview.toPlainText()
    Path("build").mkdir(exist_ok=True)
    assert widget.grab().save("build/paperfact-presentation-pane.png")


def test_added_and_deleted_slides_can_be_undone(pane):
    widget, deck, _app, _tmp = pane
    widget._add()
    assert len(widget.deck.slides) == 5
    assert widget.deck.slides[1].title == "新投影片"
    widget._undo_edit()
    assert len(widget.deck.slides) == 4
    widget._remove()
    assert len(widget.deck.slides) == 3
    widget._undo_edit()
    assert [s.title for s in widget.deck.slides] == [s.title for s in deck.slides]


def test_pdf_export_writes_one_landscape_page_per_slide(pane):
    import pymupdf
    from PySide6.QtCore import QEventLoop, QTimer

    pytest.importorskip("PySide6.QtWebEngineCore")
    widget, deck, app, tmp = pane
    dest = tmp / "guide.pdf"
    widget._export_pdf(dest)
    assert widget._pdf_job is not None
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if widget._pdf_job is None else None)
    poll.start(20)
    QTimer.singleShot(20000, loop.quit)
    loop.exec()
    app.processEvents()
    assert widget._pdf_job is None, "PDF export timed out"
    assert dest.exists(), widget.status.text()
    with pymupdf.open(dest) as document:
        assert len(document) == len(deck.slides)
        assert all(page.rect.width > page.rect.height for page in document)
        assert all(page.get_text().strip() for page in document)


def test_canvas_text_drag_style_autosave_and_reload(pane):
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest

    widget, deck, app, _tmp = pane
    item = widget.canvas.objects[1]
    item.text.setPlainText("可直接編輯的標題")
    item.setPos(QPointF(80, 105))
    item.setSelected(True)
    widget.canvas.format_selected(size=34, color="#125599")
    QTest.qWait(1150)
    saved = presentations.load_deck(deck.paper_id, "guide")
    assert saved.slides[0].title == "可直接編輯的標題"
    obj = saved.slides[0].elements[1]
    assert (obj["x"], obj["y"], obj["size"], obj["color"]) == (80, 105, 34, "#125599")
    widget.outline.setCurrentRow(1)
    widget.outline.setCurrentRow(0)
    assert widget.canvas.objects[1].text.toPlainText() == "可直接編輯的標題"
    widget._undo_edit()
    assert widget.deck.slides[0].title == deck.slides[0].title


def test_canvas_native_double_click_edits_text_and_delete_removes_object(pane):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    widget, _deck, app, _tmp = pane
    widget.resize(1100, 850)
    widget.show()
    app.processEvents()
    view = widget.canvas.view
    item = widget.canvas.objects[1]
    pos = view.mapFromScene(item.sceneBoundingRect().center())
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert item.text.hasFocus()
    QTest.keyClick(view.viewport(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(view.viewport(), "Edited in canvas")
    QTest.keyClick(view.viewport(), Qt.Key.Key_Escape)
    assert item.text.toPlainText() == "Edited in canvas"
    item.setSelected(True)
    QTest.keyClick(view.viewport(), Qt.Key.Key_Delete)
    assert item not in widget.canvas.objects
    assert widget.save_changes()


def test_canvas_pdf_exports_changed_text(pane):
    import pymupdf
    from PySide6.QtTest import QTest

    widget, _deck, _app, tmp = pane
    widget.canvas.objects[1].text.setPlainText("Canvas export evidence")
    assert widget.save_changes()
    widget._export_pdf(tmp / "canvas.pdf")
    for _ in range(100):
        if widget._pdf_job is None:
            break
        QTest.qWait(20)
    with pymupdf.open(tmp / "canvas.pdf") as document:
        assert "Canvas export evidence" in document[0].get_text()


def test_export_defaults_to_pdf_and_paper_title(pane, monkeypatch):
    from paper_daily.desktop import presentation_pane

    widget, _deck, _app, tmp = pane
    widget.deck.paper_title = "Study: A/B?"
    seen = {}

    def choose(*args):
        seen["name"], seen["filters"] = args[2:4]
        return str(tmp / "chosen"), "PDF 投影片 (*.pdf)"

    monkeypatch.setattr(presentation_pane.QFileDialog, "getSaveFileName", choose)
    monkeypatch.setattr(widget, "_export_pdf", lambda dest: seen.update(dest=dest))
    widget._export()
    assert seen["filters"].startswith("PDF")
    assert seen["name"].startswith("Slides of - Study") and seen["name"].endswith(".pdf")
    assert not any(c in seen["name"] for c in ":/*?")
    assert seen["dest"] == tmp / "chosen.pdf"


def test_object_clipboard_delete_undo_redo_stays_on_current_slide(pane):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    widget, _deck, app, _tmp = pane
    widget.resize(1000, 850)
    widget.show()
    widget.outline.setCurrentRow(2)
    app.processEvents()
    view = widget.canvas.view
    view.setFocus()
    original = len(widget.canvas.objects)
    widget.canvas.objects[1].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert len(widget.canvas.objects) == original + 1
    QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert len(widget.canvas.objects) == original and widget._index == 2
    QTest.keyClick(view, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert len(widget.canvas.objects) == original + 1 and widget._index == 2
    QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert len(widget.canvas.scene.selectedItems()) == original + 1
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert len(widget.canvas.objects) == 0
    QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert len(widget.canvas.objects) == original + 1
    widget.canvas.select_all()
    QTest.keyClick(view, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
    assert len(widget.canvas.objects) == 0
    QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert len(widget.canvas.objects) == original + 1


def test_text_shortcuts_do_not_delete_or_select_canvas_objects(pane):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    widget, _deck, app, _tmp = pane
    widget.resize(1000, 850)
    widget.show()
    app.processEvents()
    view = widget.canvas.view
    item = widget.canvas.objects[1]
    point = view.mapFromScene(item.sceneBoundingRect().center())
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.keyClick(view.viewport(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(view.viewport(), "Clipboard text")
    QTest.keyClick(view.viewport(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(view.viewport(), Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
    assert item.text.toPlainText() == ""
    assert QApplication.clipboard().text() == "Clipboard text"
    QTest.keyClick(view.viewport(), Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert item.text.toPlainText() == "Clipboard text"
    QTest.keyClick(view.viewport(), Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert item.text.toPlainText() == ""
    QTest.keyClick(view.viewport(), Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert item.text.toPlainText() == "Clipboard text"
    assert len(widget.canvas.objects) == 4


def test_pending_generation_options_survive_slide_edits_and_undo(pane):
    widget, _deck, _app, _tmp = pane
    widget.count.setValue(18)
    widget.minutes.setValue(25)
    assert "重新產生" in widget.status.text()
    widget._add()
    widget._undo_edit()
    assert widget.count.value() == 18 and widget.minutes.value() == 25


def test_materials_insert_as_editable_table_figure_and_cited_text(pane, monkeypatch, tmp_path):
    from paper_daily import materials

    widget, deck, app, _tmp = pane
    folder = tmp_path / "figures" / "ref_paper"
    folder.mkdir(parents=True)
    monkeypatch.setattr(presentations, "FIG_DIR", tmp_path / "figures")
    import pymupdf

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
    pix.save(folder / "t1.png")
    found = materials.Materials(
        deck.paper_id,
        exhibits=[
            {
                "id": "figure:1",
                "file": "t1.png",
                "label": "Table 1",
                "caption": "Table 1 Results.",
                "page": 8,
                "kind": "table",
                "rows": [["Method", "Dice"], ["Ours", "0.754"]],
                "section": "4.3 Results",
            }
        ],
        headings=[{"text": "3 Method", "level": 1, "page": 4}],
        sentences=[{"text": "We propose SASVi.", "page": 2, "kind": "claim", "source": "original"}],
    )
    monkeypatch.setattr(materials, "collect", lambda paper_id: found)
    widget.materials_button.setChecked(True)
    assert widget.materials_panel.isVisible() or not widget.isVisible()
    tree = widget.materials_panel.tree
    assert tree.topLevelItem(0).text(0).startswith("圖表（1）")
    table_item = tree.topLevelItem(0).child(0).child(0)
    widget.materials_panel.chosen.emit(table_item.data(0, Qt.ItemDataRole.UserRole))
    widget.materials_panel.chosen.emit(
        tree.topLevelItem(0).child(0).data(0, Qt.ItemDataRole.UserRole)
    )
    widget._material_dropped(
        json.dumps(
            {"kind": "sentence", "text": "We propose SASVi.", "page": 2, "source": "original"}
        ),
        100.0,
        400.0,
    )
    assert widget.save_changes(), widget.status.text()
    saved = presentations.load_deck(deck.paper_id, "guide")
    kinds = [o["kind"] for o in saved.slides[0].elements]
    assert kinds.count("table") == 1 and kinds.count("figure") == 1
    table = next(o for o in saved.slides[0].elements if o["kind"] == "table")
    assert table["rows"] == [["Method", "Dice"], ["Ours", "0.754"]]
    quote = next(o for o in saved.slides[0].elements if o["kind"] == "text" and "p.2" in o["text"])
    assert (quote["x"], quote["y"]) == (100.0, 400.0)
    assert "figure:1" in saved.slides[0].sources and "original" in saved.slides[0].sources
    assert any(f["id"] == "figure:1" and f.get("asset") for f in saved.figures)


def test_ctrl_s_saves_structured_fields(pane):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    widget, deck, app, _tmp = pane
    widget.show()
    widget.activateWindow()
    widget.views.setCurrentIndex(2)
    widget.slide_title.setFocus()
    widget.slide_title.setText("Explicitly saved")
    app.processEvents()
    QTest.keyClick(widget.slide_title, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert presentations.load_deck(deck.paper_id, "guide").slides[0].title == "Explicitly saved"


def test_form_updates_canvas_immediately_preserving_geometry_and_extra_objects(pane):
    from copy import deepcopy

    from paper_daily.slide_layout import text_box

    widget, deck, _app, _tmp = pane
    title = widget.canvas.objects[1]
    title.setPos(90, 120)
    title.spec["color"] = "#123456"
    widget.canvas.add_object(text_box("自訂補充", 50, 500, 300, 80))
    assert widget.save_changes()
    before = deepcopy(widget.canvas.snapshot())
    widget.slide_title.setText("即時更新標題")
    after = widget.canvas.snapshot()
    assert after[1] == dict(before[1], text="即時更新標題")
    assert after[-1] == before[-1]
    assert "即時更新標題" in widget.preview.toPlainText()
    assert presentations.load_deck(deck.paper_id, deck.mode).slides[0].title != "即時更新標題"
    widget._save_canvas()
    assert presentations.load_deck(deck.paper_id, deck.mode).slides[0].title == "即時更新標題"


def test_partial_form_edit_is_visible_but_does_not_replace_saved_deck(pane):
    widget, deck, _app, _tmp = pane
    widget.slide_title.clear()
    assert next(o for o in widget.canvas.snapshot() if o.get("role") == "title")["text"] == ""
    assert not widget.save_changes()
    assert presentations.load_deck(deck.paper_id, deck.mode).slides[0].title == deck.slides[0].title
    widget.slide_title.setText("完成的標題")
    assert widget.save_changes()


def test_canvas_body_edit_is_reflected_in_form_and_survives_another_field_edit(pane):
    widget, _deck, _app, _tmp = pane
    body = next(o for o in widget.canvas.objects if o.spec.get("role") == "bullets")
    body.text.setPlainText("• 畫布編輯的重點")
    assert widget.bullets.toPlainText() == "畫布編輯的重點"
    widget.section.setText("新的章節")
    assert widget.save_changes()
    assert widget.deck.slides[0].bullets == ["畫布編輯的重點"]
    assert (
        next(o for o in widget.canvas.snapshot() if o.get("role") == "bullets")["text"]
        == "• 畫布編輯的重點"
    )


def test_regenerate_cancel_does_not_save_or_call_ai(pane, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    widget, deck, _app, _tmp = pane
    widget.slide_title.setText("尚在編輯")
    monkeypatch.setattr(widget, "_start_generation", lambda: pytest.fail("AI started on cancel"))
    widget._generate()
    box = widget._generate_dialog
    assert box.buttonRole(box.defaultButton()) == QMessageBox.ButtonRole.RejectRole
    assert not widget._generating
    box.defaultButton().click()
    assert widget._generate_dialog is None
    assert widget.slide_title.text() == "尚在編輯"
    assert presentations.load_deck(deck.paper_id, deck.mode).slides[0].title == deck.slides[0].title


def test_source_preview_uses_internal_navigation(pane):
    from PySide6.QtCore import QUrl

    widget, _deck, _app, _tmp = pane
    seen = []
    widget.source_requested.connect(seen.append)
    assert not widget.preview.openExternalLinks()
    assert not widget.preview.openLinks()
    assert "paperfact-source:original" in widget.preview.toHtml()
    widget.preview.anchorClicked.emit(QUrl("paperfact-source:original"))
    assert seen[0]["page"] == 2
    widget._open_source(QUrl("https://example.com"))
    assert len(seen) == 1


def test_form_figure_replacement_preserves_geometry_without_duplicate_figures(pane):
    widget, _deck, _app, _tmp = pane
    for number in (1, 2, 3):
        sid = f"figure:{number}"
        widget.deck.figures.append(dict(id=sid, file=f"{number}.png", label=sid))
        widget.deck.sources.append(dict(id=sid, label=sid, kind="figure"))
        widget._add_source_item(sid, sid)
        widget.figure.addItem(sid, sid)
    widget.figure.setCurrentIndex(1)
    fig = next(o for o in widget.canvas.objects if o.spec["kind"] == "figure")
    fig.setPos(500, 300)
    widget.figure.setCurrentIndex(2)
    widget.figure.setCurrentIndex(3)
    figures = [o for o in widget.canvas.snapshot() if o["kind"] == "figure"]
    assert len(figures) == 1 and figures[0]["figure"] == "figure:3"
    assert (figures[0]["x"], figures[0]["y"]) == (500, 300)
    assert "原圖讀取失敗" in widget.preview.toPlainText()
    widget.figure.setCurrentIndex(0)
    assert not any(o["kind"] == "figure" for o in widget.canvas.snapshot())
