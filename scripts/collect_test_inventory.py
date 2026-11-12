"""Collect pytest node identities without executing test functions."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


class Inventory:
    def __init__(self):
        self.nodes = []
        self.skipped = 0

    def pytest_collection_finish(self, session):
        self.nodes = [item.nodeid for item in session.items]

    def pytest_collectreport(self, report):
        if report.skipped:
            self.skipped += 1


def collect(root, output, *, selections=("tests",), execute=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    build = (root / "build").resolve()
    if (
        not build.is_relative_to(root)
        or not output.is_relative_to(build)
        or output.suffix != ".json"
    ):
        raise ValueError("Collection output must stay inside build")
    selected = []
    for selection in selections:
        path = (root / selection).resolve()
        if not path.is_relative_to(root / "tests") or not path.exists():
            raise ValueError("Select existing files or directories inside tests")
        selected.append(str(path))
    if not selected:
        raise ValueError("Select at least one test scope")
    if execute is None:
        import pytest

        execute = pytest.main
    source = root / "src"
    expected_package = source / "paper_daily" / "__init__.py"
    if expected_package.is_file():
        for name, module in list(sys.modules.items()):
            if name == "paper_daily" or name.startswith("paper_daily."):
                loaded = getattr(module, "__file__", None)
                if loaded is not None and not Path(loaded).resolve().is_relative_to(
                    source.resolve()
                ):
                    raise ValueError("Use a fresh interpreter to collect this checkout")
    plugin = Inventory()
    previous_path = list(sys.path)
    try:
        sys.path.insert(0, str(source))
        code = execute(
            [
                *selected,
                "--collect-only",
                "-q",
                "--color=no",
                "-p",
                "no:cacheprovider",
                "--rootdir",
                str(root),
            ],
            plugins=[plugin],
        )
    finally:
        sys.path[:] = previous_path
    if code:
        return int(code)
    nodes = plugin.nodes
    if len(nodes) != len(set(nodes)):
        raise ValueError("Collected duplicate test identities")
    functions = {node.split("[", 1)[0] for node in nodes}
    value = {
        "status": "collection only; no tests executed by this command",
        "node_count": len(nodes),
        "unique_test_functions": len(functions),
        "parameter_expansion_extra_cases": len(nodes) - len(functions),
        "test_files": len({node.split("::", 1)[0] for node in nodes}),
        "collection_skipped": plugin.skipped,
        "selection": [Path(value).relative_to(root).as_posix() for value in selected],
        "collection_scope": "full" if selected == [str(root / "tests")] else "selected",
        "nodes": nodes,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=output.parent, suffix=".tmp"
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("build/test-inventory.json"))
    parser.add_argument("--tests", nargs="+", default=["tests"])
    options = parser.parse_args(argv)
    root = options.root.resolve()
    try:
        return collect(root, root / options.output, selections=options.tests)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Test collection failed: {type(exc).__name__}.\n")


if __name__ == "__main__":
    raise SystemExit(main())
