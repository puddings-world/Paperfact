"""Resizing and view navigation must not alter slide content or lose panel state."""

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_presentation_pane import pane as _pane_fixture

from paper_daily import materials
from paper_daily.desktop import presentation_pane

pane = _pane_fixture


def show_workspace(pane, monkeypatch):
    widget, deck, app, tmp = pane
    monkeypatch.setattr(
        presentation_pane.materials, "collect", lambda pid: materials.Materials(pid)
    )
    widget.resize(1310, 795)
    widget.show()
    widget.materials_button.setChecked(True)
    app.processEvents()
    return widget, app


def test_panels_resize_and_toggle_independently(pane, monkeypatch):
    widget, app = show_workspace(pane, monkeypatch)
    widget._split.setSizes([260, 580, 420])
    widget.materials_panel.details_split.setSizes([100, 350])
    app.processEvents()
    assert widget._split.sizes()[0] > 200 and widget._split.sizes()[2] > 360
    assert widget.materials_panel.detail.height() > 180
    widget.outline_button.setChecked(False)
    assert widget._outline_panel.isHidden() and widget.materials_button.isChecked()
    assert widget.outline_button.text().endswith("關")
    widget.materials_button.setChecked(False)
    assert widget.materials_panel.isHidden()
    widget.outline_button.setChecked(True)
    widget.materials_button.setChecked(True)
    assert widget.outline_button.text().endswith("開")
    assert widget.materials_button.text().endswith("開")
    assert widget.workspace_state()["panels"] == dict(settings=False, outline=True, materials=True)


def test_zoom_survives_resize_and_slide_navigation_without_editing(pane, monkeypatch):
    widget, app = show_workspace(pane, monkeypatch)
    view = widget.canvas.view
    before = widget.deck.to_dict()
    widget.canvas.zoom.setValue(150)
    assert not view.fit_mode and abs(view.transform().m11() - 1.5) < 0.01
    widget.resize(1100, 700)
    widget._split.setSizes([190, 540, 280])
    widget.outline.setCurrentRow(1)
    app.processEvents()
    assert abs(view.transform().m11() - 1.5) < 0.01
    assert widget.deck.to_dict() == before and not widget._dirty
    widget.canvas.fit_button.click()
    app.processEvents()
    assert view.fit_mode and view.transform().m11() < 1.5


def test_ctrl_wheel_and_middle_drag_change_view_only(pane, monkeypatch):
    widget, app = show_workspace(pane, monkeypatch)
    view = widget.canvas.view
    before = widget.canvas.snapshot()
    center = view.viewport().rect().center()
    wheel = QWheelEvent(
        QPointF(center),
        QPointF(view.viewport().mapToGlobal(center)),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    old_scale = view.transform().m11()
    app.sendEvent(view.viewport(), wheel)
    assert not view.fit_mode and view.transform().m11() > old_scale
    view.set_zoom(200)
    app.processEvents()
    old_scroll = (view.horizontalScrollBar().value(), view.verticalScrollBar().value())
    QTest.mousePress(view.viewport(), Qt.MouseButton.MiddleButton, pos=center)
    QTest.mouseMove(view.viewport(), center - QPoint(40, 30))
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.MiddleButton, pos=center - QPoint(40, 30))
    assert old_scroll != (view.horizontalScrollBar().value(), view.verticalScrollBar().value())
    assert widget.canvas.snapshot() == before and not widget._dirty


def test_workspace_roundtrip_and_narrow_window_keep_controls_accessible(pane, monkeypatch):
    widget, app = show_workspace(pane, monkeypatch)
    widget.canvas.view.set_zoom(125)
    widget.materials_panel.detail_toggle.setChecked(False)
    widget._split.setSizes([210, 600, 330])
    state = widget.workspace_state()
    widget._reset_workspace()
    widget.restore_workspace(state)
    app.processEvents()
    assert widget.materials_button.isChecked() and widget.materials_panel.detail.isHidden()
    assert widget.canvas.zoom.value() == 125 and not widget.canvas.view.fit_mode
    widget.materials_button.setChecked(False)
    widget.resize(695, 600)
    app.processEvents()
    assert widget.width() == 695
    assert widget.canvas.view.viewport().width() > 200
    widget.settings_button.setChecked(True)
    assert not widget.settings_panel.isHidden()
    assert widget.settings_panel.widgetResizable()


