"""Native continuation of completed highlight results retained after delivery failure."""

import json
import sqlite3

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox
from test_archived_draft_resume_ui import answer
from test_highlight_draft_ui import verify
from test_highlight_draft_verification import ready as ready
from test_highlight_draft_verification import scene as scene
from test_highlight_draft_verification import source_pair as source_pair
from test_highlight_draft_verification import workspace as workspace
from test_highlight_native_continuation import close_host, entry, open_original, save
from test_research_generation import rows
from test_review_dialog import app as app
from test_review_dialog import wait

from paper_daily import llm
from paper_daily import research_generation as generation
from paper_daily.document_reader import DocumentReader

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_delivery_failed_result_reopens_edits_verifies_and_applies_once(
    source_pair, app, monkeypatch, language
):
    value = source_pair
    record = rows(
        value["path"], "SELECT * FROM research_generation_requests WHERE status='candidate'"
    )[0]
    context = generation.GenerationContext(record["context_json"])

    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("Synthetic delivery storage unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(generation, "_connect", unavailable)
        retained = generation.retain_failed_generated(context, json.loads(record["row_json"]))
    assert retained.status == "candidate"
    sidecar = generation._recovery_path(context)
    original_bytes = sidecar.read_bytes()
    item = next(
        item for item in value["review"].page(limit=100)["items"] if item["origin"] == "sidecar"
    )
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **k: pytest.fail("Continuation called AI")
    )
    before = rows(value["path"], "SELECT * FROM paper_highlight_analysis")
    pending = value["client"].journal.pending(1000)
    reason = "Human appraisal of a completed result preserved after delivery failed."
    host, dialog = entry(app, value["path"], "sidecar", item["id"], language)
    try:
        save(app, dialog, reason)
        open_original(app, dialog, value["original_bytes"])
        assert rows(value["path"], "SELECT * FROM paper_highlight_analysis") == before
        assert value["client"].journal.pending(1000) == pending
    finally:
        close_host(app, host)
    host, dialog = entry(app, value["path"], "sidecar", item["id"], language)
    try:
        assert dialog.fields.reason.toPlainText() == reason
        assert not dialog.apply.isEnabled()
        verify(app, dialog)
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
        dialog.apply.click()
        assert rows(value["path"], "SELECT * FROM paper_highlight_analysis") == before
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        dialog.apply.click()
        wait(app, lambda: not dialog.busy, timeout=25)
        assert dialog.applied, dialog.status.text()
        body = json.loads(
            rows(value["path"], "SELECT body_json FROM paper_highlight_analysis")[0]["body_json"]
        )
        assert body["items"][0]["reason"] == reason
        assert len(rows(value["path"], "SELECT * FROM pdf_ai_highlights")) == 2
        assert rows(value["path"], "SELECT count(*) AS n FROM research_review_receipts") == [
            dict(n=1)
        ]
        assert (
            DocumentReader.from_workspace(value["path"]).resolve("paper").sha256
            == value["current"].sha256
        )
        assert sidecar.read_bytes() == original_bytes
    finally:
        close_host(app, host)
    host, dialog = entry(app, value["path"], "sidecar", item["id"], language)
    try:
        assert dialog.fields.reason.toPlainText() == reason
        assert not dialog.apply.isEnabled() and not dialog.verify.isEnabled()
        assert rows(value["path"], "SELECT count(*) AS n FROM research_review_receipts") == [
            dict(n=1)
        ]
    finally:
        close_host(app, host)
