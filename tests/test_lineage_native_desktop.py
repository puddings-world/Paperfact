"""A real receiving workspace opens only its own verified native original bytes."""

import hashlib
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from test_lineage_live_journey import setup_publication, sync_all
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import rows
from test_sync_files import drain

from paper_daily import lineage_sets, llm
from paper_daily import research_generation as generation
from paper_daily.ai_types import Settings
from paper_daily.desktop.lineage_dialog import LineageDialog
from paper_daily.manual_highlight_ops import observe_owner


def until(app, predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert predicate()


def test_real_peer_original_window_uses_bound_reader_and_does_not_mutate_native_state(
    selected, monkeypatch
):
    client, _result, _receipt, _science, originals = setup_publication(selected, monkeypatch)
    peer = sync_all(selected, client, originals)
    files = selected[0][4]
    for original in originals:
        drain(lambda op=original: files.download(op["entity_id"]), "bound")
    row = rows(peer, lineage_sets.TABLE)[0]
    owner = observe_owner(
        peer.journal.path, row["paper_id"], expected_native=generation._identity(peer.journal.path)
    )
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(llm, "settings", lambda *_a, **_k: Settings("none"))
    calls = []
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: calls.append(True))
    before, pending = peer.journal.path.read_bytes(), peer.journal.pending()
    dialog = LineageDialog(
        peer.journal.path,
        row["paper_id"],
        owner=owner,
        document=None,
        legacy_root=peer.journal.path.parent,
        current_view=lambda: "peer-paper",
        language="en",
    )
    dialog.show()
    try:
        until(app, lambda: not dialog.busy and bool(dialog.saved))
        source = lineage_sets.decode(row["body_json"])["report"]["sources"][1]
        assert dialog.open_source(row, source["id"])
        until(app, lambda: not dialog.busy)
        viewer = dialog._original_viewer
        assert viewer is not None and not viewer.disposed
        assert hashlib.sha256(bytes(viewer.buffer.data())).hexdigest() == source["document_hash"]
        assert dialog.document is None and viewer.document.pageCount() >= 1
        assert peer.journal.path.read_bytes() == before and peer.journal.pending() == pending
        assert calls == []
    finally:
        if dialog.busy:
            dialog.cancel()
            until(app, lambda: not dialog.busy)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
