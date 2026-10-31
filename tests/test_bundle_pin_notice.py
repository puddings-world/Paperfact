"""The existing import completion shows one bounded preservation notice, no new job."""

import json

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from paper_daily.desktop.bundle_dialog import BundleDialog, queue_pin_notice


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def result():
    return {
        "name": "Shared reading",
        "pdf_conflicts": [],
        "pdf_needed": [],
        "queue_pin_preserved": [
            {
                "package_sha256": "a" * 64,
                "source_owner": "original-alias",
                "receiver_owner": "receiver-alias",
                "incoming_pinned_at": "2026-10-30T12:34:56+08:00",
                "receiver_pinned_at": "2026-10-31T12:34:56+08:00",
            }
        ],
    }


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_actual_import_completion_once_after_failure_retry_and_duplicate_callback(
    app, monkeypatch, tmp_path, language
):
    monkeypatch.setattr(BundleDialog, "_preview", lambda self: None)
    widget = BundleDialog(source=tmp_path / "shared.zip", language=language)
    try:
        widget.preview_ready = True
        widget.show()
        app.processEvents()
        widget._failed("Fixture retry")
        payload = result()
        encoded = json.dumps(payload)
        widget._done(encoded)
        first = widget.status.text()
        notice = queue_pin_notice(payload, language)
        assert notice and first.count(notice) == 1
        assert widget.result_data == payload
        assert "original-alias" not in first and "receiver-alias" not in first
        widget._done(encoded)
        assert widget.status.text() == first and widget.result_data == payload
        monkeypatch.setattr(
            widget.runner, "start", lambda *a, **k: pytest.fail("duplicate import job")
        )
        widget._start()
        widget._start()
        assert widget.status.text() == first
    finally:
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_zero_preserved_keeps_existing_completion_and_malformed_report_cannot_claim_retention(
    app, monkeypatch, tmp_path
):
    monkeypatch.setattr(BundleDialog, "_preview", lambda self: None)
    widget = BundleDialog(source=tmp_path / "shared.zip")
    try:
        payload = result()
        payload["queue_pin_preserved"] = []
        widget._done(json.dumps(payload))
        first = widget.status.text()
        payload.pop("queue_pin_preserved")
        widget._done(json.dumps(payload))
        assert widget.status.text() == first and queue_pin_notice(payload) == ""
        payload["queue_pin_preserved"] = [{"incoming_pinned_at": "not saved"}]
        assert queue_pin_notice(payload) == ""
        widget._done(json.dumps(payload))
        assert widget.status.text() == first
    finally:
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
