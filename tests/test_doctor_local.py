import subprocess
import sys
from types import SimpleNamespace

import pytest

from paper_daily import cli, fonts, http, llm, web_assets
from paper_daily.ai_types import Settings

RUN = subprocess.run


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path / "not-created")
    monkeypatch.setattr(cli, "DB_PATH", tmp_path / "not-created/papers.db")
    monkeypatch.setattr(fonts, "missing", lambda: [])
    monkeypatch.setattr(web_assets, "missing", lambda: [])
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    monkeypatch.setattr(http, "fetch", lambda *a, **k: pytest.fail("unexpected network request"))
    monkeypatch.setattr(llm, "probe", lambda *a, **k: pytest.fail("unexpected model call"))
    return tmp_path


@pytest.mark.parametrize("backend", ["none", "cli", "codex", "gemini"])
def test_default_doctor_allows_fresh_reader_without_contacting_ai(local, monkeypatch, backend):
    monkeypatch.setattr(llm, "settings", lambda: Settings(backend))
    assert cli.cmd_doctor(SimpleNamespace(ai=False, sources=False)) == 0
    assert not (local / "not-created").exists()


def test_explicit_model_check_reports_failure_without_fallback(local, monkeypatch):
    monkeypatch.setattr(llm, "settings", lambda: Settings("cli", model="chosen"))
    calls = []
    monkeypatch.setattr(llm, "probe", lambda cfg: (calls.append(cfg) or False, "not logged in"))
    assert cli.cmd_doctor(SimpleNamespace(ai=True, sources=False)) == 1
    assert len(calls) == 1 and calls[0].model == "chosen"


def test_explicit_source_check_does_not_test_ai(local, monkeypatch):
    monkeypatch.setattr(llm, "settings", lambda: Settings("none"))
    urls = []
    monkeypatch.setattr(http, "fetch", lambda url, **kwargs: urls.append(url))
    assert cli.cmd_doctor(SimpleNamespace(ai=False, sources=True)) == 0
    assert urls


@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
def test_windows_task_status_does_not_decode_native_output(local, monkeypatch):
    monkeypatch.setattr(cli.sys, 'platform', 'win32')
    monkeypatch.setattr(llm, 'settings', lambda: Settings('none'))

    def native_output(_command, **kwargs):
        return RUN([sys.executable, '-c',
                    'import os; os.write(1, bytes([0x81])); os.write(2, bytes([0x81]))'], **kwargs)

    monkeypatch.setattr(cli.subprocess, 'run', native_output)
    assert cli.cmd_doctor(SimpleNamespace(ai=False, sources=False)) == 0
