"""Explicit tombstone restoration and non-disruptive external report freshness."""

import copy
import threading
from contextlib import closing

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox
from test_claim_evidence_ui import claims as _claims
from test_claim_evidence_ui import generate, saved, wait
from test_claim_evidence_ui import ready as _ready
from test_claim_evidence_ui import view as _view
from test_claim_evidence_ui import workspace as _workspace

from paper_daily import annotation_reader, claim_jobs, llm, store, sync_capture
from paper_daily import research_generation as generation
from paper_daily.desktop.claim_evidence import TEXT
from paper_daily.desktop.workspace_changes import WorkspaceChanges

claims, ready, view, workspace = _claims, _ready, _view, _workspace


def delete_set(view):
    with closing(generation._connect(view.ready[0])) as conn:
        observed = sync_capture.observe_target(conn, "paper", "paper", "claims")
        with sync_capture.expecting(conn, [observed]):
            conn.execute("DELETE FROM paper_claim_sets WHERE paper_id='paper'")
            conn.commit()
    return observed


def update_elsewhere(view, text="Externally revised central assertion"):
    view.claims[1]["claims"][0]["text"] = text
    job = claim_jobs.ClaimJob.capture(
        view.ready[0],
        "paper",
        legacy_root=view.ready[2].path.parent,
        document=view.ready[2],
        owner=view.d.owner,
    )
    assert job.run().status == "accepted"


def test_confirmed_restore_forwards_intent_once_and_creates_new_live_version(view, monkeypatch):
    generate(view)
    before = delete_set(view)
    assert view.d.refresh()
    wait(view.app, lambda: not view.d.busy)
    intents, prompts = [], []
    original = view.d.job_factory

    def capture(*args, **kwargs):
        intents.append(kwargs["restore_deleted"])
        return original(*args, **kwargs)

    def confirm(parent, title, text, buttons, default):
        prompts.append((text, default))
        return QMessageBox.StandardButton.Yes

    view.d.job_factory = capture
    monkeypatch.setattr(QMessageBox, "question", confirm)
    assert view.d.generate() and not view.d.generate()
    wait(view.app, lambda: not view.d.busy)
    assert intents == [True] and len(view.claims[2]) == 2 and len(saved(view)) == 1
    assert prompts == [(TEXT["en"]["confirm_restore"], QMessageBox.StandardButton.Cancel)]
    assert view.d.saved["report"] and view.d.generate_button.text() == TEXT["en"]["regenerate"]
    if view.ready[1] is not None:
        with closing(generation._connect(view.ready[0])) as conn:
            after = sync_capture.observe_target(conn, "paper", "paper", "claims")
        assert after["incarnation"] != before["incarnation"]
    assert view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent notes"


def test_restore_login_is_explicit_and_failure_retry_preserves_tombstone(view, monkeypatch):
    from paper_daily.desktop import ai_access

    generate(view)
    delete_set(view)
    view.d.refresh()
    wait(view.app, lambda: not view.d.busy)
    notices = []
    monkeypatch.setattr(llm, "available", lambda **kw: False)
    monkeypatch.setattr(ai_access, "login", lambda *args: notices.append(args[1]))
    assert not view.d.generate() and notices == ["claims"] and saved(view) == []
    assert len(view.claims[2]) == 1
    monkeypatch.setattr(llm, "available", lambda **kw: True)
    output = copy.deepcopy(view.claims[1]["claims"])
    view.claims[1]["claims"] = []
    assert view.d.generate()
    wait(view.app, lambda: not view.d.busy)
    assert saved(view) == [] and "report" not in view.d.saved
    assert view.d.status.text() == TEXT["en"]["failed"]
    view.claims[1]["claims"] = output
    assert view.d.generate()
    wait(view.app, lambda: not view.d.busy)
    assert len(saved(view)) == 1 and view.d.saved["report"]


def test_actual_revision_signal_refreshes_saved_cards_without_account_access(view, monkeypatch):
    generate(view)
    monkeypatch.setattr(store, "DB_PATH", view.ready[0])
    changes = WorkspaceChanges(view.d)
    changes.timer.stop()
    changes.changed.connect(view.d.request_refresh)
    update_elsewhere(view)
    monkeypatch.setattr(
        llm, "capture_connections", lambda: (_ for _ in ()).throw(AssertionError("AI"))
    )
    changes.poll()
    wait(view.app, lambda: not view.d.busy)
    # Unlisted papers may not increment the list-visible counter; bounded fallback covers them.
    if view.d.saved["report"]["claims"][0]["text"] != "Externally revised central assertion":
        view.d.freshness.timeout.emit()
        wait(view.app, lambda: not view.d.busy)
    assert view.d.saved["report"]["claims"][0]["text"] == "Externally revised central assertion"
    assert view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent notes"
    assert len(view.claims[2]) == 2


