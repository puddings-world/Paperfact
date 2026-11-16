"""Actual source CLI round trip for the frozen report acceptance helper."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_report_cli_uses_one_synthetic_completion_and_preserves_originals(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from verify_built_app import isolated_env
    from verify_source_report import verify

    env = isolated_env(tmp_path / "seed")
    env["PYTHONPATH"] = str(ROOT / "src")
    package = tmp_path / "original.zip"
    seed = ("import sys;sys.path.insert(0,'scripts');from demo_workspace import acceptance_package;"
            "from pathlib import Path;acceptance_package(Path(sys.argv[1]))")
    subprocess.run([sys.executable, "-c", seed, str(package)], cwd=ROOT, env=env,
                   capture_output=True, check=True, timeout=30)
    report = verify([sys.executable, "-m", "paper_daily"], tmp_path / "report", env, package)
    assert report == dict(saved=True, quote_located=True, originals_verified=True,
                          requested_model="synthetic-requested-model",
                          returned_model="synthetic-returned-model", retained_read=True,
                          cached_without_completion=True,
                          private_handoff=True, child_disk_settings_ignored=True)
    assert os.environ.get("PAPERFACT_DATA") != str(tmp_path / "report" / "workspace")


def test_private_handoff_refuses_zero_exit_without_handshake(tmp_path, monkeypatch):
    import pytest

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from verify_built_app import isolated_env
    from verify_private_report import run

    from paper_daily.ai_job_intent import FrozenRoutes
    from paper_daily.ai_types import Settings

    route = Settings("none")
    routes = FrozenRoutes(route, {"survey": route}, account_directory=str(tmp_path))
    with pytest.raises(RuntimeError, match="handoff failed"):
        run([sys.executable, "-c", "print('not a handshake')"],
            ["survey", "demo", "--sources"], isolated_env(tmp_path / "child"), routes)


def test_private_handoff_timeout_stops_the_owned_child(tmp_path, monkeypatch):
    import pytest

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from verify_built_app import isolated_env
    from verify_private_report import run

    from paper_daily.ai_job_intent import FrozenRoutes
    from paper_daily.ai_types import Settings

    route = Settings("none")
    routes = FrozenRoutes(route, {"survey": route}, account_directory=str(tmp_path))
    with pytest.raises(TimeoutError, match="time budget"):
        run([sys.executable, "-c", "import time;time.sleep(30)"],
            ["survey", "demo", "--sources"], isolated_env(tmp_path / "child"),
            routes, seconds=0.05)
