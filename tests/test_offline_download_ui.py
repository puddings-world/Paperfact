"""Explicit selected download uses the owner's memory session and never certifies readiness."""
import copy
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QWidget
from test_offline_dialog import FakeService, wait
from test_workspace_offline_download import assert_unrelated_absent, selected_ids
from test_workspace_offline_download import codec as codec_fixture
from test_workspace_offline_download import transfer_setup as transfer_setup_fixture
from test_workspace_offline_download import world as world_fixture

from paper_daily.desktop.offline_dialog import TEXT, OfflineDialog
from paper_daily.desktop.sync_connection_dialog import open_offline_connection

transfer_setup = transfer_setup_fixture
codec = codec_fixture
world = world_fixture


class Session:
    def __init__(self, database):
        info = database.stat()
        self.workspace = SimpleNamespace(path=database, identity=(info.st_dev, info.st_ino))
        self._generation = 1
        self.authenticated = True
        self.calls = []
        self.hook = None
        self.partial = False

    def summary(self):
        return {'authenticated': self.authenticated}

    def prepare_offline(self, ids, ticket, *, progress, steps, seconds):
        self.calls.append((tuple(ids), threading.get_ident(), steps, seconds))
        ticket.check()
        progress({'stage': 'offline_download', 'steps': 0})
        if self.hook:
            self.hook(ticket, progress)
        ticket.check()
        return {'state': 'partial' if self.partial else 'downloaded', 'partial': self.partial,
                'verification_required': True, 'paper_ids': list(ids)}


@pytest.fixture
def shell(tmp_path):
    app = QApplication.instance() or QApplication([])
    database = tmp_path / 'papers.db'
    database.write_bytes(b'isolated fixture identity')
    active = [database]
    parent = QWidget()
    editor = QLineEdit('Unsent parent draft', parent)
    fake = FakeService()
    selected = [Session(database)]
    opens = []
    dialog = OfflineDialog(
        database, ['paper-a', 'paper-b'], parent, current_path=lambda: active[0],
        service_factory=lambda *a, **k: fake, language='en',
        session_provider=lambda: selected[0], open_connection=lambda d: opens.append(d),
    )
    dialog.show()
    wait(app, lambda: dialog._plan is not None and not dialog.busy)
    yield SimpleNamespace(app=app, dialog=dialog, fake=fake, session=selected[0], selected=selected,
                          database=database, active=active, parent=parent, editor=editor,
                          opens=opens)
    if dialog._worker:
        dialog.cancel()
        wait(app, lambda: not dialog.busy)
    dialog.close()
    parent.close()
    dialog.deleteLater()
    parent.deleteLater()
    app.processEvents()


def test_download_is_explicit_selected_off_gui_and_requires_separate_verification(shell):
    d = shell.dialog
    assert shell.session.calls == []
    d.table.selectRow(1)
    assert d.verify()
    wait(shell.app, lambda: not d.busy)
    assert d.last_verified_at is not None
    shell.fake.calls.clear()
    assert d.download()
    assert d.last_verified_at is None and not d.download_button.isEnabled()
    assert not d.download() and not d.verify() and not d.set_pins(True)
    wait(shell.app, lambda: not d.busy)
    assert len(shell.session.calls) == 1
    ids, thread, steps, seconds = shell.session.calls[0]
    assert ids == ('paper-a', 'paper-b') and thread != threading.get_ident()
    assert steps == 64 and seconds == 20
    assert shell.fake.calls == [('plan', ('paper-a', 'paper-b'))]
    assert d.last_verified_at is None and d.status.text() == TEXT['en']['downloaded']
    assert d.table.currentRow() == 1 and shell.editor.text() == 'Unsent parent draft'
    assert d.verify()
    wait(shell.app, lambda: not d.busy)
    assert d.last_verified_at and 'Verified snapshot' in d.status.text()


def test_missing_connection_is_an_explicit_link_without_automatic_login_or_transfer(shell):
    d = shell.dialog
    shell.selected[0] = None
    assert not d.download()
    assert d.status.text() == TEXT['en']['connect_first']
    assert shell.opens == [] and shell.session.calls == []
    d.connection_button.click()
    assert shell.opens == [d] and shell.session.calls == []


def test_empty_selection_never_calls_session(shell):
    shell.dialog.paper_ids = []
    assert not shell.dialog.download()
    assert shell.session.calls == []


def test_download_partial_and_error_retry_never_reuse_readiness(shell):
    d = shell.dialog
    shell.session.partial = True
    assert d.download()
    wait(shell.app, lambda: not d.busy)
    assert d.status.text() == TEXT['en']['download_partial'] and d.last_verified_at is None

    def fail(*_):
        raise ConnectionError('secret path/token must not be displayed')

    shell.session.hook = fail
    assert d.download()
    wait(shell.app, lambda: not d.busy)
    assert d.status.text() == TEXT['en']['download_failed'] and d.last_verified_at is None
    shell.session.hook = None
    shell.session.partial = False
    assert d.download()
    wait(shell.app, lambda: not d.busy)
    assert len(shell.session.calls) == 3 and d.status.text() == TEXT['en']['downloaded']


