"""A frozen window leaves a record of where the GUI thread was stuck."""

import threading
import time

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
        watch.heartbeat()
        time.sleep(0.1)
    finally:
        watch.stop()
    assert "test_a_running_watchdog_records_a_real_freeze" in (
        tmp_path / "ui-stalls.log"
    ).read_text(encoding="utf-8")
