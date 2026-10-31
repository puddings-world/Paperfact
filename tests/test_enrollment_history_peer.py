"""Known-empty annotation graph state survives fresh enrollment and real peer sync."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from test_claim_jobs import (
    claims as claims_fixture,
)
from test_claim_jobs import (
    job,
)
from test_claim_jobs import (
    ready as ready_fixture,
)
from test_claim_jobs import (
    workspace as workspace_fixture,
)
from test_sync_files import drain

from paper_daily import (
    annotation_content,
    annotation_reader,
    claim_jobs,
    llm,
    store,
    sync_capture,
)
from paper_daily import (
    research_generation as generation,
)
from paper_daily.document_reader import DocumentReader
from paper_daily.sync_artifacts import paths
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_client import SyncClient
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare as prepare_sync
from paper_daily.sync_research import research_writer
from paper_daily.sync_service import ReferenceService
from paper_daily.sync_transfers import DocumentTransfers
from paper_daily.workspace_enrollment import EnrollmentService

claims = claims_fixture
ready = ready_fixture
workspace = workspace_fixture


def candidate(claims, tmp_path, *, deleted=False):
    assert job(claims).run().status == "accepted"
    if claims[0][1] is not None:
        return None
    source = claims[0][0]
    if deleted:
        with closing(generation._connect(source)) as conn, conn:
            conn.execute("DELETE FROM paper_claim_sets WHERE paper_id='paper'")
            conn.executemany(
                "INSERT OR IGNORE INTO paper_annotation_known VALUES(?,?)",
                [(feature, "paper") for feature in annotation_content.FEATURES],
            )
    key = str(uuid4())
    return EnrollmentService(source).prepare(
        tmp_path.parent / ("enrolled-" + key),
        backup_output=tmp_path.parent / (key + ".zip"),
        request_id=key,
        pdfs={"paper": claims[0][2].path},
    )


def peer(result, tmp_path):
    db = Path(result["database"])
    workspace = result["workspace_id"]
    device = result["device_id"]
    a = SyncClient(Journal(db, workspace_id=workspace, device_id=device), research_writer)
    other = tmp_path / "peer.sqlite"
    with closing(sqlite3.connect(other)) as conn:
        conn.executescript(store.SCHEMA)
    prepare_sync(other, workspace_id=workspace, device_id="peer")
    b = SyncClient(Journal(other, workspace_id=workspace, device_id="peer"), research_writer)
    service = ReferenceService(
        tmp_path / "authority.sqlite", blob_root=tmp_path / "authority-blobs"
    )
    ta, tb = service.enroll(workspace, device), service.enroll(workspace, "peer")
    with a.journal.transaction() as conn:
        registered = paths(conn)
    if registered:
        blobs, version_root = registered
    else:
        blobs, version_root = BlobStore(db.parent / "blobs"), db.parent / "research-versions"
    files = FileTransfers(
        a, blobs, service, origin="https://fixture.invalid", token=ta, version_root=version_root
    )
    documents = DocumentTransfers(a, blobs, service, origin="https://fixture.invalid", token=ta)

    def ready(op):
        if op["entity_type"] == "research_file":
            drain(lambda: files.upload(op), "uploaded")
        elif op["entity_type"] == "paper_document":
            drain(lambda: documents.upload(op), "uploaded")
        return True

    pending = a.journal.pending(1000)
    a.sync_once(service, ta, limit=1000, prepare_push=ready)
    b.sync_once(service, tb, limit=1000)
    peer_blobs = BlobStore(tmp_path / "peer-blobs")
    reader = DocumentTransfers(b, peer_blobs, service, origin="https://fixture.invalid", token=tb)
    artifacts = FileTransfers(b, peer_blobs, service, origin="https://fixture.invalid", token=tb)
    with b.journal.transaction() as conn:
        portable, local = conn.execute(
            "SELECT sync_id,local_id FROM research_paper_identity"
        ).fetchone()
    drain(lambda: reader.download(portable), "bound")
    for op in pending:
        if op["entity_type"] == "research_file":
            drain(lambda identity=op["entity_id"]: artifacts.download(identity), "bound")
    with closing(generation._connect(other)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id=workspace, device_id="peer")
        conn.commit()
    return a, b, service, ta, tb, portable, local, artifacts


def test_actual_initial_tombstones_peer_known_empty_and_explicit_restore(
    claims, tmp_path, monkeypatch
):
    result = candidate(claims, tmp_path, deleted=True)
    if result is None:
        return
    assert result["known_annotation_deletions"] == 4
    db = Path(result["database"])
    with closing(sqlite3.connect(db)) as conn:
        operations = [
            json.loads(row[0])
            for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        ]
        deletions = [
            op
            for op in operations
            if op["entity_type"] == "research_content" and op["action"] == "delete"
        ]
        assert len(deletions) == 4 and all(op["payload"] == {} for op in deletions)
        assert not any(op.get("payload", {}).get("feature") == "claims" for op in operations)
        assert conn.execute("SELECT count(*) FROM paper_claim_sets").fetchone()[0] == 0
    a, b, service, ta, tb, portable, local, artifacts = peer(result, tmp_path)
    for feature in annotation_content.FEATURES:
        saved = annotation_reader.saved(b.journal.path, local, feature)
        assert saved["known"] is True
    before = len(claims[2])
    complete = llm.complete_result
    monkeypatch.setattr(
        llm,
        "complete_result",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("deleted cache called AI")),
    )
    value, reason = claim_jobs.ensure(b.journal.path, local, legacy_root=tmp_path, force=True)
    assert value == {"claims": [], "known": True} and "deleted" in reason
    assert len(claims[2]) == before
    monkeypatch.setattr(llm, "complete_result", complete)
    reader = DocumentReader.from_workspace(b.journal.path)
    document = reader.resolve(local)
    assert document.available
    restored = claim_jobs.ClaimJob.capture(
        b.journal.path,
        local,
        legacy_root=reader.legacy_root,
        document=document,
        restore_deleted=True,
    )
    assert restored.run().status == "accepted"
    claim_ops = [
        op for op in b.journal.pending(1000) if op.get("payload", {}).get("feature") == "claims"
    ]
    assert len(claim_ops) == 1
    tombstone = next(op for op in deletions if op["entity_id"] == claim_ops[0]["entity_id"])
    assert claim_ops[0]["incarnation"] != tombstone["incarnation"]

    def ready(op):
        if op["entity_type"] == "research_file":
            drain(lambda: artifacts.upload(op), "uploaded")
        return True

    b.sync_once(service, tb, limit=1000, prepare_push=ready)
    a.sync_once(service, ta, limit=1000)
    assert (
        annotation_reader.saved(a.journal.path, "paper", "claims")["report"]
        == annotation_reader.saved(b.journal.path, local, "claims")["report"]
    )
    assert DocumentReader.from_workspace(b.journal.path).resolve(local).available