def test_open_materials_reload_when_parent_tab_is_hidden(pane, monkeypatch):
    widget, deck, app, tmp = pane
    loaded = []

    def collect(pid):
        loaded.append(pid)
        return materials.Materials(pid)

    monkeypatch.setattr(presentation_pane.materials, "collect", collect)
    widget.materials_button.setChecked(True)
    loaded.clear()
    assert not widget.materials_panel.isVisible()
    widget.load("another-paper", "Another paper")
    assert loaded == ["another-paper"]


def test_left_right_views_preserve_text_caret_and_object_movement(pane, monkeypatch):
    widget, app = show_workspace(pane, monkeypatch)
    widget.activateWindow()
    view = widget.canvas.view
    view.setFocus()
    app.processEvents()
    QTest.keyClick(view, Qt.Key.Key_Right)
    assert widget.views.currentIndex() == 1
    QTest.keyClick(widget.views.tabBar(), Qt.Key.Key_Right)
    assert widget.views.currentIndex() == 2
    widget.slide_title.setFocus()
    widget.slide_title.setCursorPosition(2)
    QTest.keyClick(widget.slide_title, Qt.Key.Key_Left)
    assert widget.views.currentIndex() == 2 and widget.slide_title.cursorPosition() == 1
    QTest.keyClick(widget.slide_title, Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier)
    assert widget.views.currentIndex() == 3
    widget.speaker_notes.setFocus()
    QTest.keyClick(widget.speaker_notes, Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier)
    assert widget.views.currentIndex() == 0
    item = widget.canvas.objects[1]
    item.setSelected(True)
    view.setFocus()
    x = item.x()
    QTest.keyClick(view, Qt.Key.Key_Right)
    assert widget.views.currentIndex() == 0 and item.x() == x + 1
    point = view.mapFromScene(item.sceneBoundingRect().center())
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.keyClick(view, Qt.Key.Key_Left)
    assert widget.views.currentIndex() == 0 and item.x() == x + 1


def test_reset_panels_does_not_change_pending_slide_edits(pane, monkeypatch):
    widget, app = show_workspace(pane, monkeypatch)
    widget.canvas.objects[1].text.setPlainText("Pending title")
    before = widget.canvas.snapshot()
    widget.canvas.view.set_zoom(180)
    widget.outline_button.setChecked(False)
    widget._reset_workspace()
    assert widget.canvas.snapshot() == before and widget._dirty
    assert widget.canvas.view.fit_mode
    assert widget.outline_button.isChecked() and not widget.materials_button.isChecked()


def test_source_row_selection_does_not_change_citations_and_invalid_checks_are_reverted(pane):
    widget, deck, app, tmp = pane
    first = widget._source_items[0]
    first.setSelected(True)
    assert not widget._dirty and widget._checked_sources() == ["original"]
    first.setCheckState(0, Qt.CheckState.Unchecked)
    assert first.checkState(0) == Qt.CheckState.Checked and not widget._dirty
    assert "至少" in widget.status.text()
    for i in range(8):
        sid = f"ref:{i}"
        widget.deck.sources.append(dict(id=sid, label=sid, kind="citation"))
        widget._add_source_item(sid, sid)
        widget._source_items[i + 1].setCheckState(0, Qt.CheckState.Checked)
    assert len(widget._checked_sources()) == 8
    assert widget._source_items[8].checkState(0) == Qt.CheckState.Unchecked
    assert "最多" in widget.status.text()
    assert widget.save_changes()
    first.setCheckState(0, Qt.CheckState.Unchecked)
    assert len(widget._checked_sources()) == 7 and widget.save_changes()


