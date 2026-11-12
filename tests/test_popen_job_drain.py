"""Native lifecycle contract with stdlib fake pipes; no Qt or subprocesses."""
import io
import subprocess
import threading
from types import SimpleNamespace

import pytest

from paper_daily.desktop.popen_job import Handoff, watch_detached


class HeldNativeProcess:
    def __init__(self, mode="timeout"):
        self.stdin = io.BytesIO()
        self.stdout = io.StringIO("invalid startup control\n")
        self.mode = mode
        self.returncode = None
        self.kill_calls = self.wait_calls = self.poll_calls = 0
        self.boundary = threading.Event()
        self.exited = threading.Event()
        self.output_event = threading.Event()
        self._output_done = False
        self.first_timeout = None

    @property
    def _paperfact_output_done(self):
        return self._output_done

    @_paperfact_output_done.setter
    def _paperfact_output_done(self, value):
        self._output_done = value
        self.output_event.set()
        self.boundary.set()

    def poll(self):
        self.poll_calls += 1
        return self.returncode

    def kill(self):
        # Termination is requested, not acknowledged. Native exit stays held.
        self.kill_calls += 1

    def terminate(self):
        self.returncode = 1
        self.exited.set()

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.wait_calls == 1:
            self.first_timeout = timeout
            if self.mode == "timeout":
                raise subprocess.TimeoutExpired("synthetic", timeout)
            if self.mode == "early":
                return 0
            raise OSError("synthetic native observation failed")
        self.boundary.set()
        if self.mode == "persistent_error" and not self.exited.is_set():
            raise OSError("synthetic native observation still unavailable")
        self.exited.wait()
        return self.returncode


@pytest.mark.parametrize("mode", ["timeout", "oserror", "early", "persistent_error"])
def test_failed_reap_stays_owned_until_actual_native_exit(mode):
    process = HeldNativeProcess(mode)
    handoff = Handoff(process, "a" * 32, b"private synthetic frame", 20)
    process._paperfact_ai_handoff = handoff
    watch_detached(process)
    try:
        assert process.boundary.wait(10), "reader did not reach native boundary"
        assert process.poll() is None
        assert isinstance(process.first_timeout, (int, float))
        assert 0 < process.first_timeout <= 5
        assert handoff.failed and process.kill_calls > 0
        assert not handoff.done
        assert not process._paperfact_output_done
        assert not handoff._frame
        if mode == "persistent_error":
            # Deliberately hold the native state; a coarse caller-observable
            # budget detects a tight observation loop without an exact interval.
            assert not process.exited.wait(.35)
            assert process.wait_calls < 30
            assert process.poll_calls < 60
        process.terminate()  # Cancellation remains usable while native wait owns it.
        assert process.output_event.wait(10), "reader did not acknowledge actual exit"
        assert process.poll() == 1
        assert handoff.done and process._paperfact_output_done
        assert not handoff._timer.is_alive()
        assert process.stdin.closed and process.stdout.closed
    finally:
        process.terminate()
        assert process.output_event.wait(10)
        handoff._timer.cancel()
        handoff._timer.join(timeout=10)


def test_detached_reader_does_not_infer_terminal_from_read_return():
    process = HeldNativeProcess()
    process._paperfact_ai_handoff = SimpleNamespace(done=False, read=lambda update: None)
    watch_detached(process)
    assert process.output_event.wait(10)
    assert process.poll() is None
    assert not process._paperfact_output_done
    process.terminate()


def test_already_admitted_deadline_callback_cannot_kill_ready_child():
    from paper_daily.cli_job_protocol import hello_line, ready_line

    class ReadyProcess(HeldNativeProcess):
        def __init__(self):
            super().__init__()
            self.stdout = io.StringIO((hello_line("a" * 32) + ready_line("a" * 32)).decode())

        def wait(self, timeout=None):
            self.boundary.set()
            self.exited.wait()
            return self.returncode

    process = ReadyProcess()
    handoff = Handoff(process, "a" * 32, b"synthetic private frame", 20)
    process._paperfact_ai_handoff = handoff
    watch_detached(process)
    try:
        assert process.boundary.wait(10)
        assert handoff.ready and not handoff.done and process.poll() is None
        # Timer.run can already have admitted its callback just before cancel().
        # Deliver that callback after ready, without sleeping or changing clocks.
        handoff._timer.function()
        assert not handoff.failed and process.kill_calls == 0
        assert not handoff.done and not process._paperfact_output_done
    finally:
        process.terminate()
        assert process.output_event.wait(10)
        assert handoff.done and not handoff._timer.is_alive()
