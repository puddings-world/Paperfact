"""Actual main-window list-purpose entry without live research or AI."""
from test_reader_chat import reader as reader_fixture
from test_research_chat import legacy as legacy_fixture

from paper_daily import store
from paper_daily.desktop import main, reading_goals

reader = reader_fixture
legacy = legacy_fixture


def test_entry_opens_one_list_editor_and_preserves_question_on_repeat(reader):
    app, window, page = reader
    window.active_list = 'list'
    # The shared reader fixture supplies the initialized DB and active list.
    with store.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO lists VALUES('list','List','',?)",
                     ('2026-10-30T00:00:00+00:00',))
    window._edit_reading_goal()
    first = window._goal_dialog
    try:
        window._edit_reading_goal()
        assert window._goal_dialog is first and first.list_id == 'list'
        assert first.path == store.DB_PATH.resolve()
        assert page.ask_box.text() == 'Question'
        first.editor.setPlainText('Pending research purpose')
        window.show()
        app.processEvents()
        assert window._prepare_update() is False
        assert window.close() is False
        assert first.editor.toPlainText() == 'Pending research purpose'
    finally:
        first.reject()
        window._goal_dialog = None


def test_empty_list_selection_never_creates_an_editor(reader, monkeypatch):
    _app, window, page = reader
    window.active_list = None
    notices = []
    monkeypatch.setattr(main.QMessageBox, 'information', lambda *args: notices.append(args[-1]))
    window._edit_reading_goal()
    assert not getattr(window, '_goal_dialog', None)
    assert len(notices) == 1 and page.ask_box.text() == 'Question'


def test_editor_open_failure_keeps_reader_input_and_sanitizes_notice(reader, monkeypatch):
    _app, window, page = reader
    window.active_list = 'list'
    def fail(*args, **kwargs):
        raise ValueError('private path and credential')
    monkeypatch.setattr(reading_goals, 'ReadingGoalDialog', fail)
    notices = []
    monkeypatch.setattr(main.QMessageBox, 'warning', lambda *args: notices.append(args[-1]))
    window._edit_reading_goal()
    assert 'credential' not in notices[0]
    assert page.ask_box.text() == 'Question'
