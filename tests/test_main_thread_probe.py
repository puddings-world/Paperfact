"""The opt-in probe that says what keeps the window's thread busy."""

import sys
import threading
import time
from collections import Counter

from paper_daily.desktop import main_thread_probe as probe


def test_the_probe_is_off_unless_asked_for():
    assert not probe.enabled({})
    assert not probe.enabled({"PAPERFACT_PROBE": "0"})
    assert probe.enabled({"PAPERFACT_PROBE": "1"})


def _loop_caller(entered, release):
    def busy_slot():
        entered.set()
        release.wait(5)

    busy_slot()


def test_a_thread_waiting_in_its_loop_is_idle_and_one_running_code_is_busy():
    idle_code = _loop_caller.__code__
    assert probe.signature(None, idle_code) is None

    entered, release = threading.Event(), threading.Event()
    worker = threading.Thread(target=_loop_caller, args=(entered, release))
    worker.start()
    entered.wait(5)
    time.sleep(0.05)
    frame = sys._current_frames()[worker.ident]
    stack = probe.signature(frame, idle_code)
    release.set()
    worker.join()
    # Only the code above the loop's caller counts, innermost first; this test file
    # is not app code, so it is reported without its frames.
    assert stack == "(other Python)"


def test_the_minute_report_gives_the_busy_share_and_the_busiest_code_first():
    busy = Counter({"queue_view.py:refresh:10": 30, "activity.py:tick:5": 10})
    text = probe.summarise("2026-11-03 11:00:00", 100, busy, 6.0, 60.0)
    first, second, third = text.splitlines()
    assert first == "2026-11-03 11:00:00 python-busy 40% of 100 samples; thread CPU 10%"
    assert second.endswith("queue_view.py:refresh:10") and "30.0%" in second
    assert third.endswith("activity.py:tick:5")
    assert "unknown" in probe.summarise("t", 0, Counter(), None, 60.0)
