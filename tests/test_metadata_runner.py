import os
import threading

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from paper_daily import llm
from paper_daily.desktop.ask import AskRunner


@pytest.fixture
def app(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    return QApplication.instance() or QApplication([])


def settle(runner):
    for _ in range(100):
        QTest.qWait(10)
        if not runner.busy:
            return
    pytest.fail("metadata result did not arrive")


def test_read_only_results_arrive_on_ui_thread_and_repeat_clicks_deduplicate(app):
    owner = QWidget()
    runner = AskRunner(owner, read_only=True)
    release = threading.Event()
    calls, results = [], []
    main = threading.get_ident()

    def query(_):
        calls.append(threading.get_ident())
        release.wait(2)
        return "metadata", "ok"

    for _ in range(25):
        runner.start("", lambda text: results.append((text, threading.get_ident())),
                     lambda reason: pytest.fail(reason), call=query)
    release.set()
    settle(runner)
    assert len(calls) == 1 and calls[0] != main
    assert results == [("metadata", main)]
    owner.deleteLater()


def test_cancelled_read_cannot_overwrite_new_selection(app):
    owner = QWidget()
    runner = AskRunner(owner, read_only=True)
    release, finished = threading.Event(), threading.Event()
    results = []

    def old(_):
        release.wait(2)
        finished.set()
        return "old account", "ok"

    runner.start("", results.append, results.append, call=old)
    runner.cancel_read()
    runner.start("", results.append, results.append, call=lambda _: ("new account", "ok"))
    settle(runner)
    release.set()
    assert finished.wait(2)
    QTest.qWait(50)
    assert results == ["new account"]
    owner.deleteLater()


def test_destroying_view_during_query_does_not_deliver_to_deleted_widgets(app):
    owner = QWidget()
    runner = AskRunner(owner, read_only=True)
    release, finished = threading.Event(), threading.Event()
    results = []

    def query(_):
        release.wait(2)
        finished.set()
        return "late metadata", "ok"

    runner.start("", results.append, results.append, call=query)
    runner.cancel_read()
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    release.set()
    assert finished.wait(2)
    app.processEvents()
    assert results == []


def test_metadata_exception_is_safe_and_retry_works(app):
    owner = QWidget()
    runner = AskRunner(owner, read_only=True)
    failures, successes = [], []

    def fail(_):
        raise ValueError("private upstream error")

    runner.start("", successes.append, failures.append, call=fail)
    settle(runner)
    assert failures and "private" not in failures[0]
    runner.start("", successes.append, failures.append, call=lambda _: ("recovered", "ok"))
    settle(runner)
    assert successes == ["recovered"]
    owner.deleteLater()
