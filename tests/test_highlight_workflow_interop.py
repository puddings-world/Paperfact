"""Generated layers and real local mark actions share user-owned hidden choices."""

from test_highlight_generation import QUOTES, capture
from test_highlight_generation import ready as _ready
from test_highlight_generation import workspace as _workspace

from paper_daily import llm, manual_highlight_ops

workspace = _workspace
ready = _ready


def view(ready):
    document = ready[2]
    return manual_highlight_ops.load(
        manual_highlight_ops.capture_owner(ready[0], "paper"),
        document.path,
        document.sha256,
        document=document,
    )


def test_real_manual_and_ai_marks_remain_independent_across_reselection(ready):
    assert capture(ready).run().status == "accepted"
    original = view(ready)
    automatic = original.marks[0]
    manual_highlight_ops.add(original, automatic["anchor"], automatic["quote"])
    both = view(ready)
    assert len(both.marks) == 2
    manual_highlight_ops.remove(both, [automatic["id"]])
    manual_highlight_ops.remove(both, [automatic["id"]])
    assert [mark["origin"] for mark in view(ready).marks] == ["manual"]
    ready[6][:] = [1]
    assert capture(ready).run().status == "accepted"
    current = view(ready).marks
    assert {(mark["origin"], mark["quote"]) for mark in current} == {
        ("manual", QUOTES[0]),
        ("ai", QUOTES[1]),
    }
    ready[6][:] = [0]
    assert capture(ready).run().status == "accepted"
    assert [(mark["origin"], mark["quote"]) for mark in view(ready).marks] == [
        ("manual", QUOTES[0])
    ]
    assert len(ready[5]) == 3


def test_actual_hide_during_ai_generation_retains_the_new_layer(ready, monkeypatch):
    assert capture(ready).run().status == "accepted"
    loaded = view(ready)
    job = capture(ready)
    original = llm.complete_result

    def hide(*args, **kwargs):
        response = original(*args, **kwargs)
        manual_highlight_ops.remove(loaded, [loaded.marks[0]["id"]])
        return response

    monkeypatch.setattr(llm, "complete_result", hide)
    assert job.run().status == "candidate"
    assert view(ready).marks == []
    assert len(ready[5]) == 2
