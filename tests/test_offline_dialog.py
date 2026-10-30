"""Offline checks do not block editors or mistake metadata for verified bytes."""
import copy
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget
from test_sync_transfers import setup as transfer_setup_fixture
from test_workspace_offline import prepared as offline_prepared_fixture

from paper_daily.desktop.offline_dialog import TEXT, OfflineDialog
from paper_daily.workspace_service import SnapshotChanged

transfer_setup = transfer_setup_fixture
offline_prepared = offline_prepared_fixture


def result(*, verified=False, ready=False):
    return {
        'scope': 'selected_current_manifests', 'whole_workspace_offline_verified': False,
        'ready': ready,
        'papers': [
            {'paper_id': 'paper-a', 'portable_id': 'portable-a', 'title': '<b>Paper A</b>',
             'pinned': False, 'ready': ready,
             'pdf': {'state': 'verified' if verified else 'unchecked'},
             'artifacts': [{'entity_id': 'guide', 'slot': 'guide',
                            'state': 'verified' if verified else 'unchecked',
                            'source_state': 'current'}], 'artifact_inventory_available': True},
            {'paper_id': 'paper-b', 'portable_id': 'portable-b', 'title': 'Paper B',
             'pinned': False, 'ready': ready,
             'pdf': {'state': 'verified' if verified else 'unchecked'},
             'artifacts': [], 'artifact_inventory_available': True},
        ],
    }


class FakeService:
    def __init__(self):
        self.value = result()
        self.calls = []
        self.hooks = {}

    def plan(self, papers, ticket):
        self.calls.append(('plan', tuple(papers)))
        ticket.check()
        if 'plan' in self.hooks:
            return self.hooks['plan'](ticket)
        return copy.deepcopy(self.value)

    def status(self, papers, ticket):
        self.calls.append(('verify', tuple(papers)))
        ticket.check()
        if 'status' in self.hooks:
            return self.hooks['status'](ticket)
        return result(verified=True, ready=True)

    def set_pins(self, papers, *, enabled, ticket):
        self.calls.append(('pin', tuple(papers), enabled))
        ticket.check()
        if 'pin' in self.hooks:
            return self.hooks['pin'](ticket)
        for paper in self.value['papers']:
            paper['pinned'] = enabled
        return {'paper_ids': papers, 'pinned': enabled}


def wait(app, condition, timeout=6):
    deadline = time.monotonic() + timeout
    while not condition():
        app.processEvents()
        if time.monotonic() >= deadline:
            raise AssertionError('Offline fixture worker did not finish')
        time.sleep(0.005)
    app.processEvents()


@pytest.fixture
def shell(tmp_path):
    app = QApplication.instance() or QApplication([])
    database = tmp_path / 'papers.db'
    database.write_bytes(b'isolated fixture identity')
    active = [database]
    parent = QWidget()
    editor = QLineEdit('Unsent parent question', parent)
    parent.resize(500, 200)
    parent.show()
    fake = FakeService()
    factory_threads = []

    def factory(*args, **kwargs):
        factory_threads.append(threading.get_ident())
        return fake

    dialog = OfflineDialog(database, ['paper-a', 'paper-b'], parent,
                           current_path=lambda: active[0], service_factory=factory, language='en')
    dialog.show()
    wait(app, lambda: dialog._plan is not None and not dialog.busy)
    yield SimpleNamespace(app=app, dialog=dialog, fake=fake, active=active, database=database,
                          editor=editor, parent=parent, factory_threads=factory_threads)
    for hook in fake.hooks.values():
        release = getattr(hook, 'release', None)
        if release:
            release.set()
    if dialog.busy:
        dialog.cancel()
        wait(app, lambda: not dialog.busy)
    dialog.close()
    parent.close()
    dialog.deleteLater()
    parent.deleteLater()
    app.processEvents()


