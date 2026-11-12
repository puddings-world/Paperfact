"""Native choice is captured in one job command, including rapid activation."""

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QComboBox, QPushButton
from test_cites_views import pane as pane

from paper_daily.desktop import ai_access, cites_pane


@pytest.mark.parametrize("count", [0, 1, 2])
def test_choice_is_captured_and_pending_work_is_not_repeated(pane, monkeypatch, count):
    monkeypatch.setattr(ai_access, "_bridge", None)
    calls = []
    process = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(cites_pane, "_spawn", lambda *args: calls.append(args) or process)
    monkeypatch.setattr(pane, "_reload", lambda: None)
    panel = pane._citation_controls()
    choice = panel.findChild(QComboBox, "citation-completion-budget")
    go = panel.findChild(QPushButton, "citation-analysis-start")
    assert choice.currentData() == 0
    choice.setCurrentIndex(count)
    go.click()
    choice.setCurrentIndex((count + 1) % 3)
    for _ in range(10):
        go.click()
    expected = ("cites", "p") + (("--completion-calls", str(count)) if count else ())
    assert calls == [expected]
    pane.close()


def test_old_controls_do_not_start_after_paper_change(pane, monkeypatch):
    monkeypatch.setattr(cites_pane, "_spawn", lambda *a: pytest.fail("old controls launched"))
    panel = pane._citation_controls()
    pane.paper_id = "different"
    panel.findChild(QPushButton, "citation-analysis-start").click()
    pane.close()
