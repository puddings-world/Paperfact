"""Actual native complete rescue -> local-only retention -> reviewed editable slides."""

import hashlib
import sqlite3
import threading
import time
from contextlib import closing

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from test_local_blob_binding import no_external as no_external
from test_local_deck_proposals import local as local
from test_local_rescue_import import rescued as rescued
from test_portable_deck_proposal import scientific as scientific

from paper_daily import local_deck_proposals as catalog
from paper_daily import local_rescue_import, presentations
from paper_daily import portable_deck_archive as archive
from paper_daily import portable_deck_proposal as codec
from paper_daily.desktop.pending_generation import PendingDeckHub
from paper_daily.desktop.rescue_import_dialog import RescueImportDialog
from paper_daily.desktop.window_workspace import WindowWorkspace


def settle(app, predicate, timeout=15):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate()


@pytest.fixture
def native_ui(monkeypatch):
    app = QApplication.instance() or QApplication([])
    pending = PendingDeckHub(app)
    monkeypatch.setattr(app, "_pending_deck_hub", pending, raising=False)
    dialogs = []
    yield app, pending, dialogs
    for dialog in reversed(dialogs):
        settle(app, lambda dialog=dialog: not dialog.busy)
        if not isinstance(dialog, RescueImportDialog):
            settle(app, lambda dialog=dialog: not dialog.jobs)
        dialog.close()
        dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert not pending.results.pending


def open_rescue(native_ui, rescued, monkeypatch, language="en"):
    app, _pending, dialogs = native_ui
    dialog = RescueImportDialog(WindowWorkspace.capture(), language=language)
    dialogs.append(dialog)
    dialog.show()
    settle(app, lambda: not dialog.busy and dialog.targets.count() == 1)
    assert dialog.targets.currentItem() is None
    source = rescued[1].source_path
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: (str(source), ""))
    dialog.choose()
    settle(app, lambda: not dialog.busy)
    assert dialog.source is not None, dialog.status.text()
    assert dialog.images.count() == 3 and dialog.text.isReadOnly()
    assert not dialog.retain_button.isEnabled()
    target = dialog.targets.item(0)
    assert target.data(Qt.ItemDataRole.UserRole)["id"] == "local-paper"
    dialog.targets.setCurrentItem(target)
    assert dialog.retain_button.isEnabled()
    return dialog


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_actual_local_rescue_ui_retains_then_confirms_once_without_sync(
    native_ui, rescued, scientific, monkeypatch, language
):
    database, _source, _job, saved, before = rescued
    dialog = open_rescue(native_ui, rescued, monkeypatch, language)
    for _ in range(25):
        dialog.retain_button.click()
    app, pending, dialogs = native_ui
    settle(app, lambda: not dialog.busy)
    assert dialog.result is not None, dialog.status.text()
    assert dialog.result["origin"] == "local_deck" and not pending.results.pending
    assert saved.read_bytes() == before
    identity = dialog.result["candidate_id"]
    dialog.review_button.click()
    review = dialog.review_dialog
    dialogs.append(review)
    settle(app, lambda: review.preview is not None and not review.jobs)
    assert review.selection_key == ("local_deck", identity)
    assert not review.apply.isEnabled() and scientific[0].title in review.draft.toPlainText()
    assert "Local receiver" in review.list.currentItem().text()
    review.refresh.click()
    settle(app, lambda: review.preview is not None and not review.jobs)
    assert review.apply.isEnabled(), review.status.text()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Cancel
    )
    review.apply.click()
    assert saved.read_bytes() == before
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes
    )
    for _ in range(25):
        review.apply.click()
    settle(app, lambda: not review.busy and not review.jobs)
    assert review.status.text() == review.words["saved_local"]
    loaded = presentations.load_deck("local-paper", "guide")
    assert loaded.title == scientific[0].title
    assert loaded.slides[0].speaker_notes == scientific[0].slides[0].speaker_notes
    for key, value in scientific[2].items():
        assert presentations.figure_bytes(loaded, key) == value
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT count(*) FROM " + catalog.TABLE).fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM research_review_receipts").fetchone() == (1,)
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_sync_binding'"
        ).fetchone()


