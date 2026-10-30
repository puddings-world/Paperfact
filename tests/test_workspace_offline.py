"""Offline intent and selected closure checks use real isolated stores, never network."""
import sqlite3

import pytest
from test_sync_files import INPUTS
from test_sync_files import codec as codec_fixture
from test_sync_transfers import attach
from test_sync_transfers import setup as transfer_setup_fixture
from test_workspace_sync_files import enable

from paper_daily import workspace_offline as offline
from paper_daily.sync_artifacts import activate, materialize, paths, stage_bytes
from paper_daily.sync_deck_files import encode_deck
from paper_daily.sync_documents import bind_verified_document, desired_document, verify_document
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_files import file_id
from paper_daily.workspace_service import Cancelled, SnapshotChanged, Ticket, WorkspaceChanged

transfer_setup = transfer_setup_fixture
codec = codec_fixture


@pytest.fixture
def prepared(transfer_setup, tmp_path):
    operation, manifest, data = attach(transfer_setup, tmp_path)
    a = transfer_setup[0]
    root = transfer_setup[5][0]
    portable = transfer_setup[-1]
    with a.journal.transaction() as conn:
        target = desired_document(conn, portable)
    proof = verify_document(root, target)
    with a.journal.transaction() as conn:
        assert bind_verified_document(conn, target, proof)
        local = conn.execute('SELECT local_id FROM research_paper_identity WHERE sync_id=?',
                             (portable,)).fetchone()[0]
    FileTransfers(a, root, transfer_setup[2], origin='http://127.0.0.1:1',
                  token=transfer_setup[3])
    enable(a)
    service = offline.OfflineService(a.journal.path)
    return service, a, local, portable, root, manifest, data


def test_plan_is_read_only_and_status_checks_real_pdf(prepared, monkeypatch):
    service, client, local, portable, root, manifest, data = prepared
    before = client.journal.path.read_bytes()
    original = offline.verify_document
    monkeypatch.setattr(offline, 'verify_document', lambda *a: pytest.fail('Plan hashed a PDF'))
    plan = service.plan([local, local])
    assert len(plan['papers']) == 1 and not plan['ready']
    assert plan['papers'][0]['portable_id'] == portable
    assert plan['required_bytes'] == len(data)
    assert plan['papers'][0]['pdf']['state'] == 'unchecked'
    assert client.journal.path.read_bytes() == before
    monkeypatch.setattr(offline, 'verify_document', original)
    result = service.status([local])
    assert result['ready'] and result['papers'][0]['ready']
    assert result['verified_bytes'] == len(data) and result['verified_assets'] == 1
    assert not result['whole_workspace_offline_verified']
    assert root.verified_path(manifest).read_bytes() == data
    assert client.journal.path.read_bytes() == before


def test_pins_persist_without_creating_research_operations_and_can_be_removed(prepared):
    service, client, local, portable, *_ = prepared
    before = client.journal.pending(1000)
    assert service.pins() == []
    for _ in range(3):
        assert service.set_pins([local, local]) == {'paper_ids': [local], 'pinned': True}
    reopened = offline.OfflineService(client.journal.path)
    assert reopened.pins() == [{'paper_id': local, 'portable_id': portable}]
    assert reopened.plan([local])['papers'][0]['pinned']
    assert client.journal.pending(1000) == before
    with sqlite3.connect(client.journal.path) as conn:
        rows = conn.execute('SELECT key,value FROM kv WHERE key LIKE ?',
                            (offline.PREFIX + '%',)).fetchall()
    assert rows == [(offline.PREFIX + portable, 'true')]
    reopened.set_pins([local], enabled=False)
    assert reopened.pins() == [] and client.journal.pending(1000) == before


def test_empty_selection_never_claims_offline_readiness(prepared):
    service, *_ = prepared
    assert service.plan([])['papers'] == []
    assert not service.status([])['ready']
    assert service.set_pins([]) == {'paper_ids': [], 'pinned': True}


@pytest.mark.parametrize('selection', [['unknown'], [''], [1], 'paper', ['x'] * 101])
def test_invalid_selection_does_not_change_pins(prepared, selection):
    service, *_ = prepared
    with pytest.raises(ValueError):
        service.plan(selection)
    with pytest.raises(ValueError):
        service.set_pins(selection)
    assert service.pins() == []


