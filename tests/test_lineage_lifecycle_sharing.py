"""Ordinary list packages share current research, not removed private history."""

import json
import zipfile

import pytest
from test_lineage_bundle_journey import select
from test_lineage_jobs import work
from test_lineage_lifecycle import active as active
from test_research_lineage import corpus as corpus

from paper_daily import bundle, lineage_lifecycle, lineage_sets, store


def test_list_sharing_excludes_removed_analysis_actions_candidates_and_peer_originals(
    active, monkeypatch, tmp_path
):
    owner, row = active
    select(monkeypatch, owner.database)
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES('private','Fixture','fixture')")
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('private','focal',0,'fixture')"
        )
    from uuid import uuid4

    work(lineage_lifecycle.change, owner, row, request_id=str(uuid4()), action="retire")
    monkeypatch.setattr(bundle, "fetch", lambda *_a, **_k: pytest.fail("No sharing network"))
    output = tmp_path / "current-only.zip"
    bundle.export("private", output)
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        tables = json.loads(archive.read("tables.json"))
        assert not tables.get(lineage_sets.TABLE)
        assert not any(key.startswith("research_") for key in tables)
        assert not manifest.get("lineage_sources")
        assert not any(name.startswith("files/lineage-sources/") for name in archive.namelist())
        assert not tables["cited_papers"]
    assert len(work(lineage_lifecycle.history, owner)["items"]) == 1
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