def test_unsaved_local_import_remains_app_owned_after_dialog_is_closed(
    native_ui, rescued, monkeypatch
):
    database, _source, _job, saved, before = rescued
    dialog = open_rescue(native_ui, rescued, monkeypatch)
    actual = catalog._insert

    def failed(*args, **kwargs):
        actual(*args, **kwargs)
        raise sqlite3.OperationalError("Synthetic native import metadata failure")

    monkeypatch.setattr(catalog, "_insert", failed)
    dialog.retain_button.click()
    app, pending, _dialogs = native_ui
    settle(app, lambda: not dialog.busy)
    assert dialog.result is None and dialog.pending_key is not None
    assert dialog.status.text() == dialog.words["unsaved"]
    assert saved.read_bytes() == before and pending.results.pending
    key, outcome = pending.results.items()[0]
    dialog.close()
    assert dialog.disposed and not dialog.isVisible()
    monkeypatch.setattr(catalog, "_insert", actual)
    repaired = pending.results.retry(key)
    assert repaired.durable and repaired.deck is outcome.deck and not pending.results.pending
    assert saved.read_bytes() == before
    info = database.stat()
    assert catalog.read(
        database, repaired.candidate_id, expected_native=(info.st_dev, info.st_ino)
    ).current_parent


def test_close_during_admitted_local_retention_holds_complete_result_before_delivery(
    native_ui, rescued, monkeypatch
):
    _database, _source, _job, saved, before = rescued
    dialog = open_rescue(native_ui, rescued, monkeypatch)
    actual = catalog.retain
    admitted, release = threading.Event(), threading.Event()

    def held(*args, **kwargs):
        admitted.set()
        assert release.wait(15)
        return actual(*args, **kwargs)

    monkeypatch.setattr(catalog, "retain", held)
    dialog.retain_button.click()
    app, pending, _dialogs = native_ui
    try:
        settle(app, admitted.is_set)
        assert dialog.busy and not dialog.retain_button.isEnabled()
        dialog.close()
        assert dialog._closing and dialog.lease.closed.is_set()
    finally:
        release.set()
    settle(app, lambda: not dialog.busy)
    assert dialog.disposed and pending.results.pending and saved.read_bytes() == before
    key, outcome = pending.results.items()[0]
    monkeypatch.setattr(catalog, "retain", actual)
    repaired = pending.results.retry(key)
    assert repaired.durable and repaired.deck is outcome.deck and not pending.results.pending
    assert saved.read_bytes() == before


def test_rescue_preview_and_retention_keep_evidence_only_image_and_its_other_original(
    native_ui, local, scientific, monkeypatch
):
    database, _manifest, _blobs, saved, before = local
    deck, evidence, images, originals, sha, other_pdf = scientific
    other_hash = hashlib.sha256(other_pdf).hexdigest()
    evidence["figures"].append(
        dict(
            id="evidence:four", label="Evidence-only image", caption="Complete fourth caption",
            document_hash=other_hash, page=1,
        )
    )
    images["evidence:four"] = images["figure:1"]
    originals[other_hash] = other_pdf
    manifest, blobs = codec.encode(
        deck, evidence, images, originals, source_document_hash=sha
    )
    path = database.parent / "evidence-only.paperfact-draft.zip"
    archive.export(path, manifest, lambda item: blobs[item["sha256"]])
    source = archive.inspect_file(path)
    dialog = RescueImportDialog(WindowWorkspace.capture(), language="en")
    app, _pending, dialogs = native_ui
    dialogs.append(dialog)
    dialog.show()
    settle(app, lambda: not dialog.busy and dialog.targets.count() == 1)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: (str(path), ""))
    dialog.choose()
    settle(app, lambda: not dialog.busy)
    assert dialog.source is not None and dialog.images.count() == 4, dialog.status.text()
    fourth = next(
        dialog.images.item(i) for i in range(dialog.images.count())
        if dialog.images.item(i).data(Qt.ItemDataRole.UserRole)["id"] == "evidence:four"
    )
    dialog.images.setCurrentItem(fourth)
    assert "Complete fourth caption" in dialog.image_detail.toPlainText()
    assert other_hash in dialog.image_detail.toPlainText()
    dialog.targets.setCurrentItem(dialog.targets.item(0))
    dialog.retain_button.click()
    settle(app, lambda: not dialog.busy)
    assert dialog.result and dialog.result["durable"], dialog.status.text()
    info = database.stat()
    value = catalog.read(
        database, dialog.result["candidate_id"], expected_native=(info.st_dev, info.st_ino)
    )
    assert value.content["deck"] == source.content["deck"]
    assert len(value.content["deck"]["figures"]) == 3
    assert value.content["evidence"] == source.content["evidence"]
    assert value.content["image_bytes"] == images and value.content["original_bytes"] == originals
    assert saved.read_bytes() == before


