"""Private CLI startup on the existing stdout reader; no GUI pipe I/O."""
from __future__ import annotations

import subprocess
import threading
import time
from contextlib import suppress
from uuid import uuid4

from paper_daily import llm, runtime, work_progress
from paper_daily.cli_job_protocol import MAX_CONTROL_BYTES, encode_frame, parse_control_line

STARTUP_SECONDS = 30
FAILURE = "AI job startup failed; please retry."


def command_tasks(command):
    """Declare every nested completion; ordinary commands retain ordinary stdin."""
    name = command[0] if command else ""
    if name in ("analyze", "analyse"):
        from paper_daily.desktop.ai_access import ANALYSIS_TASKS
        return ANALYSIS_TASKS
    if name == "dive-ahead":
        return ("dive",)
    if name == "cites":
        return ("citations",)
    if name == "followups":
        return (("followups", "overview", "citations") if "--with-cites" in command
                else ("followups", "overview"))
    if name == "list-add" and len(command) > 2:
        from paper_daily.lists import needs_ai_parse
        if needs_ai_parse(command[2]):
            return ("list_parse",)
    return ()


class Handoff:
    """Exactly one process, watchdog and stdout consumer; payload never logged."""
    def __init__(self, process, identity, frame, timeout):
        if (not all(callable(getattr(process, name, None)) for name in ("poll", "kill", "wait"))
                or getattr(process, "stdin", None) is None
                or getattr(process, "stdout", None) is None):
            raise ValueError(FAILURE)
        self.process, self.identity = process, identity
        self._frame = frame
        self._lock = threading.Lock()
        self.ready = self.failed = self.done = False
        self.phase = "hello"
        self.milestones = {"started": time.monotonic()}
        self._timer = threading.Timer(timeout, self._startup_timeout)
        self._timer.daemon = True
        self._timer.start()

    def __repr__(self):
        return "<PrivatePopenHandoff>"

    def _startup_timeout(self):
        self.fail(startup_only=True)

    def fail(self, *, startup_only=False):
        with self._lock:
            if self.done or (startup_only and self.ready):
                return
            self.failed = True
            self.milestones.setdefault("failed", time.monotonic())
            self._frame = b""
        try:
            if self.process.poll() is None:
                self.process.kill()
        except OSError:
            pass

    def read(self, update):
        """Called only by the sole background reader; watchdog bounds startup I/O."""
        try:
            for phase in ("hello", "ready"):
                line = self.process.stdout.readline(MAX_CONTROL_BYTES + 1)
                raw = line.encode("ascii") if isinstance(line, str) else line
                parse_control_line(raw, expected_request_id=self.identity, expected_phase=phase)
                if self.failed:
                    raise ValueError("startup stopped")
                if phase == "hello":
                    self.phase = "frame"
                    self.milestones["hello"] = time.monotonic()
                    with self._lock:
                        frame, self._frame = self._frame, b""
                    if not frame:
                        raise ValueError("startup stopped")
                    try:
                        pipe = getattr(self.process.stdin, "buffer", self.process.stdin)
                        offset = 0
                        while offset < len(frame):
                            count = pipe.write(frame[offset:])
                            if type(count) is not int or not 0 < count <= len(frame) - offset:
                                raise ValueError("invalid write")
                            offset += count
                        pipe.flush()
                        self.phase = "ready"
                        self.milestones["frame_sent"] = time.monotonic()
                    finally:
                        frame = b""
                        self.process.stdin.close()
            with self._lock:
                if self.failed:
                    raise ValueError("startup stopped")
                self.ready = True
                self.phase = "running"
                self.milestones["ready"] = time.monotonic()
                self._timer.cancel()
            for line in self.process.stdout:
                event = work_progress.parse(line.strip())
                if event:
                    update(event)
        except (OSError, ValueError, UnicodeError, AttributeError, TypeError):
            self.fail()
        finally:
            self._timer.cancel()
            self._frame = b""
            if not self.ready:
                self.fail()
                update(dict(stage=FAILURE, outcome="error"))
            for stream in (self.process.stdin, self.process.stdout):
                with suppress(OSError, ValueError, AttributeError):
                    stream.close()
            # A failed startup was killed above. Reap off GUI; no native handles
            # remain solely because a zero-exit child omitted the ready receipt.
            self._reap()
            self._timer.join()
            self.done = True
            self.milestones["drained"] = time.monotonic()

    def _native_terminal(self):
        try:
            return type(self.process.poll()) is int
        except OSError:
            return False

    def _reap(self):
        # A bounded observation timeout is not a native-exit receipt. Keep the
        # sole reader owned until the exact process really exits. A normal wait
        # blocks without polling; observation errors back off without kill loops.
        try:
            self.process.wait(timeout=5 if self.failed else None)
        except (OSError, subprocess.TimeoutExpired):
            self.fail()
        if self._native_terminal():
            return
        pause = threading.Event()
        while True:
            with suppress(OSError, subprocess.TimeoutExpired):
                self.process.wait()
            if self._native_terminal():
                return
            pause.wait(.25)

    def effective_code(self, code):
        return code if self.ready and not self.failed else 2


def launch(command, *, popen=None, timeout=STARTUP_SECONDS, **options):
    """Freeze under the original callback scope, before evaluating CLI argv."""
    command = tuple(command)
    tasks = command_tasks(command)
    if not tasks:
        return (popen or subprocess.Popen)(runtime.cli_command(*command), **options)
    intent = llm.freeze_connections(tasks).bind(uuid4().hex, tuple(command))
    frame = encode_frame(intent)
    identity = intent.request_id
    del intent
    try:
        argv = runtime.cli_command("_desktop-job-v1", identity, *command)
        options.update(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8", errors="replace")
        process = (popen or subprocess.Popen)(argv, **options)
        process._paperfact_ai_handoff = Handoff(process, identity, frame, timeout)
        return process
    finally:
        frame = b""


def watch_detached(process):
    """Cites launches had no reader. Give private children exactly one drain."""
    if not hasattr(process, "_paperfact_ai_handoff"):
        return
    if getattr(process, "_paperfact_reader_started", False):
        return
    process._paperfact_reader_started = True
    def read():
        try:
            process._paperfact_ai_handoff.read(lambda _event: None)
        finally:
            process._paperfact_output_done = process._paperfact_ai_handoff.done
    threading.Thread(target=read, daemon=True).start()
