"""Imported and real peer-native historical PDF windows use receiver-owned bytes."""

import hashlib

import pytest
from lineage_package_fixture import lineage_archive as lineage_archive
from PySide6.QtWidgets import QApplication, QMessageBox
from test_lineage_desktop import until
from test_lineage_import_desktop import scene as scene
from test_lineage_import_originals import loaded as loaded
from test_lineage_live_journey import setup_publication, sync_all
from test_lineage_package_publish import incoming as incoming
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import rows
from test_sync_files import drain

from paper_daily import lineage_history_originals as history
from paper_daily import lineage_sets, llm
from paper_daily import research_generation as generation
from paper_daily.ai_types import Settings
from paper_daily.desktop.lineage_dialog import LineageDialog
from paper_daily.manual_highlight_ops import observe_owner


def verify_windows(app, dialog, row):
    before = dialog.path.read_bytes()
    for source in lineage_sets.decode(row["body_json"])["report"]["sources"]:
        assert dialog.open_source(row, source["id"])
        until(app, lambda: not dialog.busy)
        viewer = dialog._original_viewer
        assert viewer is not None and not viewer.disposed and viewer._module is history
        assert viewer.document.pageCount() > 0
        assert hashlib.sha256(bytes(viewer.buffer.data())).hexdigest() == source["document_hash"]
        viewer.close()
        assert viewer.buffer.size() == 0 and viewer._proof is None
    assert dialog.path.read_bytes() == before
    assert lineage_sets.saved(dialog.path, row["paper_id"]) == []
    assert dialog.document is None


def test_imported_removed_report_opens_all_three_historical_pdf_windows(scene, monkeypatch):
    app, dialog, _owner, row = scene
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    assert dialog._change_analysis("retire")
    until(app, lambda: not dialog.busy)
    verify_windows(app, dialog, row)


def test_received_native_removed_report_opens_all_three_historical_pdf_windows(
    selected, monkeypatch
):
    client, _candidate, _receipt, _science, sources = setup_publication(selected, monkeypatch)
    peer = sync_all(selected, client, sources)
    for source in sources:
        drain(lambda identity=source["entity_id"]: selected[0][4].download(identity), "bound")
    row = rows(peer, lineage_sets.TABLE)[0]
    owner = observe_owner(
        peer.journal.path, row["paper_id"], expected_native=generation._identity(peer.journal.path)
    )
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(llm, "settings", lambda *_a, **_k: Settings("none"))
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No history AI"))
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    dialog = LineageDialog(
        peer.journal.path,
        row["paper_id"],
        owner=owner,
        document=None,
        legacy_root=peer.journal.path.parent,
        current_view=lambda: "native-history",
        language="en",
    )
    dialog.show()
    try:
        until(app, lambda: not dialog.busy and bool(dialog.saved))
        assert dialog._change_analysis("retire")
        until(app, lambda: not dialog.busy)
        pending = peer.journal.pending()
        verify_windows(app, dialog, row)
        assert peer.journal.pending() == pending
    finally:
        if dialog.busy:
            dialog.cancel()
            until(app, lambda: not dialog.busy)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
