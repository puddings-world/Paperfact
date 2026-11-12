"""Actual recovered and remote highlight entries, not serialized UI imitations."""

import copy
import json
import threading
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from test_archived_draft_resume_ui import answer
from test_highlight_apply_journeys import recovered as recovered
from test_highlight_draft_ui import verify
from test_highlight_draft_verification import ready as ready
from test_highlight_draft_verification import scene as scene
from test_highlight_draft_verification import source_pair as source_pair
from test_highlight_draft_verification import workspace as workspace
from test_research_generation import rows
from test_research_review import remote_graph as remote_graph
from test_review_dialog import app as app
from test_review_dialog import wait
from test_sync_files import drain

from paper_daily import sync_content, sync_source_files
from paper_daily.desktop import original_version
from paper_daily.desktop.highlight_draft_dialog import HighlightDraftDialog
from paper_daily.desktop.review_dialog import ReviewDialog
from paper_daily.document_reader import DocumentReader
from paper_daily.research_review import ResearchReview
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_service import ReferenceService

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def close_host(app, host):
    host.close()
    wait(app, lambda: host.disposed, timeout=25)


def entry(app, path, origin, identity, language):
    host = ReviewDialog(path, language=language)
    host.show()
    wait(app, lambda: not host.jobs and host.preview is not None, timeout=25)
    index = next(
        i
        for i in range(host.list.count())
        if tuple(host.list.item(i).data(Qt.ItemDataRole.UserRole)) == (origin, identity)
    )
    host.list.setCurrentRow(index)
    wait(app, lambda: not host.jobs and host.selection_key == (origin, identity), timeout=25)
    assert host.resume_button.isVisible() and host.resume_button.isEnabled()
    assert "body_json" not in host.draft.toPlainText()
    for _ in range(12):
        host.resume_button.click()
    dialog = host.claim_editor
    wait(app, lambda: not dialog.busy, timeout=25)
    assert isinstance(dialog, HighlightDraftDialog)
    assert host.findChildren(HighlightDraftDialog) == [dialog]
    if dialog.preview is None:
        assert dialog.targets.count() == 2, dialog.status.text()
        dialog.targets.setCurrentIndex(1)
        dialog.choose.click()
        wait(app, lambda: dialog.preview is not None and not dialog.busy, timeout=25)
    return host, dialog


def save(app, dialog, text):
    dialog.fields.reason.setPlainText(text)
    for _ in range(8):
        dialog.save.click()
    wait(app, lambda: not dialog.busy and not dialog.dirty, timeout=25)


def open_original(app, dialog, expected):
    for _ in range(8):
        dialog.originals.button.click()
    wait(app, lambda: dialog.originals.viewer is not None, timeout=25)
    viewer = dialog.originals.viewer
    assert viewer.snapshot.data == expected
    assert viewer.snapshot.highlight_read_proof is not None
    assert viewer.snapshot.claim_read_proof is None
    viewer.close()
    wait(app, lambda: dialog.originals.viewer is None, timeout=25)


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_recovered_native_entry_preserves_two_variants_a_b_and_later_words(
    recovered, app, language
):
    value = recovered
    assert not value["old"].exists()
    identity = value["preview"].data["id"]
    host, dialog = entry(app, value["path"], "archived_draft", identity, language)
    reason = "Recovered human explanation kept through native confirmation and restart."
    try:
        assert dialog.fields.reason.toPlainText() == json.loads(value["body"])["items"][0]["reason"]
        save(app, dialog, reason)
        open_original(app, dialog, value["original_bytes"])
        assert not dialog.apply.isEnabled()
        verify(app, dialog)
        before = rows(value["path"], "SELECT * FROM paper_highlight_analysis")
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
        dialog.apply.click()
        assert rows(value["path"], "SELECT * FROM paper_highlight_analysis") == before
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        dialog.apply.click()
        wait(app, lambda: not dialog.busy, timeout=25)
        assert dialog.applied, dialog.status.text()
        assert (
            json.loads(
                rows(value["path"], "SELECT body_json FROM paper_highlight_analysis")[0][
                    "body_json"
                ]
            )["items"][0]["reason"]
            == reason
        )
        assert (
            DocumentReader.from_workspace(value["path"])
            .resolve(dialog.preview.data["target"]["id"])
            .sha256
            == value["current"].sha256
        )
        assert value["current"].path.read_bytes() == value["current_bytes"]
        assert rows(value["path"], "SELECT count(*) AS n FROM research_review_receipts") == [
            dict(n=1)
        ]
        save(app, dialog, reason + " Later private words.")
    finally:
        close_host(app, host)
    host, reopened = entry(app, value["path"], "archived_draft", identity, language)
    try:
        assert reopened.fields.reason.toPlainText() == reason + " Later private words."
        assert not reopened.apply.isEnabled()
        old = [
            view.data["retained"]["body"]
            for item in value["review"].page(limit=100)["items"]
            if item["origin"] == "archived_draft"
            for view in [value["review"].preview(item["origin"], item["id"])]
        ]
        assert value["variants"] <= set(old)
        assert not value["old"].exists()
    finally:
        close_host(app, host)


