"""The generated explanation map tells readers what is known, stale and unreviewed."""

import hashlib
import json
import runpy
from pathlib import Path

import pytest

REPORT = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/test_report.py"))


def encode(path, data):
    path.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")


@pytest.fixture
def sample(tmp_path):
    folder = tmp_path / "tests"
    folder.mkdir()
    source = folder / "test_reviewed.py"
    source.write_text(
        "def test_reviewed(flag):\n    assert flag in (False, True)\n", encoding="utf-8"
    )
    identity = "tests/test_reviewed.py::test_reviewed"
    nodes = [identity + "[off]", identity + "[on]"]
    inventory = tmp_path / "inventory.json"
    encode(
        inventory,
        {
            "nodes": [*nodes, "tests/test_other.py::test_undocumented"],
            "node_count": 3,
            "unique_test_functions": 2,
            "parameter_expansion_extra_cases": 1,
            "test_files": 2,
        },
    )
    prose = {
        "title": "Repeated checks keep the newest request",
        "scenario": "Hold the first synthetic status lookup.",
        "actions": ["Submit one hundred duplicates.", "Release the held result."],
        "expected_outcomes": ["Only the newest scope applies."],
        "risk_protected": "No stale result replaces the current view.",
        "not_proven": ["No real model requests or scientific quality are tested."],
    }
    catalog = tmp_path / "catalog.json"
    value = {
        "format": "paperfact.test-catalog.v1",
        "reviewed_against": "a" * 40,
        "reviewed_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "collection_inventory_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
        "entries": [
            {
                "id": identity,
                "source": {"path": "tests/test_reviewed.py", "function": "test_reviewed"},
                "primary_group": "desktop/background-status",
                "case_count": 2,
                "parameter_matrix": {"cases": [{"node_id": node} for node in nodes]},
                "en": dict(prose),
                "zh-TW": dict(prose),
            }
        ],
    }
    encode(catalog, value)
    return tmp_path, source, catalog, inventory


def load(sample):
    root, _source, catalog, inventory = sample
    return REPORT["build_model"](root, catalog, inventory)


def test_report_explains_actions_outcomes_and_limits_without_running_tests(sample, monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("executed a command"))
    model = load(sample)
    result = REPORT["render"](model, "en")
    assert model["execution_status"] == "not_executed"
    assert model["counts"] == {
        "node_count": 3,
        "unique_test_functions": 2,
        "test_files": 2,
        "parameter_expansion_extra_cases": 1,
    }
    assert model["entries"][0]["issues"] == []
    assert "Submit one hundred duplicates." in result
    assert "Only the newest scope applies." in result
    assert "No real model requests or scientific quality are tested." in result
    assert "not execution results" in result
    assert "No reviewed explanation yet" in result
    assert "test_undocumented" in result
    assert "Test Undocumented" not in result
    assert "passed" not in result.lower()
    assert 'label for="search"' in result and 'type="checkbox"' in result
    assert '<html lang="en">' in result


def test_traditional_chinese_labels_are_preserved_as_unicode(sample):
    result = REPORT["render"](load(sample), "zh-TW")
    assert "\u64cd\u4f5c\u6b65\u9a5f" in result
    assert "\u9810\u671f\u7d50\u679c" in result
    assert "\u672a\u9a57\u8b49\u7bc4\u570d" in result
    assert "\u5c1a\u672a\u64b0\u5beb\u9010\u9805\u8aaa\u660e" in result


