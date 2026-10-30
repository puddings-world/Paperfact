"""Real two-peer retained analysis conflicts rebuild exact-source local highlight groups."""
import copy
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from test_highlight_generation import QUOTES
from test_research_generation import rows
from test_sync_transfers import attach, send
from test_sync_transfers import setup as transfer_setup_fixture
from test_workspace_sync_files import enable

from paper_daily import (
    llm,
    manual_highlight_ops,
    paper_highlights,
    pdf_highlights,
    store,
    sync_capture,
    sync_recovery,
)
from paper_daily import research_generation as generation
from paper_daily.document_reader import from_workspace
from paper_daily.research_question_jobs import _pages
from paper_daily.research_review import ResearchReview
from paper_daily.sync_content import content_id

transfer_setup = transfer_setup_fixture
STAMP = '2026-10-30T00:00:00+00:00'


@pytest.fixture
def remote_options(request):
    return getattr(request, 'param', {})


def save(client, scope, data):
    payload = {'scope': scope, 'feature': 'highlight_analysis', 'key': 'main',
               'source_document_hash': data['document_hash'], 'data': data}
    operation = client.new_graph_operation(
        'research_content', content_id(scope, 'highlight_analysis', 'main'), payload)
    client.save(operation)
    return operation


@pytest.fixture
def world(transfer_setup, tmp_path, monkeypatch, remote_options):
    a, b, authority, ta, tb, _stores, transfers, _actions, portable = transfer_setup
    operation, _manifest, _data = attach(transfer_setup, tmp_path, text=QUOTES[0])
    send(transfer_setup, operation)
    for _ in range(8):
        if transfers[1].download(portable)['state'] == 'bound':
            break
    else:
        pytest.fail('Fixture PDF did not bind')
    enable(a)
    enable(b)
    with b.journal.transaction() as conn:
        owner = conn.execute('SELECT local_id FROM research_paper_identity WHERE sync_id=?',
                             (portable,)).fetchone()[0]
    document = from_workspace(b.journal.path).resolve(owner)
    assert document.available
    data = {
        'body_json': {'items': [
            {'text': QUOTES[0], 'page': 1, 'kind': 'evidence', 'reason': 'Original reason',
             'source': 'page:1'}],
            'coverage': {'pages': 1, 'empty_pages': [], 'chunks': 1, 'has_page_numbers': True}},
        'source_hash': paper_highlights._hash(_pages(document)),
        'document_hash': document.sha256, 'written_at': STAMP,
    }
    scope = {'kind': 'paper', 'id': portable}
    save(a, scope, data)
    a.sync_once(authority, ta)
    b.sync_once(authority, tb)
    current = copy.deepcopy(data)
    current['body_json']['items'][0]['reason'] = 'Canonical reason'
    incoming = copy.deepcopy(data)
    incoming['body_json']['items'][0]['reason'] = 'Retained reason'
    if remote_options.get('unknown_source'):
        incoming['document_hash'] = None
    if remote_options.get('wrong_source'):
        incoming['document_hash'] = 'f' * 64
    if remote_options.get('wrong_text_hash'):
        incoming['source_hash'] = 'e' * 64
    if remote_options.get('unlocated'):
        incoming['body_json']['items'][0]['text'] = 'This full sentence never appears in the PDF.'
    if remote_options.get('empty'):
        incoming['body_json']['items'] = []
    save(a, scope, current)
    save(b, scope, incoming)
    a.sync_once(authority, ta)
    b.sync_once(authority, tb)
    a.sync_once(authority, ta)
    review = ResearchReview(b.journal.path)
    item = next(item for item in review.page()['items'] if item['origin'] == 'remote')
    monkeypatch.setattr(llm, 'complete_result', lambda *a, **k: pytest.fail('Review called AI'))
    monkeypatch.setattr(llm, 'capture_connections', lambda: pytest.fail('Review read AI accounts'))
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'different-global.sqlite')
    return SimpleNamespace(a=a, b=b, authority=authority, ta=ta, tb=tb, scope=scope,
                           owner=owner, document=document, data=data, incoming=incoming,
                           review=review, identity=item['id'], stores=_stores)


