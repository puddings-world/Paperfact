"""Platform button metrics must not force the verified preview off a narrow screen."""

import pytest
from test_question_adoption_ui import (  # noqa: F401
    old_questions,
    ready,
    verified,
    workspace,
)
from test_question_adoption_ui import (
    view as _view,
)

view = _view


@pytest.mark.parametrize("width", [600, 940])
def test_all_adoption_actions_wrap_with_wider_platform_buttons(view, width):
    app, widget, *_ = view
    widget.browser.setStyleSheet("QPushButton { min-width: 170px; padding: 8px; }")
    verified(view)
    widget.browser.resize(width, 500)
    app.processEvents()
    assert widget.browser.width() <= width
    assert widget.browser.height() <= 500
    actions = (widget.verify_in_browser, widget.adopt_button, widget.cancel, widget.insert)
    for button in actions:
        assert button.isVisible() and button.isEnabled()
        assert widget.browser.rect().contains(button.geometry())
    for index, button in enumerate(actions):
        for other in actions[index + 1:]:
            assert not button.geometry().intersects(other.geometry())
    assert widget.details_scroll.viewport().height() > 60