@pytest.mark.parametrize(
    "change,issue",
    [
        ("content", "source_changed"),
        ("missing", "source_unavailable"),
        ("digest", "missing_source_digest"),
        ("matrix", "parameter_matrix_changed"),
        ("function", "function_missing"),
    ],
)
def test_changed_or_unverifiable_explanation_is_visibly_marked_for_review(sample, change, issue):
    _root, source, catalog, inventory = sample
    value = json.loads(catalog.read_text(encoding="utf-8"))
    if change == "content":
        source.write_text("def test_reviewed(flag):\n    assert False\n", encoding="utf-8")
    elif change == "missing":
        source.unlink()
    elif change == "digest":
        value.pop("reviewed_source_sha256")
    elif change == "matrix":
        data = json.loads(inventory.read_text(encoding="utf-8"))
        data["nodes"][1] = data["nodes"][1].replace("[on]", "[changed]")
        encode(inventory, data)
    else:
        source.write_text("def test_other():\n    pass\n", encoding="utf-8")
        value["reviewed_source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    encode(catalog, value)
    model = load(sample)
    assert issue in model["entries"][0]["issues"]
    result = REPORT["render"](model, "en")
    assert "Needs review: source or collected cases changed" in result
    assert "Repeated checks keep the newest request" in result


def test_new_unrelated_collected_case_preserves_verified_explanation_and_flags_inventory(sample):
    _root, _source, _catalog, inventory = sample
    data = json.loads(inventory.read_text(encoding="utf-8"))
    data["nodes"].append("tests/test_other.py::test_another")
    data.update(node_count=4, unique_test_functions=3)
    encode(inventory, data)
    model = load(sample)
    assert model["inventory_changed"] and not model["entries"][0]["issues"]
    assert len(model["undocumented"]) == 2
    assert "Collection inventory changed" in REPORT["render"](model, "en")


def test_prose_and_node_ids_are_escaped_without_replacing_user_text_tokens(sample):
    _root, _source, catalog, inventory = sample
    data = json.loads(catalog.read_text(encoding="utf-8"))
    title = '<img src=x onerror="alert(1)"> @@MISSING@@'
    data["entries"][0]["en"]["title"] = title
    encode(catalog, data)
    nodes = json.loads(inventory.read_text(encoding="utf-8"))
    nodes["nodes"][-1] += "[</summary><script>evil()</script>]"
    encode(inventory, nodes)
    result = REPORT["render"](load(sample), "en")
    assert "<img src=x" not in result and "<script>evil()" not in result
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt; @@MISSING@@" in result
    assert "&lt;/summary&gt;&lt;script&gt;evil()&lt;/script&gt;" in result


@pytest.mark.parametrize(
    "node", [None, {}, "../outside.py::test_x", "tests/test_a.py::helper", "tests/test_a.py"]
)
def test_invalid_nodes_fail_before_a_report_can_be_written(sample, node):
    root, _source, catalog, inventory = sample
    encode(inventory, {"nodes": [node]})
    with pytest.raises(REPORT["ReportError"]):
        REPORT["write_report"](root, catalog, inventory, root / "build/report.html")
    assert not (root / "build").exists()


@pytest.mark.parametrize(
    "change",
    [
        "duplicate-node",
        "false-count",
        "duplicate-entry",
        "wrong-matrix",
        "escape-source",
        "duplicate-json",
    ],
)
def test_malformed_or_ambiguous_catalogs_are_refused(sample, change):
    _root, _source, catalog, inventory = sample
    data = json.loads(catalog.read_text(encoding="utf-8"))
    nodes = json.loads(inventory.read_text(encoding="utf-8"))
    if change == "duplicate-node":
        nodes["nodes"].append(nodes["nodes"][0])
    elif change == "false-count":
        nodes["node_count"] = True
    elif change == "duplicate-entry":
        data["entries"].append(data["entries"][0])
    elif change == "wrong-matrix":
        data["entries"][0]["parameter_matrix"]["cases"][0]["node_id"] = "tests/other.py::test_x"
    elif change == "escape-source":
        data["entries"][0]["id"] = "tests/../outside.py::test_reviewed"
        data["entries"][0]["source"]["path"] = "tests/../outside.py"
    else:
        catalog.write_text('{"format":1,"format":2}', encoding="utf-8")
        with pytest.raises(REPORT["ReportError"]):
            load(sample)
        return
    encode(catalog, data)
    encode(inventory, nodes)
    with pytest.raises(REPORT["ReportError"]):
        load(sample)


def test_atomic_generation_keeps_previous_html_on_failure_and_can_retry(sample, monkeypatch):
    root, _source, catalog, inventory = sample
    output = root / "build/report.html"
    output.parent.mkdir()
    output.write_text("previous complete report", encoding="utf-8")
    replace = REPORT["os"].replace
    with monkeypatch.context() as patch:

        def fail(*_args):
            raise OSError("synthetic disk failure")

        patch.setattr(REPORT["os"], "replace", fail)
        with pytest.raises(OSError):
            REPORT["write_report"](root, catalog, inventory, output)
    assert output.read_text(encoding="utf-8") == "previous complete report"
    assert list(output.parent.iterdir()) == [output]
    assert REPORT["os"].replace is replace
    REPORT["write_report"](root, catalog, inventory, output)
    assert "<!doctype html>" in output.read_text(encoding="utf-8")


@pytest.mark.parametrize("output", ["README.html", "build/catalog.json", "../report.html"])
def test_generation_cannot_overwrite_sources_or_leave_the_ignored_build_folder(sample, output):
    root, _source, catalog, inventory = sample
    with pytest.raises(REPORT["ReportError"]):
        REPORT["write_report"](root, catalog, inventory, root / output)
    assert not (root / "build").exists()


def test_cli_outputs_collection_counts_without_claiming_execution(sample, capsys):
    root, _source, catalog, inventory = sample
    assert (
        REPORT["main"](
            [
                "--root",
                str(root),
                "--catalog",
                str(catalog),
                "--inventory",
                str(inventory),
                "--language",
                "en",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["execution_status"] == "not_executed"
    assert output["documented_functions"] == 1 and output["needs_review"] == 0
    assert (root / "build/test-explanations.html").is_file()


@pytest.mark.parametrize("bad_field", ["source", "parameter_matrix"])
def test_wrong_descriptor_shapes_fail_as_validation_errors(sample, bad_field):
    _root, _source, catalog, _inventory = sample
    value = json.loads(catalog.read_text(encoding="utf-8"))
    value["entries"][0][bad_field] = []
    encode(catalog, value)
    with pytest.raises(REPORT["ReportError"]):
        load(sample)


def test_skipped_collection_is_visible_and_never_claimed_complete(sample):
    _root, _source, _catalog, inventory = sample
    value = json.loads(inventory.read_text(encoding="utf-8"))
    value["collection_skipped"] = 1
    encode(inventory, value)
    model = load(sample)
    assert model["collection_skipped"] == 1
    assert "Collection skipped files; this inventory is incomplete." in REPORT["render"](
        model, "en"
    )


def test_selected_inventory_cannot_be_mistaken_for_the_full_project(sample):
    _root, _source, _catalog, inventory = sample
    value = json.loads(inventory.read_text(encoding="utf-8"))
    value.update(collection_scope="selected", selection=["tests/test_reviewed.py"])
    encode(inventory, value)
    result = REPORT["render"](load(sample), "en")
    assert "Selected collection only: tests/test_reviewed.py" in result


@pytest.mark.parametrize(
    "field,value", [("collection_scope", []), ("selection", [1]), ("collection_skipped", True)]
)
def test_malformed_collection_scope_metadata_is_refused(sample, field, value):
    _root, _source, _catalog, inventory = sample
    data = json.loads(inventory.read_text(encoding="utf-8"))
    data[field] = value
    encode(inventory, data)
    with pytest.raises(REPORT["ReportError"]):
        load(sample)