def test_native_chooser_recognizes_actual_zip_even_with_a_json_filename(
    native_ui, rescued, monkeypatch
):
    database, source, job, saved, before = rescued
    renamed = source.source_path.with_suffix(".json")
    source.source_path.rename(renamed)
    actual = archive.inspect_file(renamed)
    updated = (database, actual, job, saved, before)
    dialog = open_rescue(native_ui, updated, monkeypatch)
    assert dialog.source.current() and dialog.images.count() == 3
    assert saved.read_bytes() == before


def test_pending_panel_cancel_then_complete_export_uses_zip_and_keeps_originals(
    native_ui, rescued, scientific, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor

    from PySide6.QtWidgets import QLabel, QWidget

    from paper_daily.desktop.pending_generation import PendingDeckPanel

    _database, _source, job, saved, before = rescued
    actual = catalog.retain

    def denied(*_args, **_kwargs):
        raise sqlite3.OperationalError("Synthetic pending panel save failure")

    monkeypatch.setattr(catalog, "retain", denied)
    result = local_rescue_import.run(job)
    assert not result.durable
    app, pending, _dialogs = native_ui
    key = pending.hold(result)
    pane = QWidget()
    pane.language = "en"
    pane.status = QLabel(pane)
    pane._update_controls = lambda: None
    panel = PendingDeckPanel(pane)
    pane.pending_panel = panel
    requests, choices = [], []
    monkeypatch.setattr(
        panel.runner, "start", lambda prompt, done, failed, **kw: requests.append(
            dict(kw, done=done, failed=failed)
        )
    )

    def cancelled(*args, **_kwargs):
        choices.append(args)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", cancelled)
    try:
        panel.export_button.click()
        assert choices[-1][2].endswith(".paperfact-draft.zip")
        assert "*.paperfact-draft.zip" in choices[-1][3]
        assert pending.results.items() == [(key, result)] and not requests
        destination = saved.parent / "panel-copy.paperfact-draft.zip"
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", lambda *a, **kw: (str(destination), "")
        )
        panel.export_button.click()
        assert len(requests) == 1 and not panel.export_button.isEnabled()
        for _ in range(25):
            panel.export_button.click()
        assert len(requests) == 1
        with ThreadPoolExecutor(max_workers=1) as executor:
            outcome, reason = executor.submit(requests[0]["call"], "").result(timeout=15)
        assert outcome == "exported" and reason == "ok"
        requests[0]["done"](outcome)
        app.processEvents()
        assert not pending.results.pending and not panel.isVisibleTo(pane)
        exported = archive.inspect_file(destination).content
        assert exported["image_bytes"] == scientific[2]
        assert exported["original_bytes"] == scientific[3]
        assert saved.read_bytes() == before
    finally:
        monkeypatch.setattr(catalog, "retain", actual)
        for remaining, value in pending.results.items():
            pending.results.discard(remaining, expected=value)
        pane.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
