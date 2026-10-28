import json
import os
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_daily import diagnostics as d


def test_export_contains_only_reviewed_allowlisted_data(tmp_path):
    secret = "private-question-and-account@example.invalid"
    (tmp_path / "app.log").write_text(
        "Traceback (most recent call last):\n"
        f'  File "/Users/{secret}/paper_daily/desktop/ask.py", line 12, in call\n'
        f'    answer = "{secret}"\nValueError: {secret}\n',
        encoding="utf-8",
    )
    (tmp_path / "papers.db").write_text(secret)
    (tmp_path / "credentials.json").write_text(secret)
    report = d.collect(tmp_path)
    assert report["errors"] == [
        {
            "phase": "desktop",
            "error_type": "ValueError",
            "frames": [{"module": "paper_daily.desktop.ask", "line": 12}],
        }
    ]
    assert secret not in d.render(report)
    destination = d.export(report, tmp_path / "report.zip")
    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == {"diagnostics.json", "READ-ME.txt"}
        assert archive.read("diagnostics.json").decode() == d.render(report)
    assert (tmp_path / "papers.db").read_text() == secret


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {"phase": []},
        {"phase": "private-topic"},
        {"phase": "desktop", "frames": None, "error_type": {}},
        {"phase": "desktop", "frames": [{"module": "paper_daily.private_account", "line": 2}]},
    ],
)
def test_malformed_or_arbitrary_stored_data_never_leaks(tmp_path, bad):
    row = {
        "phase": "worker",
        "error_type": "RuntimeError",
        "private": "private-topic",
        "frames": [{"module": "paper_daily.store", "line": 1, "locals": "private-topic"}],
    }
    (tmp_path / "diagnostics.jsonl").write_text(
        "invalid-json\n" + json.dumps(bad) + "\n" + json.dumps(row), encoding="utf-8"
    )
    report = d.collect(tmp_path)
    assert report["errors"][-1] == {
        "phase": "worker",
        "error_type": "RuntimeError",
        "frames": [{"module": "paper_daily.store", "line": 1}],
    }
    assert "private" not in d.render(report)


def test_missing_logs_are_unknown_and_collection_does_not_create_workspace(tmp_path):
    missing = tmp_path / "absent"
    report = d.collect(missing)
    assert not missing.exists()
    assert set(report["logs"].values()) == {"unavailable"}
    assert report["errors"] == []
    assert "not prove health" in str(report["limits"])


def test_reads_and_events_are_bounded(tmp_path):
    (tmp_path / "app.log").write_text(
        "ValueError: old\n" + "x" * (d.LIMIT + 10) + "\nTypeError: recent\n"
    )
    (tmp_path / "diagnostics.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "phase": "worker",
                    "error_type": "ValueError",
                    "frames": [],
                }
            )
            for _ in range(200)
        )
    )
    report = d.collect(tmp_path)
    assert len(report["errors"]) == d.MAX_EVENTS
    assert len(d._tail(tmp_path / "app.log").encode()) <= d.LIMIT


def test_record_exception_omits_messages_and_rotates(tmp_path):
    (tmp_path / "diagnostics.jsonl").write_text("x" * (d.LIMIT + 1))
    try:
        exec(
            compile('raise ValueError("private-prompt")', "private-path.py", "exec"),
            {"__name__": "paper_daily.desktop.ask"},
        )
    except ValueError:
        assert d.record_exception(ValueError, sys.exc_info()[2], directory=tmp_path)
    report = d.collect(tmp_path)
    assert report["errors"][0]["frames"][-1] == {
        "module": "paper_daily.desktop.ask",
        "line": 1,
    }
    assert "private" not in (tmp_path / "diagnostics.jsonl").read_text()


def test_storage_failures_do_not_break_reporting_or_app(tmp_path, monkeypatch):
    blocked = tmp_path / "file"
    blocked.write_text("preserve")
    assert not d.record_exception(ValueError, None, directory=blocked)
    assert not d.install_error_hooks(directory=blocked)
    monkeypatch.setattr(d, "_tail", lambda path: (_ for _ in ()).throw(PermissionError()))
    assert set(d.collect(tmp_path)["logs"].values()) == {"unreadable"}


def test_export_refuses_existing_and_racing_destination(tmp_path, monkeypatch):
    from paper_daily import sync_recovery_fs

    target = tmp_path / "existing.zip"
    target.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        d.export(d.collect(tmp_path), target)
    assert target.read_bytes() == b"keep"
    target = tmp_path / "racing.zip"
    publish = sync_recovery_fs.publish_directory

    def raced(stage, destination):
        destination.write_bytes(b"racing-content")
        publish(stage, destination)

    monkeypatch.setattr(sync_recovery_fs, "publish_directory", raced)
    with pytest.raises(OSError):
        d.export(d.collect(tmp_path), target)
    assert target.read_bytes() == b"racing-content"
    assert {p.name for p in tmp_path.iterdir()} == {"existing.zip", "racing.zip"}


