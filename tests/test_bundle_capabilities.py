"""Extended research packages must not silently lose source or deletion state."""

import json
import zipfile

import pytest
from test_annotation_archives import add
from test_annotation_archives import workspace as workspace_fixture

from paper_daily import bundle, reading_goals, store

workspace = workspace_fixture


def rewrite(source, target, change):
    with zipfile.ZipFile(source) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(files["manifest.json"])
    tables = json.loads(files["tables.json"])
    change(manifest, tables)
    files["manifest.json"] = json.dumps(manifest).encode()
    files["tables.json"] = json.dumps(tables).encode()
    with zipfile.ZipFile(target, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)


def test_goals_annotations_and_deletion_markers_declare_all_required_capabilities(workspace):
    root, database = workspace
    reading_goals.save(reading_goals.load(database, "l"), "Compare the evidence")
    with store.connect() as conn:
        add(conn, "research_questions")
    archive = root / "combined.zip"
    bundle.export("l", archive, with_pdfs=False)
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
    assert manifest["format"] == 2
    assert manifest["capabilities"] == [
        "annotation_deletions",
        "reading_annotations",
        "reading_goal",
    ]
    assert bundle.inspect(archive)["list_id"] == "l"


def test_deleted_annotation_without_any_goal_still_requires_new_reader(workspace):
    root, _database = workspace
    with store.connect() as conn:
        add(conn, "research_questions")
        conn.execute("DELETE FROM paper_research_questions WHERE paper_id='p'")
    archive = root / "deleted.zip"
    bundle.export("l", archive, with_pdfs=False)
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
    assert manifest["format"] == 2
    assert manifest["capabilities"] == ["annotation_deletions"]
    assert bundle.inspect(archive)["list_id"] == "l"


@pytest.mark.parametrize(
    "damage", ["old_format", "missing", "unknown", "duplicate", "missing_rows"]
)
def test_inconsistent_package_capabilities_fail_before_import(workspace, damage):
    root, database = workspace
    reading_goals.save(reading_goals.load(database, "l"), "Keep this purpose")
    with store.connect() as conn:
        add(conn, "research_questions")
    source, bad = root / "original.zip", root / "bad.zip"
    bundle.export("l", source, with_pdfs=False)

    def change(manifest, tables):
        if damage == "old_format":
            manifest["format"] = 1
        elif damage == "missing":
            manifest.pop("capabilities")
        elif damage == "unknown":
            manifest["capabilities"].append("unsupported_future_feature")
        elif damage == "duplicate":
            manifest["capabilities"].append("reading_goal")
        else:
            tables.pop("list_reading_goals")

    rewrite(source, bad, change)
    with pytest.raises(ValueError):
        bundle.import_(bad, replace=True, pdfs=False)
    assert reading_goals.text(reading_goals.load(database, "l")) == "Keep this purpose"
