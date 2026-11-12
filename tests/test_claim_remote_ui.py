"""Actual native remote/sidecar entry, editing, confirmation and late-work controls."""

import json
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from test_archived_draft_resume_ui import answer
from test_claim_conflict_intent import remote as remote
from test_claim_draft_storage import rows
from test_claim_draft_ui import app as app
from test_claim_draft_ui import closed
from test_claim_jobs import job
from test_claim_review_continuity import claims as claims
from test_claim_review_continuity import ready as ready
from test_claim_review_continuity import receiver as receiver
from test_claim_review_continuity import scene as scene
from test_claim_review_continuity import source_pair as source_pair
from test_claim_review_continuity import workspace as workspace
from test_review_dialog import opened, wait

from paper_daily.archived_draft_resume import _sealed
from paper_daily.desktop.claim_draft_dialog import ClaimDraftDialog
from paper_daily.document_reader import DocumentReader
from paper_daily.research_review import ResearchReview

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def entry(app, path, origin, identity, language):
    host = opened(app, path, language=language)
    index = next(
        i
        for i in range(host.list.count())
        if tuple(host.list.item(i).data(Qt.ItemDataRole.UserRole)) == (origin, identity)
    )
    host.list.setCurrentRow(index)
    wait(
        app,
        lambda: (
            host.preview is not None
            and host.selection_key == (origin, identity)
            and host.claim_button.isEnabled()
        ),
        timeout=20,
    )
    for _ in range(10):
        host.claim_button.click()
    dialog = host.claim_editor
    wait(app, lambda: not dialog.busy, timeout=20)
    assert host.findChildren(ClaimDraftDialog) == [dialog]
    if dialog.preview is None:
        assert dialog.targets.count() == 2, dialog.status.text()
        dialog.targets.setCurrentIndex(1)
        dialog.choose.click()
        wait(app, lambda: not dialog.busy and dialog.preview is not None, timeout=20)
    return host, dialog


def close_host(app, host):
    host.close()
    wait(app, lambda: host.disposed, timeout=20)