@pytest.fixture
def remote_highlights(scene, remote_graph, tmp_path):
    a, b, original_service, ta, tb, _list = remote_graph
    service = ReferenceService(
        original_service.path, blob_root=tmp_path / "highlight-authority-blobs"
    )
    with b.journal.transaction() as conn:
        portable, local = conn.execute(
            "SELECT sync_id,local_id FROM research_paper_identity"
        ).fetchone()
        parent = b._optimistic_graph(conn)[0][("paper", portable)]["incarnation"]
    retained = scene["original"].data["retained"]["analysis"]
    scope = dict(kind="paper", id=portable)
    identity = sync_content.content_id(scope, "highlight_analysis", "main")
    baseline = dict(
        scope=scope,
        feature="highlight_analysis",
        key="main",
        source_document_hash=retained["document_hash"],
        data={
            key: json.loads(value) if key == "body_json" else value
            for key, value in retained.items()
            if key != "paper_id"
        },
    )

    def put(client, reason):
        payload = copy.deepcopy(baseline)
        payload["data"]["body_json"]["items"][0]["reason"] = reason
        client.save(client.new_graph_operation("research_content", identity, payload))

    put(a, "Initial")
    a.sync_once(service, ta, limit=1000)
    b.sync_once(service, tb, limit=1000)
    put(a, "Desktop")
    put(b, "Laptop")
    a.sync_once(service, ta, limit=1000)
    b.sync_once(service, tb, limit=1000)
    a.sync_once(service, ta, limit=1000)
    store, versions = BlobStore(tmp_path / "highlight-blobs"), tmp_path / "highlight-versions"
    sync_source_files.publish(
        b,
        portable,
        scene["document"].path,
        document_hash=retained["document_hash"],
        parent_incarnation=parent,
        store=store,
        version_root=versions,
        request_id=str(uuid4()),
    )
    review = ResearchReview(b.journal.path)
    try:
        source = next(
            view
            for item in review.page(limit=100)["items"]
            if item["origin"] == "remote"
            and (view := review.preview("remote", item["id"])).data["source_hash"]
            == retained["document_hash"]
        )
        yield dict(
            path=b.journal.path,
            review=review,
            original=source,
            a=a,
            b=b,
            service=service,
            ta=ta,
            tb=tb,
            local=local,
            store=store,
            versions=versions,
            original_bytes=scene["document"].path.read_bytes(),
        )
    finally:
        review.close()


def sync_remote(value):
    files = FileTransfers(
        value["b"],
        value["store"],
        value["service"],
        origin="https://fixture.invalid",
        token=value["tb"],
        version_root=value["versions"],
    )
    try:

        def prepare(op):
            if op["entity_type"] == "research_file":
                drain(lambda: files.upload(op), "uploaded")
            return True

        value["b"].sync_once(value["service"], value["tb"], limit=1000, prepare_push=prepare)
        value["a"].sync_once(value["service"], value["ta"], limit=1000)
        value["b"].sync_once(value["service"], value["tb"], limit=1000)
    finally:
        files.close()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_remote_native_entry_applies_group_syncs_and_keeps_decided_private_editable(
    remote_highlights, app, language
):
    value = remote_highlights
    identity = value["original"].data["id"]
    host, dialog = entry(app, value["path"], "remote", identity, language)
    reason = "Native appraisal of the competing remote highlight interpretation."
    try:
        save(app, dialog, reason)
        open_original(app, dialog, value["original_bytes"])
        verify(app, dialog)
        before = rows(value["path"], "SELECT * FROM paper_highlight_analysis")
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
        dialog.apply.click()
        assert rows(value["path"], "SELECT * FROM paper_highlight_analysis") == before
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        dialog.apply.click()
        wait(app, lambda: not dialog.busy, timeout=25)
        assert dialog.applied, dialog.status.text()
        assert rows(value["path"], "SELECT count(*) AS n FROM research_review_receipts") == [
            dict(n=1)
        ]
        assert len(rows(value["path"], "SELECT * FROM pdf_ai_highlights")) == 2
    finally:
        close_host(app, host)
    sync_remote(value)
    assert rows(value["a"].journal.path, "SELECT body_json FROM paper_highlight_analysis") == rows(
        value["path"], "SELECT body_json FROM paper_highlight_analysis"
    )
    before = rows(value["path"], "SELECT * FROM paper_highlight_analysis")
    host, dialog = entry(app, value["path"], "remote", identity, language)
    try:
        assert dialog.fields.reason.toPlainText() == reason
        assert not dialog.verify.isEnabled() and not dialog.apply.isEnabled()
        assert not dialog.choose.isEnabled() and dialog.review_hint.isVisible()
        assert dialog.verify.toolTip()
        save(app, dialog, reason + " Additional private interpretation.")
        dialog.copy.click()
        assert "Additional private interpretation." in QApplication.clipboard().text()
        assert rows(value["path"], "SELECT * FROM paper_highlight_analysis") == before
        assert not value["b"].journal.pending(1000)
    finally:
        close_host(app, host)


