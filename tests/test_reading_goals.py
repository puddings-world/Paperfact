"""Per-list goals remain user-owned through local edits, sync and research packages."""
import json
import sqlite3
import zipfile

import pytest
from test_sync_capture import bound as bound_fixture
from test_sync_capture import make, seed

from paper_daily import bundle, store, sync_capture, sync_content, sync_recovery
from paper_daily import reading_goals as goals
from paper_daily import research_generation as generation
from paper_daily.sync_service import ReferenceService

bound = bound_fixture


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    path = tmp_path / 'papers.db'
    monkeypatch.setattr(store, 'DB_PATH', path)
    monkeypatch.setattr(store, 'ensure_dirs', lambda: None)
    monkeypatch.setattr(bundle, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(bundle, 'PDF_DIR', tmp_path / 'pdf')
    with store.connect() as conn:
        conn.executescript(store.SCHEMA)
        conn.execute("INSERT INTO lists VALUES('list','Research','Original description',?)",
                     ('2026-10-30T00:00:00+00:00',))
        store.upsert_papers(conn, [{'id':'paper', 'title':'Paper', 'year':2026,
                                   'venue':'Fixture', 'source':'fixture'}])
        conn.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                     "VALUES('list','paper',0,?)", ('2026-10-30T00:00:00+00:00',))
        conn.execute("INSERT INTO notes(paper_id,body,created_at) VALUES('paper','Keep',?)",
                     ('2026-10-30T00:00:00+00:00',))
    return path


def row(path):
    with sqlite3.connect(path) as conn:
        return conn.execute('SELECT list_id,body,written_at FROM list_reading_goals').fetchone()


def test_edit_reload_clear_preserves_description_notes_and_other_research(legacy):
    observed=goals.load(legacy,'list')
    assert goals.text(observed)==''
    assert goals.save(observed,'Compare assumptions; read methods in depth').status=='accepted'
    assert goals.text(goals.load(legacy,'list'))=='Compare assumptions; read methods in depth'
    assert goals.save(goals.load(legacy,'list'),'').status=='accepted'
    assert row(legacy)[1]==''
    with sqlite3.connect(legacy) as conn:
        assert conn.execute('SELECT note FROM lists').fetchone()[0]=='Original description'
        assert conn.execute('SELECT body FROM notes').fetchone()[0]=='Keep'


def test_repeated_save_uses_same_receipt_and_stale_edit_is_retained(legacy):
    original=goals.load(legacy,'list')
    first=goals.save(original,'Goal A')
    assert goals.save(original,'Goal A')==first
    stale=goals.save(original,'Goal B')
    assert stale.status=='candidate' and row(legacy)[1]=='Goal A'
    assert goals.save(original,'Goal B')==stale
    with sqlite3.connect(legacy) as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_generation_requests").fetchone()[0]==2


def test_old_observation_cannot_write_to_deleted_recreated_or_replaced_list(legacy):
    observed=goals.load(legacy,'list')
    with store.connect() as conn:
        conn.execute("DELETE FROM lists WHERE id='list'")
        conn.execute("INSERT INTO lists VALUES('list','Replacement','',?)",
                     ('2026-10-31T00:00:00+00:00',))
    assert goals.save(observed,'Old purpose').status=='candidate'
    assert row(legacy) is None


@pytest.mark.parametrize('body',[None,42,'x'*2001])
def test_invalid_goal_is_rejected_without_publishing(legacy,body):
    with pytest.raises(ValueError):
        goals.save(goals.load(legacy,'list'),body)
    assert row(legacy) is None


def test_goal_is_list_scoped_and_has_no_pdf_provenance():
    payload={'scope':{'kind':'list','id':'list'}, 'feature':'reading_goal','key':'main',
             'source_document_hash':None,
             'data':{'body':'Human purpose','written_at':'2026-10-30T00:00:00+00:00'}}
    sync_content.validate_payload(payload)
    payload['source_document_hash']='a'*64
    with pytest.raises(ValueError):
        sync_content.validate_payload(payload)


