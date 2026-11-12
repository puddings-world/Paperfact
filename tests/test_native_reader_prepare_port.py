"""Maintained master reader promises through actual owned native preparation."""

import threading

from PySide6.QtCore import QTimer
from test_reader_ai_scope import asking as _asking
from test_reader_prepare import _settle_owned
from test_reader_prepare import window as _window

from paper_daily import reader_saved_inputs as saved
from paper_daily.desktop import reading

window = _window
asking = _asking


def test_saved_dive_yields_to_native_drafts_while_actual_input_read_is_held(window, monkeypatch):
    win, app = window
    reader = win.reader_page
    win.open_paper("a")
    _settle_owned(reader.preparation, app)
    assert "Dive of the first paper." in reader.dive_view._body
    entered, release = threading.Event(), threading.Event()
    original = saved.read

    def read(*args, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(saved, "read", read)
    win.open_paper("b")
    try:
        assert entered.wait(5) and reader.preparation.busy
        beats = []
        QTimer.singleShot(0, reader, lambda: beats.append(reader.preparation.busy))
        app.processEvents()
        assert beats == [True]
        assert reader.paper.id == "b" and reader.pdf.position_identity()[1].name == "b.pdf"
        assert "Dive of the first paper." not in reader.dive_view._body
        reader.ask_box.setText("Unsent current question")
        reader.note_edit.setPlainText("Unsent current note")
    finally:
        release.set()
    _settle_owned(reader.preparation, app)
    assert "Dive of the second paper." in reader.dive_view._body
    assert reader.ask_box.text() == "Unsent current question"
    assert reader.note_edit.toPlainText() == "Unsent current note"


def test_abandoned_actual_held_typesetting_never_replaces_next_native_paper(window, monkeypatch):
    win, app = window
    reader = win.reader_page
    entered, release = threading.Event(), threading.Event()
    original = reading.render

    def render(body, *args, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        if "Method A" in body:
            entered.set()
            assert release.wait(10)
        return original(body, *args, **kwargs)

    monkeypatch.setattr(reading, "render", render)
    win.open_paper("a")
    try:
        assert entered.wait(5) and reader.preparation.busy
        win.open_paper("b")
        reader.ask_box.setText("Question for B")
        reader.note_edit.setPlainText("Note for B")
    finally:
        release.set()
    _settle_owned(reader.preparation, app)
    assert reader.paper.id == "b" and reader.pdf.position_identity()[1].name == "b.pdf"
    assert "Dive of the second paper." in reader.dive_view._body
    assert "Dive of the first paper." not in reader.dive_view._body
    assert reader.ask_box.text() == "Question for B"
    assert reader.note_edit.toPlainText() == "Note for B"


def test_saved_real_chat_yields_without_another_model_call_or_discarding_drafts(
    asking, monkeypatch
):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._ask("Question for original A")
    calls[0][1]("Actual retained answer for A")
    _settle_owned(reader.preparation, app)
    assert "Actual retained answer for A" in reader.chat_view._body
    entered, release = threading.Event(), threading.Event()
    original = saved.read

    def read(*args, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(saved, "read", read)
    reader._load_chat()
    try:
        assert entered.wait(5) and reader.preparation.busy
        beats = []
        QTimer.singleShot(0, reader, lambda: beats.append(reader.preparation.busy))
        app.processEvents()
        assert beats == [True]
        reader.ask_box.setText("Unsent next question")
        reader.note_edit.setPlainText("Unsent note")
    finally:
        release.set()
    _settle_owned(reader.preparation, app)
    assert "Actual retained answer for A" in reader.chat_view._body
    assert len(calls) == 1
    assert [(row["role"], row["body"]) for row in win.data.chat("a")] == [
        ("user", "Question for original A"), ("assistant", "Actual retained answer for A")
    ]
    assert reader.ask_box.text() == "Unsent next question"
    assert reader.note_edit.toPlainText() == "Unsent note"