def test_recovered_held_original_close_drains_and_keeps_words_without_publishing(
    recovered, app, monkeypatch
):
    value = recovered
    host, dialog = entry(app, value["path"], "archived_draft", value["preview"].data["id"], "en")
    reason = "Recovered words survive closing while the original reader is pending."
    save(app, dialog, reason)
    before = rows(value["path"], "SELECT * FROM paper_highlight_analysis")
    pending = value["client"].journal.pending(1000)
    entered, release = threading.Event(), threading.Event()
    prepare = original_version.prepare_highlight_draft_read

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(original_version, "prepare_highlight_draft_read", held)
    try:
        dialog.originals.button.click()
        wait(app, entered.is_set, timeout=15)
        host.close()
        assert not host.disposed and not dialog.disposed
        release.set()
        wait(app, lambda: host.disposed and dialog.disposed, timeout=25)
        assert dialog.originals.viewer is None
        assert rows(value["path"], "SELECT * FROM paper_highlight_analysis") == before
        assert value["client"].journal.pending(1000) == pending
        saved = rows(
            value["path"], "SELECT body FROM research_review_drafts WHERE origin='highlight_resume'"
        )
        assert any(json.loads(row["body"])["items"][0]["reason"] == reason for row in saved)
    finally:
        release.set()
        close_host(app, host)


def test_remote_held_verification_refuses_another_decision_and_preserves_private_words(
    remote_highlights, app, monkeypatch
):
    value = remote_highlights
    identity = value["original"].data["id"]
    host, dialog = entry(app, value["path"], "remote", identity, "en")
    reason = "My pending private appraisal must survive another accepted interpretation."
    save(app, dialog, reason)
    private_id = dialog.persisted["draft_id"]
    entered, release = threading.Event(), threading.Event()
    original = ResearchReview.verify_highlight_draft

    def held(self, *args, **kwargs):
        if self is dialog.service:
            entered.set()
            assert release.wait(15)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ResearchReview, "verify_highlight_draft", held)
    other = ResearchReview(value["path"])
    try:
        dialog.verify.click()
        wait(app, entered.is_set, timeout=15)
        preview, body = other.select_highlight_draft(
            other.preview("remote", identity), value["local"]
        )
        draft = json.loads(body)
        draft["items"][0]["reason"] = "A different reviewer accepted this interpretation."
        body = json.dumps(draft, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        checked = other.verify_highlight_draft(preview, body)
        other.apply_highlight_draft(checked, body, request_id=str(uuid4()), confirm_target=True)
        formal = rows(value["path"], "SELECT * FROM paper_highlight_analysis")
        marks = rows(value["path"], "SELECT * FROM pdf_ai_highlights ORDER BY id")
        pending = value["b"].journal.pending(1000)
        release.set()
        wait(app, lambda: not dialog.busy, timeout=25)
        assert not dialog.apply.isEnabled() and not dialog.verified
        assert dialog.fields.reason.toPlainText() == reason
        assert rows(value["path"], "SELECT * FROM paper_highlight_analysis") == formal
        assert rows(value["path"], "SELECT * FROM pdf_ai_highlights ORDER BY id") == marks
        assert value["b"].journal.pending(1000) == pending
        saved = rows(value["path"], "SELECT draft_id,body FROM research_review_drafts")
        private = next(row for row in saved if row["draft_id"] == private_id)
        assert json.loads(private["body"])["items"][0]["reason"] == reason
        assert rows(value["path"], "SELECT count(*) AS n FROM research_review_receipts") == [
            dict(n=1)
        ]
    finally:
        release.set()
        other.close()
        close_host(app, host)
