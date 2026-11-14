"""Native import review exercises actual saved data and GUI delivery boundaries."""

import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QInputDialog
from test_lineage_jobs import work
from test_package_review import codec as codec
from test_package_review import dump
from test_package_review import package as package
from test_package_review import pair as pair
from test_package_review import review as review

from paper_daily import store
from paper_daily.desktop import package_review_dialog as ui


@pytest.fixture(scope="session")
def app():
    from paper_daily.desktop import fonts

    application = QApplication.instance() or QApplication([])
    fonts.load()
    application.setStyle("Fusion")
    application.setFont(fonts.font(fonts.SANS, pixels=fonts.UI_PIXELS))
    return application


def wait(app, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "GUI review did not reach its expected state"
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def close(app, widget):
    widget.reject()
    wait(app, lambda: not widget.busy and not widget.isVisible())
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def dialog(app, review, monkeypatch):
    monkeypatch.setattr(ui, "PackageReview", lambda *_a, **_k: review)
    widget = ui.PackageReviewDialog(
        review.importer.database, review.importer.root, review.archive, language="en"
    )
    widget.show()
    wait(app, lambda: widget.session is not None and not widget.busy)
    yield widget
    close(app, widget)


def test_actual_review_requires_separate_confirmation_and_repeated_apply_saves_once(
    app,
    dialog,
    review,
):
    before = dump(review)
    assert dialog.table.item(0, 0).text() == "Original paper"
    assert not dialog.apply_button.isEnabled()
    for _ in range(20):
        dialog.review()
    wait(app, lambda: not dialog.busy)
    assert dialog.reviewed and dialog.apply_button.isEnabled()
    assert "Reading" in dialog.preview.toPlainText()
    assert "identity_mapping" not in dialog.preview.toPlainText()
    assert dump(review) == before
    screenshot = Path(__file__).resolve().parents[1] / "build/package-review-desktop.png"
    assert dialog.grab().save(str(screenshot))
    for _ in range(20):
        dialog.apply()
    wait(app, lambda: not dialog.busy)
    assert dialog.result_data["state"] == "applied_locally"
    assert "saved locally" in dialog.status.text()
    after = dump(review)
    assert after != before
    for _ in range(20):
        dialog.apply()
    app.processEvents()
    assert not dialog.busy and dump(review) == after


def test_failure_then_retry_retains_choices_and_never_enables_apply_early(
    app,
    dialog,
    review,
    monkeypatch,
):
    original = review.prepare
    calls = []

    def flaky(**options):
        calls.append(True)
        if len(calls) == 1:
            raise ValueError("Choose a different destination")
        return original(**options)

    monkeypatch.setattr(review, "prepare", flaky)
    before = dump(review)
    dialog.review()
    wait(app, lambda: not dialog.busy)
    assert "different destination" in dialog.status.text()
    assert not dialog.apply_button.isEnabled() and dump(review) == before
    dialog.review()
    wait(app, lambda: not dialog.busy)
    assert dialog.apply_button.isEnabled() and dump(review) == before


def test_close_held_prepare_waits_and_cancels_without_saved_research(
    app,
    dialog,
    review,
    monkeypatch,
):
    entered, release = threading.Event(), threading.Event()
    original = review.prepare

    def held(**options):
        entered.set()
        assert release.wait(20)
        return original(**options)

    monkeypatch.setattr(review, "prepare", held)
    before = dump(review)
    dialog.review()
    wait(app, entered.is_set)
    dialog.reject()
    assert dialog.busy and dialog.isVisible()
    release.set()
    wait(app, lambda: not dialog.busy and not dialog.isVisible())
    assert dialog.result_data is None and dump(review) == before


def test_workspace_switch_after_worker_finish_refuses_actual_queued_delivery(
    app,
    dialog,
    review,
    monkeypatch,
    tmp_path,
):
    before = dump(review)
    dialog.review()
    deadline = time.monotonic() + 30
    while not dialog._future.done():
        assert time.monotonic() < deadline
        time.sleep(0.005)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "another.sqlite")
    app.processEvents()
    wait(app, lambda: not dialog.busy)
    assert not dialog.reviewed and not dialog.apply_button.isEnabled()
    assert not dialog.review_button.isEnabled()
    assert "workspace changed" in dialog.status.text()
    assert dialog.result_data is None and dump(review) == before


