import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

CHECK = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "check.py"))


@pytest.mark.parametrize("failure", [None, 0, 1, 2, 3])
def test_full_check_propagates_failure_and_stops_without_reporting_success(
    tmp_path, monkeypatch, capsys, failure
):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: "node")
    observed = []

    def execute(command, **kwargs):
        observed.append((command, kwargs))
        return SimpleNamespace(returncode=7 if len(observed) - 1 == failure else 0)

    result = CHECK["run_checks"](tmp_path, execute, files=[])
    assert result == (0 if failure is None else 7)
    assert len(observed) == (4 if failure is None else failure + 1)
    assert ("All checks passed." in capsys.readouterr().out) == (failure is None)
    assert all(options["env"]["QT_QPA_PLATFORM"] == "offscreen" for _, options in observed)


def test_missing_frontend_runtime_is_a_failure_not_a_silent_skip(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: None)
    assert CHECK["run_checks"](tmp_path, lambda *a, **k: pytest.fail("missing runtime")) == 1
    assert "Node.js is required" in capsys.readouterr().out


def test_a_fresh_clone_gets_a_folder_for_the_test_temp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: "node")
    basetemps = []

    def execute(command, **kwargs):
        if "--basetemp" in command:
            basetemps.append(Path(command[command.index("--basetemp") + 1]))
        return SimpleNamespace(returncode=0)

    assert CHECK["run_checks"](tmp_path, execute, files=[]) == 0
    assert basetemps and basetemps[0].parent.is_dir()


@pytest.mark.parametrize("passed", [True, False])
def test_test_temp_files_are_removed_after_a_pass_and_kept_after_a_failure(
    tmp_path, monkeypatch, passed
):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: "node")
    basetemps = []

    def execute(command, **kwargs):
        if "--basetemp" in command:
            base = Path(command[command.index("--basetemp") + 1])
            (base / "test_x0").mkdir(parents=True)
            (base / "test_x0" / "paper.pdf").write_bytes(b"%PDF")
            # Git writes its objects read-only; a checkout made by a test must still go.
            (base / "test_x0" / "object").write_bytes(b"blob")
            (base / "test_x0" / "object").chmod(0o444)
            basetemps.append(base)
            return SimpleNamespace(returncode=0 if passed else 1)
        return SimpleNamespace(returncode=0)

    assert CHECK["run_checks"](tmp_path, execute, files=[]) == (0 if passed else 1)
    assert basetemps and basetemps[0].exists() != passed


# Built from pieces so that this file does not trip the scan it tests.
FAKE_SECRETS = {
    "Anthropic key": "sk-" + "ant-api03-" + "x" * 40,
    "GitHub token": "gh" + "p_" + "A" * 36,
    "Google OAuth secret": "GOC" + "SPX-" + "a" * 28,
    "private key": "-----BEGIN " + "RSA PRIVATE KEY-----",
}


@pytest.mark.parametrize("kind", FAKE_SECRETS)
def test_a_committable_credential_fails_the_check_before_anything_runs(
    tmp_path, monkeypatch, capsys, kind
):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: "node")
    leak = tmp_path / "config.py"
    leak.write_text(f'TOKEN = "{FAKE_SECRETS[kind]}"\n', encoding="utf-8")
    ran = []
    result = CHECK["run_checks"](tmp_path, lambda *a, **k: ran.append(a), files=[leak])
    out = capsys.readouterr().out
    assert result == 1 and not ran
    assert f"config.py:1: {kind}" in out
    # The report names where, never what: it is safe to paste into an issue.
    assert FAKE_SECRETS[kind] not in out


def test_private_terms_come_from_the_ignored_env_file_and_match_any_case(tmp_path, monkeypatch):
    monkeypatch.delenv("PAPERFACT_PRIVATE_TERMS", raising=False)
    (tmp_path / ".env").write_text(
        "PAPERFACT_PRIVATE_TERMS=someone@example.net, jdoe-laptop\n", encoding="utf-8"
    )
    notes = tmp_path / "notes.md"
    notes.write_text("ok\nContact SomeOne@Example.NET\nbuilt on jdoe-laptop\n", encoding="utf-8")
    terms = CHECK["private_terms"](tmp_path)
    assert CHECK["scan_privacy"](tmp_path, [notes], terms) == [
        "notes.md:2: private term #1",
        "notes.md:3: private term #2",
    ]


def test_binary_files_and_clean_text_pass(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\0\0" + FAKE_SECRETS["GitHub token"].encode())
    readme = tmp_path / "README.md"
    readme.write_text("Set S2_API_KEY in .env; see sk-ant-... in the docs.\n", encoding="utf-8")
    assert CHECK["scan_privacy"](tmp_path, [image, readme], []) == []


def test_outside_a_git_checkout_the_scan_fails_rather_than_passing_blind(tmp_path, monkeypatch):
    failed = SimpleNamespace(returncode=128, stdout=b"")
    monkeypatch.setattr(CHECK["subprocess"], "run", lambda *a, **k: failed)
    assert CHECK["committable_files"](tmp_path) is None



def test_full_check_includes_mobile_and_real_service_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: "node")
    observed = []

    def execute(command, **options):
        observed.append(command)
        return SimpleNamespace(returncode=0)

    assert CHECK["run_checks"](tmp_path, execute, files=[]) == 0
    assert observed[-1] == [
        "node", str(tmp_path / "mobile" / "check.mjs"), "--python", CHECK["sys"].executable
    ]


