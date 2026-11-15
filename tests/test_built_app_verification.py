import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import types
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify", ROOT / "scripts/verify_built_app.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def test_verification_does_not_inherit_developer_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'private')
    monkeypatch.setenv('CODEX_HOME', '/private/codex')
    monkeypatch.setenv('PAPERFACT_DATA', '/private/research')
    env = verify.isolated_env(tmp_path)
    assert 'ANTHROPIC_API_KEY' not in env and 'CODEX_HOME' not in env
    assert Path(env['PAPERFACT_DATA']).is_relative_to(tmp_path)
    assert Path(env['HOME']).is_relative_to(tmp_path)
    # Native Mac WebEngine reader acceptance must not inherit a CI offscreen backend.
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(verify.sys, "platform", "darwin")
    mac = verify.isolated_env(tmp_path / "mac")
    assert mac["QT_QPA_PLATFORM"] == "cocoa"
    assert "ANTHROPIC_API_KEY" not in mac and "CODEX_HOME" not in mac
    assert Path(mac["PAPERFACT_DATA"]).is_relative_to(tmp_path / "mac")
    monkeypatch.setattr(verify.sys, "platform", "linux")
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    assert verify.isolated_env(tmp_path / "linux")["QT_QPA_PLATFORM"] == "xcb"


def test_frozen_roundtrip_checks_pdf_bytes_not_just_counts(tmp_path):
    first, second = tmp_path / 'a.zip', tmp_path / 'b.zip'
    for target in (first, second):
        with zipfile.ZipFile(target, 'w') as archive:
            archive.writestr('files/pdf/demo.pdf', b'original bytes')
    assert verify.compare_files(first, second) == 1
    with zipfile.ZipFile(second, 'w') as archive:
        archive.writestr('files/pdf/demo.pdf', b'changed bytes')
    with pytest.raises(ValueError, match='changed'):
        verify.compare_files(first, second)


def test_zero_exit_does_not_hide_a_background_traceback():
    result = subprocess.CompletedProcess([], 0, b'Checks complete',
                                         b'Traceback (most recent call last):\nworker failed')
    with pytest.raises(RuntimeError, match='doctor failed'):
        verify.check_process(result, 'doctor')
    verify.check_process(subprocess.CompletedProcess([], 0, b'Checks complete', b''), 'doctor')


@pytest.mark.parametrize("failure", ["exit", "traceback", "timeout", "missing", "interrupt"])
def test_failed_acceptance_reports_exact_stage_without_private_text(tmp_path, monkeypatch, failure):
    built, out = tmp_path / "built", tmp_path / "acceptance"
    metadata = built / "_internal" / "build-info.json"
    metadata.parent.mkdir(parents=True)
    secret = "private-account@example.invalid /private/research token=do-not-export"
    metadata.write_text(
        json.dumps(dict(commit="b" * 40, dirty=False, account=secret)), encoding="utf-8"
    )
    monkeypatch.setattr(verify, "host_architecture", lambda: secret)

    def fake(command, **kwargs):
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, b"paperfact 0.4.8\n", b"")
        if failure == "exit":
            return subprocess.CompletedProcess(command, 7, secret.encode(), secret.encode())
        if failure == "traceback":
            return subprocess.CompletedProcess(
                command, 0, b"", b"Traceback (most recent call last):" + secret.encode()
            )
        if failure == "timeout":
            raise subprocess.TimeoutExpired(secret, 90, output=secret.encode(), stderr=b"partial")
        if failure == "missing":
            raise FileNotFoundError(secret)
        raise KeyboardInterrupt(secret)

    monkeypatch.setattr(verify.subprocess, "run", fake)
    with pytest.raises(
        (RuntimeError, subprocess.TimeoutExpired, FileNotFoundError, KeyboardInterrupt)
    ):
        verify.verify(built, out)
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    codes = dict(
        exit="process_failed",
        traceback="background_traceback",
        timeout="timeout",
        missing="missing_file",
        interrupt="interrupted",
    )
    assert report["format"] == verify.FORMAT and report["passed"] is False
    assert report["status"] == ("interrupted" if failure == "interrupt" else "failed")
    assert report["active_check"] == "doctor"
    detail = (out / "failure-detail.log").read_text(encoding="utf-8")
    assert "Traceback" in detail and len(detail) <= 16384
    assert report["completed_checks"] == ["isolation", "version"]
    assert report["build"] == dict(commit="b" * 40, dirty=False, version="0.4.8")
    assert report["host"]["architecture"] == "other"
    assert report["failure"] == dict(
        code=codes[failure],
        returncode=7 if failure == "exit" else 0 if failure == "traceback" else None,
    )
    encoded = (out / "report.json").read_bytes()
    assert secret.encode() not in encoded and str(tmp_path).encode() not in encoded
    assert len(encoded) < 4096
    if failure in {"exit", "traceback", "timeout"}:
        assert secret.encode() in (out / "doctor.log").read_bytes()
    with pytest.raises(FileExistsError):
        verify.verify(built, out)
    assert (out / "report.json").read_bytes() == encoded


