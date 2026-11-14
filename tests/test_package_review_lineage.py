"""Actual desktop confirmation retains scientific reports and all source PDFs."""

import json
import sqlite3
from contextlib import closing

from test_lineage_bundle_journey import shared as shared
from test_lineage_enrolled_import import native_shared as native_shared
from test_package_import import enroll_capture
from test_package_review_dialog import app as app
from test_package_review_dialog import close, wait
from test_research_lineage import corpus as corpus
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import bundle, lineage_sets, store
from paper_daily.desktop.bundle_dialog import import_dialog
from paper_daily.sync_source_files import resolved


def test_actual_file_review_confirmation_keeps_complete_lineage_and_three_originals(
    app,
    native_shared,
    pair,
    monkeypatch,
):
    archive, _source, originals, scientific = native_shared
    client = pair[1]
    enroll_capture(client)
    monkeypatch.setattr(store, "DB_PATH", client.journal.path)
    monkeypatch.setattr(bundle, "DATA_DIR", client.journal.path.parent)
    dialog = import_dialog(source=archive, language="en")
    try:
        dialog.show()
        wait(app, lambda: dialog.session is not None and not dialog.busy)
        assert dialog.table.rowCount() == 3
        with closing(sqlite3.connect(client.journal.path)) as conn:
            before = tuple(conn.iterdump())
        dialog.review()
        wait(app, lambda: not dialog.busy)
        assert dialog.reviewed, dialog.status.text()
        assert "New lineage analyses: 1" in dialog.preview.toPlainText()
        with closing(sqlite3.connect(client.journal.path)) as conn:
            assert tuple(conn.iterdump()) == before
        dialog.apply()
        wait(app, lambda: not dialog.busy)
        result = dialog.result_data
        assert result is not None, dialog.status.text()
        assert result["lineage_reports"] == 1
        focal = result["identity_mapping"]["focal"]["local_id"]
        saved = lineage_sets.saved(client.journal.path, focal)
        assert (
            json.loads(saved[0]["body_json"])["report"]
            == json.loads(scientific[0]["body_json"])["report"]
        )
        with closing(client.journal._connect()) as conn:
            for source in json.loads(saved[0]["body_json"])["report"]["sources"]:
                binding = next(
                    b
                    for b in json.loads(saved[0]["body_json"])["bindings"]
                    if b["source_id"] == source["id"]
                )
                old = next(
                    old
                    for old, mapped in result["identity_mapping"].items()
                    if mapped["local_id"] == binding["paper_id"]
                )
                portable = result["identity_mapping"][old]["portable_id"]
                assert (
                    resolved(conn, portable, source["document_hash"]).read_bytes() == originals[old]
                )
    finally:
        close(app, dialog)
