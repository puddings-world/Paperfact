"""Recovered notes keep exact selected passages and sync through native peers."""

import hashlib
import json
from contextlib import closing
from uuid import uuid4

import pymupdf
import pytest
from test_sync_authority_restore_native import join_and_download, publish
from test_sync_device_recovery import dump
from test_sync_files import LOCAL, PAPER
from test_sync_recovery_target import attached
from test_sync_recovery_target import codec as codec
from test_sync_recovery_target import pair as pair
from test_workspace_dialog import app as app
from test_workspace_dialog import wait

from paper_daily import note_positions
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_note_copy as copy
from paper_daily import sync_recovery_target as target
from paper_daily.desktop.workspace_dialog import WorkspaceDialog
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_blobs import BlobManifest
from paper_daily.sync_source_files import publish as publish_source


@pytest.fixture
def positioned(pair, tmp_path, tmp_path_factory):
    old, files = pair[1], pair[3]
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 60), "Exact original research evidence")
        data = pdf.tobytes()
    sha = hashlib.sha256(data).hexdigest()
    original = tmp_path / "original.pdf"
    original.write_bytes(data)
    with pymupdf.open(original) as pdf:
        anchor = note_positions.select(
            pdf, dict(p0=0, o0=0, p1=0, o1=2, document_hash=sha), sha
        )
    with old.journal.transaction() as conn:
        parent = old._optimistic_graph(conn)[0][("paper", PAPER)]["incarnation"]
    publish_source(
        old, PAPER, original, document_hash=sha, parent_incarnation=parent,
        store=files.store, version_root=files.root, request_id="retained-original",
    )
    payload = dict(paper_id=PAPER, body="Private interpretation, not a quotation", kind="note",
                   created_at="2026-11-14T00:00:00+00:00", page=1, anchor=anchor)
    identity = str(uuid4())
    old.save(old.new_graph_operation("note", identity, payload))
    service = publish(pair, tmp_path)
    destination = tmp_path_factory.mktemp("positioned-recovery-target") / "workspace"
    enroll = service.enroll
    tokens = {}

    def capture(workspace, device):
        tokens[device] = enroll(workspace, device)
        return tokens[device]

    service.enroll = capture
    path = join_and_download(service, old.journal.path, destination, lambda _: [LOCAL],
                             missing_primary=1)
    service.enroll = enroll
    operation = old.new_graph_operation("note", identity, {**payload, "body": "Unsent reasoning"})
    old.save(operation)
    source = candidates.prepare(old.journal.path, tmp_path / "authority-snapshot", "workspace")
    change = next(row["change_id"] for row in source.page()["items"]
                  if row["operation_id"] == operation["operation_id"])
    return old, source, change, path, operation, service, sha, data, tokens["new-travel-device"]


def prepare(positioned, request=None):
    _, source, change, path, *_ = positioned
    return copy.prepare(target.observe(source, path), change, request or str(uuid4()))


def notes(path):
    with closing(_readonly_connection(path)) as conn:
        return [(body, page, json.loads(anchor)) for body, page, anchor in
                conn.execute("SELECT body,page,anchor FROM notes ORDER BY id")]


def source_file(path, sha, size):
    from paper_daily.sync_source_files import _inspection_paths

    with closing(_readonly_connection(path)) as conn:
        return _inspection_paths(conn)[0].verified_path(BlobManifest(sha, size))


