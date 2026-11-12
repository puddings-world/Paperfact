"""Required ordinary slide-source continuity; audit-only expected missing adapter."""

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from test_enrolled_deck_proposals import prepare, save
from test_enrolled_deck_review import actual as actual
from test_enrolled_deck_review import case as case
from test_enrolled_deck_review import codec as codec
from test_enrolled_deck_review import no_external as no_external
from test_enrolled_deck_review import original as original
from test_enrolled_deck_review import package as package
from test_enrolled_deck_review import scientific as scientific
from test_local_deck_proposals import local as local
from test_local_deck_proposals import prepared

from paper_daily import local_deck_proposals, presentations, store
from paper_daily.desktop import main
from paper_daily.desktop.document_flow import anchor_allowed, loaded_document_valid
from paper_daily.desktop.original_version import OriginalVersionDialog
from paper_daily.document_reader import from_workspace
from paper_daily.research_review import ResearchReview


def snapshot(database, root):
    with closing(sqlite3.connect(database)) as conn:
        sql = list(conn.iterdump())
    files = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and not path.name.endswith(("-shm", "-wal"))
    }
    return sql, files


@pytest.mark.parametrize("mode", ["local", "managed"])
def test_public_applied_deck_source_a_opens_independently_of_loaded_b(
    mode, request, tmp_path, monkeypatch
):
    """Actual public Apply/load/click; B and all saved state survive missing A UI."""
    if mode == "local":
        local = request.getfixturevalue("local")
        science = request.getfixturevalue("scientific")
        database, _manifest, _blobs, _saved, _prior = local
        paper_id, origin = "local-paper", "local_deck"
        proposal = local_deck_proposals.retain(prepared(local))
        root = tmp_path / "pdf"
        root.mkdir()
        (root / (paper_id + ".pdf")).write_bytes(science[5])
        expected_a = science[4]
        expected_bytes = science[3][expected_a]
        service = ResearchReview(database, presentation_root=local[3].parents[1])
        resolver = from_workspace(database, legacy_root=root)
    else:
        actual = request.getfixturevalue("actual")
        database = actual["client"].journal.path
        paper_id, origin = actual["local"], "enrolled_deck"
        proposal = save(actual, prepare(actual))
        expected_a = actual["package"].original_a
        expected_bytes = actual["expected"]["original_bytes"][expected_a]
        service = ResearchReview(database)
        resolver = from_workspace(database)
    monkeypatch.setattr(store, "DB_PATH", database)
    loaded_b = resolver.resolve(paper_id)
    assert loaded_b.available and loaded_b.sha256 != expected_a
    assert resolver.intact(loaded_b)
    preview = service.prepare_file(service.preview(origin, proposal))
    result = service.decide(preview, request_id="ordinary-source-apply", confirm_target=True)
    assert result["decision"] == "applied"
    active = presentations.load_deck(paper_id, "guide")
    source = next(row for row in active.sources if row["id"] == "figure:1")
    assert source["document_hash"] == expected_a and source["page"] == 1
    observation = active._file_observation
    assert (observation is not None) == (mode == "managed")

    app = QApplication.instance() or QApplication([])
    widget = main.ReaderPage(
        SimpleNamespace(pal=main.palette(), remember=lambda *_: None, data=main.Data())
    )
    widget.paper = SimpleNamespace(
        id=paper_id, title="Explicit receiver", _document_reader=resolver,
        _document_status=loaded_b, _loaded_document=loaded_b,
    )
    widget._active_document = loaded_b
    widget._pdf_fingerprint = loaded_b.sha256
    widget.resize(1300, 850)
    widget.show()
    try:
        # Isolate source navigation from unrelated opt-in legacy highlight analysis.
        widget.auto_highlights.setChecked(False)
        assert widget.pdf.load(loaded_b.path)
        widget.pdf.show()
        widget.presentation_pane.load(paper_id, "Explicit receiver")
        widget.note_edit.setPlainText("Preserve the unsaved reading interpretation")
        app.processEvents()
        assert loaded_document_valid(widget)
        assert not anchor_allowed(widget, source)  # Never weaken the current-B guard.
        prior = snapshot(database, tmp_path)
        before_b = loaded_b.path.read_bytes()
        seen = []
        widget.presentation_pane.source_requested.connect(seen.append)
        widget.presentation_pane.preview.anchorClicked.emit(QUrl("paperfact-source:figure:1"))
        # The missing adapter is now asynchronous; await its owned terminal delivery.
        deadline = time.monotonic() + 15
        while widget.active_originals.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        app.processEvents()
        assert not widget.active_originals.busy
        assert seen == [source]
        assert widget._active_document is loaded_b
        assert widget._pdf_fingerprint == loaded_b.sha256
        assert loaded_b.path.read_bytes() == before_b
        assert widget.note_edit.toPlainText() == "Preserve the unsaved reading interpretation"
        assert snapshot(database, tmp_path) == prior
        viewers = [
            item for item in app.topLevelWidgets()
            if isinstance(item, OriginalVersionDialog) and item.isVisible()
        ]
        observed = {
            "mode": mode, "source": source, "loaded_b": loaded_b.sha256,
            "active_observation": observation, "status": widget.presentation_pane.status.text(),
            "independent_original_views": len(viewers), "sql_and_files_unchanged": True,
        }
        (tmp_path / "observed-navigation.json").write_text(
            json.dumps(observed, indent=2, default=str), encoding="utf8"
        )
        assert len(viewers) == 1, "Missing ordinary active-deck original-A navigation adapter"
        assert viewers[0].snapshot.document_hash == expected_a
        assert viewers[0].snapshot.data == expected_bytes
    finally:
        widget.active_originals.request_close()
        deadline = time.monotonic() + 15
        while widget.active_originals.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert not widget.active_originals.busy
        widget.pdf.unload()
        widget.close()
        widget.deleteLater()
        app.processEvents()
        service.close()
