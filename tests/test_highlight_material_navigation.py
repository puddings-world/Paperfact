"""Real owned readers wait for materials before locating the selected highlight."""

import pytest
from PySide6.QtCore import Qt
from test_material_reader_ui import (
    actual_desktop_capture_and_owned_drain as actual_desktop_capture_and_owned_drain,
)
from test_material_reader_ui import (
    await_owned,
    collect,
    heading,
    hold,
    sql,
    use_b,
)
from test_material_reader_ui import (
    loaded as loaded,
)
from test_material_reader_ui import (
    no_external as no_external,
)
from test_material_reader_ui import (
    workspace as workspace,
)
from test_reader_preparation import settle

from paper_daily.desktop import material_preparation


def mark(w):
    view = w.widget
    selection = view.pdf.selection
    assert selection.focus(selection.find(0, "Alpha material."))
    view._highlight_selection()
    await_owned(w, "material_preparation", "reading_positions")
    return selection._marks[0][0]["id"]


def test_browse_waits_for_one_collection_and_then_locates_the_actual_highlight(loaded, monkeypatch):
    w, view = loaded, loaded.widget
    identity = mark(w)
    panel = view.presentation_pane.materials_panel
    panel.clear()
    before = sql(w)
    view.pdf.selection.clear()
    entered, release, calls = hold(monkeypatch, material_preparation, "_collect")
    try:
        for _ in range(12):
            view.browse_highlights.click()
        settle(w.app, entered.is_set)
        assert len(calls) == 1
        assert view.material_preparation.busy
        assert not panel.refresh.isEnabled()
        assert not view.pdf.selection.selected_text()
    finally:
        release.set()
    await_owned(w, "material_preparation", "material_originals")
    selected = panel.tree.currentItem().data(0, Qt.ItemDataRole.UserRole)
    assert selected["mark_id"] == identity
    assert view.pdf.selection.selected_text() == "Alpha material."
    assert selected["document_hash"] == w.first.sha256
    assert panel._source_collection is not None
    assert panel.refresh.isEnabled() and sql(w) == before
    assert view.note_edit.toPlainText() == "Unsent research interpretation"


@pytest.mark.parametrize("choice", ["other_material", "other_tab", "panel_closed"])
def test_later_user_navigation_cancels_pending_highlight_jump(loaded, monkeypatch, choice):
    w, view = loaded, loaded.widget
    mark(w)
    panel = collect(w)
    view.pdf.selection.clear()
    located = []
    panel.source_requested.connect(located.append)
    entered, release, _calls = hold(monkeypatch, material_preparation, "_collect")
    try:
        view.browse_highlights.click()
        settle(w.app, entered.is_set)
        if choice == "other_material":
            panel.tree.setCurrentItem(heading(panel))
        elif choice == "other_tab":
            view.tabs.setCurrentIndex(0)
        else:
            view.presentation_pane.materials_button.setChecked(False)
        located.clear()
    finally:
        release.set()
    await_owned(w, "material_preparation", "material_originals")
    assert not located
    assert not view.pdf.selection.selected_text()
    assert view.note_edit.toPlainText() == "Unsent research interpretation"


def test_failed_collection_does_not_jump_to_stale_marks_and_browse_is_an_explicit_retry(
    loaded,
    monkeypatch,
):
    w, view = loaded, loaded.widget
    identity = mark(w)
    panel = collect(w)
    before, collection = sql(w), panel._source_collection
    view.pdf.selection.clear()
    original = material_preparation._collect

    def fail(*_args):
        raise RuntimeError("PRIVATE FAILURE DETAILS")

    monkeypatch.setattr(material_preparation, "_collect", fail)
    view.browse_highlights.click()
    await_owned(w, "material_preparation", "material_originals")
    assert not view.pdf.selection.selected_text()
    assert panel._source_collection is collection and panel.refresh.isEnabled()
    assert "PRIVATE" not in view.presentation_pane.status.text()
    monkeypatch.setattr(material_preparation, "_collect", original)
    view.browse_highlights.click()
    await_owned(w, "material_preparation", "material_originals")
    assert panel.tree.currentItem().data(0, Qt.ItemDataRole.UserRole)["mark_id"] == identity
    assert view.pdf.selection.selected_text() == "Alpha material."
    assert sql(w) == before


@pytest.mark.parametrize("change", ["source", "close"])
def test_source_replacement_or_close_never_delivers_a_pending_highlight_jump(
    loaded,
    monkeypatch,
    change,
):
    w, view = loaded, loaded.widget
    mark(w)
    panel = collect(w)
    view.pdf.selection.clear()
    located = []
    panel.source_requested.connect(located.append)
    entered, release, _calls = hold(monkeypatch, material_preparation, "_collect")
    try:
        view.browse_highlights.click()
        settle(w.app, entered.is_set)
        if change == "source":
            use_b(w)
        else:
            assert not view.close()
        located.clear()
    finally:
        release.set()
    await_owned(w, "material_preparation", "material_originals")
    assert not located
    assert not view.pdf.selection.selected_text()
    assert view.note_edit.toPlainText() == "Unsent research interpretation"


@pytest.mark.parametrize("target", [None, 999999])
def test_empty_or_missing_highlight_does_not_navigate_to_unrelated_material(loaded, target):
    w, view = loaded, loaded.widget
    panel = view.presentation_pane.materials_panel
    before = sql(w)
    located = []
    panel.source_requested.connect(located.append)
    view._show_highlight_material(target)
    await_owned(w, "material_preparation", "material_originals")
    assert not located and not view.pdf.selection.selected_text()
    assert "不在素材" in view.highlight_status.text()
    assert panel.refresh.isEnabled() and sql(w) == before
    assert view.note_edit.toPlainText() == "Unsent research interpretation"
