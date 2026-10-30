"""Selected offline downloads never imply metadata sync, AI work or unrelated transfers."""
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_sync_document_research import pdf_bytes
from test_sync_files import INPUTS
from test_sync_files import codec as codec_fixture
from test_sync_http import running
from test_sync_operations import paper
from test_sync_transfers import finish_upload
from test_sync_transfers import setup as transfer_setup_fixture
from test_workspace_sync import Native
from test_workspace_sync_files import enable

from paper_daily.sync_artifacts import applied_file, stage_bytes
from paper_daily.sync_blobs import BlobManifest
from paper_daily.sync_deck_files import encode_deck
from paper_daily.sync_document_actions import stage_file
from paper_daily.sync_documents import applied_document, desired_document
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_files import file_id
from paper_daily.sync_http import make_server
from paper_daily.sync_operations import ResearchOperations
from paper_daily.sync_transfers import CHUNK_BYTES
from paper_daily.workspace_offline import OfflineService
from paper_daily.workspace_service import Cancelled, Ticket
from paper_daily.workspace_sync import SyncSession, SyncStopped

transfer_setup = transfer_setup_fixture
codec = codec_fixture


@pytest.fixture
def world(transfer_setup, codec, tmp_path):
    a, b, authority, ta, tb, stores, pdfs, actions, selected = transfer_setup
    created = actions.create_list('Unrelated list', [{'paper': paper('Unrelated')}],
                                  request_id='unrelated-list')
    unrelated = created['papers'][0]['paper_id']
    files = [FileTransfers(c, s, authority, origin='http://127.0.0.1:1', token=token)
             for c, s, token in zip((a, b), stores, (ta, tb), strict=True)]
    targets = {}
    for identity, text in ((selected, 'Selected paper'), (unrelated, 'Unrelated paper')):
        data = pdf_bytes(text) + b'\n%' + b'x' * (CHUNK_BYTES + 100) + b'\n%%EOF\n'
        source = tmp_path / (identity + '.pdf')
        source.write_bytes(data)
        manifest = stage_file(stores[0], source)
        attached = actions.attach_document(identity, manifest, store=stores[0],
                                            request_id='pdf-' + identity)
        operation = next(op for op in a.journal.pending(1000)
                         if op['operation_id'] == attached['operation_id'])
        finish_upload(pdfs[0], operation)
        value = codec[0]
        payload, blobs = encode_deck(value, identity, input_versions=INPUTS,
                                     source_document_hash=manifest.sha256)
        stage_bytes(stores[0], blobs)
        deck = a.new_graph_operation('research_file', file_id(identity, 'deck', 'guide'), payload)
        a.save(deck)
        for _ in range(20):
            if files[0].upload(deck)['state'] == 'uploaded':
                break
        else:
            pytest.fail('Fixture deck upload did not finish')
        targets[identity] = {'pdf': manifest, 'deck': deck, 'bytes': data}
    a.sync_once(authority, ta, limit=100)
    for _ in range(8):
        result = b.sync_once(authority, tb, limit=100)
        if result['received'] == 0:
            break
    enable(b)
    local = {}
    with sqlite3.connect(b.journal.path) as conn:
        local = dict(conn.execute('SELECT sync_id,local_id FROM research_paper_identity'))
    calls, requests = [], []
    original = authority.blob_read

    def read(*args, **kwargs):
        requests.append((args[1], args[3]))
        return original(*args, **kwargs)

    authority.blob_read = read
    active = [b.journal.path]
    session = SyncSession(b.journal.path, current_path=lambda: active[0],
                          transport_factory=lambda endpoint: Native(endpoint, authority, calls))
    session.connect('http://127.0.0.1:1', 'workspace', 'b', tb, Ticket())
    calls.clear()
    return {'a': a, 'b': b, 'authority': authority, 'token': tb, 'stores': stores,
            'session': session, 'selected': selected, 'unrelated': unrelated,
            'local': local, 'targets': targets, 'calls': calls, 'requests': requests,
            'active': active, 'tmp_path': tmp_path}


def selected_ids(world):
    return [world['local'][world['selected']]]


def assert_unrelated_absent(world):
    target = world['targets'][world['unrelated']]
    with world['b'].journal.transaction() as conn:
        assert applied_document(conn, world['unrelated']) is None
        assert applied_file(conn, target['deck']['entity_id']) is None
    assert not world['stores'][1]._path(target['pdf']).exists()
    body = target['deck']['payload']['body']
    assert not world['stores'][1]._path(BlobManifest(body['sha256'], body['size'])).exists()


