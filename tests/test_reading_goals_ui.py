"""User-visible purpose editing and its no-AI draft integration."""
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from test_reading_goals import legacy as legacy_fixture
from test_reading_goals import row
from test_research_tasks import reader as reader_fixture

from paper_daily import reading_goals as goals
from paper_daily.desktop import research_tasks as tasks
from paper_daily.desktop.reading_goals import ReadingGoalDialog

legacy = legacy_fixture
reader = reader_fixture


@pytest.fixture
def view(legacy):
    app = QApplication.instance() or QApplication([])
    dialog = ReadingGoalDialog(legacy, 'list')
    yield dialog
    dialog.reject()
    dialog.deleteLater()
    app.processEvents()


def test_save_and_reopen_preserve_the_exact_purpose_without_ai(view, legacy):
    view.editor.setPlainText('Compare evidence, assumptions and limitations')
    view.save_button.click()
    assert view.result() == view.DialogCode.Accepted
    assert row(legacy)[1] == 'Compare evidence, assumptions and limitations'
    restored = ReadingGoalDialog(legacy, 'list')
    assert restored.editor.toPlainText() == row(legacy)[1]
    restored.reject()


def test_cancel_and_oversized_input_never_save(view, legacy):
    view.editor.setPlainText('x' * 2001)
    assert not view.save_button.isEnabled()
    view.save()
    view.reject()
    assert row(legacy) is None


def test_save_failure_retains_editor_and_allows_retry(view, legacy, monkeypatch):
    real = goals.save
    monkeypatch.setattr(goals, 'save', lambda *args: (_ for _ in ()).throw(OSError('failure')))
    view.editor.setPlainText('My draft')
    view.save_button.click()
    assert view.editor.toPlainText() == 'My draft'
    assert view.save_button.isEnabled() and row(legacy) is None
    monkeypatch.setattr(goals, 'save', real)
    view.save_button.click()
    view.save()
    assert row(legacy)[1] == 'My draft'


def test_stale_edit_is_retained_without_replacing_current_goal(view, legacy):
    goals.save(goals.load(legacy, 'list'), 'Newer goal')
    view.editor.setPlainText('My older draft')
    view.save_button.click()
    assert row(legacy)[1] == 'Newer goal'
    assert view.publication.status == 'candidate'
    assert view.editor.toPlainText() == 'My older draft'
    assert view.editor.isReadOnly() and not view.save_button.isEnabled()
    assert '未覆蓋' in view.status.text()


def test_switching_workspace_keeps_draft_and_never_saves_to_either(view, legacy, tmp_path):
    view.current_path = lambda: tmp_path / 'other.db'
    view.editor.setPlainText('Original draft')
    view.save_button.click()
    assert row(legacy) is None
    assert not (tmp_path / 'other.db').exists()
    assert view.editor.toPlainText() == 'Original draft'


def test_list_purpose_is_included_only_in_a_reviewed_question_draft(reader, legacy, monkeypatch):
    # reader fixture deliberately has no host selection; bind it to this explicit list.
    reader.win = SimpleNamespace(active_list='list')
    reader.paper.id = 'paper'
    goals.save(goals.load(legacy, 'list'), 'Find a reproducible experimental design')
    from paper_daily import store
    monkeypatch.setattr(store, 'DB_PATH', legacy)
    previews = []
    monkeypatch.setattr(tasks, 'preview',
                        lambda *args: (previews.append(args[-1]) or args[-1], True))
    tasks.draft(reader, 'replication')
    assert 'Find a reproducible experimental design' in previews[0]
    assert reader.drafted == previews
    assert row(legacy)[1] == 'Find a reproducible experimental design'


@pytest.mark.parametrize('change', ['goal', 'list', 'cancel'])
def test_changed_purpose_or_list_or_cancel_keeps_unsent_input(reader, legacy, monkeypatch, change):
    from paper_daily import store
    reader.win = SimpleNamespace(active_list='list')
    reader.paper.id = 'paper'
    monkeypatch.setattr(store, 'DB_PATH', legacy)
    reader.ask_box.setText('Unsent input')
    def preview(*args):
        if change == 'goal':
            goals.save(goals.load(legacy, 'list'), 'Changed intent')
        elif change == 'list':
            reader.win.active_list = None
        return args[-1], change != 'cancel'
    monkeypatch.setattr(tasks, 'preview', preview)
    tasks.draft(reader, 'evidence')
    assert reader.ask_box.text() == 'Unsent input' and not reader.drafted


def test_closing_editor_keeps_research_and_discards_only_unsaved_purpose(view, legacy):
    view.editor.setPlainText('Unsubmitted purpose')
    view.show()
    assert view.close()
    assert row(legacy) is None
    assert view.disposed
