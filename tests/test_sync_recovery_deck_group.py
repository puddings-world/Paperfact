"""Whole-deck recovery retains editable bytes, owned originals and one decision."""

from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from test_sync_device_recovery import dump
from test_sync_files import PAPER, drain
from test_sync_recovery_note_original_group import group as _original_group
from test_sync_recovery_note_original_group import peer
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


@pytest.mark.parametrize('language', ['en', 'zh-TW'])
def test_native_review_compares_complete_deck_and_requires_one_confirmed_action(
    group, app, monkeypatch, language,
):
    from PySide6.QtWidgets import QMessageBox

    from paper_daily.desktop.workspace_dialog import WorkspaceDialog

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
        assert 'Speaker explanation' in ui.old.toPlainText()
        assert 'Editable' in ui.old.toPlainText()
        assert 'Reference' in ui.old.toPlainText()
        assert 'Cell evidence | 50' in ui.old.toPlainText()
        assert 'Caption one' in ui.old.toPlainText()
        assert 'https://example.org/paper' in ui.old.toPlainText()
        before = dump(path)
        monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.No)
        ui.copy_button.click()
        assert dump(path) == before and not owner.busy
        monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Yes)
        ui.copy_button.click()
        ui.copy_button.click()
        wait(app, lambda: not owner.busy)
        assert len(attached(path).journal.pending()) == 2, owner.status.text()
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
