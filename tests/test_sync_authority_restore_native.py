"""Native recovery journeys keep editable decks and original-pinned research."""

import json
import sqlite3
from contextlib import closing

from test_lineage_enrolled_import import mapping_options
from test_lineage_import_review import compared as compared
from test_lineage_import_review import corpus as corpus
from test_lineage_import_review import native_shared as native_shared
from test_lineage_import_review import shared as shared
from test_lineage_jobs import work
from test_sync_files import LOCAL, drain, save_current
from test_sync_files import codec as codec
from test_sync_files import pair as pair
from test_workspace_sync import Native

from paper_daily import (
    lineage_bound_originals,
    lineage_projection,
    lineage_sets,
    presentations,
    store,
    sync_admin,
    sync_bootstrap,
)
from paper_daily import research_generation as generation
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_authority_restore as recovery
from paper_daily.manual_highlight_ops import observe_owner
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import SyncSession


def publish(pair, tmp_path, client=None):
    original, original_client, _peer, old_files, _peer_files, old_token, _peer_token = pair
    client = client or original_client
    root = tmp_path / "marked-authority"
    sync_admin.initialize(root)
    service = sync_admin.authority(root)
    token = service.enroll(client.journal.workspace_id, client.journal.device_id)
    # Fixture writers already received the initial root; seed its exact receipt.
    for event in original.pull(old_token):
        assert service.push(token, event["operation"]) == event
    files = FileTransfers(
        client,
        old_files.store,
        service,
        origin="https://recovery.fixture.invalid",
        token=token,
        version_root=old_files.root,
    )
    try:
        for operation in client.journal.pending():
            if operation["entity_type"] == "research_file":
                drain(lambda op=operation: files.upload(op), "uploaded")
        for _ in range(20):
            result = client.sync_once(service, token, prepare_push=files.ready_to_push)
            if not result["pending"]:
                break
        assert result["pending"] == result["conflicts"] == 0
    finally:
        files.close()
    snapshot, recovered = tmp_path / "authority-snapshot", tmp_path / "recovered-authority"
    backup.export(root, snapshot)
    receipt = recovery.restore(snapshot, recovered, "workspace", "fresh-research", seconds=60)
    assert receipt["requires_enrollment"]
    return sync_admin.authority(recovered)


def join_and_download(service, control, destination, selected, *, missing_primary):
    endpoint, device = "https://recovery.fixture.invalid", "new-travel-device"
    token = service.enroll("fresh-research", device)
    joining = SyncSession(control, transport_factory=lambda url: Native(url, service, []))
    joining.connect(endpoint, "fresh-research", device, token, Ticket())
    try:
        assert sync_bootstrap.join(joining, destination, Ticket())["state"] == "metadata_ready"
    finally:
        joining.disconnect()
    database = destination / "papers.db"
    travel = SyncSession(database, transport_factory=lambda url: Native(url, service, []))
    travel.connect(endpoint, "fresh-research", device, token, Ticket())
    try:
        targets = selected(database)
        result = travel.prepare_offline(targets, Ticket())
        # Source fixtures specify which primaries exist; historical originals stay separate.
        assert result["missing_pdf_manifests"] == missing_primary
        assert result["state"] == "partial" and result["partial"]
        assert result["attachments"]["completed_targets"] > 0
        assert result["attachments"]["remaining_targets"] == 0
        assert result["attachments"]["pending"] == result["attachments"]["failed"] == 0
    finally:
        travel.disconnect()
    return database


def test_recovery_rejoins_editable_deck_and_exact_assets(
    pair, codec, tmp_path, tmp_path_factory, monkeypatch
):
    save_current(pair, codec[0])
    recovered = publish(pair, tmp_path)
    destination = tmp_path_factory.mktemp("recovered-deck-peer") / "workspace"
    database = join_and_download(
        recovered, pair[1].journal.path, destination, lambda _path: [LOCAL], missing_primary=1
    )
    monkeypatch.setattr(store, "DB_PATH", database)
    loaded = presentations.load_deck(LOCAL, "guide")
    assert loaded.slides[0].speaker_notes == "Speaker explanation"
    assert loaded.slides[0].elements[2]["text"] == "Editable"
    assert len(loaded.slides[0].elements) == 3
    assert loaded.sources[2]["url"] == "https://example.org/paper"
    from test_sync_files import png

    assert presentations.figure_bytes(loaded, "figure:1") == png("red")
    assert presentations.figure_bytes(loaded, "figure:2") == png("blue")


def test_recovery_rejoins_native_lineage_history_and_all_three_originals(
    compared, native_shared, pair, tmp_path, tmp_path_factory
):
    client, importer, archive, receipt, review = compared
    decision = review.decide({review.conflicts[0]["id"]: "replace"})
    work(
        importer.apply,
        work(importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt)),
    )
    focal = receipt["identity_mapping"]["focal"]["local_id"]
    latest = lineage_sets.decode(lineage_sets.saved(client.journal.path, focal)[0]["body_json"])
    recovered = publish(pair, tmp_path, importer.client)
    destination = tmp_path_factory.mktemp("recovered-lineage-peer") / "workspace"

    def selected(database):
        with closing(sqlite3.connect(database)) as conn:
            row = conn.execute("SELECT body_json FROM paper_lineage_sets").fetchone()
        return [item["paper_id"] for item in lineage_sets.decode(row[0])["bindings"]]

    database = join_and_download(
        recovered, client.journal.path, destination, selected, missing_primary=2
    )
    with closing(sqlite3.connect(database)) as conn:
        row = conn.execute("SELECT paper_id FROM paper_lineage_sets").fetchone()
        assert conn.execute("SELECT count(*) FROM " + lineage_projection.HISTORY).fetchone()[0] == 2
    saved = lineage_sets.saved(database, row[0])[0]
    assert lineage_sets.decode(saved["body_json"])["report"] == latest["report"]
    owner = observe_owner(
        database, saved["paper_id"], expected_native=generation._identity(database)
    )
    original = json.loads(native_shared[3][0]["body_json"])
    exact = {
        source["document_hash"]: native_shared[2][binding["paper_id"]]
        for binding, source in zip(original["bindings"], original["report"]["sources"], strict=True)
    }
    assert len(exact) == 3
    for source in latest["report"]["sources"]:
        proof = work(lineage_bound_originals.prepare, owner, saved, source["id"])
        assert (
            lineage_bound_originals.for_delivery(proof, owner, saved, source["id"])
            == exact[source["document_hash"]]
        )