def test_material_at_source_limit_is_rejected_without_mutating_deck_or_canvas(pane):
    widget, deck, app, tmp = pane
    for i in range(7):
        sid = f"ref:{i}"
        widget.deck.sources.append(dict(id=sid, label=sid, kind="citation"))
        widget._add_source_item(sid, sid)
        widget._source_items[i + 1].setCheckState(0, Qt.CheckState.Checked)
    assert widget.save_changes()
    before, canvas = widget.deck.to_dict(), widget.canvas.snapshot()
    widget._insert_material(dict(kind="sentence", text="Original evidence", page=7))
    assert widget.deck.to_dict() == before and widget.canvas.snapshot() == canvas
    assert "8 個" in widget.status.text() and not widget._dirty


def test_invalid_edits_can_be_recovered_without_overwriting_saved_deck(pane):
    from paper_daily import presentations

    widget, deck, app, tmp = pane
    widget.outline.setCurrentRow(2)
    widget.bullets.setPlainText("")
    widget.speaker_notes.setPlainText("Unsaved explanation")
    assert not widget.save_changes()
    widget.save_recovery()
    assert presentations.load_deck(deck.paper_id, "guide").slides[2].bullets
    widget.load(deck.paper_id, deck.paper_title)
    assert widget._index == 2 and widget._dirty
    assert widget.bullets.toPlainText() == ""
    assert widget.speaker_notes.toPlainText() == "Unsaved explanation"
    widget.bullets.setPlainText("Repaired evidence")
    assert widget.save_changes()
    assert not widget._recovery_path().exists()
    saved = presentations.load_deck(deck.paper_id, "guide")
    assert saved.slides[2].speaker_notes == "Unsaved explanation"


def test_google_main_button_authorizes_and_includes_notes_even_when_other_exports_do_not(
    pane, monkeypatch
):
    from paper_daily import google_slides

    widget, deck, app, tmp = pane
    seen = {}
    monkeypatch.setattr(google_slides, "read_client", lambda: {})
    monkeypatch.setattr(google_slides, "authorize", lambda: "session")
    monkeypatch.setattr(
        google_slides,
        "export_copy",
        lambda deck, session, **opts: (
            seen.update(session=session, **opts)
            or "https://docs.google.com/presentation/d/test/edit"
        ),
    )
    monkeypatch.setattr(
        presentation_pane.QDesktopServices, "openUrl", lambda url: seen.update(url=url.toString())
    )

    def start(prompt, done, failed, *, call):
        value, reason = call(prompt)
        assert reason == "ok"
        done(value)

    monkeypatch.setattr(widget.runner, "start", start)
    widget.include_notes.setChecked(False)
    widget.google_button.click()
    assert seen["session"] == "session" and seen["include_notes"] is True
    assert seen["url"].endswith("/test/edit") and not widget._cloud_busy


def test_close_invalid_edits_offers_nonblocking_recovery_and_reopens_editor(pane):
    from PySide6.QtWidgets import QMessageBox, QStackedWidget, QTabWidget, QVBoxLayout, QWidget

    from paper_daily.desktop.main import MainWindow

    widget, deck, app, tmp = pane

    class Window(MainWindow):
        def __init__(self):
            QWidget.__init__(self)
            self.stack = QStackedWidget(self)
            QVBoxLayout(self).addWidget(self.stack)
            self.reader_page = QWidget()
            self.reader_page.presentation_pane = widget
            self.reader_page.tabs = QTabWidget(self.reader_page)
            self.reader_page.tabs.addTab(widget, "簡報")
            self.stack.addWidget(QWidget())
            self.stack.addWidget(self.reader_page)
            self.remember = lambda *args: None

    window = Window()
    window.show()
    app.processEvents()
    widget.bullets.setPlainText("")
    assert not window.close()
    app.processEvents()
    dialog = window._close_dialog
    assert dialog.isVisible() and window.isVisible()
    back = next(
        b for b in dialog.buttons() if dialog.buttonRole(b) == QMessageBox.ButtonRole.RejectRole
    )
    back.click()
    app.processEvents()
    assert window.isVisible() and window.stack.currentWidget() is window.reader_page
    assert widget.views.currentIndex() == 2
    window.close()
    app.processEvents()
    dialog = window._close_dialog
    keep = next(
        b for b in dialog.buttons() if dialog.buttonRole(b) == QMessageBox.ButtonRole.AcceptRole
    )
    keep.click()
    app.processEvents()
    assert not window.isVisible() and widget._recovery_path().exists()
    widget.setParent(None)
    window.deleteLater()


