"""Run the complete local checks, including desktop action stress tests."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


def run_checks(root, execute=subprocess.run):
    node = shutil.which("node")
    if not node:
        print("Node.js is required for the frontend tests; no checks were skipped.")
        return 1
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PAPERFACT_PLAIN_VIEWS": "1"}
    # pytest creates --basetemp but not its parent; a fresh clone has no build/.
    (root / "build").mkdir(exist_ok=True)
    checks = [
        ("Ruff", [sys.executable, "-m", "ruff", "check", "."]),
        (
            "Python and desktop stress tests",
            [
                sys.executable,
                "-X",
                "faulthandler",
                "-m",
                "pytest",
                "tests",
                "-q",
                "--tb=short",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(root / "build" / ("check-" + uuid4().hex[:8])),
            ],
        ),
        (
            "Frontend tests",
            [node, "--test", *map(str, sorted((root / "tests").glob("test_*.mjs")))],
        ),
    ]
    for name, command in checks:
        print(f"Checking: {name}", flush=True)
        result = execute(command, cwd=root, env=env)
        if result.returncode:
            print(f"FAILED: {name} (exit {result.returncode})", flush=True)
            return result.returncode
    print("All checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes

        # Child tests report native failures to the terminal instead of opening
        # a blocking Windows crash dialog on the user's desktop.
        ctypes.windll.kernel32.SetErrorMode(0x8003)
    raise SystemExit(run_checks(Path(__file__).resolve().parents[1]))
