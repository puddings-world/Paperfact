"""Whole-deck recovery retains editable bytes, owned originals and one decision."""

from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from test_sync_device_recovery import dump
from test_sync_files import PAPER, drain
from test_sync_recovery_note_original_group import group as _original_group
from test_sync_recovery_note_original_group import peer, retire_source_before_review
from test_sync_recovery_positioned_note import positioned as positioned
from test_sync_recovery_target import attached
from test_sync_recovery_target import codec as codec
from test_sync_recovery_target import pair as pair
from test_workspace_dialog import app as app
from test_workspace_dialog import wait

from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_deck_group as recovery
from paper_daily import sync_recovery_target as target
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_artifacts import applied_file, desired_file, stage_bytes, verify_closure
from paper_daily.sync_authority_backup import BackupCancelled
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_files import file_id
from paper_daily.sync_research import research_writer
from paper_daily.sync_source_files import _inspection_paths

original_group = _original_group


@pytest.fixture
def group(original_group, pair, codec):
    old, previous, _, path, _, service, sha, data, token = original_group
    payload = deepcopy(codec[1])
    payload['source_document_hash'] = sha
    from paper_daily.sync_files import canonical_json, descriptor, read_json

    blobs = deepcopy(codec[2])
    body = read_json(blobs.pop(payload['body']['sha256']))
    body['deck']['slides'][0]['elements'].append(dict(
        kind='table', x=20, y=320, w=500, h=80, rows=[['Cell evidence', '50']], header=True,
    ))
    content = canonical_json(body)
    payload['body'] = descriptor(content, 'application/json')
    blobs[payload['body']['sha256']] = content
    stage_bytes(pair[3].store, blobs)
    root = old.new_graph_operation('research_file', file_id(PAPER, 'deck', 'guide'), payload)
    old.save(root)
    source = candidates.prepare(old.journal.path, previous.snapshot, previous.workspace)
    change = next(row['change_id'] for row in source.page()['items']
                  if row['operation_id'] == root['operation_id'])
    return old, source, change, path, root, service, sha, data, token


def plan(group, request=None, **kwargs):
    _, source, change, path, *_ = group
    return recovery.prepare(target.observe(source, path), change, request or str(uuid4()), **kwargs)


def saved(path, root):
    with closing(_readonly_connection(path)) as conn:
        operation = applied_file(conn, root['entity_id'])
        assert operation == desired_file(conn, root['entity_id'])
        store, _ = _inspection_paths(conn)
        return operation, verify_closure(store, operation)[1]


def test_editable_deck_original_and_receipt_commit_once_and_reach_another_native_peer(
    group, tmp_path_factory,
):
    old, source, change, path, root, service, sha, _, token = group
    source, change = retire_source_before_review(old, source, root, sha)
    group = (old, source, change, *group[3:])
    before = dump(old.journal.path), dump(path)
    request = str(uuid4())
    prepared = plan(group, request)
    assert (dump(old.journal.path), dump(path)) == before
    comparison = prepared.comparison
    assert comparison['state'] == 'absent' and comparison['original_hashes'] == [sha]
    assert comparison['source']['deck']['slides'][0]['speaker_notes'] == 'Speaker explanation'
    first = prepared.apply()
    assert first['applied'] and not first['remote_acceptance_checked']
    operation, body = saved(path, root)
    assert body == comparison['source']
    assert operation['payload']['input_versions']['workspace_id'] == 'workspace'
    assert operation['workspace_id'] == 'fresh-research'
    assert dump(old.journal.path) == before[0]
    assert not prepared.apply()['applied']
    assert not plan(group, request).apply()['applied']
    client = attached(path)
    pending = client.journal.pending()
    assert [o['payload']['feature'] for o in pending] == ['original_source', 'deck']
    with closing(_readonly_connection(path)) as conn:
        store, version_root = _inspection_paths(conn)
    transfer = FileTransfers(client, BlobStore(store.root), service,
        origin='https://recovery.fixture.invalid', token=token, version_root=version_root)
    try:
        for item in pending:
            drain(lambda item=item: transfer.upload(item), 'uploaded')
        result = client.sync_once(service, token, prepare_push=transfer.ready_to_push)
        assert result['pending'] == result['conflicts'] == 0
    finally:
        transfer.close()
    other = peer(path, service, tmp_path_factory)
    assert saved(other, root)[1] == body
    assert len(body['deck']['slides'][0]['elements']) == 4
    assert body['deck']['slides'][0]['elements'][3]['rows'] == [['Cell evidence', '50']]
    assert len(body['deck']['figures']) == 2


