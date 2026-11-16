"""Exercise the production desktop handoff against the selected real CLI executable."""

import time
from uuid import uuid4

_APP = None


def run(command, arguments, environment, routes, *, seconds=45):
    """Use a real QProcess and private stdin protocol, with bounded output/lifetime."""
    from PySide6.QtCore import QProcess, QProcessEnvironment
    from PySide6.QtWidgets import QApplication

    from paper_daily.desktop.cli_job import JobHandoff

    global _APP
    _APP = QApplication.instance() or QApplication([])
    intent = routes.bind(uuid4().hex, tuple(arguments))
    process = QProcess()
    env = QProcessEnvironment()
    for name, value in environment.items():
        env.insert(name, value)
    process.setProcessEnvironment(env)
    handoff = JobHandoff(process, intent, timeout_ms=30_000)
    output, errors = bytearray(), bytearray()
    overflow = False

    def drain():
        nonlocal overflow
        chunk = bytes(process.readAllStandardOutput())
        output.extend(handoff.filter_output(chunk))
        errors.extend(bytes(process.readAllStandardError()))
        if len(output) + len(errors) > 1024 * 1024:
            overflow = True
            handoff.cancel()

    process.readyReadStandardOutput.connect(drain)
    process.readyReadStandardError.connect(drain)
    argv = [*map(str, command[1:]), "_desktop-job-v1", intent.request_id, *arguments]
    deadline = time.monotonic() + seconds
    try:
        process.start(str(command[0]), argv)
        while process.state() != QProcess.ProcessState.NotRunning:
            _APP.processEvents()
            if time.monotonic() >= deadline:
                raise TimeoutError("Private report handoff exceeded its time budget")
            time.sleep(0.005)
        drain()
        if (overflow or handoff.complete(process.exitCode()) != 0
                or process.exitStatus() != QProcess.ExitStatus.NormalExit):
            raise RuntimeError("Private report handoff failed")
        return output.decode("utf-8")
    finally:
        handoff.cancel()
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            process.waitForFinished(1000)
        process.deleteLater()
