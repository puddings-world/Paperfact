"""Collection is reproducible local metadata, never evidence that tests passed."""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/collect_test_inventory.py"
COLLECT = runpy.run_path(str(SCRIPT))


def scope(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    return tests


def test_actual_collection_never_executes_poisoned_test_bodies(tmp_path):
    tests = scope(tmp_path)
    (tests / "test_collect_only_sample.py").write_text(
        'import pytest\n@pytest.mark.parametrize("x",[1,2],ids=["first","second"])\n'
        'def test_poison(x):\n    raise AssertionError("test body must not run")\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    inventory = json.loads((tmp_path / "build/test-inventory.json").read_text(encoding="utf-8"))
    assert inventory["nodes"] == [
        "tests/test_collect_only_sample.py::test_poison[first]",
        "tests/test_collect_only_sample.py::test_poison[second]",
    ]
    assert inventory["node_count"] == 2 and inventory["unique_test_functions"] == 1
    assert inventory["parameter_expansion_extra_cases"] == 1
    assert inventory["test_files"] == 1 and inventory["collection_skipped"] == 0
    assert inventory["selection"] == ["tests"] and inventory["collection_scope"] == "full"
    assert inventory["status"] == "collection only; no tests executed by this command"


def test_failed_collection_preserves_previous_inventory_and_explicit_retry_replaces_it(tmp_path):
    scope(tmp_path)
    output = tmp_path / "build/inventory.json"
    output.parent.mkdir()
    output.write_text("previous complete inventory", encoding="utf-8")
    seen = []

    def execute(args, plugins):
        seen.append(args)
        plugin = plugins[0]
        plugin.pytest_collection_finish(
            SimpleNamespace(items=[SimpleNamespace(nodeid="tests/test_a.py::test_a")])
        )
        return 2 if len(seen) == 1 else 0

    assert COLLECT["collect"](tmp_path, output, execute=execute) == 2
    assert output.read_text(encoding="utf-8") == "previous complete inventory"
    assert COLLECT["collect"](tmp_path, output, execute=execute) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["nodes"] == ["tests/test_a.py::test_a"]
    assert all("--collect-only" in args for args in seen)


def test_collection_skip_is_preserved_instead_of_claiming_a_complete_inventory(tmp_path):
    scope(tmp_path)
    output = tmp_path / "build/inventory.json"

    def execute(args, plugins):
        plugins[0].pytest_collectreport(SimpleNamespace(skipped=True))
        plugins[0].pytest_collection_finish(SimpleNamespace(items=[]))
        return 0

    assert COLLECT["collect"](tmp_path, output, execute=execute) == 0
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["collection_skipped"] == 1 and value["node_count"] == 0


@pytest.mark.parametrize("selection", ["../outside.py", "scripts", "tests/missing.py"])
def test_collection_cannot_import_outside_or_nonexistent_scopes(tmp_path, selection):
    scope(tmp_path)
    with pytest.raises(ValueError):
        COLLECT["collect"](
            tmp_path,
            tmp_path / "build/test.json",
            selections=[selection],
            execute=lambda *a, **k: pytest.fail("imported invalid selection"),
        )
    assert not (tmp_path / "build").exists()


def test_collection_cannot_overwrite_a_tracked_file(tmp_path):
    scope(tmp_path)
    tracked = tmp_path / "catalog.json"
    tracked.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError):
        COLLECT["collect"](
            tmp_path, tracked, execute=lambda *a, **k: pytest.fail("imported before validation")
        )
    assert tracked.read_text(encoding="utf-8") == "keep"


def test_selected_collection_records_its_exact_limited_scope(tmp_path):
    tests = scope(tmp_path)
    (tests / "test_selected.py").write_text("def test_one():\n    pass\n", encoding="utf-8")
    output = tmp_path / "build/selected.json"
    assert (
        COLLECT["collect"](
            tmp_path, output, selections=["tests/test_selected.py"], execute=lambda *a, **k: 0
        )
        == 0
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["selection"] == ["tests/test_selected.py"]
    assert value["collection_scope"] == "selected"


def test_real_collection_pins_requested_source_over_a_foreign_package(tmp_path):
    tests = scope(tmp_path)
    current = tmp_path / "src/paper_daily"
    foreign = tmp_path / "foreign/paper_daily"
    current.mkdir(parents=True)
    foreign.mkdir(parents=True)
    (current / "__init__.py").write_text("MARKER='selected-checkout'\n", encoding="utf-8")
    (foreign / "__init__.py").write_text("MARKER='foreign-checkout'\n", encoding="utf-8")
    (tests / "test_selected_source.py").write_text(
        "import paper_daily\nassert paper_daily.MARKER=='selected-checkout'\n"
        "def test_body():\n    raise AssertionError('must not execute')\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(foreign.parent),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONUTF8": "1",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads((tmp_path / "build/test-inventory.json").read_text(encoding="utf-8"))
    assert value["nodes"] == ["tests/test_selected_source.py::test_body"]


def test_in_process_collection_refuses_a_loaded_foreign_app_without_mutating_it(tmp_path):
    scope(tmp_path)
    package = tmp_path / "src/paper_daily"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("MARKER='different'\n", encoding="utf-8")
    from paper_daily import llm

    loaded = sys.modules["paper_daily"]
    original_path = list(sys.path)
    with pytest.raises(ValueError, match="fresh interpreter"):
        COLLECT["collect"](
            tmp_path,
            tmp_path / "build/report.json",
            execute=lambda *a, **k: pytest.fail("collected mixed app versions"),
        )
    assert sys.modules["paper_daily"] is loaded and loaded.llm is llm
    assert sys.path == original_path and not (tmp_path / "build").exists()


@pytest.mark.parametrize("failure", [False, True])
def test_collection_restores_caller_import_paths_on_success_or_error(tmp_path, failure):
    scope(tmp_path)
    source = tmp_path / "src"
    source.mkdir()
    (source / "fixture_collection_dependency.py").write_text(
        "VALUE='from selected source'\n", encoding="utf-8"
    )
    original = list(sys.path)

    def execute(*args, **kwargs):
        import importlib.util

        found = importlib.util.find_spec("fixture_collection_dependency")
        assert Path(found.origin) == source / "fixture_collection_dependency.py"
        if failure:
            raise OSError("synthetic collector error")
        return 0

    if failure:
        with pytest.raises(OSError):
            COLLECT["collect"](tmp_path, tmp_path / "build/report.json", execute=execute)
    else:
        assert COLLECT["collect"](tmp_path, tmp_path / "build/report.json", execute=execute) == 0
    assert sys.path == original


@pytest.mark.parametrize("failure", [False, True])
def test_collection_isolates_outer_pytest_options_and_restores_them(tmp_path, monkeypatch, failure):
    scope(tmp_path)
    monkeypatch.setenv("PYTEST_ADDOPTS", "--outer-run-only-option")

    def execute(*args, **kwargs):
        assert "PYTEST_ADDOPTS" not in os.environ
        if failure:
            raise OSError("synthetic collection failure")
        return 0

    if failure:
        with pytest.raises(OSError, match="synthetic collection failure"):
            COLLECT["collect"](tmp_path, tmp_path / "build/report.json", execute=execute)
    else:
        assert COLLECT["collect"](
            tmp_path, tmp_path / "build/report.json", execute=execute
        ) == 0
    assert os.environ["PYTEST_ADDOPTS"] == "--outer-run-only-option"


def test_actual_collection_ignores_outer_execution_options(tmp_path):
    tests = scope(tmp_path)
    (tests / "test_inventory_only.py").write_text(
        "def test_not_executed():\n    raise AssertionError('body must not run')\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_ADDOPTS": "--outer-run-only-option",
             "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONUTF8": "1"},
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads((tmp_path / "build/test-inventory.json").read_text(encoding="utf-8"))
    assert value["nodes"] == ["tests/test_inventory_only.py::test_not_executed"]
    assert value["status"] == "collection only; no tests executed by this command"