@pytest.mark.parametrize('change', ['session', 'generation', 'workspace', 'source'])
def test_changed_context_never_displays_late_download_success(shell, change):
    d = shell.dialog
    before = copy.deepcopy(d._plan)

    def changed(ticket, progress):
        if change == 'session':
            shell.selected[0] = Session(shell.database)
        elif change == 'generation':
            shell.session._generation += 1
        elif change == 'workspace':
            shell.active[0] = shell.database.parent / 'different.db'
        else:
            from paper_daily.workspace_sync import SyncStopped
            raise SyncStopped('Selected source changed')

    shell.session.hook = changed
    assert d.download()
    wait(shell.app, lambda: not d.busy)
    assert d._plan == before and d.last_verified_at is None
    assert d.status.text() in (TEXT['en']['connection_changed'], TEXT['en']['changed'],
                               TEXT['en']['cancelled'])
    assert d.status.text() != TEXT['en']['downloaded']


@pytest.mark.parametrize('close', [False, True])
def test_cancel_or_close_waits_for_worker_and_discards_late_result(shell, close):
    d = shell.dialog
    entered, release = threading.Event(), threading.Event()

    def blocked(ticket, progress):
        entered.set()
        assert release.wait(5)

    shell.session.hook = blocked
    assert d.download()
    assert entered.wait(5)
    if close:
        assert not d.close() and not d.disposed
    else:
        d.cancel()
    release.set()
    wait(shell.app, lambda: not d.busy)
    assert d.disposed is close and d.last_verified_at is None
    assert shell.editor.text() == 'Unsent parent draft'


def test_progress_reports_current_file_bytes_without_invented_overall_percentage(shell):
    entered, release = threading.Event(), threading.Event()

    def blocked(ticket, progress):
        progress({'offset': 25, 'size': 100, 'path': 'never display', 'token': 'secret'})
        entered.set()
        assert release.wait(5)

    shell.session.hook = blocked
    d = shell.dialog
    try:
        assert d.download() and entered.wait(5)
        wait(shell.app, lambda: d.progress.maximum() == 100)
        assert d.progress.value() == 25
        assert d.status.text() == 'Current file: 25 / 100 bytes'
    finally:
        release.set()
        wait(shell.app, lambda: not d.busy)


class Connection(QDialog):
    def __init__(self, session, parent, **_kwargs):
        super().__init__(parent)
        self.session = session
        self.disposed = False
        self.busy = False


def test_connection_helper_reuses_actual_workspace_owner_session_and_existing_dialog(shell):
    owner, d, session = shell.parent, shell.dialog, shell.session
    owner._workspace_sync_session = session
    child = Connection(session, owner)
    owner._workspace_dialog = SimpleNamespace(_sync_dialog=child)
    opened = open_offline_connection(owner, d, shell.database,
                                    current_path=lambda: shell.database,
                                    dialog_factory=lambda *_a, **_k: pytest.fail(
                                        'Duplicate dialog'))
    assert opened is child and owner._workspace_sync_session is session
    assert session.calls == []
    child.close()


def test_connection_helper_creates_only_unauthenticated_memory_session_on_click(shell):
    owner, d = shell.parent, shell.dialog
    assert not hasattr(owner, '_workspace_sync_session')
    child = open_offline_connection(owner, d, shell.database, dialog_factory=Connection)
    assert child.session is owner._workspace_sync_session
    assert child.session.summary()['authenticated'] is False
    assert child.session.workspace.path == shell.database
    child.close()


def test_real_selected_download_then_separate_actual_verification(world):
    app = QApplication.instance() or QApplication([])
    session = world['session']
    d = OfflineDialog(world['b'].journal.path, selected_ids(world), language='en',
                      current_path=lambda: world['active'][0], session_provider=lambda: session)
    try:
        d.show()
        wait(app, lambda: d._plan is not None and not d.busy, timeout=15)
        assert d.download()
        wait(app, lambda: not d.busy, timeout=30)
        assert d.status.text() == TEXT['en']['downloaded'] and d.last_verified_at is None
        assert 'push' not in world['calls'] and 'pull' not in world['calls']
        assert_unrelated_absent(world)
        assert d.verify()
        wait(app, lambda: not d.busy, timeout=20)
        assert d.last_verified_at and d._plan['ready']
    finally:
        if d.busy:
            d.cancel()
            wait(app, lambda: not d.busy, timeout=30)
        d.close()
        d.deleteLater()
        app.processEvents()


def test_closing_offline_dialog_waits_for_real_connection_worker(world, monkeypatch):
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    owner._workspace_sync_session = world['session']
    d = OfflineDialog(
        world['b'].journal.path, selected_ids(world), owner, language='en',
        service_factory=lambda *a, **k: FakeService(),
        session_provider=lambda: owner._workspace_sync_session,
        open_connection=lambda parent: open_offline_connection(
            owner, parent, parent.path, language='en'),
    )
    entered, release = threading.Event(), threading.Event()
    original = world['authority'].session_info

    def blocked(token):
        entered.set()
        assert release.wait(10)
        return original(token)

    try:
        wait(app, lambda: not d.busy and d._plan is not None)
        assert d.connect_sync()
        child = d._connection_dialog
        wait(app, lambda: not child.busy and child.binding is not None)
        assert child.session is world['session']
        child.credential.setText(world['token'])
        monkeypatch.setattr(world['authority'], 'session_info', blocked)
        assert child.connect_session() and entered.wait(5)
        assert d.busy and not d.close() and not d.disposed
        release.set()
        wait(app, lambda: d.disposed and child.disposed, timeout=15)
        assert not d.busy and not child.busy
    finally:
        release.set()
        if d.busy:
            d.close()
            wait(app, lambda: not d.busy, timeout=15)
        d.close()
        owner.close()
        d.deleteLater()
        owner.deleteLater()
        app.processEvents()