@pytest.mark.parametrize('failure', ['write', 'cancel'])
def test_failure_after_original_rolls_back_deck_activation_outbox_and_receipt(
    group, monkeypatch, failure,
):
    _, _, _, path, *_ = group
    prepared = plan(group)
    activated, written = CaptureConnection._activate, []

    def activate(conn):
        activated(conn)

        def writer(conn, operation):
            research_writer(conn, operation)
            written.append(operation['payload'].get('feature'))
            if written[-1] == 'deck' and failure == 'write':
                raise RuntimeError('simulated deck write failure')
        conn._capture_client.writer = writer

    monkeypatch.setattr(CaptureConnection, '_activate', activate)
    before = dump(path)
    with pytest.raises(RuntimeError if failure == 'write' else BackupCancelled):
        prepared.apply(cancelled=lambda: failure == 'cancel' and 'deck' in written)
    assert written == ['original_source', 'deck']
    assert dump(path) == before and not attached(path).journal.pending()
    monkeypatch.setattr(CaptureConnection, '_activate', activated)
    assert prepared.apply()['applied']
    assert not prepared.apply()['applied']


def test_pending_target_change_and_forged_plan_cannot_overwrite_research(group):
    _, _, _, path, *_ = group
    prepared = plan(group)
    with pytest.raises(ValueError, match='original prepared'):
        replace(prepared, replace=True).apply()
    client = attached(path)
    client.save(client.new_graph_operation('note', str(uuid4()),
        dict(paper_id=PAPER, body='New destination work')))
    before = dump(path)
    with pytest.raises(ValueError):
        prepared.apply()
    assert dump(path) == before


def test_repeated_decision_preserves_later_deletion_and_requires_explicit_restore(group):
    _, _, _, path, root, *_ = group
    request = str(uuid4())
    assert plan(group, request).apply()['applied']
    client = attached(path)
    client.save(client.new_graph_operation('research_file', root['entity_id'], {}, action='delete'))
    before = dump(path)
    assert not plan(group, request).apply()['applied'] and dump(path) == before
    with pytest.raises(ValueError, match='before replacement'):
        plan(group)
    restoring = plan(group, replace=True)
    assert restoring.comparison['state'] == 'retired'
    assert restoring.apply()['applied']
    assert saved(path, root)[1] == restoring.comparison['source']

@pytest.mark.parametrize('damage', ['asset', 'original', 'late_private_file'])
def test_incomplete_or_changed_file_inputs_never_publish_a_partial_deck(group, pair, damage):
    import hashlib

    from paper_daily.sync_blobs import BlobManifest

    _, _, _, path, root, _, sha, data, _ = group
    prepared = plan(group)
    if damage == 'asset':
        row = root['payload']['assets'][0]
        location = pair[3].store._path(BlobManifest(row['sha256'], row['size']))
        location.write_bytes(b'X' * row['size'])
    elif damage == 'original':
        pair[3].store._path(BlobManifest(sha, len(data))).unlink()
    else:
        with closing(_readonly_connection(path)) as conn:
            local = conn.execute('SELECT local_id FROM research_paper_identity WHERE sync_id=?',
                                 (PAPER,)).fetchone()[0]
        legacy = path.parent / 'presentations' / hashlib.sha256(local.encode()).hexdigest()[:24]
        legacy.mkdir(parents=True)
        (legacy / 'guide.json').write_text('Private unsaved import', encoding='utf-8')
    before = dump(path)
    with pytest.raises((OSError, ValueError)):
        prepared.apply()
    assert dump(path) == before and not attached(path).journal.pending()


