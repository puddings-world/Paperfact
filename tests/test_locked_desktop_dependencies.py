"""Fresh desktop installations resolve the declared, locked dependencies."""
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def test_declared_desktop_dependencies_are_in_the_lock_and_satisfy_constraints():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    package = next(item for item in lock["package"] if item.get("source") == {"editable": "."})
    requirements = [Requirement(raw) for raw in project["optional-dependencies"]["app"]]
    assert {canonicalize_name(row["name"]) for row in package["optional-dependencies"]["app"]} == {
        canonicalize_name(requirement.name) for requirement in requirements
    }
    for requirement in requirements:
        releases = [item for item in lock["package"]
                    if canonicalize_name(item["name"]) == canonicalize_name(requirement.name)]
        assert releases, requirement.name
        assert all(requirement.specifier.contains(item["version"], prereleases=True)
                   for item in releases), requirement.name
