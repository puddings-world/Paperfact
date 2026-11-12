"""A draining retired collection cannot consume a newer explicit navigation request."""

import pytest
from PySide6.QtCore import Qt
from test_highlight_material_navigation import mark
from test_material_reader_ui import (
    actual_desktop_capture_and_owned_drain as actual_desktop_capture_and_owned_drain,
)
from test_material_reader_ui import await_owned, collect, hold, sql, use_b
from test_material_reader_ui import loaded as loaded
from test_material_reader_ui import no_external as no_external
from test_material_reader_ui import workspace as workspace
from test_reader_preparation import settle

from paper_daily.desktop import material_preparation


@pytest.mark.parametrize("poll_before_finish", [False, True])
def test_browse_for_new_original_survives_retired_collection_completion(
    loaded,
    monkeypatch,
    poll_before_finish,
):
    w, view = loaded, loaded.widget
    mark(w)
    panel = collect(w)
    requests = []
    entered, release, calls = hold(monkeypatch, material_preparation, "_collect", requests=requests)
    try:
        view.browse_highlights.click()
        settle(w.app, entered.is_set)
        current = use_b(w)
        selection = view.pdf.selection
        assert selection.focus(selection.find(0, "Beta material."))
        view._highlight_selection()
        before = sql(w)
        for _ in range(12):
            view.browse_highlights.click()
        if poll_before_finish:
            view.material_preparation.timer.timeout.emit()
        assert len(calls) == 1 and view.material_preparation.busy
        assert not selection.selected_text()
    finally:
        release.set()
    await_owned(w, "material_preparation", "material_originals")
    payload = panel.tree.currentItem().data(0, Qt.ItemDataRole.UserRole)
    assert payload["document_hash"] == current.sha256
    assert payload["text"] == "Beta material."
    assert view.pdf.selection.selected_text() == "Beta material."
    assert len(calls) == 2 and requests[0].fingerprint != requests[1].fingerprint
    assert panel.refresh.isEnabled() and sql(w) == before
    assert view.note_edit.toPlainText() == "Unsent research interpretation"


@pytest.mark.parametrize("change", ["panel_closed", "close"])
def test_cancelled_new_navigation_is_not_revived_when_the_old_worker_finishes(
    loaded,
    monkeypatch,
    change,
):
    w, view = loaded, loaded.widget
    mark(w)
    panel = collect(w)
    requests = []
    entered, release, calls = hold(monkeypatch, material_preparation, "_collect", requests=requests)
    located = []
    panel.source_requested.connect(located.append)
    try:
        view.browse_highlights.click()
        settle(w.app, entered.is_set)
        current = use_b(w)
        selection = view.pdf.selection
        assert selection.focus(selection.find(0, "Beta material."))
        view._highlight_selection()
        view.browse_highlights.click()
        if change == "panel_closed":
            view.presentation_pane.materials_button.setChecked(False)
        else:
            assert not view.close()
        view.material_preparation.timer.timeout.emit()
        located.clear()
    finally:
        release.set()
    await_owned(w, "material_preparation", "material_originals")
    assert not located and not view.pdf.selection.selected_text()
    assert view._active_document.sha256 == current.sha256
    assert len(calls) == (2 if change == "panel_closed" else 1)
    assert view.note_edit.toPlainText() == "Unsent research interpretation"
