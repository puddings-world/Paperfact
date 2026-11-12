"""Context state changes render a useful action without invoking AI."""

import pytest
from PySide6.QtWidgets import QLabel, QPushButton
from test_cites_views import pane as pane


@pytest.mark.parametrize(
    "state,expected,button",
    [
        ({"untold": True}, "沒有可整理", False),
        ({"why": "服務暫時無法連線"}, "上次沒有完成", True),
        ({"partial": True}, "分析參考文獻", True),
    ],
)
def test_context_card_renders_observed_state_and_action(pane, state, expected, button):
    pane._data = state
    card = pane._story(None, [{"verdict": "略過"}], [], "now")
    text = " ".join(label.text() for label in card.findChildren(QLabel))
    assert expected in text
    actions = [item for item in card.findChildren(QPushButton) if item.text() == "深入分析"]
    assert bool(actions) == button
    card.close()
    pane.close()