@pytest.mark.parametrize('language,with_related', [('en', False), ('zh-TW', False), ('en', True)])
def test_native_review_compares_complete_deck_and_requires_one_confirmed_action(
    group, app, monkeypatch, language, with_related, request,
):
    from PySide6.QtWidgets import QMessageBox

    from paper_daily.desktop.workspace_dialog import WorkspaceDialog

    if with_related:
        related = request.getfixturevalue('related')
        group = related['group']
        assert add_related(related)['applied']
    old, source, _, path, root, *_ = group
    owner = WorkspaceDialog(old.journal.path, language=language)
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
        selected = next(row['change_id'] for row in ui.page['items']
                        if row['operation_id'] == root['operation_id'])
        for index in range(ui.rows.count()):
            ui.rows.setCurrentRow(index)
            if ui.selected() == selected:
                break
        assert ui.compare()
        wait(app, lambda: not owner.busy)
        assert ui.action_select.currentData() == 'deck_group', owner.status.text()
        if language == 'zh-TW':
            assert '\u7c21\u5831' in ui.action_select.currentText()
        assert 'Speaker explanation' in ui.old.toPlainText()
        assert 'Editable' in ui.old.toPlainText()
        assert 'Reference' in ui.old.toPlainText()
        assert 'Cell evidence | 50' in ui.old.toPlainText()
        assert 'Caption one' in ui.old.toPlainText()
        assert 'https://example.org/paper' in ui.old.toPlainText()
        if with_related:
            assert 'Related controlled comparison' in ui.old.toPlainText()
        before = dump(path)
        monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.No)
        ui.copy_button.click()
        assert dump(path) == before and not owner.busy
        monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Yes)
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        expected = 4 if with_related else 2
        assert len(attached(path).journal.pending()) == expected, owner.status.text()
        assert saved(path, root)[1]['deck']['slides'][0]['speaker_notes'] == 'Speaker explanation'
        assert not ui.copy_button.isEnabled()
    finally:
        if owner.busy:
            owner.cancel()
            wait(app, lambda: not owner.busy)
        owner.close()
        app.processEvents()

def test_installed_file_change_after_activation_rolls_back_the_whole_decision(group, monkeypatch):
    from paper_daily import sync_artifacts

    _, _, _, path, *_ = group
    prepared = plan(group)
    activate = sync_artifacts.activate

    def damaged(conn, operation, directory):
        result = activate(conn, operation, directory)
        (directory / 'deck.json').write_text('Changed after activation', encoding='utf-8')
        return result

    monkeypatch.setattr(sync_artifacts, 'activate', damaged)
    before = dump(path)
    with pytest.raises(ValueError, match='files changed before recovery committed'):
        prepared.apply()
    assert dump(path) == before and not attached(path).journal.pending()

