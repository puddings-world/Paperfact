"""A finished decision keeps independently owned originals readable, never writable."""

import json
import sqlite3
import threading
from contextlib import closing

import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QMessageBox
from test_archived_draft_resume_ui import answer
from test_claim_conflict_intent import remote as remote
from test_claim_draft_storage import rows
from test_claim_draft_ui import app as app
from test_claim_remote_ui import close_host, entry, verify
from test_claim_review_continuity import claims as claims
from test_claim_review_continuity import ready as ready
from test_claim_review_continuity import receiver as receiver
from test_claim_review_continuity import scene as scene
from test_claim_review_continuity import source_pair as source_pair
from test_claim_review_continuity import workspace as workspace
from test_review_dialog import wait

from paper_daily import research_generation as generation
from paper_daily.desktop import original_version
from paper_daily.document_reader import DocumentReader
from paper_daily.sync_files import file_id
from paper_daily.sync_source_files import FEATURE

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


@pytest.fixture
def decided(remote, app, request):
    value = remote
    path = value["b"].journal.path
    host, dialog = entry(
        app, path, "remote", value["origin"].split(":", 1)[1], getattr(request, "param", "zh-TW")
    )
    try:
        dialog.fields.assertion.setPlainText("Keep original A readable after this decision.")
        verify(app, dialog)
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        dialog.apply.click()
        wait(app, lambda: not dialog.busy, timeout=20)
        value["b"].sync_once(value["service"], value["tb"], limit=1000)
        value["a"].sync_once(value["service"], value["ta"], limit=1000)
        yield dict(value, host=host, dialog=dialog)
    finally:
        close_host(app, host)


@pytest.mark.parametrize("decided", ["en", "zh-TW"], indirect=True)
@pytest.mark.parametrize("native", [False, True])
def test_decided_original_opens_readonly_without_reenabling_a_decision(
    decided, app, monkeypatch, native
):
    monkeypatch.setattr(original_version, "HAVE_QTPDF", native and original_version.HAVE_QTPDF)
    value = decided
    dialog = value["dialog"]
    path = value["b"].journal.path
    before = rows(path, "SELECT * FROM paper_claim_sets")
    assert not dialog.apply.isEnabled() and not dialog.verify.isEnabled()
    assert dialog.originals.button.isEnabled()
    for _ in range(10):
        dialog.originals.button.click()
    wait(app, lambda: dialog.originals.viewer is not None, timeout=20)
    viewer = dialog.originals.viewer
    assert viewer.snapshot.claim_read_proof is not None and viewer.snapshot.draft_proof is None
    assert viewer.snapshot.document_hash == value["value"]["source_hash"]
    assert not dialog.apply.isEnabled() and not dialog.verify.isEnabled()
    assert rows(path, "SELECT * FROM paper_claim_sets") == before
    assert not value["b"].journal.pending(1000)
    assert (
        DocumentReader.from_workspace(path).resolve(value["local"]).sha256
        == value["value"]["current"].sha256
    )
    viewer.close()
    wait(app, lambda: dialog.originals.viewer is None, timeout=20)


def opened_original(app, dialog):
    dialog.originals.button.click()
    wait(app, lambda: dialog.originals.viewer is not None, timeout=20)
    viewer = dialog.originals.viewer
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


def test_unsaved_private_text_does_not_require_save_or_grant_apply_to_read(decided, app):
    value, dialog = decided, decided["dialog"]
    path = value["b"].journal.path
    before = rows(path, "SELECT * FROM research_review_drafts")
    formal = rows(path, "SELECT * FROM paper_claim_sets")
    text = "Unfinished private wording must not block reading the actual source."
    dialog.fields.assertion.setPlainText(text)
    dialog.autosave.stop()
    assert dialog.dirty and dialog.originals.button.isEnabled()
    viewer = opened_original(app, dialog)
    assert viewer.snapshot.document_hash == value["value"]["source_hash"]
    assert rows(path, "SELECT * FROM research_review_drafts") == before
    assert rows(path, "SELECT * FROM paper_claim_sets") == formal
    assert dialog.fields.assertion.toPlainText() == text
    assert dialog.dirty and not dialog.apply.isEnabled() and not dialog.verify.isEnabled()
    assert not value["b"].journal.pending(1000)


def test_failed_read_reenables_button_and_retry_opens_the_same_original(decided, app, monkeypatch):
    from paper_daily import claim_draft_originals

    dialog = decided["dialog"]
    prepare = claim_draft_originals.prepare
    calls = []

    def once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.DatabaseError("Synthetic source metadata interruption")
        return prepare(*args, **kwargs)

    monkeypatch.setattr(claim_draft_originals, "prepare", once)
    dialog.originals.button.click()
    wait(app, lambda: not dialog.jobs, timeout=20)
    assert dialog.originals.viewer is None and not dialog.originals.opening
    assert dialog.originals.button.isEnabled()
    assert dialog.status.text() == dialog.originals.t["failed"]
    viewer = opened_original(app, dialog)
    assert len(calls) == 2 and viewer.snapshot.document_hash == decided["value"]["source_hash"]
    assert not dialog.verify.isEnabled() and not dialog.apply.isEnabled()


