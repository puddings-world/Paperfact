"""Current legacy mark browsing remains immediate without granting research ownership."""

import sqlite3

import pymupdf
import pytest
from PySide6.QtCore import Qt
from test_pdf_highlights import reader as reader

from paper_daily import materials, store


def seeded(reader):
    widget, app, path = reader
    widget.auto_highlights.setChecked(False)
    widget.presentation_pane.load(widget.paper.id, "Legacy preview")
    selection = widget.pdf.selection
    assert selection.focus(selection.find(0, "Alpha beta"))
    widget._highlight_selection()
    return widget, app, path


def test_browse_reuses_loaded_marks_without_sql_pdf_parse_collection_or_ai(reader, monkeypatch):
    widget, app, _path = seeded(reader)
    panel = widget.presentation_pane.materials_panel
    panel.clear()

    def forbidden(*args, **kwargs):
        raise AssertionError("Loaded preview did expensive collection")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(pymupdf, "open", forbidden)
    monkeypatch.setattr(materials, "collect", forbidden)
    for _ in range(10):
        widget.browse_highlights.click()
    app.processEvents()
    payload = panel.tree.currentItem().data(0, Qt.ItemDataRole.UserRole)
    assert payload["text"] == "Alpha beta" and payload["origin"] == "manual"
    assert payload["document_hash"] == widget._pdf_fingerprint
    assert panel._source_collection is None and not widget.material_preparation.busy
    assert widget.pdf.selection.selected_text() == "Alpha beta"


def test_failed_owned_reader_cannot_fall_back_to_legacy_preview(reader):
    widget, app, _path = seeded(reader)
    widget._highlight_owner = None
    panel = widget.presentation_pane.materials_panel
    panel.clear()
    assert not widget.material_preparation.request()
    app.processEvents()
    assert panel.tree.currentItem() is None and panel._source_collection is None
    assert not widget.material_preparation.busy


@pytest.mark.parametrize("change", ["source", "workspace"])
def test_changed_original_or_workspace_cannot_reproject_legacy_marks(reader, monkeypatch, change):
    widget, app, path = seeded(reader)
    panel = widget.presentation_pane.materials_panel
    panel.clear()
    if change == "source":
        data = bytearray(path.read_bytes())
        data[-8] ^= 1
        path.write_bytes(data)
    else:
        other = path.parent / "other.db"
        other.write_bytes(store.DB_PATH.read_bytes())
        monkeypatch.setattr(store, "DB_PATH", other)
        before = other.read_bytes()
    assert not widget.material_preparation.request()
    app.processEvents()
    assert panel.tree.currentItem() is None and panel._source_collection is None
    assert not widget.material_preparation.busy
    if change == "workspace":
        assert other.read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [("reason", None), ("reason", "x" * 1601), ("quote", "x" * 32769)],
    ids=["invalid-reason", "oversized-reason", "oversized-quote"],
)
def test_malformed_loaded_mark_cannot_replace_visible_preview(reader, field, value):
    widget, app, _path = seeded(reader)
    panel = widget.presentation_pane.materials_panel
    widget.browse_highlights.click()
    previous = panel.tree.currentItem().data(0, Qt.ItemDataRole.UserRole)
    selection = widget.pdf.selection
    # Shown marks are derived from the loaded records on demand; damage the record.
    selection._mark_records[0] = dict(selection._mark_records[0], **{field: value})
    assert not widget.material_preparation.request()
    app.processEvents()
    assert panel.tree.currentItem().data(0, Qt.ItemDataRole.UserRole) == previous
    assert panel._source_collection is None and not widget.material_preparation.busy
