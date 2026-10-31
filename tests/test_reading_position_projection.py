"""Snapshots preserve exact declared originals without inventing local byte proof."""

import hashlib
import json
import sqlite3
from contextlib import closing

import pytest
from test_reading_positions import bound as _bound
from test_reading_positions import loaded as _loaded
from test_reading_positions import prepared

from paper_daily import reading_position_ops as operations
from paper_daily import sync_projection

bound, loaded = _bound, _loaded


def snapshot(client, **kwargs):
    return sync_projection.read_manifest(
        client.journal.path, workspace_id="workspace", schema_version=2, **kwargs
    )


def test_exact_original_A_and_current_B_remain_distinct_read_only_snapshot(loaded):
    client, path, native = loaded
    operations.save(prepared(native))
    original = path.read_bytes()
    position = next(
        op
        for op in client.journal.pending()
        if op.get("payload", {}).get("feature") == "reading_position"
    )
    paper = position["payload"]["scope"]["id"]
    client.save(
        client.new_graph_operation(
            "paper_document",
            paper,
            dict(paper_id=paper, sha256="b" * 64, size=20, media_type="application/pdf"),
        )
    )
    before = client.journal.path.read_bytes()
    result = snapshot(client)
    assert client.journal.path.read_bytes() == before
    assert result["required_capabilities"] == ["reading_position"]
    (row,) = result["reading_positions"]
    assert (row["paper_id"], row["document_hash"], row["page"], row["method"]) == (
        paper,
        hashlib.sha256(original).hexdigest(),
        3,
        "entered",
    )
    assert row["source"]["manifest"]["slot"] == native.fingerprint
    assert row["source"]["parents"] == position["parents"]
    assert {asset["sha256"] for asset in result["assets"]} == {native.fingerprint, "b" * 64}
    assert all(asset["availability"] == "unchecked" for asset in result["assets"])
    assert result["papers"][0]["pdf_asset_id"] == "sha256:" + "b" * 64
    serialized = json.dumps(result)
    assert str(path) not in serialized and "owner_json" not in serialized
    assert original == path.read_bytes()
    with pytest.raises(ValueError, match="Source-bound reading positions are not supported"):
        sync_projection.read_manifest(client.journal.path, workspace_id="workspace")


@pytest.mark.parametrize("change", ["missing", "deleted", "wrong_owner", "stale_parent"])
def test_incomplete_or_retired_original_refuses_without_omitting_position(loaded, change):
    client, _path, native = loaded
    operations.save(prepared(native))
    with closing(sqlite3.connect(client.journal.path)) as conn, conn:
        raw = conn.execute("SELECT entity_id,operation FROM research_file_desired").fetchone()
        if change == "missing":
            conn.execute("DELETE FROM research_file_desired WHERE entity_id=?", (raw[0],))
        elif change == "deleted":
            conn.execute("UPDATE research_file_desired SET active=0")
        else:
            op = json.loads(raw[1])
            if change == "wrong_owner":
                op["payload"]["paper_id"] = "11111111-1111-4111-8111-111111111111"
            else:
                op["parents"][0]["incarnation"] = "stale-paper"
            conn.execute("UPDATE research_file_desired SET operation=?", (json.dumps(op),))
    before = client.journal.path.read_bytes()
    with pytest.raises(ValueError, match="Source-bound reading positions are not supported"):
        snapshot(client)
    assert client.journal.path.read_bytes() == before
    with closing(sqlite3.connect(client.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM reading_positions").fetchone()[0] == 1


def test_snapshot_bounds_count_positions_and_sources(loaded):
    client, _path, native = loaded
    operations.save(prepared(native))
    with pytest.raises(ValueError, match="record limit"):
        snapshot(client, max_records=1)
    with pytest.raises(ValueError, match="byte limit"):
        snapshot(client, max_bytes=10)
