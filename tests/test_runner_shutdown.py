"""Completing a worker must not require another GUI event before joining it."""

import os
import threading

import pytest
from PySide6.QtWidgets import QApplication

from paper_daily.desktop.ask import AskRunner

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.mark.parametrize("answer", ["ready", None])
def test_completed_worker_exits_even_while_gui_is_waiting(answer):
    app = QApplication.instance() or QApplication([])
    main = threading.get_ident()
    seen = []
    runner = AskRunner()
    runner.start(
        "",
        lambda value: seen.append((value, threading.get_ident())),
        lambda reason: seen.append((reason, threading.get_ident())),
        call=lambda _: (answer, "fixture failure"),
    )
    try:
        # Do not pump UI events. The worker must stop independently of queued UI
        # callbacks; this reliably fails with an auto/queued connection to quit.
        assert runner._thread.wait(2000), "Completed worker is waiting for the GUI to stop it"
        assert not seen
        assert runner.busy, "Busy must include the queued result, not just thread lifetime"
        runner.start(
            "duplicate",
            lambda _v: seen.append("wrong"),
            lambda _r: seen.append("wrong"),
            call=lambda _: ("duplicate", "ok"),
        )
        app.processEvents()
        assert seen == [(answer or "fixture failure", main)]
        assert not runner.busy
    finally:
        runner._thread.quit()
        runner._thread.wait(2000)