def hold_result(value):
    entered, release = threading.Event(), threading.Event()

    def work(ticket):
        entered.set()
        assert release.wait(5)
        ticket.check()
        return copy.deepcopy(value)

    work.entered, work.release = entered, release
    return work


def test_open_reads_only_metadata_and_preserves_parent_draft(shell):
    d = shell.dialog
    assert shell.fake.calls == [('plan', ('paper-a', 'paper-b'))]
    assert len(shell.factory_threads) == 1
    assert shell.factory_threads[0] != threading.get_ident()
    assert d.table.item(0, 0).text() == '<b>Paper A</b>'
    assert d.table.item(0, 1).text() == 'Not verified'
    assert d.status.text() == TEXT['en']['planned']
    assert d.verify_button.isEnabled() and d.pin_button.isEnabled()
    assert not d.progress.isVisible()
    assert shell.editor.text() == 'Unsent parent question'


def test_verify_requires_real_ready_result_and_preserves_row_selection(shell):
    d = shell.dialog
    d.table.selectRow(1)
    d.verify_button.click()
    wait(shell.app, lambda: not d.busy)
    assert d.status.text() == TEXT['en']['ready'].format(time=d.last_verified_at)
    assert d.table.currentRow() == 1
    assert d.table.item(0, 1).text() == 'Verified'
    assert d.table.item(1, 0).data(Qt.ItemDataRole.UserRole) == 'paper-b'
    assert shell.editor.text() == 'Unsent parent question'


@pytest.mark.parametrize('problem', ['budget', 'missing', 'source', 'inventory', 'false-ready'])
def test_partial_results_never_claim_selected_or_whole_workspace_ready(shell, problem):
    value = result(verified=True, ready=False)
    if problem == 'budget':
        value['papers'][0]['pdf']['state'] = 'budget_exceeded'
    elif problem == 'missing':
        value['papers'][0]['pdf']['state'] = 'missing_manifest'
    elif problem == 'source':
        value['papers'][0]['artifacts'][0]['source_state'] = 'unknown'
    elif problem == 'inventory':
        value['papers'][0]['artifact_inventory_available'] = False
    else:
        value['ready'] = True  # Per-paper confirmation is independently required.
    shell.fake.hooks['status'] = lambda ticket: value
    shell.dialog.verify()
    wait(shell.app, lambda: not shell.dialog.busy)
    assert shell.dialog.status.text() == TEXT['en']['partial']
    assert shell.dialog.table.item(0, 1).text() != ''
    labels = ' '.join(
        label.text() for label in shell.dialog.findChildren(type(shell.dialog.status)))
    assert 'They do not certify the whole workspace' in labels


def test_pin_and_unpin_only_save_intent_and_refresh_metadata(shell):
    d = shell.dialog
    changed = []
    d.pins_changed.connect(lambda: changed.append(True))
    d.pin_button.click()
    wait(shell.app, lambda: not d.busy)
    assert d.table.item(0, 3).text() == 'Marked'
    assert d.status.text() == TEXT['en']['pinned']
    assert not any(call[0] == 'verify' for call in shell.fake.calls)
    d.unpin_button.click()
    wait(shell.app, lambda: not d.busy)
    assert d.table.item(0, 3).text() == 'Not marked'
    assert ('pin', ('paper-a', 'paper-b'), False) in shell.fake.calls
    assert changed == [True, True]


def test_repeated_activation_and_cancel_share_one_worker(shell):
    held = hold_result(result(verified=True, ready=True))
    shell.fake.hooks['status'] = held
    d = shell.dialog
    assert d.verify()
    wait(shell.app, held.entered.is_set)
    for _ in range(20):
        assert not d.verify()
        assert not d.set_pins(True)
    assert not d.verify_button.isEnabled() and not d.pin_button.isEnabled()
    d.cancel_button.click()
    held.release.set()
    wait(shell.app, lambda: not d.busy)
    assert d.status.text() == TEXT['en']['cancelled']
    assert len([call for call in shell.fake.calls if call[0] == 'verify']) == 1
    assert d.verify_button.isEnabled()