def verify(app, dialog):
    for _ in range(10):
        dialog.verify.click()
    wait(app, lambda: not dialog.busy, timeout=25)
    assert dialog.apply.isEnabled(), dialog.status.text()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_native_remote_entry_edit_source_cancel_apply_sync_and_reopen(remote, app, language):
    value = remote
    path = value["b"].journal.path
    sequence = value["origin"].split(":", 1)[1]
    host, dialog = entry(app, path, "remote", sequence, language)
    text = "Native offline appraisal of the retained comparison."
    before = rows(path, "SELECT * FROM paper_claim_sets")
    try:
        assert "body_json" not in host.draft.toPlainText()
        dialog.fields.assertion.setPlainText(text)
        dialog.fields.reason.setPlainText("The original passage needs an independent appraisal.")
        verify(app, dialog)
        dialog.originals.button.click()
        wait(app, lambda: dialog.originals.viewer is not None, timeout=20)
        assert dialog.originals.viewer.snapshot.document_hash == value["value"]["source_hash"]
        assert (
            DocumentReader.from_workspace(path).resolve(value["local"]).sha256
            == value["value"]["current"].sha256
        )
        dialog.originals.viewer.close()
        wait(app, lambda: dialog.originals.viewer is None, timeout=20)
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
        dialog.apply.click()
        assert rows(path, "SELECT * FROM paper_claim_sets") == before
        assert not value["b"].journal.pending(1000)
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        dialog.apply.click()
        for _ in range(10):
            dialog.apply.click()
        wait(app, lambda: not dialog.busy, timeout=20)
        assert (
            json.loads(rows(path, "SELECT body_json FROM paper_claim_sets")[0]["body_json"])[
                "report"
            ]["claims"][0]["text"]
            == text
        )
        pending = value["b"].journal.pending(1000)
        assert (
            len(pending) == 1 and pending[0]["resolution_of"] == value["incoming"]["operation_id"]
        )
        assert rows(path, "SELECT count(*) AS n FROM research_review_receipts") == [dict(n=1)]
    finally:
        close_host(app, host)
    value["b"].sync_once(value["service"], value["tb"], limit=1000)
    value["a"].sync_once(value["service"], value["ta"], limit=1000)
    assert rows(path, "SELECT resolved_by FROM paperfact_sync_conflicts") == [
        dict(resolved_by=pending[0]["operation_id"])
    ]
    reopened = ClaimDraftDialog(path, "remote", sequence, language=language)
    reopened.show()
    try:
        wait(app, lambda: not reopened.busy, timeout=20)
        assert reopened.fields.assertion.toPlainText() == text, reopened.status.text()
        assert not reopened.apply.isEnabled()
        assert not reopened.verify.isEnabled()
        assert reopened.verify.toolTip() and reopened.review_hint.isVisible()
        assert not reopened.choose.isEnabled()
        if language == "zh-TW":
            folder = Path(__file__).resolve().parents[1] / "build"
            for width in (980, 620):
                reopened.resize(width, 780)
                app.processEvents()
                assert reopened.review_hint.isVisible() and reopened.fields.height() > 100
                for control in (reopened.copy, reopened.close_button, reopened.verify):
                    position = control.mapTo(reopened, QPoint(0, 0))
                    assert position.x() >= 0 and position.x() + control.width() <= reopened.width()
                    assert (
                        position.y() >= 0 and position.y() + control.height() <= reopened.height()
                    )
                assert reopened.grab().save(str(folder / f"claim-remote-zh-TW-{width}.png"))
        assert (
            "已套用" in reopened.status.text()
            if language == "zh-TW"
            else "already" in reopened.status.text()
        )
        newer = rows(path, "SELECT * FROM paper_claim_sets")
        retained = text + " Additional private interpretation."
        reopened.fields.assertion.setPlainText(retained)
        reopened.copy.click()
        assert retained in QApplication.clipboard().text()
        assert not reopened.verify.isEnabled() and reopened.review_hint.isVisible()
        reopened.save.click()
        wait(app, lambda: not reopened.busy and not reopened.dirty, timeout=20)
        assert (
            json.loads(rows(path, "SELECT body FROM research_review_drafts")[0]["body"])["claims"][
                0
            ]["text"]
            == retained
        )
        assert rows(path, "SELECT * FROM paper_claim_sets") == newer
        assert not value["b"].journal.pending(1000)
    finally:
        closed(app, reopened)


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_native_cancelled_result_entry_keeps_completed_work_and_edited_words(claims, app, language):
    assert job(claims).run().status == "accepted"
    current = job(claims)
    calls = len(claims[2])
    assert current.run(cancelled=lambda: len(claims[2]) > calls).status == "candidate"
    host = opened(app, claims[0][0], language=language)
    try:
        item = next(
            host.list.item(i)
            for i in range(host.list.count())
            if host.list.item(i).data(Qt.ItemDataRole.UserRole)[0] == "sidecar"
        )
        origin, identity = tuple(item.data(Qt.ItemDataRole.UserRole))
    finally:
        close_host(app, host)
    host, dialog = entry(app, claims[0][0], origin, identity, language)
    text = "Native manual continuation after cancelling completed analysis."
    try:
        dialog.fields.assertion.setPlainText(text)
        verify(app, dialog)
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        dialog.apply.click()
        wait(app, lambda: not dialog.busy, timeout=20)
        actual = json.loads(
            rows(claims[0][0], "SELECT body_json FROM paper_claim_sets")[0]["body_json"]
        )
        assert actual["report"]["claims"][0]["text"] == text
        assert actual["generation"]["backend"] == "manual" and len(claims[2]) == calls + 1
        assert not dialog.apply.isEnabled()
    finally:
        close_host(app, host)
    reopened = ClaimDraftDialog(claims[0][0], origin, identity, language=language)
    reopened.show()
    try:
        wait(app, lambda: not reopened.busy, timeout=20)
        assert reopened.fields.assertion.toPlainText() == text
        assert not reopened.verify.isEnabled()
    finally:
        closed(app, reopened)