def state(world):
    path = world.b.journal.path
    return (rows(path, 'SELECT * FROM paper_highlight_analysis'),
            rows(path, 'SELECT * FROM pdf_ai_highlights'),
            rows(path, 'SELECT * FROM pdf_highlights'), world.b.journal.pending(1000))


def receipt_count(world):
    with closing(sqlite3.connect(world.b.journal.path)) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_review_receipts'").fetchone()
        if not exists:
            return 0
        return conn.execute('SELECT count(*) FROM research_review_receipts').fetchone()[0]


def test_actual_two_peer_remote_analysis_becomes_complete_source_group_once(world):
    shown = world.review.preview('remote', world.identity)
    assert shown.data['apply'] and not shown.data['editable']
    group = shown.data['retained']
    assert len(group['marks']) == 1 and group['unmatched'] == []
    assert group['marks'][0]['quote'] == QUOTES[0]
    assert group['analysis']['document_hash'] == world.document.sha256
    before = len(world.b.journal.pending())
    result = world.review.decide(shown, request_id='remote-group')
    assert result == {'decision': 'applied', 'operation_id': 'remote-group'}
    assert len(world.b.journal.pending()) == before + 2
    saved = state(world)
    assert json.loads(saved[0][0]['body_json'])['items'][0]['reason'] == 'Retained reason'
    assert saved[1][0]['quote'] == QUOTES[0] and saved[1][0]['reason'] == 'Retained reason'
    assert world.review.decide(shown, request_id='remote-group') == result
    assert state(world) == saved and receipt_count(world) == 1
    world.b.sync_once(world.authority, world.tb)
    world.a.sync_once(world.authority, world.ta)
    assert world.b.status()['conflicts'] == 0
    assert rows(world.a.journal.path, 'SELECT reason FROM pdf_ai_highlights') == [
        {'reason': 'Retained reason'}]
    assert rows(world.a.journal.path, 'SELECT body_json FROM paper_highlight_analysis') == [
        {'body_json': saved[0][0]['body_json']}]


@pytest.mark.parametrize('remote_options', [
    {'unknown_source': True}, {'wrong_source': True}, {'wrong_text_hash': True},
    {'unlocated': True}, {'empty': True},
], indirect=True)
def test_unknown_or_incomplete_source_stays_read_only_and_exportable(world):
    shown = world.review.preview('remote', world.identity)
    assert not shown.data['apply'] and not shown.data['editable']
    assert 'complete grouped source review' in shown.data['reason']
    before = state(world)
    exported = world.review.export_text(shown)
    assert str(world.b.journal.path) not in exported and str(world.document.path) not in exported
    if world.incoming['body_json']['items']:
        assert world.incoming['body_json']['items'][0]['text'] in exported
    with pytest.raises(ValueError, match='complete grouped source review'):
        world.review.decide(shown, request_id='no-authority')
    assert state(world) == before
    result = world.review.decide(shown, keep=True, request_id='keep-unsupported')
    assert result['decision'] == 'kept'
    assert state(world) == before


def add_curated_marks(world):
    path = world.b.journal.path
    body = world.data['body_json']
    fingerprint, located, unmatched = pdf_highlights.locate(world.document.path, body)
    assert fingerprint == world.document.sha256 and not unmatched
    key, anchor, item = located[0]
    with closing(generation._connect(path)) as conn:
        observed = sync_capture.observe_target(conn, 'paper', world.owner, 'ai_highlight',
                                               fingerprint + ':' + key)
        with sync_capture.expecting(conn, [observed]):
            conn.execute(
                'INSERT INTO pdf_ai_highlights(paper_id,document_hash,source_key,analysis_hash,'
                'anchor,quote,reason,hidden) VALUES(?,?,?,?,?,?,?,1)',
                (world.owner, fingerprint, key, world.data['source_hash'],
                 json.dumps(anchor), item['text'], 'Curated hidden reason'))
            conn.commit()
    owner = manual_highlight_ops.capture_owner(path, world.owner)
    view = manual_highlight_ops.load(owner, world.document.path, world.document.sha256,
                                     document=world.document)
    manual_highlight_ops.add(view, anchor, item['text'])
    return key


