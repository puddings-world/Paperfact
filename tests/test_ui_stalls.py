"""A frozen window leaves a record of where the GUI thread was stuck."""

import threading
import time

import pytest

from paper_daily import ui_stalls


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def _busy_thread():
    """A thread parked inside a recognisable function, standing in for the GUI."""
    ready, release = threading.Event(), threading.Event()

    def slow_render_of_the_notes():
        ready.set()
        release.wait(5)

    thread = threading.Thread(target=slow_render_of_the_notes)
    thread.start()
    ready.wait(5)
    return thread, release


def test_a_stall_is_written_once_with_the_stuck_function(tmp_path):
    thread, release = _busy_thread()
    clock = Clock()
    watch = ui_stalls.Watchdog(
        tmp_path / "ui-stalls.log", thread_id=thread.ident, clock=clock, prefix=__name__
    )
    try:
        watch.heartbeat()
        clock.now += 0.1
        watch.check()
        assert not (tmp_path / "ui-stalls.log").exists()
        for _ in range(5):
            clock.now += 0.2
            watch.check()
        clock.now += 0.05
        watch.heartbeat()
        watch.check()
    finally:
        release.set()
        thread.join()
    log = (tmp_path / "ui-stalls.log").read_text(encoding="utf-8")
    assert log.count(" stall ") == 1 and "stall 1150 ms" in log
    assert "slow_render_of_the_notes" in log
    # Steady beats afterwards add nothing.
    watch.check()
    assert (tmp_path / "ui-stalls.log").read_text(encoding="utf-8") == log


def test_the_log_stays_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_stalls, "LIMIT", 200)
    path = tmp_path / "ui-stalls.log"
    path.write_text("x" * 300, encoding="utf-8")
    watch = ui_stalls.Watchdog(path, thread_id=threading.get_ident())
    watch.samples[("paper_daily.desktop.main:ReaderPage.load:1",)] = 1
    watch.stall_started = watch.beat
    watch._write(0.4)
    assert path.with_name("ui-stalls.log.1").read_text(encoding="utf-8") == "x" * 300
    assert "ReaderPage.load" in path.read_text(encoding="utf-8")


def test_a_running_watchdog_records_a_real_freeze(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_stalls, "THRESHOLD", 0.05)
    watch = ui_stalls.Watchdog(tmp_path / "ui-stalls.log", prefix=__name__)
    watch.start()
    try:
        time.sleep(0.3)  # the main thread is "the GUI" and stops beating
        # Beat steadily afterwards, as the GUI does: on a loaded machine the watcher
        # may first wake after one lone beat has already gone stale.
        end = time.monotonic() + 2
        while not (tmp_path / "ui-stalls.log").exists() and time.monotonic() < end:
            watch.heartbeat()
            time.sleep(0.01)
    finally:
        watch.stop()
    assert "test_a_running_watchdog_records_a_real_freeze" in (
        tmp_path / "ui-stalls.log"
    ).read_text(encoding="utf-8")


def _stall(watch, clock, seconds=0.6):
    watch.heartbeat()
    while seconds > 0:
        clock.now += 0.2
        seconds -= 0.2
        watch.check()
    watch.heartbeat()
    watch.check()


def test_a_stall_names_what_happened_just_before_it(tmp_path):
    clock = Clock()
    watch = ui_stalls.Watchdog(
        tmp_path / "ui-stalls.log", thread_id=threading.get_ident(), clock=clock
    )
    watch.widgets = 1834
    clock.now += 3 * 3600
    watch.note("fonts-changed")  # long before: not this stall's cause
    clock.now += 30
    watch.note("app-active")
    clock.now += 1
    watch.note("screen-changed")
    watch.note("a paper title")  # never written: only the fixed vocabulary is
    clock.now += 2
    _stall(watch, clock)
    log = (tmp_path / "ui-stalls.log").read_text(encoding="utf-8")
    context = [line for line in log.splitlines() if line.startswith("  context ")]
    assert context == [
        "  context state=active open=3.0h widgets=1834 "
        "before=app-active@-3.0s,screen-changed@-2.0s"
    ]
    assert "paper title" not in log


def test_a_stall_in_the_background_says_so(tmp_path):
    clock = Clock()
    watch = ui_stalls.Watchdog(
        tmp_path / "ui-stalls.log", thread_id=threading.get_ident(), clock=clock
    )
    watch.note("app-inactive")
    clock.now += 60
    _stall(watch, clock)
    assert "  context state=inactive open=0.0h widgets=? before=-" in (
        tmp_path / "ui-stalls.log"
    ).read_text(encoding="utf-8")


def test_the_support_report_keeps_only_the_known_context(tmp_path):
    from paper_daily import diagnostics

    (tmp_path / "ui-stalls.log").write_text(
        "2026-10-29T09:55:14 stall 8173 ms (stack in 216/235 samples)\n"
        "  paper_daily.desktop.main:run:3229\n"
        "  context state=active open=11.2h widgets=2210 "
        "before=screen-changed@-1.5s,my-secret-list@-1.0s\n"
        "2026-10-29T09:56:00 stall 300 ms (stack in 1/1 samples)\n"
        "  paper_daily.desktop.main:run:3229\n"
        "  context state=private open=x widgets=1 before=-\n",
        encoding="utf-8",
    )
    first, second = diagnostics.collect(tmp_path)["ui_stalls"]
    assert first["context"] == {
        "state": "active",
        "open_hours": 11.2,
        "widgets": 2210,
        "before": [{"event": "screen-changed", "seconds_before": 1.5}],
    }
    assert second["context"] is None
    assert "secret" not in diagnostics.render(diagnostics.collect(tmp_path))


def test_the_installed_watchdog_follows_the_window_system(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    watch = ui_stalls.install(tmp_path, window)
    try:
        assert watch.widgets and watch.widgets >= 1
        window.resize(300, 200)
        window.show()
        window.resize(500, 400)
        app.processEvents()
        app.fontDatabaseChanged.emit()
        events = [event for _at, event in watch.recent]
        assert "window-resized" in events and "fonts-changed" in events
        assert events.count("window-resized") == 1  # one note per second of resizing
    finally:
        watch.stop()
        window.close()
        window.deleteLater()