def test_figure_evidence_cannot_be_unchecked_while_used(pane):
    widget, deck, app, tmp = pane
    widget.deck.figures.append(dict(id="fig:1", file="figure.png", label="Figure 1"))
    widget.deck.sources.append(dict(id="fig:1", label="Figure 1", kind="figure"))
    widget._add_source_item("fig:1", "Figure 1")
    source = widget._source_items[1]
    source.setCheckState(0, Qt.CheckState.Checked)
    widget.figure.addItem("Figure 1", "fig:1")
    widget.figure.setCurrentIndex(widget.figure.findData("fig:1"))
    source.setCheckState(0, Qt.CheckState.Unchecked)
    assert source.checkState(0) == Qt.CheckState.Checked
    assert "圖表" in widget.status.text()


def test_source_label_click_is_not_a_citation_toggle(pane, monkeypatch):
    widget, app = show_workspace(pane, monkeypatch)
    widget.views.setCurrentIndex(2)
    app.processEvents()
    picker = widget.source_picker
    row = picker.visualItemRect(widget._source_items[0])
    QTest.mouseClick(
        picker.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(row.right() - 20, row.center().y())
    )
    assert not widget._dirty and widget._checked_sources() == ["original"]


def test_canvas_up_down_changes_slides_and_respects_editing(pane, monkeypatch):
    widget, app = show_workspace(pane, monkeypatch)
    view = widget.canvas.view
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Down)
    assert widget._index == 1 and view.hasFocus()
    QTest.keyClick(view, Qt.Key.Key_Up)
    assert widget._index == 0
    QTest.keyClick(view, Qt.Key.Key_Up)
    assert widget._index == 0
    obj = widget.canvas.objects[1]
    obj.setSelected(True)
    y = obj.y()
    QTest.keyClick(view, Qt.Key.Key_Down)
    assert widget._index == 0 and obj.y() == y + 1
    QTest.keyClick(view, Qt.Key.Key_PageDown)
    assert widget._index == 1
    obj = widget.canvas.objects[1]
    obj.setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert not widget.canvas.scene.selectedItems()
    QTest.keyClick(view, Qt.Key.Key_Down)
    assert widget._index == 2
    obj = widget.canvas.objects[1]
    point = view.mapFromScene(obj.sceneBoundingRect().center())
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert obj.text.hasFocus()
    QTest.keyClick(view, Qt.Key.Key_Up)
    assert widget._index == 2
    QTest.keyClick(view, Qt.Key.Key_PageDown)
    assert widget._index == 2


def test_canvas_page_navigation_saves_pending_changes_and_stops_at_last_slide(pane, monkeypatch):
    from paper_daily import presentations

    widget, app = show_workspace(pane, monkeypatch)
    widget.canvas.objects[1].text.setPlainText("Saved before navigation")
    widget.canvas.scene.clearSelection()
    QTest.keyClick(widget.canvas.view, Qt.Key.Key_Down)
    assert widget._index == 1
    assert (
        presentations.load_deck(widget.paper_id, "guide").slides[0].title
        == "Saved before navigation"
    )
    widget.outline.setCurrentRow(len(widget.deck.slides) - 1)
    QTest.keyClick(widget.canvas.view, Qt.Key.Key_Down)
    assert widget._index == len(widget.deck.slides) - 1
    widget.bullets.setPlainText("")
    QTest.keyClick(widget.canvas.view, Qt.Key.Key_Up)
    assert widget._index == len(widget.deck.slides) - 1 and widget._dirty


