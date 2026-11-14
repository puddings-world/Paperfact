"""Bound source ownership is checked without copying its graph/native receipts."""

import json
from uuid import uuid4

import pytest
from test_lineage_observation import work
from test_lineage_packages import package
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import frame_for, project

from paper_daily import lineage_packages as packages


def staged(selected):
    client = selected[0][1]
    frame, operations = frame_for(selected)
    work(project, client, frame)
    focal = json.loads(selected[1]._json)["observed"][0]["local_id"]
    return client, focal, operations


def test_bound_sources_pack_without_outbox_changes_or_sender_authority(selected, tmp_path):
    client, focal, _operations = staged(selected)
    before = client.journal.pending(), client.journal.path.read_bytes()
    prepared = work(packages.collect, client.journal.path, [focal])
    manifest, tables = package(prepared, tmp_path / "bound.zip", focal_ids=[focal])
    import zipfile

    with zipfile.ZipFile(tmp_path / "bound.zip") as archive:
        assert packages.validate_package(archive, manifest, tables) == prepared.rows
        raw = archive.read("manifest.json") + archive.read("tables.json")
        for forbidden in [b"incarnation", b"device_id", b"operation_id", b"source_dependencies"]:
            assert forbidden not in raw
    assert (client.journal.pending(), client.journal.path.read_bytes()) == before
    work(packages.check_export, prepared)


def test_same_bytes_source_restore_never_reauthorizes_prepared_export(selected):
    client, focal, operations = staged(selected)
    prepared = work(packages.collect, client.journal.path, [focal])
    old = next(iter(operations.values()))
    with client.journal.transaction() as conn:
        deleted = client.new_graph_operation_in(
            conn, "research_file", old["entity_id"], {}, action="delete"
        )
        client.journal.apply_in(conn, deleted, client.writer)
        restored = client.new_graph_operation_in(
            conn,
            "research_file",
            old["entity_id"],
            old["payload"],
            operation_id=str(uuid4()),
            restore=True,
        )
        client.journal.apply_in(conn, restored, client.writer)
    assert restored["incarnation"] != old["incarnation"]
    before = client.journal.pending()
    with pytest.raises(ValueError, match="ownership changed"):
        work(packages.check_export, prepared)
    with pytest.raises(ValueError, match="lifetime changed"):
        work(packages.collect, client.journal.path, [focal])
    assert client.journal.pending() == before
