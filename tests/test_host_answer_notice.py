"""An answer an agent host saves reaches the open reader as a notice, then on request."""

from test_reader_chat import reader as reader
from test_reader_preparation import settle
from test_research_chat import legacy as legacy
from test_saved_text_notice import ready as ready

from paper_daily import brief, local_operations

DIVE = "## 一句話結論\n" + "外部 agent 寫的講解。" * 100


def op(name, **arguments):
    result = local_operations.dispatch(name, arguments)
    assert result["ok"], result
    return result["result"]


def test_a_host_answer_is_announced_and_loaded_without_touching_drafts(ready):
    app, window, view, _document = ready
    asked = op("research.ask.task", paper_id="local-paper", question="Host question?")
    op("research.ask.save", request_id=asked["request_id"], answer="<answer>Host answer.</answer>")
    assert "Host answer." not in view.chat_view._body
    window.workspace_changes.poll()
    assert view.saved_text_notice.isVisible()
    assert "問答" in view.saved_text_notice.label.text()
    assert view.saved_text_notice.load_updates()
    settle(app, lambda: not view.preparation.busy)
    window.workspace_changes.poll()
    assert not view.saved_text_notice.isVisible()
    assert "Host question?" in view.chat_view._body and "Host answer." in view.chat_view._body
    assert view.ask_box.text() == "Unsent question draft"
    assert view.note_edit.toPlainText() == "Unsent note draft"


def test_a_host_deep_dive_is_announced_and_loaded(ready, monkeypatch):
    app, window, view, _document = ready
    monkeypatch.setattr(brief, "pack_text", lambda conn, row: ("pack", None))
    op("research.dive.save", paper_id="local-paper", body=DIVE)
    window.workspace_changes.poll()
    assert view.saved_text_notice.isVisible()
    assert "講解" in view.saved_text_notice.label.text()
    assert view.saved_text_notice.load_updates()
    settle(app, lambda: not view.preparation.busy)
    assert "外部 agent 寫的講解。" in view.dive_view._body