def test_add_figure_opens_materials_for_preview_without_inserting(pane, monkeypatch):
    widget, deck, app, tmp = pane
    found = materials.Materials(
        deck.paper_id,
        exhibits=[
            dict(id="figure:1", file="missing.png", label="Figure 1", caption="Evidence", page=2)
        ],
    )
    monkeypatch.setattr(materials, "collect", lambda pid: found)
    before = widget.canvas.snapshot()
    widget._browse_figures()
    assert widget.materials_button.isChecked()
    assert widget.materials_button.text().endswith("開")
    assert widget.materials_panel.tree.currentItem().text(0).startswith("Figure 1")
    assert widget.materials_panel.detail_toggle.isChecked()
    assert widget.canvas.snapshot() == before and not widget._dirty


def test_source_navigation_keeps_reader_on_current_paper(pane):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from paper_daily.desktop.main import ReaderPage

    widget, _deck, _app, _tmp = pane
    selection = Mock()
    selection.find.return_value = {"p0": 1, "p1": 1, "o0": 3, "o1": 8}
    selection.focus.return_value = True
    reader = SimpleNamespace(
        pdf=SimpleNamespace(selection=selection, isVisible=lambda: True),
        presentation_pane=widget,
    )
    ReaderPage._jump_to_source(reader, dict(kind="figure", page=2, text="Figure 1 evidence"))
    selection.find.assert_called_once_with(1, "Figure 1 evidence")
    selection.focus.assert_called_once()
    assert "第 2 頁" in widget.status.text()
    selection.reset_mock()
    ReaderPage._jump_to_source(reader, dict(kind="original", page=4, text="Entire page"))
    selection.scroll_to_page.assert_called_once_with(3)
    selection.find.assert_not_called()
    ReaderPage._jump_to_source(reader, dict(kind="notes", text="Reader note"))
    assert "無法精確跳轉" in widget.status.text()


def test_analysis_and_citation_sources_open_their_own_tabs(pane):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from paper_daily.desktop.main import ReaderPage

    widget, _deck, _app, _tmp = pane
    dive_view = Mock()
    dive_view.find.return_value = True
    cites_pane = Mock()
    cites_pane.focus.return_value = "已跳到「引用」分頁的參考文獻這一筆。"
    reader = SimpleNamespace(
        pdf=SimpleNamespace(selection=None, isVisible=lambda: False),
        presentation_pane=widget,
        tabs=Mock(),
        dive_view=dive_view,
        cites_pane=cites_pane,
        _show_cites_if_visible=Mock(),
    )
    # Neither needs the PDF on screen: they live in the right-hand tabs.
    ReaderPage._jump_to_source(
        reader, dict(kind="close_reading", label="逐節精讀（AI 分析）：3 Method")
    )
    reader.tabs.setCurrentWidget.assert_called_with(dive_view)
    dive_view.find.assert_called_once_with("3 Method")
    assert "3 Method" in widget.status.text()

    source = dict(kind="citations", id="cite:12", label="引用分析（AI 分析） [12] SAM 2")
    ReaderPage._jump_to_source(reader, source)
    reader.tabs.setCurrentWidget.assert_called_with(cites_pane)
    cites_pane.focus.assert_called_once_with(source)
    assert "參考文獻" in widget.status.text()


def test_restart_preserves_incomplete_slides_and_unsent_inputs(pane, monkeypatch):
    import json
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTabWidget

    from paper_daily.desktop.main import MainWindow

    widget, deck, _app, _tmp = pane
    monkeypatch.setattr(QApplication, "activeModalWidget", lambda: None)
    worker = SimpleNamespace(busy=False)
    reader = SimpleNamespace(
        paper=SimpleNamespace(id=deck.paper_id),
        pdf=SimpleNamespace(current_page=lambda: 3, isVisible=lambda: True),
        presentation_pane=widget,
        runner=worker,
        translate_runner=worker,
        refine_runner=worker,
        fetcher=worker,
        tabs=QTabWidget(),
        note_edit=QPlainTextEdit("尚未完成的筆記"),
        ask_box=QLineEdit("尚未送出的問題"),
    )
    stored = {}
    window = SimpleNamespace(
        reader_page=reader,
        remember=lambda k, v: stored.update({k: v}),
        stack=SimpleNamespace(currentWidget=lambda: reader),
    )
    widget.bullets.clear()
    assert MainWindow._prepare_restart(window)
    assert window._closing_with_recovery and widget._recovery_path().exists()
    state = json.loads(stored["restart"])
    assert state["note"] == "尚未完成的筆記" and state["question"] == "尚未送出的問題"
    assert state["paper"] == deck.paper_id and state["pdf_page"] == 3
    worker.busy = True
    assert not MainWindow._prepare_restart(window)