def test_actual_captured_goal_reaches_peer_and_conflict_keeps_both(bound,tmp_path):
    seed()
    a=bound
    b=make(tmp_path/'b.sqlite','b')
    service=ReferenceService(tmp_path/'authority.sqlite')
    ta,tb=service.enroll('workspace','a'),service.enroll('workspace','b')
    assert goals.save(goals.load(a.journal.path,'list'),'Initial question').status=='accepted'
    a.sync_once(service,ta)
    b.sync_once(service,tb)
    with generation._connect(b.journal.path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        sync_capture.install(conn, workspace_id='workspace', device_id='b')
    assert row(b.journal.path)[1]=='Initial question'
    left,right=goals.load(a.journal.path,'list'),goals.load(b.journal.path,'list')
    assert goals.save(left,'Desktop purpose').status=='accepted'
    assert goals.save(right,'Offline laptop purpose').status=='accepted'
    a.sync_once(service,ta)
    b.sync_once(service,tb)
    a.sync_once(service,ta)
    assert b.status()['conflicts']>0
    assert 'Desktop purpose' in row(a.journal.path)[1]
    conflicts = b.history(conflicts_only=True)
    assert any(event['operation']['payload'].get('data', {}).get('body') ==
               'Offline laptop purpose' for event in conflicts)
    assert row(b.journal.path)[1] == 'Desktop purpose'


def test_bundle_export_import_goal_uses_capability_version_and_preserves_local_by_default(
    legacy,tmp_path,
):
    assert goals.save(goals.load(legacy,'list'),'Purpose from sharer').status=='accepted'
    archive=tmp_path/'research.zip'
    bundle.export('list',archive)
    with zipfile.ZipFile(archive) as z:
        assert json.loads(z.read('manifest.json'))['format']==2
        shared = json.loads(z.read('tables.json'))['list_reading_goals'][0]
        assert shared['body'] == 'Purpose from sharer'
    assert goals.save(goals.load(legacy,'list'),'Keep local purpose').status=='accepted'
    bundle.import_(archive,pdfs=False)
    assert row(legacy)[1]=='Keep local purpose'
    bundle.import_(archive,replace=True,pdfs=False)
    assert row(legacy)[1]=='Purpose from sharer'


def test_recovery_preserves_goal_in_independent_detached_copy(legacy,tmp_path):
    assert goals.save(goals.load(legacy,'list'),'Portable research question').status=='accepted'
    archive=tmp_path/'backup.zip'
    sync_recovery.create(legacy,archive)
    dest=tmp_path/'restored'
    sync_recovery.restore_detached(archive,dest)
    assert row(dest/'papers.db')[1]=='Portable research question'
    assert row(legacy)[1]=='Portable research question'


@pytest.mark.parametrize('captured', [False, True])
def test_deleted_list_does_not_give_its_old_goal_to_a_recreated_id(
    legacy, tmp_path, captured,
):
    if captured:
        client = make(legacy)
        with generation._connect(legacy) as conn:
            conn.execute('BEGIN IMMEDIATE')
            sync_capture.install(conn, workspace_id='workspace', device_id='a')
            sync_capture.capture_existing(conn)
    goals.save(goals.load(legacy, 'list'), 'Purpose of the original list')
    with store.connect() as conn:
        conn.execute("DELETE FROM lists WHERE id='list'")
    assert row(legacy) is None
    if captured:
        # Reusing a synchronized tombstone requires explicit restoration.
        op = client.new_graph_operation('list', 'list', {'name': 'New list', 'note': ''},
                                        restore=True)
        client.journal.apply(op, client.writer)
    else:
        with store.connect() as conn:
            conn.execute("INSERT INTO lists VALUES('list','New list','',?)",
                         ('2026-10-31T00:00:00+00:00',))
    assert goals.text(goals.load(legacy, 'list')) == ''
    if captured:
        assert any(op['entity_type'] == 'research_content' and op['action'] == 'delete'
                   for op in client.journal.pending())


def test_no_goal_package_remains_readable_as_legacy_format(legacy, tmp_path):
    archive = tmp_path / 'legacy.zip'
    bundle.export('list', archive)
    with zipfile.ZipFile(archive) as z:
        assert json.loads(z.read('manifest.json'))['format'] == 1
        assert 'list_reading_goals' not in json.loads(z.read('tables.json'))
    assert bundle.inspect(archive)['list_id'] == 'list'


@pytest.mark.parametrize('damage', ['legacy_format', 'missing_goal', 'wrong_list', 'too_long'])
def test_malformed_goal_package_is_rejected_before_changing_local_data(legacy, tmp_path, damage):
    goals.save(goals.load(legacy, 'list'), 'Keep current goal')
    archive = tmp_path / 'research.zip'
    bundle.export('list', archive)
    with zipfile.ZipFile(archive) as z:
        files = {name: z.read(name) for name in z.namelist()}
    manifest = json.loads(files['manifest.json'])
    tables = json.loads(files['tables.json'])
    if damage == 'legacy_format':
        manifest['format'] = 1
    elif damage == 'missing_goal':
        tables.pop('list_reading_goals')
    elif damage == 'wrong_list':
        tables['list_reading_goals'][0]['list_id'] = 'other'
    else:
        tables['list_reading_goals'][0]['body'] = 'x' * 2001
    files['manifest.json'] = json.dumps(manifest).encode()
    files['tables.json'] = json.dumps(tables).encode()
    damaged = tmp_path / 'damaged.zip'
    with zipfile.ZipFile(damaged, 'w') as z:
        for name, value in files.items():
            z.writestr(name, value)
    with pytest.raises(ValueError):
        bundle.import_(damaged, replace=True, pdfs=False)
    assert row(legacy)[1] == 'Keep current goal'


def test_legacy_backup_without_goal_table_still_restores(legacy, tmp_path):
    with sqlite3.connect(legacy) as conn:
        conn.execute('DROP TRIGGER list_goal_parent_delete')
        conn.execute('DROP TABLE list_reading_goals')
    archive = tmp_path / 'old-backup.zip'
    sync_recovery.create(legacy, archive)
    target = tmp_path / 'legacy-restored'
    sync_recovery.restore_detached(archive, target)
    assert row(target / 'papers.db') is None


def test_goal_delete_without_observation_still_cannot_bypass_conflict_guard(bound):
    seed()
    goals.save(goals.load(bound.journal.path, 'list'), 'Retain this purpose')
    with pytest.raises(sync_capture.StaleCaptureError), store.connect() as conn:
        conn.execute("DELETE FROM list_reading_goals WHERE list_id='list'")
    assert row(bound.journal.path)[1] == 'Retain this purpose'


def test_failed_parent_deletion_rolls_back_goal_and_its_journal(bound):
    seed()
    goals.save(goals.load(bound.journal.path, 'list'), 'Keep the purpose')
    pending = bound.journal.pending()
    with pytest.raises(OSError), store.connect() as conn:
        real = conn._capture_client.writer
        def fail_on_parent(connection, operation):
            if operation['entity_type'] == 'list' and operation['action'] == 'delete':
                raise OSError('Injected failure after child operation')
            return real(connection, operation)
        conn._capture_client.writer = fail_on_parent
        conn.execute("DELETE FROM lists WHERE id='list'")
    assert row(bound.journal.path)[1] == 'Keep the purpose'
    with sqlite3.connect(bound.journal.path) as conn:
        assert conn.execute("SELECT name FROM lists WHERE id='list'").fetchone()[0] == 'Reading'
    assert bound.journal.pending() == pending