def test_running_then_successful_acceptance_keeps_full_roundtrip_contract(tmp_path, monkeypatch):
    """Script orchestration only; fake child apps are not native package acceptance."""
    out, seen = tmp_path / "acceptance", []
    incomplete = [False]
    fail_reader = [False]
    reader_launches = [0]

    def fake(command, **kwargs):
        env = kwargs["env"]
        destination = Path(env["HOME"]).parents[1]
        progress = json.loads((destination / "report.json").read_text(encoding="utf-8"))
        seen.append(progress["active_check"])
        assert not progress["passed"] and progress["status"] == "running"
        stdout = b""
        if progress["active_check"] == "reader":
            reader_launches[0] += 1
            if fail_reader[0] and reader_launches[0] == 2:
                (Path(env["PAPERFACT_DATA"]) / "app-fault.log").write_text(
                    "synthetic native fault stack", encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, -11, b"", b"native crash")
        if "--version" in command:
            stdout = b"paperfact 0.5.0.dev\n"
        elif "-c" in command and "demo_workspace" in command[2]:
            with zipfile.ZipFile(command[-1], "w") as archive:
                archive.writestr("files/pdf/demo.pdf", b"synthetic original")
        elif "list-share-link" in command:
            checksum = hashlib.sha256(Path(command[2]).read_bytes()).hexdigest()
            stdout = (command[3] + "#paperfact-sha256=" + checksum).encode()
        elif "list-import" in command:
            workspace = Path(env["PAPERFACT_DATA"])
            workspace.mkdir(exist_ok=True)
            with closing(sqlite3.connect(workspace / "papers.db")) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS list_papers(id TEXT PRIMARY KEY)")
                db.execute("CREATE TABLE IF NOT EXISTS dives(id TEXT PRIMARY KEY,body TEXT)")
                db.execute("INSERT OR IGNORE INTO list_papers VALUES('fixture')")
                db.execute("INSERT OR IGNORE INTO dives VALUES('fixture','saved analysis')")
                db.execute("CREATE TABLE IF NOT EXISTS paper_lineage_sets("
                           "paper_id TEXT PRIMARY KEY,"
                           "corpus_key TEXT)")
                db.execute("INSERT OR IGNORE INTO paper_lineage_sets VALUES(?,?)",
                           ("demo:paperfact", "3390faaf-42c5-4953-8391-024cf4fe7dce"))
        elif "analysis.audit" in command:
            report = dict(
                format="paperfact.lineage-audit.v1", originals_checked=3, originals_total=3,
                semantics="not_checked", sources=[
                    dict(state="available", report=dict(checks=[
                        dict(rule="quote_location", state="located") for _ in range(count)
                    ])) for count in (2, 1, 2)
                ],
            )
            if incomplete[0]:
                report["originals_checked"] = 2
            stdout = json.dumps(dict(ok=True, result=report)).encode()
        elif "list-export" in command:
            shutil.copyfile(destination / "original.zip", command[-1])
        return subprocess.CompletedProcess(command, 0, stdout, b"")

    def integration(command, workspace, env):
        assert "CODEX_HOME" not in env and "ANTHROPIC_API_KEY" not in env
        return dict(retry_preserved=True, restart_recovery=True)

    def handoff(command, env, output):
        current = json.loads((output / "report.json").read_text(encoding="utf-8"))
        assert current["active_check"] == "instance-handoff" and not current["passed"]
        assert "--paper" in command and "CODEX_HOME" not in env
        return dict(primary_ready=True, second_launch_handoff=True, primary_normal_exit=True)

    monkeypatch.setitem(
        sys.modules, "verify_sync_protocol", types.SimpleNamespace(
            verify=lambda *args: dict(authenticated_pull=True, stale_execution_refused=True,
                                      reconnected=True),
        ),
    )
    monkeypatch.setattr(verify, "_instance_handoff", handoff)
    monkeypatch.setattr(verify.subprocess, "run", fake)
    monkeypatch.setitem(
        sys.modules, "verify_local_integration", types.SimpleNamespace(verify=integration)
    )
    first = verify.verify(tmp_path / "built", out)
    saved = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert first == saved and first["passed"] and first["status"] == "passed"
    assert first["active_check"] is first["failure"] is None
    assert {
        "import",
        "import-again",
        "file-fidelity",
        "research-content",
        "lineage-audit",
        "lineage-audit-result",
        "instance-handoff",
        "local-integration",
        "sync-protocol",
    } <= set(first["completed_checks"])
    assert first["instance_handoff"] == dict(
        primary_ready=True, second_launch_handoff=True, primary_normal_exit=True,
    )
    assert first["research_files_preserved"] == 1 and first["integration"]["retry_preserved"]
    assert first["build"] == dict(commit=None, dirty=None, version="0.5.0.dev")
    assert "hosted multi-device sync" in first["limitations"]
    assert verify.verify(tmp_path / "built", tmp_path / "retry")["status"] == "passed"
    assert seen.count("version") == 2
    incomplete[0] = True
    with pytest.raises(AssertionError, match="Packaged acceptance condition failed"):
        verify.verify(tmp_path / "built", tmp_path / "incomplete")
    failed = json.loads((tmp_path / "incomplete" / "report.json").read_text(encoding="utf-8"))
    assert failed["status"] == "failed" and not failed["passed"]
    assert failed["active_check"] == "lineage-audit-result"
    incomplete[0] = False
    monkeypatch.setattr(verify.sys, "platform", "darwin")
    reader_launches[0] = 0
    mac = verify.verify(tmp_path / "built", tmp_path / "mac")
    assert mac["reader_launches_verified"] == reader_launches[0] == 3
    assert mac["completed_checks"].count("reader") == 3
    assert "mac-foreground" in mac["completed_checks"]
    fail_reader[0], reader_launches[0] = True, 0
    with pytest.raises(verify.CheckFailure):
        verify.verify(tmp_path / "built", tmp_path / "mac-intermittent")
    failed = json.loads((tmp_path / "mac-intermittent/report.json").read_text(encoding="utf-8"))
    assert failed["status"] == "failed" and not failed["passed"]
    assert failed["active_check"] == "reader" and failed["failure"]["returncode"] == -11
    assert reader_launches[0] == 2  # Failure is not retried or replaced by a third success.
    assert "export" not in failed["completed_checks"]
    assert (tmp_path / "mac-intermittent/recipient/workspace/app-fault.log").read_text(
        encoding="utf-8",
    ) == "synthetic native fault stack"


