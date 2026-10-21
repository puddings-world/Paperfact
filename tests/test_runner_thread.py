"""A model call's callback must come back on the GUI thread.

Qt picks a connection type from the receiver. A bound method of a QObject is
delivered on that object's thread; a plain function or lambda has no thread
affinity and is connected directly, so it runs on the worker. A callback that
touches a widget then draws from outside the GUI thread, which aborts the process
with no Python traceback at all -- which is what pressing 翻譯 used to do, because
that one call site passed lambdas while every other passed bound methods.
"""

import os
import threading

import pytest

pytest.importorskip("PySide6", reason="the desktop reader is an optional extra")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from paper_daily import llm  # noqa: E402
from paper_daily.desktop.ask import AskRunner  # noqa: E402


@pytest.fixture
def app():
    existing = QApplication.instance()
    yield existing or QApplication([])


@pytest.mark.parametrize("answer", ["an answer", ""])
def test_callbacks_arrive_on_the_gui_thread(app, monkeypatch, answer):
    """Both paths: a reply, and a failure. A lambda must be as safe as a method."""
    monkeypatch.setattr(
        llm,
        "complete",
        lambda prompt, system=None, timeout=300, cfg=None, **kwargs: (answer, "no key"),
    )
    monkeypatch.setattr(llm, "describe", lambda *a, **k: "test backend")

    gui = threading.current_thread()
    seen: list[threading.Thread] = []
    runner = AskRunner()
    runner.start(
        "q",
        lambda _a: seen.append(threading.current_thread()),
        lambda _r: seen.append(threading.current_thread()),
    )

    QTimer.singleShot(5000, app.quit)
    while not seen and runner.busy:
        app.processEvents()
    app.processEvents()

    # The callback arrives while the worker thread is still winding down. The
    # runner is local here, so letting it be collected now would destroy a running
    # QThread, which aborts the whole test process at a random later test.
    runner._thread.wait()

    assert seen, "the callback never fired"
    assert seen[0] is gui


def test_background_job_uses_connections_from_start_not_current_selection(
    app, monkeypatch, tmp_path
):
    from paper_daily.desktop.ask import AskWorker

    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.delenv("PAPERFACT_PROFILE", raising=False)
    monkeypatch.delenv("PAPER_DAILY_PROFILE", raising=False)
    llm.save_settings(profile="a", backend="openai", model="first", isolated=True)
    llm.save_settings(profile="b", backend="openai", model="second", isolated=True)
    worker = AskWorker("", call=lambda _: (llm.settings().model, "ok"))
    llm.use_profile("b", desktop=True)
    results = []
    worker.finished.connect(results.append)
    worker.run()
    assert results == ["first"]
    assert llm.settings().model == "second"


def test_custom_job_exception_reports_failure_and_releases_busy_state(app):
    from PySide6.QtTest import QTest

    def fail(_prompt):
        raise OSError("private diagnostic")

    failures = []
    runner = AskRunner()
    runner.start("", lambda value: pytest.fail("must not succeed"), failures.append, call=fail)
    try:
        for _ in range(100):
            QTest.qWait(10)
            if failures and not runner.busy:
                break
        assert failures and "OSError" in failures[0]
        assert "private diagnostic" not in failures[0]
        assert not runner.busy
    finally:
        runner._thread.quit()
        runner._thread.wait(3000)
