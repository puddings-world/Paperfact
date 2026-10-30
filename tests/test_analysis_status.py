"""Analysis checks coalesce safely without source hashing on Qt's thread."""

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from test_research_compound import driver as driver
from test_research_generation import pdf
from test_research_generation import workspace as workspace

from paper_daily import analyze, store
from paper_daily.desktop import analysis_bar, analysis_status
from paper_daily.desktop.main import palette


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def settle(app, worker):
    assert worker.wait(5)
    for _ in range(5):
        app.processEvents()


def test_repeats_coalesce_and_only_latest_different_scope_is_applied(app):
    worker = analysis_status.LatestStatus()
    entered, release = threading.Event(), threading.Event()
    calls, applied = [], []

    def first():
        calls.append("first")
        entered.set()
        assert release.wait(5)
        return "stale"

    assert worker.run("one", first, applied.append)
    assert entered.wait(5)
    for _ in range(100):
        assert not worker.run("one", lambda: pytest.fail("duplicate"), applied.append)
    worker.run("two", lambda: calls.append("two") or "two", applied.append)
    worker.run("three", lambda: calls.append("three") or "three", applied.append)
    release.set()
    settle(app, worker)
    assert calls == ["first", "three"] and applied == ["three"]
    worker.close()


def test_failure_is_sanitized_and_can_retry(app):
    worker = analysis_status.LatestStatus()
    errors, applied = [], []
    worker.failed.connect(errors.append)

    def fail():
        raise ValueError("private question and token")

    worker.run("one", fail, applied.append)
    settle(app, worker)
    assert errors == ["Saved analysis could not be checked; please retry"] and not applied
    worker.run("one", lambda: "recovered", applied.append)
    settle(app, worker)
    assert applied == ["recovered"]
    worker.close()


def test_closing_while_active_never_applies_late_result(app):
    worker = analysis_status.LatestStatus()
    entered, release = threading.Event(), threading.Event()
    applied = []

    def work():
        entered.set()
        assert release.wait(5)
        return "late"

    worker.run("one", work, applied.append)
    assert entered.wait(5)
    worker.close()
    release.set()
    settle(app, worker)
    assert applied == []
    assert not worker.run("two", lambda: "closed", applied.append)


def make_bar(app, monkeypatch, document):
    monkeypatch.setattr(analyze, "PDF_DIR", document.path.parent)
    win = SimpleNamespace(analysis_running=lambda *args: False)
    bar = analysis_bar.AnalysisBar(win, palette())
    bar.show()
    app.processEvents()
    return bar


def test_actual_bar_reads_off_thread_and_applies_saved_citation_completion(
    app, driver, monkeypatch
):
    _path, _client, document, _calls, install, invoke = driver
    install("citations")
    assert invoke("citations") == 2
    bar = make_bar(app, monkeypatch, document)
    original = analyze.status
    threads = []

    def status(conn, paper_id, **kwargs):
        threads.append(threading.current_thread())
        return original(conn, paper_id, **kwargs)

    monkeypatch.setattr(analyze, "status", status)
    try:
        bar.show_paper("paper")
        settle(app, bar._status_worker)
        assert bar._state["cites"] is True
        assert threads and all(thread is not threading.current_thread() for thread in threads)
    finally:
        bar._status_worker.close()
        bar.close()


@pytest.mark.parametrize("change", ["source", "workspace", "paper", "close"])
def test_pending_bar_check_does_not_apply_to_replaced_context(app, workspace, monkeypatch, change):
    path, _client, document = workspace
    bar = make_bar(app, monkeypatch, document)
    entered, release = threading.Event(), threading.Event()

    def status(conn, paper_id, **kwargs):
        assert (
            kwargs["verify_sources"] and threading.current_thread() is not threading.main_thread()
        )
        entered.set()
        assert release.wait(5)
        return dict(pdf=True, dive=True, highlights=True, cites=True, later=True)

    monkeypatch.setattr(analyze, "status", status)
    try:
        bar.show_paper("paper")
        assert entered.wait(5)
        if change == "source":
            pdf(document.path, "Replacement document")
        elif change == "workspace":
            monkeypatch.setattr(store, "DB_PATH", path.with_name("other.sqlite"))
        elif change == "paper":
            bar.paper_id = "other"
        else:
            bar.close()
        release.set()
        settle(app, bar._status_worker)
        assert bar._state == {}
    finally:
        release.set()
        bar._status_worker.close()
        bar.close()