def test_main_returns_failure_without_printing_exception_or_old_success(
    tmp_path, monkeypatch, capsys
):
    secret = "private local failure /secret/workspace"

    def failed(*args, **kwargs):
        raise SystemExit(secret)

    monkeypatch.setattr(verify.subprocess, "run", failed)
    out = tmp_path / "acceptance"
    assert verify.main([str(tmp_path / "built"), str(out)]) == 1
    assert secret not in capsys.readouterr().err
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed" and report["failure"]["code"] == "unexpected_error"
    before = (out / "report.json").read_bytes()
    assert verify.main([str(tmp_path / "built"), str(out)]) == 1
    assert "earlier run" in capsys.readouterr().err
    assert (out / "report.json").read_bytes() == before


def test_packaged_metadata_is_bounded_and_does_not_infer_checkout_identity(tmp_path):
    metadata = tmp_path / "Contents" / "Resources" / "build-info.json"
    metadata.parent.mkdir(parents=True)
    for raw in [b"[", b"[]", b"x" * 140000]:
        metadata.write_bytes(raw)
        assert verify.packaged_identity(tmp_path) == dict(commit=None, dirty=None, version=None)
    metadata.write_text(json.dumps(dict(commit="private-account", dirty="true")), encoding="utf-8")
    assert verify.packaged_identity(tmp_path) == dict(commit=None, dirty=None, version=None)