def test_grouped_sources_filter_search_preview_and_live_citation_change(pane):
    widget, _deck, _app, _tmp = pane
    widget.deck.sources.append(
        dict(id="note:1", kind="notes", label="讀者筆記", text="獨特筆記內容")
    )
    widget._add_source_item("note:1", "讀者筆記")
    widget._source_count()
    before = widget.canvas.snapshot()
    note = widget._source_items[-1]
    assert note.isHidden()
    assert widget.source_picker.topLevelItemCount() == 2
    widget.source_search.setText("獨特筆記")
    assert not note.isHidden() and widget._source_items[0].isHidden()
    widget.source_picker.setCurrentItem(note)
    assert widget.source_detail.toPlainText() == "獨特筆記內容"
    assert not widget._dirty
    note.setCheckState(0, Qt.CheckState.Checked)
    assert widget._checked_sources() == ["original", "note:1"]
    assert "讀者筆記" in widget.preview.toPlainText()
    assert widget.canvas.snapshot() == before
    widget.source_search.clear()
    assert not note.isHidden()
    note.setCheckState(0, Qt.CheckState.Unchecked)
    assert note.isHidden() and "讀者筆記" not in widget.preview.toPlainText()
    assert widget.canvas.snapshot() == before
    widget.source_selected_only.setChecked(False)
    assert not note.isHidden()
    assert all(not parent.isExpanded() for parent in widget._source_groups.values())


def test_alt_view_navigation_wins_over_window_history_shortcuts(pane, monkeypatch):
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    widget, _app = show_workspace(pane, monkeypatch)
    host = QWidget()
    QVBoxLayout(host).addWidget(widget)
    history = []
    shortcut = QShortcut(QKeySequence("Alt+Left"), host)
    shortcut.activated.connect(lambda: history.append("back"))
    host.show()
    host.activateWindow()
    widget.views.setCurrentIndex(2)
    widget.slide_title.setFocus()
    _app.processEvents()
    QTest.keyClick(widget.slide_title, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    assert widget.views.currentIndex() == 1 and not history
    QTest.keyClick(widget.views.tabBar(), Qt.Key.Key_Left)
    assert widget.views.currentIndex() == 0 and widget.canvas.view.hasFocus()
    QTest.keyClick(widget.canvas.view, Qt.Key.Key_Down)
    assert widget._index == 1
    widget.setParent(None)
    host.close()


def test_a_d_r_toggle_the_panels_but_type_into_text(pane, monkeypatch):
    widget, app = show_workspace(pane, monkeypatch)
    widget.activateWindow()
    widget.canvas.view.setFocus()
    app.processEvents()
    QTest.keyClick(widget.canvas.view, Qt.Key.Key_A)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_D)
    assert not widget.outline_button.isChecked() and not widget.materials_button.isChecked()
    widget.outline_button.setChecked(True)
    widget.outline.setFocus()
    QTest.keyClick(widget.outline, Qt.Key.Key_A)
    # Closing the panel that had the keys leaves them in the pane.
    assert widget._outline_panel.isHidden()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_A)
    assert widget.outline_button.isChecked()
    widget.materials_button.setChecked(True)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_R)
    assert widget.outline_button.isChecked() and not widget.materials_button.isChecked()
    widget.slide_title.setFocus()
    widget.slide_title.end(False)
    title = widget.slide_title.text()
    QTest.keyClick(widget.slide_title, Qt.Key.Key_D)
    assert widget.slide_title.text() == title + "d" and not widget.materials_button.isChecked()
    widget.views.setCurrentIndex(3)
    widget.speaker_notes.setFocus()
    QTest.keyClick(widget.speaker_notes, Qt.Key.Key_A)
    assert "a" in widget.speaker_notes.toPlainText()
    assert widget.outline_button.isChecked()
