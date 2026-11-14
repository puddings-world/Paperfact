"""Critical user journeys by default; exhaustive checks remain explicitly available."""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

# Credential shapes that must never reach the public repo, whoever is committing.
SECRET_PATTERNS = {
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "Anthropic key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "OpenAI key": r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}",
    "GitHub token": r"\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,})",
    "Google API key": r"\bAIza[0-9A-Za-z_-]{35}",
    "Google OAuth secret": r"\bGOCSPX-[A-Za-z0-9_-]{20,}",
    "Google access token": r"\bya29\.[A-Za-z0-9_-]{20,}",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
}


def remove_tree(path: Path) -> None:
    """Delete a test temp folder, including read-only files such as git objects."""

    def writable_then_retry(function, name, _error):
        os.chmod(name, stat.S_IWRITE)
        function(name)

    if path.exists():
        shutil.rmtree(path, onerror=writable_then_retry)


def committable_files(root):
    """Every file a commit could pick up: tracked, plus new files not ignored."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
    )
    if listed.returncode:
        return None
    names = {n for n in listed.stdout.decode("utf-8").split("\0") if n}
    return sorted(root / n for n in names if (root / n).is_file())


def private_terms(root):
    """A maintainer's own identifiers (an address, a username), listed in the ignored
    .env so that the check guarding them does not publish them itself."""
    sys.path.insert(0, str(root / "src"))
    from paper_daily.runtime import read_env_file

    raw = os.environ.get("PAPERFACT_PRIVATE_TERMS") or read_env_file(root / ".env").get(
        "PAPERFACT_PRIVATE_TERMS", ""
    )
    return [t.strip() for t in raw.split(",") if t.strip()]


def scan_privacy(root, files, terms):
    """Findings as `path:line: kind`, never echoing the matched text, so the report
    itself is safe to paste anywhere."""
    rules = [(name, re.compile(rx)) for name, rx in SECRET_PATTERNS.items()]
    rules += [
        (f"private term #{i}", re.compile(re.escape(t), re.IGNORECASE))
        for i, t in enumerate(terms, 1)
    ]
    found = []
    for path in files:
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", errors="replace")
        if text.lstrip().startswith("{"):
            try:
                record = json.loads(text)
            except (ValueError, RecursionError):
                record = None
            if (
                isinstance(record, dict)
                and set(record) == {"format", "endpoint", "workspace_id", "device_id", "token"}
                and type(record["format"]) is int and record["format"] == 1
                and isinstance(record["token"], str)
                and record["token"] not in ("", "REPLACE_WITH_NEW_DEVICE_TOKEN")
            ):
                found.append(f"{path.relative_to(root).as_posix()}:1: Paperfact device credential")
        for number, line in enumerate(text.splitlines(), 1):
            found += [
                f"{path.relative_to(root).as_posix()}:{number}: {name}"
                for name, rule in rules
                if rule.search(line)
            ]
    return found


DOC_TESTS = (
    "tests/test_usage_docs.py",
    "tests/test_distribution.py",
    "tests/test_check_script.py",
)


# Existing behavior tests, grouped by the user outcome they protect.
CRITICAL_JOURNEYS = {
    "Startup": ("tests/test_smoke_onboarding.py",),
    "List package and PDF preservation": (
        "tests/test_bundle.py::test_a_bundle_carries_the_analyses_and_files_but_not_history",
        "tests/test_bundle.py::test_the_receivers_own_work_wins_unless_asked",
        "tests/test_bundle.py::test_the_lists_pinned_papers_and_order_travel_with_it",
    ),
    "Notes and durable Q&A": (
        "tests/test_list_notes.py::test_a_note_is_rewritten_cleared_and_bounded",
        "tests/test_research_chat.py::test_question_is_durable_before_answer_and_exact_answer_retry_is_idempotent",
        "tests/test_research_chat.py::test_workspace_switch_writes_only_original_database",
    ),
    "AI configuration isolation": (
        "tests/test_ai_profiles.py::test_backend_switch_drops_previous_credentials_endpoint_and_model",
        "tests/test_ai_profiles.py::test_task_routes_do_not_change_default_and_can_follow_it_again",
    ),
    "Offline synchronization": (
        "tests/test_sync_client.py::test_list_and_note_converge_after_restart_and_duplicate_transfer",
        "tests/test_sync_client.py::test_offline_concurrent_note_edits_preserve_both_versions",
        "tests/test_sync_client.py::test_timeout_after_remote_commit_retries_once",
    ),
    "Backup and restore": (
        "tests/test_workspace_dialog.py::test_actual_backup_preview_restore_buttons_preserve_research",
        "tests/test_workspace_dialog.py::test_cancelled_file_choosers_do_not_create_jobs",
    ),
}


def selected_tests(root, values, suffix):
    """Only explicit repository test files, optionally a pytest node ID."""
    selected = []
    for value in values:
        filename, separator, node_id = value.partition("::")
        path = (root / filename).resolve()
        try:
            relative = path.relative_to(root.resolve())
        except ValueError:
            raise ValueError("Test selections must stay inside tests/.") from None
        if (
            not relative.parts or relative.parts[0] != "tests"
            or not path.is_file() or path.suffix != suffix
            or not path.name.startswith("test_")
            or (separator and (suffix != ".py" or not node_id))
        ):
            raise ValueError("Select existing tests/test_* files of the appropriate type.")
        normalized = relative.as_posix() + (separator + node_id if separator else "")
        if normalized not in selected:
            selected.append(normalized)
    return selected


def check_plan(root, profile, python_tests, frontend_tests, mobile):
    if profile not in {"full", "critical", "focused", "docs"}:
        raise ValueError("Unknown check profile.")
    if profile != "focused" and (python_tests or frontend_tests or mobile):
        raise ValueError("Selections require --profile focused; fixed profiles cannot be narrowed.")
    if profile == "focused" and not (python_tests or frontend_tests or mobile):
        raise ValueError("Focused checks require --python, --frontend or --mobile.")
    python_tests = selected_tests(root, python_tests, ".py")
    frontend_tests = selected_tests(root, frontend_tests, ".mjs")
    if profile == "critical":
        python_tests = selected_tests(root, [
            test for group in CRITICAL_JOURNEYS.values() for test in group
        ], ".py")
    if profile == "docs":
        python_tests = selected_tests(root, DOC_TESTS, ".py")
    if profile == "full":
        python_tests = ["tests"]
        frontend_tests = [p.relative_to(root).as_posix()
                          for p in sorted((root / "tests").glob("test_*.mjs"))]
    needs_node = profile == "full" or bool(frontend_tests) or mobile
    node = shutil.which("node") if needs_node else None
    if needs_node and not node:
        raise ValueError("Node.js is required for the frontend tests; no checks were skipped.")
    checks = [("Ruff", [sys.executable, "-m", "ruff", "check", "."])]
    if python_tests:
        checks.append(("Python and desktop stress tests" if profile == "full"
                       else "Selected Python tests", [
            sys.executable, "-X", "faulthandler", "-m", "pytest", *python_tests,
            "-q", "-x", "--tb=short", "--durations=20", "-o", "faulthandler_timeout=60",
            "-p", "no:cacheprovider",
            "--basetemp", str(root / "build" / ("check-" + uuid4().hex[:8])),
        ]))
    if profile == "full" or frontend_tests:
        checks.append(("Frontend tests", [node, "--test", *frontend_tests]))
    if profile == "full" or mobile:
        checks.append(("Mobile domain and Python service integration", [
            node, str(root / "mobile" / "check.mjs"), "--python", sys.executable,
        ]))
    return checks, {"python": python_tests, "frontend": frontend_tests,
                    "mobile": profile == "full" or mobile}


def run_checks(root, execute=subprocess.run, files=None, *, profile="full",
               python_tests=(), frontend_tests=(), mobile=False, clock=time.perf_counter):
    started = clock()
    report = {"profile": profile, "status": "running", "full_check_passed": False,
              "stages": []}
    run_id = os.environ.get("PAPERFACT_CHECK_RUN_ID", "")
    if len(run_id) == 32 and all(char in "0123456789abcdef" for char in run_id):
        report["run_id"] = run_id
    # No credentials, environment dumps or command/executable paths in reports.
    (root / "build").mkdir(exist_ok=True)
    temporary = root / "build" / ("check-report-" + uuid4().hex + ".tmp")

    def save_report():
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(root / "build" / "check-latest.json")

    # A killed process must not leave a previous successful run looking current.
    save_report()
    stage = None
    code = 1
    try:
        checks, report["selection"] = check_plan(
            root, profile, python_tests, frontend_tests, mobile,
        )
        if profile == "critical":
            report["journeys"] = CRITICAL_JOURNEYS
            for name in CRITICAL_JOURNEYS:
                print(f"Protecting: {name}", flush=True)
        print(f"Profile: {profile}. Stage counts are not time estimates.", flush=True)
        print("Pytest percentages count cases in its phase, not overall progress.", flush=True)
        for index, (name, command) in enumerate([("Privacy scan", None), *checks], 1):
            print(f"Checking: {name} [stage {index}/{len(checks) + 1}]", flush=True)
            stage = {"name": name, "status": "running"}
            report["stages"].append(stage)
            save_report()
            stage_started = clock()
            if command is None:
                files = committable_files(root) if files is None else files
                if files is None:
                    print("FAILED: Privacy scan (not a git checkout)")
                    code = 1
                else:
                    findings = scan_privacy(root, files, private_terms(root))
                    if findings:
                        print("\n".join(findings))
                    code = int(bool(findings))
            else:
                code = execute(command, cwd=root, env={
                    **os.environ, "QT_QPA_PLATFORM": "offscreen", "PAPERFACT_PLAIN_VIEWS": "1",
                }).returncode
            stage.update(seconds=round(clock() - stage_started, 3), exit_code=code,
                         status="failed" if code else "passed")
            if command is not None and "--basetemp" in command and not code:
                # A passing run's test files are never read again; a full run leaves
                # gigabytes. A failing run keeps them for diagnosis.
                remove_tree(Path(command[command.index("--basetemp") + 1]))
            print(f"{name}: {stage['status']} in {stage['seconds']:.1f}s", flush=True)
            if code:
                break
        report["status"] = "failed" if code else "passed"
        report["full_check_passed"] = profile == "full" and code == 0
        if not code:
            print("All checks passed." if profile == "full" else
                  f"{profile.capitalize()} checks passed; exhaustive suite not run.",
                  flush=True)
    except KeyboardInterrupt:
        code = 130
        report["status"] = "interrupted"
        print("Check interrupted; no full-check pass recorded.", flush=True)
    except (ValueError, OSError) as error:
        code = 1
        report["status"] = "failed"
        # Selection errors contain only fixed messages; OS errors can contain private paths.
        print(str(error) if isinstance(error, ValueError) else
              f"Check failed ({type(error).__name__}); no full-check pass recorded.", flush=True)
    finally:
        if stage and stage["status"] == "running":
            stage.update(status=report["status"], seconds=round(clock() - stage_started, 3),
                         exit_code=code)
        report["seconds"] = round(clock() - started, 3)
        save_report()
        print(f"Total: {report['seconds']:.1f}s. Report: build/check-latest.json", flush=True)
    return code


def main(root, argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", choices=("critical", "full", "focused", "docs"), default="critical",
    )
    parser.add_argument("--python", nargs="+", default=[], dest="python_tests")
    parser.add_argument("--frontend", nargs="+", default=[], dest="frontend_tests")
    parser.add_argument("--mobile", action="store_true")
    return run_checks(root, **vars(parser.parse_args(argv)))


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes

        # Child tests report native failures to the terminal instead of opening
        # a blocking Windows crash dialog on the user's desktop.
        ctypes.windll.kernel32.SetErrorMode(0x8003)
    raise SystemExit(main(Path(__file__).resolve().parents[1]))