def test_export_failure_cleans_stage_and_can_retry(tmp_path, monkeypatch):
    from paper_daily import sync_recovery_fs

    target = tmp_path / "report.zip"
    report = d.collect(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(
            sync_recovery_fs,
            "publish_directory",
            lambda *a: (_ for _ in ()).throw(PermissionError()),
        )
        with pytest.raises(OSError):
            d.export(report, target)
    assert not list(tmp_path.iterdir())
    assert d.export(report, target).is_file()


def test_log_hooks_keep_native_stream_and_handle_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "__excepthook__", lambda *args: None)
    enabled = []
    monkeypatch.setattr(d.faulthandler, "enable", lambda **kw: enabled.append(kw["file"]))
    monkeypatch.setattr(d.faulthandler, "disable", lambda: None)
    monkeypatch.setattr(d, "_fault_stream", None)
    (tmp_path / "app.log").write_text("x" * (d.LIMIT + 1))
    assert d.install_error_hooks(directory=tmp_path, phase="startup")
    assert not enabled[-1].closed
    sys.excepthook(ValueError, ValueError("private-raw-error"), None)
    threading.excepthook(
        SimpleNamespace(exc_type=TypeError, exc_value=TypeError("private"), exc_traceback=None)
    )
    assert [row["phase"] for row in d.collect(tmp_path)["errors"]][-2:] == ["startup", "worker"]
    assert "private-raw-error" in (tmp_path / "app.log").read_text()
    assert "private-raw-error" not in d.render(d.collect(tmp_path))
    first = enabled[-1]
    assert d.install_error_hooks(directory=tmp_path)
    assert first.closed and not enabled[-1].closed
    enabled[-1].close()


def test_cold_diagnostics_works_without_loading_cli_qt_or_database(tmp_path):
    code = """
import sys
from paper_daily.integration_entry import main
class Guard:
    def find_spec(self, fullname, *args):
        if fullname in ('paper_daily.cli', 'paper_daily.store', 'paper_daily.config', 'PySide6'):
            raise AssertionError('Diagnostics must not import app dependencies')
sys.meta_path.insert(0, Guard())
raise SystemExit(main(['diagnostics', '--workspace', sys.argv[1]]))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["app"] == "Paperfact"
    assert not list(tmp_path.iterdir())


def test_early_cli_import_failure_is_captured_before_desktop(tmp_path):
    code = """
import sys
from paper_daily.integration_entry import main
class Broken:
    def find_spec(self, fullname, *args):
        if fullname == 'paper_daily.cli':
            raise ImportError('synthetic-private-dependency-message')
sys.meta_path.insert(0, Broken())
main(['app'])
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PAPERFACT_DATA": str(tmp_path)},
        timeout=30,
    )
    assert result.returncode != 0
    report = d.collect(tmp_path)
    assert any(
        row["phase"] == "startup" and row["error_type"] == "ImportError" for row in report["errors"]
    )
    assert "synthetic-private" not in d.render(report)


def test_cli_export_and_failure_are_clear(tmp_path, capsys):
    target = tmp_path / "report.zip"
    args = ["--workspace", str(tmp_path), "--output", str(target)]
    assert d.main(args) == 0
    assert "nothing was uploaded" in capsys.readouterr().out
    assert d.main(args) == 2
    assert "new output filename" in capsys.readouterr().err


def test_shipped_gui_uses_early_bootstrap():
    root = Path(__file__).resolve().parents[1]
    assert (
        "from paper_daily.integration_entry import main"
        in (root / "packaging/gui_entry.py").read_text()
    )


def test_prerelease_version_is_not_reported_as_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(d, '__version__', '0.5.0-beta.2')
    assert d.collect(tmp_path)['version'] == '0.5.0-beta.2'


def test_missing_metadata_does_not_claim_bundled_packages_are_absent(tmp_path, monkeypatch):
    def missing(_name):
        raise d.importlib.metadata.PackageNotFoundError()

    monkeypatch.setattr(d.importlib.metadata, 'version', missing)
    monkeypatch.setattr(d.runtime, 'FROZEN', True)
    report = d.collect(tmp_path)
    assert report['install'] == 'release'
    assert set(report['packages'].values()) == {'version-unavailable'}


def test_package_versions_are_read_once_per_run(tmp_path, monkeypatch):
    # Reading distribution metadata scans site-packages; the 診斷與回報 dialog took
    # half a second to open while it did that on every refresh.
    calls = []
    monkeypatch.setattr(
        d.importlib.metadata, 'version', lambda name: calls.append(name) or '1.2.3'
    )
    first = d.collect(tmp_path)['packages']
    second = d.collect(tmp_path)['packages']
    assert first == second == {name: '1.2.3' for name in d.PACKAGES}
    assert sorted(calls) == sorted(d.PACKAGES)
