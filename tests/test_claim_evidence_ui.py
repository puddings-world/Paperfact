"""Actual Qt claim cards use one observed producer without touching reader drafts."""

import copy
import threading
import time
from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QWidget
from test_claim_jobs import claims as claims_fixture
from test_claim_jobs import ready as ready_fixture
from test_claim_jobs import workspace as workspace_fixture
from test_research_generation import pdf, rows

from paper_daily import llm, manual_highlight_ops, sync_capture
from paper_daily import research_generation as generation
from paper_daily.desktop.claim_evidence import TEXT, ClaimEvidenceDialog
from paper_daily.research_review import ResearchReview

workspace = workspace_fixture
ready = ready_fixture
claims = claims_fixture


def wait(app, condition, timeout=15):
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert condition(), "Isolated claim UI worker did not finish"


@pytest.fixture
def view(claims, monkeypatch):
    ready = claims[0]
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(llm, "available", lambda **kw: True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    owner = manual_highlight_ops.capture_owner(ready[0], "paper")
    parent = QWidget()
    question, note = QLineEdit("Unsent question", parent), QPlainTextEdit("Unsent notes", parent)
    with closing(generation._connect(ready[0])) as conn, conn, sync_capture.suppress_capture(conn):
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) "
            "VALUES('paper','Legacy claim card','claim','2026-01-01T00:00:00+00:00')"
        )
    active = [ready[0], "paper", 1, ready[2]]
    jumps = []

    def focus(source):
        jumps.append((source, QThread.currentThread() == app.thread()))
        return True

    dialog = ClaimEvidenceDialog(
        ready[0],
        "paper",
        parent,
        legacy_root=ready[2].path.parent,
        owner=owner,
        current_path=lambda: active[0],
        current_view=lambda: tuple(active),
        document=ready[2],
        source_callback=focus,
        language="en",
    )
    dialog.show()
    wait(app, lambda: not dialog.busy and dialog.status.text() != TEXT["en"]["loading"])
    yield SimpleNamespace(
        app=app,
        d=dialog,
        ready=ready,
        claims=claims,
        active=active,
        parent=parent,
        question=question,
        note=note,
        jumps=jumps,
    )
    if dialog.busy:
        dialog.cancel()
        wait(app, lambda: not dialog.busy)
    dialog.close()
    parent.close()
    dialog.deleteLater()
    parent.deleteLater()
    app.processEvents()


def saved(view):
    return rows(view.ready[0], "SELECT * FROM paper_claim_sets")


def generate(view):
    assert view.d.generate()
    wait(view.app, lambda: not view.d.busy)
    assert view.d.saved is not None and "report" in view.d.saved, view.d.status.text()


def test_open_is_saved_first_and_generate_is_one_real_off_gui_producer(view, monkeypatch):
    assert not view.claims[2] and view.d.saved is None
    assert view.d.status.text() == TEXT["en"]["empty"]
    original = llm.complete_result
    threads = []
    capture = view.d.job_factory
    owners = []

    def factory(*args, **kwargs):
        owners.append(kwargs["owner"])
        return capture(*args, **kwargs)

    view.d.job_factory = factory

    def complete(*args, **kwargs):
        threads.append(QThread.currentThread() != view.app.thread())
        return original(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", complete)
    assert view.d.generate()
    assert not view.d.generate() and not view.d.refresh()
    wait(view.app, lambda: not view.d.busy)
    assert threads == [True] and len(view.claims[2]) == 1 and len(saved(view)) == 1
    assert owners == [view.d.owner]
    assert view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent notes"
    assert rows(view.ready[0], "SELECT body,kind FROM notes") == [
        {"body": "Legacy claim card", "kind": "claim"}
    ]
    text = "\n".join(label.text() for label in view.d.findChildren(QLabel))
    assert (
        "Proposed judgment: unresolved" in text and "semantic support has not been verified" in text
    )
    assert len(view.d.source_buttons) == 1 and view.d.source_buttons[0].isEnabled()


def test_cached_refresh_never_reads_accounts_or_models(view, monkeypatch):
    generate(view)
    before = saved(view)
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Cache read AI accounts"))
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Cache called AI"))
    assert view.d.refresh()
    wait(view.app, lambda: not view.d.busy)
    assert saved(view) == before and len(view.d.source_buttons) == 1


def test_missing_login_uses_existing_onboarding_without_automatic_call(view, monkeypatch):
    from paper_daily.desktop import ai_access

    notices = []
    monkeypatch.setattr(llm, "available", lambda **kw: False)
    monkeypatch.setattr(
        ai_access, "login", lambda parent, task, reason: notices.append((task, reason))
    )
    assert not view.d.generate() and notices == [("claims", TEXT["en"]["login"])]
    assert not view.claims[2] and saved(view) == [] and not view.d.busy
    monkeypatch.setattr(llm, "available", lambda **kw: True)
    generate(view)
    assert len(view.claims[2]) == 1


def test_regeneration_cancel_and_malformed_model_retry_preserve_existing_set(view, monkeypatch):
    from paper_daily.ai_types import Completion

    generate(view)
    before = saved(view)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    assert not view.d.generate() and len(view.claims[2]) == 1 and saved(view) == before
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    original = llm.complete_result
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: Completion("not JSON"))
    assert view.d.generate()
    wait(view.app, lambda: not view.d.busy)
    assert saved(view) == before and view.d.saved["report"]
    assert view.d.status.text() == TEXT["en"]["failed"]
    monkeypatch.setattr(llm, "complete_result", original)
    generate(view)
    assert len(view.claims[2]) == 2


