"""Real recovered proposals: explicit Verify, exact original A, separate Apply."""

import hashlib
import threading
from contextlib import closing

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from shiboken6 import isValid
from test_common_proposal_recovery import actual as actual
from test_common_proposal_recovery import all_rows, count, native, preview
from test_common_proposal_recovery import case as case
from test_common_proposal_recovery import codec as codec
from test_common_proposal_recovery import local as local
from test_common_proposal_recovery import no_external as no_external
from test_common_proposal_recovery import original as original
from test_common_proposal_recovery import package as package
from test_common_proposal_recovery import receiver as receiver
from test_common_proposal_recovery import scientific as scientific
from test_retained_original_ui import opened, settle
from test_retained_originals import source_bytes

from paper_daily import enrolled_deck_proposals as catalog
from paper_daily import proposal_recovery_review as recovered
from paper_daily import retained_originals
from paper_daily.desktop import original_version
from paper_daily.desktop.review_dialog import ReviewDialog
from paper_daily.research_file_review import _storage
from paper_daily.research_review import ResearchReview
from paper_daily.sync_deck_publication import runtime


@pytest.fixture
def view(receiver):
    app = QApplication.instance() or QApplication([])
    service = ResearchReview(receiver["database"])
    dialog = ReviewDialog(service=service, language="zh-TW")
    dialog.show()
    settle(app, lambda: not dialog.jobs and dialog.list.count() > 0)
    found = [
        i for i in range(dialog.list.count())
        if recovered.virtual(dialog.list.item(i).data(Qt.ItemDataRole.UserRole)[1])
    ]
    assert len(found) == 1
    dialog.list.setCurrentRow(found[0])
    settle(app, lambda: dialog.preview is not None and not dialog.jobs)
    yield receiver, app, dialog
    if not dialog.disposed:
        dialog.close()
        settle(app, lambda: dialog.disposed)
    settle(app, lambda: all(job[0].done() for job in dialog.jobs))
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_archive_original_requires_verify_before_native_catalog_access(receiver, monkeypatch):
    service = ResearchReview(receiver["database"])
    try:
        archived = preview(service)
        before = all_rows(service.path)
        originals = source_bytes(service.path)

        def forbidden(*args, **kwargs):
            pytest.fail("An archive ID attempted native original/catalog access before Verify")

        monkeypatch.setattr(retained_originals, "_connect", forbidden)
        with pytest.raises(ValueError, match="Verify"):
            retained_originals.prepare(
                service, archived, receiver["science"]["source_document_hash"]
            )
        assert count(service.path) == 0 and all_rows(service.path) == before
        assert source_bytes(service.path) == originals
    finally:
        service.close()


