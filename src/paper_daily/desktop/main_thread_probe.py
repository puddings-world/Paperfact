"""Opt-in sampler of what the window's thread is busy with (PAPERFACT_PROBE=1).

Keys feel slow when the thread that draws the window and receives keys is busy
with something else. This samples that thread's Python stack from a side thread
and, once a minute, writes how busy it was and the code it was in to
`<data>/diagnostics/main-thread-<date>.log`. Nothing runs unless the variable is
set; it never uploads and records code locations only, never paper content.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

SAMPLE_SECONDS = 0.02
REPORT_SECONDS = 60
TOP = 15
OWN = ("paper_daily", "PySide6", "shiboken6")


def enabled(env=os.environ) -> bool:
    return env.get("PAPERFACT_PROBE") == "1"


def signature(frame, idle_code) -> str | None:
    """The busy stack as `file:function:line` frames, innermost last; None when idle.

    The thread is idle when its innermost Python frame is the event loop's caller:
    Qt is waiting for input and runs no Python code.
    """
    if frame is None or frame.f_code is idle_code:
        return None
    frames = []
    while frame is not None and frame.f_code is not idle_code:
        code = frame.f_code
        name = code.co_filename.replace("\\", "/")
        if any(part in name for part in OWN):
            short = name.rsplit("/", 1)[-1]
            frames.append(f"{short}:{code.co_name}:{frame.f_lineno}")
        frame = frame.f_back
    return " < ".join(frames[:8]) or "(other Python)"


def summarise(stamp: str, samples: int, busy: Counter, cpu_seconds: float | None,
              wall_seconds: float) -> str:
    total_busy = sum(busy.values())
    share = 100 * total_busy / samples if samples else 0
    cpu = (f"{100 * cpu_seconds / wall_seconds:.0f}%" if cpu_seconds is not None
           and wall_seconds > 0 else "unknown")
    lines = [f"{stamp} python-busy {share:.0f}% of {samples} samples; thread CPU {cpu}"]
    for stack, count in busy.most_common(TOP):
        lines.append(f"  {100 * count / samples:5.1f}%  {stack}")
    return "\n".join(lines) + "\n"


def _thread_cpu(native_id):
    """CPU seconds the thread has used, on Windows; None elsewhere or on failure."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.windll.kernel32
    handle = kernel.OpenThread(0x0800, False, native_id)  # THREAD_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    times = [wintypes.FILETIME() for _ in range(4)]
    ok = kernel.GetThreadTimes(handle, *[ctypes.byref(t) for t in times])
    kernel.CloseHandle(handle)
    if not ok:
        return None
    kernel_time, user_time = times[2], times[3]
    ticks = sum((t.dwHighDateTime << 32) | t.dwLowDateTime for t in (kernel_time, user_time))
    return ticks / 1e7


def start(idle_code, folder: Path) -> threading.Thread:
    """Sample the calling thread, whose event loop is entered from `idle_code`."""
    main = threading.get_ident()
    native = threading.get_native_id()
    folder.mkdir(parents=True, exist_ok=True)

    def run():
        busy, samples = Counter(), 0
        began, cpu_began = time.monotonic(), _thread_cpu(native)
        while True:
            time.sleep(SAMPLE_SECONDS)
            frame = sys._current_frames().get(main)
            if frame is None:
                return
            samples += 1
            stack = signature(frame, idle_code)
            if stack is not None:
                busy[stack] += 1
            now = time.monotonic()
            if now - began >= REPORT_SECONDS:
                cpu_now = _thread_cpu(native)
                used = cpu_now - cpu_began if None not in (cpu_now, cpu_began) else None
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                path = folder / f"main-thread-{stamp[:10]}.log"
                with path.open("a", encoding="utf-8") as log:
                    log.write(summarise(stamp, samples, busy, used, now - began))
                busy, samples, began, cpu_began = Counter(), 0, now, cpu_now

    thread = threading.Thread(target=run, name="main-thread-probe", daemon=True)
    thread.start()
    return thread