def test_actual_cli_missing_bundle_reports_failure_and_preserves_previous_run(tmp_path):
    built, out = tmp_path / "missing-built-app", tmp_path / "acceptance"
    command = [sys.executable, str(ROOT / "scripts/verify_built_app.py"), str(built), str(out)]
    result = subprocess.run(command, capture_output=True, timeout=30)
    assert result.returncode == 1 and b"Acceptance failed" in result.stderr
    assert b"Traceback" not in result.stderr and str(tmp_path).encode() not in result.stderr
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed" and report["passed"] is False
    assert report["active_check"] == "version" and report["completed_checks"] == ["isolation"]
    assert report["failure"] == dict(code="missing_file", returncode=None)
    before = (out / "report.json").read_bytes()
    result = subprocess.run(command, capture_output=True, timeout=30)
    assert result.returncode == 1 and b"earlier run" in result.stderr
    assert (out / "report.json").read_bytes() == before


@pytest.mark.parametrize(
    "mode", ["success", "not-ready", "second-failed", "second-timeout", "primary-closed"],
)
def test_instance_handoff_requires_live_primary_and_clean_second_launch(
    tmp_path, monkeypatch, mode,
):
    calls = []

    class Primary:
        returncode = None

        def poll(self):
            if mode == "not-ready" or mode == "primary-closed" and "second" in calls:
                self.returncode = 0
            return self.returncode

        def wait(self, timeout):
            self.returncode = 0
            calls.append("wait")
            return 0

        def terminate(self):
            calls.append("terminate")
            self.returncode = -1

    primary = Primary()

    def launch(command, **options):
        assert command == ["fixture-app"] and options["stdin"] == subprocess.DEVNULL
        assert options["env"]["PAPERFACT_SMOKE_SECONDS"] == "20"
        return primary

    def second(command, **options):
        calls.append("second")
        assert options["timeout"] == 15
        assert options["env"]["PAPERFACT_SMOKE_SECONDS"] == "60"
        if mode == "second-timeout":
            raise subprocess.TimeoutExpired(command, 15, output=b"duplicate-window")
        return subprocess.CompletedProcess(command, 2 if mode == "second-failed" else 0, b"", b"")

    monkeypatch.setattr(verify, "_instance_probe", lambda: lambda root: mode != "not-ready")
    monkeypatch.setattr(verify.subprocess, "Popen", launch)
    monkeypatch.setattr(verify.subprocess, "run", second)
    env = {"PAPERFACT_DATA": str(tmp_path / "synthetic"), "PAPERFACT_SMOKE_SECONDS": "5"}
    original = dict(env)
    if mode == "success":
        result = verify._instance_handoff(["fixture-app"], env, tmp_path)
        assert all(result.values()) and calls == ["second", "wait"]
    else:
        error = subprocess.TimeoutExpired if mode == "second-timeout" else verify.CheckFailure
        with pytest.raises(error):
            verify._instance_handoff(["fixture-app"], env, tmp_path)
        assert "terminate" in calls or primary.returncode == 0
        if mode == "not-ready":
            assert "second" not in calls
    assert env == original and not (tmp_path / "synthetic").exists()


