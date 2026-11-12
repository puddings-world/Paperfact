"""Deferred standalone material reads retain their destination and retire cleanly."""

import threading
import time
from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from test_presentation_pane import pane as pane

from paper_daily import materials, store


@pytest.mark.parametrize("change", ["paper", "workspace", "close"])
def test_late_deferred_materials_do_not_replace_another_context(pane, monkeypatch, change):
    widget, deck, app, tmp = pane
    widget.materials_button.setChecked(True)
    widget.hide()
    entered, release = threading.Event(), threading.Event()
    calls = []
    database = Path(store.DB_PATH).resolve()

    def collect(paper_id, *, database, paths):
        calls.append((paper_id, database, threading.current_thread() is threading.main_thread()))
        entered.set()
        assert release.wait(10)
        return materials.Materials(paper_id)

    monkeypatch.setattr(materials, "collect", collect)
    try:
        widget.load(deck.paper_id, "Original", defer=True)
        widget.show()
        deadline = time.monotonic() + 5
        while not entered.is_set() and time.monotonic() < deadline:
            QTest.qWait(5)
        assert entered.is_set()
        if change == "paper":
            widget.load("another-paper", "Another", defer=True)
        elif change == "workspace":
            monkeypatch.setattr(store, "DB_PATH", tmp / "another.sqlite")
        else:
            assert widget.close()
    finally:
        release.set()
        assert widget._materials_read.wait()
        app.processEvents()
    assert calls == [(deck.paper_id, database, False)]
    assert widget.materials_panel.paper_id is None
