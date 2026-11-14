"""Freshly enrolled Lineage travels through real sync and attachment operations."""

from pathlib import Path
from uuid import uuid4

from test_lineage_enrollment import corpus as corpus
from test_lineage_enrollment import selection
from test_lineage_jobs import work
from test_lineage_lifecycle import active as active
from test_lineage_projection import rows
from test_workspace_sync import Native

from paper_daily import lineage_bound_originals, lineage_projection, lineage_sets, sync_bootstrap
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import observe_owner
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import research_projection_writer, research_writer
from paper_daily.sync_service import ReferenceService
from paper_daily.workspace_enrollment import EnrollmentService
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import SyncSession
from paper_daily.workspace_sync_files import AttachmentSteps


def test_enrolled_report_reaches_peer_before_verified_original_download(active, corpus, tmp_path):
    owner, original = active
    expected = {
        binding["source_id"]: (corpus[1] / (binding["paper_id"] + ".pdf")).read_bytes()
        for binding in lineage_sets.decode(original["body_json"])["bindings"]
    }
    before = owner.database.read_bytes()
    result = EnrollmentService(owner.database).prepare(
        tmp_path / "enrolled",
        backup_output=tmp_path / "baseline.zip",
        request_id=str(uuid4()),
        pdfs=selection(corpus),
    )
    workspace, device = result["workspace_id"], result["device_id"]
    sender = SyncClient(
        Journal(Path(result["database"]), workspace_id=workspace, device_id=device),
        research_writer,
        projection_writer=research_projection_writer,
    )
    originals = [
        operation
        for operation in sender.journal.pending()
        if operation["entity_type"] == "research_file"
        and operation["payload"].get("feature") == "original_source"
    ]
    assert len(originals) == 3
    authority = ReferenceService(tmp_path / "authority.sqlite", blob_root=tmp_path / "server-blobs")
    token = authority.enroll(workspace, device)
    peer_device = str(uuid4())
    peer_token = authority.enroll(workspace, peer_device)
    endpoint = "https://fixture.invalid"
    transfer = AttachmentSteps(
        sender,
        Native(endpoint, authority, []),
        token,
        lambda: None,
        lambda _value: None,
    )
    try:
        for _ in range(6):
            synced = sender.sync_once(authority, token, prepare_push=transfer.prepare)
            if synced["pending"] == 0:
                break
        assert synced["pending"] == 0 and synced["conflicts"] == 0
        assert transfer.failed == 0 and transfer.steps > 0
        joining = SyncSession(
            sender.journal.path, transport_factory=lambda url: Native(url, authority, [])
        )
        joining.connect(endpoint, workspace, peer_device, peer_token, Ticket())
        destination = tmp_path / "peer"
        try:
            joined = sync_bootstrap.join(joining, destination, Ticket())
            assert joined["state"] == "metadata_ready" and joined["attachments"] == "unavailable"
        finally:
            joining.disconnect()
        peer_path = destination / "papers.db"
        peer = SyncClient(
            Journal.attach_existing(peer_path, workspace_id=workspace, device_id=peer_device),
            research_writer,
            projection_writer=research_projection_writer,
        )
        reports = rows(peer, lineage_sets.TABLE)
        assert len(reports) == 1
        remote = reports[0]
        body = lineage_sets.decode(remote["body_json"])
        assert body["report"] == lineage_sets.decode(original["body_json"])["report"]
        assert remote["source_hash"] == original["source_hash"]
        with peer.journal.transaction() as conn:
            assert conn.execute("SELECT count(*) FROM research_file_applied").fetchone()[0] == 0
        loaded = observe_owner(
            peer_path, remote["paper_id"], expected_native=generation._identity(peer_path)
        )
        for source in body["report"]["sources"]:
            assert work(lineage_bound_originals.prepare, loaded, remote, source["id"]) is None
        travel = SyncSession(peer_path, transport_factory=lambda url: Native(url, authority, []))
        travel.connect(endpoint, workspace, peer_device, peer_token, Ticket())
        try:
            selected = [binding["paper_id"] for binding in body["bindings"]]
            downloaded = travel.prepare_offline(selected, Ticket())
            assert downloaded["state"] == "downloaded" and not downloaded["partial"]
            for source in body["report"]["sources"]:
                proof = work(lineage_bound_originals.prepare, loaded, remote, source["id"])
                data = lineage_bound_originals.for_delivery(proof, loaded, remote, source["id"])
                assert data == expected[source["id"]]
            from paper_daily.document_reader import DocumentReader

            reader = DocumentReader.from_workspace(peer_path)
            for binding in body["bindings"]:
                primary = reader.resolve(binding["paper_id"])
                assert primary.available
                assert primary.path.read_bytes() == expected[binding["source_id"]]
            count = len(rows(peer, lineage_projection.HISTORY))
            peer.sync_once(authority, peer_token)
            sender.sync_once(authority, token, prepare_push=transfer.prepare)
            assert len(rows(peer, lineage_projection.HISTORY)) == count == 1
            assert rows(peer, lineage_sets.TABLE) == reports
        finally:
            travel.disconnect()
    finally:
        transfer.close()
    assert owner.database.read_bytes() == before