def test_unchanged_background_read_preserves_expansion_widgets_focus_and_scroll(view):
    proposal = copy.deepcopy(view.claims[1]["claims"][0])
    view.claims[1]["claims"] = [
        {**copy.deepcopy(proposal), "text": f"Central assertion {i}"} for i in range(7)
    ]
    generate(view)
    view.d.show_all()
    view.app.processEvents()
    buttons = list(view.d.source_buttons)
    buttons[2].setFocus()
    bar = view.d.scroll.verticalScrollBar()
    bar.setValue(min(70, bar.maximum()))
    scroll = bar.value()
    view.d.request_refresh()
    wait(view.app, lambda: not view.d.busy)
    assert view.d._all and view.d.source_buttons == buttons
    assert buttons[2].hasFocus() and bar.value() == scroll
    assert len(view.claims[2]) == 1


class ChangeSignal(QObject):
    changed = Signal()


def test_external_deletion_blocks_stale_source_and_coalesces_busy_refreshes(view, monkeypatch):
    generate(view)
    entered, release = threading.Event(), threading.Event()
    calls = []
    original = annotation_reader.saved

    def slow(*args):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(annotation_reader, "saved", slow)
    changes = ChangeSignal(view.d)
    changes.changed.connect(view.d.request_refresh)
    view.d.request_refresh()
    wait(view.app, entered.is_set)
    delete_set(view)
    passage = view.d.saved["report"]["claims"][0]["passages"][0]
    for _ in range(20):
        changes.changed.emit()
    assert view.d._refresh_pending and not view.d.open_source(passage)
    assert not view.d.generate_button.isEnabled() and len(calls) == 1
    release.set()
    wait(view.app, lambda: not view.d.busy and not view.d._refresh_pending)
    assert len(calls) == 2 and "report" not in view.d.saved
    assert not view.d.source_buttons and not view.jumps
    assert len(view.claims[2]) == 1


def test_close_during_freshness_waits_and_does_not_reopen_or_touch_drafts(view, monkeypatch):
    generate(view)
    entered, release = threading.Event(), threading.Event()
    original = annotation_reader.saved

    def slow(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(annotation_reader, "saved", slow)
    view.d.request_refresh()
    wait(view.app, entered.is_set)
    assert not view.d.close() and view.d.busy
    release.set()
    wait(view.app, lambda: view.d.disposed)
    assert not view.d.isVisible() and not view.d.freshness.isActive()
    assert view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent notes"


def test_research_changed_during_confirmation_requires_rechecking_before_account_lookup(
    view, monkeypatch
):
    generate(view)
    delete_set(view)
    view.d.refresh()
    wait(view.app, lambda: not view.d.busy)

    def confirm(*args):
        update_elsewhere_restore = claim_jobs.ClaimJob.capture(
            view.ready[0],
            "paper",
            legacy_root=view.ready[2].path.parent,
            document=view.ready[2],
            owner=view.d.owner,
            restore_deleted=True,
        )
        assert update_elsewhere_restore.run().status == "accepted"
        view.d.request_refresh()
        wait(view.app, lambda: not view.d.busy)
        monkeypatch.setattr(
            llm, "capture_connections", lambda: pytest.fail("Stale confirmation read account")
        )
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    assert not view.d.generate() and view.d.saved["report"]
    assert len(view.claims[2]) == 2 and len(saved(view)) == 1


@pytest.mark.parametrize("changed", ["cancel", "source"])
def test_restore_cancel_or_replaced_original_retains_candidate_without_reviving(
    view, monkeypatch, changed
):
    from test_research_generation import pdf

    from paper_daily.research_review import ResearchReview

    generate(view)
    delete_set(view)
    view.d.refresh()
    wait(view.app, lambda: not view.d.busy)
    entered, release = threading.Event(), threading.Event()
    original = llm.complete_result

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", blocked)
    assert view.d.generate()
    wait(view.app, entered.is_set)
    if changed == "cancel":
        view.d.cancel()
    else:
        pdf(view.ready[2].path, "An unrelated replacement original")
    release.set()
    wait(view.app, lambda: not view.d.busy)
    assert saved(view) == [] and "report" not in view.d.saved
    retained = ResearchReview(view.ready[0]).page()["items"]
    assert retained and not view.jumps and len(view.claims[2]) == 2
    assert view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent notes"


def test_external_deletion_during_exact_source_check_blocks_late_navigation(view, monkeypatch):
    from paper_daily.desktop import claim_evidence

    generate(view)
    original = claim_evidence.verify_source
    changes = ChangeSignal(view.d)
    changes.changed.connect(view.d.request_refresh)

    def deleted_after_hash(*args):
        result = original(*args)
        delete_set(view)
        changes.changed.emit()
        return result

    monkeypatch.setattr(claim_evidence, "verify_source", deleted_after_hash)
    passage = view.d.saved["report"]["claims"][0]["passages"][0]
    assert view.d.open_source(passage)
    wait(view.app, lambda: not view.d.busy and not view.d._refresh_pending)
    assert not view.jumps and not view.d.disposed and "report" not in view.d.saved
    assert view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent notes"