def test_actual_recovered_view_verifies_reads_A_then_explicitly_applies_once(view, monkeypatch):
    c, app, dialog = view
    client = runtime(database=dialog.service.path)
    before = all_rows(dialog.service.path)
    physical = source_bytes(dialog.service.path)
    pending = client.journal.pending()
    assert recovered.virtual(dialog.preview.data["id"])
    assert dialog.originals.widget.isVisible()
    assert not dialog.originals.button.isEnabled()
    assert dialog.words["verify_slides"] in dialog.originals.button.text()
    for _ in range(25):
        dialog.originals.button.click()
        assert not dialog.originals.open()
    assert not dialog.jobs and dialog.originals.viewer is None
    assert count(dialog.service.path) == 0 and all_rows(dialog.service.path) == before
    assert client.journal.pending() == pending
    for _ in range(25):
        dialog.refresh.click()
    settle(app, lambda: dialog.preview is not None and not dialog.jobs)
    assert not recovered.virtual(dialog.preview.data["id"])
    assert count(dialog.service.path) == 1 and dialog.apply.isEnabled()
    assert dialog.preview.data["current"]["title"] == c["prior_title"]
    assert client.journal.pending() == pending
    assert dialog.originals.button.isEnabled()
    assert dialog.originals.button.text() == dialog.originals.t["open"]
    assert dialog.originals.button.toolTip() == ""
    assert dialog.words["pdf_mismatch"] in dialog.source.text()
    captions = [item["caption"] for item in c["science"]["evidence"]["figures"]]
    assert len(captions) == 4 and all(captions)
    assert all(caption in dialog.evidence.toPlainText() for caption in captions)
    verified_rows = all_rows(dialog.service.path)
    sha = c["science"]["source_document_hash"]
    prepare, calls = original_version.prepare_retained, []

    def prepared(*args, **kwargs):
        calls.append(args[2])
        return prepare(*args, **kwargs)

    monkeypatch.setattr(original_version, "prepare_retained", prepared)
    for _ in range(25):
        dialog.originals.button.click()
    viewer = opened(app, dialog)
    assert calls == [sha] and viewer.snapshot.document_hash == sha
    assert viewer.snapshot.data == c["science"]["original_bytes"][sha]
    assert hashlib.sha256(viewer.snapshot.data).hexdigest() == sha
    assert all_rows(dialog.service.path) == verified_rows
    assert source_bytes(dialog.service.path) == physical
    assert client.journal.pending() == pending
    viewer.close()
    settle(app, lambda: dialog.originals.viewer is None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Cancel)
    dialog.apply.click()
    assert not dialog.busy and not dialog.jobs
    assert all_rows(dialog.service.path) == verified_rows
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    for _ in range(25):
        dialog.apply.click()
    settle(app, lambda: not dialog.busy and not dialog.jobs)
    assert len(client.journal.pending()) == len(pending) + 1
    assert dialog.status.text() == dialog.words["saved"]
    with closing(dialog.service._connect()) as conn:
        receipts = conn.execute("SELECT decision FROM research_review_receipts").fetchall()
    assert [row[0] for row in receipts] == ["applied"]
    assert count(dialog.service.path) == 1
    with closing(dialog.service._connect()) as conn:
        cache = _storage(conn)[0]
    full = catalog.read(
        client, cache, dialog.preview.data["id"], expected_native=native(dialog.service.path)
    )
    assert full.content == c["science"] and len(full.content["image_bytes"]) == 4
    after_files = source_bytes(dialog.service.path)
    assert {key: after_files[key] for key in physical} == physical


def test_verify_error_keeps_archive_and_can_retry_without_automatic_apply(view, monkeypatch):
    c, app, dialog = view
    prepare, calls = dialog.service.prepare_file, []
    before = all_rows(dialog.service.path)

    def failed(*args, **kwargs):
        calls.append(1)
        raise ValueError("Verification unavailable; retained content remains unchanged")

    monkeypatch.setattr(dialog.service, "prepare_file", failed)
    for _ in range(25):
        dialog.refresh.click()
    settle(app, lambda: dialog.preview is not None and not dialog.jobs)
    assert calls == [1] and "Verification unavailable" in dialog.status.text()
    assert recovered.virtual(dialog.preview.data["id"])
    assert not dialog.originals.button.isEnabled() and not dialog.apply.isEnabled()
    assert all_rows(dialog.service.path) == before and count(dialog.service.path) == 0
    monkeypatch.setattr(dialog.service, "prepare_file", prepare)
    dialog.refresh.click()
    settle(app, lambda: dialog.preview is not None and not dialog.jobs)
    assert dialog.apply.isEnabled() and dialog.originals.button.isEnabled()
    assert count(dialog.service.path) == 1
    assert dialog.preview.data["current"]["title"] == c["prior_title"]


@pytest.mark.parametrize("changed", ["selection", "close"])
def test_held_archive_verify_does_not_open_or_apply_after_selection_or_close(
    view, monkeypatch, changed
):
    _c, app, dialog = view
    prepare, entered, release = dialog.service.prepare_file, threading.Event(), threading.Event()
    before = all_rows(dialog.service.path)
    pending = runtime(database=dialog.service.path).journal.pending()

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "prepare_file", held)
    dialog.refresh.click()
    try:
        settle(app, entered.is_set)
        if changed == "selection":
            dialog.list.setCurrentRow(-1)
        else:
            dialog.close()
            assert dialog.disposed
    finally:
        release.set()
    settle(app, lambda: all(job[0].done() for job in dialog.jobs))
    app.processEvents()
    assert dialog.preview is None and dialog.originals.viewer is None
    # A closed dialog retires its native widgets; one that survives stays hidden.
    widget = dialog.originals.widget
    assert not isValid(widget) or not widget.isVisible()
    if changed == "selection":
        assert isValid(widget)
    assert runtime(database=dialog.service.path).journal.pending() == pending
    if changed == "close":
        assert all_rows(dialog.service.path) == before and count(dialog.service.path) == 0
    else:
        # An explicit admitted Verify may retain an inactive proposal; never apply it.
        assert count(dialog.service.path) == 1
        assert not dialog.apply.isEnabled()