@pytest.mark.parametrize("failure", [
    None, "stale_accepted", "bad_header", "graph_lost", "wrong_history_accepted",
    "duplicate_accepted", "prototype_accepted",
])
def test_packaged_sync_verifier_uses_real_isolated_cli_and_listener(tmp_path, monkeypatch, failure):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import verify_sync_protocol
    finally:
        sys.path.pop(0)
    # Source-only children use this checkout, not the venv editable install.
    children = []
    spawn = verify_sync_protocol.subprocess.Popen

    def tracked(*args, **kwargs):
        child = spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(verify_sync_protocol.subprocess, "Popen", tracked)
    post = verify_sync_protocol._post

    def altered(*args, **kwargs):
        status, offered, body = post(*args, **kwargs)
        if failure == "stale_accepted" and status == 428:
            return 200, offered, []
        if failure == "graph_lost" and args[2] == "/v1/pull" and args[3].get("after") == 1:
            return status, offered, []
        if (failure == "wrong_history_accepted" and status == 412
                and args[2] == "/v1/history/push"):
            return 200, offered, body
        if failure == "prototype_accepted" and status == 412 and args[2] == "/v1/push":
            return 200, offered, body
        return status, offered, body

    if failure == "duplicate_accepted":
        run = verify_sync_protocol.subprocess.run

        def accepted_duplicate(command, **kwargs):
            result = run(command, **kwargs)
            if "serve" in command and result.returncode == 2:
                return subprocess.CompletedProcess(command, 0, result.stdout, result.stderr)
            return result

        monkeypatch.setattr(verify_sync_protocol.subprocess, "run", accepted_duplicate)
    if failure == "bad_header":
        # Change the expected contract: actual service still offers its real header.
        monkeypatch.setattr(verify_sync_protocol, "HEADER", "X-Unknown-Sync-Instance")
    monkeypatch.setattr(verify_sync_protocol, "_post", altered)
    try:
        if failure:
            with pytest.raises((ValueError, AssertionError)):
                verify_sync_protocol.verify(
                    [sys.executable, "-m", "paper_daily"], tmp_path / "protocol",
                    {**verify.isolated_env(tmp_path / "isolated"),
                     "PYTHONPATH": str(ROOT / "src")},
                )
        else:
            result = verify_sync_protocol.verify(
                [sys.executable, "-m", "paper_daily"], tmp_path / "protocol",
                {**verify.isolated_env(tmp_path / "isolated"),
                 "PYTHONPATH": str(ROOT / "src")},
            )
            assert result == dict(authenticated_pull=True, stale_execution_refused=True,
                                  reconnected=True, citation_graph=True,
                                  citation_graph_retry=True, citation_graph_restart=True,
                                  duplicate_listener_refused=True, verified_history=True,
                                  wrong_history_refused=True, verified_history_restart=True,
                                  prototype_writes_refused=True)
            assert "token" not in json.dumps(result)
    finally:
        assert children and all(child.poll() is not None for child in children)


def test_acceptance_upload_excludes_synthetic_credentials_and_authority():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    block = workflow.split("name: acceptance-${{ matrix.name }}", 1)[1].split("- uses:", 1)[0]
    paths = [line.strip() for line in block.split("path: |", 1)[1].splitlines() if line.strip()]
    assert paths == [
        "build/frozen-acceptance/*.log",
        "build/frozen-acceptance/recipient/workspace/app-fault.log",
        *[f"build/frozen-acceptance/sync-protocol/{name}.log"
          for name in ("init", "issue", "first-listener", "second-listener")],
    ]


@pytest.fixture(scope='module')
def legacy_upgrade_source(tmp_path_factory):
    import io

    source = tmp_path_factory.mktemp('legacy-upgrade-source')
    result = subprocess.run(
        ['git', '-c', 'core.autocrlf=false', 'archive', '--format=zip', verify.LEGACY_BASELINE,
         'src',
         'scripts/demo_workspace.py'], cwd=ROOT, capture_output=True, check=True, timeout=15)
    with zipfile.ZipFile(io.BytesIO(result.stdout)) as archive:
        # This archive is created from the exact local Git object, not user input.
        archive.extractall(source)
    return source


