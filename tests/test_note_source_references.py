"""Bounded native source references retain exact bytes and live ownership."""

import sqlite3
from contextlib import closing

import pytest
from PySide6.QtWidgets import QFileDialog
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_note_draft_resumption import recovered_note as recovered_note
from test_note_draft_resumption_edges import selected, stored
from test_review_dialog import app as app
from test_review_dialog import wait

from paper_daily import research_generation as generation
from paper_daily.desktop.note_source_dialog import NoteSourceDialog
from paper_daily.sync_source_files import _inspection_paths


def ref(preview, kind):
    data = preview.data
    sha = data["source_hash"] if kind == "recorded" else data["expected"]["document"]["sha256"]
    return dict(kind=kind, document_hash=sha)


def test_reference_inspection_rejects_arbitrary_paths_and_tracks_store_ownership(recovered_note):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    before = stored(value)
    for bad in (
        {"path": str(value["path"])},
        {"kind": [], "document_hash": value["source_a"]},
        {"kind": "recorded", "document_hash": "f" * 64},
    ):
        with pytest.raises(ValueError):
            review.inspect_note_source_reference(preview, bad)
    reference = ref(preview, "recorded")
    inspected = review.inspect_note_source_reference(preview, reference)
    reference["document_hash"] = value["source_b"]
    exposed = inspected.reference.ref
    exposed["document_hash"] = value["source_b"]
    assert inspected.sha256 == value["source_a"]
    assert review.note_source_page(preview, inspected, 0)["words"][0]["text"] == "A"
    with closing(generation._connect(value["path"])) as conn:
        index = _inspection_paths(conn)[0].root / "index.sqlite"
    with closing(sqlite3.connect(index)) as conn, conn:
        original = conn.execute("SELECT device FROM transfer_binding WHERE id=1").fetchone()[0]
        conn.execute("UPDATE transfer_binding SET device='wrong-device' WHERE id=1")
    with pytest.raises(ValueError, match="Currently selected original changed"):
        review.note_source_page(preview, inspected, 0)
    with closing(sqlite3.connect(index)) as conn, conn:
        conn.execute("UPDATE transfer_binding SET device=? WHERE id=1", (original,))
    assert stored(value) == before
    review.close()


@pytest.mark.parametrize(
    "recovered_note",
    [None, {"page": 99, "anchor": dict(p0=98, o0=0, p1=98, o1=3, document_hash="source-a")}],
    indirect=True,
)
def test_native_saved_original_selector_uses_bounded_reference_without_a_file_picker(
    recovered_note, app, monkeypatch
):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    before = stored(value)

    def no_picker(*args, **kwargs):
        pytest.fail("Saved original selection used the arbitrary native file picker")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", no_picker)
    dialog = NoteSourceDialog(review, preview, language="zh-TW")
    dialog.show()
    try:
        assert dialog.references.count() == 2
        assert dialog.references.currentData()["kind"] == "recorded"
        for _ in range(12):
            dialog.load_reference.click()
        wait(app, lambda: dialog.page_data is not None and dialog.future is None, timeout=15)
        assert dialog.text.toPlainText() == "A verified source paper"
        dialog.text.selectAll()
        dialog.use.click()
        wait(app, lambda: dialog.disposed)
        assert dialog.result_preview.data["source_hash"] == value["source_a"]
        assert dialog.result_preview.data["retained"]["page"] == 1
        assert (
            dialog.result_preview.data["retained"]["anchor"]["selection"]["quote"]
            == "A verified source paper"
        )
        assert stored(value) == before
    finally:
        dialog.close()
        wait(app, lambda: dialog.disposed)
        review.close()