def test_explicit_search_mapping_and_reset_invalidate_prepared_confirmation(
    app,
    dialog,
    review,
    monkeypatch,
):
    work(review.prepare)
    receipt = work(review.apply)
    target = receipt["identity_mapping"]["ref:example"]["local_id"]
    monkeypatch.setattr(QInputDialog, "getText", lambda *_a, **_k: ("Original", True))
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **_k: (a[3][0], True))
    dialog.choose(0)
    wait(app, lambda: not dialog.busy)
    assert dialog.mapping == {"ref:example": target}
    dialog.review()
    wait(app, lambda: not dialog.busy)
    assert dialog.reviewed
    dialog.reset(0)
    assert dialog.mapping == {} and not dialog.apply_button.isEnabled()


def test_cancel_search_keeps_original_mapping_and_review(app, dialog, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *_a, **_k: ("", False))
    dialog.review()
    wait(app, lambda: not dialog.busy)
    before = dialog.preview.toPlainText()
    dialog.choose(0)
    assert not dialog.busy and dialog.mapping == {}
    assert dialog.preview.toPlainText() == before and dialog.reviewed


def test_committed_result_after_workspace_switch_reports_saved_without_navigation(
    app,
    dialog,
    review,
    monkeypatch,
    tmp_path,
):
    dialog.review()
    wait(app, lambda: not dialog.busy)
    before = dump(review)
    dialog.apply()
    deadline = time.monotonic() + 30
    while not dialog._future.done():
        assert time.monotonic() < deadline
        time.sleep(0.005)
    assert dialog._ticket.published and dump(review) != before
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "different.sqlite")
    app.processEvents()
    wait(app, lambda: not dialog.busy)
    assert dialog.result_data is None and not dialog.apply_button.isEnabled()
    assert "saved locally" in dialog.status.text() and "workspace changed" in dialog.status.text()


def test_native_import_factory_uses_review_without_legacy_writer(app, review, monkeypatch):
    from paper_daily.desktop import bundle_dialog

    monkeypatch.setattr(
        bundle_dialog, "BundleDialog", lambda *_a, **_k: pytest.fail("legacy writer")
    )
    widget = bundle_dialog.import_dialog(source=review.archive)
    try:
        assert isinstance(widget, ui.PackageReviewDialog)
    finally:
        close(app, widget)


def test_unbound_import_factory_preserves_original_constructor_contract(app, monkeypatch, tmp_path):
    from paper_daily.desktop import bundle_dialog

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "empty.sqlite")
    calls = []

    def legacy(parent, *, source, download_missing=False):
        calls.append((parent, source, download_missing))
        return "legacy-dialog"

    monkeypatch.setattr(bundle_dialog, "BundleDialog", legacy)
    assert (
        bundle_dialog.import_dialog(source="fixture.zip", download_missing=False) == "legacy-dialog"
    )
    assert calls == [(None, "fixture.zip", False)]


def test_long_duplicate_titles_have_short_distinct_choices_and_keep_exact_target_ids(
    app,
    dialog,
    review,
    monkeypatch,
):
    from test_sync_files import paper_payload

    identities = ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"]
    for identity in identities:
        review.importer.client.save(
            review.importer.client.new_graph_operation(
                "paper",
                identity,
                {**paper_payload(), "title": "Research " * 50},
            )
        )
    monkeypatch.setattr(QInputDialog, "getText", lambda *_a, **_k: ("Research", True))

    def selected(*args, **_kwargs):
        choices = args[3]
        assert len(choices) == len(set(choices)) == 2
        assert all(len(label) < 150 for label in choices)
        return choices[0], True

    monkeypatch.setattr(QInputDialog, "getItem", selected)
    dialog.choose(0)
    wait(app, lambda: not dialog.busy)
    assert dialog.mapping == {"ref:example": "sync:" + identities[0]}