def fixture_test(root, name):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# fixture\n", encoding="utf-8")
    return name


def report_at(root):
    return json.loads((root / "build" / "check-latest.json").read_text(encoding="utf-8"))


def test_focused_python_needs_no_node_and_never_claims_full_pass(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: None)
    name = fixture_test(tmp_path, "tests/test_example.py") + "::test_case"
    observed = []
    times = iter(range(20))

    def execute(command, **kwargs):
        observed.append(command)
        return SimpleNamespace(returncode=0)

    assert CHECK["run_checks"](tmp_path, execute, files=[], profile="focused",
                               python_tests=[name, name], clock=lambda: next(times)) == 0
    assert len(observed) == 2
    assert observed[1].count(name) == 1
    assert "--durations=20" in observed[1]
    assert "-x" in observed[1]
    assert "faulthandler_timeout=60" in observed[1]
    report = report_at(tmp_path)
    assert report["status"] == "passed" and not report["full_check_passed"]
    assert report["selection"] == {"python": [name], "frontend": [], "mobile": False}
    assert [s["seconds"] for s in report["stages"]] == [1, 1, 1]
    assert report["seconds"] == 7
    assert "All checks passed." not in capsys.readouterr().out
    assert str(tmp_path) not in json.dumps(report)


@pytest.mark.parametrize("options", [
    {"profile": "focused"},
    {"profile": "full", "python_tests": ["tests/test_example.py"]},
    {"profile": "docs", "mobile": True},
    {"profile": "focused", "python_tests": ["../test_outside.py"]},
    {"profile": "focused", "python_tests": ["tests/test_missing.py"]},
    {"profile": "focused", "python_tests": ["--collect-only"]},
    {"profile": "focused", "python_tests": ["tests/test_example.py::"]},
    {"profile": "focused", "frontend_tests": ["tests/test_example.py"]},
    {"profile": "unknown"},
])
def test_invalid_scope_fails_without_running_or_claiming_success(tmp_path, options):
    fixture_test(tmp_path, "tests/test_example.py")
    assert CHECK["run_checks"](tmp_path, lambda *a, **k: pytest.fail("invalid scope ran"),
                               files=[], **options) == 1
    assert report_at(tmp_path)["status"] == "failed"
    assert not report_at(tmp_path)["full_check_passed"]


def test_docs_profile_runs_fixed_contract_tests_without_node(tmp_path, monkeypatch):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: None)
    for name in CHECK["DOC_TESTS"]:
        fixture_test(tmp_path, name)
    observed = []

    def execute(command, **kwargs):
        observed.append(command)
        return SimpleNamespace(returncode=0)

    assert CHECK["run_checks"](tmp_path, execute, files=[], profile="docs") == 0
    assert len(observed) == 2
    assert all(name in observed[1] for name in CHECK["DOC_TESTS"])
    assert not report_at(tmp_path)["full_check_passed"]


@pytest.mark.parametrize("mobile", [False, True])
def test_selected_js_or_mobile_needs_node_and_runs_exact_scope(tmp_path, monkeypatch, mobile):
    name = fixture_test(tmp_path, "tests/test_example.mjs")
    options = {"mobile": True} if mobile else {"frontend_tests": [name]}
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: None)
    assert CHECK["run_checks"](tmp_path, files=[], profile="focused", **options) == 1
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: "node")
    observed = []

    def execute(command, **kwargs):
        observed.append(command)
        return SimpleNamespace(returncode=0)

    assert CHECK["run_checks"](tmp_path, execute, files=[], profile="focused", **options) == 0
    assert len(observed) == 2
    if mobile:
        assert observed[-1][1] == str(tmp_path / "mobile" / "check.mjs")
    else:
        assert observed[-1] == ["node", "--test", name]


@pytest.mark.parametrize("failure", ["exit", "interrupt", "launch"])
def test_failed_or_interrupted_run_replaces_previous_success_report(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda name: "node")
    assert CHECK["run_checks"](tmp_path, lambda *a, **k: SimpleNamespace(returncode=0),
                               files=[]) == 0
    assert report_at(tmp_path)["full_check_passed"]

    def execute(*args, **kwargs):
        in_progress = report_at(tmp_path)
        assert in_progress["status"] == "running"
        assert not in_progress["full_check_passed"]
        assert in_progress["stages"][-1]["status"] == "running"
        if failure == "interrupt":
            raise KeyboardInterrupt
        if failure == "launch":
            raise OSError("private filesystem path")
        return SimpleNamespace(returncode=7)

    expected = {"exit": 7, "interrupt": 130, "launch": 1}[failure]
    assert CHECK["run_checks"](tmp_path, execute, files=[]) == expected
    report = report_at(tmp_path)
    assert not report["full_check_passed"]
    assert report["stages"][-1]["status"] == (
        "interrupted" if failure == "interrupt" else "failed"
    )
    assert "private filesystem path" not in json.dumps(report)
    assert not list((tmp_path / "build").glob("check-report-*.tmp"))


