"""Installation links and command examples must lead to usable local entry points."""

import re
from pathlib import Path

import pytest

from paper_daily import cli

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("document", ["README.md", "docs/install.md", "docs/cli-reference.md"])
def test_installation_navigation_has_no_missing_local_targets(document):
    source = ROOT / document
    for link in re.findall(r"\]\(([^)]+)\)", source.read_text(encoding="utf-8")):
        if "://" in link or link.startswith("#"):
            continue
        assert (source.parent / link.split("#", 1)[0]).exists(), (document, link)


@pytest.mark.parametrize("args", [
    ["app"], ["doctor"], ["lists"], ["list-export", "my-list", "-o", "research.zip"],
    ["list-import", "research.zip"], ["analyze", "--list", "my-list", "--retry"],
])
def test_documented_common_commands_are_accepted_without_running_them(args):
    parsed = cli.build_parser().parse_args(args)
    assert callable(parsed.func)
