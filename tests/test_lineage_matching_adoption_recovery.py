"""Adopted native science remains complete without restoring active identities."""

import json
import sqlite3
import zipfile
from contextlib import closing

from test_lineage_jobs import work
from test_lineage_matching_adoption import codec as codec
from test_lineage_matching_adoption import corpus as corpus
from test_lineage_matching_adoption import legacy as legacy
from test_lineage_matching_adoption import native_shared as native_shared
from test_lineage_matching_adoption import pair as pair
from test_lineage_matching_adoption import planned
from test_lineage_matching_adoption import shared as shared
from test_sync_recovery import archive_rows

from paper_daily import lineage_projection, lineage_sets, sync_recovery


def test_adopted_science_and_all_originals_survive_independent_detached_recovery(
    legacy, native_shared, tmp_path
):
    client, importer, _archive, _receipt, row, review = legacy
    work(importer.apply, planned(legacy)[0])
    output = tmp_path / "adopted-research.zip"
    before = client.journal.path.read_bytes()
    manifest = sync_recovery.create(client.journal.path, output, blob_store=importer.store)
    assert sync_recovery.inspect(output) == manifest
    assert client.journal.path.read_bytes() == before
    assert row in archive_rows(output, lineage_sets.TABLE)
    histories = archive_rows(output, lineage_projection.HISTORY)
    assert len([item for item in histories if item["entity_id"] == review.conflicts[0]["id"]]) == 1
    original = json.loads(native_shared[3][0]["body_json"])
    exact = {
        source["document_hash"]: native_shared[2][binding["paper_id"]]
        for source, binding in zip(original["report"]["sources"], original["bindings"], strict=True)
    }
    assert len(exact) == 3
    with zipfile.ZipFile(output) as archive:
        for digest, data in exact.items():
            assert archive.read("objects/" + digest) == data
    destination = tmp_path / "detached-adopted-research"
    sync_recovery.restore_detached(output, destination)
    database = destination / "papers.db"
    assert row in lineage_sets.saved(database, row["paper_id"])
    with closing(sqlite3.connect(database)) as conn:
        tables = {
            item[0] for item in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert (
            not {
                "paperfact_sync_identity",
                lineage_projection.TABLE,
                "research_lineage_sync_sources",
            }
            & tables
        )
    for digest, data in exact.items():
        assert (destination / "objects" / digest).read_bytes() == data