def test_selected_pdf_and_editable_deck_download_without_metadata_sync_or_pin(world):
    b = world['b']
    ResearchOperations(b).create_list('Unsent local work', [], request_id='local-unsent')
    before = b.status()
    pending = b.journal.pending(1000)
    result = world['session'].prepare_offline(selected_ids(world), Ticket())
    assert result['state'] == 'downloaded' and not result['partial']
    assert result['attachments']['remaining_targets'] == 0
    assert result['attachments']['pending'] == 0
    assert result['verification_required']
    assert not result['attachments']['complete_offline_verified']
    assert b.status()['cursor'] == before['cursor']
    assert b.journal.pending(1000) == pending
    assert 'push' not in world['calls'] and 'pull' not in world['calls']
    assert not any(name in world['calls'] for name in ('blob_begin', 'blob_append', 'blob_commit'))
    assert OfflineService(b.journal.path).pins() == []
    assert OfflineService(b.journal.path).status(selected_ids(world))['ready']
    assert_unrelated_absent(world)


def test_repeated_selected_downloads_reuse_bytes_and_existing_transfer_identities(world):
    session = world['session']
    first = session.prepare_offline(selected_ids(world), Ticket())
    assert not first['partial']
    requests = list(world['requests'])
    with world['b'].journal.transaction() as conn:
        counts = [conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                  for table in ('research_document_transfers', 'research_file_transfers')]
    for _ in range(3):
        assert not session.prepare_offline(selected_ids(world) * 2, Ticket())['partial']
    assert world['requests'] == requests
    with world['b'].journal.transaction() as conn:
        assert counts == [conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                          for table in ('research_document_transfers', 'research_file_transfers')]
    assert_unrelated_absent(world)


def test_bounded_pass_resumes_selected_pdf_at_durable_offset(world):
    session = world['session']
    first = session.prepare_offline(selected_ids(world), Ticket(), steps=1)
    assert first['partial'] and first['attachments']['remaining_targets'] == 2
    selected = world['targets'][world['selected']]['pdf']
    offsets = [offset for digest, offset in world['requests'] if digest == selected.sha256]
    assert offsets == [0]
    second = session.prepare_offline(selected_ids(world), Ticket())
    assert not second['partial']
    offsets = [offset for digest, offset in world['requests'] if digest == selected.sha256]
    assert offsets == [0, CHUNK_BYTES]
    assert_unrelated_absent(world)


@pytest.mark.parametrize('selection', [['unknown'], [''], [1], ['p'] * 101, 'not-a-list'])
def test_invalid_selection_never_authenticates_or_transfers(world, selection):
    with pytest.raises(ValueError):
        world['session'].prepare_offline(selection, Ticket())
    assert not world['calls'] and not world['requests']


def test_empty_selection_is_local_and_never_authenticates(world):
    result = world['session'].prepare_offline([], Ticket())
    assert result['state'] == 'empty' and result['attachments'] is None
    assert not world['calls'] and not world['requests']


@pytest.mark.parametrize('budget', [{'steps': 0}, {'steps': True}, {'steps': 257},
                                  {'seconds': 0}, {'seconds': float('nan')}])
def test_invalid_budgets_never_contact_authority(world, budget):
    with pytest.raises(ValueError):
        world['session'].prepare_offline(selected_ids(world), Ticket(), **budget)
    assert not world['calls']


@pytest.mark.parametrize('change', ['disconnect', 'cancel-session', 'cancel-ticket', 'workspace'])
def test_changed_job_context_cannot_bind_late_download(world, monkeypatch, change):
    ticket = Ticket()
    authority, session = world['authority'], world['session']
    original = authority.blob_read

    def changed(*args, **kwargs):
        data = original(*args, **kwargs)
        if change == 'disconnect':
            session.disconnect()
        elif change == 'cancel-session':
            session.cancel()
        elif change == 'cancel-ticket':
            ticket.cancel()
        else:
            world['active'][0] = world['tmp_path'] / 'other.db'
        return data

    monkeypatch.setattr(authority, 'blob_read', changed)
    with pytest.raises((SyncStopped, Cancelled)):
        session.prepare_offline(selected_ids(world), ticket)
    with world['b'].journal.transaction() as conn:
        assert applied_document(conn, world['selected']) is None
    assert_unrelated_absent(world)


def test_selected_source_replacement_aborts_instead_of_downloading_new_target(world, monkeypatch):
    authority = world['authority']
    original = authority.blob_read
    changed = False

    def replace(*args, **kwargs):
        nonlocal changed
        data = original(*args, **kwargs)
        if not changed:
            changed = True
            source = world['tmp_path'] / 'replacement.pdf'
            source.write_bytes(pdf_bytes('New current source'))
            manifest = stage_file(world['stores'][1], source)
            ResearchOperations(world['b']).attach_document(
                world['selected'], manifest, store=world['stores'][1], request_id='replacement')
        return data

    monkeypatch.setattr(authority, 'blob_read', replace)
    with pytest.raises(SyncStopped):
        world['session'].prepare_offline(selected_ids(world), Ticket())
    with world['b'].journal.transaction() as conn:
        assert applied_document(conn, world['selected']) is None
        assert desired_document(conn, world['selected'])['sha256'] != (
            world['targets'][world['selected']]['pdf'].sha256)
    assert len(world['requests']) == 1


