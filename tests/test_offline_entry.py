from types import SimpleNamespace

import pytest
from test_reader_chat import reader as reader_fixture
from test_research_chat import legacy as legacy_fixture

from paper_daily import store
from paper_daily.desktop import main

reader = reader_fixture
legacy = legacy_fixture


class Dialog:
    instances = []

    def __init__(self, database, papers, parent, **kwargs):
        self.database, self.papers, self.parent = database, papers, parent
        self.current_path = kwargs['current_path']
        self.disposed = False
        self.opened = self.raised = 0
        self.instances.append(self)

    def setWindowModality(self, value):
        pass

    def open(self):
        self.opened += 1

    def show(self):
        pass

    def raise_(self):
        self.raised += 1

    def activateWindow(self):
        pass

    def close(self):
        return False


@pytest.fixture
def fake_dialog(monkeypatch):
    from paper_daily.desktop import offline_dialog
    Dialog.instances = []
    monkeypatch.setattr(offline_dialog, 'OfflineDialog', Dialog)
    return Dialog


def test_reading_entry_is_scoped_to_current_paper_and_repeated_action_reuses_dialog(
    reader, fake_dialog,
):
    _app, window, page = reader
    window.stack.setCurrentWidget(page)
    draft = page.ask_box.text()
    window._offline_selected()
    window._offline_selected()
    try:
        assert len(fake_dialog.instances) == 1
        view = fake_dialog.instances[0]
        assert view.papers == ['local-paper'] and view.database == store.DB_PATH
        assert view.current_path() == store.DB_PATH
        assert view.opened == 1 and view.raised == 1
        assert page.ask_box.text() == draft
    finally:
        window._offline_dialog = None


@pytest.mark.parametrize('ids', [[], [str(i) for i in range(101)]])
def test_no_selection_and_over_limit_never_start_offline_work(
    reader, fake_dialog, monkeypatch, ids,
):
    _app, window, _page = reader
    window.stack.setCurrentWidget(window.queue_page)
    indexes = [SimpleNamespace(data=lambda role, pid=pid: SimpleNamespace(id=pid)) for pid in ids]
    monkeypatch.setattr(window.queue_page.view, 'selectionModel',
                        lambda: SimpleNamespace(selectedIndexes=lambda: indexes))
    notices = []
    monkeypatch.setattr(main.QMessageBox, 'information', lambda *args: notices.append(args[1]))
    window._offline_selected()
    assert not fake_dialog.instances and len(notices) == 1


def test_queue_entry_deduplicates_selected_papers_without_changing_selection(
    reader, fake_dialog, monkeypatch,
):
    _app, window, page = reader
    window.stack.setCurrentWidget(window.queue_page)
    indexes = [SimpleNamespace(data=lambda role, pid=pid: SimpleNamespace(id=pid))
               for pid in ['selected-b', 'selected-a', 'selected-b']]
    monkeypatch.setattr(window.queue_page.view, 'selectionModel',
                        lambda: SimpleNamespace(selectedIndexes=lambda: indexes))
    window._offline_selected()
    try:
        assert fake_dialog.instances[0].papers == ['selected-b', 'selected-a']
        assert page.paper.id == 'local-paper'
    finally:
        window._offline_dialog = None


def test_offline_work_blocks_parent_close_and_updater_without_discarding_draft(reader, fake_dialog):
    app, window, page = reader
    window.stack.setCurrentWidget(page)
    window.show()
    app.processEvents()
    window._offline_selected()
    try:
        assert window._prepare_update() is False
        assert window.close() is False
        assert window.isVisible() and page.ask_box.text() == 'Question'
    finally:
        window._offline_dialog = None


def test_offline_start_failure_is_sanitized_and_leaves_question_untouched(reader, monkeypatch):
    from paper_daily.desktop import offline_dialog
    _app, window, page = reader
    window.stack.setCurrentWidget(page)

    def fail(*args, **kwargs):
        raise ValueError('private credential or path must not enter the message')

    monkeypatch.setattr(offline_dialog, 'OfflineDialog', fail)
    notices = []
    monkeypatch.setattr(main.QMessageBox, 'warning', lambda *args: notices.append(args[-1]))
    window._offline_selected()
    assert len(notices) == 1 and 'credential' not in notices[0]
    assert page.ask_box.text() == 'Question'