@pytest.fixture
def related(group, pair, tmp_path):
    import hashlib

    import pymupdf
    from test_sync_files import paper_payload

    from paper_daily.sync_blobs import BlobManifest
    from paper_daily.sync_documents import desired_document
    from paper_daily.sync_files import canonical_json, descriptor, read_json
    from paper_daily.sync_source_files import publish

    old, previous, _, path, previous_root, service, sha, data, token = group
    other = '22222222-2222-4222-8222-222222222222'
    parent = old.new_graph_operation('paper', other, {
        **paper_payload(), 'title': 'Related controlled comparison',
    })
    old.save(parent)
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 60), 'Related experiment observed 75 participants')
        content = pdf.tobytes()
    digest = hashlib.sha256(content).hexdigest()
    original = tmp_path / 'related-original.pdf'
    original.write_bytes(content)
    document = old.new_graph_operation('paper_document', other, dict(
        paper_id=other, sha256=digest, size=len(content), media_type='application/pdf',
    ))
    old.save(document)
    publish(old, other, original, document_hash=digest,
        parent_incarnation=parent['incarnation'], store=pair[3].store,
        version_root=pair[3].root, request_id='related-original')
    with old.journal.transaction() as conn:
        document = desired_document(conn, other)
    payload = deepcopy(previous_root['payload'])
    payload['input_versions'].update(schema_version=2, workspace_id='workspace')
    payload['input_versions']['documents'] = [{key: document[key] for key in (
        'paper_id', 'operation_id', 'incarnation', 'parent_incarnation', 'sha256',
    )}]
    body = read_json(pair[3].store._path(BlobManifest(
        payload['body']['sha256'], payload['body']['size'],
    )).read_bytes())
    body['deck']['sources'].append(dict(id='related:1', label='Related experiment',
        kind='original', page=1, document_hash=digest,
        text='Related experiment observed 75 participants'))
    body['deck']['slides'][0]['sources'].append('related:1')
    raw = canonical_json(body)
    payload['body'] = descriptor(raw, 'application/json')
    stage_bytes(pair[3].store, {payload['body']['sha256']: raw})
    root = old.new_graph_operation('research_file', previous_root['entity_id'], payload)
    old.save(root)
    source = candidates.prepare(old.journal.path, previous.snapshot, previous.workspace)
    rows = source.page()['items']
    change = next(r['change_id'] for r in rows if r['operation_id'] == root['operation_id'])
    parent_change = next(r['change_id'] for r in rows
                         if r['operation_id'] == parent['operation_id'])
    return dict(group=(old, source, change, path, root, service, sha, data, token),
                parent=parent, parent_change=parent_change, document=document,
                sha=digest, data=content, original=original)


def add_related(related):
    from paper_daily import sync_recovery_choices

    _, source, _, path, *_ = related['group']
    return sync_recovery_choices.prepare(target.observe(source, path), related['parent_change'],
                                        'add', str(uuid4())).apply()


def test_related_original_uses_its_proven_paper_and_reaches_an_independent_native_peer(
    related, tmp_path_factory, pair,
):
    from test_workspace_sync import Native

    from paper_daily.workspace_service import Ticket
    from paper_daily.workspace_sync import SyncSession

    group = related['group']
    old, source, change, path, root, service, _, _, token = group
    before = dump(path)
    with pytest.raises(ValueError, match='parent must already exist') as blocked:
        plan(group)
    assert 'Related controlled comparison' in str(blocked.value)
    assert dump(path) == before and not attached(path).journal.pending()
    assert add_related(related)['applied']
    request = str(uuid4())
    prepared = plan(group, request)
    owner = next(r for r in prepared.comparison['original_owners']
                 if r['sha256'] == related['sha'])
    assert owner['source_parent'] == dict(kind='paper', id=related['parent']['entity_id'],
                                         incarnation=related['parent']['incarnation'])
    assert owner['target_parent']['incarnation'] != owner['source_parent']['incarnation']
    old_bytes = dump(old.journal.path)
    assert prepared.apply()['applied']
    assert dump(old.journal.path) == old_bytes
    client = attached(path)
    pending = client.journal.pending()
    assert [o['entity_type'] for o in pending] == ['paper'] + ['research_file'] * 3
    original = next(o for o in pending if o['payload'].get('slot') == related['sha'])
    assert original['payload']['paper_id'] == related['parent']['entity_id']
    assert original['parents'] == [owner['target_parent']]
    with closing(_readonly_connection(path)) as conn:
        store, version_root = _inspection_paths(conn)
    transfer = FileTransfers(client, BlobStore(store.root), service,
        origin='https://recovery.fixture.invalid', token=token, version_root=version_root)
    try:
        for item in pending:
            if item['entity_type'] == 'research_file':
                drain(lambda item=item: transfer.upload(item), 'uploaded')
        result = client.sync_once(service, token, prepare_push=transfer.ready_to_push)
        assert result['pending'] == result['conflicts'] == 0
    finally:
        transfer.close()
    tokens, enroll = {}, service.enroll

    def capture(workspace, device):
        tokens[device] = enroll(workspace, device)
        return tokens[device]

    service.enroll = capture
    try:
        other = peer(path, service, tmp_path_factory)
    finally:
        service.enroll = enroll
    travel = SyncSession(other, transport_factory=lambda url: Native(url, service, []))
    travel.connect('https://recovery.fixture.invalid', 'fresh-research', 'original-group-peer',
                   tokens['original-group-peer'], Ticket())
    try:
        result = travel.prepare_offline(['sync:' + related['parent']['entity_id']], Ticket())
        assert result['attachments']['failed'] == 0
    finally:
        travel.disconnect()
    from test_sync_recovery_positioned_note import source_file

    assert source_file(other, related['sha'], len(related['data'])).read_bytes() == related['data']
    assert saved(other, root)[1] == saved(path, root)[1]
    client.save(client.new_graph_operation('research_file', original['entity_id'], {},
                                          action='delete'))
    later = dump(path)
    assert not plan(group, request).apply()['applied'] and dump(path) == later
    with pytest.raises(ValueError, match='source restoration'):
        plan(group, replace=True).apply()
    assert dump(path) == later
    from paper_daily.sync_blobs import BlobManifest

    pair[3].store._path(BlobManifest(related['sha'], len(related['data']))).unlink()
    assert not plan(group, request).apply()['applied'] and dump(path) == later


