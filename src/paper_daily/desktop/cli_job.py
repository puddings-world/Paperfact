"""Nonblocking, per-QProcess private AI-job startup; no credentials in argv/env."""
from __future__ import annotations

from uuid import uuid4

from PySide6.QtCore import QObject, QProcess, QTimer

from paper_daily import llm, runtime
from paper_daily.cli_job_protocol import (
    MAX_CONTROL_BYTES,
    JobProtocolError,
    encode_frame,
    parse_control_line,
)


class JobHandoff(QObject):
    """Own one process's bounded startup buffer, deadline and route frame."""

    def __init__(self, process, intent, *, timeout_ms=30_000):
        super().__init__(process)
        self.process = process
        self.identity = intent.request_id
        self._frame = encode_frame(intent)
        self._offset = 0
        self._pending = b""
        self.phase = "hello"
        self.failed = False
        self._reported = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._fail)
        process.bytesWritten.connect(self._write)
        process.errorOccurred.connect(self._error)
        process.finished.connect(self._finished)
        self.timer.start(timeout_ms)

    def _fail(self):
        if self.failed:
            return
        self.failed = True
        self.timer.stop()
        self._frame = self._pending = b""
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()

    def _write(self, *_):
        if self.failed or self.phase != "ready" or not self._frame:
            return
        count = self.process.write(self._frame[self._offset:])
        if count < 0 or count > len(self._frame) - self._offset:
            self._fail()
            return
        self._offset += count
        if self._offset == len(self._frame):
            self._frame = b""
            self.process.closeWriteChannel()

    def filter_output(self, chunk):
        """Return user output only after ready; control frames never reach the UI."""
        if not self.failed and self.phase == "running":
            return chunk
        if not self.failed:
            offset = 0
            while not self.failed and self.phase != "running" and offset < len(chunk):
                # Do not duplicate an arbitrary startup-output chunk into our buffer.
                budget = MAX_CONTROL_BYTES - len(self._pending)
                part = chunk[offset:offset + budget]
                line, separator, _rest = part.partition(b"\n")
                consumed = len(line) + len(separator)
                self._pending += part[:consumed]
                offset += consumed
                if not separator:
                    if len(self._pending) >= MAX_CONTROL_BYTES:
                        self._fail()
                    break
                try:
                    parse_control_line(self._pending, expected_request_id=self.identity,
                                       expected_phase=self.phase)
                except JobProtocolError:
                    self._fail()
                    break
                self._pending = b""
                if self.phase == "hello":
                    self.phase = "ready"
                    self._write()
                elif self._frame:
                    self._fail()
                else:
                    self.phase = "running"
                    self.timer.stop()
            if not self.failed and self.phase == "running":
                return chunk[offset:]
        if self.failed and not self._reported:
            self._reported = True
            return b"AI job startup failed; please retry.\n"
        return b""

    def cancel(self):
        """Release private startup state and stop this process, never another job."""
        self._fail()

    def _error(self, _error):
        self._fail()

    def _finished(self, *_):
        if self.phase != "running":
            self.failed = True
        self.timer.stop()
        self._frame = self._pending = b""

    def complete(self, code):
        result = code if self.phase == "running" and not self.failed else 2
        self._finished()
        return result


def prepare(process, command, tasks):
    """Bind final logical argv without rereading outside the admitted UI scope."""
    intent = llm.freeze_connections(tasks).bind(uuid4().hex, tuple(command))
    handoff = JobHandoff(process, intent)
    process._ai_job_handoff = handoff
    return runtime.cli_command("_desktop-job-v1", intent.request_id, *command)
