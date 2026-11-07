"""Actual private child startup and bounded malformed/partial pipe handling."""
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from paper_daily import llm
from paper_daily.ai_job_intent import FrozenRoutes
from paper_daily.ai_types import Settings
from paper_daily.cli_job_protocol import decode_frame, hello_line, ready_line
from paper_daily.desktop import cli_job


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def intent():
    return FrozenRoutes(Settings("none"), {"survey": Settings(
        "openai", model="original-model", api_key="synthetic-private-key", isolated=True,
        cli_home="private-home", max_tokens=4000)}).bind("a" * 32, ("survey", "fixture"))


class Pipe(QObject):
    bytesWritten = Signal(int)
    errorOccurred = Signal(object)
    finished = Signal(int, object)

    def __init__(self, limit=13):
        super().__init__()
        self.limit = limit
        self.written = bytearray()
        self.closed = False
        self.killed = False

    def write(self, data):
        count = min(self.limit, len(data))
        self.written.extend(data[:count])
        return count

    def state(self):
        return QProcess.ProcessState.Running

    def kill(self):
        self.killed = True

    def closeWriteChannel(self):
        self.closed = True


def test_partial_write_and_split_control_lines_keep_frame_private(app):
    process = Pipe()
    bound = intent()
    handoff = cli_job.JobHandoff(process, bound)
    hello = hello_line(bound.request_id)
    assert handoff.filter_output(hello[:9]) == b""
    assert process.written == b""
    assert handoff.filter_output(hello[9:]) == b""
    while handoff._frame:
        process.bytesWritten.emit(13)
    assert process.closed
    received = decode_frame(bytes(process.written), expected_request_id=bound.request_id,
                            expected_command=bound.command)
    assert received.routes.settings("survey").api_key == "synthetic-private-key"
    visible = handoff.filter_output(ready_line(bound.request_id) + b"visible progress\n")
    assert visible == b"visible progress\n"
    assert handoff.filter_output(b"next\n") == b"next\n"
    assert handoff.complete(0) == 0 and not handoff.timer.isActive()
    assert not handoff._frame and not handoff._pending and not process.killed


@pytest.mark.parametrize(
    "kind", ["old-cli", "wrong-id", "wrong-version", "ready-first", "oversized"],
)
def test_unverified_child_never_receives_private_frame(app, kind):
    process = Pipe()
    bound = intent()
    handoff = cli_job.JobHandoff(process, bound)
    line = {"old-cli": b"unrecognized arguments\n", "wrong-id": hello_line("b" * 32),
            "wrong-version": hello_line(bound.request_id).replace(b" 1 ", b" 2 "),
            "ready-first": ready_line(bound.request_id), "oversized": b"x" * 129}[kind]
    assert handoff.filter_output(line) == b"AI job startup failed; please retry.\n"
    assert process.written == b"" and process.killed
    assert handoff.complete(0) == 2
    assert not handoff._frame and not handoff._pending and not handoff.timer.isActive()
    assert handoff.filter_output(b"late line\n") == b""


@pytest.mark.parametrize("kind", ["deadline", "failed-start", "early-exit", "broken-pipe"])
def test_startup_failures_clear_private_payload_and_cannot_report_success(app, kind):
    process = Pipe()
    bound = intent()
    handoff = cli_job.JobHandoff(process, bound)
    if kind == "deadline":
        handoff.timer.timeout.emit()
    elif kind == "failed-start":
        process.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
    elif kind == "early-exit":
        process.finished.emit(0, QProcess.ExitStatus.NormalExit)
    else:
        process.limit = -1
        handoff.filter_output(hello_line(bound.request_id))
    assert handoff.complete(0) == 2
    assert not handoff._frame and not handoff._pending and not handoff.timer.isActive()


def test_actual_qprocess_retains_route_and_keeps_gui_alive(tmp_path, monkeypatch, app):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    llm.save_settings(profile="selected", backend="openai", model="original-model",
                      api_key="synthetic-private-key", isolated=True, max_tokens=4000)
    llm.use_profile("selected", desktop=True)
    process = QProcess()
    command = cli_job.prepare(process, ("survey", "fixture"), ("survey",))
    assert command[-4] == "_desktop-job-v1"
    assert "synthetic-private-key" not in " ".join(command)
    llm.save_settings(profile="selected", model="changed-model", api_key="replacement")
    # The subprocess runs the real bootstrap with only the final CLI body simulated.
    script = r'''
import sys
from types import SimpleNamespace
from paper_daily import integration_entry, runtime
runtime.read_env_file = lambda *_: (_ for _ in ()).throw(AssertionError("dotenv read"))
def run(args):
    from concurrent.futures import ThreadPoolExecutor
    from paper_daily import llm
    with ThreadPoolExecutor(max_workers=1) as pool:
        cfg = pool.submit(llm.settings, "survey").result()
    assert args == ["survey", "fixture"]
    assert cfg.api_key == "synthetic-private-key" and cfg.max_tokens == 4000
    sys.stdout.buffer.write(("RESULT=" + cfg.model + "\n").encode())
    sys.stdout.buffer.flush()
    return 0
sys.modules["paper_daily.cli"] = SimpleNamespace(main=run)
raise SystemExit(integration_entry.main(sys.argv[1:]))
'''
    environment = QProcessEnvironment.systemEnvironment()
    environment.insert("PAPERFACT_DATA", str(tmp_path / "child-data"))
    environment.insert("PYTHONPATH", str(Path(__file__).resolve().parents[1] / "src"))
    process.setProcessEnvironment(environment)
    process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
    output, finished, pulses = [], [], []
    process.readyReadStandardOutput.connect(lambda: output.append(
        process._ai_job_handoff.filter_output(bytes(process.readAllStandardOutput()))))
    process.finished.connect(lambda code, status: finished.append(
        process._ai_job_handoff.complete(code)))
    timer = QTimer()
    timer.timeout.connect(lambda: pulses.append(True))
    timer.start(5)
    # Preserve the logical command and private prefix; replace only the CLI body.
    process.start(sys.executable, ["-c", script, *command[-4:]])
    try:
        deadline = time.monotonic() + 30
        while not finished and time.monotonic() < deadline:
            QTest.qWait(5)
        assert finished == [0]
        assert b"".join(output) == b"RESULT=original-model\n"
        assert pulses and not process._ai_job_handoff._frame
        assert not process._ai_job_handoff.timer.isActive()
    finally:
        timer.stop()
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            assert process.waitForFinished(5000)
        process.deleteLater()
        app.processEvents()


def test_oversized_startup_output_is_discarded_without_retained_payload(app):
    process = Pipe()
    handoff = cli_job.JobHandoff(process, intent())
    assert handoff.filter_output(b"x" * (1024 * 1024)) == (
        b"AI job startup failed; please retry.\n"
    )
    assert not handoff._pending and not handoff._frame and not process.written
    assert handoff.filter_output(b"ignored after failure\n") == b""