def test_native_remote_result_changed_during_verification_keeps_private_fields(
    remote, app, monkeypatch
):
    value = remote
    path = value["b"].journal.path
    host, dialog = entry(app, path, "remote", value["origin"].split(":", 1)[1], "zh-TW")
    entered, release = threading.Event(), threading.Event()
    original = dialog.service.verify_claim_draft

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(20)
        return original(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "verify_claim_draft", held)
    text = "Private text survives a decision made on another computer."
    try:
        dialog.fields.assertion.setPlainText(text)
        dialog.verify.click()
        wait(app, entered.is_set, timeout=20)
        sequence = int(value["origin"].split(":", 1)[1])
        value["a"].resolve_conflict(sequence, choice="canonical", operation_id=str(uuid4()))
        value["a"].sync_once(value["service"], value["ta"], limit=1000)
        value["b"].sync_once(value["service"], value["tb"], limit=1000)
        newer = rows(path, "SELECT * FROM paper_claim_sets")
        release.set()
        wait(app, lambda: not dialog.busy, timeout=20)
        assert dialog.fields.assertion.toPlainText() == text
        assert not dialog.apply.isEnabled()
        assert dialog.words["failed"] in dialog.status.text()
        assert rows(path, "SELECT * FROM paper_claim_sets") == newer
        assert not value["b"].journal.pending(1000)
        assert (
            json.loads(rows(path, "SELECT body FROM research_review_drafts")[0]["body"])["claims"][
                0
            ]["text"]
            == text
        )
    finally:
        release.set()
        close_host(app, host)


@pytest.mark.parametrize("close_parent", [False, True])
def test_native_remote_cancel_or_parent_close_drains_held_work_without_apply(
    remote, app, monkeypatch, close_parent
):
    value = remote
    path = value["b"].journal.path
    host, dialog = entry(app, path, "remote", value["origin"].split(":", 1)[1], "en")
    before = rows(path, "SELECT * FROM paper_claim_sets")
    entered, release = threading.Event(), threading.Event()
    original = dialog.service.verify_claim_draft

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(20)
        return original(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "verify_claim_draft", held)
    text = "Retain this work when the native review is cancelled or closed."
    try:
        dialog.fields.assertion.setPlainText(text)
        dialog.verify.click()
        wait(app, entered.is_set, timeout=20)
        if close_parent:
            host.close()
            assert not host.disposed and not dialog.disposed
        else:
            dialog.cancel.click()
        release.set()
        wait(
            app,
            lambda: (host.disposed and dialog.disposed) if close_parent else not dialog.busy,
            timeout=20,
        )
        if not close_parent:
            assert not dialog.apply.isEnabled()
        assert rows(path, "SELECT * FROM paper_claim_sets") == before
        assert not value["b"].journal.pending(1000)
        assert (
            json.loads(rows(path, "SELECT body FROM research_review_drafts")[0]["body"])["claims"][
                0
            ]["text"]
            == text
        )
    finally:
        release.set()
        close_host(app, host)


def test_native_legacy_remote_draft_requires_review_then_keeps_text_when_upgraded(remote, app):
    value = remote
    path = value["b"].journal.path
    sequence = value["origin"].split(":", 1)[1]
    review = ResearchReview(path)
    text = "Legacy native draft words survive explicit reselection."
    try:
        preview, body = review.select_claim_draft(
            review.preview("remote", sequence), value["local"]
        )
        raw = json.loads(body)
        raw["claims"][0]["text"] = text
        data = preview.data
        data["expected"]["version"] = 1
        data["expected"].pop("conflict")
        review.save_claim_draft(
            _sealed(review, data), json.dumps(raw), str(uuid4()), draft_id=str(uuid4())
        )
    finally:
        review.close()
    host, dialog = entry(app, path, "remote", sequence, "zh-TW")
    try:
        assert dialog.fields.assertion.toPlainText() == text
        assert not dialog.verify.isEnabled()
        dialog.choose.click()
        wait(
            app,
            lambda: not dialog.busy and dialog.preview.data["expected"]["version"] == 2,
            timeout=20,
        )
        assert dialog.fields.assertion.toPlainText() == text
        verify(app, dialog)
        assert dialog.apply.isEnabled()
    finally:
        close_host(app, host)