def test_remote_group_preserves_hidden_preferences_and_manual_marks(world):
    add_curated_marks(world)
    before = rows(world.b.journal.path, 'SELECT * FROM pdf_highlights')
    shown = world.review.preview('remote', world.identity)
    assert shown.data['apply'] and shown.data['retained']['marks'][0]['hidden'] == 1
    world.review.decide(shown, request_id='keep-user-choices')
    assert rows(world.b.journal.path, 'SELECT * FROM pdf_highlights') == before
    assert rows(world.b.journal.path, 'SELECT hidden FROM pdf_ai_highlights') == [{'hidden': 1}]


def test_preview_cancel_and_keep_do_not_create_companion_writes(world):
    before = state(world)
    shown = world.review.preview('remote', world.identity)
    assert state(world) == before
    exported = world.review.export_text(shown)
    assert QUOTES[0] in exported and str(world.document.path) not in exported
    assert world.review.decide(shown, keep=True, request_id='cancel-group')['decision'] == 'kept'
    assert state(world) == before
    assert world.review.decide(shown, keep=True, request_id='cancel-group')['decision'] == 'kept'


@pytest.mark.parametrize('late', ['parent', 'mark'])
def test_late_current_edits_reject_the_displayed_base_without_partial_application(world, late):
    add_curated_marks(world)
    shown = world.review.preview('remote', world.identity)
    with closing(generation._connect(world.b.journal.path)) as conn:
        if late == 'parent':
            conn.execute('UPDATE papers SET title=? WHERE id=?', ('New paper title', world.owner))
        else:
            current = rows(world.b.journal.path, 'SELECT * FROM pdf_ai_highlights')[0]
            observed = sync_capture.observe_target(
                conn, 'paper', world.owner, 'ai_highlight',
                current['document_hash'] + ':' + current['source_key'])
            with sync_capture.expecting(conn, [observed]):
                conn.execute('UPDATE pdf_ai_highlights SET hidden=0 WHERE paper_id=?',
                             (world.owner,))
        conn.commit()
    before = state(world)
    with pytest.raises(ValueError, match='changed'):
        world.review.decide(shown, request_id='late-' + late)
    assert state(world) == before and receipt_count(world) == 0


def test_receipt_failure_rolls_back_analysis_marks_resolution_intent_and_outbox(world, monkeypatch):
    shown = world.review.preview('remote', world.identity)
    before = state(world)
    original = world.review._receipt

    def fail(*args):
        original(*args)
        raise sqlite3.OperationalError('Fixture receipt failure')

    monkeypatch.setattr(world.review, '_receipt', fail)
    with pytest.raises(sqlite3.OperationalError, match='receipt failure'):
        world.review.decide(shown, request_id='rollback-group')
    assert state(world) == before and receipt_count(world) == 0
    assert rows(world.b.journal.path, 'SELECT * FROM research_resolution_intents') == []
    monkeypatch.setattr(world.review, '_receipt', original)
    assert world.review.decide(shown, request_id='rollback-group')['decision'] == 'applied'


def test_complete_group_and_receipt_source_closure_survive_detached_backup(world, tmp_path):
    shown = world.review.preview('remote', world.identity)
    world.review.decide(shown, request_id='before-backup')
    package = tmp_path / 'review.zip'
    sync_recovery.create(world.b.journal.path, package, blob_store=world.stores[1])
    manifest = sync_recovery.inspect(package)
    assert world.document.sha256 in {source['sha256'] for source in manifest['blobs']}
    destination = tmp_path / 'detached'
    sync_recovery.restore_detached(package, destination)
    restored = destination / 'papers.db'
    assert rows(restored, 'SELECT * FROM pdf_ai_highlights') == state(world)[1]
    records = rows(restored,
                   "SELECT data FROM recovery_records WHERE table_name='research_review_receipts'")
    assert len(records) == 1
    provenance = json.loads(json.loads(records[0]['data'])['provenance'])
    assert provenance['source_document_hash'] == world.document.sha256


