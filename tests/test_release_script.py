"""scripts/release.py: the version it writes is the one the app and the build read."""

import importlib.util
from pathlib import Path

import pytest

from paper_daily import __version__, updates

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release.py"
spec = importlib.util.spec_from_file_location("release_script", SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_the_version_line_is_replaced_and_nothing_else():
    text = '"""Doc."""\r\n\r\n__version__ = "0.1.0"\r\n'
    assert release.set_version(text, "0.2.0") == '"""Doc."""\r\n\r\n__version__ = "0.2.0"\r\n'


def test_versions_compare_as_numbers():
    assert release.parse("0.10.0") > release.parse("0.9.3")
    with pytest.raises(SystemExit):
        release.parse("v0.2")


def test_the_package_version_is_one_the_update_check_understands():
    assert updates.parse_version(__version__) is not None
    assert release.VERSION_LINE.search(release.INIT.read_text(encoding="utf-8"))