@pytest.mark.parametrize('damage', ['wrong_epoch', 'foreign_workspace', 'ambiguous_hash'])
def test_unproved_related_input_never_relabels_or_publishes_originals(related, damage):
    old, previous, _, path, root, service, sha, data, token = related['group']
    payload = deepcopy(root['payload'])
    ref = payload['input_versions']['documents'][0]
    if damage == 'wrong_epoch':
        ref['incarnation'] = 'wrong-document-epoch'
    elif damage == 'foreign_workspace':
        payload['input_versions']['workspace_id'] = 'another-workspace'
    else:
        operation = old.new_graph_operation('paper_document', ref['paper_id'], dict(
            paper_id=ref['paper_id'], sha256=sha, size=len(data), media_type='application/pdf',
        ))
        old.save(operation)
        ref.update(operation_id=operation['operation_id'], incarnation=operation['incarnation'],
                   sha256=sha)
    operation = old.new_graph_operation('research_file', root['entity_id'], payload)
    old.save(operation)
    source = candidates.prepare(old.journal.path, previous.snapshot, previous.workspace)
    change = next(r['change_id'] for r in source.page()['items']
                  if r['operation_id'] == operation['operation_id'])
    group = old, source, change, path, operation, service, sha, data, token
    before = dump(path)
    with pytest.raises(ValueError, match={
        'wrong_epoch': 'retained native operation', 'foreign_workspace': 'workspace mapping',
        'ambiguous_hash': 'ambiguous recorded paper owners',
    }[damage]):
        plan(group)
    assert dump(path) == before and not attached(path).journal.pending()


def test_root_only_legacy_receipt_retries_after_bytes_are_lost_but_rejects_wrong_native_type(
    group, pair,
):
    import hashlib
    import json
    import sqlite3

    from paper_daily.sync_blobs import BlobManifest

    _, _, _, path, root, *_ = group
    request = str(uuid4())
    assert plan(group, request).apply()['applied']

    def rewrite(change):
        with closing(sqlite3.connect(path)) as conn, conn:
            value = json.loads(conn.execute('SELECT result FROM integration_operations WHERE id=?',
                                           (request,)).fetchone()[0])
            change(value)
            raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            conn.execute('UPDATE integration_operations SET result=?,fingerprint=? WHERE id=?',
                         (raw, hashlib.sha256(raw.encode()).hexdigest(), request))

    def old_shape(value):
        for ref in value['originals']:
            ref.pop('source_parent')
            ref.pop('target_parent')

    rewrite(old_shape)
    asset = root['payload']['assets'][0]
    pair[3].store._path(BlobManifest(asset['sha256'], asset['size'])).unlink()
    before = dump(path)
    assert not plan(group, request).apply()['applied'] and dump(path) == before

    def wrong_type(value):
        value['originals'][0] = dict(value['native'])

    rewrite(wrong_type)
    before = dump(path)
    with pytest.raises(ValueError, match='another native content type'):
        plan(group, request)
    assert dump(path) == before
