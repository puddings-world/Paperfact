"""A selection arriving before queued figure initialization is not discarded."""

import pytest
from test_progressive_figures import hold_decode, start_owned, until
from test_progressive_figures import no_model as no_model
from test_progressive_figures import owned as owned


@pytest.mark.parametrize(
    "index, order", [(3, [1, 4, 2, 3]), (-1, [1, 2, 3, 4]), (99, [1, 2, 3, 4])]
)
def test_selection_before_gui_initialization_is_retained_or_rejected(
    owned, monkeypatch, index, order
):
    w = owned
    entered, release, _ = hold_decode(monkeypatch)
    begun, drawn = [], []
    initialize, entry = w.pane._begin_owned, w.pane._entry
    monkeypatch.setattr(w.pane, "_begin_owned", begun.append)
    monkeypatch.setattr(
        w.pane, "_entry", lambda fig, *args: drawn.append(fig.page) or entry(fig, *args)
    )
    try:
        start_owned(w)
        until(w.app, lambda: entered.is_set() and bool(begun))
        assert not w.pane._entries
        w.pane._toc.linkActivated.emit(str(index))
        initialize(begun[0])
    finally:
        release.set()
    until(w.app, lambda: not w.pane.busy)
    assert drawn == order
    assert all(item is not None for item in w.pane._entries)
