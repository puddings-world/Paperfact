"""Bounded native job contracts; tiny child processes only, no research fixtures."""

import ctypes
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_bounded.py"
spec = importlib.util.spec_from_file_location("check_bounded", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ([], 300),
        (["--profile", "full"], 1800),
        (["--profile", "release"], 1800),
        (["--profile", "focused", "--python", "tests/test_x.py"], 300),
        (["--profile=docs"], 300),
    ],
)
def test_default_wall_budget_matches_requested_tier(arguments, expected):
    assert module.seconds_for(arguments) == expected


@pytest.mark.parametrize("seconds", [0, -1, 1801, True])
def test_invalid_wall_budget_never_starts_process(seconds, monkeypatch, tmp_path):
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_a, **_k: pytest.fail("launched"))
    with pytest.raises(ValueError):
        module.execute(["unused"], cwd=tmp_path, seconds=seconds)


def test_unavailable_governor_never_launches_unlimited_work(monkeypatch, tmp_path):
    def unavailable():
        raise module.BudgetUnavailable("fixture unsupported")

    monkeypatch.setattr(module.subprocess, "Popen", lambda *_a, **_k: pytest.fail("launched"))
    with pytest.raises(module.BudgetUnavailable):
        module.execute(["unused"], cwd=tmp_path, budget_factory=unavailable)


@pytest.mark.skipif(os.name != "nt", reason="Native Windows job acceptance")
def test_actual_native_job_has_hard_cap_low_priority_and_at_most_two_processors():
    budget = module.WindowsBudget(exclusive=False)
    try:
        settings = budget.settings()
        assert settings == dict(
            cpu_rate_percent=25,
            logical_processors=settings["logical_processors"],
            hard_cap=True,
            lower_priority=True,
        )
        assert 1 <= settings["logical_processors"] <= 2
    finally:
        budget.close()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows job acceptance")
def test_child_failure_is_preserved_under_actual_resource_limits(tmp_path):
    result = module.execute(
        [sys.executable, "-c", "raise SystemExit(7)"],
        cwd=tmp_path,
        seconds=5,
        budget_factory=lambda: module.WindowsBudget(exclusive=False),
    )
    assert result["status"] == "failed" and result["returncode"] == 7


def active(pid):
    from ctypes import wintypes as w

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD)
    api.OpenProcess.restype = w.HANDLE
    api.GetExitCodeProcess.argtypes = (w.HANDLE, ctypes.POINTER(w.DWORD))
    api.CloseHandle.argtypes = (w.HANDLE,)
    handle = api.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = w.DWORD()
        return bool(api.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259)
    finally:
        api.CloseHandle(handle)


@pytest.mark.skipif(os.name != "nt", reason="Native Windows job acceptance")
def test_deadline_kills_actual_child_tree_and_never_reports_pass(tmp_path):
    marker = tmp_path / "child.json"
    script = (
        "import subprocess,sys,time,json; from pathlib import Path; "
        'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); '
        "Path(sys.argv[1]).write_text(json.dumps(p.pid));time.sleep(60)"
    )
    result = module.execute(
        [sys.executable, "-c", script, str(marker)],
        cwd=tmp_path,
        seconds=2,
        budget_factory=lambda: module.WindowsBudget(exclusive=False),
    )
    assert result["status"] == "timed_out" and result["returncode"] == 124
    assert result["seconds"] < 5
    pid = json.loads(marker.read_text())
    for _ in range(20):
        if not active(pid):
            break
        time.sleep(0.05)
    assert not active(pid)


def test_timeout_report_reconciles_only_its_own_child_run(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    monkeypatch.setattr(module, "__file__", str(tmp_path / "scripts/check_bounded.py"))

    def execute(*_a, **kwargs):
        report = dict(
            run_id=kwargs["env"]["PAPERFACT_CHECK_RUN_ID"],
            status="running",
            full_check_passed=False,
            stages=[dict(status="running")],
        )
        (tmp_path / "build/check-latest.json").write_text(json.dumps(report), encoding="utf-8")
        return dict(status="timed_out", returncode=124, seconds=0.1, limits={}, timeout_seconds=300)

    monkeypatch.setattr(module, "execute", execute)
    assert module.main(["--profile", "focused", "--python", "tests/test_x.py"]) == 124
    report = json.loads((tmp_path / "build/check-latest.json").read_text())
    assert report["status"] == "timed_out" and not report["full_check_passed"]
    assert report["stages"][0]["status"] == "timed_out"


def test_uncorrelated_success_is_not_accepted_as_a_pass(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    monkeypatch.setattr(module, "__file__", str(tmp_path / "scripts/check_bounded.py"))
    monkeypatch.setattr(
        module, "execute", lambda *_a, **_k: dict(status="passed", returncode=0, seconds=0.1)
    )
    assert module.main(["--profile", "focused", "--python", "tests/test_x.py"]) == 2
    report = json.loads((tmp_path / "build/check-budget-latest.json").read_text())
    assert report["status"] == "unverified_result" and not report["full_check_passed"]