def test_budget_is_partial_without_hashing_or_claiming_verified_bytes(prepared, monkeypatch):
    service, _, local, *_ = prepared
    monkeypatch.setattr(offline, 'verify_document', lambda *a: pytest.fail('Exceeded byte budget'))
    result = service.status([local], max_bytes=1)
    assert result['partial'] and not result['ready']
    assert result['verified_bytes'] == 0
    assert result['papers'][0]['pdf']['state'] == 'budget_exceeded'


@pytest.mark.parametrize('budget', [
    {'max_bytes': 0}, {'max_bytes': True}, {'seconds': float('nan')},
    {'seconds': -1}, {'max_assets': 0}])
def test_invalid_work_budgets_fail_closed(prepared, budget):
    service, _, local, *_ = prepared
    with pytest.raises(ValueError):
        service.status([local], **budget)


def test_corrupt_blob_is_never_ready_and_explicit_recheck_reads_repaired_bytes(prepared):
    service, _, local, _, root, manifest, data = prepared
    path = root.verified_path(manifest)
    path.write_bytes(b'x' * len(data))
    bad = service.status([local])
    assert not bad['ready'] and bad['verified_bytes'] == 0
    assert bad['papers'][0]['pdf']['state'] == 'unavailable'
    path.write_bytes(data)
    assert service.status([local])['ready']


def test_unapplied_pdf_replacement_keeps_old_bytes_but_never_claims_new_version_ready(
    prepared, transfer_setup, tmp_path,
):
    service, _, local, _, root, manifest, data = prepared
    attach(transfer_setup, tmp_path, request_id='new-pdf', text='Replacement')
    result = service.status([local])
    assert not result['ready']
    assert result['papers'][0]['pdf']['state'] == 'unbound'
    assert root.verified_path(manifest).read_bytes() == data


def test_pdf_change_during_verification_cannot_return_stale_ready(
    prepared, transfer_setup, tmp_path, monkeypatch,
):
    service, _, local, *_ = prepared
    original = offline.verify_document

    def replaced(*args):
        proof = original(*args)
        attach(transfer_setup, tmp_path, request_id='during-check', text='New source')
        return proof

    monkeypatch.setattr(offline, 'verify_document', replaced)
    with pytest.raises(SnapshotChanged):
        service.status([local])


@pytest.mark.parametrize('when', ['before', 'during'])
def test_cancel_never_returns_a_ready_result_or_saves_intent(prepared, monkeypatch, when):
    service, _, local, *_ = prepared
    ticket = Ticket()
    if when == 'before':
        ticket.cancel()
    else:
        original = offline.verify_document

        def cancelled(*args):
            proof = original(*args)
            ticket.cancel()
            return proof

        monkeypatch.setattr(offline, 'verify_document', cancelled)
    with pytest.raises(Cancelled):
        service.status([local], ticket)
    with pytest.raises(Cancelled):
        service.set_pins([local], ticket=ticket)
    assert not service.pins()


def test_workspace_switch_during_verification_drops_result(prepared, tmp_path, monkeypatch):
    _, client, local, *_ = prepared
    active = [client.journal.path]
    service = offline.OfflineService(client.journal.path, current_path=lambda: active[0])
    original = offline.verify_document

    def changed(*args):
        proof = original(*args)
        active[0] = tmp_path / 'another.db'
        return proof

    monkeypatch.setattr(offline, 'verify_document', changed)
    with pytest.raises(WorkspaceChanged):
        service.status([local])


def add_deck(prepared, codec, *, source='current'):
    _, client, _local, portable, blob_store, manifest, _data = prepared
    value = codec[0]
    payload, blobs = encode_deck(value, portable, input_versions=INPUTS,
                                 source_document_hash=(manifest.sha256 if source == 'current'
                                                       else None if source == 'unknown'
                                                       else '0' * 64))
    stage_bytes(blob_store, blobs)
    operation = client.new_graph_operation('research_file', file_id(portable, 'deck', value.mode),
                                          payload)
    client.save(operation)
    with client.journal.transaction() as conn:
        configured = paths(conn)
    directory = materialize(blob_store, configured[1], operation)
    with client.journal.transaction() as conn:
        assert activate(conn, operation, directory)
    return operation


