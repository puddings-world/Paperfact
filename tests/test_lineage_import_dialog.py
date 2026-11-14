"""Actual native version comparison and queued desktop publication choices."""

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog
from test_lineage_import_review import compared as compared
from test_lineage_import_review import corpus as corpus
from test_lineage_import_review import dump
from test_lineage_import_review import native_shared as native_shared
from test_lineage_import_review import shared as shared
from test_package_review_dialog import app as app
from test_package_review_dialog import close, wait
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import lineage_sets, store
from paper_daily.desktop import lineage_import_dialog as comparison
from paper_daily.desktop import package_review_dialog as ui


@pytest.fixture
def dialog(app, compared, monkeypatch):
    client, importer, archive, receipt, _review = compared
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


def test_comparison_shows_both_reports_quotes_and_default_keep_without_writes(app, compared):
    client, _importer, _archive, _receipt, review = compared
    before = dump(client)
    widget = comparison.LineageImportDialog(review.conflicts)
    try:
        widget.show()
        app.processEvents()
        assert widget.choices == {review.conflicts[0]["id"]: "keep"}
        assert "alternative bounded interpretation" not in widget.current.toPlainText().lower()
        assert "alternative bounded interpretation" in widget.incoming.toPlainText().lower()
        quote = review.conflicts[0]["incoming"]["report"]["statements"][0]["passages"][0]["quote"]
        assert quote in widget.incoming.toPlainText()
        assert "Location: located" in widget.incoming.toPlainText()
        image = Path(__file__).resolve().parents[1] / "build/lineage-import-comparison.png"
        assert widget.grab().save(str(image))
        widget.choice.setCurrentIndex(1)
        assert widget.choices == {review.conflicts[0]["id"]: "replace"}
        assert review.decide(widget.choices)
        assert dump(client) == before
    finally:
        widget.close()


@pytest.mark.parametrize("choice", ["keep", "replace"])
def test_real_import_comparison_choice_still_requires_final_confirmation(
    app,
    dialog,
    compared,
    monkeypatch,
    choice,
):
    client, _importer, _archive, receipt, _review = compared
    viewed = []

    def choose(widget):
        viewed.append(True)
        widget.choice.setCurrentIndex(1 if choice == "replace" else 0)
        widget.accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(comparison.LineageImportDialog, "exec", choose)
    before = dump(client)
    dialog.review()
    wait(app, lambda: dialog.reviewed and not dialog.busy)
    assert viewed == [True] and dump(client) == before
    assert dialog.apply_button.isEnabled()
    assert (
        "versions adopted" if choice == "replace" else "analyses kept"
    ) in dialog.preview.toPlainText()
    dialog.apply()
    wait(app, lambda: not dialog.busy)
    assert (
        dialog.result_data["lineage_replaced" if choice == "replace" else "lineage_preserved"] == 1
    )
    local = receipt["identity_mapping"]["focal"]["local_id"]
    row = lineage_sets.saved(client.journal.path, local)[0]
    changed = (
        "alternative bounded interpretation"
        in json.loads(row["body_json"])["report"]["statements"][0]["text"].lower()
    )
    assert changed == (choice == "replace")


def test_canceling_comparison_keeps_research_mapping_and_confirmation_disabled(
    app,
    dialog,
    compared,
    monkeypatch,
):
    client = compared[0]
    shown = []

    def cancel(widget):
        shown.append(True)
        widget.reject()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(comparison.LineageImportDialog, "exec", cancel)
    before, mapping = dump(client), dict(dialog.mapping)
    dialog.review()
    wait(app, lambda: shown and not dialog.busy)
    assert not dialog.reviewed and not dialog.apply_button.isEnabled()
    assert dialog.mapping == mapping and dump(client) == before


def test_workspace_switch_inside_comparison_cannot_queue_scientific_publication(
    app,
    dialog,
    compared,
    monkeypatch,
    tmp_path,
):
    client = compared[0]
    new_database = tmp_path / "another.sqlite"

    def changed(widget):
        widget.choice.setCurrentIndex(1)
        monkeypatch.setattr(store, "DB_PATH", new_database)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(comparison.LineageImportDialog, "exec", changed)
    before = dump(client)
    dialog.review()
    wait(app, lambda: dialog._stale and not dialog.busy)
    assert not dialog.apply_button.isEnabled() and not dialog.reviewed
    assert dump(client) == before and not new_database.exists()


def test_closing_parent_inside_comparison_drains_once_without_saving(
    app,
    dialog,
    compared,
    monkeypatch,
):
    client = compared[0]

    def closing(widget):
        dialog.reject()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(comparison.LineageImportDialog, "exec", closing)
    before = dump(client)
    dialog.review()
    wait(app, lambda: not dialog.isVisible() and not dialog.busy)
    assert dialog.result_data is None and dump(client) == before


def test_unavailable_ownership_offers_keep_only_and_no_restore_action(app, compared):
    rows = compared[4].conflicts
    rows[0]["can_replace"] = False
    widget = comparison.LineageImportDialog(rows)
    try:
        assert widget.choice.count() == 1 and widget.choice.currentData() == "keep"
        assert "unavailable" in widget.reason.text()
    finally:
        widget.close()


def test_unrecorded_model_is_explicit_without_inventing_a_version(app, compared):
    body = json.loads(json.dumps(compared[4].conflicts[0]["incoming"]))
    body["generation"]["requested_model"] = body["generation"]["returned_model"] = None
    text = comparison.version_text(body, "2026-11-14T00:00:00+00:00", "No active result")
    assert "not recorded" in text and " / None" not in text
    assert body["report"]["statements"][0]["text"] in text
