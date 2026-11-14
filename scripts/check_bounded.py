"""Bound local checks on Windows; fail closed where the governor is unavailable.

The underlying suite is unchanged. A timeout or missing resource governor is never
an application pass. Native Mac/Linux governors remain an explicit follow-up.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

LOCAL_SECONDS = 300
FULL_SECONDS = 1800
CPU_RATE = 2500
MAX_CORES = 2
BOOTSTRAP = (
    "import subprocess,sys; "
    "permit=sys.stdin.buffer.read(1); "
    "sys.exit(subprocess.call(sys.argv[1:],stdin=subprocess.DEVNULL) if permit==b'1' else 126)"
)


class BudgetUnavailable(RuntimeError):
    pass


def seconds_for(arguments):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--profile", choices=("critical", "full", "focused", "docs"), default="critical",
    )
    options, _ = parser.parse_known_args(arguments)
    return FULL_SECONDS if options.profile == "full" else LOCAL_SECONDS


class WindowsBudget:
    def __init__(self, *, exclusive=True):
        if os.name != "nt":
            raise BudgetUnavailable(
                "A verified native CPU governor is not available on this OS yet"
            )
        from ctypes import wintypes as w

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.job = self.mutex = None
        api = self.api
        api.CreateMutexW.argtypes = (ctypes.c_void_p, w.BOOL, w.LPCWSTR)
        api.CreateMutexW.restype = w.HANDLE
        api.WaitForSingleObject.argtypes = (w.HANDLE, w.DWORD)
        api.WaitForSingleObject.restype = w.DWORD
        api.ReleaseMutex.argtypes = (w.HANDLE,)
        api.CloseHandle.argtypes = (w.HANDLE,)
        api.CreateJobObjectW.argtypes = (ctypes.c_void_p, w.LPCWSTR)
        api.CreateJobObjectW.restype = w.HANDLE
        api.SetInformationJobObject.argtypes = (w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD)
        api.SetInformationJobObject.restype = w.BOOL
        api.QueryInformationJobObject.argtypes = (
            w.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            w.DWORD,
            ctypes.c_void_p,
        )
        api.QueryInformationJobObject.restype = w.BOOL
        api.AssignProcessToJobObject.argtypes = (w.HANDLE, w.HANDLE)
        api.AssignProcessToJobObject.restype = w.BOOL
        api.TerminateJobObject.argtypes = (w.HANDLE, w.UINT)
        api.TerminateJobObject.restype = w.BOOL
        api.GetCurrentProcess.restype = w.HANDLE
        api.GetProcessAffinityMask.argtypes = (
            w.HANDLE,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_size_t),
        )
        api.GetProcessAffinityMask.restype = w.BOOL

        class Basic(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_longlong),
                ("job_time", ctypes.c_longlong),
                ("flags", w.DWORD),
                ("minimum", ctypes.c_size_t),
                ("maximum", ctypes.c_size_t),
                ("process_limit", w.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", w.DWORD),
                ("scheduling", w.DWORD),
            ]

        class IO(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", IO),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        class Rate(ctypes.Structure):
            _fields_ = [("flags", w.DWORD), ("rate", w.DWORD)]

        self.Extended, self.Rate = Extended, Rate
        try:
            if exclusive:
                self.mutex = api.CreateMutexW(None, False, "Local\\PaperfactDevelopmentChecks")
                if not self.mutex or api.WaitForSingleObject(self.mutex, 0) not in (0, 0x80):
                    raise BudgetUnavailable("Another bounded Paperfact check is already running")
                self.owns_mutex = True
            self.job = api.CreateJobObjectW(None, None)
            if not self.job:
                raise BudgetUnavailable("Could not create the CPU-limited job")
            current, system = ctypes.c_size_t(), ctypes.c_size_t()
            if not api.GetProcessAffinityMask(
                api.GetCurrentProcess(), ctypes.byref(current), ctypes.byref(system)
            ):
                raise BudgetUnavailable("Could not determine available processors")
            bits = [
                1 << bit for bit in range(current.value.bit_length()) if current.value & (1 << bit)
            ]
            mask = sum(bits[:MAX_CORES])
            if not mask:
                raise BudgetUnavailable("No processors are available for the bounded check")
            limits = Extended()
            limits.basic.flags = 0x2000 | 0x20 | 0x10  # Kill on close, priority, affinity.
            limits.basic.affinity, limits.basic.priority = mask, 0x4000
            rate = Rate(0x1 | 0x4, CPU_RATE)  # Enabled, hard cap.
            if not api.SetInformationJobObject(
                self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise BudgetUnavailable("Could not set process-tree limits")
            if not api.SetInformationJobObject(
                self.job, 15, ctypes.byref(rate), ctypes.sizeof(rate)
            ):
                raise BudgetUnavailable("Could not enforce the CPU rate cap")
        except BaseException:
            self.close()
            raise

    def attach(self, process):
        if not self.api.AssignProcessToJobObject(self.job, int(process._handle)):
            raise BudgetUnavailable("Could not attach the waiting child to its resource budget")

    def settings(self):
        limits, rate = self.Extended(), self.Rate()
        for code, value in ((9, limits), (15, rate)):
            if not self.api.QueryInformationJobObject(
                self.job, code, ctypes.byref(value), ctypes.sizeof(value), None
            ):
                raise BudgetUnavailable("Could not verify the native resource limits")
        return dict(
            cpu_rate_percent=rate.rate / 100,
            logical_processors=limits.basic.affinity.bit_count(),
            hard_cap=bool(rate.flags & 4),
            lower_priority=limits.basic.priority == 0x4000,
        )

    def terminate(self, code):
        if self.job and not self.api.TerminateJobObject(self.job, code):
            raise BudgetUnavailable("Could not terminate the owned check job")

    def close(self):
        if self.job:
            self.api.CloseHandle(self.job)
            self.job = None
        if self.mutex:
            if getattr(self, "owns_mutex", False):
                self.api.ReleaseMutex(self.mutex)
            self.api.CloseHandle(self.mutex)
            self.mutex = None


def execute(command, *, cwd, env=None, seconds=LOCAL_SECONDS, budget_factory=WindowsBudget):
    if type(seconds) not in (int, float) or not 0 < seconds <= FULL_SECONDS:
        raise ValueError("A positive wall budget of at most 1800 seconds is required")
    started = time.monotonic()
    budget, process = budget_factory(), None
    try:
        settings = budget.settings()
        process = subprocess.Popen(
            [sys.executable, "-c", BOOTSTRAP, *command],
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        budget.attach(process)
        process.stdin.write(b"1")
        process.stdin.close()
        try:
            code = process.wait(timeout=max(0.01, seconds - (time.monotonic() - started)))
            state = "passed" if code == 0 else "failed"
        except subprocess.TimeoutExpired:
            budget.terminate(124)
            process.wait(timeout=5)
            code, state = 124, "timed_out"
        except KeyboardInterrupt:
            budget.terminate(130)
            process.wait(timeout=5)
            code, state = 130, "interrupted"
        return dict(
            status=state,
            returncode=code,
            seconds=round(time.monotonic() - started, 3),
            limits=settings,
            timeout_seconds=seconds,
        )
    finally:
        budget.close()  # Also kills any remaining owned descendants.
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def _save(path, data):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    root = Path(__file__).resolve().parents[1]
    seconds = seconds_for(arguments)
    run_id = uuid4().hex
    path = root / "build/check-budget-latest.json"
    path.parent.mkdir(exist_ok=True)
    report = dict(
        format="paperfact.check-budget.v1",
        run_id=run_id,
        status="running",
        full_check_passed=False,
        timeout_seconds=seconds,
    )
    _save(path, report)
    print(
        f"Check budget: {seconds}s total, at most 2 logical processors, 25% job CPU cap.",
        flush=True,
    )
    environment = dict(os.environ, PAPERFACT_CHECK_RUN_ID=run_id)
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        environment[name] = "1"
    try:
        result = execute(
            [sys.executable, str(root / "scripts/check.py"), *arguments],
            cwd=root,
            env=environment,
            seconds=seconds,
        )
        report.update(result)
        try:
            child = json.loads((root / "build/check-latest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            child = {}
        if child.get("run_id") == run_id:
            if (
                result["status"] in {"timed_out", "interrupted"}
                and child.get("status") == "running"
            ):
                child.update(status=result["status"], full_check_passed=False)
                for stage in child.get("stages", []):
                    if stage.get("status") == "running":
                        stage.update(status=result["status"], exit_code=result["returncode"])
                _save(root / "build/check-latest.json", child)
            report["full_check_passed"] = bool(
                result["status"] == "passed" and child.get("full_check_passed")
            )
        code = result["returncode"]
        if code == 0 and (child.get("run_id") != run_id or child.get("status") != "passed"):
            report.update(status="unverified_result", returncode=2, full_check_passed=False)
            code = 2
    except (BudgetUnavailable, OSError):
        report.update(status="budget_unavailable", returncode=2)
        code = 2
        print("Resource governor unavailable; no unlimited check was started.", flush=True)
    _save(path, report)
    print(f"Bounded check: {report['status']}. Report: build/check-budget-latest.json", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