def test_close_waits_for_worker_without_discarding_parent_input(shell):
    held = hold_result(result(verified=True, ready=True))
    shell.fake.hooks['status'] = held
    d = shell.dialog
    d.verify()
    wait(shell.app, held.entered.is_set)
    assert not d.close() and not d.disposed
    assert d.status.text() == TEXT['en']['cancelling']
    held.release.set()
    wait(shell.app, lambda: d.disposed)
    assert not d.isVisible() and not d.busy
    assert shell.editor.text() == 'Unsent parent question'
    assert d.status.text() != TEXT['en']['ready'].format(time=d.last_verified_at)


@pytest.mark.parametrize('change', ['workspace', 'replacement'])
def test_late_result_after_workspace_switch_or_database_replacement_is_discarded(shell, change):
    # Deliberately disregard cancellation in the fake service to prove the UI guard.
    entered, release = threading.Event(), threading.Event()

    def stale(ticket):
        entered.set()
        assert release.wait(5)
        return result(verified=True, ready=True)

    stale.release = release
    shell.fake.hooks['status'] = stale
    d = shell.dialog
    d.verify()
    wait(shell.app, entered.is_set)
    if change == 'workspace':
        shell.active[0] = shell.database.with_name('other.db')
    else:
        shell.database.rename(shell.database.with_name('old.db'))
        shell.database.write_bytes(b'replacement')
    d._check_context()
    release.set()
    wait(shell.app, lambda: not d.busy)
    assert d.status.text() == TEXT['en']['changed']
    assert not d.verify_button.isEnabled()
    assert d.table.item(0, 1).text() == 'Not verified'


@pytest.mark.parametrize('error', [OSError('secret research path'), SnapshotChanged('private')])
def test_failure_is_sanitized_and_retry_keeps_selection(shell, error):
    d = shell.dialog
    d.table.selectRow(1)

    def fail(ticket):
        raise error

    shell.fake.hooks['status'] = fail
    d.verify()
    wait(shell.app, lambda: not d.busy)
    assert 'secret' not in d.status.text() and 'private' not in d.status.text()
    assert d.table.currentRow() == 1 and d.verify_button.isEnabled()
    del shell.fake.hooks['status']
    d.verify()
    wait(shell.app, lambda: not d.busy)
    assert d.status.text() == TEXT['en']['ready'].format(time=d.last_verified_at)
    assert d.table.currentRow() == 1


@pytest.mark.parametrize('selection', [[], ['x'] * 101, 'paper-a', [None]])
def test_empty_or_invalid_selection_never_starts_a_service(tmp_path, selection):
    app = QApplication.instance() or QApplication([])
    database = tmp_path / 'fixture.db'
    database.write_bytes(b'identity')
    d = OfflineDialog(database, selection,
                      service_factory=lambda *a, **k: pytest.fail('Invalid selection read data'),
                      language='en')
    d.show()
    app.processEvents()
    assert d.status.text() == TEXT['en']['empty']
    assert not d.verify_button.isEnabled() and not d.pin_button.isEnabled()
    assert not d.busy and not d.verify()
    d.close()


def test_service_construction_failure_is_sanitized_and_retryable(tmp_path):
    app = QApplication.instance() or QApplication([])
    database = tmp_path / 'fixture.db'
    database.write_bytes(b'identity')
    calls = []
    fake = FakeService()

    def factory(*args, **kwargs):
        calls.append(threading.get_ident())
        if len(calls) == 1:
            raise OSError('fixture-private-directory')
        return fake

    d = OfflineDialog(database, ['paper-a', 'paper-b'], service_factory=factory, language='en')
    d.show()
    wait(app, lambda: len(calls) == 1 and not d.busy)
    assert d.status.text() == TEXT['en']['failure'] and 'private' not in d.status.text()
    assert d.refresh()
    wait(app, lambda: not d.busy)
    assert d.status.text() == TEXT['en']['planned']
    assert all(value != threading.get_ident() for value in calls)
    d.close()


