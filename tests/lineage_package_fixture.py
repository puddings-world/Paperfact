"""Immutable actual sender ZIP per test module; receiver state stays per case."""

import json
import shutil
import zipfile

import pytest
from test_lineage_packages import export, package
from test_research_lineage import corpus


@pytest.fixture(scope="module")
def lineage_archive(tmp_path_factory):
    root = tmp_path_factory.mktemp("lineage-immutable-sender")
    # The underlying fixture is a plain corpus factory taking only its temp path.
    # Build once with the maintained real publication/export path and fake model.
    with pytest.MonkeyPatch.context() as patch:
        captured = corpus.__wrapped__(root)
        prepared = export(captured, patch)
        path = root / "sample.zip"
        package(prepared, path)
    return path


def copy_archive(source, destination):
    """Copy bytes and parse fresh metadata; no shared mutable object or receiver."""
    shutil.copyfile(source, destination)
    with zipfile.ZipFile(destination) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        tables = json.loads(archive.read("tables.json"))
    return manifest, tables
