"""Native UI keeps actual unsaved results outside the saved editor."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from shiboken6 import isValid
from test_raw_deck_receipts import codec as _codec
from test_raw_deck_receipts import no_external as _no_external
from test_raw_deck_receipts import original as _original
from test_raw_deck_receipts import retained

from paper_daily import llm, presentations, raw_deck_receipts, store
from paper_daily.ai_types import Settings
from paper_daily.desktop.pending_generation import PendingDeckHub
from paper_daily.desktop.presentation_pane import PresentationPane
from paper_daily.pending_deck_result import read_export
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_deck_publication import IncompleteDraftRetention

codec = _codec
no_external = _no_external
original = _original


def execute(request):
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(request["call"], "").result(timeout=60)


@pytest.fixture
def pending(original, monkeypatch):
    app = QApplication.instance() or QApplication([])
    value = PendingDeckHub(app)
    monkeypatch.setattr(app, "_pending_deck_hub", value, raising=False)
    a, b, fa, deck, images, evidence, observation = original
    presentations.save_deck(deck, observation=observation, evidence=evidence)
    before = presentations.load_deck(deck.paper_id, deck.mode).to_dict()
    deck.title = "Completed but unsaved research"
    real_begin, real_write = BlobStore.begin, raw_deck_receipts.write_owned
    _error, outcome = retained(original, monkeypatch, blob_fail=True, receipt_fail=True)
    widget = PresentationPane()
    widget.load(deck.paper_id, deck.paper_title)
    requests, calls = [], []
    monkeypatch.setattr(llm, "settings", lambda **kwargs: Settings("gateway", model="fixture"))
    monkeypatch.setattr(llm, "available", lambda **kwargs: True)

    def produce(*args, **kwargs):
        calls.append(kwargs)
        raise IncompleteDraftRetention(outcome)

    monkeypatch.setattr(presentations, "generate", produce)
    monkeypatch.setattr(
        widget.runner,
        "start",
        lambda prompt, done, failed, **kwargs: requests.append(
            dict(kwargs, prompt=prompt, done=done, failed=failed)
        ),
    )
    yield widget, value, requests, calls, outcome, before, app, (real_begin, real_write), b
    for key, result in value.results.items():
        value.results.discard(key, expected=result)
    value.changed.emit()
    if isValid(widget):
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def deliver(state):
    widget, value, requests, calls, outcome, before, app, originals, other = state
    widget._start_generation_ready()
    answer, reason = execute(requests[0])
    assert len(value.results.items()) == 1
    assert value.results.items()[0][1] is outcome
    assert answer is None
    requests[0]["failed"](reason)
    app.processEvents()
    return widget.pending_panel


def test_total_failure_holds_result_before_callback_and_does_not_replace_saved_editor(pending):
    widget, value, requests, calls, outcome, before, app, originals, other = pending
    panel = deliver(pending)
    assert value.results.pending and widget.busy and panel.isVisibleTo(widget)
    assert widget.deck.to_dict() == before
    assert presentations.load_deck(widget.paper_id, widget._mode).to_dict() == before
    assert not widget.generate_button.isEnabled() and len(calls) == 1
    assert "尚未儲存" in panel.notice.text()
    widget.load("different-paper", "Different")
    assert widget.paper_id == outcome.deck.paper_id and widget.deck.to_dict() == before
    assert not widget.close()
    requests[0]["failed"]("duplicate callback")
    assert len(value.results.items()) == 1
    assert value.results.items()[0][1] is outcome


@pytest.mark.parametrize("change", ["database", "folder", "destroyed"])
def test_pending_result_survives_late_delivery_without_wrong_view_mutation(
    pending, monkeypatch, change
):
    widget, value, requests, calls, outcome, before, app, originals, other = pending
    widget._start_generation_ready()
    answer, reason = execute(requests[0])
    assert value.results.pending
    if change == "database":
        monkeypatch.setattr(store, "DB_PATH", other.journal.path)
    elif change == "folder":
        monkeypatch.setattr(presentations, "DECK_DIR", presentations.DECK_DIR / "other")
    else:
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    requests[0]["failed"](reason)
    assert len(value.results.items()) == 1
    assert value.results.items()[0][1] is outcome and len(calls) == 1
    if isValid(widget):
        assert widget.deck.to_dict() == before
    replacement = PresentationPane()
    assert replacement.pending_panel.pending and replacement.busy
    replacement.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_retry_failure_then_success_is_one_job_without_another_model(pending, monkeypatch):
    widget, value, requests, calls, outcome, before, app, originals, other = pending
    panel = deliver(pending)
    actions = []
    monkeypatch.setattr(
        panel.runner,
        "start",
        lambda prompt, done, failed, **kwargs: actions.append(
            dict(kwargs, prompt=prompt, done=done, failed=failed)
        ),
    )
    for _ in range(20):
        panel.retry_button.click()
    assert len(actions) == 1
    answer, reason = execute(actions[0])
    assert answer is None
    actions[0]["failed"](reason)
    assert value.results.pending and panel.retry_button.isEnabled()
    monkeypatch.setattr(BlobStore, "begin", originals[0])
    monkeypatch.setattr(raw_deck_receipts, "write_owned", originals[1])
    panel.retry_button.click()
    answer, reason = execute(actions[1])
    actions[1]["done"](answer)
    assert not value.results.pending and not widget.busy and len(calls) == 1
    assert widget.deck.to_dict() == before
    assert "等待核對" in widget.status.text()


def test_discard_requires_confirmation_and_cancellation_keeps_everything(pending):
    widget, value, requests, calls, outcome, before, app, originals, other = pending
    panel = deliver(pending)
    for _ in range(20):
        panel.discard_button.click()
    assert len([box for box in panel.findChildren(QMessageBox) if box.isVisible()]) == 1
    box = panel._confirmation
    box.button(QMessageBox.StandardButton.Cancel).click()
    app.processEvents()
    assert len(value.results.items()) == 1
    assert value.results.items()[0][1] is outcome
    panel.discard_button.click()
    box = panel._confirmation
    next(
        button
        for button in box.buttons()
        if box.buttonRole(button) == QMessageBox.ButtonRole.DestructiveRole
    ).click()
    app.processEvents()
    assert not value.results.pending and not widget.busy
    assert presentations.load_deck(widget.paper_id, widget._mode).to_dict() == before


def test_export_cancel_failure_and_verified_success_preserve_old_deck(
    pending, monkeypatch, tmp_path
):
    widget, value, requests, calls, outcome, before, app, originals, other = pending
    panel = deliver(pending)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: ("", ""))
    panel.export_button.click()
    assert value.results.pending and not panel._action
    actions = []
    monkeypatch.setattr(
        panel.runner,
        "start",
        lambda prompt, done, failed, **kwargs: actions.append(
            dict(kwargs, prompt=prompt, done=done, failed=failed)
        ),
    )
    destination = tmp_path / "snapshot.paperfact-draft.json"
    destination.write_bytes(b"previous research")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(destination), ""))
    panel.export_button.click()
    answer, reason = execute(actions[0])
    actions[0]["failed"](reason)
    assert value.results.pending and destination.read_bytes() == b"previous research"
    destination = tmp_path / "fresh.paperfact-draft.json"
    panel.export_button.click()
    answer, reason = execute(actions[1])
    actions[1]["done"](answer)
    assert not value.results.pending and not widget.busy
    assert read_export(destination.read_bytes())["image_bytes"] == original_images(outcome)
    assert presentations.load_deck(widget.paper_id, widget._mode).to_dict() == before
    assert len(calls) == 1


def original_images(outcome):
    import hashlib

    _header, objects = raw_deck_receipts.decode(outcome._capture)
    return {
        key: objects[hashlib.sha256(data).hexdigest()]
        for key, data in outcome.deck._revision_figures.items()
    }


def test_actual_main_window_defers_close_restart_and_update_until_pending_disposition(
    pending, monkeypatch
):
    from PySide6.QtGui import QCloseEvent

    from paper_daily import updates
    from paper_daily.desktop import main
    from paper_daily.desktop.account_status import AccountStatus
    from paper_daily.desktop.ai_dialog import AIStatusButton

    widget, value, requests, calls, outcome, before, app, originals, other = pending
    deliver(pending)
    monkeypatch.setattr(AccountStatus, "check", lambda *a, **kw: None)
    monkeypatch.setattr(AIStatusButton, "refresh", lambda button: button.setText("AI fixture"))
    monkeypatch.setattr(main.ReaderPage, "_check_resources", lambda *a: None)
    monkeypatch.setattr(main.ReaderPage, "_prepare_reading_highlights", lambda *a: None)
    monkeypatch.setattr(main.MainWindow, "top_up_dives", lambda *a: None)
    monkeypatch.setattr(updates, "check", lambda *a, **kw: None)
    window = main.MainWindow()
    try:
        window.show()
        app.processEvents()
        assert window.reader_page.presentation_pane.busy
        assert not window._prepare_restart()
        assert not window._prepare_update()
        event = QCloseEvent()
        window.closeEvent(event)
        assert not event.isAccepted() and window.isVisible()
        assert not window._workspace_owner.closed
        assert len(value.results.items()) == 1 and value.results.items()[0][1] is outcome
        assert len(calls) == 1
    finally:
        for key, result in value.results.items():
            value.results.discard(key, expected=result)
        value.changed.emit()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_equal_titles_show_original_workspace_before_destructive_disposition(pending, monkeypatch):
    from copy import deepcopy

    from paper_daily import raw_deck_closure
    from paper_daily import sync_deck_publication as publication

    widget, value, requests, calls, outcome, before, app, originals, other = pending
    panel = deliver(pending)
    original_database = store.DB_PATH
    monkeypatch.setattr(store, "DB_PATH", other.journal.path)
    # A new B producer has captured image bytes, not A's private loaded-artifact capability.
    second_deck = presentations.deck_from_dict(outcome.deck.to_dict())
    second_deck._revision_figures = deepcopy(outcome.deck._revision_figures)
    observed = publication.observe_deck(second_deck.paper_id, second_deck.mode)
    second = raw_deck_closure.retain_outcome(
        observed, second_deck, evidence=outcome.evidence, request_id=outcome.candidate_id
    )
    assert second._capture is not None
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(value.hold, second).result(timeout=60)
    monkeypatch.setattr(store, "DB_PATH", original_database)
    app.processEvents()
    assert panel.choice.count() == 2
    assert panel.choice.itemText(0) != panel.choice.itemText(1)
    panel.choice.setCurrentIndex(1)
    assert other.journal.path.name in panel.detail.text()
    panel.discard_button.click()
    box = panel._confirmation
    assert other.journal.path.name in box.text()
    box.button(QMessageBox.StandardButton.Cancel).click()
    app.processEvents()
    assert len(value.results.items()) == 2


def test_result_settlement_during_banner_refresh_keeps_editor_unchanged(pending, monkeypatch):
    widget, value, requests, calls, outcome, before, app, originals, other = pending
    panel = deliver(pending)
    original_label = value.results.label

    def settle_before_label(key):
        # The GUI already copied its row list when a worker settled this result.
        held = next(result for item_key, result in value.results.items() if item_key == key)
        value.results.discard(key, expected=held)
        return original_label(key)

    monkeypatch.setattr(value.results, "label", settle_before_label)
    panel.refresh()
    assert not value.results.pending and not widget.busy
    assert widget.deck.to_dict() == before
    assert presentations.load_deck(widget.paper_id, widget._mode).to_dict() == before