def test_positioned_copy_preserves_passage_and_reaches_independent_native_peer(
    positioned, tmp_path_factory,
):
    old, source, change, path, operation, service, sha, _data, token = positioned
    before = dump(old.journal.path)
    request = str(uuid4())
    saved = prepare(positioned, request).apply()
    assert attached(path).journal.pending()[0]["payload"] == operation["payload"]
    assert notes(path)[-1] == ("Unsent reasoning", 1, operation["payload"]["anchor"])
    assert not copy.prepare(target.observe(source, path), change, request).apply()["applied"]
    client = attached(path)
    result = client.sync_once(service, token)
    assert result["pending"] == result["conflicts"] == 0
    destination = tmp_path_factory.mktemp("positioned-independent-peer") / "workspace"
    from test_workspace_sync import Native

    from paper_daily import sync_bootstrap
    from paper_daily.workspace_service import Ticket
    from paper_daily.workspace_sync import SyncSession

    peer_token = service.enroll("fresh-research", "independent-note-peer")
    joining = SyncSession(path, transport_factory=lambda url: Native(url, service, []))
    joining.connect("https://recovery.fixture.invalid", "fresh-research",
                    "independent-note-peer", peer_token, Ticket())
    try:
        assert sync_bootstrap.join(joining, destination, Ticket())["state"] == "metadata_ready"
    finally:
        joining.disconnect()
    peer = destination / "papers.db"
    travel = SyncSession(peer, transport_factory=lambda url: Native(url, service, []))
    travel.connect("https://recovery.fixture.invalid", "fresh-research",
                   "independent-note-peer", peer_token, Ticket())
    try:
        assert travel.prepare_offline([LOCAL], Ticket())["attachments"]["failed"] == 0
    finally:
        travel.disconnect()
    assert notes(peer) == notes(path)
    assert saved["entity_id"] != operation["entity_id"]
    assert dump(old.journal.path) == before
    assert source_file(peer, sha, len(_data)).read_bytes() == _data
    with closing(_readonly_connection(peer)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_document_desired").fetchone()[0] == 0


def test_changed_original_after_prepare_refuses_then_exact_retry_repairs(positioned):
    _, _, _, path, _, _, sha, data, _ = positioned
    plan = prepare(positioned)
    original = source_file(path, sha, len(data))
    before = dump(path)
    original.write_bytes(data + b"\n% changed after review\n")
    with pytest.raises((ValueError, OSError)):
        plan.apply()
    assert dump(path) == before and attached(path).journal.pending() == []
    original.unlink()
    with pytest.raises((ValueError, OSError)):
        plan.apply()
    assert dump(path) == before and attached(path).journal.pending() == []
    original.write_bytes(data)
    assert plan.apply()["applied"]
    original.unlink()
    assert not plan.apply()["applied"]  # Durable receipt does not require the PDF again.
    assert len(notes(path)) == 2


def test_forged_passage_is_not_accepted_as_source_evidence(positioned):
    old, source, _, path, operation, *_ = positioned
    payload = operation["payload"]
    anchor = {**payload["anchor"], "selection": {
        **payload["anchor"]["selection"], "quote": "Invented claim absent from the original"}}
    changed = old.new_graph_operation("note", str(uuid4()), {**payload, "anchor": anchor})
    old.save(changed)
    review = candidates.prepare(old.journal.path, source.snapshot, source.workspace)
    change = next(row["change_id"] for row in review.page()["items"]
                  if row["operation_id"] == changed["operation_id"])
    before = dump(path)
    with pytest.raises(ValueError, match="selected passage changed"):
        copy.prepare(target.observe(review, path), change, str(uuid4()))
    assert dump(path) == before and len(notes(path)) == 1


def test_native_review_enables_verified_positioned_copy_and_saves_once(
    positioned, app, monkeypatch,
):
    from PySide6.QtWidgets import QMessageBox

    old, source, _, path, operation, *_ = positioned
    owner = WorkspaceDialog(old.journal.path, language="en")
    owner.show()
    try:
        wait(app, lambda: owner._ready and not owner.busy)
        owner.task_tabs.setCurrentIndex(2)
        owner.device_review.disclosure.setChecked(True)
        ui = owner.device_review.changes
        assert owner.device_review.inspect(source.snapshot)
        wait(app, lambda: not owner.busy)
        assert ui.load(path.parent)
        wait(app, lambda: not owner.busy)
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        assert ui.copy_button.isEnabled(), owner.status.text()
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        assert notes(path)[-1] == ("Unsent reasoning", 1, operation["payload"]["anchor"])
        assert len(attached(path).journal.pending()) == 1 and len(notes(path)) == 2
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()


def test_primary_original_can_authorize_copy_without_a_retained_manifest(positioned):
    from paper_daily.document_reader import register_document_paths
    from paper_daily.sync_files import file_id
    from paper_daily.sync_source_files import FEATURE, _inspection_paths

    _, _, _, path, _, _, sha, data, _ = positioned
    client = attached(path)
    original_id = file_id(PAPER, FEATURE, sha)
    client.save(client.new_graph_operation("research_file", original_id, {}, action="delete"))
    client.save(client.new_graph_operation("paper_document", PAPER, dict(
        paper_id=PAPER, sha256=sha, size=len(data), media_type="application/pdf")))
    with client.journal.transaction() as conn:
        blob_root = _inspection_paths(conn)[0].root
        register_document_paths(conn, workspace_id="fresh-research", blob_root=blob_root,
                                projection_root=path.parent / "reader-documents",
                                legacy_root=path.parent / "pdf")
    plan = prepare(positioned)
    assert plan.apply()["applied"]
    assert notes(path)[-1][0] == "Unsent reasoning"
    assert not (path.parent / "reader-documents").exists()


def test_source_changed_after_native_write_rolls_back_the_whole_copy(positioned, monkeypatch):
    from paper_daily.sync_capture import CaptureConnection
    from paper_daily.sync_research import research_writer

    _, _, _, path, _, _, sha, data, _ = positioned
    plan = prepare(positioned)
    original = source_file(path, sha, len(data))
    before = dump(path)
    activate = CaptureConnection._activate

    def corrupt_after_write(conn):
        activate(conn)

        def write(conn, operation):
            research_writer(conn, operation)
            original.write_bytes(data + b"\n% changed during write\n")

        conn._capture_client.writer = write

    monkeypatch.setattr(CaptureConnection, "_activate", corrupt_after_write)
    with pytest.raises(ValueError, match="original changed before recovery committed"):
        plan.apply()
    assert dump(path) == before and len(notes(path)) == 1
