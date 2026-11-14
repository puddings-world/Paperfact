"""Explicit matching-adoption choice and final import confirmation in actual Qt."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog
from test_lineage_matching_adoption import codec as codec
from test_lineage_matching_adoption import corpus as corpus
from test_lineage_matching_adoption import dump
from test_lineage_matching_adoption import legacy as legacy
from test_lineage_matching_adoption import native_shared as native_shared
from test_lineage_matching_adoption import pair as pair
from test_lineage_matching_adoption import shared as shared
from test_package_review_dialog import app as app
from test_package_review_dialog import close, wait

from paper_daily import lineage_sets, store
from paper_daily.desktop import lineage_import_dialog as comparison
from paper_daily.desktop import package_review_dialog as ui


@pytest.fixture
def dialog(app, legacy, monkeypatch):
    client, importer, archive, receipt, _row, _review = legacy
    monkeypatch.setattr(store, "DB_PATH", client.journal.path)
    widget = ui.PackageReviewDialog(client.journal.path, importer.root, archive, language="en")
    widget.show()
    wait(app, lambda: widget.session is not None and not widget.busy)
    widget.destination.setCurrentIndex(widget.destination.findData(receipt["list"]))
    widget.mapping = {
        old: mapped["local_id"] for old, mapped in receipt["identity_mapping"].items()
    }
    yield widget
    close(app, widget)


def choose_matching(widget):
    widget.choice.setCurrentIndex(widget.choice.findData("adopt"))
    widget.accept()
    return QDialog.DialogCode.Accepted


def test_matching_comparison_defaults_to_keep_and_shows_sources_without_writing(app, legacy):
    client, _importer, _archive, _receipt, _row, review = legacy
    before = dump(client)
    widget = comparison.LineageImportDialog(review.conflicts)
    try:
        widget.show()
        app.processEvents()
        assert widget.choice.currentData() == "keep"
        assert widget.choice.findData("replace") == -1
        assert widget.choice.findData("adopt") >= 0
        assert "match exactly" in widget.reason.text()
        assert widget.current.toPlainText() == widget.incoming.toPlainText()
        assert widget.choice.currentData() == "keep"
        widget.choice.setCurrentIndex(widget.choice.findData("adopt"))
        assert review.decide(widget.choices)
        assert "Include in sync: 1" in widget.summary.text()
        image = Path(__file__).resolve().parents[1] / "build/lineage-matching-adoption.png"
        assert widget.grab().save(str(image))
        widget.reject()
        assert dump(client) == before
    finally:
        widget.close()


def test_adoption_needs_final_confirmation_and_repeated_clicks_publish_once(
    app, dialog, legacy, monkeypatch
):
    client, _importer, _archive, _receipt, row, _review = legacy
    monkeypatch.setattr(comparison.LineageImportDialog, "exec", choose_matching)
    before = dump(client)
    dialog.review()
    wait(app, lambda: dialog.reviewed and not dialog.busy)
    assert dump(client) == before
    assert "Identical saved analyses included in sync: 1" in dialog.preview.toPlainText()
    for _ in range(20):
        dialog.apply_button.click()
    wait(app, lambda: not dialog.busy)
    assert dialog.result_data["lineage_adopted"] == 1
    assert row in lineage_sets.saved(client.journal.path, row["paper_id"])
    from paper_daily import lineage_projection

    with client.journal.transaction() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM " + lineage_projection.HISTORY + " WHERE entity_id=?",
                (_review.conflicts[0]["id"],),
            ).fetchone()[0]
            == 1
        )


def test_close_before_final_import_preserves_the_private_analysis(app, dialog, legacy, monkeypatch):
    client, _importer, _archive, _receipt, _row, _review = legacy
    monkeypatch.setattr(comparison.LineageImportDialog, "exec", choose_matching)
    dialog.review()
    wait(app, lambda: dialog.reviewed and not dialog.busy)
    before = dump(client)
    # The reviewed choice is a preview; closing instead of clicking Import cancels it.
    dialog.reject()
    wait(app, lambda: not dialog.busy and not dialog.isVisible())
    assert dialog.result_data is None and dump(client) == before
