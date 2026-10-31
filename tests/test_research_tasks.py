from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox, QWidget

from paper_daily import research_tasks, store
from paper_daily.desktop import research_tasks as ui


@pytest.mark.parametrize('task', research_tasks.TASKS, ids=lambda task: task.id)
def test_each_task_produces_a_goal_aware_evidence_question(task):
    text = research_tasks.question(task.id, goal='Compare robustness across study designs')
    assert task.instruction in text
    assert 'Compare robustness across study designs' in text
    assert research_tasks.EVIDENCE_RULES in text
    assert '不要編造' in text and '明確標記' in text


def test_unknown_task_and_oversized_goal_fail_without_side_effects():
    with pytest.raises(ValueError):
        research_tasks.question('unknown')
    with pytest.raises(ValueError):
        research_tasks.question('evidence', goal='x' * 2001)
    assert '我的研究目的' not in research_tasks.question('evidence', goal='  ')


@pytest.fixture
def reader(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'workspace.db')
    widget = QWidget()
    widget.paper = SimpleNamespace(id='paper-a')
    widget._qa_epoch = 1
    widget.ask_box = QLineEdit(widget)
    widget.ask_status = QLabel(widget)
    widget.drafted = []

    def fill(text):
        widget.drafted.append(text)
        widget.ask_box.setText(text)

    widget._draft_question = fill
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_task_menu_opens_editable_draft_without_ai_or_history_writes(reader, monkeypatch):
    calls = []
    monkeypatch.setattr(ui, 'preview',
                        lambda *a: (calls.append(a[-1]) or 'Edited research question', True))
    picker = ui.button(reader)
    action = picker.menu().actions()[0]
    action.trigger()
    assert calls == [research_tasks.question(action.data())]
    assert reader.drafted == ['Edited research question']
    assert reader.ask_box.text() == 'Edited research question'
    assert not store.DB_PATH.exists()


@pytest.mark.parametrize('accepted,text', [(False, 'draft'), (True, '  ')])
def test_cancel_or_blank_keeps_existing_input(reader, monkeypatch, accepted, text):
    reader.ask_box.setText('My own question')
    monkeypatch.setattr(ui, 'preview', lambda *a: (text, accepted))
    ui.draft(reader, 'methods')
    assert reader.ask_box.text() == 'My own question' and not reader.drafted


def test_replacing_manual_input_requires_confirmation_and_repeated_use_is_only_a_draft(
    reader, monkeypatch,
):
    reader.ask_box.setText('My own question')
    monkeypatch.setattr(ui, 'preview', lambda *a: ('New draft', True))
    monkeypatch.setattr(ui.QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.No)
    ui.draft(reader, 'methods')
    assert reader.ask_box.text() == 'My own question' and not reader.drafted
    monkeypatch.setattr(ui.QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    for _ in range(3):
        ui.draft(reader, 'methods')
    assert reader.ask_box.text() == 'New draft'
    assert not store.DB_PATH.exists()


@pytest.mark.parametrize('change', ['paper', 'workspace', 'draft', 'epoch'])
def test_changed_context_during_preview_never_receives_stale_draft(reader, monkeypatch, change):
    reader.ask_box.setText('Keep my question')

    def preview(*args):
        if change == 'paper':
            reader.paper = SimpleNamespace(id='paper-b')
        elif change == 'workspace':
            monkeypatch.setattr(store, 'DB_PATH', store.DB_PATH.with_name('other.db'))
        elif change == 'draft':
            reader.ask_box.setText('Typed while previewing')
        else:
            reader._qa_epoch += 1
        return 'Stale task', True

    monkeypatch.setattr(ui, 'preview', preview)
    ui.draft(reader, 'evidence')
    assert not reader.drafted and reader.ask_box.text() != 'Stale task'
    assert reader.ask_status.text()


def test_empty_selection_and_context_switch_during_confirmation(reader, monkeypatch):
    reader.paper = None
    monkeypatch.setattr(ui, 'preview',
                        lambda *a: pytest.fail('No selected paper'))
    ui.draft(reader, 'evidence')
    reader.paper = SimpleNamespace(id='paper-a')
    reader.ask_box.setText('Keep')
    monkeypatch.setattr(ui, 'preview', lambda *a: ('Stale', True))

    def confirm(*args):
        reader.paper = SimpleNamespace(id='paper-b')
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(ui.QMessageBox, 'question', confirm)
    ui.draft(reader, 'evidence')
    assert reader.ask_box.text() == 'Keep' and not reader.drafted


def test_closing_reader_during_task_preview_does_not_apply_draft(reader, monkeypatch):
    reader.show()
    reader.ask_box.setText('Keep my draft')

    def preview(*args):
        reader.close()
        return 'Closed view task', True

    monkeypatch.setattr(ui, 'preview', preview)
    ui.draft(reader, 'replication')
    assert reader.ask_box.text() == 'Keep my draft' and not reader.drafted


def test_preview_wraps_long_questions_and_cancellation_returns_no_action(reader):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QPlainTextEdit

    observed = []
    text = research_tasks.question('methods')

    def inspect():
        dialog = QApplication.activeModalWidget()
        try:
            editor = dialog.findChild(QPlainTextEdit)
            observed.append((editor.toPlainText(), editor.lineWrapMode(),
                             editor.horizontalScrollBar().maximum(), dialog.okButtonText()))
        finally:
            dialog.reject()

    QTimer.singleShot(50, inspect)
    result, accepted = ui.preview(reader, 'Methods', text)
    assert not accepted and result == text
    assert observed == [
        (text, QPlainTextEdit.LineWrapMode.WidgetWidth, 0, '\u5e36\u5165\u8349\u7a3f')]


@pytest.mark.parametrize('task,required', [
    ('methods', ('\u5be6\u8b49\u7814\u7a76', '\u7406\u8ad6\u7814\u7a76',
                 '\u8cea\u6027\u7814\u7a76', '\u901a\u7528\u5206\u6578')),
    ('replication', ('\u5c1a\u672a\u57f7\u884c', '\u540c\u4e00\u8cc7\u6599',
                     '\u7368\u7acb\u8cc7\u6599', '\u8b49\u660e', '\u8cea\u6027')),
    ('evidence', ('\u4e0d\u8db3', '\u4f5c\u8005', '\u63a8\u8ad6')),
])
def test_professional_task_draft_is_design_aware_and_stays_free(
    reader, monkeypatch, task, required,
):
    from paper_daily import llm

    monkeypatch.setattr(llm, 'complete', lambda *a, **k: pytest.fail('Draft called AI'))
    monkeypatch.setattr(llm, 'complete_result', lambda *a, **k: pytest.fail('Draft called AI'))
    previews = []

    def accept(_reader, _title, text):
        previews.append(text)
        return text, True

    monkeypatch.setattr(ui, 'preview', accept)
    ui.draft(reader, task)
    text = reader.ask_box.text()
    assert all(part in text for part in required)
    assert reader.drafted == previews == [text]
    assert research_tasks.EVIDENCE_RULES in text
    assert not store.DB_PATH.exists()