def test_focused_checks_still_scan_unselected_committable_files(tmp_path):
    name = fixture_test(tmp_path, "tests/test_example.py")
    leak = tmp_path / "unrelated.txt"
    leak.write_text(FAKE_SECRETS["GitHub token"], encoding="utf-8")
    assert CHECK["run_checks"](tmp_path, lambda *a, **k: pytest.fail("privacy failed"),
                               files=[leak], profile="focused", python_tests=[name]) == 1
    assert report_at(tmp_path)["stages"][0]["status"] == "failed"


def test_cli_help_explains_profiles_without_running_checks(tmp_path, capsys):
    with pytest.raises(SystemExit) as stopped:
        CHECK["main"](tmp_path, ["--help"])
    assert stopped.value.code == 0
    assert "focused" in capsys.readouterr().out
    assert not (tmp_path / "build").exists()


@pytest.mark.parametrize("name", ["new-device.json", "unexpected-config.txt"])
def test_device_connection_record_stops_checks_without_echoing_credential(
    tmp_path, monkeypatch, capsys, name
):
    monkeypatch.setattr(CHECK["shutil"], "which", lambda _name: "node")
    token = "device-runtime-" + "x" * 43
    packet = tmp_path / name
    packet.write_text(json.dumps({
        "format": 1, "endpoint": "https://sync.example.org",
        "workspace_id": "workspace", "device_id": "mac", "token": token,
    }), encoding="utf-8")
    called = []

    def execute(*args, **kwargs):
        called.append(args)
        return SimpleNamespace(returncode=0)

    assert CHECK["run_checks"](tmp_path, execute, files=[packet]) == 1
    report = capsys.readouterr().out
    assert not called and token not in report
    assert f"{name}:1: Paperfact device credential" in report


@pytest.mark.parametrize("record", [
    {"format": 1, "endpoint": "https://sync.example.org", "workspace_id": "workspace",
     "device_id": "example", "token": "REPLACE_WITH_NEW_DEVICE_TOKEN"},
    {"format": 1, "endpoint": "https://sync.example.org", "workspace_id": "workspace",
     "device_id": "example", "token": ""},
    {"format": 1, "token": "unrelated application metadata"},
])
def test_connection_placeholders_and_unrelated_json_remain_committable(tmp_path, record):
    packet = tmp_path / "example.json"
    packet.write_text(json.dumps(record), encoding="utf-8")
    assert CHECK["scan_privacy"](tmp_path, [packet], []) == []


def test_private_sync_outputs_are_absent_from_a_real_git_file_inventory(tmp_path):
    import subprocess

    root = Path(__file__).resolve().parents[1]
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / ".gitignore").write_bytes((root / ".gitignore").read_bytes())
    for name in ("desktop-connection.json", "nested/mac-connection.json",
                 "sync-service/authority.sqlite", ".paperfact-sync/service/authority.sqlite"):
        item = tmp_path / name
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_text("synthetic private fixture", encoding="utf-8")
    (tmp_path / "source.py").write_text("# committable fixture\n", encoding="utf-8")
    result = CHECK["committable_files"](tmp_path)
    assert {item.relative_to(tmp_path).as_posix() for item in result} == {
        ".gitignore", "source.py"
    }


def test_critical_profile_runs_named_journeys_without_claiming_exhaustive_pass(tmp_path):
    expected = [test for group in CHECK["CRITICAL_JOURNEYS"].values() for test in group]
    for test in expected:
        fixture_test(tmp_path, test.partition("::")[0])
    observed = []
    def execute(command, **kwargs):
        observed.append(command)
        return SimpleNamespace(returncode=0)
    assert CHECK["run_checks"](tmp_path, execute, files=[], profile="critical") == 0
    report = report_at(tmp_path)
    assert report["selection"]["python"] == expected
    assert report["journeys"] == {
        key: list(value) for key, value in CHECK["CRITICAL_JOURNEYS"].items()
    }
    assert report["status"] == "passed" and not report["full_check_passed"]
    assert observed[1][5:5 + len(expected)] == expected


def test_cli_defaults_to_critical_journeys():
    calls = []
    main = CHECK["main"]
    original = main.__globals__["run_checks"]
    try:
        main.__globals__["run_checks"] = lambda root, **options: calls.append(options) or 0
        assert main(Path("."), []) == 0
    finally:
        main.__globals__["run_checks"] = original
    assert calls[0]["profile"] == "critical"