def test_open_original_rechecks_unrelated_saved_note_off_thread(decided, app, monkeypatch):
    value, dialog = decided, decided["dialog"]
    viewer = opened_original(app, dialog)
    original = viewer.snapshot
    parse = original_version.pymupdf.open
    threads = []

    def parsed(*args, **kwargs):
        threads.append(QThread.currentThread() != app.thread())
        return parse(*args, **kwargs)

    monkeypatch.setattr(original_version.pymupdf, "open", parsed)
    with closing(generation._connect(value["b"].journal.path)) as conn, conn:
        conn.execute("UPDATE papers SET title='A later title' WHERE id=?", (value["local"],))
    pending = value["b"].journal.pending(1000)
    viewer.check()
    for _ in range(10):
        dialog.originals.button.click()
    wait(
        app,
        lambda: viewer.disposed or (viewer.snapshot is not original and not viewer.busy),
        timeout=20,
    )
    assert not viewer.disposed and viewer.view.isEnabled()
    assert viewer.snapshot.data == original.data and threads and all(threads)
    assert value["b"].journal.pending(1000) == pending
    assert not dialog.verify.isEnabled() and not dialog.apply.isEnabled()


def test_retired_original_closes_view_and_never_uses_selected_pdf(decided, app):
    value, dialog = decided, decided["dialog"]
    viewer = opened_original(app, dialog)
    with closing(generation._connect(value["b"].journal.path)) as conn:
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (value["local"],)
        ).fetchone()[0]
    value["b"].save(
        value["b"].new_graph_operation(
            "research_file",
            file_id(portable, FEATURE, value["value"]["source_hash"]),
            {},
            action="delete",
        )
    )
    pending = value["b"].journal.pending(1000)
    viewer.check()
    wait(app, lambda: viewer.disposed and dialog.originals.viewer is None, timeout=20)
    dialog.originals.button.click()
    wait(app, lambda: not dialog.jobs, timeout=20)
    assert dialog.originals.viewer is None
    assert dialog.status.text() == dialog.originals.t["failed"]
    assert value["b"].journal.pending(1000) == pending
    assert (
        DocumentReader.from_workspace(value["b"].journal.path).resolve(value["local"]).sha256
        == value["value"]["current"].sha256
    )


@pytest.mark.parametrize("action", ["edit", "close"])
def test_held_original_never_opens_after_edit_or_parent_close(decided, app, monkeypatch, action):
    value, dialog = decided, decided["dialog"]
    entered, release = threading.Event(), threading.Event()
    prepare = original_version.prepare_claim_draft_read

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(20)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(original_version, "prepare_claim_draft_read", held)
    before = rows(value["b"].journal.path, "SELECT * FROM paper_claim_sets")
    try:
        dialog.originals.button.click()
        wait(app, entered.is_set, timeout=20)
        future = dialog.originals.future
        if action == "edit":
            text = "A later private draft must retain its own text and original scope."
            dialog.fields.assertion.setPlainText(text)
            dialog.autosave.stop()
        else:
            value["host"].close()
            assert not value["host"].disposed
        release.set()
        assert future.result(timeout=20) is None
        wait(app, lambda: not dialog.jobs, timeout=20)
        assert dialog.originals.viewer is None
        if action == "edit":
            assert dialog.fields.assertion.toPlainText() == text
            dialog.save.click()
            wait(app, lambda: not dialog.busy and not dialog.dirty, timeout=20)
            assert (
                json.loads(
                    rows(value["b"].journal.path, "SELECT body FROM research_review_drafts")[0][
                        "body"
                    ]
                )["claims"][0]["text"]
                == text
            )
        else:
            wait(app, lambda: value["host"].disposed and dialog.disposed, timeout=20)
        assert rows(value["b"].journal.path, "SELECT * FROM paper_claim_sets") == before
        assert not value["b"].journal.pending(1000)
    finally:
        release.set()


def test_parent_close_drains_readonly_fallback_render(decided, app, monkeypatch):
    monkeypatch.setattr(original_version, "HAVE_QTPDF", False)
    entered, release = threading.Event(), threading.Event()
    render = original_version.render_page

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(20)
        return render(*args, **kwargs)

    monkeypatch.setattr(original_version, "render_page", held)
    value, dialog = decided, decided["dialog"]
    before = rows(value["b"].journal.path, "SELECT * FROM paper_claim_sets")
    try:
        dialog.originals.button.click()
        wait(app, lambda: entered.is_set() and dialog.originals.viewer is not None, timeout=20)
        viewer = dialog.originals.viewer
        assert viewer.busy
        value["host"].close()
        assert not value["host"].disposed and not dialog.disposed
        release.set()
        wait(
            app, lambda: value["host"].disposed and dialog.disposed and viewer.disposed, timeout=20
        )
        assert rows(value["b"].journal.path, "SELECT * FROM paper_claim_sets") == before
        assert not value["b"].journal.pending(1000)
    finally:
        release.set()
