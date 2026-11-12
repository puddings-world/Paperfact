"""Native draft-original A viewer preserves selected B and human edit buffers."""

import threading

import pytest
from PySide6.QtCore import QThread, QTimer
from test_archived_draft_resume_ui import choose_target
from test_archived_draft_resumption import client_for, rows
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_review_dialog import app as app
from test_review_dialog import opened, wait

from paper_daily.desktop import original_version


def resumed(app, value, language="en"):
    value["review"].close()
    view = opened(app, value["path"], language=language)
    QTimer.singleShot(0, choose_target)
    view.resume_button.click()
    wait(app, lambda: view.preview is not None and view.preview.data["apply"], timeout=20)
    assert view._save_pending(all_items=True)
    return view


def source_view(app, view):
    wait(app, lambda: view.originals.viewer is not None, timeout=20)
    viewer = view.originals.viewer
    wait(
        app,
        lambda: (
            viewer.disposed
            or (viewer.pdf.pageCount() > 0 if viewer.native else viewer._rendered_page >= 0)
        ),
        timeout=20,
    )
    assert not viewer.disposed
    return viewer


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_actual_source_button_opens_a_once_and_private_edit_refresh_retains_b(
    copied, app, monkeypatch, language
):
    view = resumed(app, copied, language)
    calls, threads = [], []
    original = original_version.prepare_resumed_draft
    parse = original_version.pymupdf.open
    before = client_for(copied["path"]).journal.pending()
    current = copied["current"].path.read_bytes()

    def prepared(*args, **kwargs):
        calls.append(args[2])
        return original(*args, **kwargs)

    def parsed(*args, **kwargs):
        threads.append(QThread.currentThread() != app.thread())
        return parse(*args, **kwargs)

    monkeypatch.setattr(original_version, "prepare_resumed_draft", prepared)
    monkeypatch.setattr(original_version.pymupdf, "open", parsed)
    try:
        assert view.originals.widget.isVisible() and view.originals.button.isEnabled()
        for _index in range(25):
            view.originals.button.click()
        viewer = source_view(app, view)
        assert calls == [copied["value"]["source_hash"]] and threads and all(threads)
        assert viewer.snapshot.data == copied["value"]["original_bytes"]
        assert viewer.snapshot.document_hash != copied["current"].sha256
        old = viewer.snapshot
        view.draft.setPlainText("Edit retained while original A is open")
        assert view._save_pending(all_items=True)
        viewer.check()
        for _index in range(10):
            view.originals.button.click()
        wait(
            app,
            lambda: viewer.disposed or (viewer.snapshot is not old and not viewer.busy),
            timeout=20,
        )
        assert not viewer.disposed and viewer.view.isEnabled()
        assert viewer.snapshot.data == copied["value"]["original_bytes"]
        assert calls == [copied["value"]["source_hash"]]
        assert view.draft.toPlainText() == "Edit retained while original A is open"
        assert copied["current"].path.read_bytes() == current
        assert client_for(copied["path"]).journal.pending() == before
        assert rows(copied["path"], "SELECT body FROM close_readings") == [
            ("Human-reviewed interpretation",)
        ]
    finally:
        view.close()
        wait(app, lambda: view.disposed, timeout=20)


@pytest.mark.parametrize("action", ["close", "switch"])
def test_held_original_read_never_opens_in_closed_or_different_draft(
    copied, app, monkeypatch, action
):
    view = resumed(app, copied)
    before = client_for(copied["path"]).journal.pending()
    entered, release = threading.Event(), threading.Event()
    original = original_version.prepare_resumed_draft

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return original(*args, **kwargs)

    monkeypatch.setattr(original_version, "prepare_resumed_draft", held)
    try:
        text = view.draft.toPlainText()
        view.originals.button.click()
        wait(app, entered.is_set, timeout=15)
        future = view.originals.future
        if action == "close":
            view.close()
            assert view.disposed
        else:
            view.list.setCurrentRow(1)
            wait(app, lambda: view.preview is not None, timeout=15)
            assert view.draft.toPlainText() != text
            other = view.draft.toPlainText()
        release.set()
        assert future.result(timeout=15) is None
        if action == "switch":
            wait(app, lambda: not view.jobs, timeout=15)
            assert view.draft.toPlainText() == other and view.draft.isReadOnly()
        else:
            app.processEvents()
            assert not view.isVisible()
        assert view.originals.viewer is None
        assert client_for(copied["path"]).journal.pending() == before
    finally:
        release.set()
        view.close()
        wait(app, lambda: view.disposed, timeout=20)


def test_close_waits_for_actual_fallback_render_without_losing_private_text(
    copied, app, monkeypatch
):
    monkeypatch.setattr(original_version, "HAVE_QTPDF", False)
    view = resumed(app, copied)
    view.draft.setPlainText("Preserve edit through held read-only render")
    assert view._save_pending(all_items=True)
    before = client_for(copied["path"]).journal.pending()
    entered, release = threading.Event(), threading.Event()
    render = original_version.render_page

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return render(*args, **kwargs)

    monkeypatch.setattr(original_version, "render_page", held)
    try:
        view.originals.button.click()
        wait(app, lambda: entered.is_set() and view.originals.viewer is not None, timeout=20)
        viewer = view.originals.viewer
        assert viewer.busy
        view.close()
        assert not view.disposed
        release.set()
        wait(app, lambda: view.disposed and viewer.disposed, timeout=20)
        assert client_for(copied["path"]).journal.pending() == before
        assert rows(copied["path"], "SELECT body FROM research_review_drafts") == [
            ("Preserve edit through held read-only render",)
        ]
    finally:
        release.set()
        view.close()
        wait(app, lambda: view.disposed, timeout=20)


def test_sql_failure_reenables_original_button_and_actual_retry_opens_a(copied, app, monkeypatch):
    import sqlite3

    from paper_daily import resumed_draft_originals

    view = resumed(app, copied)
    before = client_for(copied["path"]).journal.pending()
    prepare = resumed_draft_originals.prepare
    calls = []

    def once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.DatabaseError("Synthetic temporary source metadata failure")
        return prepare(*args, **kwargs)

    monkeypatch.setattr(resumed_draft_originals, "prepare", once)
    try:
        text = view.draft.toPlainText()
        view.originals.button.click()
        wait(app, lambda: not view.jobs, timeout=20)
        assert view.originals.viewer is None
        assert view.originals.button.isEnabled() and not view.originals.opening
        assert view.draft.toPlainText() == text
        assert view.status.text() == view.originals.t["failed"]
        view.originals.button.click()
        viewer = source_view(app, view)
        assert viewer.snapshot.data == copied["value"]["original_bytes"]
        assert len(calls) == 2
        assert client_for(copied["path"]).journal.pending() == before
    finally:
        view.close()
        wait(app, lambda: view.disposed, timeout=20)