def test_remote_analysis_restoration_requires_same_paper_choice_and_confirmation(world):
    identity = content_id(world.scope, 'highlight_analysis', 'main')
    deletion = world.b.new_graph_operation('research_content', identity, {}, action='delete')
    world.b.save(deletion)
    world.b.sync_once(world.authority, world.tb)
    shown = world.review.preview('remote', world.identity)
    assert not shown.data['apply'] and 'restore' in shown.data['reason']
    title = rows(world.b.journal.path, 'SELECT title FROM papers')[0]['title']
    assert world.review.targets(shown)['items'] == [{'id': world.owner, 'title': title}]
    other = world.review.target_preview(shown, 'another-paper')
    assert not other.data['apply'] and 'another paper' in other.data['reason']
    confirmed = world.review.target_preview(shown, world.owner)
    assert confirmed.data['apply'] and confirmed.data['requires_confirmation']
    before = state(world)
    with pytest.raises(ValueError, match='Confirm'):
        world.review.decide(confirmed, request_id='revive-analysis')
    assert state(world) == before
    world.review.decide(confirmed, request_id='revive-analysis', confirm_target=True)
    resolution = next(op for op in world.b.journal.pending()
                      if op['operation_id'] == 'revive-analysis')
    assert resolution['incarnation'] == 'revive-analysis'
    incoming = confirmed.data['expected']['remote']['event']['operation']
    assert resolution['resolution_of'] == incoming['operation_id']
    assert len(rows(world.b.journal.path, 'SELECT * FROM pdf_ai_highlights')) == 1
    world.b.sync_once(world.authority, world.tb)
    world.a.sync_once(world.authority, world.ta)
    assert world.b.status()['conflicts'] == 0


def test_deleted_companion_requires_explicit_restore_and_keeps_manual_layer(world):
    key = add_curated_marks(world)
    world.b.sync_once(world.authority, world.tb)
    entity = content_id(world.scope, 'ai_highlight', world.document.sha256 + ':' + key)
    deletion = world.b.new_graph_operation('research_content', entity, {}, action='delete')
    world.b.save(deletion)
    world.b.sync_once(world.authority, world.tb)
    before = rows(world.b.journal.path, 'SELECT * FROM pdf_highlights')
    shown = world.review.preview('remote', world.identity)
    assert not shown.data['apply'] and 'restore' in shown.data['reason']
    confirmed = world.review.target_preview(shown, world.owner)
    world.review.decide(confirmed, request_id='revive-mark', confirm_target=True)
    mark = next(op for op in world.b.journal.pending() if op['entity_id'] == entity)
    assert mark['incarnation'] == mark['operation_id'] != deletion['incarnation']
    assert rows(world.b.journal.path, 'SELECT * FROM pdf_highlights') == before


@pytest.mark.parametrize('change', ['source', 'parent', 'mark'])
def test_reentrant_change_after_resolution_rolls_back_complete_group(world, monkeypatch, change):
    from paper_daily.sync_client import SyncClient

    add_curated_marks(world)
    shown = world.review.preview('remote', world.identity)
    before = state(world)
    original = SyncClient.resolve_conflict_in

    def intervene(client, conn, *args, **kwargs):
        result = original(client, conn, *args, **kwargs)
        if change == 'source':
            world.document.path.chmod(0o600)
            world.document.path.write_bytes(b'Changed PDF after remote resolution')
        elif change == 'parent':
            conn.execute('UPDATE papers SET title=? WHERE id=?', ('Reentrant title', world.owner))
        else:
            conn.execute('UPDATE pdf_ai_highlights SET hidden=0 WHERE paper_id=?', (world.owner,))
        return result

    monkeypatch.setattr(SyncClient, 'resolve_conflict_in', intervene)
    with pytest.raises(ValueError, match='changed'):
        world.review.decide(shown, request_id='reentrant-' + change)
    assert state(world) == before and receipt_count(world) == 0
    assert rows(world.b.journal.path, 'SELECT * FROM research_resolution_intents') == []