@pytest.mark.parametrize('damage', [None, 'note', 'pdf', 'deck', 'export-note', 'init-no-op'])
def test_pinned_legacy_source_upgrade_checks_exact_research_not_only_counts(
    tmp_path, legacy_upgrade_source, damage,
):
    out = tmp_path / 'acceptance'
    out.mkdir()
    calls = []
    command = [sys.executable, '-c',
               'import sys;sys.path.insert(0,' + repr(str(ROOT / 'src')) + ');'
               'from paper_daily.integration_entry import main;raise SystemExit(main())']

    def run(label, args, env):
        calls.append(label)
        if label in {'legacy-source-seed', 'legacy-source-export'}:
            assert env['PYTHONPATH'] == str(legacy_upgrade_source / 'src')
        else:
            assert 'PYTHONPATH' not in env
        if label == 'legacy-upgrade-init' and damage == 'init-no-op':
            return  # A zero-exit initializer without schema changes must not pass.
        result = subprocess.run(list(map(str, args)), env=env, cwd=ROOT,
                                capture_output=True, timeout=30)
        (out / (label + '.log')).write_bytes(result.stdout + result.stderr)
        verify.check_process(result, label)
        workspace = Path(env['PAPERFACT_DATA'])
        if (label == 'legacy-upgrade-export'
                and damage in {'note', 'pdf', 'deck', 'export-note'}):
            if damage == 'note':
                from contextlib import closing

                with closing(sqlite3.connect(workspace / 'papers.db')) as conn:
                    conn.execute("UPDATE notes SET body='Changed after upgrade'")
                    conn.commit()
            elif damage == 'pdf':
                pdf = next((workspace / 'pdf').glob('*.pdf'))
                with pdf.open('ab') as stream:
                    stream.write(b'changed')
            elif damage == 'export-note':
                target = workspace.parent / 'returned.zip'
                with zipfile.ZipFile(target) as archive:
                    entries = {name: archive.read(name) for name in archive.namelist()}
                tables = json.loads(entries['tables.json'])
                tables['notes'][0]['body'] = 'Changed exported note'
                entries['tables.json'] = json.dumps(tables).encode('utf-8')
                with zipfile.ZipFile(target, 'w') as archive:
                    for name, body in entries.items():
                        archive.writestr(name, body)
            else:
                deck = next((workspace / 'presentations').rglob('notes.json'))
                value = json.loads(deck.read_text(encoding='utf-8'))
                value['slides'][0]['elements'][0]['x'] += 1
                deck.write_text(json.dumps(value), encoding='utf-8')

    if damage:
        reason = 'schema initialization' if damage == 'init-no-op' else 'changed during upgrade'
        with pytest.raises(ValueError, match=reason):
            verify._legacy_upgrade(command, legacy_upgrade_source, out, run)
    else:
        result = verify._legacy_upgrade(command, legacy_upgrade_source, out, run)
        assert result['baseline_version'] == '0.4.3' and result['source_format_only']
        assert result['research_preserved'] and result['editable_deck_preserved']
        assert result['schema_initialized'] and result['exported_research_preserved']
        assert result['tables']['notes'] == result['tables']['pdf_highlights'] == 1
        assert result['tables']['chat'] == 2 and result['files'] >= 2
        assert not result['older_binary_install_checked'] and not result['gui_upgrade_checked']
        assert 'Saved note' not in json.dumps(result)
    assert calls == ['legacy-source-seed', 'legacy-source-export',
                     'legacy-upgrade-compatibility', 'legacy-upgrade-init', 'legacy-upgrade-export']


def test_legacy_upgrade_refuses_modified_old_source_before_executing(
    tmp_path, legacy_upgrade_source,
):
    source = tmp_path / 'old-source'
    shutil.copytree(legacy_upgrade_source, source)
    target = source / 'src/paper_daily/__init__.py'
    with target.open('ab') as stream:
        stream.write(bytes([10]) + b'# modified baseline' + bytes([10]))
    calls = []
    with pytest.raises(ValueError, match='pinned commit'):
        verify._legacy_upgrade(['must-not-launch'], source, tmp_path,
                               lambda *args: calls.append(args))
    assert not calls and not (tmp_path / 'legacy-upgrade').exists()