def test_copy_sets_match_and_unknown_language_uses_english(tmp_path):
    assert set(TEXT['en']) == set(TEXT['zh-TW'])
    app = QApplication.instance() or QApplication([])
    database = tmp_path / 'fixture.db'
    database.write_bytes(b'identity')
    d = OfflineDialog(database, [], language='unknown')
    assert d.windowTitle() == TEXT['en']['title']
    d.close()
    app.processEvents()


def test_actual_service_verifies_bytes_and_persists_only_local_pin_intent(offline_prepared):
    app = QApplication.instance() or QApplication([])
    service, client, local, portable, *_ = offline_prepared
    pending = client.journal.pending(1000)
    d = OfflineDialog(client.journal.path, [local], language='en')
    d.show()
    try:
        wait(app, lambda: d._plan is not None and not d.busy)
        assert d.table.item(0, 1).text() == 'Not verified'
        d.verify_button.click()
        wait(app, lambda: not d.busy)
        assert d.status.text() == TEXT['en']['ready'].format(time=d.last_verified_at)
        assert d.table.item(0, 1).text() == 'Verified'
        d.pin_button.click()
        wait(app, lambda: not d.busy)
        assert d.table.item(0, 3).text() == 'Marked'
        assert service.pins() == [{'paper_id': local, 'portable_id': portable}]
        assert client.journal.pending(1000) == pending
        assert d.last_verified_at is None  # Pin metadata is not verification.
        assert d.status.text() == TEXT['en']['pinned']
    finally:
        if d.busy:
            d.cancel()
            wait(app, lambda: not d.busy)
        d.close()


def test_actual_corrupt_pdf_cannot_render_ready(offline_prepared):
    app = QApplication.instance() or QApplication([])
    _, client, local, _, blob_store, manifest, data = offline_prepared
    blob_store.verified_path(manifest).write_bytes(b'x' * len(data))
    d = OfflineDialog(client.journal.path, [local], language='en')
    d.show()
    try:
        wait(app, lambda: d._plan is not None and not d.busy)
        d.verify_button.click()
        wait(app, lambda: not d.busy)
        assert d.status.text() == TEXT['en']['partial']
        assert d.table.item(0, 1).text() == 'Unavailable'
    finally:
        if d.busy:
            d.cancel()
            wait(app, lambda: not d.busy)
        d.close()


def test_ready_is_a_dated_snapshot_and_metadata_refresh_clears_it(shell):
    d = shell.dialog
    d.verify()
    wait(shell.app, lambda: not d.busy)
    assert d.last_verified_at and d.last_verified_at in d.status.text()
    assert 'snapshot' in d.status.text()
    assert 'Recheck after source or file changes' in d.status.text()
    shell.fake.value['papers'][0]['pdf']['state'] = 'unbound'
    d.refresh()
    wait(shell.app, lambda: not d.busy)
    assert d.last_verified_at is None
    assert d.table.item(0, 1).text() == 'Files not bound'
    assert d.status.text() == TEXT['en']['planned']


def test_unenrolled_research_is_explained_without_migration_or_raw_errors(tmp_path):
    from paper_daily.workspace_sync import EnrollmentRequired

    app = QApplication.instance() or QApplication([])
    database = tmp_path / 'fixture.db'
    database.write_bytes(b'identity')
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(1)
        raise EnrollmentRequired('private-source-details')

    d = OfflineDialog(database, ['paper-a'], service_factory=unavailable, language='en')
    d.show()
    wait(app, lambda: bool(calls) and not d.busy)
    assert d.status.text() == TEXT['en']['enrollment']
    assert 'private-source-details' not in d.status.text()
    assert not d.pin_button.isEnabled() and d._plan is None
    assert database.read_bytes() == b'identity'
    d.close()