def test_new_selected_pdf_after_preview_cannot_be_substituted(world, transfer_setup, tmp_path):
    shown = world.review.preview('remote', world.identity)
    operation, _manifest, _data = attach(transfer_setup, tmp_path, request_id='replacement',
                                       text=QUOTES[1])
    send(transfer_setup, operation)
    for _ in range(8):
        if transfer_setup[6][1].download(world.scope['id'])['state'] == 'bound':
            break
    else:
        pytest.fail('Replacement fixture PDF did not bind')
    before = state(world)
    with pytest.raises(ValueError, match='original verified PDF'):
        world.review.decide(shown, request_id='late-document')
    assert state(world) == before and receipt_count(world) == 0
    fresh = world.review.preview('remote', world.identity)
    assert not fresh.data['apply'] and 'original verified PDF' in fresh.data['reason']


def test_late_receipt_mark_change_is_rolled_back_and_same_request_can_retry(world, monkeypatch):
    shown = world.review.preview('remote', world.identity)
    before = state(world)
    original = world.review._receipt

    def mutate(conn, *args):
        original(conn, *args)
        conn.execute('UPDATE pdf_ai_highlights SET reason=? WHERE paper_id=?',
                     ('Reentrant mark rewrite', world.owner))

    monkeypatch.setattr(world.review, '_receipt', mutate)
    with pytest.raises(ValueError, match='Highlight group changed'):
        world.review.decide(shown, request_id='late-receipt')
    assert state(world) == before and receipt_count(world) == 0
    monkeypatch.setattr(world.review, '_receipt', original)
    assert world.review.decide(shown, request_id='late-receipt')['decision'] == 'applied'


def test_real_review_ui_cancel_target_and_rapid_apply_preserve_parent_draft(world, monkeypatch):
    from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QWidget
    from test_review_dialog import wait

    from paper_daily.desktop import review_dialog

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    editor = QLineEdit('Unsent research question', parent)
    dialog = review_dialog.ReviewDialog(world.b.journal.path, parent, language='en')
    dialog.show()
    try:
        wait(app, lambda: dialog.preview is not None)
        assert dialog.target_button.isEnabled() and dialog.draft.isReadOnly()
        before = state(world)
        monkeypatch.setattr(review_dialog.TargetDialog, 'exec',
                            lambda _: QDialog.DialogCode.Rejected)
        dialog.target_button.click()
        assert state(world) == before
        for _ in range(20):
            dialog.apply.click()
        wait(app, lambda: not dialog.busy)
        assert receipt_count(world) == 1
        assert len(world.b.journal.pending()) == len(before[3]) + 2
        assert editor.text() == 'Unsent research question'
        assert not dialog.apply.isEnabled()
    finally:
        dialog.close()
        parent.close()
        dialog.deleteLater()
        parent.deleteLater()
        app.processEvents()


def test_companion_write_failure_rolls_back_remote_resolution_then_retries(world):
    shown = world.review.preview('remote', world.identity)
    with sqlite3.connect(world.b.journal.path) as conn:
        conn.execute("CREATE TRIGGER reject_remote_mark BEFORE INSERT ON pdf_ai_highlights "
                     "BEGIN SELECT RAISE(ABORT,'Fixture mark storage failure'); END")
    before = state(world)
    with pytest.raises(sqlite3.DatabaseError, match='mark storage failure'):
        world.review.decide(shown, request_id='mark-retry')
    assert state(world) == before and receipt_count(world) == 0
    assert rows(world.b.journal.path, 'SELECT * FROM research_resolution_intents') == []
    with sqlite3.connect(world.b.journal.path) as conn:
        conn.execute('DROP TRIGGER reject_remote_mark')
    assert world.review.decide(shown, request_id='mark-retry')['decision'] == 'applied'