def test_ci_legacy_archive_preserves_git_blobs_with_windows_line_endings(tmp_path):
    workflow = (ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8')
    recipe = next(line.strip() for line in workflow.splitlines()
                  if ' archive --format=tar --output=build/upgrade-baseline-0.4.3.tar ' in line)
    archive = tmp_path / 'old-source.tar'
    command = [('--output=' + str(archive)) if arg.startswith('--output=') else arg
               for arg in shlex.split(recipe)]
    env = dict(os.environ, GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='core.autocrlf',
               GIT_CONFIG_VALUE_0='true')
    subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True, timeout=15)
    source = tmp_path / 'source'
    with tarfile.open(archive) as data:
        data.extractall(source, filter='data')
    assert verify._legacy_source_check(source)


@pytest.fixture
def screenshot_tool():
    spec = importlib.util.spec_from_file_location('screenshots', ROOT / 'scripts/screenshots.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_screenshots_wait_for_observed_queued_work_and_timeout(screenshot_tool, monkeypatch):
    calls = []
    app = types.SimpleNamespace(processEvents=lambda: calls.append('event'))
    monkeypatch.setattr(screenshot_tool.time, 'sleep', lambda _seconds: None)
    screenshot_tool.wait_until(app, lambda: len(calls) == 3, label='content')
    assert calls == ['event'] * 3
    with pytest.raises(TimeoutError, match='saved text'):
        screenshot_tool.wait_until(app, lambda: False, label='saved text', seconds=0)


@pytest.mark.parametrize('blank', [False, True])
def test_screenshots_reject_blank_surface_instead_of_publishing_it(
    screenshot_tool, tmp_path, blank,
):
    from PySide6.QtGui import QColor, QImage

    image = QImage(4, 4, QImage.Format.Format_RGBA8888)
    image.fill(QColor('white'))
    if not blank:
        image.setPixelColor(1, 1, QColor('black'))
    target = tmp_path / 'reading.png'
    class Pixmap:
        def toImage(self):  # noqa: N802
            return image

        def save(self, filename):
            return image.save(filename)

    view = types.SimpleNamespace(_body='<p>Saved research</p>', rich=False,
                                 grab_page=lambda: Pixmap())
    reader = types.SimpleNamespace(dive_view=view, preparation=types.SimpleNamespace(busy=True))
    app = types.SimpleNamespace(processEvents=lambda: setattr(reader.preparation, 'busy', False))
    if blank:
        with pytest.raises(RuntimeError, match='surface is blank'):
            screenshot_tool.save_reading_view(app, reader, target)
        assert not target.exists()
    else:
        screenshot_tool.save_reading_view(app, reader, target)
        assert target.exists() and not QImage(str(target)).isNull()


def test_screenshots_ignore_render_completion_for_an_older_page(screenshot_tool, tmp_path):
    from PySide6.QtGui import QColor, QImage

    image = QImage(4, 4, QImage.Format.Format_RGBA8888)
    image.fill(QColor('white'))
    image.setPixelColor(1, 1, QColor('black'))
    scripts = []
    class Page:
        def runJavaScript(self, script, world, callback):  # noqa: N802
            scripts.append(script)
            if len(scripts) == 1:
                view._page_id = 2
            callback(True)

    pixmap = types.SimpleNamespace(toImage=lambda: image, save=lambda name: image.save(name))
    view = types.SimpleNamespace(_body='Saved text', rich=True, _page_id=1,
                                 view=types.SimpleNamespace(page=lambda: Page()),
                                 grab_page=lambda: pixmap)
    reader = types.SimpleNamespace(dive_view=view, preparation=types.SimpleNamespace(busy=False))
    target = tmp_path / 'reading.png'
    screenshot_tool.save_reading_view(types.SimpleNamespace(processEvents=lambda: None),
                                      reader, target)
    assert len(scripts) == 2
    assert 'PAGE_ID === 1' in scripts[0] and 'PAGE_ID === 2' in scripts[1]
    assert QImage(str(target)).pixelColor(1, 1) == QColor('black')