def test_account_switch_during_model_retains_original_task_route(view, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = llm.complete_result

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", blocked)
    try:
        assert view.d.generate() and entered.wait(8)
        view.ready[3].update(account="different-account", model="different-model")
        release.set()
        wait(view.app, lambda: not view.d.busy)
        assert view.d.saved["generation"]["requested_model"] == "requested"
        assert view.ready[4] == [{"account": "original", "model": "original-model"}] * 2
    finally:
        release.set()


@pytest.mark.parametrize("change", ["paper", "workspace"])
def test_pending_context_switch_cancels_without_repaint_or_redirect(
    view, monkeypatch, tmp_path, change
):
    entered, release = threading.Event(), threading.Event()
    original = llm.complete_result

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", blocked)
    try:
        assert view.d.generate() and entered.wait(8)
        other = tmp_path / "other.sqlite"
        if change == "paper":
            view.active[1] = "other"
        else:
            view.active[0] = other
        wait(view.app, lambda: view.d._invalid)
        release.set()
        wait(view.app, lambda: not view.d.busy)
        assert view.d.saved is None and not other.exists() and saved(view) == []
        assert generation.list_recovery_requests(view.ready[0])
        assert view.d.status.text() == TEXT["en"]["changed"]
        assert view.question.text() == "Unsent question"
    finally:
        release.set()


def test_changed_source_after_model_retains_original_candidate_without_current_replacement(
    view, monkeypatch
):
    original = llm.complete_result

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        view.ready[2].path.unlink()
        pdf(view.ready[2].path, "A completely different original version")
        return result

    monkeypatch.setattr(llm, "complete_result", changed)
    assert view.d.generate()
    wait(view.app, lambda: not view.d.busy)
    assert saved(view) == [] and view.d.saved is None
    review = ResearchReview(view.ready[0])
    retained = [
        item for item in review.page()["items"] if item["origin"] in {"generation", "sidecar"}
    ]
    assert retained, (view.d.status.text(), view.d.last_error)
    assert view.d.status.text() == TEXT["en"]["retained"]
    row = review.preview(retained[0]["origin"], retained[0]["id"]).data["retained"]
    assert row["document_hash"] == view.ready[2].sha256


def test_active_close_waits_and_retains_completed_source_work(view, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = llm.complete_result

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", blocked)
    try:
        assert view.d.generate() and entered.wait(8)
        assert view.d.close() is False and not view.d.disposed
        release.set()
        wait(view.app, lambda: not view.d.busy and view.d.disposed)
        assert saved(view) == [] and generation.list_recovery_requests(view.ready[0])
        assert view.note.toPlainText() == "Unsent notes"
    finally:
        release.set()


def test_verified_source_focus_runs_on_gui_thread_and_only_once(view):
    generate(view)
    assert view.d.open_source(view.d.saved["report"]["claims"][0]["passages"][0])
    assert not view.d.open_source(view.d.saved["report"]["claims"][0]["passages"][0])
    wait(view.app, lambda: not view.d.busy)
    assert view.d.disposed and len(view.jumps) == 1 and view.jumps[0][1]
    assert view.jumps[0][0]["document_hash"] == view.ready[2].sha256
    assert view.question.text() == "Unsent question"


def test_old_source_cards_stay_readable_and_cannot_jump_to_other_document(view):
    generate(view)
    view.d.document = replace(view.ready[2], sha256="f" * 64)
    view.d._render()
    assert view.d.version.text() == TEXT["en"]["source_old"]
    assert not any(button.isEnabled() for button in view.d.source_buttons)
    passage = view.d.saved["report"]["claims"][0]["passages"][0]
    assert view.d.open_source(passage)
    wait(view.app, lambda: not view.d.busy)
    assert not view.jumps and view.d.status.text() == TEXT["en"]["source_failed"]


@pytest.mark.parametrize("quote", ["The", "A missing original quotation"])
def test_ambiguous_or_missing_quote_has_no_active_source_button(view, quote):
    view.claims[1]["claims"][0]["passages"][0]["quote"] = quote
    generate(view)
    state = view.d.saved["report"]["claims"][0]["passages"][0]["location"]["state"]
    assert state in {"ambiguous", "missing"} and view.d.source_buttons == []
    assert not view.jumps


def test_initial_cards_are_bounded_and_more_only_changes_reading_view(view):
    proposal = copy.deepcopy(view.claims[1]["claims"][0])
    view.claims[1]["claims"] = [
        {**copy.deepcopy(proposal), "text": f"Proposed assertion {i}"} for i in range(7)
    ]
    generate(view)
    assert len(view.d.source_buttons) == 5 and view.d.more_button.isVisible()
    before = saved(view)
    view.d.more_button.click()
    assert len(view.d.source_buttons) == 7 and not view.d.more_button.isVisible()
    assert saved(view) == before and len(view.claims[2]) == 1


def test_missing_loaded_owner_is_read_only_without_recapturing_write_authority(view, monkeypatch):
    generate(view)
    before = saved(view)
    view.d.owner = None
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Read-only view read AI"))
    assert view.d.refresh()
    wait(view.app, lambda: not view.d.busy)
    assert view.d.saved["report"] and saved(view) == before
    assert not view.d.generate_button.isEnabled() and not view.d.generate()
    assert not any(button.isEnabled() for button in view.d.source_buttons)


def test_known_deleted_set_requires_explicit_confirmation_without_spending_on_cancel(
    view, monkeypatch
):
    generate(view)
    with closing(generation._connect(view.ready[0])) as conn:
        observed = sync_capture.observe_target(conn, "paper", "paper", "claims")
        with sync_capture.expecting(conn, [observed]):
            conn.execute("DELETE FROM paper_claim_sets WHERE paper_id='paper'")
            conn.commit()
    assert view.d.refresh()
    wait(view.app, lambda: not view.d.busy)
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Deleted set spent AI"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    assert view.d.generate_button.isEnabled()
    assert view.d.generate_button.text() == TEXT["en"]["restore"]
    assert not view.d.generate()
    assert view.d.status.text() == TEXT["en"]["deleted"] and saved(view) == []
    assert len(view.claims[2]) == 1


def test_reader_switch_after_source_verification_discards_late_navigation(view, monkeypatch):
    from paper_daily.desktop import claim_evidence

    generate(view)
    original = claim_evidence.verify_source

    def switched(*args):
        result = original(*args)
        view.active[1] = "different-paper"
        return result

    monkeypatch.setattr(claim_evidence, "verify_source", switched)
    assert view.d.open_source(view.d.saved["report"]["claims"][0]["passages"][0])
    wait(view.app, lambda: not view.d.busy)
    assert not view.jumps and view.d.status.text() == TEXT["en"]["changed"]
    assert view.question.text() == "Unsent question"