def test_duplicate_jobs_share_running_guard_without_second_network_request(world, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = world['authority'].blob_read

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(4)
        return original(*args, **kwargs)

    monkeypatch.setattr(world['authority'], 'blob_read', paused)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(world['session'].prepare_offline, selected_ids(world), Ticket())
        try:
            assert entered.wait(3)
            calls = list(world['calls'])
            with pytest.raises(SyncStopped, match='active'):
                world['session'].prepare_offline(selected_ids(world), Ticket())
            assert world['calls'] == calls
        finally:
            release.set()
        assert future.result(timeout=12)['state'] == 'downloaded'


def test_revoked_credential_preserves_metadata_and_pending_work(world):
    before = world['b'].journal.pending(1000)
    world['authority'].revoke(world['token'])
    with pytest.raises(PermissionError):
        world['session'].prepare_offline(selected_ids(world), Ticket())
    assert world['b'].journal.pending(1000) == before
    assert not world['requests']
    assert world['session'].summary()['state'] == 'reconnect'


def test_corrupt_partial_fails_then_explicit_retry_repairs_selected_version(world, monkeypatch):
    original = world['authority'].blob_read
    digest = world['targets'][world['selected']]['pdf'].sha256

    def corrupted(*args, **kwargs):
        data = original(*args, **kwargs)
        return b'x' * len(data) if args[1] == digest else data

    monkeypatch.setattr(world['authority'], 'blob_read', corrupted)
    failed = world['session'].prepare_offline(selected_ids(world), Ticket())
    assert failed['partial'] and failed['attachments']['failed']
    assert not OfflineService(world['b'].journal.path).status(selected_ids(world))['ready']
    monkeypatch.setattr(world['authority'], 'blob_read', original)
    repaired = world['session'].prepare_offline(selected_ids(world), Ticket())
    assert not repaired['partial']
    assert OfflineService(world['b'].journal.path).status(selected_ids(world))['ready']
    assert_unrelated_absent(world)


def test_corrupt_applied_file_is_failure_even_when_metadata_pending_is_zero(world):
    session = world['session']
    assert not session.prepare_offline(selected_ids(world), Ticket())['partial']
    manifest = world['targets'][world['selected']]['pdf']
    path = world['stores'][1].verified_path(manifest)
    path.write_bytes(b'x' * manifest.size)
    again = session.prepare_offline(selected_ids(world), Ticket())
    assert again['attachments']['pending'] == 0
    assert again['partial'] and again['attachments']['remaining_targets']
    assert again['attachments']['failed']
    assert not OfflineService(world['b'].journal.path).status(selected_ids(world))['ready']


def test_real_loopback_http_selected_roundtrip(world):
    server = make_server(world['authority'])
    with running(server) as endpoint:
        session = SyncSession(world['b'].journal.path)
        session.connect(endpoint, 'workspace', 'b', world['token'], Ticket())
        result = session.prepare_offline(selected_ids(world), Ticket())
    assert result['state'] == 'downloaded'
    report = OfflineService(world['b'].journal.path).status(selected_ids(world))
    assert report['ready']
    assert_unrelated_absent(world)



def test_private_empty_filter_never_means_download_everything(world):
    from paper_daily.workspace_sync_files import AttachmentSteps

    ticket = Ticket()
    with world['session'].authorized(ticket) as (transport, token, _identity, live):
        files = AttachmentSteps(world['b'], transport, token, live, lambda _value: None)
        try:
            assert files.status()['pending'] == 4
            result = files.download_selected([])
            assert result['transfer_targets'] == result['remaining_targets'] == 0
            assert files.status(paper_ids=[])['pending'] == 0
            assert files.status()['pending'] == 4
            with pytest.raises(ValueError):
                files.download_selected([{}])
        finally:
            files.close()
    assert not world['requests']


def test_pre_cancelled_action_never_authenticates(world):
    ticket = Ticket()
    ticket.cancel()
    with pytest.raises(Cancelled):
        world['session'].prepare_offline(selected_ids(world), ticket)
    assert not world['calls'] and not world['requests']


def test_missing_known_pdf_manifest_stays_partial_without_discovery(world):
    result = ResearchOperations(world['b']).create_list(
        'Paper without PDF', [{'paper': paper('No PDF manifest')}], request_id='missing-pdf')
    identity = result['papers'][0]['paper_id']
    with world['b'].journal.transaction() as conn:
        local = conn.execute('SELECT local_id FROM research_paper_identity WHERE sync_id=?',
                             (identity,)).fetchone()[0]
    report = world['session'].prepare_offline([local], Ticket())
    assert report['partial'] and report['missing_pdf_manifests'] == 1
    assert report['attachments']['transfer_targets'] == 0
    assert not world['requests'] and 'pull' not in world['calls'] and 'push' not in world['calls']
