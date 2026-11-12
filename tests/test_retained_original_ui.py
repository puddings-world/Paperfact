"""Actual retained review opens A read-only, coalesces clicks and rejects late results."""

import hashlib
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThread
from PySide6.QtWidgets import QApplication, QMessageBox
from test_retained_originals import context as context
from test_retained_originals import local as local
from test_retained_originals import no_external as no_external
from test_retained_originals import rows, source_bytes
from test_retained_originals import scientific as scientific
from test_retained_originals import union_package as union_package

from paper_daily import llm, retained_originals
from paper_daily.desktop import original_version
from paper_daily.desktop.review_dialog import ReviewDialog


def settle(app, predicate, timeout=20):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate()


@pytest.fixture
def view(context):
    app = QApplication.instance() or QApplication([])
    dialog = ReviewDialog(service=context.service, language="zh-TW")
    dialog.show()
    settle(app, lambda: dialog.preview is not None and not dialog.jobs)
    yield context, app, dialog
    if not dialog.disposed:
        dialog.close()
        settle(app, lambda: dialog.disposed)
    settle(app, lambda: all(job[0].done() for job in dialog.jobs))
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def opened(app, dialog):
    settle(app, lambda: not dialog.jobs and dialog.originals.viewer is not None)
    viewer = dialog.originals.viewer
    settle(
        app,
        lambda: (
            viewer.disposed
            or (viewer.pdf.pageCount() > 0 if viewer.native else viewer._rendered_page >= 0)
        ),
    )
    assert not viewer.disposed
    return viewer


def test_actual_retained_review_reads_exact_original_once_and_preserves_research(view, monkeypatch):
    c, app, dialog = view
    before = rows(c.service.path)
    originals_before = source_bytes(c.service.path)
    assert dialog.originals.widget.isVisible() and dialog.originals.button.isEnabled()
    assert dialog.evidence.isReadOnly()
    assert "Keep full fourth caption" in dialog.evidence.toPlainText()
    parse, parsed_off_thread, calls = original_version.pymupdf.open, [], []
    prepare = original_version.prepare_retained

    def forbidden(*a, **kw):
        pytest.fail("Original view accessed AI accounts/models")

    def parsed(*a, **kw):
        parsed_off_thread.append(QThread.currentThread() != app.thread())
        return parse(*a, **kw)

    def prepared(*a, **kw):
        calls.append(a[2])
        return prepare(*a, **kw)

    monkeypatch.setattr(original_version, "prepare_retained", prepared)
    monkeypatch.setattr(original_version.pymupdf, "open", parsed)
    monkeypatch.setattr(llm, "capture_connections", forbidden)
    monkeypatch.setattr(llm, "complete_result", forbidden)
    for _ in range(25):
        dialog.originals.button.click()
    viewer = opened(app, dialog)
    assert calls == [c.case.original_sha] and all(parsed_off_thread)
    assert viewer.snapshot.document_hash == c.case.original_sha
    assert hashlib.sha256(viewer.snapshot.data).hexdigest() == c.case.original_sha
    assert viewer.snapshot.data == c.case.expected["original_bytes"][c.case.original_sha]
    assert not hasattr(viewer.view, "selection")
    for _ in range(5):
        dialog.originals.button.click()
    assert calls == [c.case.original_sha] and dialog.originals.viewer is viewer
    assert rows(c.service.path) == before
    assert source_bytes(c.service.path) == originals_before
    assert c.case.saved.read_bytes() == c.case.saved_before
    assert "唯讀" in dialog.status.text()


def test_corrupt_original_reports_failure_and_explicit_retry_can_open(view):
    c, app, dialog = view
    proof = retained_originals.prepare(c.service, dialog.preview, c.case.original_sha)
    proof.source.write_bytes(b"corrupt owned original")
    dialog.originals.button.click()
    settle(app, lambda: not dialog.jobs)
    assert dialog.originals.viewer is None and dialog.originals.button.isEnabled()
    assert dialog.status.text() == dialog.originals.t["failed"]
    proof.source.write_bytes(proof.data)
    dialog.originals.button.click()
    viewer = opened(app, dialog)
    assert viewer.snapshot.data == proof.data
    proof.source.write_bytes(b"damaged after the viewer opened")
    assert not dialog.originals.open()
    settle(app, lambda: viewer.disposed)
    assert dialog.originals.viewer is None
    assert dialog.status.text() == dialog.originals.t["changed"]


@pytest.mark.parametrize("changed", ["selection", "close"])
def test_late_prepared_original_never_opens_for_a_changed_or_closed_review(
    view, monkeypatch, changed
):
    c, app, dialog = view
    prepare = original_version.prepare_retained
    entered, release = threading.Event(), threading.Event()

    def held(*args, **kwargs):
        result = prepare(*args, **kwargs)
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(original_version, "prepare_retained", held)
    before = rows(c.service.path)
    dialog.originals.button.click()
    try:
        settle(app, entered.is_set)
        if changed == "selection":
            dialog.list.setCurrentRow(-1)
            assert dialog.preview is None
        else:
            dialog.close()
            assert dialog.disposed
    finally:
        release.set()
    settle(app, lambda: all(job[0].done() for job in dialog.jobs))
    app.processEvents()
    assert dialog.originals.viewer is None
    assert rows(c.service.path) == before


def test_parent_close_waits_for_owned_original_renderer_to_drain(view, monkeypatch):
    _c, app, dialog = view
    entered, release = threading.Event(), threading.Event()
    render = original_version.render_page

    def held(*args):
        entered.set()
        assert release.wait(10)
        return render(*args)

    monkeypatch.setattr(original_version, "HAVE_QTPDF", False)
    monkeypatch.setattr(original_version, "render_page", held)
    dialog.originals.button.click()
    try:
        settle(app, entered.is_set)
        viewer = dialog.originals.viewer
        assert viewer is not None and viewer.busy
        dialog.close()
        assert not dialog.disposed and viewer._closing

        def reopened():
            pytest.fail("A closing source viewer was reopened")

        monkeypatch.setattr(viewer, "show", reopened)
        assert not dialog.originals.open()
    finally:
        release.set()
    settle(app, lambda: dialog.disposed and viewer.disposed)


def test_close_retires_apply_authority_before_waiting_for_original_renderer(view, monkeypatch):
    c, app, dialog = view
    dialog.refresh.click()
    settle(app, lambda: dialog.preview is not None and not dialog.jobs)
    assert dialog.apply.isEnabled()
    before, prior_deck = rows(c.service.path), c.case.saved.read_bytes()
    rendering, render_release = threading.Event(), threading.Event()
    applying, apply_release = threading.Event(), threading.Event()
    render, decide = original_version.render_page, c.service.decide

    def held_render(*args):
        rendering.set()
        assert render_release.wait(10)
        return render(*args)

    def held_decide(*args, **kwargs):
        applying.set()
        assert apply_release.wait(10)
        return decide(*args, **kwargs)

    monkeypatch.setattr(original_version, "HAVE_QTPDF", False)
    monkeypatch.setattr(original_version, "render_page", held_render)
    monkeypatch.setattr(c.service, "decide", held_decide)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog.originals.button.click()
    try:
        settle(app, rendering.is_set)
        dialog.apply.click()
        settle(app, applying.is_set)
        dialog.close()
        assert not dialog.disposed
        assert c.service.closed
        apply_release.set()
        settle(app, lambda: all(job[0].done() for job in dialog.jobs))
        assert rows(c.service.path) == before
        assert c.case.saved.read_bytes() == prior_deck
    finally:
        apply_release.set()
        render_release.set()
    settle(app, lambda: dialog.disposed)