def test_current_editable_deck_closure_verifies_png_assets_and_source_version(prepared, codec):
    service, _, local, *_ = prepared
    add_deck(prepared, codec)
    result = service.status([local])
    assert result['ready'] and result['verified_assets'] == 4
    assert result['papers'][0]['artifacts'][0]['state'] == 'verified'
    assert result['papers'][0]['artifacts'][0]['source_state'] == 'current'
    assert result['verified_bytes'] == result['required_bytes']


def test_missing_deck_asset_does_not_inflate_verified_counts(prepared, codec):
    service, _, local, _, blob_store, *_ = prepared
    operation = add_deck(prepared, codec)
    asset = operation['payload']['assets'][0]
    from paper_daily.sync_blobs import BlobManifest
    blob_store.verified_path(BlobManifest(asset['sha256'], asset['size'])).unlink()
    result = service.status([local])
    assert not result['ready']
    assert result['verified_assets'] == 1  # PDF only; no half-verified deck claim.
    assert result['papers'][0]['artifacts'][0]['state'] == 'unavailable'


@pytest.mark.parametrize('source', ['unknown', 'mismatch'])
def test_deck_bytes_do_not_imply_verified_source_identity(prepared, codec, source):
    service, _, local, *_ = prepared
    add_deck(prepared, codec, source=source)
    result = service.status([local])
    assert not result['ready']
    artifact = result['papers'][0]['artifacts'][0]
    assert artifact['state'] == 'verified' and artifact['source_state'] == source


def test_missing_pdf_manifest_cannot_be_ready(transfer_setup):
    client, _, _, _, _, *_rest = transfer_setup
    portable = transfer_setup[-1]
    enable(client)
    with sqlite3.connect(client.journal.path) as conn:
        local = conn.execute('SELECT local_id FROM research_paper_identity WHERE sync_id=?',
                             (portable,)).fetchone()[0]
    result = offline.OfflineService(client.journal.path).status([local])
    assert not result['ready']
    assert result['papers'][0]['pdf']['state'] == 'missing_manifest'


def test_unpin_remains_available_when_asset_metadata_is_damaged(prepared):
    service, client, local, portable, *_ = prepared
    service.set_pins([local])
    with sqlite3.connect(client.journal.path) as conn:
        conn.execute('UPDATE research_document_desired SET target=? WHERE paper_id=?',
                     ('broken metadata', portable))
    with pytest.raises(ValueError):
        service.plan([local])
    service.set_pins([local], enabled=False)
    assert service.pins() == []


def test_pin_storage_failure_rolls_back_and_explicit_retry_preserves_one_intent(
    prepared, monkeypatch,
):
    service, _, local, *_ = prepared
    original = offline.CaptureConnection

    class FailCommit(original):
        def commit(self):
            raise OSError('Synthetic storage failure')

    monkeypatch.setattr(offline, 'CaptureConnection', FailCommit)
    with pytest.raises(OSError):
        service.set_pins([local])
    assert service.pins() == []
    monkeypatch.setattr(offline, 'CaptureConnection', original)
    service.set_pins([local])
    assert len(service.pins()) == 1


def test_shared_deck_assets_are_counted_once(prepared, codec):
    service, _, local, *_ = prepared
    add_deck(prepared, codec)
    codec[0].mode = 'notes'
    add_deck(prepared, codec)
    result = service.status([local])
    assert result['ready']
    assert len(result['papers'][0]['artifacts']) == 2
    assert result['verified_assets'] == 5  # PDF, two bodies, two shared PNGs.
    assert result['verified_bytes'] == result['required_bytes']
    assert result['verification_bytes'] > result['verified_bytes']


def test_blob_ownership_mismatch_cannot_be_reported_ready(prepared):
    service, _, local, _, root, *_ = prepared
    with sqlite3.connect(root.root / 'index.sqlite') as conn:
        conn.execute('UPDATE transfer_binding SET device=?', ('another-device',))
    with pytest.raises(WorkspaceChanged):
        service.status([local])


def test_late_blob_change_invalidates_earlier_pdf_proof(prepared, codec, monkeypatch):
    service, _, local, _, root, manifest, data = prepared
    add_deck(prepared, codec)
    original = offline.verify_closure

    def changed(*args):
        proof = original(*args)
        root._path(manifest).write_bytes(b'x' * len(data))
        return proof

    monkeypatch.setattr(offline, 'verify_closure', changed)
    result = service.status([local])
    assert not result['ready']
    assert result['papers'][0]['pdf']['state'] == 'invalid'
    assert result['verified_assets'] == 3  # Only the intact deck closure.
